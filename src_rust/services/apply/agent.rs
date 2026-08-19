//! Gemini-driven application agent.
//!
//! Why this exists: every previous failure in the apply pipeline came from the same root
//! cause — hardcoded label lists and CSS selectors. In a single session that produced four
//! separate bugs (English-only aria-labels, a footer-scoped element search, a missing
//! hydration wait, and an APPLY_LABELS list that lacked the bare word "Apply"). There are
//! thousands of ATS products and every company names its controls differently, so no list
//! can ever be complete.
//!
//! This module inverts the design: instead of the code deciding what each control means, it
//! hands the model a semantic snapshot of whatever is on screen and asks for ONE action at a
//! time. Nothing here knows about LinkedIn, BairesDev or any other site.
//!
//! Actions are a closed vocabulary executed over CDP. The model never runs code; it chooses
//! among verbs, and every target is a `data-tf-id` assigned by the snapshot — so a
//! hallucinated id simply fails to resolve instead of clicking something arbitrary.

use anyhow::Result;
use chromiumoxide::Page;
use serde::{Deserialize, Serialize};
use serde_json::Value;
use std::time::Duration;

/// One interactive element the agent can act on.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct AgentElement {
    pub id: String,
    /// "text" | "select" | "checkbox" | "radio" | "file" | "button" | "link"
    pub kind: String,
    pub label: String,
    #[serde(default)]
    pub value: String,
    #[serde(default)]
    pub options: Vec<String>,
    #[serde(default)]
    pub required: bool,
    #[serde(default)]
    pub error: Option<String>,
}

/// What the agent can see right now.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct PageSnapshot {
    pub url: String,
    pub title: String,
    pub fields: Vec<AgentElement>,
    pub actions: Vec<AgentElement>,
    /// Trimmed visible text, so the model can read confirmations, validation messages and
    /// instructions that are not attached to any control.
    pub text: String,
}

impl PageSnapshot {
    /// Compact signature used to notice that a step did not advance.
    pub fn fingerprint(&self) -> String {
        let mut s = String::from(&self.url);
        for f in &self.fields {
            s.push('|');
            s.push_str(&f.id);
            s.push(':');
            s.push_str(&f.label);
            s.push('=');
            s.push_str(&f.value);
        }
        for a in &self.actions {
            s.push('|');
            s.push_str(&a.label);
        }
        s
    }
}

/// The closed set of verbs the model may choose from.
#[derive(Debug, Clone, PartialEq)]
pub enum AgentAction {
    Click { id: String },
    Type { id: String, text: String },
    Select { id: String, value: String },
    Check { id: String, checked: bool },
    UploadResume,
    PressKey { id: String, key: String },
    Scroll { y: i64 },
    Wait { ms: u64 },
    /// Arbitrary JavaScript evaluated in the page. This is the agent's escape hatch: the
    /// fixed verbs cannot cover custom date pickers, shadow DOM, drag-and-drop uploaders or
    /// canvas widgets, and no list of verbs ever will. Whatever the script returns is fed
    /// back as an observation, so the agent can also use it to inspect the page.
    EvalJs { code: String },
    /// Navigate somewhere else (a company careers page, a direct application URL).
    Navigate { url: String },
    /// The model believes the application is submitted.
    Done { reason: String },
    /// The model cannot proceed safely (login wall, captcha, missing data).
    NeedsHuman { reason: String },
}

impl AgentAction {
    pub fn describe(&self) -> String {
        match self {
            AgentAction::Click { id } => format!("click {}", id),
            AgentAction::Type { id, text } => format!("type '{}' -> {}", text, id),
            AgentAction::Select { id, value } => format!("select '{}' -> {}", value, id),
            AgentAction::Check { id, checked } => format!("check({}) {}", checked, id),
            AgentAction::UploadResume => "upload_resume".to_string(),
            AgentAction::PressKey { id, key } => format!("press {} on {}", key, id),
            AgentAction::Scroll { y } => format!("scroll {}", y),
            AgentAction::Wait { ms } => format!("wait {}ms", ms),
            AgentAction::EvalJs { code } => format!("eval_js: {}", code.chars().take(90).collect::<String>()),
            AgentAction::Navigate { url } => format!("navigate {}", url),
            AgentAction::Done { reason } => format!("done: {}", reason),
            AgentAction::NeedsHuman { reason } => format!("needs_human: {}", reason),
        }
    }

    /// Parses the model's JSON reply. Unknown verbs are rejected rather than guessed at.
    pub fn from_json(v: &Value) -> Option<AgentAction> {
        let action = v.get("action")?.as_str()?.trim().to_lowercase();
        let id = || v.get("id").and_then(|x| x.as_str()).unwrap_or("").to_string();
        let text = || v.get("text").and_then(|x| x.as_str()).unwrap_or("").to_string();
        let reason = || {
            v.get("reason")
                .and_then(|x| x.as_str())
                .unwrap_or("(sin motivo)")
                .to_string()
        };

        match action.as_str() {
            "click" => Some(AgentAction::Click { id: id() }),
            "type" => Some(AgentAction::Type { id: id(), text: text() }),
            "select" => Some(AgentAction::Select { id: id(), value: text() }),
            "check" => Some(AgentAction::Check {
                id: id(),
                checked: v.get("checked").and_then(|x| x.as_bool()).unwrap_or(true),
            }),
            "upload_resume" => Some(AgentAction::UploadResume),
            "press_key" => Some(AgentAction::PressKey { id: id(), key: text() }),
            "scroll" => Some(AgentAction::Scroll {
                y: v.get("y").and_then(|x| x.as_i64()).unwrap_or(500),
            }),
            "wait" => Some(AgentAction::Wait {
                ms: v.get("ms").and_then(|x| x.as_u64()).unwrap_or(1500).min(15_000),
            }),
            "eval_js" => {
                let code = v.get("code").and_then(|x| x.as_str()).unwrap_or("").trim().to_string();
                if code.is_empty() { None } else { Some(AgentAction::EvalJs { code }) }
            }
            "navigate" => {
                let url = v.get("url").and_then(|x| x.as_str()).unwrap_or("").trim().to_string();
                // Only real web navigation — javascript:/data:/file: URLs are not navigation.
                if url.starts_with("http://") || url.starts_with("https://") {
                    Some(AgentAction::Navigate { url })
                } else {
                    None
                }
            }
            "done" => Some(AgentAction::Done { reason: reason() }),
            "needs_human" => Some(AgentAction::NeedsHuman { reason: reason() }),
            _ => None,
        }
    }

    /// True for actions that could submit an application. Dry-run refuses these.
    pub fn is_potentially_final(&self) -> bool {
        matches!(self, AgentAction::Click { .. })
    }
}

/// Tags every interactive element with a `data-tf-id` and returns what is on screen.
///
/// Deliberately semantic: elements are described by role, accessible name and current
/// value, never by class or id, because LinkedIn (and most modern ATS bundles) ship hashed
/// class names and framework-generated ids that change between deploys.
pub async fn snapshot(page: &Page) -> Result<PageSnapshot> {
    let raw: String = page.evaluate(SNAPSHOT_JS).await?.into_value().unwrap_or_else(|_| "{}".to_string());
    let snap: PageSnapshot = serde_json::from_str(&raw).unwrap_or(PageSnapshot {
        url: String::new(),
        title: String::new(),
        fields: Vec::new(),
        actions: Vec::new(),
        text: String::new(),
    });
    Ok(snap)
}

/// Runs one action against the page. Returns false when the target could not be resolved,
/// which the caller feeds back to the model instead of silently continuing.
pub async fn execute(page: &Page, action: &AgentAction) -> Result<bool> {
    match action {
        AgentAction::Scroll { y } => {
            let _ = page.evaluate(format!("window.scrollBy(0, {})", y)).await;
            Ok(true)
        }
        AgentAction::Wait { ms } => {
            tokio::time::sleep(Duration::from_millis(*ms)).await;
            Ok(true)
        }
        AgentAction::Click { id } => {
            let script = format!(
                r#"(() => {{
                    const el = document.querySelector("[data-tf-id='{id}']");
                    if (!el) return false;
                    el.scrollIntoView({{block: 'center'}});
                    el.click();
                    return true;
                }})()"#,
                id = id
            );
            Ok(page.evaluate(script).await?.into_value::<bool>().unwrap_or(false))
        }
        AgentAction::Check { id, checked } => {
            let script = format!(
                r#"(() => {{
                    const el = document.querySelector("[data-tf-id='{id}']");
                    if (!el) return false;
                    if (el.checked !== {checked}) {{ el.click(); }}
                    return true;
                }})()"#,
                id = id,
                checked = checked
            );
            Ok(page.evaluate(script).await?.into_value::<bool>().unwrap_or(false))
        }
        AgentAction::Select { id, value } => {
            let script = format!(
                r#"(() => {{
                    const el = document.querySelector("[data-tf-id='{id}']");
                    if (!el) return false;
                    const want = {value};
                    const opts = Array.from(el.options || []);
                    let hit = opts.find(o => o.text.trim() === want) ||
                              opts.find(o => o.text.trim().toLowerCase() === want.toLowerCase()) ||
                              opts.find(o => o.text.trim().toLowerCase().includes(want.toLowerCase()));
                    if (!hit) return false;
                    el.value = hit.value;
                    el.dispatchEvent(new Event('change', {{bubbles: true}}));
                    return true;
                }})()"#,
                id = id,
                value = serde_json::to_string(value).unwrap_or_else(|_| "\"\"".to_string())
            );
            Ok(page.evaluate(script).await?.into_value::<bool>().unwrap_or(false))
        }
        AgentAction::Type { id, text } => {
            // Reuse the hardened typeahead-aware filler: it types real keystrokes and
            // resolves suggestion popups, which naive value-setting cannot do.
            match super::dom::fill_text_like_field(page, id, text).await? {
                super::dom::FillOutcome::NotFound => Ok(false),
                _ => Ok(true),
            }
        }
        AgentAction::PressKey { id, key } => {
            let selector = format!("[data-tf-id='{}']", id);
            match page.find_element(&selector).await {
                Ok(el) => {
                    let _ = el.click().await;
                    Ok(el.press_key(key.as_str()).await.is_ok())
                }
                Err(_) => Ok(false),
            }
        }
        AgentAction::EvalJs { code } => {
            // Wrapped so a bare expression, a statement block or a thrown error all come
            // back as a readable observation instead of killing the step.
            let wrapped = format!(
                "(() => {{ try {{ const __r = (function() {{ {code} }})(); \
                 return String(__r === undefined ? 'ok (sin valor de retorno)' : \
                 (typeof __r === 'object' ? JSON.stringify(__r) : __r)).slice(0, 800); }} \
                 catch (e) {{ return 'ERROR: ' + (e && e.message ? e.message : e); }} }})()",
                code = code
            );
            match page.evaluate(wrapped).await {
                Ok(r) => {
                    let out = r.into_value::<String>().unwrap_or_else(|_| "(sin salida)".to_string());
                    Ok(!out.starts_with("ERROR:"))
                }
                Err(e) => {
                    println!("      ⚠️ [Agente] eval_js falló: {}", e);
                    Ok(false)
                }
            }
        }
        AgentAction::Navigate { url } => Ok(page.goto(url.as_str()).await.is_ok()),
        AgentAction::UploadResume => Ok(true), // handled by the caller, which owns the CV path
        AgentAction::Done { .. } | AgentAction::NeedsHuman { .. } => Ok(true),
    }
}

/// Same as [`execute`] but returns what the page reported back, so `eval_js` results become
/// observations the agent can reason about on the next turn.
pub async fn execute_observed(page: &Page, action: &AgentAction) -> (bool, String) {
    if let AgentAction::EvalJs { code } = action {
        let wrapped = format!(
            "(() => {{ try {{ const __r = (function() {{ {code} }})(); \
             return String(__r === undefined ? 'ok (sin valor de retorno)' : \
             (typeof __r === 'object' ? JSON.stringify(__r) : __r)).slice(0, 800); }} \
             catch (e) {{ return 'ERROR: ' + (e && e.message ? e.message : e); }} }})()",
            code = code
        );
        return match page.evaluate(wrapped).await {
            Ok(r) => {
                let out = r.into_value::<String>().unwrap_or_else(|_| "(sin salida)".to_string());
                (!out.starts_with("ERROR:"), out)
            }
            Err(e) => (false, format!("ERROR de evaluación: {}", e)),
        };
    }
    let ok = execute(page, action).await.unwrap_or(false);
    (ok, if ok { "ok".to_string() } else { "FALLÓ".to_string() })
}

/// Outcome of an agent run.
#[derive(Debug, Clone, PartialEq)]
pub enum AgentOutcome {
    Submitted(String),
    NeedsHuman(String),
    Exhausted,
}

/// Perceive → decide → act, until the agent finishes or runs out of steps.
///
/// The loop owns two safeguards the model cannot override: dry-run refuses any click that
/// could submit, and a repeated-snapshot guard stops the run when the page stops changing
/// (the failure mode that previously burned 15 identical iterations against one step).
pub async fn run_agent(
    page: &Page,
    ai: &crate::services::AiClient,
    resume_manager: &super::resume_manager::ResumeManager,
    ctx: &mut super::form::JobContext,
    profile_yaml: &str,
    dry_run: bool,
    max_steps: u32,
) -> Result<AgentOutcome> {
    let goal = format!(
        "Postularte a '{}' en '{}' ({}). Completa todos los campos obligatorios con los datos del perfil, \
         adjunta el CV y envía la solicitud.",
        ctx.role, ctx.company, ctx.location
    );

    let mut history: Vec<String> = Vec::new();
    let mut last_fingerprint: Option<String> = None;
    let mut unchanged_rounds = 0u32;

    for step in 1..=max_steps {
        let snap = snapshot(page).await?;
        println!(
            "      🤖 [Agente] Paso {}: {} campos, {} acciones — {}",
            step,
            snap.fields.len(),
            snap.actions.len(),
            snap.title.chars().take(50).collect::<String>()
        );

        let fp = snap.fingerprint();
        if Some(&fp) == last_fingerprint.as_ref() {
            unchanged_rounds += 1;
            if unchanged_rounds >= 3 {
                let msg = "La página dejó de cambiar tras 3 acciones seguidas del agente.".to_string();
                println!("      🛑 [Agente] {}", msg);
                return Ok(AgentOutcome::NeedsHuman(msg));
            }
        } else {
            unchanged_rounds = 0;
        }
        last_fingerprint = Some(fp);

        let Some(decision) = ai.decide_next_action(&goal, profile_yaml, &snap, &history, dry_run).await else {
            history.push("(el modelo no devolvió una acción válida)".to_string());
            continue;
        };

        let Some(action) = AgentAction::from_json(&decision) else {
            println!("      ⚠️ [Agente] Acción no reconocida, se descarta: {}", decision);
            history.push(format!("(acción inválida ignorada: {})", decision));
            continue;
        };

        println!("      ➡️  [Agente] {}", action.describe());

        match &action {
            AgentAction::Done { reason } => {
                // Never take the model's word for it — require the page to say so.
                let confirmed = super::dom::text_visible_on_page(page, "application submitted").await
                    || super::dom::text_visible_on_page(page, "postulación enviada").await
                    || super::dom::text_visible_on_page(page, "thank you for applying").await
                    || super::dom::text_visible_on_page(page, "solicitud enviada").await;
                if confirmed {
                    return Ok(AgentOutcome::Submitted(reason.clone()));
                }
                println!("      ⚠️ [Agente] Dijo 'done' pero la página no confirma el envío; continúa.");
                history.push("done rechazado: la página no muestra confirmación".to_string());
                continue;
            }
            AgentAction::NeedsHuman { reason } => {
                return Ok(AgentOutcome::NeedsHuman(reason.clone()));
            }
            AgentAction::UploadResume => {
                let uploaded = resume_manager.smart_upload_resume(page, &ctx.target_resume).await.ok().flatten();
                match uploaded {
                    Some(name) => {
                        ctx.actual_resume = Some(name.clone());
                        history.push(format!("upload_resume -> {}", name));
                    }
                    None => history.push("upload_resume -> no se encontró campo de archivo".to_string()),
                }
                tokio::time::sleep(Duration::from_millis(800)).await;
                continue;
            }
            AgentAction::Click { .. } if dry_run => {
                // Dry-run cannot tell a "Next" from a "Submit" reliably — label-based
                // detection is exactly what caused a real accidental submission before.
                // So it refuses every click rather than guessing which ones are safe.
                let msg = "Auditoría: se omitió un clic (el modo dry-run nunca pulsa nada).".to_string();
                println!("      🛡️ [Agente] {}", msg);
                history.push(msg);
                return Ok(AgentOutcome::NeedsHuman("auditoría completada sin enviar".to_string()));
            }
            _ => {}
        }

        let (ok, observation) = execute_observed(page, &action).await;
        history.push(format!("{} -> {}", action.describe(), observation));
        if matches!(action, AgentAction::EvalJs { .. }) {
            println!("      📄 [Agente] resultado del script: {}", observation.chars().take(200).collect::<String>());
        }
        if !ok {
            println!("      ⚠️ [Agente] La acción no se pudo ejecutar (id inexistente, script con error o elemento no interactuable).");
        }
        tokio::time::sleep(Duration::from_millis(900)).await;
    }

    Ok(AgentOutcome::Exhausted)
}

const SNAPSHOT_JS: &str = r#"(() => {
    function isVisible(el) {
        if (!(el.offsetWidth || el.offsetHeight || el.getClientRects().length)) return false;
        const st = getComputedStyle(el);
        return st.visibility !== 'hidden' && st.display !== 'none';
    }
    function norm(s) { return (s || '').replace(/\s+/g, ' ').trim(); }

    // Accessible name, resolved the standards-defined way. Falls back to placeholder and
    // name so controls that ship no label at all are still identifiable.
    function accName(el) {
        const aria = norm(el.getAttribute('aria-label'));
        if (aria) return aria;
        const by = norm(el.getAttribute('aria-labelledby'));
        if (by) {
            const t = by.split(/\s+/).map(i => { const r = document.getElementById(i); return r ? norm(r.innerText) : ''; })
                       .filter(Boolean).join(' ');
            if (t) return t;
        }
        if (el.id) {
            try {
                const sel = (window.CSS && CSS.escape) ? 'label[for="' + CSS.escape(el.id) + '"]' : null;
                const bound = sel ? document.querySelector(sel) : null;
                if (bound && norm(bound.innerText)) return norm(bound.innerText);
            } catch (e) {}
        }
        const wrap = el.closest('label');
        if (wrap && norm(wrap.innerText)) return norm(wrap.innerText);
        // Only trust an ancestor's text when that ancestor holds exactly this one control,
        // otherwise a neighbouring field's label gets attributed to this one.
        let cur = el;
        for (let i = 0; i < 4 && cur; i++) {
            cur = cur.parentElement;
            if (!cur) break;
            if (cur.querySelectorAll('input, select, textarea').length !== 1) break;
            const lbl = cur.querySelector('label');
            if (lbl && isVisible(lbl) && norm(lbl.innerText)) return norm(lbl.innerText);
        }
        return norm(el.getAttribute('placeholder')) || norm(el.getAttribute('name')) || '';
    }

    function nearbyError(el) {
        if (el.getAttribute('aria-invalid') === 'true') {
            const d = el.getAttribute('aria-describedby');
            if (d) { const m = document.getElementById(d); if (m && norm(m.innerText)) return norm(m.innerText); }
            return 'campo inválido';
        }
        let p = el.parentElement;
        for (let i = 0; i < 3 && p; i++) {
            const e = p.querySelector("[role='alert']");
            if (e && isVisible(e) && norm(e.innerText)) return norm(e.innerText);
            p = p.parentElement;
        }
        return null;
    }

    let n = 0;
    const tag = (el) => { const id = 'tf_' + (n++); el.setAttribute('data-tf-id', id); return id; };
    const fields = [];
    const actions = [];
    const SKIP = ['hidden', 'submit', 'reset', 'image'];

    for (const el of document.querySelectorAll('input, textarea, select')) {
        if (!isVisible(el)) continue;
        const raw = (el.tagName === 'INPUT') ? String(el.type || 'text').toLowerCase()
                  : (el.tagName === 'SELECT') ? 'select' : 'text';
        if (SKIP.includes(raw)) continue;
        if (raw === 'button') { continue; }
        let kind = 'text';
        if (raw === 'select') kind = 'select';
        else if (raw === 'checkbox') kind = 'checkbox';
        else if (raw === 'radio') kind = 'radio';
        else if (raw === 'file') kind = 'file';

        fields.push({
            id: tag(el),
            kind: kind,
            label: accName(el).slice(0, 120),
            value: (kind === 'checkbox' || kind === 'radio') ? String(!!el.checked) : String(el.value || '').slice(0, 120),
            options: (kind === 'select') ? Array.from(el.options || []).map(o => norm(o.text)).filter(Boolean).slice(0, 40) : [],
            required: !!el.required || el.getAttribute('aria-required') === 'true',
            error: nearbyError(el)
        });
    }

    for (const el of document.querySelectorAll("button, a[href], [role='button'], input[type='submit']")) {
        if (!isVisible(el) || el.disabled) continue;
        const label = (norm(el.innerText) || norm(el.getAttribute('aria-label')) || norm(el.value)).slice(0, 80);
        if (!label) continue;
        actions.push({
            id: tag(el),
            kind: el.tagName.toLowerCase() === 'a' ? 'link' : 'button',
            label: label,
            value: '',
            options: [],
            required: false,
            error: null
        });
    }

    return JSON.stringify({
        url: location.href,
        title: document.title || '',
        fields: fields.slice(0, 60),
        actions: actions.slice(0, 60),
        text: norm(document.body.innerText).slice(0, 2500)
    });
})()"#;

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    #[test]
    fn parses_each_supported_verb() {
        assert_eq!(
            AgentAction::from_json(&json!({"action": "click", "id": "tf_3"})),
            Some(AgentAction::Click { id: "tf_3".into() })
        );
        assert_eq!(
            AgentAction::from_json(&json!({"action": "type", "id": "tf_1", "text": "Medellín"})),
            Some(AgentAction::Type { id: "tf_1".into(), text: "Medellín".into() })
        );
        assert_eq!(
            AgentAction::from_json(&json!({"action": "select", "id": "tf_2", "text": "Colombia"})),
            Some(AgentAction::Select { id: "tf_2".into(), value: "Colombia".into() })
        );
        assert_eq!(
            AgentAction::from_json(&json!({"action": "upload_resume"})),
            Some(AgentAction::UploadResume)
        );
    }

    #[test]
    fn rejects_unknown_verbs_instead_of_guessing() {
        // A model that invents "run_shell" or "navigate" must not be silently reinterpreted
        // as something else — an unparsed action ends the turn and asks again.
        assert_eq!(AgentAction::from_json(&json!({"action": "run_shell", "cmd": "rm -rf /"})), None);
        assert_eq!(AgentAction::from_json(&json!({"action": "read_file", "path": "/etc/passwd"})), None);
        assert_eq!(AgentAction::from_json(&json!({"nope": 1})), None);
    }

    #[test]
    fn navigate_accepts_only_real_web_urls() {
        assert_eq!(
            AgentAction::from_json(&json!({"action": "navigate", "url": "https://careers.example.com/apply"})),
            Some(AgentAction::Navigate { url: "https://careers.example.com/apply".into() })
        );
        // Non-http schemes are not navigation — file:// would reach the local disk and
        // javascript:/data: are code execution wearing a URL's clothes.
        for bad in ["file:///etc/passwd", "javascript:alert(1)", "data:text/html,<h1>x", "chrome://settings"] {
            assert_eq!(AgentAction::from_json(&json!({"action": "navigate", "url": bad})), None, "debió rechazar {}", bad);
        }
    }

    #[test]
    fn eval_js_requires_actual_code() {
        assert_eq!(AgentAction::from_json(&json!({"action": "eval_js", "code": "   "})), None);
        assert_eq!(
            AgentAction::from_json(&json!({"action": "eval_js", "code": "return document.title"})),
            Some(AgentAction::EvalJs { code: "return document.title".into() })
        );
    }

    #[test]
    fn wait_is_clamped_so_the_model_cannot_stall_the_run() {
        assert_eq!(
            AgentAction::from_json(&json!({"action": "wait", "ms": 999999})),
            Some(AgentAction::Wait { ms: 15_000 })
        );
    }

    #[test]
    fn only_clicks_are_treated_as_potentially_final() {
        assert!(AgentAction::Click { id: "tf_1".into() }.is_potentially_final());
        assert!(!AgentAction::Type { id: "tf_1".into(), text: "x".into() }.is_potentially_final());
        assert!(!AgentAction::Scroll { y: 100 }.is_potentially_final());
    }
}
