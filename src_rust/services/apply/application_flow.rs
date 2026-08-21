use super::dom;
use super::form::{fill_form, JobContext};
use super::resume_manager::ResumeManager;
use crate::db::{DatabaseRepository, JobStatusUpdate};
use crate::domain::models::SkillInfo;
use crate::services::AiClient;
use anyhow::Result;
use chromiumoxide::Page;
use std::collections::HashMap;
use std::path::Path;

pub(super) fn applied_update(ctx: &JobContext) -> JobStatusUpdate {
    // Never silently substitute the INTENDED filename here — incident 2026-08-18 was
    // exactly this: the DB said the correct CV was used while LinkedIn had actually
    // kept a different, stale one attached. Record only what was verified, and say so
    // plainly when it wasn't.
    let resume = ctx.actual_resume.clone().unwrap_or_else(|| "SIN VERIFICAR — no se confirmó qué CV quedó adjunto".to_string());
    let mut update = JobStatusUpdate::new("Applied").uploaded_cv(resume);
    if let Some(s) = &ctx.applied_salary { update = update.salary(s.clone()); }
    if let Some(c) = &ctx.applied_currency { update = update.currency(c.clone()); }
    update
}

#[derive(Debug, Clone, PartialEq)]
pub enum FlowResult {
    Submitted,
    Manual,
    Stopped,
    /// Shadow/dry-run mode: form was filled but Submit was intentionally not clicked.
    Debug,
}

/// Drives the "Easy Apply" modal step by step: upload resume, fill the current step,
/// then look for Submit/Next/Done. Mirrors
/// src/app/bots/apply/application_flow.py::ApplicationFlow.handle_application_flow.
///
/// Note: unlike the Python version (which does a physical mouse-jitter click for
/// anti-bot evasion), this port clicks via the DOM directly (`element.click()` through
/// CDP), the same interaction style already used by the Rust search scraper.
pub async fn handle_application_flow(
    page: &Page,
    db: &DatabaseRepository,
    ai_client: &AiClient,
    resume_manager: &ResumeManager,
    ctx: &mut JobContext,
    profile_skills: &HashMap<String, HashMap<String, SkillInfo>>,
    dry_run: bool,
    stop_signal_path: &Path,
) -> Result<FlowResult> {
    const MAX_STEPS: u32 = 15;
    let submit_labels = ["Submit application", "Enviar solicitud", "Postularse"];
    // NOTE (incident 2026-08-18): "Review" turned out to be the FINAL action button on
    // at least one real LinkedIn Easy Apply flow — clicking it during a dry-run test
    // submitted a real application, because only submit_labels was gated behind
    // `dry_run`. Label-based "is this the last step?" detection is provably unreliable
    // against LinkedIn's current markup, so dry-run no longer trusts it AT ALL: it fills
    // one step and stops, full stop, never clicking anything in next_labels/done_labels.
    let next_labels = ["Continue to next step", "Next", "Siguiente", "Continue", "Review", "Revisar"];
    let done_labels = ["Done", "Hecho", "Finalizar"];

    let mut empty_steps_in_a_row = 0u32;
    let mut last_fingerprint: Option<String> = None;

    for step in 1..=MAX_STEPS {
        if stop_signal_path.exists() {
            println!("🛑 Stop signal detected in flow. Terminating...");
            return Ok(FlowResult::Stopped);
        }

        tokio::time::sleep(std::time::Duration::from_millis(800)).await;

        // 1. Upload resume, then verify by reading back what LinkedIn's UI actually
        // shows as attached — never trust smart_upload_resume's return value alone.
        // (Incident 2026-08-18: LinkedIn kept a stale previously-attached resume from
        // an earlier test session and the upload call reported success anyway.)
        if ctx.actual_resume.is_none() {
            let target_name = ctx.target_resume.file_name().map(|f| f.to_string_lossy().to_string()).unwrap_or_default();
            let _ = resume_manager.smart_upload_resume(page, &ctx.target_resume).await;
            tokio::time::sleep(std::time::Duration::from_millis(500)).await;

            match dom::read_attached_resume_filename(page).await {
                Some(attached) if attached == target_name => {
                    println!("   ✅ CV verificado: LinkedIn muestra adjunto exactamente '{}'.", attached);
                    ctx.actual_resume = Some(attached.clone());
                    crate::services::audit::log_audit_event(
                        "PASO_5_APPLY_SUPERVISOR",
                        &format!("Verificación de CV Adjunto: {} @ {}", ctx.role, ctx.company),
                        "OK",
                        "CV_ATTACHED_CONFIRMED",
                        &format!("El DOM de LinkedIn muestra exactamente el CV solicitado: '{}'", attached),
                        None,
                        None,
                        "Continuando con el llenado de campos.",
                        "El supervisor verificó que LinkedIn no usó un CV antiguo de la cuenta."
                    );
                }
                Some(attached) => {
                    println!("   ⚠️ CV incorrecto detectado: se buscaba '{}' pero LinkedIn muestra '{}'. Reintentando subida...", target_name, attached);
                    let _ = resume_manager.smart_upload_resume(page, &ctx.target_resume).await;
                    tokio::time::sleep(std::time::Duration::from_millis(800)).await;
                    let recheck = dom::read_attached_resume_filename(page).await;
                    match recheck {
                        Some(ref a) if *a == target_name => {
                            println!("   ✅ Reintento exitoso: ahora está adjunto '{}'.", a);
                            ctx.actual_resume = Some(target_name);
                        }
                        Some(a) => {
                            println!("   ❌ El CV adjunto sigue siendo el incorrecto ('{}'). Se dejará constancia en el registro.", a);
                            ctx.actual_resume = Some(format!("{} (INCORRECTO — se buscaba {})", a, target_name));
                        }
                        None => {
                            ctx.actual_resume = Some("SIN VERIFICAR — no se pudo leer el CV adjunto tras reintento".to_string());
                        }
                    }
                }
                None => {
                    println!("   ⚠️ No se pudo leer qué CV está adjunto en la página (aún sin verificar).");
                }
            }
        }

        // 2. Fill current step
        let _ = db.update_job_status(ctx.id, &JobStatusUpdate::new("Applying").error(format!("Step {}: Filling form...", step)));
        let fields_found = match fill_form(page, ai_client, resume_manager, ctx, profile_skills, true).await {
            Ok(result) => {
                if let Some(s) = result.captured.get("salary") { ctx.applied_salary = Some(s.clone()); }
                if let Some(c) = result.captured.get("currency") { ctx.applied_currency = Some(c.clone()); }
                if !result.needs_human.is_empty() {
                    let reasons = result.needs_human.join(" | ");
                    println!("   🛑 Campo(s) sin resolver con confianza, deteniendo antes de avanzar: {}", reasons);
                    crate::services::audit::log_audit_event(
                        "PASO_5_APPLY_SUPERVISOR",
                        &format!("Formulario Requiere Intervención: {} @ {}", ctx.role, ctx.company),
                        "MANUAL",
                        "UNRESOLVED_FORM_FIELDS",
                        &reasons,
                        None,
                        None,
                        "Postulación detenida y enviada a cola Manual.",
                        "El supervisor impidió enviar respuestas inventadas o no seguras."
                    );
                    let _ = db.update_job_status(ctx.id, &JobStatusUpdate::new("Manual").error(format!("Campo(s) sin resolver: {}", reasons)));
                    return Ok(FlowResult::Manual);
                }

                // Loop guard: if this step looks identical to the previous one, the last
                // "Next" click did not actually advance the form (LinkedIn is refusing,
                // or the click landed on a decoy). Stop instead of re-scanning the same
                // step until MAX_STEPS, which is what happened live for 15 iterations.
                if !result.fingerprint.is_empty() && Some(&result.fingerprint) == last_fingerprint.as_ref() {
                    println!("   🛑 El formulario no avanzó tras el clic anterior (mismo paso otra vez). Deteniendo.");
                    let _ = db.update_job_status(
                        ctx.id,
                        &JobStatusUpdate::new("Manual").error("El formulario no avanza: el mismo paso se repite tras hacer clic en Siguiente (probable campo obligatorio sin llenar)."),
                    );
                    return Ok(FlowResult::Manual);
                }
                last_fingerprint = Some(result.fingerprint.clone());
                true
            }
            Err(e) => {
                println!("   ⚠️ Error autofilling: {}", e);
                false
            }
        };

        // 3. Blocking validation error. This is now a hard stop, not just a log line:
        // an unfilled required field is precisely what makes LinkedIn silently refuse to
        // advance, and continuing to click "Next" past it is what produced the 15-step
        // loop. Better to hand the job to a human with the exact message than to spin.
        if let Some(msg) = dom::visible_error_message(page).await {
            println!("   🛑 [Flow] LinkedIn reporta un error de validación: {}", msg);
            let _ = db.update_job_status(ctx.id, &JobStatusUpdate::new("Manual").error(format!("Error de validación en el formulario: {}", msg)));
            return Ok(FlowResult::Manual);
        }

        if dry_run {
            println!("🛡️ [SHADOW MODE] Paso {} auditado (llenado sin enviar). Deteniendo aquí — el modo dry-run nunca hace clic en Submit/Next/Review/Done.", step);
            crate::services::audit::log_audit_event(
                "PASO_5_APPLY_SUPERVISOR",
                &format!("Auditoría Dry-Run: {} @ {}", ctx.role, ctx.company),
                "OK",
                "FORM_AUDITED_NO_SUBMIT",
                &format!("Formulario llenado con éxito en modo simulación (Paso {}). Cero envíos realizados.", step),
                None,
                None,
                "Formulario cerrado y sesión liberada limpiamente.",
                "Modo auditoría completado bajo supervisión estricta."
            );
            let _ = db.update_job_status(ctx.id, &JobStatusUpdate::new("Matched").error(format!("Shadow mode: paso {} auditado, no se envió nada.", step)));
            return Ok(FlowResult::Debug);
        }

        // 4. Submit-ready?
        if dom::button_visible(page, &submit_labels).await {
            println!("⚠️ Ejecutando clic de ENVIAR APLICACIÓN definitiva...");
            if dom::click_by_text(page, &submit_labels).await? {
                return Ok(finalize_after_click(page, db, ctx).await);
            }
        }

        // 5. Next/Review
        if dom::click_by_text(page, &next_labels).await? {
            println!("      ➡️  Next/Review click ejecutado (paso {}).", step);
            empty_steps_in_a_row = 0;
            continue;
        }

        // 6. Success text visible without an explicit Submit click (some flows auto-advance).
        if dom::text_visible_on_page(page, "application sent").await || dom::text_visible_on_page(page, "solicitud enviada").await {
            let _ = db.update_job_status(ctx.id, &applied_update(ctx).error("Confirmado: texto de éxito visible en la página."));
            return Ok(FlowResult::Submitted);
        }

        // Done/Finish
        if dom::click_by_text(page, &done_labels).await? {
            return Ok(finalize_after_click(page, db, ctx).await);
        }

        println!("   ❓ No actionable buttons found. Wait...");

        // Nothing detected AND nothing clickable, twice in a row: the modal most likely
        // closed on its own (which — per the incident above — can mean it silently
        // submitted). Stop looping and go verify against LinkedIn's own confirmation
        // instead of burning through all MAX_STEPS on a dead page.
        if !fields_found {
            empty_steps_in_a_row += 1;
            if empty_steps_in_a_row >= 2 {
                println!("   🔎 El modal parece haberse cerrado. Verificando el resultado real contra LinkedIn...");
                return Ok(verify_against_job_page(page, db, ctx).await);
            }
        }
    }

    Ok(verify_against_job_page(page, db, ctx).await)
}

/// After clicking something that looked like the final action, don't just trust it —
/// poll for the site's own confirmation modal and keep it visible so the human user can see it.
async fn finalize_after_click(page: &Page, db: &DatabaseRepository, ctx: &JobContext) -> FlowResult {
    println!("   ⏳ Esperando confirmación de envío por parte de LinkedIn...");
    
    // 1. Sondeo adaptativo de hasta 6s para dar tiempo a la animación y respuesta de red
    let mut immediate_confirmation = false;
    let start_wait = std::time::Instant::now();
    while start_wait.elapsed() < std::time::Duration::from_secs(6) {
        tokio::time::sleep(std::time::Duration::from_millis(400)).await;
        if dom::text_visible_on_page(page, "application sent").await
            || dom::text_visible_on_page(page, "solicitud enviada").await
            || dom::text_visible_on_page(page, "your application was sent").await
            || dom::text_visible_on_page(page, "aplicación enviada").await
            || dom::text_visible_on_page(page, "candidatura enviada").await
            || dom::text_visible_on_page(page, "postulación enviada").await
            || dom::text_visible_on_page(page, "sua candidatura foi enviada").await
            || dom::text_visible_on_page(page, "application submitted").await
            || dom::text_visible_on_page(page, "thank you for applying").await
            || dom::text_visible_on_page(page, "gracias por postularte").await
            || dom::text_visible_on_page(page, "obrigado por se candidatar").await
        {
            immediate_confirmation = true;
            break;
        }
    }

    if immediate_confirmation {
        let resume = ctx.actual_resume.clone().unwrap_or_else(|| ctx.target_resume.file_name().map(|f| f.to_string_lossy().to_string()).unwrap_or_default());
        println!("   🎉 [CONFIRMACIÓN VISIBLE] ¡Tu solicitud fue enviada con éxito a '{}'! (CV: {})", ctx.company, resume);
        println!("   👁️ [Pausa de Visibilidad] Manteniendo la pantalla de confirmación 5s para que puedas verla...");

        crate::services::audit::log_audit_event(
            "PASO_5_APPLY_SUPERVISOR",
            &format!("Confirmación Inmediata de Envío: {} @ {}", ctx.role, ctx.company),
            "OK",
            "APPLICATION_CONFIRMED_MODAL",
            &format!("LinkedIn mostró la pantalla de confirmación exitosa. CV: '{}'", resume),
            None,
            None,
            "Postulación certificada.",
            "Confirmación verificada en el modal de LinkedIn."
        );

        // Pausa visible de 5 segundos para que el usuario humano la vea con calma en pantalla
        tokio::time::sleep(std::time::Duration::from_secs(5)).await;

        println!("   ✨ [Humano] Cerrando modal de confirmación tras validación visual...");
        cleanup_modal(page).await;
        tokio::time::sleep(std::time::Duration::from_millis(800)).await;

        let _ = db.update_job_status(ctx.id, &applied_update(ctx).error("Confirmado: mensaje de éxito visible tras el clic."));
        return FlowResult::Submitted;
    }

    println!("   ⏳ Confirmación no detectada en el modal tras 6s. Verificando estado en la página principal de la vacante...");
    verify_against_job_page(page, db, ctx).await
}

/// The definitive check: reload the ORIGINAL LinkedIn job URL (not the modal) and read
/// LinkedIn's own "Application submitted" / "Postulación enviada" badge on the job
/// listing itself. This is the same signal job_processor.rs uses to skip jobs that were
/// already applied to, so it's ground truth, not a guess based on which button we
/// happened to click.
async fn verify_against_job_page(page: &Page, db: &DatabaseRepository, ctx: &JobContext) -> FlowResult {
    if page.goto(&ctx.url).await.is_err() {
        let _ = db.update_job_status(ctx.id, &JobStatusUpdate::new("Manual").error("No se pudo recargar la oferta para verificar el resultado."));
        return FlowResult::Manual;
    }
    tokio::time::sleep(std::time::Duration::from_secs(4)).await;

    // Deliberately specific phrases only — a bare "applied" is too generic and risks a
    // false-positive "Submitted" verdict (e.g. "filters applied" elsewhere on the page).
    let confirmed = dom::text_visible_on_page(page, "application submitted").await
        || dom::text_visible_on_page(page, "postulación enviada").await
        || dom::text_visible_on_page(page, "solicitud enviada").await
        || dom::text_visible_on_page(page, "candidatura enviada").await
        || dom::text_visible_on_page(page, "you applied").await
        || dom::text_visible_on_page(page, "ya aplicaste").await
        || dom::text_visible_on_page(page, "você se candidatou").await;

    if confirmed {
        let resume = ctx.actual_resume.clone().unwrap_or_else(|| ctx.target_resume.file_name().map(|f| f.to_string_lossy().to_string()).unwrap_or_default());
        println!("   ✅ VERIFICADO: {} en {} — LinkedIn confirma la oferta como aplicada. CV usado: {}.", ctx.role, ctx.company, resume);
        println!("   👁️ [Pausa de Visibilidad] Mostrando insignia de confirmación en la página por 4s...");
        tokio::time::sleep(std::time::Duration::from_secs(4)).await;

        crate::services::audit::log_audit_event(
            "PASO_5_APPLY_SUPERVISOR",
            &format!("Confirmación Oficial de Envío: {} @ {}", ctx.role, ctx.company),
            "OK",
            "APPLICATION_CONFIRMED_ON_LINKEDIN",
            &format!("LinkedIn confirmó oficialmente la postulación. CV adjunto verificado: '{}'", resume),
            None,
            None,
            "Oferta marcada como 'Applied' en base de datos.",
            "El supervisor certificó que LinkedIn muestra la insignia de postulado."
        );
        let _ = db.update_job_status(ctx.id, &applied_update(ctx).error("Verificado: al recargar la oferta, LinkedIn la muestra como ya aplicada."));
        FlowResult::Submitted
    } else {
        println!("   ⚠️ Verificado contra LinkedIn: {} en {} NO aparece como aplicada. Enviando a revisión manual.", ctx.role, ctx.company);
        crate::services::audit::log_audit_event(
            "PASO_5_APPLY_SUPERVISOR",
            &format!("Confirmación Oficial de Envío: {} @ {}", ctx.role, ctx.company),
            "FAIL",
            "APPLICATION_NOT_CONFIRMED_ON_PAGE",
            "Al recargar la oferta en LinkedIn, no se encontró la insignia de solicitud enviada.",
            None,
            None,
            "Oferta marcada como 'Manual' para revisión del usuario.",
            "El supervisor impidió asumir un éxito falso."
        );
        let _ = db.update_job_status(
            ctx.id,
            &JobStatusUpdate::new("Manual").error("Verificado: al recargar la oferta, LinkedIn NO la muestra como aplicada."),
        );
        FlowResult::Manual
    }
}

/// Ensures the Easy Apply modal is closed before moving to the next job.
pub async fn cleanup_modal(page: &Page) {
    let script = r#"(() => {
        // 1. Intentar clic en botón 'Hecho', 'Done' o 'Finalizar'
        const buttons = Array.from(document.querySelectorAll('button, .artdeco-button'));
        const doneBtn = buttons.find(b => {
            const t = (b.innerText || b.textContent || '').trim().toLowerCase();
            return t === 'hecho' || t === 'done' || t === 'finalizar';
        });
        if (doneBtn && (doneBtn.offsetWidth || doneBtn.offsetHeight)) {
            doneBtn.click();
            return true;
        }

        // 2. Intentar cerrar el modal por botón de cierre (Dismiss / Cerrar)
        const closeBtn = document.querySelector(
            "button[aria-label='Dismiss'], button[aria-label='Cerrar'], button[aria-label='Close'], button.artdeco-modal__dismiss, button[data-test-modal-close-btn]"
        );
        if (closeBtn) {
            closeBtn.click();
            return true;
        }

        // 3. Confirmar descarte si pide confirmación
        const modal = document.querySelector('.jobs-easy-apply-modal, .artdeco-modal');
        if (modal) {
            const btn = modal.querySelector("button[data-control-name='discard_application_confirm_btn']");
            if (btn) btn.click();
        }
        return true;
    })()"#;
    let _ = page.evaluate(script).await;
    tokio::time::sleep(std::time::Duration::from_millis(500)).await;
    let _ = page.evaluate("(() => document.activeElement && document.activeElement.blur())()").await;
}
