mod config;
mod db;
mod domain;
mod services;
mod dashboard;

use anyhow::Result;
use clap::{Parser, Subcommand};
use config::AppConfig;
use db::DatabaseRepository;
use services::AiClient;

#[derive(Parser)]
#[command(name = "talentflow")]
#[command(about = "TalentFlow - Engine de Búsqueda y Análisis de Empleos en Rust", long_about = None)]
struct Cli {
    #[command(subcommand)]
    command: Option<Commands>,
}

#[derive(Subcommand)]
enum Commands {
    /// Inicia el servidor Dashboard en el puerto 8001
    Dashboard {
        #[arg(short, long, default_value_t = 8001)]
        port: u16,
    },
    /// Muestra estadísticas de la base de datos talentflow.db
    Stats,
    /// Prueba la conexión con Gemini API y Steel Wasp
    TestAi,
    /// Prueba la extracción de cookies activas de LinkedIn desde Google Chrome del sistema
    TestCookies,
    /// Ejecuta la Tarea 1: Verificación estricta de Login y Supervisión de Identidad
    Step1Auth {
        /// Carpeta de perfil a usar (ej. user_data_safe o user_data_auth_profile_1)
        #[arg(long, default_value = "user_data_safe")]
        profile: String,
    },
    /// Ejecuta la Tarea 1 + Tarea 3: Inicia sesión, supervisa y recolecta ofertas en vivo
    Search {
        /// Carpeta de perfil a usar
        #[arg(long, default_value = "user_data_safe")]
        profile: String,
        /// Límite de vacantes a escanear por búsqueda
        #[arg(long, default_value_t = 10)]
        limit: usize,
        /// País específico a buscar (ej. Colombia, Uruguay, Argentina)
        #[arg(long, default_value = "Colombia")]
        country: String,
    },
    /// Ejecuta el análisis de IA sobre las vacantes pendientes en la base de datos
    Analyze {
        /// Forzar re-análisis de todas las vacantes (incluso las ya analizadas)
        #[arg(long)]
        re_analyze: bool,
    },
    /// Ejecuta el Apply Bot: aplica a las ofertas 'Matched' pendientes.
    /// ⚠️ Por defecto ENVÍA aplicaciones reales (igual que python -m src.apply_bot).
    /// Usa --dry-run para solo llenar los formularios sin enviarlos (modo auditoría).
    Apply {
        #[arg(long)]
        dry_run: bool,
    },
    /// Ejecuta el Apply Bot Directo para vacantes Externas: toma el external_link de la base de datos
    /// y aplica directamente en el portal externo sin pasar por LinkedIn.
    ApplyExternal {
        /// Modo auditoría (llena formularios sin enviar)
        #[arg(long)]
        dry_run: bool,
        /// Filtrar por ID específico de vacante
        #[arg(long)]
        job_id: Option<i64>,
        /// Filtrar por estado (ej. Matched, Manual, Failed o 'all')
        #[arg(long)]
        status: Option<String>,
        /// Límite de vacantes a procesar
        #[arg(long, default_value_t = 30)]
        limit: usize,
    },
    /// Diagnóstico de solo lectura: abre un perfil de Chrome, va a linkedin.com/feed,
    /// lee el nombre de la cuenta logueada y cierra. No busca ni aplica a nada.
    Whoami {
        /// Carpeta de perfil a inspeccionar (ej. user_data_auth_profile_1)
        #[arg(long)]
        profile: String,
    },
    /// Abre el navegador en una carpeta de perfil NUEVA y espera a que inicies sesión
    /// manualmente en LinkedIn. No escribe ni envía nada — solo espera y confirma.
    Login {
        /// Carpeta de perfil a crear/usar (ej. user_data_safe)
        #[arg(long, default_value = "user_data_safe")]
        profile: String,
    },
    /// Abre Chrome en modo humano (perfil persistente, puerto CDP 9222) y lo deja abierto
    /// para que un cliente MCP (chrome-devtools-mcp) se conecte con --browserUrl y lo controle
    /// directamente. Termina cuando aparece debug/close_browser.signal o pasan 30 minutos.
    DebugBrowser {
        #[arg(long, default_value = "user_data_safe")]
        profile: String,
        /// URL inicial a abrir (opcional)
        #[arg(long)]
        url: Option<String>,
    },
}

#[tokio::main]
async fn main() -> Result<()> {
    // Cargar variables de entorno desde .env
    dotenvy::dotenv().ok();

    // Inicializar subscriptor de logs
    tracing_subscriber::fmt::init();

    tokio::spawn(async {
        use std::io::Write;
        loop {
            tokio::time::sleep(std::time::Duration::from_millis(300)).await;
            let _ = std::io::stdout().flush();
        }
    });

    println!("====================================================");
    println!(" 🦀 TalentFlow Engine (100% Native Rust v0.2.0)");
    println!("====================================================\n");

    let app_config = AppConfig::load()?;
    let db = DatabaseRepository::new(&app_config.db_path)?;

    let cli = Cli::parse();

    match cli.command {
        Some(Commands::Dashboard { port }) => {
            dashboard::start_dashboard_server(db, port, app_config.profile.clone()).await?;
        }
        Some(Commands::Stats) => {
            print_stats(&db)?;
        }
        Some(Commands::Step1Auth { profile }) => {
            let profile_path = std::env::current_dir()?.join(&profile);
            let expected_name = app_config.profile.personal_info.as_ref().and_then(|p| p.full_name.as_deref());

            println!("🚀 [TAREA 1] Ejecutando Login con Supervisión Forense...");
            println!("👤 Usuario esperado en configuración: {:?}", expected_name.unwrap_or("No configurado"));
            
            match services::verify_linkedin_session(&profile_path, expected_name).await? {
                Some((browser, handle)) => {
                    println!("\n🎉 [RESULTADO] Tarea 1 SUPERADA con ÉXITO.");
                    println!("   El Supervisor validó la identidad y el navegador está listo.");
                    tokio::time::sleep(std::time::Duration::from_secs(2)).await;
                    services::browser::close_browser(browser, handle).await;
                }
                None => {
                    println!("\n🛑 [RESULTADO] Tarea 1 DETENIDA por el Supervisor / Diagnóstico.");
                    println!("   Revisa 'logs/audit.jsonl' para el informe forense detallado.");
                }
            }
        }
        Some(Commands::Search { profile, limit, country }) => {
            let profile_path = std::env::current_dir()?.join(&profile);
            let expected_name = app_config.profile.personal_info.as_ref().and_then(|p| p.full_name.as_deref());

            println!("🚀 [TAREA 1 + 3] Ejecutando Flujo Completo de Búsqueda Supervisada...");
            println!("👤 Verificando usuario: {:?}", expected_name.unwrap_or("No configurado"));
            println!("📍 País objetivo: {}", country);
            
            // 1. Paso 1: Autenticación con Supervisor
            let auth_res = services::verify_linkedin_session(&profile_path, expected_name).await?;
            if auth_res.is_none() {
                println!("\n🛑 Flujo detenido en el Paso 1. No se puede iniciar la búsqueda sin sesión válida.");
                return Ok(());
            }

            let (mut browser, handle) = auth_res.unwrap();
            println!("\n✅ [Paso 1 Aprobado] Manteniendo navegador abierto y saltando a la Búsqueda de Ofertas...");

            // 2. Paso 3: Búsqueda y Recolección
            let saved = services::search::run_job_search(&mut browser, &app_config, &db, limit, Some(&country)).await?;

            println!("\n🎉 [RESULTADO] Búsqueda finalizada con éxito.");
            println!("   📥 Total de nuevas ofertas guardadas en DB: {}", saved);
            print_stats(&db)?;

            services::browser::close_browser(browser, handle).await;
        }
        Some(Commands::Analyze { re_analyze }) => {
            let conn = rusqlite::Connection::open(db.db_path())?;
            if re_analyze {
                conn.execute("UPDATE jobs SET status = 'Pending', match_score = NULL, raw_analysis = NULL, skills = NULL;", [])?;
                println!("🧹 [Limpieza] Todas las evaluaciones previas han sido limpiadas.");
                println!("🧠 Re-analizando todas las vacantes con el nuevo Prompt de ADN Inteligente...\n");
            } else {
                println!("🧠 [Paso 4: Análisis] Procesando vacantes en estado 'Pending' con ADN Inteligente...\n");
            }

            let mut stmt = conn.prepare("SELECT id, role, company, requirements, url FROM jobs WHERE status = 'Pending' ORDER BY id ASC")?;
            let pending_jobs = stmt.query_map([], |row| {
                Ok((
                    row.get::<_, i64>(0)?,
                    row.get::<_, String>(1)?,
                    row.get::<_, String>(2)?,
                    row.get::<_, Option<String>>(3)?,
                    row.get::<_, String>(4)?,
                ))
            })?.collect::<Result<Vec<_>, _>>()?;

            if pending_jobs.is_empty() {
                println!("✅ No hay vacantes pendientes por analizar. Usa --re-analyze para forzar re-análisis.");
                return Ok(());
            }

            println!("📊 Total de vacantes a evaluar: {}", pending_jobs.len());
            let ai_client = AiClient::with_profile(Some(&app_config.profile));

            for (idx, (id, role, company, req_opt, _url)) in pending_jobs.into_iter().enumerate() {
                let req_text = req_opt.unwrap_or_else(|| role.clone());
                println!("\n🔍 [{:02}/{:02}] Evaluando: '{}' @ '{}'", idx + 1, idx + 1, role.lines().next().unwrap_or(&role), company);
                
                match ai_client.analyze_job(&role, &company, &req_text).await {
                    Ok(result) => {
                        let skills_str = result.skills.join(", ");
                        db.update_job_analysis(id, result.match_score, &result.status, &result.summary, &skills_str)?;
                        
                        let badge = if result.match_score >= 70.0 { "🌟 [MATCH ALTO]" } else if result.match_score >= 50.0 { "⚖️ [PARCIAL]" } else { "❌ [DESCARTE]" };
                        println!("   {} Score: {:.0}% | Estado: {} | Skills: [{}]", badge, result.match_score, result.status, skills_str);
                        println!("   💡 Razonamiento: {}", result.summary);
                    }
                    Err(e) => {
                        eprintln!("   ⚠️ Error evaluando vacante #{}: {}", id, e);
                    }
                }
            }

            println!("\n🎉 [RESULTADO] Evaluación masiva completada con éxito.");
            print_stats(&db)?;
        }
        Some(Commands::TestAi) => {
            println!("🔄 Probando conexión con el motor de IA (Gemini / Steel Wasp / Local)...");
            let ai_client = AiClient::with_profile(Some(&app_config.profile));
            match ai_client.analyze_job("Senior .NET / C# Software Architect", "TechCorp", "10+ years experience, C#, .NET Core, SQL Server, Microservices, React, Angular").await {
                Ok(result) => {
                    println!("\n✅ Respuesta exitosa del motor de IA:");
                    println!("  Match Score: {}%", result.match_score);
                    println!("  Status:      {}", result.status);
                    println!("  Skills:      {:?}", result.skills);
                    println!("  Resumen:     {}", result.summary);
                }
                Err(err) => {
                    println!("❌ Error en motor de IA: {}", err);
                }
            }
        }
        Some(Commands::TestCookies) => {
            println!("🔄 Extrayendo cookies de LinkedIn directamente de Google Chrome del sistema...");
            match services::extract_system_linkedin_cookies() {
                Ok(cookies) => {
                    println!("✅ Total de cookies extraídas: {}", cookies.len());
                    for c in &cookies {
                        if c.name == "li_at" || c.name == "JSESSIONID" || c.name == "bcookie" {
                            println!("  🔑 {}: {}... (Domain: {})", c.name, &c.value.chars().take(15).collect::<String>(), c.domain);
                        }
                    }
                }
                Err(e) => println!("❌ Error extrayendo cookies: {}", e),
            }
        }
        Some(Commands::Whoami { profile }) => {
            let profile_path = std::env::current_dir()?.join(&profile);
            if !profile_path.exists() {
                println!("❌ La carpeta de perfil '{}' no existe.", profile);
                return Ok(());
            }
            println!("🔎 Abriendo perfil '{}' (solo lectura, no busca ni aplica a nada)...", profile);
            let (browser, handle) = services::browser::launch_browser_with_profile(&profile_path).await?;
            let page = browser.new_page("https://www.linkedin.com/in/me/").await?;
            tokio::time::sleep(std::time::Duration::from_secs(4)).await;
            let title = page.get_title().await.ok().flatten().unwrap_or_default();
            let url = page.url().await.ok().flatten().unwrap_or_default();
            println!("👤 Perfil '{}' → título de página: '{}' (URL final: {})", profile, title, url);
            if title.to_lowercase().contains("login") || url.contains("/login") || url.contains("/checkpoint") {
                println!("⚠️ No hay sesión activa válida en este perfil (pide login o verificación).");
            }
            services::browser::close_browser(browser, handle).await;
        }
        Some(Commands::Login { profile }) => {
            let profile_path = std::env::current_dir()?.join(&profile);
            std::fs::create_dir_all(&profile_path)?;
            println!("🔐 Abriendo perfil nuevo '{}' en LinkedIn login...", profile);
            println!("👉 Inicia sesión manualmente con tu cuenta (usuario, contraseña, verificación/2FA si aplica).");
            println!("⏳ Esperando hasta 10 minutos a que la sesión llegue a linkedin.com/feed/...\n");

            let (browser, handle) = services::browser::launch_browser_with_profile(&profile_path).await?;
            let page = browser.new_page("https://www.linkedin.com/login").await?;

            let max_wait_secs = 600;
            let mut waited = 0;
            let mut reached_feed = false;
            while waited < max_wait_secs {
                tokio::time::sleep(std::time::Duration::from_secs(2)).await;
                waited += 2;
                let current_url = page.url().await.ok().flatten().unwrap_or_default();
                if current_url.contains("linkedin.com/feed") {
                    reached_feed = true;
                    break;
                }
                if waited % 20 == 0 {
                    println!("   ⏳ Aún esperando... ({}s) — URL actual: {}", waited, current_url);
                }
            }

            if reached_feed {
                tokio::time::sleep(std::time::Duration::from_secs(2)).await;
                let _ = page.goto("https://www.linkedin.com/in/me/").await;
                tokio::time::sleep(std::time::Duration::from_secs(3)).await;
                let title = page.get_title().await.ok().flatten().unwrap_or_default();
                tokio::time::sleep(std::time::Duration::from_secs(2)).await;
                println!("\n✅ Sesión detectada y guardada en '{}'.", profile);
                println!("👤 Cuenta confirmada: '{}'", title);
                println!("   A partir de ahora, usa --profile {} (o configúralo como perfil por defecto) para búsqueda y auto-apply.", profile);
            } else {
                println!("\n⚠️ No se detectó login en {} segundos. Cierra y vuelve a intentar con: cargo run -- login --profile {}", max_wait_secs, profile);
            }

            services::browser::close_browser(browser, handle).await;
        }
        Some(Commands::DebugBrowser { profile, url }) => {
            let profile_path = std::env::current_dir()?.join(&profile);
            std::fs::create_dir_all(&profile_path)?;
            let signal_path = std::env::current_dir()?.join("debug").join("close_browser.signal");
            std::fs::create_dir_all(signal_path.parent().unwrap())?;
            let _ = std::fs::remove_file(&signal_path);

            println!("🔎 Abriendo Chrome en modo humano sobre el perfil '{}' (puerto CDP 9222)...", profile);
            let (browser, handle) = services::browser::launch_browser_with_profile(&profile_path).await?;
            let page = browser.new_page(url.as_deref().unwrap_or("about:blank")).await?;
            let _ = services::browser::inject_stealth_scripts(&page).await;

            println!("✅ Chrome listo en http://127.0.0.1:9222 — conecta un cliente MCP con --browserUrl http://127.0.0.1:9222");
            println!("🛑 Para cerrarlo: touch debug/close_browser.signal  (o espera 30 minutos de inactividad)");

            let max_wait_secs: u64 = 30 * 60;
            let mut waited = 0u64;
            while waited < max_wait_secs {
                if signal_path.exists() {
                    println!("🛑 Señal de cierre detectada.");
                    break;
                }
                tokio::time::sleep(std::time::Duration::from_secs(2)).await;
                waited += 2;
            }
            let _ = std::fs::remove_file(&signal_path);
            services::browser::close_browser(browser, handle).await;
            println!("✅ Chrome cerrado.");
        }
        Some(Commands::Apply { dry_run }) => {
            let mode = if dry_run { "AUDITORÍA (dry-run)" } else { "REAL (enviará aplicaciones)" };
            println!("🤖 Iniciando Apply Bot en modo {}...", mode);
            let flag = std::sync::Arc::new(tokio::sync::Mutex::new(true));
            let processed = services::apply::run_apply_bot(db, app_config.profile.clone(), app_config.base_dir.clone(), dry_run, flag).await?;
            println!("✅ Apply Bot finalizado. {} ofertas procesadas.", processed);
        }
        Some(Commands::ApplyExternal { dry_run, job_id, status, limit }) => {
            let mode = if dry_run { "AUDITORÍA (dry-run)" } else { "REAL (enviará aplicaciones)" };
            println!("🌐 Iniciando Apply Bot Directo para Vacantes Externas en modo {}...", mode);
            if let Some(id) = job_id {
                println!("🎯 Objetivo específico: Vacante ID #{}", id);
            }
            if let Some(ref s) = status {
                println!("🔎 Filtro de estado: {}", s);
            }
            let flag = std::sync::Arc::new(tokio::sync::Mutex::new(true));
            let processed = services::apply::run_external_apply_bot(
                db,
                app_config.profile.clone(),
                app_config.base_dir.clone(),
                dry_run,
                job_id,
                status,
                limit,
                flag,
            ).await?;
            println!("✅ Apply Bot Directo Externo finalizado. {} ofertas procesadas.", processed);
        }
        None => {
            print_stats(&db)?;
            println!("💡 Iniciando Servidor Web del Dashboard en Rust (puerto 8001)...");
            println!("   Para ver las opciones completas ejecuta: cargo run -- --help\n");
            dashboard::start_dashboard_server(db, 8001, app_config.profile.clone()).await?;
        }
    }

    Ok(())
}

fn print_stats(db: &DatabaseRepository) -> Result<()> {
    let stats = db.get_stats()?;
    println!("📊 Estadísticas Actuales en talentflow.db:");
    println!(" -----------------------------------------");
    println!("  Total Vacantes:    {}", stats.total_jobs);
    println!("  Vacantes Matched:  {}", stats.matched_jobs);
    println!("  Vacantes Descarte: {}", stats.discarded_jobs);
    println!("  Vacantes Pendientes: {}", stats.pending_jobs);
    println!("  Match Score Promedio: {:.2}%", stats.avg_match_score);
    println!(" -----------------------------------------\n");
    Ok(())
}
