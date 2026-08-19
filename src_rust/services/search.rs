use crate::config::AppConfig;
use crate::db::DatabaseRepository;
use crate::services::audit::log_audit_event;
use anyhow::Result;
use chromiumoxide::browser::Browser;
use chromiumoxide::Page;
use serde_json::Value;
use std::time::Duration;

/// Pausa humana natural con micro-variaciones (Jitter)
async fn human_pause(min_ms: u64, max_ms: u64) {
    let diff = if max_ms > min_ms { max_ms - min_ms } else { 1 };
    let jitter = (chrono::Utc::now().timestamp_subsec_nanos() as u64) % diff;
    tokio::time::sleep(Duration::from_millis(min_ms + jitter)).await;
}

/// Scroll físico suave para la lista izquierda de ofertas
async fn scroll_left_results_list(page: &Page, delta_y: i32) -> Result<()> {
    let js = format!(
        r#"
        () => {{
            const list = document.querySelector('.jobs-search-results-list') 
                || document.querySelector('.scaffold-layout__list')
                || document.querySelector('ul.scaffold-layout__list-container')
                || window;
            if (list.scrollBy) {{
                list.scrollBy({{ top: {}, behavior: 'smooth' }});
            }}
        }}
        "#,
        delta_y
    );
    let _ = page.evaluate(js).await;
    Ok(())
}

/// Scroll físico suave exclusivo para el panel DERECHO de la oferta (donde está la descripción)
async fn scroll_right_details_pane(page: &Page, delta_y: i32) -> Result<()> {
    let js = format!(
        r#"
        () => {{
            // Encontrar el contenedor exacto con scroll del panel derecho
            const detailPane = document.querySelector('.scaffold-layout__detail')
                || document.querySelector('.jobs-search__job-details--container')
                || document.querySelector('div.job-view-layout')
                || document.querySelector('.jobs-description')
                || document.querySelector('.jobs-description-content__text')
                || document.querySelector('#job-details');
            
            if (detailPane) {{
                if (detailPane.scrollBy) {{
                    detailPane.scrollBy({{ top: {}, behavior: 'smooth' }});
                }} else {{
                    detailPane.scrollTop = (detailPane.scrollTop || 0) + {};
                }}
            }}
        }}
        "#,
        delta_y, delta_y
    );
    let _ = page.evaluate(js).await;
    Ok(())
}

/// Hace clic en una tarjeta específica para abrir su panel de detalles en la derecha
async fn click_and_open_job(page: &Page, card_idx: usize) -> Result<bool> {
    let js = format!(
        r#"
        () => {{
            const cards = document.querySelectorAll('.job-card-container, .jobs-search-results__list-item, div[data-job-id], li.ember-view[data-occludable-job-id]');
            if (!cards || !cards[{}]) return false;
            
            const card = cards[{}];
            const clickTarget = card.querySelector('a.job-card-container__link, .job-card-list__title, .artdeco-entity-lockup__title') || card;
            clickTarget.click();
            return true;
        }}
        "#,
        card_idx, card_idx
    );
    
    let clicked = page.evaluate(js).await?.into_value::<bool>().unwrap_or(false);
    Ok(clicked)
}

pub async fn run_job_search(
    browser: &mut Browser,
    config: &AppConfig,
    db: &DatabaseRepository,
    limit_per_search: usize,
    target_country: Option<&str>,
) -> Result<usize> {
    let country = target_country.unwrap_or("Colombia");
    println!("\n🔍 [Paso 3: Búsqueda] Iniciando Motor de Navegación Humana (Scroll en Panel de Oferta)...");
    println!("📍 Explorando vacantes en: {}", country);

    let page = browser.new_page("https://www.linkedin.com/jobs/").await?;
    let _ = crate::services::browser::inject_stealth_scripts(&page).await;
    human_pause(2000, 3000).await;

    let default_roles = vec!["Developer".to_string()];
    let target_roles = config
        .profile
        .target_roles
        .as_ref()
        .unwrap_or(&default_roles);

    let mut total_saved = 0;

    for (role_idx, role) in target_roles.iter().enumerate() {
        let encoded_role = role.replace(" ", "%20");
        let encoded_loc = country.replace(" ", "%20");
        
        let search_url = format!(
            "https://www.linkedin.com/jobs/search/?keywords={}&location={}&f_TPR=r86400",
            encoded_role, encoded_loc
        );

        println!("\n🌐 [{}/{}] Explorando en vivo: '{}' en '{}'", role_idx + 1, target_roles.len(), role, country);
        println!("   🔗 URL: {}", search_url);

        if let Err(e) = page.goto(&search_url).await {
            log_audit_event(
                "PASO_3_BUSQUEDA", "Carga de Página", "FAIL", "NAVIGATION_ERROR",
                &format!("Error cargando búsqueda: {}", e), None, None, "Saltando a siguiente criterio.", ""
            );
            continue;
        }

        human_pause(3000, 4000).await;

        // Verificar si LinkedIn metió el modal bloqueante de 'Sign in'
        let is_blocked = page
            .evaluate(r#"
                () => {
                    const modal = document.querySelector('.contextual-sign-in-modal, .sign-in-modal, [data-tracking-control-name="public_jobs_contextual-sign-in-modal_sign-in-modal_outlet"]');
                    const bodyText = document.body ? document.body.innerText : '';
                    return (modal !== null) || bodyText.includes('Sign in to view more jobs');
                }
            "#)
            .await?
            .into_value::<bool>()
            .unwrap_or(false);

        if is_blocked {
            let timestamp = chrono::Utc::now().format("%Y%m%d_%H%M%S").to_string();
            let screen_path = format!("debug/screenshots/blocked_search_{}.png", timestamp);
            let _ = page.save_screenshot(
                chromiumoxide::page::ScreenshotParams::builder().format(chromiumoxide::cdp::browser_protocol::page::CaptureScreenshotFormat::Png).build(),
                &screen_path
            ).await;

            log_audit_event(
                "PASO_3_BUSQUEDA", "Verificación Anti-Bloqueo", "FAIL", "SIGN_IN_WALL_DETECTED",
                "LinkedIn presentó el modal de 'Sign in to view more jobs' bloqueando la búsqueda.",
                None, Some(screen_path), "Deteniendo búsqueda para proteger la cuenta.", "Revisar sesión del perfil."
            );
            break;
        }

        // Hidratación inicial de la lista izquierda
        let _ = scroll_left_results_list(&page, 350).await;
        human_pause(600, 1000).await;

        // Extraer lista de ofertas
        let extraction_js = r#"
            () => {
                const jobs = [];
                const cards = document.querySelectorAll('.job-card-container, .jobs-search-results__list-item, div[data-job-id], li.ember-view[data-occludable-job-id], .base-card');
                
                for (const card of cards) {
                    try {
                        const titleElem = card.querySelector('.job-card-list__title, .artdeco-entity-lockup__title, .base-search-card__title, a.job-card-container__link, strong');
                        const companyElem = card.querySelector('.job-card-container__primary-description, .base-search-card__subtitle, .artdeco-entity-lockup__subtitle, h4 a');
                        const locElem = card.querySelector('.job-card-container__metadata-item, .job-search-card__location');
                        const linkElem = card.querySelector('a[href*="/jobs/view/"], a.job-card-container__link, a.base-card__full-link');
                        
                        const title = titleElem ? titleElem.innerText.trim() : '';
                        const company = companyElem ? companyElem.innerText.trim() : '';
                        const location = locElem ? locElem.innerText.trim() : '';
                        const url = linkElem ? linkElem.href.split('?')[0] : '';
                        
                        if (title && url) {
                            jobs.push({
                                title: title,
                                company: company || 'Empresa Confidencial',
                                location: location || 'Remoto / No especificado',
                                url: url
                            });
                        }
                    } catch (e) {}
                }
                return jobs;
            }
        "#;

        let extracted: Vec<Value> = match page.evaluate(extraction_js).await {
            Ok(v) => v.into_value().unwrap_or_default(),
            Err(_) => Vec::new(),
        };

        println!("   📋 [Resultados] Encontradas {} ofertas. Leyendo panel de descripción en la derecha...", extracted.len());

        for (idx, item) in extracted.iter().enumerate() {
            if idx >= limit_per_search {
                break;
            }

            let title = item.get("title").and_then(|v| v.as_str()).unwrap_or("");
            let company = item.get("company").and_then(|v| v.as_str()).unwrap_or("");
            let loc = item.get("location").and_then(|v| v.as_str()).unwrap_or("");
            let url = item.get("url").and_then(|v| v.as_str()).unwrap_or("");

            if url.is_empty() || title.is_empty() {
                continue;
            }

            let display_title = title.lines().next().unwrap_or(title);

            // 1. Clic en la tarjeta de la izquierda
            println!("   👉 [Clic] Abriendo oferta {:02}/{:02}: '{}' @ '{}'", idx + 1, extracted.len().min(limit_per_search), display_title, company);
            let _ = click_and_open_job(&page, idx).await;
            human_pause(1200, 1800).await;

            // 2. Desplazar hacia abajo el PANEL DERECHO DE LA OFERTA (Descripción)
            println!("      📖 [Scroll Panel Derecho] Leyendo descripción y requisitos del empleo (+300px)...");
            let _ = scroll_right_details_pane(&page, 300).await;
            human_pause(1200, 1800).await;

            println!("      📖 [Scroll Panel Derecho] Leyendo tecnologías y responsabilidades (+350px)...");
            let _ = scroll_right_details_pane(&page, 350).await;
            human_pause(1000, 1500).await;

            // 3. Guardar en SQLite
            let is_new = save_job_if_new(db, url, company, title, loc, role)?;
            if is_new {
                total_saved += 1;
                println!("      ✨ [GUARDADA NUEVA #{}] '{}' @ '{}'", total_saved, display_title, company);
            } else {
                println!("      ⏭️ [YA EN BASE DE DATOS] Omitiendo duplicado.");
            }

            // 4. Scroll suave en la lista izquierda para enfocar la siguiente tarjeta
            let _ = scroll_left_results_list(&page, 140).await;
        }

        log_audit_event(
            "PASO_3_BUSQUEDA_SUPERVISOR",
            &format!("Búsqueda: {} en {}", role, country),
            "OK",
            "JOBS_EXTRACTED",
            &format!("Procesadas {} ofertas en LinkedIn con lectura del panel derecho.", extracted.len()),
            None, None,
            "Búsqueda completada.",
            ""
        );

        human_pause(2000, 3000).await;
    }

    Ok(total_saved)
}

fn save_job_if_new(
    db: &DatabaseRepository,
    url: &str,
    company: &str,
    role: &str,
    location: &str,
    source_role: &str,
) -> Result<bool> {
    let conn = rusqlite::Connection::open(db.db_path())?;
    
    let count: i64 = conn.query_row(
        "SELECT count(*) FROM jobs WHERE url = ?1",
        rusqlite::params![url],
        |r| r.get(0),
    ).unwrap_or(0);

    if count > 0 {
        return Ok(false);
    }

    let source = format!("LinkedIn ({})", source_role);
    conn.execute(
        "INSERT INTO jobs (url, company, role, location, work_mode, date_posted, source, status, created_at)
         VALUES (?1, ?2, ?3, ?4, 'Remote', CURRENT_TIMESTAMP, ?5, 'Pending', CURRENT_TIMESTAMP)",
        rusqlite::params![url, company, role, location, source],
    )?;

    Ok(true)
}
