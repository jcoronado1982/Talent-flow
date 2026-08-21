use crate::db::DatabaseRepository;
use crate::services::{AiClient, Normalizer};
use anyhow::Result;
use chromiumoxide::Page;
use std::path::Path;
use std::time::Duration;

/// Extrae la descripción completa de una vacante desde su página directa /jobs/view/<id>/ o panel redirigido
pub async fn extract_description_from_job_page(page: &Page) -> Result<String> {
    // 1. Inyectar script para cerrar posibles modales o banners
    let dismiss_js = r#"
        (() => {
            const dismissBtn = document.querySelector('button[aria-label="Dismiss"], button.modal__dismiss, .artdeco-modal__dismiss, [data-test-modal-close-btn], .contextual-sign-in-modal__modal-dismiss-btn');
            if (dismissBtn) { try { dismissBtn.click(); } catch(e) {} }
        })()
    "#;
    let _ = page.evaluate(dismiss_js).await;

    // 2. Sondeo adaptativo de hasta 6s con expansión activa de "Ver más"
    let start_wait = std::time::Instant::now();
    while start_wait.elapsed() < Duration::from_millis(6000) {
        tokio::time::sleep(Duration::from_millis(400)).await;
        let get_desc_js = r#"
            (() => {
                const moreBtns = document.querySelectorAll(
                    'button.jobs-description__footer-button, button[aria-label*="Show more"], button[aria-label*="Ver más"], button.show-more-less-html__button, .artdeco-card__action, button[data-tracking-control-name="public_jobs_show-more-html-btn"]'
                );
                for (const b of moreBtns) {
                    try { b.click(); } catch(e) {}
                }

                const selectors = [
                    '#job-details',
                    '.jobs-description__content',
                    '.jobs-box__html-content',
                    '.show-more-less-html__markup',
                    'article.jobs-description__container',
                    '.jobs-description-content__text',
                    '.jobs-description',
                    'div.job-view-layout',
                    '.decorated-job-posting__details',
                    'section.description',
                    'article'
                ];

                for (const sel of selectors) {
                    const el = document.querySelector(sel);
                    if (el) {
                        const text = el.innerText.trim();
                        if (text.length > 50) {
                            return text.slice(0, 4000);
                        }
                    }
                }

                // Fallback a contenedor principal
                const main = document.querySelector('main, [role="main"]');
                if (main) {
                    const text = main.innerText.trim();
                    if (text.includes('About the job') || text.includes('Acerca del empleo') || text.includes('Requirements') || text.includes('Requisitos') || text.includes('Sobre a vaga') || text.includes('Responsabilidades')) {
                        return text.slice(0, 4000);
                    }
                }

                return '';
            })()
        "#;

        if let Ok(desc_res) = page.evaluate(get_desc_js).await {
            if let Ok(text) = desc_res.into_value::<String>() {
                if text.len() > 50 {
                    return Ok(text);
                }
            }
        }
    }

    Ok(String::new())
}

pub async fn run_rehydrate_empty_jobs(
    db: &DatabaseRepository,
    ai_client: &AiClient,
    profile_path: &Path,
    limit: Option<usize>,
) -> Result<usize> {
    let empty_jobs = db.get_jobs_with_missing_requirements(limit)?;
    if empty_jobs.is_empty() {
        println!("✅ No hay vacantes con descripción vacía en la base de datos.");
        return Ok(0);
    }

    println!("====================================================");
    println!(" 🔄 Rehidratación Forense de Vacantes Incompletas");
    println!("====================================================");
    println!("📊 Total de vacantes a rehidratar: {}", empty_jobs.len());
    println!("📂 Usando perfil de Chrome: {:?}", profile_path);

    let (browser, handle) = crate::services::browser::launch_browser_with_profile(profile_path).await?;
    let page = browser.new_page("about:blank").await?;
    let _ = crate::services::browser::inject_stealth_scripts(&page).await;

    let mut rehydrated_count = 0;

    for (idx, job) in empty_jobs.iter().enumerate() {
        let job_id = job.id.unwrap_or(0);
        let display_role = job
            .role
            .lines()
            .next()
            .unwrap_or(&job.role)
            .replace("with verification", "")
            .replace("con verificación", "")
            .trim()
            .to_string();

        println!("\n🔍 [{}/{}] Vacante #{} → '{}' @ '{}'", idx + 1, empty_jobs.len(), job_id, display_role, job.company);
        println!("   🔗 URL: {}", job.url);

        if let Err(e) = page.goto(&job.url).await {
            eprintln!("   ⚠️ Error navegando a {}: {}", job.url, e);
            continue;
        }

        // Pausa humana breve para carga de red
        tokio::time::sleep(Duration::from_millis(2000)).await;

        let desc = match extract_description_from_job_page(&page).await {
            Ok(d) if !d.is_empty() => d,
            _ => {
                println!("   ⚠️ No se pudo extraer descripción del DOM (oferta cerrada o no disponible).");
                continue;
            }
        };

        let desc_len = desc.len();
        println!("   📄 Descripción extraída: {} caracteres", desc_len);

        // Detectar idioma
        let language = Normalizer::detect_language(&format!("{} {}", display_role, desc));

        // Re-evaluar con IA (Gemini)
        println!("   🧠 Re-evaluando con Gemini ({}) ...", ai_client.gemini_model());
        let analysis = ai_client
            .analyze_job(&display_role, &job.company, &desc)
            .await
            .unwrap_or_else(|_| crate::services::AnalysisResult {
                match_score: 50.0,
                status: "Manual".to_string(),
                skills: Normalizer::extract_skills_heuristic(&desc),
                summary: "Evaluado automáticamente tras rehidratación".to_string(),
            });

        let skills_str = analysis.skills.join(", ");
        let badge = if analysis.match_score >= 70.0 {
            "🌟 [MATCH]"
        } else if analysis.match_score >= 50.0 {
            "⚖️ [MANUAL]"
        } else {
            "❌ [DESCARTE]"
        };
        println!(
            "   {} Score: {:.0}% | Estado: {} | Skills: [{}]",
            badge, analysis.match_score, analysis.status, skills_str
        );
        println!("   💡 Razonamiento: {}", analysis.summary.chars().take(140).collect::<String>());

        // Actualizar en SQLite
        db.update_job_full_details(
            job_id,
            &desc,
            &language,
            analysis.match_score,
            &analysis.status,
            &analysis.summary,
            &skills_str,
            ai_client.gemini_model(),
        )?;

        rehydrated_count += 1;
        println!("   💾 [Actualizada en DB #{}] Vacante #{} completada.", rehydrated_count, job_id);

        // Jitter natural entre vacantes (1.5s - 2.5s)
        tokio::time::sleep(Duration::from_millis(1500 + (idx as u64 % 5) * 200)).await;
    }

    crate::services::browser::close_browser(browser, handle).await;

    println!("\n🎉 [Rehidratación Finalizada] {} vacantes completadas y re-evaluadas.", rehydrated_count);
    Ok(rehydrated_count)
}
