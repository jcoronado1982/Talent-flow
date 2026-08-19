use crate::services::audit::log_audit_event;
use anyhow::Result;
use chromiumoxide::browser::Browser;
use std::path::Path;
use std::time::Duration;
use tokio::task::JoinHandle;
use tokio::time::timeout;

pub async fn verify_linkedin_session(
    profile_dir: &Path,
    expected_user_name: Option<&str>,
) -> Result<Option<(Browser, JoinHandle<()>)>> {
    println!("📡 [Paso 1: Acción] Iniciando acceso a LinkedIn con perfil: {:?}", profile_dir);
    
    // 1. Launch Browser
    let launch_result = crate::services::browser::launch_browser_with_profile(profile_dir).await;
    if let Err(e) = launch_result {
        log_audit_event(
            "PASO_1_LOGIN", "Lanzar navegador Chrome", "FAIL", "CHROME_LAUNCH_ERROR",
            &format!("Error al intentar iniciar Chrome: {}", e),
            None, None, "Proceso abortado antes de iniciar.", "Revisar procesos zombis."
        );
        return Ok(None);
    }
    let (mut browser, handle) = launch_result.unwrap();

    // 2. Open LinkedIn Feed (La Acción)
    let page = match browser.new_page("https://www.linkedin.com/feed/").await {
        Ok(p) => p,
        Err(e) => {
            log_audit_event(
                "PASO_1_LOGIN", "Abrir linkedin.com/feed", "FAIL", "PAGE_ERROR",
                &format!("No se pudo crear pestaña: {}", e),
                None, None, "Abortado.", "Verificar puertos de debugging."
            );
            handle.abort();
            let _ = browser.close().await;
            return Ok(None);
        }
    };

    let wait_future = page.wait_for_navigation();
    let _ = timeout(Duration::from_secs(10), wait_future).await;
    tokio::time::sleep(Duration::from_secs(3)).await;

    let current_url = page.url().await.unwrap_or_default().unwrap_or_default();
    
    // Si la acción básica de carga falló (redirigió a login o checkpoint)
    if current_url.contains("linkedin.com/login") || current_url.contains("session-redirect") {
        log_audit_event(
            "PASO_1_LOGIN", "Acceso inicial", "FAIL", "NO_ACTIVE_SESSION",
            &format!("Redirigido a: {}", current_url), None, None,
            "Deteniendo flujo.", "Ejecutar 'talentflow login'."
        );
        handle.abort();
        let _ = browser.close().await;
        return Ok(None);
    } else if current_url.contains("/checkpoint/") || current_url.contains("/challenge/") {
        log_audit_event(
            "PASO_1_LOGIN", "Acceso inicial", "FAIL", "SECURITY_CHECKPOINT",
            "LinkedIn solicitó 2FA/CAPTCHA.", None, None,
            "Deteniendo flujo.", "Resolver reto manualmente."
        );
        handle.abort();
        let _ = browser.close().await;
        return Ok(None);
    }

    // ==============================================================================
    // 👁️ SUPERVISOR DE IDENTIDAD Y DOBLE VERIFICACIÓN
    // ==============================================================================
    println!("🕵️ [Paso 1: Supervisor] Verificando identidad de la sesión conectada...");
    
    let _ = page.goto("https://www.linkedin.com/in/me/").await;
    tokio::time::sleep(Duration::from_secs(4)).await; // Esperar redirección al perfil real
    
    let profile_url = page.url().await.unwrap_or_default().unwrap_or_default();
    let page_title = page.get_title().await.unwrap_or_default().unwrap_or_default();
    
    // Si el título es genérico o pide login, era un falso positivo.
    if page_title.to_lowercase().contains("login") || page_title.to_lowercase().contains("sign in") || profile_url.contains("/login") {
         log_audit_event(
            "PASO_1_LOGIN_SUPERVISOR", "Verificación de Identidad", "FAIL", "GHOST_SESSION",
            "El sistema parecía estar en el feed pero la sesión era de invitado o expiró silenciosamente.",
            None, None, "Cerrando navegador por seguridad.", "Renovar sesión con 'talentflow login'."
        );
        handle.abort();
        let _ = browser.close().await;
        return Ok(None);
    }

    // Si pasamos un nombre esperado (ej. desde config), el supervisor compara:
    if let Some(expected_name) = expected_user_name {
        // Normalizamos a minúsculas para comparar
        if !page_title.to_lowercase().contains(&expected_name.to_lowercase()) {
             let msg = format!("IDENTIDAD INCORRECTA. Esperaba: '{}', pero la cuenta activa es: '{}'", expected_name, page_title);
             log_audit_event(
                "PASO_1_LOGIN_SUPERVISOR", "Validación Cruzada de Usuario", "FAIL", "IDENTITY_MISMATCH",
                &msg, None, None, "Abortando. No se puede continuar con la cuenta equivocada.", "Cambiar perfil de Chrome o iniciar sesión con la cuenta correcta."
            );
            handle.abort();
            let _ = browser.close().await;
            return Ok(None);
        }
    }

    // Si todo está correcto, el Supervisor aprueba la tarea.
    log_audit_event(
        "PASO_1_LOGIN_SUPERVISOR",
        "Auditoría de Identidad Exitosa",
        "OK",
        "VERIFIED",
        &format!("Acceso verificado. Actuando bajo la cuenta: '{}' (Perfil: {})", page_title.replace(" | LinkedIn", ""), profile_url),
        None, None,
        "Supervisor aprueba avanzar al Paso 2.",
        ""
    );

    Ok(Some((browser, handle)))
}
