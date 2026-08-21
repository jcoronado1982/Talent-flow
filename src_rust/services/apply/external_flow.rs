use super::application_flow::{applied_update, FlowResult};
use super::dom;
use super::form::{fill_form, JobContext};
use super::resume_manager::ResumeManager;
use crate::db::{DatabaseRepository, JobStatusUpdate};
use crate::domain::models::SkillInfo;
use crate::services::AiClient;
use anyhow::Result;
use chromiumoxide::Page;
use std::collections::HashMap;

// Ordered most-specific first: matching is a substring test, so the bare "Apply"/"Solicitar"
// entries must come last or they would swallow the more precise variants.
// NOTE: the bare entries were missing entirely, and every label here is a phrase — since the
// test is `buttonText.includes(label)`, a button labelled exactly "Apply" matched none of
// them ("apply".includes("apply now") === false). BairesDev's ATS labels its button exactly
// "Apply", so the flow reported no Apply button while one sat visible on the page.
const APPLY_LABELS: &[&str] = &[
    "Apply for this job",
    "Apply on company site",
    "Apply Now",
    "Enviar mi CV",
    "Postularse",
    "Postulate",
    "Join us",
    "Apply",
    "Solicitar",
];
const SUBMIT_LABELS: &[&str] = &["Submit application", "Submit", "Enviar solicitud", "Finalizar postulación"];
const NEXT_LABELS: &[&str] = &["Next", "Continue", "Siguiente", "Continuar"];
const SUCCESS_INDICATORS: &[&str] = &[
    "application submitted",
    "thank you for applying",
    "thank you for your application",
    "thanks for applying",
    "success",
    "¡gracias!",
    "gracias por postular",
    "recibimos tu solicitud",
    "tu solicitud ha sido enviada",
    "solicitud recibida",
    "application received",
    "submitted successfully",
    "has been submitted",
    "applied",
    "congratulations",
    "enviado con éxito",
];
const GUEST_BYPASS_LABELS: &[&str] = &[
    "Apply without an account", "Continue as guest", "Guest checkout", "Apply as guest",
    "Skip and apply", "Aplicar sin cuenta", "Continuar como invitado", "Postular sin registrarme",
];
// Chrome runs the persistent, already-authenticated profile (see services/browser.rs), so an
// OAuth "with Google" control is always faster and more reliable than hand-filling a signup/
// registration form: no email/password to invent, no email-verification step to get stuck on.
// Checked first, every step, ahead of any manual form fill — mirrors the priority the user
// asked for after watching the bot fill a registration form that had a Google button sitting
// right on it while the browser was already signed in.
const GOOGLE_AUTH_LABELS: &[&str] = &[
    "Continue with Google",
    "Sign up with Google",
    "Sign in with Google",
    "Log in with Google",
    "Apply with Google",
    "Register with Google",
    "Continuar con Google",
    "Regístrate con Google",
    "Registrarse con Google",
    "Iniciar sesión con Google",
    "Iniciar sesion con Google",
    "Aplicar con Google",
];

/// Takes control of an external ATS tab (Workday/Greenhouse/Lever/etc.) opened after
/// clicking LinkedIn's "Apply" button, and tries to complete the application.
/// Mirrors src/app/bots/apply/external_flow.py::ExternalFlow.handle_external_application.
pub async fn handle_external_application(
    page: &Page,
    db: &DatabaseRepository,
    ai_client: &AiClient,
    resume_manager: &ResumeManager,
    ctx: &mut JobContext,
    profile_skills: &HashMap<String, HashMap<String, SkillInfo>>,
    dry_run: bool,
) -> Result<FlowResult> {
    let url = page.url().await.ok().flatten().unwrap_or_default();
    println!("   🚀 Starting External Engine (AI Model: {}) for: {}", ai_client.gemini_model(), url);
    let _ = db.update_job_status(ctx.id, &JobStatusUpdate::new("Applying").error(format!("External Flow: {}", url)));

    const MAX_STEPS: u32 = 8;
    // Cap Google-auth clicks so a persistent header/nav "Sign in with Google" link (unrelated to
    // the actual application flow) can't get clicked every single step and burn all MAX_STEPS
    // without the bot ever reaching the real form. 2 attempts covers the legitimate two-click
    // flow (initial button + account picker if it redirects back to the same page).
    const MAX_GOOGLE_AUTH_ATTEMPTS: u32 = 2;
    let mut google_auth_attempts = 0u32;

    // Give a client-rendered ATS time to mount its form before concluding there isn't one.
    let initial = dom::wait_for_form_inputs(page, 2, std::time::Duration::from_secs(20)).await;
    println!("      [External] Campos detectados tras esperar hidratación: {}", initial);

    for step in 1..=MAX_STEPS {
        let _ = page.evaluate("window.scrollTo(0, 500)").await;

        if google_auth_attempts < MAX_GOOGLE_AUTH_ATTEMPTS && dom::click_by_text(page, GOOGLE_AUTH_LABELS).await? {
            google_auth_attempts += 1;
            println!("      [External] 🔵 Paso {}: botón de Google detectado — usando la sesión ya autenticada en vez de llenar el registro a mano.", step);
            tokio::time::sleep(std::time::Duration::from_secs(2)).await;
            if check_success(page).await {
                println!("      🎉 [External] La autenticación con Google completó la postulación de inmediato.");
                let _ = db.update_job_status(ctx.id, &applied_update(ctx).error("Autenticado y postulado vía Google OAuth (sesión ya iniciada)."));
                return Ok(FlowResult::Submitted);
            }
            // Google auth suele redirigir al formulario real, que puede montarse por JS.
            // Esperamos a que aparezcan campos en vez de asumir que 3 s bastan.
            dom::wait_for_form_inputs(page, 2, std::time::Duration::from_secs(12)).await;
            continue; // Re-read the page fresh next iteration.
        }

        let mut on_form = dom::count_form_inputs(page).await >= 2;
        if !on_form {
            println!("      [External] Step {}: buscando botón Apply...", step);
            if dom::click_by_text(page, APPLY_LABELS).await? {
                // Asentamiento corto para descartar rápido el caso de "un solo clic"
                // (botones Apply que ya envían la postulación y no abren formulario).
                tokio::time::sleep(std::time::Duration::from_secs(1)).await;

                // Some ATS "Apply Now" buttons are themselves a one-click submit (no
                // further form) — verify before assuming we just navigated to a form.
                if check_success(page).await {
                    println!("      [External] ⚠️ El botón 'Apply' parece haber enviado la aplicación de inmediato (sin formulario adicional).");
                    let _ = db.update_job_status(ctx.id, &applied_update(ctx).error("El sitio externo confirmó envío inmediato tras el botón Apply (aplicación de un clic)."));
                    return Ok(FlowResult::Submitted);
                }

                // Espera adaptativa en vez de un sleep fijo: muchos ATS redirigen y montan el
                // formulario por JS, y con 2 s fijos se concluía "aquí no hay formulario" y se
                // quemaba el paso entero buscando otro botón Apply que ya no existía. Devuelve
                // apenas aparecen los campos, así que un sitio rápido no paga la espera.
                let found = dom::wait_for_form_inputs(page, 2, std::time::Duration::from_secs(12)).await;
                on_form = found >= 2;
                if on_form {
                    println!("      [External] Formulario encontrado tras clic en Apply ({} campos).", found);
                }
            }
        }

        if on_form && dom::looks_like_login_wall(page).await {
            println!("      [External] 🔒 Muro de login/cuenta detectado. Buscando opción de aplicar sin cuenta...");
            if dom::click_by_text(page, GUEST_BYPASS_LABELS).await? {
                tokio::time::sleep(std::time::Duration::from_secs(2)).await;
                on_form = dom::count_form_inputs(page).await >= 2;
                if on_form && dom::looks_like_login_wall(page).await {
                    on_form = false; // Bypass didn't actually clear the wall.
                }
            } else {
                on_form = false;
            }

            if !on_form {
                // Don't stop here on a hardcoded guess: the "guest bypass" label list is the
                // same brittle pattern that failed everywhere else. Let the agent look at the
                // actual page — it may find a route the list never knew about.
                println!("      [External] 🔒 Muro de login sin bypass conocido. Relevo al agente...");
                return handover_to_agent(page, db, ai_client, resume_manager, ctx, dry_run).await;
            }
        }

        if on_form {
            if ctx.actual_resume.is_none() {
                if let Ok(Some(name)) = resume_manager.smart_upload_resume(page, &ctx.target_resume).await {
                    ctx.actual_resume = Some(name);
                }
            }

            if let Ok(result) = fill_form(page, ai_client, resume_manager, ctx, profile_skills, false).await {
                if !result.needs_human.is_empty() {
                    let reasons = result.needs_human.join(" | ");
                    println!("      🤖 [External] Campo con widget personalizado ({}). Relevo inmediato al Agente Inteligente...", reasons);
                    return handover_to_agent(page, db, ai_client, resume_manager, ctx, dry_run).await;
                }
            }

            if dry_run {
                println!("      🛡️ [External][SHADOW] Formulario externo auditado en el paso {} — deteniendo aquí, nunca se hace clic en Submit/Next en modo dry-run.", step);
                let _ = db.update_job_status(
                    ctx.id,
                    &JobStatusUpdate::new("Matched").error(format!("Shadow mode (externo): paso {} auditado, no se envió nada.", step)),
                );
                return Ok(FlowResult::Debug);
            }

            if dom::click_by_text(page, SUBMIT_LABELS).await? {
                println!("      [External] Clic en 'Submit / Enviar solicitud'. Verificando confirmación...");
                tokio::time::sleep(std::time::Duration::from_secs(3)).await;
                if check_success(page).await {
                    println!("      🎉 [External] ¡Postulación externa completada y confirmada con éxito!");
                    let _ = db.update_job_status(ctx.id, &applied_update(ctx).error("Postulación enviada en portal externo exitosamente."));
                    return Ok(FlowResult::Submitted);
                }
                println!("      [External] Sin mensaje final todavía, continuando con pasos siguientes...");
            } else if dom::click_by_text(page, NEXT_LABELS).await? {
                println!("      ➡️ [External] Paso {} completado. Clic en 'Next / Siguiente' para continuar...", step);
                tokio::time::sleep(std::time::Duration::from_millis(800)).await;
                if check_success(page).await {
                    println!("      🎉 [External] ¡Postulación externa completada y confirmada!");
                    let _ = db.update_job_status(ctx.id, &applied_update(ctx).error("Postulación enviada en portal externo exitosamente."));
                    return Ok(FlowResult::Submitted);
                }
                // El paso siguiente del asistente suele montar sus campos por JS tras la
                // transición; esperamos a que aparezcan en vez de dar por perdido el paso.
                dom::wait_for_form_inputs(page, 2, std::time::Duration::from_secs(10)).await;
                continue;
            }
        }

        tokio::time::sleep(std::time::Duration::from_millis(1000)).await;
    }

    // Record what the external page actually showed
    dom::dump_apply_button_diagnostics(page).await;

    println!("      🤖 [External] El flujo determinista completó sus pasos. Relevo al agente inteligente...");
    handover_to_agent(page, db, ai_client, resume_manager, ctx, dry_run).await
}

/// Hands control to the Gemini agent.
///
/// The deterministic flow above can only recognise the control names someone thought to
/// list; the agent reads whatever is actually on screen and decides for itself, which is the
/// only approach that generalises across the thousands of ATS products in the wild.
async fn handover_to_agent(
    page: &Page,
    db: &DatabaseRepository,
    ai_client: &AiClient,
    resume_manager: &ResumeManager,
    ctx: &mut JobContext,
    dry_run: bool,
) -> Result<FlowResult> {
    let profile_yaml = resume_manager.build_profile_yaml(Some(&ctx.location));
    match super::agent::run_agent(page, ai_client, resume_manager, ctx, &profile_yaml, dry_run, 18).await {
        Ok(super::agent::AgentOutcome::Submitted(reason)) => {
            println!("      🎉 [Agente] Postulación enviada y confirmada: {}", reason);
            let _ = db.update_job_status(ctx.id, &applied_update(ctx).error(format!("Enviado por el agente: {}", reason)));
            Ok(FlowResult::Submitted)
        }
        Ok(super::agent::AgentOutcome::NeedsHuman(reason)) => {
            println!("      ⚠️ [Agente] Se detiene: {}", reason);
            let _ = db.update_job_status(
                ctx.id,
                &JobStatusUpdate::new("Manual")
                    .external_link(page.url().await.ok().flatten().unwrap_or_default())
                    .error(format!("Agente: {}", reason)),
            );
            Ok(FlowResult::Manual)
        }
        Ok(super::agent::AgentOutcome::Exhausted) => {
            let _ = db.update_job_status(ctx.id, &JobStatusUpdate::new("Manual").error("El agente agotó sus pasos sin completar la postulación."));
            Ok(FlowResult::Manual)
        }
        Err(e) => {
            let _ = db.update_job_status(ctx.id, &JobStatusUpdate::new("Manual").error(format!("Error del agente: {}", e)));
            Ok(FlowResult::Manual)
        }
    }
}

async fn check_success(page: &Page) -> bool {
    for indicator in SUCCESS_INDICATORS {
        if dom::text_visible_on_page(page, indicator).await {
            return true;
        }
    }
    false
}
