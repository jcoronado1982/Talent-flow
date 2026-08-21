use super::application_flow::{self, FlowResult};
use super::dom;
use super::external_flow;
use super::form::JobContext;
use super::resume_manager::ResumeManager;
use crate::db::{DatabaseRepository, JobStatusUpdate};
use crate::domain::models::{Job, ProfileConfig, SkillInfo};
use crate::services::AiClient;
use anyhow::Result;
use chromiumoxide::browser::Browser;
use chromiumoxide::Page;
use serde_json::json;
use std::collections::HashMap;
use std::fs;
use std::path::{Path, PathBuf};
use std::sync::Arc;
use std::time::{SystemTime, UNIX_EPOCH};
use tokio::sync::Mutex;

fn pseudo_random_delay_secs(min: u64, max: u64) -> u64 {
    let nanos = SystemTime::now().duration_since(UNIX_EPOCH).map(|d| d.subsec_nanos() as u64).unwrap_or(0);
    min + (nanos % (max - min + 1))
}

fn write_status(status: &str, task: &str) {
    let data = json!({
        "status": status,
        "current_task": task,
        "timestamp": chrono::Utc::now().to_rfc3339(),
    });
    let _ = fs::write("dashboard/status.json", data.to_string());
}

/// Top-level Apply bot loop: pulls 'Matched' jobs and processes them one at a time with
/// an anti-ban pause in between. Mirrors
/// src/app/bots/apply/supervisor.py::ApplyBotSupervisor.run.
pub async fn run_apply_bot(
    db: DatabaseRepository,
    profile: ProfileConfig,
    base_dir: PathBuf,
    dry_run: bool,
    is_applying_flag: Arc<Mutex<bool>>,
) -> Result<usize> {
    let stop_signal_path = base_dir.join("dashboard").join("stop.signal");
    let _ = fs::remove_file(&stop_signal_path);

    let jobs = db.get_jobs_to_apply(30)?;
    if jobs.is_empty() {
        println!("✅ No hay ofertas 'Matched' para aplicar.");
        write_status("Ready", "No hay ofertas para aplicar.");
        return Ok(0);
    }
    println!("📂 {} ofertas pendientes en base de datos.", jobs.len());

    let (browser, handle) = crate::services::browser::launch_authenticated_browser().await?;
    let page = browser.new_page("about:blank").await?;
    // Modelo que se cambia a mano (intencional — no convertir en config)
    let ai_client = AiClient::with_profile(Some(&profile)).with_custom_model("gpt-5.6-terra");
    println!("🤖 [Apply Bot] Usando modelo especializado '{}' para postulaciones (LinkedIn & Externas)...", ai_client.gemini_model());
    let resume_manager = ResumeManager::new(base_dir.clone(), profile.clone());
    let profile_skills = profile.skills.clone();

    println!("   🔄 Verificando sesión...");
    let _ = page.goto("https://www.linkedin.com/feed/").await;
    tokio::time::sleep(std::time::Duration::from_secs(2)).await;

    let total = jobs.len();
    let mut processed = 0usize;

    for (idx, job) in jobs.into_iter().enumerate() {
        let running = *is_applying_flag.lock().await;
        if !running || stop_signal_path.exists() {
            println!("🛑 Stop recibido. Deteniendo...");
            break;
        }

        write_status("Running", &format!("Aplicando [{}/{}]: {} en {}", idx + 1, total, job.role, job.company));

        if let Err(e) = process_job(&page, &browser, &db, &ai_client, &resume_manager, &profile_skills, &job, dry_run, &stop_signal_path).await {
            eprintln!("   [Error] {}", e);
            if let Some(id) = job.id {
                let _ = db.update_job_status(id, &JobStatusUpdate::new("Failed").error(e.to_string()));
            }
        }
        application_flow::cleanup_modal(&page).await;
        processed += 1;

        if idx + 1 >= total {
            break;
        }

        // Pausa de transición natural humana entre ofertas (8-15s)
        let delay = pseudo_random_delay_secs(8, 15);
        println!("   ⏱️ [Paso Humano] Pausa natural: {}s antes de pasar a la siguiente vacante...", delay);
        for sec in 0..delay {
            if !*is_applying_flag.lock().await || stop_signal_path.exists() {
                println!("✅ Batch Cancelled.");
                crate::services::browser::close_browser(browser, handle).await;
                return Ok(processed);
            }
            tokio::time::sleep(std::time::Duration::from_secs(1)).await;
        }
    }

    write_status("Ready", &format!("Batch completado. {} ofertas procesadas.", processed));
    println!("✅ Batch Completed.");
    crate::services::browser::close_browser(browser, handle).await;
    Ok(processed)
}

async fn process_job(
    page: &Page,
    browser: &Browser,
    db: &DatabaseRepository,
    ai_client: &AiClient,
    resume_manager: &ResumeManager,
    profile_skills: &HashMap<String, HashMap<String, SkillInfo>>,
    job: &Job,
    dry_run: bool,
    stop_signal_path: &Path,
) -> Result<()> {
    if stop_signal_path.exists() {
        println!("🛑 Stop signal detected. Skipping job.");
        return Ok(());
    }

    let job_id = job.id.unwrap_or(0);
    let role = job.role.clone();
    let reqs = job.requirements.clone().unwrap_or_default();
    let url = job.url.clone();
    let location = job.location.clone().unwrap_or_else(|| "Unknown".to_string());

    println!("\n👉 Processing Job ID {}: {}", job_id, role);
    let _ = db.update_job_status(job_id, &JobStatusUpdate::new("Applying").error("Starting application process..."));

    println!("   🌐 [Nav] Navigating to: {}", url);
    page.goto(&url).await?;
    tokio::time::sleep(std::time::Duration::from_secs(5)).await;

    if dom::text_visible_on_page(page, "application submitted").await || dom::text_visible_on_page(page, "postulación enviada").await {
        println!("   ✅ Already applied to this job.");
        let _ = db.update_job_status(job_id, &JobStatusUpdate::new("Applied").resume("Previously"));
        return Ok(());
    }

    let before_tabs = super::tabs::snapshot_target_ids(browser).await;

    println!("   ⏳ Waiting for 'Apply' button to be ready...");
    let clicked = dom::click_apply_button(page).await.unwrap_or(false);

    if !clicked {
        println!("   ❌ Apply button not found.");
        let _ = db.update_job_status(job_id, &JobStatusUpdate::new("Failed").error("Apply button not found"));
        return Ok(());
    }

    tokio::time::sleep(std::time::Duration::from_secs(2)).await;

    // Detect a brand-new tab (target="_blank" redirect) first — chromiumoxide
    // auto-discovers and auto-attaches new targets on its own, so Browser::pages()
    // already reflects it within a couple of polls. Falls back to the same-tab
    // URL-diff check for the (more common) same-tab redirect case.
    let new_tab = super::tabs::wait_for_new_page(browser, &before_tabs, std::time::Duration::from_secs(4)).await;

    let (page, is_external, current_url) = if let Some(new_page) = new_tab {
        let u = new_page.url().await.ok().flatten().unwrap_or_default();
        (new_page, true, u)
    } else {
        let u = page.url().await.ok().flatten().unwrap_or_default();
        let ext = !u.contains("linkedin.com/jobs");
        (page.clone(), ext, u)
    };
    let page = &page;

    let lang = ResumeManager::detect_language(&format!("{} {}", role, reqs));

    // The AI picks from the resumes that actually exist on disk (deterministic rules are
    // the fallback). Resolved once here so both flows apply for the same document.
    let target_res = resume_manager
        .choose_resume_smart(ai_client, &role, &job.company, &reqs, &lang, job.applied_resume.as_deref())
        .await;

    // Never start an application we cannot attach a CV to. Without this, a missing resume
    // file meant smart_upload_resume quietly uploaded nothing and LinkedIn submitted with
    // whatever document was already on the account (incident 2026-08-18, Crossing Hurdles).
    if !target_res.exists() {
        let msg = format!("CV inexistente en disco: {:?}. No se aplica para no enviar un CV viejo.", target_res);
        println!("   🛑 {}", msg);
        crate::services::audit::log_audit_event(
            "PASO_5_APPLY_SUPERVISOR",
            &format!("Validación de CV: {} @ {}", role, job.company),
            "FAIL",
            "CV_NOT_FOUND_ON_DISK",
            &msg,
            None,
            None,
            "Postulación cancelada por seguridad. Marcada como Manual.",
            "El supervisor impidió enviar un documento viejo o inválido."
        );
        let _ = db.update_job_status(job_id, &JobStatusUpdate::new("Manual").error(msg));
        return Ok(());
    }

    crate::services::audit::log_audit_event(
        "PASO_5_APPLY_SUPERVISOR",
        &format!("Selección de CV: {} @ {}", role, job.company),
        "OK",
        "CV_VERIFIED",
        &format!("CV seleccionado: {:?} | Idioma: {}", target_res.file_name().unwrap_or_default(), lang),
        None,
        None,
        "Procediendo con apertura de formulario.",
        "El supervisor certificó que el PDF existe físicamente en cv/."
    );

    if is_external {
        println!("      📍 RESUME SELECTED: {:?}", target_res.file_name().unwrap_or_default());
        let (salary_val, salary_curr) = resume_manager.get_salary_expectation(&role, &lang);
        println!("      💰 RESOLVED SALARY: {} {} ({})", salary_val, salary_curr, lang);

        let mut ctx = JobContext {
            id: job_id,
            role: role.clone(),
            company: job.company.clone(),
            location,
            description: reqs.clone(),
            url: url.clone(),
            target_resume: target_res.clone(),
            actual_resume: None,
            applied_salary: Some(salary_val),
            applied_currency: Some(salary_curr),
        };

        let ext_ai_client = ai_client.with_custom_model("gpt-5.6-terra");
        let result = external_flow::handle_external_application(page, db, &ext_ai_client, resume_manager, &mut ctx, profile_skills, dry_run).await?;
        match result {
            FlowResult::Submitted => {
                println!("   🎉 [External] Application Successful!");
                // External ATS resume widgets vary too much site-to-site for a generic
                // read-back check yet (unlike the LinkedIn flow) — be honest about that
                // instead of assuming the intended file was the one actually attached.
                let resume = ctx.actual_resume.clone().unwrap_or_else(|| "SIN VERIFICAR — el sitio externo no permitió confirmar qué CV quedó adjunto".to_string());
                let _ = db.update_job_status(job_id, &JobStatusUpdate::new("Applied").uploaded_cv(resume));
            }
            FlowResult::Manual => {
                println!("   ⚠️ [External] Manual intervention needed.");
                let _ = db.update_job_status(job_id, &JobStatusUpdate::new("Manual").external_link(current_url));
            }
            FlowResult::Debug => {
                println!("   🛡️ [External][SHADOW] Formulario auditado sin enviar.");
                // Restore to Matched (not left stuck in "Applying") so a dry-run audit
                // never removes a job from the queue — it's just observation.
                let _ = db.update_job_status(job_id, &JobStatusUpdate::new("Matched").error("Shadow mode (externo): formulario auditado, no se envió."));
            }
            FlowResult::Stopped => {}
        }
        return Ok(());
    }

    // Same-tab Easy Apply modal flow — reuses the resume resolved above.
    let _ = db.update_job_status(job_id, &JobStatusUpdate::new("Applying").error(format!("Resume selected: {}", filename_str(&target_res))));
    let (salary_val, salary_curr) = resume_manager.get_salary_expectation(&role, &lang);
    println!("      💰 RESOLVED SALARY: {} {} ({})", salary_val, salary_curr, lang);

    let mut ctx = JobContext {
        id: job_id,
        role: role.clone(),
        company: job.company.clone(),
        location,
        description: reqs.clone(),
        url: url.clone(),
        target_resume: target_res.clone(),
        actual_resume: None,
        applied_salary: Some(salary_val),
        applied_currency: Some(salary_curr),
    };

    let result = application_flow::handle_application_flow(page, db, ai_client, resume_manager, &mut ctx, profile_skills, dry_run, stop_signal_path).await?;

    match result {
        FlowResult::Submitted => println!("   🎉 Application Successfully Submitted!"),
        FlowResult::Manual => {
            println!("   ⚠️  Complex form/Manual intervention needed.");
            let resume = ctx.actual_resume.clone().unwrap_or_else(|| filename_str(&target_res));
            let _ = db.update_job_status(job_id, &JobStatusUpdate::new("Manual").resume(resume));
        }
        FlowResult::Debug => {
            println!("   🛡️ [SHADOW MODE] Formulario auditado sin enviar.");
            let _ = db.update_job_status(job_id, &JobStatusUpdate::new("Matched").error("Shadow mode: formulario auditado, no se envió."));
        }
        FlowResult::Stopped => {}
    }

    Ok(())
}

fn filename_str(path: &Path) -> String {
    path.file_name().map(|f| f.to_string_lossy().to_string()).unwrap_or_default()
}
