use super::application_flow::FlowResult;
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

/// Ejecuta el Apply Bot Directo para vacantes Externas.
/// Consulta en `talentflow.db` los empleos que ya tienen su enlace externo (`external_link`)
/// y navega directamente al portal correspondiente (Workday, Greenhouse, Lever, Micro1, Teamtailor, etc.)
/// SIN pasar por LinkedIn.
pub async fn run_external_apply_bot(
    db: DatabaseRepository,
    profile: ProfileConfig,
    base_dir: PathBuf,
    dry_run: bool,
    job_id: Option<i64>,
    status_filter: Option<String>,
    limit: usize,
    is_applying_flag: Arc<Mutex<bool>>,
) -> Result<usize> {
    let stop_signal_path = base_dir.join("dashboard").join("stop.signal");
    let _ = fs::remove_file(&stop_signal_path);

    let jobs = db.get_external_jobs_to_apply(limit as i64, status_filter.as_deref(), job_id)?;
    if jobs.is_empty() {
        println!("✅ No hay ofertas externas con 'external_link' pendientes para procesar.");
        write_status("Ready", "No hay ofertas externas para aplicar.");
        return Ok(0);
    }
    println!("📂 {} ofertas externas encontradas en la base de datos.", jobs.len());

    let (browser, handle) = crate::services::browser::launch_apply_browser().await?;
    let page = browser.new_page("about:blank").await?;
    let _ = crate::services::browser::inject_stealth_scripts(&page).await;

    let ai_client = AiClient::with_profile(Some(&profile)).with_custom_model("gpt-5.6-terra");
    println!("🤖 [External Apply Bot] Usando modelo especializado '{}' para ofertas externas...", ai_client.gemini_model());
    let resume_manager = ResumeManager::new(base_dir.clone(), profile.clone());
    let profile_skills = profile.skills.clone();

    let total = jobs.len();
    let mut processed = 0usize;

    for (idx, job) in jobs.into_iter().enumerate() {
        let running = *is_applying_flag.lock().await;
        if !running || stop_signal_path.exists() {
            println!("🛑 Stop recibido. Deteniendo proceso de postulación externa...");
            break;
        }

        write_status("Running", &format!("Aplicando DIRECTO externo [{}/{}]: {} en {}", idx + 1, total, job.role, job.company));

        if let Err(e) = process_external_job_direct(&page, &browser, &db, &ai_client, &resume_manager, &profile_skills, &job, dry_run, &stop_signal_path).await {
            eprintln!("   [Error] {}", e);
            if let Some(id) = job.id {
                let _ = db.update_job_status(id, &JobStatusUpdate::new("Failed").error(format!("Error en Apply Directo Externo: {}", e)));
            }
        }
        processed += 1;

        if idx + 1 >= total {
            break;
        }

        let delay = pseudo_random_delay_secs(8, 15);
        println!("   ⏱️ [Paso Humano] Pausa natural: {}s antes de pasar a la siguiente vacante externa...", delay);
        for _sec in 0..delay {
            if !*is_applying_flag.lock().await || stop_signal_path.exists() {
                println!("✅ Lote cancelado por el usuario.");
                crate::services::browser::close_browser(browser, handle).await;
                return Ok(processed);
            }
            tokio::time::sleep(std::time::Duration::from_secs(1)).await;
        }
    }

    write_status("Ready", &format!("Lote externo completado. {} ofertas procesadas.", processed));
    println!("✅ Batch External Apply Completed ({} ofertas procesadas).", processed);
    crate::services::browser::close_browser(browser, handle).await;
    Ok(processed)
}

async fn process_external_job_direct(
    page: &Page,
    _browser: &Browser,
    db: &DatabaseRepository,
    ai_client: &AiClient,
    resume_manager: &ResumeManager,
    profile_skills: &HashMap<String, HashMap<String, SkillInfo>>,
    job: &Job,
    dry_run: bool,
    stop_signal_path: &Path,
) -> Result<()> {
    if stop_signal_path.exists() {
        println!("🛑 Stop signal detected. Omitiendo vacante.");
        return Ok(());
    }

    let job_id = job.id.unwrap_or(0);
    let role = job.role.clone();
    let company = job.company.clone();
    let reqs = job.requirements.clone().unwrap_or_default();
    let location = job.location.clone().unwrap_or_else(|| "Colombia".to_string());
    let ext_url = match &job.external_link {
        Some(u) if !u.trim().is_empty() => u.trim().to_string(),
        _ => {
            println!("   ⚠️ La vacante #{} no tiene external_link válido.", job_id);
            return Ok(());
        }
    };

    println!("\n🌐 [Direct External Apply] Vacante ID #{}: '{}' @ '{}'", job_id, role, company);
    println!("   🔗 URL Directa Externa: {}", ext_url);

    let _ = db.update_job_status(job_id, &JobStatusUpdate::new("Applying").error(format!("Direct External Flow: {}", ext_url)));

    crate::services::audit::log_audit_event(
        "PASO_5_APPLY_EXTERNAL_DIRECTO",
        &format!("Navegación Directa: {} @ {}", role, company),
        "OK",
        "DIRECT_EXTERNAL_NAVIGATION",
        &format!("Navegando directamente al portal externo sin pasar por LinkedIn: {}", ext_url),
        None,
        None,
        "Iniciando flujo de formulario externo.",
        "El supervisor confirmó la URL externa de SQLite."
    );

    // Navegar DIRECTAMENTE al sitio externo
    page.goto(&ext_url).await?;
    tokio::time::sleep(std::time::Duration::from_secs(4)).await;

    let lang = ResumeManager::detect_language(&format!("{} {}", role, reqs));

    // Selección inteligente de CV
    let target_res = resume_manager
        .choose_resume_smart(ai_client, &role, &company, &reqs, &lang, job.applied_resume.as_deref())
        .await;

    if !target_res.exists() {
        let msg = format!("CV inexistente en disco: {:?}. Cancelando para no enviar documento inválido.", target_res);
        println!("   🛑 {}", msg);
        crate::services::audit::log_audit_event(
            "PASO_5_APPLY_EXTERNAL_DIRECTO",
            &format!("Validación de CV: {} @ {}", role, company),
            "FAIL",
            "CV_NOT_FOUND_ON_DISK",
            &msg,
            None,
            None,
            "Postulación detenida y marcada como Manual.",
            "El supervisor impidió enviar un documento que no existe físicamente en cv/."
        );
        let _ = db.update_job_status(job_id, &JobStatusUpdate::new("Manual").error(msg));
        return Ok(());
    }

    println!("      📍 RESUME SELECTED: {:?}", target_res.file_name().unwrap_or_default());
    let (salary_val, salary_curr) = resume_manager.get_salary_expectation(&role, &lang);
    println!("      💰 RESOLVED SALARY: {} {} ({})", salary_val, salary_curr, lang);

    let mut ctx = JobContext {
        id: job_id,
        role: role.clone(),
        company: company.clone(),
        location,
        description: reqs.clone(),
        url: ext_url.clone(),
        target_resume: target_res.clone(),
        actual_resume: None,
        applied_salary: Some(salary_val.clone()),
        applied_currency: Some(salary_curr.clone()),
    };

    let result = external_flow::handle_external_application(page, db, ai_client, resume_manager, &mut ctx, profile_skills, dry_run).await?;

    match result {
        FlowResult::Submitted => {
            println!("   🎉 [Direct External] ¡Postulación externa completada con éxito!");
            let resume = ctx.actual_resume.clone().unwrap_or_else(|| {
                target_res.file_name().map(|f| f.to_string_lossy().to_string()).unwrap_or_default()
            });
            let _ = db.update_job_status(
                job_id,
                &JobStatusUpdate::new("Applied")
                    .uploaded_cv(resume)
                    .salary(salary_val)
                    .currency(salary_curr)
                    .error("Postulación directa enviada exitosamente en portal externo.")
            );
        }
        FlowResult::Manual => {
            println!("   ⚠️ [Direct External] Requiere intervención manual.");
            let current_url = page.url().await.ok().flatten().unwrap_or(ext_url);
            let _ = db.update_job_status(job_id, &JobStatusUpdate::new("Manual").external_link(current_url));
        }
        FlowResult::Debug => {
            println!("   🛡️ [Direct External][SHADOW] Formulario auditado sin enviar en modo dry-run.");
            let _ = db.update_job_status(
                job_id,
                &JobStatusUpdate::new(job.status.clone()).error("Shadow mode (directo externo): formulario auditado, no se envió nada.")
            );
        }
        FlowResult::Stopped => {
            println!("   🛑 Proceso detenido.");
        }
    }

    Ok(())
}
