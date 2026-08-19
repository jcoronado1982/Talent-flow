use crate::db::DatabaseRepository;
use crate::services::{AiClient, NativeBrowserScraper};
use axum::{
    extract::{Path as AxumPath, Query, State},
    http::{Method, StatusCode},
    response::{
        sse::{Event, KeepAlive, Sse},
        Html, IntoResponse, Response,
    },
    routing::{get, post},
    Json, Router,
};
use futures_util::stream::Stream;
use serde::Deserialize;
use serde_json::json;
use std::convert::Infallible;
use std::fs;
use std::net::SocketAddr;
use std::path::Path;
use std::sync::Arc;
use std::time::Duration;
use tokio::sync::Mutex;
use tower_http::cors::{Any, CorsLayer};
use tower_http::services::ServeDir;

#[derive(Clone)]
pub struct AppState {
    pub db: DatabaseRepository,
    pub is_searching: Arc<Mutex<bool>>,
    pub is_applying: Arc<Mutex<bool>>,
    pub ai_client: AiClient,
    pub profile: crate::domain::models::ProfileConfig,
    pub base_dir: std::path::PathBuf,
}

#[derive(Deserialize)]
pub struct SearchQuery {
    pub mode: Option<String>,
}

#[derive(Deserialize)]
pub struct ApplyQuery {
    /// Shadow mode: fills every form step but never clicks the final Submit button.
    /// Defaults to false (matching Python's ApplyBotSupervisor.run(dry_run=False)
    /// default) — pass `?dry_run=true` to audit safely first.
    pub dry_run: Option<bool>,
}

#[derive(Deserialize)]
pub struct AnswerPayload {
    pub answer: String,
}

#[derive(Deserialize)]
pub struct BulkUpdatePayload {
    pub job_ids: Vec<i64>,
    pub new_status: String,
}

pub async fn start_dashboard_server(
    db: DatabaseRepository,
    port: u16,
    profile: crate::domain::models::ProfileConfig,
) -> anyhow::Result<()> {
    let base_dir = std::env::current_dir().unwrap_or_else(|_| std::path::PathBuf::from("."));
    let state = AppState {
        db,
        is_searching: Arc::new(Mutex::new(false)),
        is_applying: Arc::new(Mutex::new(false)),
        ai_client: AiClient::with_profile(Some(&profile)),
        profile,
        base_dir,
    };

    // Reset initial status.json on startup so the UI never starts in a stale 'Running' state
    let initial_status = json!({
        "status": "Ready",
        "current_task": "Listo para buscar o aplicar",
        "current_role": "Ready",
        "current_location": "Colombia",
        "processing_count": 0,
        "current_job_index": 0,
        "jobs_in_current_batch": 0,
        "current_combination_index": 0,
        "total_combinations": 1,
        "logs": [
            "Sistema TalentFlow 100% Rust conectado y listo.",
            "Esperando orden de búsqueda o postulación."
        ]
    });
    let _ = fs::write("dashboard/status.json", initial_status.to_string());

    let cors = CorsLayer::new()
        .allow_origin(Any)
        .allow_methods([Method::GET, Method::POST, Method::OPTIONS])
        .allow_headers(Any);

    let static_service = ServeDir::new("dashboard/static");
    // Svelte's SvelteKit static build (see dashboard-svelte/). Mirrors how
    // dashboard/main.py mounts `dashboard-svelte/build/_app` — if the app hasn't
    // been built yet this directory just won't exist and requests 404, falling
    // back to the legacy static HTML served by handle_index/handle_reports.
    let svelte_assets_service = ServeDir::new("dashboard-svelte/build/_app");

    let app = Router::new()
        .route("/", get(handle_index))
        .route("/inspect", get(handle_index))
        .route("/inspection", get(handle_index))
        .route("/reports", get(handle_reports))
        .route("/status.json", get(handle_status_json))
        .route("/events", get(handle_events))
        .route("/check_interaction", get(handle_check_interaction))
        .route("/submit_answer", post(handle_submit_answer))
        .route("/search", post(handle_start_search))
        .route("/apply", post(handle_start_apply))
        .route("/stop", post(handle_stop))
        .route("/api/clear_jobs", post(handle_clear_jobs))
        .route("/api/inspection/clear", post(handle_clear_inspection))
        .route("/api/jobs/bulk_update", post(handle_bulk_update))
        .route("/api/jobs/:id/reanalyze", post(handle_reanalyze_job))
        .route("/api/audit/:span_id", post(handle_audit_span))
        .route("/api/audit/logs", get(handle_audit_logs))
        .route("/api/stats", get(handle_stats))
        .route("/api/jobs", get(handle_jobs))
        .route("/api/status", get(handle_status))
        .route("/api/pending_count", get(handle_pending_count))
        .nest_service("/static", static_service)
        .nest_service("/_app", svelte_assets_service)
        .layer(cors)
        .with_state(state);

    let addr = SocketAddr::from(([0, 0, 0, 0], port));
    println!("🚀 Dashboard web en Rust (100% Nativo) iniciado:");
    println!("👉 Abre tu navegador en: http://localhost:{}", port);

    let listener = tokio::net::TcpListener::bind(addr).await?;
    axum::serve(listener, app).await?;

    Ok(())
}

async fn handle_index() -> Response {
    // Prefer the SvelteKit build (the current frontend, see dashboard-svelte/) and
    // fall back to the legacy static HTML if it hasn't been built yet.
    let svelte_path = Path::new("dashboard-svelte/build/index.html");
    let legacy_path = Path::new("dashboard/index.html");

    let path = if svelte_path.exists() { svelte_path } else { legacy_path };

    if path.exists() {
        match fs::read_to_string(path) {
            Ok(content) => Html(content).into_response(),
            Err(e) => (StatusCode::INTERNAL_SERVER_ERROR, format!("Error: {}", e)).into_response(),
        }
    } else {
        Html("<h1>🤖 TalentFlow Dashboard (Rust Edition)</h1><p>Ni dashboard-svelte/build/index.html ni dashboard/index.html fueron encontrados</p>".to_string()).into_response()
    }
}

async fn handle_audit_logs(State(state): State<AppState>) -> impl IntoResponse {
    match state.db.get_audit_jobs() {
        Ok(jobs) => Json(jobs).into_response(),
        Err(e) => (StatusCode::INTERNAL_SERVER_ERROR, Json(json!({"status": "error", "message": e.to_string()}))).into_response(),
    }
}

async fn handle_reports() -> Response {
    let path = Path::new("dashboard/reports.html");
    if path.exists() {
        match fs::read_to_string(path) {
            Ok(content) => Html(content).into_response(),
            Err(e) => (StatusCode::INTERNAL_SERVER_ERROR, format!("Error: {}", e)).into_response(),
        }
    } else {
        Html("<h1>📊 TalentFlow Reportes</h1><p>dashboard/reports.html no encontrado</p>".to_string()).into_response()
    }
}

async fn handle_status_json() -> impl IntoResponse {
    let path = Path::new("dashboard/status.json");
    if path.exists() {
        if let Ok(content) = fs::read_to_string(path) {
            if let Ok(val) = serde_json::from_str::<serde_json::Value>(&content) {
                return Json(val).into_response();
            }
        }
    }
    Json(json!({
        "status": "Ready",
        "current_task": "Esperando comandos del usuario...",
        "timestamp": chrono::Utc::now().to_rfc3339()
    })).into_response()
}

async fn handle_start_search(
    State(state): State<AppState>,
    Query(query): Query<SearchQuery>,
) -> impl IntoResponse {
    let mut searching = state.is_searching.lock().await;
    if *searching {
        return (
            StatusCode::CONFLICT,
            Json(json!({"status": "error", "message": "Ya hay una búsqueda en progreso"})),
        );
    }
    *searching = true;

    let _ = fs::remove_file("user_data_auth/SingletonLock");
    let _ = fs::remove_file("user_data_auth_profile_1/SingletonLock");
    let _ = fs::remove_file("user_data_safe/SingletonLock");
    let _ = fs::remove_file("user_data/SingletonLock");
    let _ = fs::remove_file("dashboard/stop.signal");

    let status_data = json!({
        "status": "Running",
        "current_task": "Abriendo navegador Chromium en Rust y buscando ofertas en LinkedIn...",
        "timestamp": chrono::Utc::now().to_rfc3339(),
        "stats": {
            "pending": 0,
            "processed": 0
        }
    });
    let _ = fs::write("dashboard/status.json", status_data.to_string());

    let db_clone = state.db.clone();
    let searching_flag = state.is_searching.clone();

    let target_roles = state.profile.target_roles.clone().unwrap_or_else(|| vec!["Developer".to_string()]);

    tokio::spawn(async move {
        println!("🤖 [Rust Engine] Ejecutando búsqueda masiva en LATAM con Chromium...");
        let scraper = NativeBrowserScraper::new(db_clone);
        
        let countries = vec!["Brazil", "Argentina", "Uruguay", "Chile", "Mexico", "Colombia"];
        let mut global_count = 0;

        for country in &countries {
            for role in &target_roles {
                let flag = searching_flag.lock().await;
                if !*flag {
                    println!("🛑 Búsqueda detenida por el usuario.");
                    break;
                }
                drop(flag);

                println!("📍 Buscando Rol '{}' en {}...", role, country);
                let res = scraper.run_linkedin_continuous_search(role, country, searching_flag.clone()).await;
                
                match res {
                    Ok(count) => {
                        global_count += count;
                        println!("✅ {} ofertas guardadas en {}.", count, country);
                    }
                    Err(e) => {
                        eprintln!("❌ [Rust Engine] Error en búsqueda de navegador para {} en {}: {}", role, country, e);
                    }
                }
                // Pequeña pausa entre iteraciones
                tokio::time::sleep(std::time::Duration::from_secs(5)).await;
            }
        }
        
        println!("✅ [Rust Engine] Búsqueda masiva finalizada. {} ofertas totales guardadas en SQLite.", global_count);
        let mut flag = searching_flag.lock().await;
        *flag = false;
    });

    (
        StatusCode::OK,
        Json(json!({
            "status": "running",
            "engine": "100% Native Rust (Chromiumoxide + Tokio)",
            "mode": query.mode.unwrap_or_else(|| "scan".to_string())
        })),
    )
}

async fn handle_start_apply(State(state): State<AppState>, Query(query): Query<ApplyQuery>) -> impl IntoResponse {
    let mut applying = state.is_applying.lock().await;
    if *applying {
        return (
            StatusCode::CONFLICT,
            Json(json!({"status": "error", "message": "Ya hay un proceso de aplicación en curso"})),
        );
    }
    let searching = state.is_searching.lock().await;
    if *searching {
        return (
            StatusCode::CONFLICT,
            Json(json!({"status": "error", "message": "Detén la búsqueda antes de iniciar el Apply bot"})),
        );
    }
    drop(searching);
    *applying = true;
    drop(applying);

    let dry_run = query.dry_run.unwrap_or(false);
    let _ = fs::remove_file("dashboard/stop.signal");

    let status_data = json!({
        "status": "Running",
        "current_task": if dry_run { "Ejecutando Auto-Apply en modo AUDITORÍA (Shadow Mode)..." } else { "Ejecutando proceso de Auto-Apply en Rust..." },
        "timestamp": chrono::Utc::now().to_rfc3339()
    });
    let _ = fs::write("dashboard/status.json", status_data.to_string());

    let db_clone = state.db.clone();
    let profile_clone = state.profile.clone();
    let base_dir_clone = state.base_dir.clone();
    let applying_flag = state.is_applying.clone();

    tokio::spawn(async move {
        println!("🤖 [Rust Engine] Ejecutando Apply Bot (dry_run={})...", dry_run);
        let res = crate::services::apply::run_apply_bot(db_clone, profile_clone, base_dir_clone, dry_run, applying_flag.clone()).await;
        match res {
            Ok(count) => println!("✅ [Rust Engine] Apply Bot finalizado. {} ofertas procesadas.", count),
            Err(e) => {
                eprintln!("❌ [Rust Engine] Error en Apply Bot: {}", e);
                let err_status = json!({
                    "status": "Ready",
                    "current_task": format!("Error en Apply Bot: {}", e),
                    "timestamp": chrono::Utc::now().to_rfc3339()
                });
                let _ = fs::write("dashboard/status.json", err_status.to_string());
            }
        }
        let mut flag = applying_flag.lock().await;
        *flag = false;
    });

    (
        StatusCode::OK,
        Json(json!({
            "status": "running",
            "engine": "Rust Native",
            "dry_run": dry_run
        })),
    )
}

async fn handle_stop(State(state): State<AppState>) -> impl IntoResponse {
    let mut searching = state.is_searching.lock().await;
    *searching = false;
    let mut applying = state.is_applying.lock().await;
    *applying = false;

    let _ = fs::write("dashboard/stop.signal", "stop");

    let status_data = json!({
        "status": "Ready",
        "current_task": "Detenido por el usuario",
        "timestamp": chrono::Utc::now().to_rfc3339()
    });
    let _ = fs::write("dashboard/status.json", status_data.to_string());

    println!("🛑 [Rust Engine] Proceso detenido por el usuario.");
    Json(json!({"status": "stopped"}))
}

async fn handle_clear_jobs(State(state): State<AppState>) -> impl IntoResponse {
    println!("🧹 [Rust Engine] Vaciando reporte y base de datos (DELETE FROM jobs)...");
    match state.db.clear_all_jobs() {
        Ok(_) => {
            let status_data = json!({
                "status": "Ready",
                "current_task": "Reporte y base de datos limpiados exitosamente.",
                "timestamp": chrono::Utc::now().to_rfc3339(),
                "stats": {
                    "pending": 0,
                    "processed": 0
                }
            });
            let _ = fs::write("dashboard/status.json", status_data.to_string());
            (StatusCode::OK, Json(json!({"status": "ok", "message": "Report cleared"})))
        }
        Err(e) => {
            eprintln!("❌ Error limpiando base de datos: {}", e);
            (StatusCode::INTERNAL_SERVER_ERROR, Json(json!({"status": "error", "message": e.to_string()})))
        }
    }
}

async fn handle_clear_inspection() -> impl IntoResponse {
    let status_data = json!({
        "status": "Ready",
        "current_task": "Vista de inspección limpia.",
        "timestamp": chrono::Utc::now().to_rfc3339()
    });
    let _ = fs::write("dashboard/status.json", status_data.to_string());
    Json(json!({"status": "ok"}))
}

async fn handle_bulk_update(
    State(state): State<AppState>,
    Json(payload): Json<BulkUpdatePayload>,
) -> impl IntoResponse {
    match state.db.bulk_update_status(&payload.job_ids, &payload.new_status) {
        Ok(_) => (StatusCode::OK, Json(json!({"status": "ok"}))),
        Err(e) => (StatusCode::INTERNAL_SERVER_ERROR, Json(json!({"status": "error", "message": e.to_string()}))),
    }
}

async fn handle_reanalyze_job(
    State(state): State<AppState>,
    AxumPath(job_id): AxumPath<i64>,
) -> impl IntoResponse {
    match state.db.get_job_by_id(job_id) {
        Ok(Some(job)) => {
            let desc = job.requirements.unwrap_or(job.role.clone());
            let analysis = state.ai_client.analyze_job(&job.role, &job.company, &desc).await.unwrap_or_else(|_| crate::services::AnalysisResult {
                match_score: 75.0,
                status: "Matched".to_string(),
                skills: vec!["Full Stack".to_string()],
                summary: "Re-análisis automático".to_string(),
            });

            let skills_str = analysis.skills.join(", ");
            let _ = state.db.update_job_analysis(job_id, analysis.match_score, &analysis.status, &analysis.summary, &skills_str);

            (StatusCode::OK, Json(json!({"status": "ok", "match_score": analysis.match_score})))
        }
        Ok(None) => (StatusCode::NOT_FOUND, Json(json!({"status": "error", "message": "Job not found"}))),
        Err(e) => (StatusCode::INTERNAL_SERVER_ERROR, Json(json!({"status": "error", "message": e.to_string()}))),
    }
}

async fn handle_audit_span(AxumPath(_span_id): AxumPath<String>) -> impl IntoResponse {
    Json(json!({"status": "ok", "valid": true}))
}

async fn handle_events(State(state): State<AppState>) -> Sse<impl Stream<Item = Result<Event, Infallible>>> {
    let stream = async_stream::stream! {
        let mut last_payload = String::new();
        loop {
            let mut status_data = if let Ok(content) = fs::read_to_string("dashboard/status.json") {
                serde_json::from_str::<serde_json::Value>(&content).unwrap_or_else(|_| json!({"status": "Ready"}))
            } else {
                json!({"status": "Ready"})
            };

            let now_epoch = chrono::Utc::now().timestamp_millis();
            if let Some(obj) = status_data.as_object_mut() {
                obj.insert("last_updated".to_string(), json!(now_epoch));
            }

            let stats = state.db.get_stats().unwrap_or_else(|_| crate::domain::models::StatsSummary {
                total_jobs: 0,
                matched_jobs: 0,
                discarded_jobs: 0,
                pending_jobs: 0,
                avg_match_score: 0.0,
            });

            let (recent, _) = state.db.get_filtered_jobs(&crate::db::JobFilter {
                status: Some("Matched".to_string()),
                page_size: Some(10),
                ..Default::default()
            }).unwrap_or_default();

            let recent_matches: Vec<serde_json::Value> = recent.into_iter().map(|j| {
                json!({
                    "id": j.id.unwrap_or(0),
                    "company": j.company,
                    "location": j.location.unwrap_or_else(|| "Colombia".to_string()),
                    "role": j.role.lines().next().unwrap_or(&j.role),
                    "date": j.created_at.clone().unwrap_or_else(|| "Reciente".to_string()),
                    "work_mode": "En remoto",
                    "created_at": j.created_at.unwrap_or_default(),
                    "match_score": j.match_score.unwrap_or(0.0),
                    "status": j.status
                })
            }).collect();

            let payload = json!({
                "status": status_data,
                "stats": {
                    "total_matches": stats.matched_jobs,
                    "total_jobs": stats.total_jobs,
                    "matched_jobs": stats.matched_jobs,
                    "discarded_jobs": stats.discarded_jobs,
                    "pending_jobs": stats.pending_jobs,
                    "avg_match_score": stats.avg_match_score,
                    "recent_matches": recent_matches,
                    "status_breakdown": {
                        "Matched": stats.matched_jobs,
                        "Discarded": stats.discarded_jobs,
                        "Pending": stats.pending_jobs
                    }
                },
                "pending_count": stats.pending_jobs
            });

            let payload_str = payload.to_string();
            if payload_str != last_payload {
                last_payload = payload_str.clone();
                yield Ok(Event::default().data(payload_str));
            }

            tokio::time::sleep(Duration::from_millis(500)).await;
        }
    };

    Sse::new(stream).keep_alive(KeepAlive::default())
}

async fn handle_check_interaction() -> impl IntoResponse {
    let path = Path::new("dashboard/interaction.json");
    if path.exists() {
        if let Ok(content) = fs::read_to_string(path) {
            if let Ok(val) = serde_json::from_str::<serde_json::Value>(&content) {
                return Json(val).into_response();
            }
        }
    }
    Json(json!({})).into_response()
}

async fn handle_submit_answer(Json(payload): Json<AnswerPayload>) -> impl IntoResponse {
    let response_data = json!({
        "status": "answered",
        "answer": payload.answer,
        "timestamp": chrono::Utc::now().to_rfc3339()
    });
    let _ = fs::write("dashboard/interaction.json", response_data.to_string());
    Json(json!({"status": "ok"}))
}

async fn handle_stats(State(state): State<AppState>) -> impl IntoResponse {
    match state.db.get_stats() {
        Ok(stats) => Json(json!({
            "status": "success",
            "data": stats
        })),
        Err(err) => Json(json!({
            "status": "error",
            "message": err.to_string()
        })),
    }
}

async fn handle_jobs(
    State(state): State<AppState>,
    Query(filter): Query<crate::db::repository::JobFilter>,
) -> impl IntoResponse {
    let page = filter.page.unwrap_or(1).max(1);
    let page_size = filter.page_size.unwrap_or(100).max(1);

    match state.db.get_filtered_jobs(&filter) {
        Ok((jobs, total)) => {
            let total_pages = if total > 0 { (total + page_size - 1) / page_size } else { 1 };
            Json(json!({
                "status": "success",
                "jobs": jobs,
                "data": jobs,
                "total": total,
                "page": page,
                "page_size": page_size,
                "total_pages": total_pages
            }))
        }
        Err(err) => Json(json!({
            "status": "error",
            "message": err.to_string(),
            "jobs": [],
            "total": 0,
            "page": 1,
            "page_size": page_size,
            "total_pages": 1
        })),
    }
}

async fn handle_pending_count(State(state): State<AppState>) -> impl IntoResponse {
    match state.db.get_stats() {
        Ok(stats) => Json(json!({
            "status": "success",
            "pending_count": stats.pending_jobs
        })),
        Err(err) => Json(json!({
            "status": "error",
            "message": err.to_string()
        })),
    }
}

async fn handle_status() -> impl IntoResponse {
    Json(json!({
        "status": "active",
        "engine": "100% Native Rust (Axum + Tokio + Chromiumoxide + SQLite WAL)",
        "version": "0.2.0"
    }))
}
