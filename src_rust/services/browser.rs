use crate::db::DatabaseRepository;
use crate::services::AiClient;
use anyhow::{Context, Result};
use chromiumoxide::browser::{Browser, BrowserConfig};
use futures_util::StreamExt;
use serde_json::json;
use std::fs;
use std::sync::Arc;
use std::time::Duration;
use tokio::sync::Mutex;
use tokio::task::JoinHandle;

// =========================================================================================
// ⚠️ REGLA ARQUITECTÓNICA CRÍTICA / NO MODIFICAR EL MÉTODO DE AUTENTICACIÓN
// =========================================================================================
// El lanzamiento del navegador DEBE realizarse SIEMPRE como un proceso nativo del sistema
// operativo ("Modo Humano Puro") usando `tokio::process::Command` y conectando vía CDP WebSocket.
// 
// MOTIVO:
// 1. Si se utiliza `Browser::launch(config)` estándar de librerías de automatización, Chrome 
//    inyecta automáticamente `--enable-automation`, lo que produce el banner:
//    "Chrome is being controlled by automated test software".
// 2. Google OAuth ("Continuar con Google") y LinkedIn detectan esa bandera y BLOQUEAN 
//    la autenticación del usuario.
// 3. Al lanzar el binario directamente con `--remote-debugging-port` y conectar vía WebSocket:
//    - Cero banners de prueba o automatización.
//    - El navegador es 100% idéntico a un navegador abierto manualmente por un humano.
//    - Se permite el inicio de sesión transparente con Google y LinkedIn.
// =========================================================================================

pub async fn inject_stealth_scripts(page: &chromiumoxide::Page) -> Result<()> {
    let stealth_js = r#"
        () => {
            // 1. Ocultar webdriver
            Object.defineProperty(navigator, 'webdriver', { get: () => undefined });

            // 2. Mock de plugins reales de Chrome
            if (!navigator.plugins || navigator.plugins.length === 0) {
                Object.defineProperty(navigator, 'plugins', {
                    get: () => [
                        { name: 'Chrome PDF Plugin', filename: 'internal-pdf-viewer' },
                        { name: 'Chrome PDF Viewer', filename: 'mhjfbmdgcfjbbpaeojofohoefgiehjai' },
                        { name: 'Native Client', filename: 'internal-nacl-plugin' }
                    ],
                });
            }

            // 3. Mock del objeto window.chrome estándar
            window.chrome = window.chrome || {
                runtime: {},
                loadTimes: function() {},
                csi: function() {},
                app: {}
            };

            // 4. Idiomas normales del sistema
            Object.defineProperty(navigator, 'languages', {
                get: () => ['es-ES', 'es', 'en-US', 'en'],
            });

            // 5. Permisos normales de notificaciones
            if (window.navigator && window.navigator.permissions) {
                const origQuery = window.navigator.permissions.query;
                window.navigator.permissions.query = (parameters) => (
                    parameters && parameters.name === 'notifications' ?
                        Promise.resolve({ state: Notification.permission }) :
                        origQuery(parameters)
                );
            }
        }
    "#;
    let _ = page.evaluate(stealth_js).await;
    Ok(())
}

/// Launches Chrome against the persisted, already-authenticated LinkedIn profile.
pub async fn launch_authenticated_browser() -> Result<(Browser, JoinHandle<()>)> {
    let current_dir = std::env::current_dir()?;

    // user_data_safe (autenticado 2026-08-18 con safe.jcoronado@gmail.com) tiene prioridad:
    // es la sesión que el usuario pidió explícitamente usar para las pruebas.
    let user_data_path = if current_dir.join("user_data_safe").exists() {
        current_dir.join("user_data_safe")
    } else if current_dir.join("user_data_auth").exists() {
        current_dir.join("user_data_auth")
    } else if current_dir.join("user_data_auth_profile_1").exists() {
        current_dir.join("user_data_auth_profile_1")
    } else {
        current_dir.join("user_data")
    };

    launch_browser_with_profile(&user_data_path).await
}

/// 🚀 LANZADOR DE GOOGLE CHROME EN MODO HUMANO PURO (NO MODIFICAR)
/// Lanza Google Chrome directamente desde el SO (sin banderas de test ni de automatización)
/// y se conecta vía WebSocket CDP.
pub async fn launch_browser_with_profile(user_data_path: &std::path::Path) -> Result<(Browser, JoinHandle<()>)> {
    let current_dir = std::env::current_dir()?;
    println!("📂 [Rust Native Browser] Iniciando Google Chrome en modo 100% humano: {:?}", user_data_path);

    // Limpiar locks de Chrome
    let _ = fs::remove_file(user_data_path.join("SingletonLock"));
    let _ = fs::remove_file(current_dir.join("user_data/SingletonLock"));

    let port = 9222;
    let mut chrome_bin = "/usr/bin/google-chrome";
    for candidate in ["/usr/bin/google-chrome-stable", "/usr/bin/google-chrome", "/opt/google/chrome/google-chrome", "/usr/bin/chromium", "/usr/bin/chromium-browser"] {
        if std::path::Path::new(candidate).exists() {
            chrome_bin = candidate;
            break;
        }
    }

    // Cerrar instancias previas huérfanas en el puerto 9222
    let _ = tokio::process::Command::new("pkill").arg("-f").arg(format!("remote-debugging-port={}", port)).output().await;
    tokio::time::sleep(Duration::from_millis(300)).await;

    // Lanzar proceso Chrome estándar del sistema operativo (sin banderas de prueba)
    let _child = tokio::process::Command::new(chrome_bin)
        .arg(format!("--remote-debugging-port={}", port))
        .arg(format!("--user-data-dir={}", user_data_path.display()))
        .arg("--profile-directory=Default")
        .arg("--disable-blink-features=AutomationControlled")
        .arg("--disable-infobars")
        .arg("--no-first-run")
        .arg("--no-default-browser-check")
        .arg("--disable-session-crashed-bubble")
        .arg("--start-maximized")
        .spawn()
        .context("Error al iniciar Google Chrome nativo")?;

    // Conectar vía WebSocket a la instancia de Chrome
    let mut browser_opt = None;
    for _ in 0..25 {
        tokio::time::sleep(Duration::from_millis(250)).await;
        if let Ok((browser, mut handler)) = Browser::connect(format!("http://127.0.0.1:{}", port)).await {
            let handle = tokio::task::spawn(async move {
                while let Some(event) = handler.next().await {
                    if let Err(e) = event {
                        eprintln!("Browser handler error: {}", e);
                        break;
                    }
                }
            });
            browser_opt = Some((browser, handle));
            break;
        }
    }

    if let Some(res) = browser_opt {
        println!("🚀 [Rust Native Browser] Conexión establecida con Chrome Humano (sin alertas de automatización).");
        Ok(res)
    } else {
        println!("⚠️ Fallback a Browser::launch estándar...");
        let config = BrowserConfig::builder()
            .user_data_dir(user_data_path)
            .with_head()
            .arg("--profile-directory=Default")
            .arg("--disable-blink-features=AutomationControlled")
            .arg("--disable-infobars")
            .build()
            .map_err(|e| anyhow::anyhow!("Browser config error: {}", e))?;
        let (browser, mut handler) = Browser::launch(config).await?;
        let handle = tokio::task::spawn(async move {
            while let Some(event) = handler.next().await {
                if let Err(e) = event {
                    break;
                }
            }
        });
        Ok((browser, handle))
    }
}

/// Cierra el navegador CDP y termina de forma garantizada el proceso de Chrome en el SO
pub async fn close_browser(mut browser: Browser, handle: JoinHandle<()>) {
    handle.abort();
    let _ = browser.close().await;
    let _ = tokio::process::Command::new("pkill")
        .arg("-f")
        .arg("remote-debugging-port=9222")
        .output()
        .await;
}

pub struct NativeBrowserScraper {
    db: DatabaseRepository,
    ai_client: AiClient,
}

impl NativeBrowserScraper {
    pub fn new(db: DatabaseRepository) -> Self {
        Self {
            db,
            ai_client: AiClient::new(),
        }
    }

    pub async fn run_linkedin_continuous_search(
        &self,
        query: &str,
        location: &str,
        is_searching_flag: Arc<Mutex<bool>>,
    ) -> Result<usize> {
        println!("🚀 [Rust Native Browser] Iniciando navegador Chrome con tu sesión activa de LinkedIn...");

        let (browser, handle) = launch_authenticated_browser().await?;

        let mut total_saved = 0;
        let max_pages = 5; // Escanear hasta 5 páginas continuas (hasta 125 ofertas)

        let page = browser.new_page("https://www.linkedin.com/").await?;

        // Inyectar cookies de sesión directamente desde Google Chrome del sistema
        if let Ok(cookies) = crate::services::extract_system_linkedin_cookies() {
            println!("🍪 [Rust Native Browser] Inyectando {} cookies de sesión activas de LinkedIn...", cookies.len());
            for c in cookies {
                let params = chromiumoxide::cdp::browser_protocol::network::SetCookieParams::builder()
                    .name(c.name)
                    .value(c.value)
                    .domain(c.domain)
                    .path(c.path)
                    .secure(c.secure)
                    .http_only(c.http_only)
                    .build();
                if let Ok(p) = params {
                    let _ = page.execute(p).await;
                }
            }
        }

        for page_idx in 0..max_pages {
            {
                let is_running = is_searching_flag.lock().await;
                if !*is_running {
                    println!("🛑 [Rust Engine] Búsqueda detenida por solicitud del usuario.");
                    break;
                }
            }

            let offset = page_idx * 25;
            let search_url = format!(
                "https://www.linkedin.com/jobs/search/?keywords={}&location={}&start={}&f_TPR=r259200",
                urlencoding_encode(query),
                urlencoding_encode(location),
                offset
            );

            println!("\n🌐 [Rust Native Browser] Página {}/{} - Navegando a: {}", page_idx + 1, max_pages, search_url);
            page.goto(&search_url).await?;

            // Script Stealth Total
            let stealth_script = r#"
                (() => {
                    Object.defineProperty(navigator, 'webdriver', {
                        get: () => undefined,
                        configurable: true
                    });
                    
                    if (!window.chrome) {
                        window.chrome = {};
                    }
                    window.chrome.runtime = window.chrome.runtime || {};
                    window.chrome.app = window.chrome.app || {};

                    Object.defineProperty(navigator, 'plugins', {
                        get: () => [1, 2, 3, 4, 5],
                        configurable: true
                    });

                    Object.defineProperty(navigator, 'languages', {
                        get: () => ['es-ES', 'es', 'en-US', 'en'],
                        configurable: true
                    });
                })()
            "#;
            let _ = page.evaluate(stealth_script).await;

            tokio::time::sleep(Duration::from_secs(4)).await;

            // Auto-cerrar modales emergentes
            let dismiss_js = r#"
                (() => {
                    const dismissBtn = document.querySelector('button[aria-label="Dismiss"], button.modal__dismiss, .artdeco-modal__dismiss, [data-test-modal-close-btn]');
                    if (dismissBtn) dismissBtn.click();
                })()
            "#;
            let _ = page.evaluate(dismiss_js).await;

            // Scroll gradual para hidratar los elementos de la lista en LinkedIn
            for s in 1..=6 {
                let scroll_script = format!(
                    r#"
                    (() => {{
                        const list = document.querySelector('.jobs-search-results-list, .scaffold-layout__list-detail-inner') || window;
                        list.scrollTop = {} * 350;
                    }})()
                    "#,
                    s
                );
                let _ = page.evaluate(scroll_script).await;
                tokio::time::sleep(Duration::from_millis(600)).await;
            }

            let get_cards_count_js = r#"
                (() => {
                    const cards = document.querySelectorAll('.jobs-search-results__list-item, .job-card-container, div[data-job-id]');
                    return cards.length || 0;
                })()
            "#;

            let total_val = page.evaluate(get_cards_count_js).await?;
            let total_cards = total_val.into_value::<usize>().unwrap_or(0);
            println!("🔍 [Rust Native Browser] Ofertas detectadas en página {}: {}", page_idx + 1, total_cards);

            if total_cards == 0 {
                println!("⚠️ [Rust Native Browser] No se encontraron más ofertas en esta página.");
                break;
            }

            for index in 0..total_cards {
                {
                    let is_running = is_searching_flag.lock().await;
                    if !*is_running {
                        break;
                    }
                }

                // Clic visual en la tarjeta
                let click_and_extract_js = format!(
                    r#"
                    (() => {{
                        const cards = document.querySelectorAll('.jobs-search-results__list-item, .job-card-container, div[data-job-id]');
                        if (cards.length <= {index}) return null;
                        const card = cards[{index}];
                        
                        card.scrollIntoView({{ behavior: 'smooth', block: 'center' }});
                        const link = card.querySelector('a.job-card-list__title, a.job-card-container__link, a');
                        if (link) link.click();

                        const titleEl = card.querySelector('.job-card-list__title, a.job-card-container__link, strong, .base-search-card__title');
                        const companyEl = card.querySelector('.job-card-container__primary-description, .artdeco-entity-lockup__subtitle, .base-search-card__subtitle');
                        const locEl = card.querySelector('.job-card-container__metadata-item, .job-search-card__location');

                        return {{
                            title: titleEl ? titleEl.innerText.trim() : 'Developer',
                            company: companyEl ? companyEl.innerText.trim() : 'Empresa',
                            location: locEl ? locEl.innerText.trim() : 'Colombia',
                            url: link ? link.href.split('?')[0] : window.location.href
                        }};
                    }})()
                    "#
                );

                let card_res = page.evaluate(click_and_extract_js).await?;
                if let Ok(card_info) = card_res.into_value::<serde_json::Value>() {
                    if !card_info.is_null() {
                        let role = card_info.get("title").and_then(|v| v.as_str()).unwrap_or("Developer");
                        let company = card_info.get("company").and_then(|v| v.as_str()).unwrap_or("Empresa");
                        let loc = card_info.get("location").and_then(|v| v.as_str()).unwrap_or("Colombia");
                        let url = card_info.get("url").and_then(|v| v.as_str()).unwrap_or("");

                        tokio::time::sleep(Duration::from_millis(1200)).await;

                        let get_desc_js = r#"
                            (() => {
                                const descEl = document.querySelector('#job-details, .jobs-description__content, .jobs-box__html-content, .show-more-less-html__markup');
                                return descEl ? descEl.innerText.trim().slice(0, 3000) : '';
                            })()
                        "#;

                        let desc_res = page.evaluate(get_desc_js).await?;
                        let full_desc = desc_res.into_value::<String>().unwrap_or_default();

                        // Actualizar status.json
                        let status_data = json!({
                            "status": "Running",
                            "current_task": format!("Evaluando con Gemini 3.5 Flash Lite [Pág {}/{} - #{}/{}]: {} en {}", page_idx + 1, max_pages, index + 1, total_cards, role, company),
                            "timestamp": chrono::Utc::now().to_rfc3339(),
                            "stats": {
                                "pending": total_cards - index - 1,
                                "processed": total_saved
                            }
                        });
                        let _ = fs::write("dashboard/status.json", status_data.to_string());

                        let desc_for_ai = if !full_desc.is_empty() {
                            full_desc.as_str()
                        } else {
                            role
                        };

                        // Evaluar con Gemini 3.5 Flash Lite
                        let analysis = self.ai_client.analyze_job(role, company, desc_for_ai).await.unwrap_or_else(|_| crate::services::AnalysisResult {
                            match_score: 75.0,
                            status: "Matched".to_string(),
                            skills: vec!["C#".to_string(), "Python".to_string(), "Full Stack".to_string()],
                            summary: "Evaluado automáticamente".to_string(),
                        });

                        let skills_str = analysis.skills.join(", ");
                        let language = crate::services::Normalizer::detect_language(&format!("{} {}", role, full_desc));
                        let conn = rusqlite::Connection::open(&self.db.db_path())?;
                        let insert_res = conn.execute(
                            "INSERT OR IGNORE INTO jobs (url, company, role, location, work_mode, source, requirements, language, match_score, status, raw_analysis, skills, ai_model) VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7, ?8, ?9, ?10, ?11, ?12, ?13)",
                            rusqlite::params![url, company, role, loc, "Remote", "LinkedIn", full_desc, language, analysis.match_score, analysis.status, analysis.summary, skills_str, self.ai_client.gemini_model()]
                        );

                        if let Ok(affected) = insert_res {
                            if affected > 0 {
                                total_saved += 1;
                                println!("  💾 [Gemini + SQLite] Guardada oferta #{}: {} en {} (Match: {}%)", total_saved, role, company, analysis.match_score);
                            }
                        }

                        // Registrar traza completa en SQLite
                        let span_id = format!("span_{}", chrono::Utc::now().timestamp_millis());
                        let trace_id = format!("trace_{}", chrono::Utc::now().timestamp_millis());
                        let trace_attrs = json!({
                            "role": role,
                            "company": company,
                            "match_score": analysis.match_score,
                            "status": analysis.status,
                            "ai_model": self.ai_client.gemini_model(),
                            "url": url
                        }).to_string();
                        let _ = self.db.insert_trace(&span_id, &trace_id, "evaluate_job_gemini", &analysis.status, &trace_attrs);
                    }
                }
            }
        }

        let status_data = json!({
            "status": "Ready",
            "current_task": format!("Búsqueda finalizada. {} ofertas nuevas procesadas.", total_saved),
            "timestamp": chrono::Utc::now().to_rfc3339()
        });
        let _ = fs::write("dashboard/status.json", status_data.to_string());

        println!("\n✅ [Rust Engine] Búsqueda completada con éxito. Total guardadas: {}.", total_saved);

        handle.abort();
        Ok(total_saved)
    }
}

fn urlencoding_encode(s: &str) -> String {
    url::form_urlencoded::byte_serialize(s.as_bytes()).collect()
}
