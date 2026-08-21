use anyhow::Result;
use chromiumoxide::Page;
use serde::{Deserialize, Serialize};
use serde_json::json;
use std::time::Duration;

/// Result of trying to fill a single field. Richer than a bool so callers can tell
/// "typed successfully" apart from "typed but a suggestion list never resolved" —
/// the latter must never be treated as success (see FillOutcome::NeedsHuman).
#[derive(Debug, Clone, PartialEq)]
pub enum FillOutcome {
    Filled,
    FilledViaSuggestion,
    NeedsHuman(String),
    NotFound,
}

/// One field detected on an Easy Apply / external ATS form step.
/// Mirrors the schema built by src/app/bots/apply/form_handler.py::scan_form_structure,
/// minus the Playwright locator handle — instead every matched DOM element is tagged
/// with a `data-tf-id` attribute so later fill calls can re-select it directly.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct FormField {
    pub id: String,
    #[serde(rename = "type")]
    pub field_type: String,
    pub label: String,
    #[serde(default)]
    pub value: String,
    pub error: Option<String>,
    /// El portal exige este campo (atributo nativo, `aria-required`, o asterisco en la
    /// etiqueta). Sin esto no se podía distinguir obligatorio de opcional, así que un campo
    /// sin respuesta se saltaba igual en ambos casos y el ATS rechazaba el envío.
    #[serde(default)]
    pub required: bool,
    #[serde(default)]
    pub options: Vec<String>,
    #[serde(default)]
    pub is_combobox: bool,
    /// Only populated when label detection fails ("Unknown Group Choice") — lets us
    /// dump the real markup to debug/dom/ so the label-detection selectors can be fixed
    /// against actual LinkedIn/ATS DOM instead of guessing blind.
    #[serde(default)]
    pub raw_html: Option<String>,
}

/// Scans the current Easy Apply modal (or the whole page for external ATS forms) and
/// returns a semantic map of its fields. Every matched element gets a `data-tf-id`
/// attribute so fill_* below can address it without holding a live element handle.
pub async fn scan_form_structure(page: &Page, prefer_modal: bool) -> Result<Vec<FormField>> {
    let script = SCAN_JS.replace("__PREFER_MODAL__", if prefer_modal { "true" } else { "false" });
    let result = page.evaluate(script).await?;
    let raw: String = result.into_value().unwrap_or_else(|_| "[]".to_string());

    #[derive(Deserialize)]
    struct ScanResult {
        fields: Vec<FormField>,
        root_html: String,
    }
    let parsed: ScanResult = serde_json::from_str(&raw).unwrap_or(ScanResult { fields: Vec::new(), root_html: String::new() });

    dump_debug_snapshot(&parsed.root_html);

    for field in &parsed.fields {
        if let Some(html) = &field.raw_html {
            let _ = std::fs::create_dir_all("debug/dom");
            let ts = chrono::Utc::now().timestamp_millis();
            let prefix = if field.field_type == "unknown" { "unknown_field" } else { "unresolved_group" };
            let path = format!("debug/dom/{}_{}_{}.html", prefix, field.id, ts);
            if std::fs::write(&path, html).is_ok() {
                let note = if field.field_type == "unknown" { "Campo de tipo no reconocido" } else { "Etiqueta de grupo no resuelta" };
                println!("      🩺 {} — HTML guardado en {}", note, path);
            }
        }
    }

    Ok(parsed.fields)
}

/// Mirrors Python's scan_form_structure debug dump (rotate_files, keep last 10) — every
/// scanned step's raw markup is saved so a stuck/misbehaving step can be inspected after
/// the fact instead of guessed at blind.
fn dump_debug_snapshot(html: &str) {
    if html.is_empty() {
        return;
    }
    let _ = std::fs::create_dir_all("debug/dom");
    let ts = chrono::Utc::now().timestamp_millis();
    let path = format!("debug/dom/raw_dom_{}.html", ts);
    let _ = std::fs::write(&path, html);

    if let Ok(entries) = std::fs::read_dir("debug/dom") {
        let mut files: Vec<_> = entries
            .filter_map(|e| e.ok())
            .filter(|e| e.file_name().to_string_lossy().starts_with("raw_dom_"))
            .collect();
        if files.len() > 40 {
            files.sort_by_key(|e| e.metadata().and_then(|m| m.modified()).ok());
            for old in &files[..files.len() - 40] {
                let _ = std::fs::remove_file(old.path());
            }
        }
    }
}

/// Direct value-set fallback for when real keystrokes aren't possible (e.g. the
/// element handle went stale). Not exported — always prefer fill_text_like_field.
async fn fill_text_field_raw(page: &Page, field_id: &str, value: &str) -> Result<bool> {
    let script = format!(
        "(() => {{ const el = document.querySelector(\"[data-tf-id='{id}']\"); if (!el) return false; \
         el.focus(); el.value = {value}; \
         el.dispatchEvent(new Event('input', {{ bubbles: true }})); \
         el.dispatchEvent(new Event('change', {{ bubbles: true }})); return true; }})()",
        id = field_id,
        value = json!(value),
    );
    let result = page.evaluate(script).await?;
    Ok(result.into_value::<bool>().unwrap_or(false))
}

/// Checks whether a suggestion/autocomplete popup is currently visible anywhere on the
/// page. Deliberately behavioral rather than attribute-based (LinkedIn's markup uses
/// hashed CSS classes and doesn't reliably set role="combobox"/aria-autocomplete on the
/// input itself) — this is what makes typeahead detection survive frontend rewrites.
/// Returns a short description of the suggestion popup currently open **for this input**,
/// or None if there is none.
///
/// NOTE (incident 2026-08-18): steps 2 and 3 used to query the whole document —
/// `document.querySelector("[role='listbox']")` matches ANY listbox on the page, and
/// LinkedIn keeps several around outside the application form (global search typeahead,
/// sort/filter dropdowns, the messaging overlay). One unrelated visible listbox pinned the
/// probe to `true` permanently, so a typeahead that had actually closed correctly was still
/// reported as unresolved and the whole job was sent to Manual. Every signal is now bound
/// to the input: either an explicit ARIA relationship, or geometric proximity to it.
async fn suggestion_popup_match(page: &Page, field_id: &str) -> Option<String> {
    let script = format!(
        r#"(() => {{
            function isVisible(el) {{ return !!(el.offsetWidth || el.offsetHeight || el.getClientRects().length); }}
            const input = document.querySelector("[data-tf-id='{id}']");
            if (!input) return null;

            const rect = input.getBoundingClientRect();
            // A popup belongs to this input only if it sits right under/beside it.
            function isNearInput(el) {{
                const r = el.getBoundingClientRect();
                if (r.width < 20 || r.height < 10) return false;
                return r.top >= rect.top - 5 && r.top <= rect.bottom + 300 && Math.abs(r.left - rect.left) < 400;
            }}
            function describe(el, why) {{
                const tag = el.tagName.toLowerCase();
                const role = el.getAttribute('role') || '-';
                return why + ' <' + tag + ' role=' + role + '> con ' + el.children.length + ' filas';
            }}

            // 1. Explicit ARIA relationship — trusted without geometry, it names THIS input's popup.
            const ref = input.getAttribute('aria-controls') || input.getAttribute('aria-owns');
            if (ref) {{
                const el = document.getElementById(ref);
                if (el && isVisible(el) && el.children.length > 0) return describe(el, 'aria-controls');
            }}
            if (input.getAttribute('aria-expanded') === 'true') return 'aria-expanded=true en el input';

            // 2. role=listbox / role=option — only when positioned against this input.
            for (const el of Array.from(document.querySelectorAll("[role='listbox']"))) {{
                if (el.contains(input) || !isVisible(el) || el.tagName.toLowerCase() === 'input' || el.children.length === 0) continue;
                if (isNearInput(el)) return describe(el, 'listbox cercano');
            }}
            for (const el of Array.from(document.querySelectorAll("[role='option']"))) {{
                if (!isVisible(el)) continue;
                if (isNearInput(el)) return describe(el, 'option cercano');
            }}

            // 3. Generic floating popup near the input, for widgets with no ARIA roles at all.
            for (const el of Array.from(document.querySelectorAll('ul, div[role], div[class]'))) {{
                if (el === input || el.contains(input) || !isVisible(el)) continue;
                const style = getComputedStyle(el);
                if (style.position !== 'absolute' && style.position !== 'fixed') continue;
                if (el.children.length === 0) continue;
                if (isNearInput(el)) return describe(el, 'popup flotante');
            }}
            return null;
        }})()"#,
        id = field_id,
    );
    page.evaluate(script)
        .await
        .ok()
        .and_then(|r| r.into_value::<Option<String>>().ok())
        .flatten()
}

async fn has_suggestion_popup(page: &Page, field_id: &str) -> bool {
    suggestion_popup_match(page, field_id).await.is_some()
}

/// Cuánto se espera a que un typeahead pinte su lista antes de tratar el campo como texto
/// plano. Los autocompletar de los ATS externos (ciudad, país, universidad, empresa) casi
/// siempre consultan la red: entre que se dispara el evento `input` y aparece la lista pasan
/// típicamente 300–1500 ms.
const SUGGESTION_POPUP_WAIT: Duration = Duration::from_millis(900);

/// Espera a que aparezca la lista de sugerencias del campo.
///
/// Antes se preguntaba por el popup inmediatamente después de escribir, a los ~0 ms. Ningún
/// typeahead con búsqueda por red alcanza a responder en ese tiempo, así que el campo se daba
/// por "texto plano" y quedaba con el texto crudo escrito y ninguna opción seleccionada — que
/// es justo lo que estos portales rechazan al enviar el formulario.
///
/// Devuelve apenas la lista aparece, así que un typeahead rápido no paga la espera completa;
/// solo un campo de texto normal agota el presupuesto entero (una vez por campo).
async fn wait_for_suggestion_popup(page: &Page, field_id: &str, timeout: Duration) -> bool {
    let started = std::time::Instant::now();
    loop {
        if has_suggestion_popup(page, field_id).await {
            return true;
        }
        if started.elapsed() >= timeout {
            return false;
        }
        tokio::time::sleep(Duration::from_millis(150)).await;
    }
}

/// Dispara `blur` sobre un campo ya resuelto. Se hace al final y solo cuando se confirmó que
/// el campo NO es un typeahead: muchos autocompletar cierran (y descartan) su lista al recibir
/// blur, así que dispararlo junto con el `input` cerraba el desplegable que luego se buscaba.
async fn blur_field(page: &Page, field_id: &str) {
    let script = format!(
        "(() => {{ const el = document.querySelector(\"[data-tf-id='{id}']\"); \
         if (!el) return false; el.dispatchEvent(new Event('blur', {{ bubbles: true, composed: true }})); return true; }})()",
        id = field_id,
    );
    let _ = page.evaluate(script).await;
}

/// Clicks the first visible suggestion-like row currently on screen — last-resort
/// confirmation when ArrowDown+Enter didn't close the popup.
async fn click_first_suggestion(page: &Page) -> bool {
    let script = r#"(() => {
        function isVisible(el) { return !!(el.offsetWidth || el.offsetHeight || el.getClientRects().length); }
        let candidate = document.querySelector("[role='option']");
        if (!candidate || !isVisible(candidate)) {
            const listbox = document.querySelector("[role='listbox']");
            candidate = listbox ? listbox.querySelector('li, div, a') : null;
        }
        if (candidate && isVisible(candidate)) { candidate.click(); return true; }
        return false;
    })()"#;
    page.evaluate(script).await.ok().and_then(|r| r.into_value::<bool>().ok()).unwrap_or(false)
}

/// Fills any text-like field (text/email/tel/number/textarea). Escribe el valor de una vez
/// usando el setter nativo del prototipo (para que React/Vue/Angular registren el cambio en
/// su estado interno, no solo en el DOM), luego **espera** hasta [`SUGGESTION_POPUP_WAIT`] a
/// que aparezca una lista de sugerencias — si aparece, la maneja con el teclado (con clic
/// directo como respaldo) y solo reporta éxito cuando confirma que la lista se cerró.
///
/// El sondeo es de comportamiento, no por atributos: reemplaza la vieja compuerta `is_combobox`,
/// que se rompió en silencio cuando LinkedIn dejó de exponer los atributos ARIA de combobox
/// (confirmado en vivo: la lista de sugerencias de Ciudad se abría pero nunca se llenaba).
pub async fn fill_text_like_field(page: &Page, field_id: &str, value: &str) -> Result<FillOutcome> {
    let selector = format!("[data-tf-id='{}']", field_id);
    let element = match page.find_element(&selector).await {
        Ok(el) => el,
        Err(_) => return Ok(FillOutcome::NotFound),
    };

    let clean_value = if value.to_lowercase().contains("medell") {
        "Medellin".to_string()
    } else if value.to_lowercase().contains("bogot") {
        "Bogota".to_string()
    } else {
        value.to_string()
    };

    let _ = element.click().await;

    // Fast machine fill: Clear input, set native prototype property for React/Vue/Angular, and dispatch full event sequence
    let react_fill_script = format!(
        r#"(() => {{
            const el = document.querySelector("{sel}");
            if (!el) return false;
            el.focus();
            el.select();
            const val = {val:?};
            const proto = el.tagName === 'TEXTAREA' ? window.HTMLTextAreaElement.prototype : window.HTMLInputElement.prototype;
            const nativeSetter = Object.getOwnPropertyDescriptor(proto, 'value')?.set;
            if (nativeSetter) {{
                nativeSetter.call(el, val);
            }} else {{
                el.value = val;
            }}
            el.dispatchEvent(new Event('input', {{ bubbles: true, composed: true }}));
            el.dispatchEvent(new Event('change', {{ bubbles: true, composed: true }}));
            return true;
        }})()"#,
        sel = selector,
        val = clean_value
    );
    let _ = page.evaluate(react_fill_script).await;

    if !wait_for_suggestion_popup(page, field_id, SUGGESTION_POPUP_WAIT).await {
        // Plain text field, already filled correctly with clean value. El blur va aquí,
        // una vez descartado que sea un typeahead cuya lista se cerraría con él.
        blur_field(page, field_id).await;
        return Ok(FillOutcome::Filled);
    }

    let _ = element.press_key("ArrowDown").await;
    tokio::time::sleep(Duration::from_millis(150)).await;
    let _ = element.press_key("Enter").await;
    tokio::time::sleep(Duration::from_millis(200)).await;

    if has_suggestion_popup(page, field_id).await {
        click_first_suggestion(page).await;
        tokio::time::sleep(Duration::from_millis(200)).await;
    }

    if let Some(what) = suggestion_popup_match(page, field_id).await {
        // The popup is still up. Before giving up, check whether the field nonetheless
        // ended up holding a resolved value — some typeaheads keep a (now stale) list
        // rendered after the selection has already been applied to the input.
        let current = read_field_value(page, field_id).await;
        if !current.trim().is_empty() && current.trim().to_lowercase() != clean_value.trim().to_lowercase() {
            println!("      ℹ️ La lista sigue abierta ({}), pero el campo ya quedó resuelto como '{}'.", what, current.trim());
            return Ok(FillOutcome::FilledViaSuggestion);
        }
        return Ok(FillOutcome::NeedsHuman(format!(
            "Se escribió '{}' pero la lista de sugerencias nunca se cerró [detectada por: {}; valor actual del campo: '{}']",
            clean_value,
            what,
            current.trim()
        )));
    }

    Ok(FillOutcome::FilledViaSuggestion)
}

/// Reads back what a field currently holds (`value` for inputs, `innerText` for
/// contenteditable-style widgets).
async fn read_field_value(page: &Page, field_id: &str) -> String {
    let script = format!(
        "(() => {{ const el = document.querySelector(\"[data-tf-id='{id}']\"); return el ? (el.value || el.innerText || '') : ''; }})()",
        id = field_id
    );
    page.evaluate(script)
        .await
        .ok()
        .and_then(|r| r.into_value::<String>().ok())
        .unwrap_or_default()
}

/// Last-resort filler for field types scan_form_structure couldn't classify (custom
/// date pickers, contenteditable widgets, tag inputs, etc.) — click, type the answer,
/// confirm with Tab, then reuse the same suggestion-popup probe in case it turns out to
/// be yet another unlabeled combobox variant. Never silently no-ops: if nothing visibly
/// changes, it reports NeedsHuman instead of pretending the field is handled.
pub async fn fill_generic_fallback(page: &Page, field_id: &str, value: &str) -> Result<FillOutcome> {
    let selector = format!("[data-tf-id='{}']", field_id);
    let element = match page.find_element(&selector).await {
        Ok(el) => el,
        Err(_) => return Ok(FillOutcome::NotFound),
    };

    let before = page
        .evaluate(format!("(() => {{ const el = document.querySelector(\"{sel}\"); return el ? (el.value || el.innerText || '') : ''; }})()", sel = selector))
        .await
        .ok()
        .and_then(|r| r.into_value::<String>().ok())
        .unwrap_or_default();

    let _ = element.click().await;
    tokio::time::sleep(Duration::from_millis(150)).await;
    if element.type_str(value).await.is_err() {
        let _ = fill_text_field_raw(page, field_id, value).await;
    }
    let _ = element.press_key("Tab").await;
    tokio::time::sleep(Duration::from_millis(500)).await;

    if has_suggestion_popup(page, field_id).await {
        let _ = element.press_key("ArrowDown").await;
        let _ = element.press_key("Enter").await;
        tokio::time::sleep(Duration::from_millis(400)).await;
        if has_suggestion_popup(page, field_id).await {
            click_first_suggestion(page).await;
            tokio::time::sleep(Duration::from_millis(400)).await;
        }
    }

    let after = page
        .evaluate(format!("(() => {{ const el = document.querySelector(\"{sel}\"); return el ? (el.value || el.innerText || '') : ''; }})()", sel = selector))
        .await
        .ok()
        .and_then(|r| r.into_value::<String>().ok())
        .unwrap_or_default();

    if after.trim().is_empty() || after == before {
        dump_unresolved_field(field_id, &format!("Campo de tipo desconocido, valor no cambió tras intentar llenarlo con '{}'", value));
        return Ok(FillOutcome::NeedsHuman(format!("Campo de tipo desconocido no se pudo llenar (id={})", field_id)));
    }

    Ok(FillOutcome::Filled)
}

/// Saves a targeted HTML snapshot for a single unresolved field — cheaper and more
/// specific than relying only on the full-step dump when diagnosing a NeedsHuman case.
fn dump_unresolved_field(field_id: &str, reason: &str) {
    let _ = std::fs::create_dir_all("debug/dom");
    let ts = chrono::Utc::now().timestamp_millis();
    let path = format!("debug/dom/unresolved_field_{}_{}.html", field_id, ts);
    let _ = std::fs::write(&path, reason);
    println!("      🩺 Campo sin resolver ({}) — nota guardada en {}", field_id, path);
}

pub async fn fill_select_field(page: &Page, field_id: &str, answer: &str) -> Result<bool> {
    let script = format!(
        r#"(() => {{
            const el = document.querySelector("[data-tf-id='{id}']");
            if (!el) return false;
            const target = {answer}.toLowerCase();
            const options = Array.from(el.options || el.querySelectorAll('option, [role="option"]') || []);
            let matched = null;
            for (const opt of options) {{
                const text = (opt.innerText || opt.textContent || '').trim();
                const lower = text.toLowerCase();
                if (lower.includes(target) || target.includes(lower) || (target === 'yes' && lower.includes('sí')) || (target === 'no' && lower === 'no')) {{
                    matched = opt;
                    break;
                }}
            }}
            if (!matched) return false;
            if (el.tagName === 'SELECT') {{
                const nativeSetter = Object.getOwnPropertyDescriptor(window.HTMLSelectElement.prototype, 'value')?.set;
                if (nativeSetter) {{
                    nativeSetter.call(el, matched.value || matched.getAttribute('value') || '');
                }} else {{
                    el.value = matched.value || matched.getAttribute('value') || '';
                }}
                el.dispatchEvent(new Event('input', {{ bubbles: true, composed: true }}));
                el.dispatchEvent(new Event('change', {{ bubbles: true, composed: true }}));
            }} else {{
                matched.click();
            }}
            return true;
        }})()"#,
        id = field_id,
        answer = json!(answer),
    );
    let result = page.evaluate(script).await?;
    Ok(result.into_value::<bool>().unwrap_or(false))
}

pub async fn fill_choice_field(page: &Page, field_id: &str, field_type: &str, answers: &[String]) -> Result<bool> {
    let script = format!(
        r#"(() => {{
            const grp = document.querySelector("[data-tf-id='{id}']");
            if (!grp) return false;
            function norm(s) {{ return (s || '').normalize('NFD').replace(/[\u0300-\u036f]/g, '').toLowerCase(); }}
            const targets = {answers}.map(a => norm(String(a)));
            let options = [];
            if (grp.tagName === 'INPUT' && grp.name) {{
                options = Array.from(document.querySelectorAll(`input[name="${{CSS.escape(grp.name)}}"]`))
                    .map(inp => inp.closest('label') || document.querySelector(`label[for="${{CSS.escape(inp.id || '')}}"]`) || inp.parentElement || inp)
                    .filter(Boolean);
            }} else {{
                options = Array.from(grp.querySelectorAll('label, [role="radio"], [role="checkbox"], button, [class*="option"], [class*="radio"], [class*="checkbox"], li'));
            }}
            let found = false;
            for (const opt of options) {{
                const raw = (opt.innerText || opt.textContent || opt.getAttribute('aria-label') || '').trim();
                const text = norm(raw);
                if (!text) continue;
                const matches = targets.some(t => text.includes(t) || t.includes(text) || (t === 'si' && (text === 'si' || text === 'yes')) || (t === 'yes' && (text === 'si' || text === 'yes')));
                if (matches) {{
                    const input = opt.querySelector('input');
                    if (input) {{
                        input.checked = true;
                        input.dispatchEvent(new Event('input', {{ bubbles: true }}));
                        input.dispatchEvent(new Event('change', {{ bubbles: true }}));
                    }}
                    opt.click();
                    found = true;
                    if ({is_radio}) break;
                }}
            }}
            return found;
        }})()"#,
        id = field_id,
        answers = json!(answers),
        is_radio = field_type == "radio",
    );
    let result = page.evaluate(script).await?;
    Ok(result.into_value::<bool>().unwrap_or(false))
}

/// Detects a blocking validation error on the current step, and returns its message.
///
/// The original check looked only for `.artdeco-inline-feedback--error`, a legacy class
/// LinkedIn's current hashed-class UI no longer emits — so validation failures were
/// completely invisible to the bot. That is what turned a single unfilled required field
/// into an endless loop: LinkedIn refused to advance, the bot never noticed, clicked
/// "Next" again, re-scanned the identical step, and repeated until MAX_STEPS.
///
/// Detection is now semantic (aria-invalid / role=alert), with the legacy class kept
/// only as an extra hint.
pub async fn visible_error_message(page: &Page) -> Option<String> {
    let script = r#"(() => {
        function isVisible(el) { return !!(el.offsetWidth || el.offsetHeight || el.getClientRects().length); }

        // 1. A field explicitly marked invalid — the strongest, most portable signal.
        const invalid = Array.from(document.querySelectorAll("[aria-invalid='true']")).filter(isVisible);
        if (invalid.length) {
            const el = invalid[0];
            const described = el.getAttribute('aria-describedby');
            if (described) {
                const msg = document.getElementById(described);
                if (msg && msg.innerText.trim()) return msg.innerText.trim().slice(0, 200);
            }
            const label = el.getAttribute('aria-label') || '';
            return ('Campo inválido: ' + label).trim().slice(0, 200);
        }

        // 2. Any visible alert region with text — but role="alert" is ARIA's generic live
        // region, and LinkedIn uses it for SUCCESS toasts too. Confirmed live: after a
        // resume upload it announces "Se ha cargado el currículum" in a role=alert, which
        // was read as a blocking validation error and aborted a real application mid-flow.
        // Filter out confirmations before treating an alert as a failure.
        function norm(s) { return (s || '').normalize('NFD').replace(/[\u0300-\u036f]/g, '').toLowerCase(); }
        const SUCCESS = /(se ha cargado|cargado correctamente|subido correctamente|uploaded|upload complete|guardado|saved|success|listo|completado|adjuntado)/;

        const alerts = Array.from(document.querySelectorAll("[role='alert'], .artdeco-inline-feedback--error"))
            .filter(el => isVisible(el) && el.innerText.trim())
            .filter(el => !SUCCESS.test(norm(el.innerText)));
        if (alerts.length) return alerts[0].innerText.trim().slice(0, 200);

        return null;
    })()"#;
    page.evaluate(script).await.ok().and_then(|r| r.into_value::<Option<String>>().ok()).flatten()
}

/// Prefers buttons/links inside a `<footer>` — confirmed (via captured DOM snapshots)
/// to be where LinkedIn's Easy Apply step actions (Next/Review/Submit) actually live in
/// the current hashed-class UI — falling back to the whole page only if nothing footer-
/// scoped matches (external ATS pages rarely use `<footer>` for their action bar).
/// Without this, a same-labeled decoy elsewhere on the page (a "Siguiente" pagination
/// control in a sidebar job carousel, for example) can get clicked instead of the real
/// action, which looks like a successful click but never actually advances the form —
/// confirmed live: a step's fields kept re-appearing identically for 15 iterations even
/// though "Next/Review click ejecutado" printed as succeeding every time.
// Modal/step action buttons live in a footer, so those are checked FIRST — but the rest of
// the document must still be searched afterwards.
//
// This used to `return footerEls.length ? footerEls : allEls`, i.e. the presence of ANY
// footer hid the whole rest of the page from every text-based click. Confirmed live on
// BairesDev's ATS: the page's "Apply" button sits in the main content while Terms/Privacy/
// FAQ links sit in a footer, so the search saw only the footer and reported that no Apply
// button existed — the offer was filed as Manual with a perfectly clickable button on screen.
const CANDIDATES_JS: &str = "(() => { \
    const footerEls = Array.from(document.querySelectorAll('footer button, footer a')); \
    const allEls = Array.from(document.querySelectorAll('button, a, [role=\"button\"]')); \
    const seen = new Set(footerEls); \
    return footerEls.concat(allEls.filter(el => !seen.has(el))); \
})()";

/// Same fuzzy text match as click_by_text, but only reports visibility — used to gate
/// dry-run/shadow mode before actually clicking Submit.
pub async fn button_visible(page: &Page, labels: &[&str]) -> bool {
    let script = format!(
        "(() => {{ const labels = {labels}; \
         const candidates = {candidates}; \
         function visible(el) {{ return !!(el.offsetWidth || el.offsetHeight || el.getClientRects().length); }} \
         for (const lbl of labels) {{ \
           const target = lbl.toLowerCase(); \
           for (const el of candidates) {{ \
             const text = (el.innerText || el.getAttribute('aria-label') || '').trim().toLowerCase(); \
             if (text && text.includes(target) && visible(el)) return true; \
           }} \
         }} \
         return false; }})()",
        labels = json!(labels),
        candidates = CANDIDATES_JS,
    );
    page.evaluate(script).await.ok().and_then(|r| r.into_value::<bool>().ok()).unwrap_or(false)
}

/// Clicks the first visible button/link matching any of `labels` (fuzzy, case-insensitive
/// substring match on visible text) — mirrors ApplicationFlow.click_button's label search,
/// minus the physical mouse jitter (this port clicks via the DOM directly).
pub async fn click_by_text(page: &Page, labels: &[&str]) -> Result<bool> {
    let script = format!(
        "(() => {{ const labels = {labels}; \
         const candidates = {candidates}; \
         function visible(el) {{ return !!(el.offsetWidth || el.offsetHeight || el.getClientRects().length) && !el.disabled; }} \
         for (const lbl of labels) {{ \
           const target = lbl.toLowerCase(); \
           for (const el of candidates) {{ \
             const text = (el.innerText || el.getAttribute('aria-label') || '').trim().toLowerCase(); \
             if (text && text.includes(target) && visible(el)) {{ el.scrollIntoView({{block: 'center'}}); el.click(); return true; }} \
           }} \
         }} \
         return false; }})()",
        labels = json!(labels),
        candidates = CANDIDATES_JS,
    );
    let result = page.evaluate(script).await?;
    Ok(result.into_value::<bool>().unwrap_or(false))
}

/// Clicks LinkedIn's job-page Apply / Easy Apply button. Mirrors
/// InteractionHandler.click_like_an_ai's selector-priority approach: try LinkedIn's
/// known CSS selectors first (high precision), then fall back to fuzzy text matching.
pub async fn click_apply_button(page: &Page) -> Result<bool> {
    let _ = page.evaluate("window.scrollTo(0, 0)").await;
    tokio::time::sleep(std::time::Duration::from_millis(400)).await;

    let selectors = [
        "button[data-control-name='jobdetails_topcard_apply']",
        "a[data-control-name='jobdetails_topcard_apply']",
        ".jobs-apply-button--top-card button",
        ".jobs-s-apply button",
        "button.jobs-apply-button",
        "a.jobs-apply-button",
        "button[aria-label*='Solicitud sencilla']",
        "button[aria-label*='Easy Apply']",
        "button[aria-label*='Apply']",
        "a[aria-label*='Apply']",
        // Spanish UI: external ("Solicitar" / "Solicitar en el sitio web de la empresa").
        // Everything above is English-only or keyed on classes LinkedIn no longer ships,
        // so on a Spanish account an external offer matched nothing here and fell through
        // to the text search — which was footer-scoped and never saw the top card.
        "button[aria-label*='Solicitar']",
        "a[aria-label*='Solicitar']",
        "button[aria-label*='Postular']",
        "a[aria-label*='Postular']",
    ];

    let script = format!(
        "(() => {{ const selectors = {selectors}; \
         function visible(el) {{ return !!(el.offsetWidth || el.offsetHeight || el.getClientRects().length); }} \
         for (const sel of selectors) {{ \
           const els = document.querySelectorAll(sel); \
           for (const el of els) {{ if (visible(el)) {{ el.scrollIntoView({{block: 'center'}}); el.click(); return true; }} }} \
         }} \
         return false; }})()",
        selectors = json!(selectors),
    );
    let result = page.evaluate(script).await?;
    if result.into_value::<bool>().unwrap_or(false) {
        return Ok(true);
    }

    // Fallback: walk the WHOLE document for an apply control.
    //
    // This deliberately does not reuse click_by_text: that helper scans CANDIDATES_JS,
    // which narrows to `footer button, footer a` whenever the page has a footer. On the
    // Easy Apply modal that's right (its actions live in a footer), but on a job PAGE the
    // footer is LinkedIn's site-wide one, so the search never reached the top-card Apply
    // button. Combined with the English-only aria-labels above, every external offer on a
    // Spanish account reported "Apply button not found" (jobs 18, 25 and 28).
    let fallback = r#"(() => {
        function visible(el) { return !!(el.offsetWidth || el.offsetHeight || el.getClientRects().length) && !el.disabled; }
        function norm(s) { return (s || '').normalize('NFD').replace(/[\u0300-\u036f]/g, '').toLowerCase(); }
        const WANTED = /^(solicitud sencilla|easy apply|apply|apply now|solicitar|postularse|postular|solicitar empleo)\b/;

        const els = Array.from(document.querySelectorAll("button, a, [role='button']"));
        // Prefer the top card: the first match in document order that is not in a footer.
        for (const el of els) {
            if (!visible(el) || el.closest('footer')) continue;
            const text = norm(el.innerText) || norm(el.getAttribute('aria-label'));
            if (text && WANTED.test(text.trim())) {
                el.scrollIntoView({block: 'center'});
                el.click();
                return (el.innerText || el.getAttribute('aria-label') || '').trim().slice(0, 60);
            }
        }
        return null;
    })()"#;
    if let Some(label) = page.evaluate(fallback).await.ok().and_then(|r| r.into_value::<Option<String>>().ok()).flatten() {
        println!("      🎯 Botón de postulación encontrado por texto: '{}'", label);
        return Ok(true);
    }

    dump_apply_button_diagnostics(page).await;
    Ok(false)
}

/// Records what the page actually offered when no apply control was found, so the next
/// failure is diagnosable from evidence instead of guesswork. Also surfaces the common
/// benign explanation: the posting simply closed.
pub async fn dump_apply_button_diagnostics(page: &Page) {
    let script = r#"(() => {
        function visible(el) { return !!(el.offsetWidth || el.offsetHeight || el.getClientRects().length); }
        const buttons = Array.from(document.querySelectorAll("button, a, [role='button']"))
            .filter(visible)
            .map(el => ({
                tag: el.tagName.toLowerCase(),
                text: (el.innerText || '').trim().slice(0, 60),
                aria: (el.getAttribute('aria-label') || '').slice(0, 60),
                inFooter: !!el.closest('footer')
            }))
            .filter(b => b.text || b.aria)
            .slice(0, 60);
        const body = (document.body.innerText || '').toLowerCase();
        const closed = /(no longer accepting applications|ya no acepta solicitudes|no se aceptan solicitudes)/.test(body);
        const inputs = Array.from(document.querySelectorAll('input, textarea, select')).map(el => ({
            tag: el.tagName.toLowerCase(),
            type: (el.type || ''),
            name: (el.getAttribute('name') || '').slice(0, 40),
            visible: visible(el)
        })).slice(0, 40);
        const text = (document.body.innerText || '').replace(/\s+/g, ' ').trim().slice(0, 1200);
        const frames = Array.from(document.querySelectorAll('iframe')).map(f => (f.getAttribute('src') || '').slice(0, 120));
        return JSON.stringify({ url: location.href, closed, title: document.title, frames, inputs, buttons, text }, null, 1);
    })()"#;

    if let Some(report) = page.evaluate(script).await.ok().and_then(|r| r.into_value::<String>().ok()) {
        if report.contains("\"closed\": true") {
            println!("      ℹ️ La oferta ya no acepta solicitudes (cerrada), por eso no hay botón.");
        }
        let _ = std::fs::create_dir_all("debug/dom");
        let path = format!("debug/dom/no_apply_button_{}.json", chrono::Utc::now().timestamp_millis());
        if std::fs::write(&path, &report).is_ok() {
            println!("      🩺 Inventario de botones de la página guardado en {}", path);
        }
    }
}

pub async fn text_visible_on_page(page: &Page, needle: &str) -> bool {
    let script = format!(
        "(() => document.body && document.body.innerText.toLowerCase().includes({needle}))()",
        needle = json!(needle.to_lowercase()),
    );
    page.evaluate(script).await.ok().and_then(|r| r.into_value::<bool>().ok()).unwrap_or(false)
}

/// Reads back the resume filename LinkedIn's UI actually shows as attached, so we can
/// verify the CV we intended to use is the one that really went out — instead of
/// trusting smart_upload_resume's return value, which can be wrong if LinkedIn silently
/// kept a previously-attached document instead of accepting the new upload.
pub async fn read_attached_resume_filename(page: &Page) -> Option<String> {
    let script = r#"(() => {
        function isVisible(el) { return !!(el.offsetWidth || el.offsetHeight || el.getClientRects().length); }
        
        // 1. Check selected / checked resume cards first
        const selectedCards = Array.from(document.querySelectorAll('.jobs-document-card, [class*="resume"], [class*="document"], label, li, div[role="radio"]'))
            .filter(c => isVisible(c) && (c.querySelector('input:checked, [aria-checked="true"]') || c.classList.contains('is-selected') || c.classList.contains('selected')));
            
        for (const c of selectedCards) {
            const text = (c.innerText || c.textContent || '').trim();
            const match = text.match(/([a-zA-Z0-9_\-\.]+\.pdf)/i);
            if (match && match[1].length > 4) {
                return match[1];
            }
        }

        // 2. Check all visible text elements for any .pdf filename mention
        const candidates = Array.from(document.querySelectorAll('span, p, div, label, h3, h4, a'));
        for (const el of candidates) {
            if (!isVisible(el)) continue;
            const text = (el.innerText || el.textContent || '').trim();
            const match = text.match(/([a-zA-Z0-9_\-\.]+\.pdf)/i);
            if (match && match[1].length > 4 && match[1].length < 150) {
                return match[1];
            }
        }
        return null;
    })()"#;
    page.evaluate(script).await.ok().and_then(|r| r.into_value::<Option<String>>().ok()).flatten()
}

/// Searches LinkedIn's rendered saved resume cards / options for the target resume filename
/// (e.g. "CV_D_EN_Jesus_Coronado.pdf") and clicks it if found.
pub async fn select_saved_resume_if_present(page: &Page, target_filename: &str) -> bool {
    let script = format!(
        r#"(() => {{
            function isVisible(el) {{ return !!(el.offsetWidth || el.offsetHeight || el.getClientRects().length); }}
            const target = {target:?}.toLowerCase();
            const containers = Array.from(document.querySelectorAll('label, div[role="radio"], .jobs-document-card, [class*="document-card"], [class*="resume-card"], li'));
            for (const c of containers) {{
                if (!isVisible(c)) continue;
                const text = (c.innerText || c.textContent || '').toLowerCase();
                if (text.includes(target)) {{
                    const radio = c.querySelector('input[type="radio"], input[type="checkbox"]');
                    if (radio) {{
                        radio.checked = true;
                        radio.dispatchEvent(new Event('input', {{ bubbles: true, composed: true }}));
                        radio.dispatchEvent(new Event('change', {{ bubbles: true, composed: true }}));
                    }}
                    c.click();
                    return true;
                }}
            }}
            return false;
        }})()"#,
        target = target_filename
    );
    page.evaluate(script).await.ok().and_then(|r| r.into_value::<bool>().ok()).unwrap_or(false)
}

/// Clicks LinkedIn's "replace / remove resume" control so a new file input appears.
///
/// When a resume is already attached, LinkedIn renders the document card INSTEAD of an
/// upload field — `input[type='file']` simply isn't in the DOM. smart_upload_resume then
/// had nothing to upload into and silently gave up, leaving the stale document attached;
/// that is how the Miratech application went out with a Java Developer CV for a Python
/// Architect role. Deliberately text/ARIA driven: LinkedIn's class names are hashed
/// (`_5e54ca0a`) and churn constantly, so matching on them is what rotted last time.
pub async fn click_replace_resume_control(page: &Page) -> bool {
    let script = r#"(() => {
        function isVisible(el) { return !!(el.offsetWidth || el.offsetHeight || el.getClientRects().length); }

        // LinkedIn's Spanish UI writes "Cargar currículum" WITH accents. Matching raw text
        // against an unaccented pattern silently fails, which is exactly why the first
        // version of this function found no control at all. Strip diacritics before testing.
        function norm(s) { return (s || '').normalize('NFD').replace(/[\u0300-\u036f]/g, '').toLowerCase(); }

        const RE = /(replace|remove|delete|change|choose another|reemplaz|sustitu|quitar|eliminar|cambiar|borrar|elegir otro|subir otro|cargar otro)/;

        function clickableIn(root, mustMatch) {
            const nodes = root.querySelectorAll("button, a, [role='button'], input[type='button']");
            for (const el of nodes) {
                if (!isVisible(el)) continue;
                const raw = ((el.innerText || '') + ' ' + (el.getAttribute('aria-label') || '') + ' ' + (el.getAttribute('title') || '')).trim();
                if (mustMatch.test(norm(raw))) { el.click(); return raw.slice(0, 60); }
            }
            return null;
        }

        // 1. A control sitting next to the attached PDF's name.
        const pdfNode = Array.from(document.querySelectorAll('span, p, div, h3'))
            .find(el => /\.pdf\s*$/i.test((el.innerText || '').trim()) && isVisible(el));
        if (pdfNode) {
            let curr = pdfNode;
            for (let i = 0; i < 5 && curr; i++) {
                curr = curr.parentElement;
                if (!curr) break;
                const hit = clickableIn(curr, RE);
                if (hit) return hit;
            }
        }

        // 2. Anywhere in the dialog: an explicit upload control. Confirmed live — LinkedIn
        // renders no input[type=file] at all while a resume card is shown; the "Cargar
        // currículum" button is what injects it.
        const scope = document.querySelector("div[role='dialog']") || document.body;
        const UPLOAD = /(upload resume|upload cv|cargar curriculum|cargar cv|subir curriculum|subir cv|adjuntar)/;
        const up = clickableIn(scope, UPLOAD);
        if (up) return up;

        return null;
    })()"#;
    match page.evaluate(script).await.ok().and_then(|r| r.into_value::<Option<String>>().ok()).flatten() {
        Some(label) => {
            println!("      🔁 Control de reemplazo de CV accionado: '{}'", label.trim());
            true
        }
        None => false,
    }
}

/// Polls until at least `min` fillable fields exist, or `timeout` elapses; returns the
/// final count.
///
/// External ATS portals are frequently client-rendered single-page apps — BairesDev's
/// serves an Angular bundle whose HTML contains zero inputs and zero forms until the
/// JavaScript boots. The external flow used to sample the field count immediately and
/// again ~1.5s later, giving up after roughly 4 seconds and filing a perfectly good
/// application form as "Manual". Waiting for the app to mount is the fix; no amount of
/// cleverer DOM matching helps when the form does not exist yet.
pub async fn wait_for_form_inputs(page: &Page, min: usize, timeout: Duration) -> usize {
    let started = std::time::Instant::now();
    let mut last = 0usize;
    while started.elapsed() < timeout {
        last = count_form_inputs(page).await;
        if last >= min {
            return last;
        }
        tokio::time::sleep(Duration::from_millis(500)).await;
    }
    last
}

/// Counts the fillable fields visible on the page — the signal external_flow uses to decide
/// "am I on the application form yet?".
///
/// The old version listed explicit `input[type=...]` selectors, which misses a bare
/// `<input>` (no type attribute): the browser treats it as text, but it matches no
/// `input[type='text']` selector. scan_form_structure was already fixed for exactly this,
/// this counter was not — so on ATS sites that ship untyped inputs (confirmed live on
/// BairesDev's applicants portal) the flow concluded it was not on a form, went looking for
/// an "Apply" button that no longer existed, and handed a perfectly fillable form to Manual.
/// Uses the normalized `.type` DOM property, which always resolves (defaults to "text").
pub async fn count_form_inputs(page: &Page) -> usize {
    let script = r#"(() => {
        function visible(el) { return !!(el.offsetWidth || el.offsetHeight || el.getClientRects().length); }
        const SKIP = ['hidden', 'submit', 'button', 'reset', 'image'];
        // LinkedIn's own top-nav search box (and equivalents) must not count as form fields.
        function isChrome(el) { return !!el.closest('header, nav, [role="navigation"], [data-testid*="search" i]'); }

        let n = 0;
        for (const el of document.querySelectorAll('input, textarea, select')) {
            if (isChrome(el) || !visible(el)) continue;
            const type = (el.tagName === 'INPUT') ? String(el.type || 'text').toLowerCase() : 'text';
            if (SKIP.includes(type)) continue;
            n++;
        }
        return n;
    })()"#;
    page.evaluate(script).await.ok().and_then(|r| r.into_value::<usize>().ok()).unwrap_or(0)
}

/// Detects a login/account wall on an external ATS page (Workday, Greenhouse, etc.
/// commonly require an account before letting you apply). A visible password field is
/// the strongest signal; account-creation copy is the fallback. This exists so the
/// external flow never tries to blindly fill credentials it doesn't have — it should
/// hand the job to a human instead.
pub async fn looks_like_login_wall(page: &Page) -> bool {
    let script = r#"(() => {
        const pw = document.querySelector("input[type='password']");
        if (pw && (pw.offsetWidth || pw.offsetHeight || pw.getClientRects().length)) return true;
        const text = (document.body.innerText || '').toLowerCase();
        const markers = [
            'sign in to apply', 'log in to apply', 'sign in to continue', 'please sign in',
            'create an account to apply', 'create your account', 'sign up to apply',
            'iniciar sesión para aplicar', 'inicia sesión para continuar', 'crear una cuenta',
            'crea tu cuenta', 'regístrate para aplicar'
        ];
        return markers.some(m => text.includes(m));
    })()"#;
    page.evaluate(script).await.ok().and_then(|r| r.into_value::<bool>().ok()).unwrap_or(false)
}

const SCAN_JS: &str = r#"
(() => {
    function isVisible(el) {
        return !!(el.offsetWidth || el.offsetHeight || el.getClientRects().length);
    }

    // Scope the scan to the Easy Apply dialog when there is one. `.jobs-easy-apply-modal`
    // is a legacy class LinkedIn's current hashed-class UI no longer emits, so relying on
    // it alone silently widened every scan to the whole document — pulling in unrelated
    // page chrome (global search box, sidebar carousels) as if they were form fields.
    // Prefer semantic role=dialog, then the legacy class, then give up and use document.
    const preferModal = __PREFER_MODAL__;
    let root = document;
    if (preferModal) {
        const dialogs = Array.from(document.querySelectorAll("[role='dialog'], [aria-modal='true'], .jobs-easy-apply-modal"));
        // If several are present (nested/stale dialogs), take the innermost visible one
        // that actually contains form controls.
        const usable = dialogs.filter(d => isVisible(d) && d.querySelector('input, select, textarea, button'));
        if (usable.length) {
            root = usable.reduce((best, d) => (best && best.contains(d)) ? d : (best || d), null) || usable[0];
        }
    }

    function cleanLabel(text) {
        if (!text) return "";
        const lines = text.split("\n").map(l => l.trim()).filter(Boolean);
        const uniq = [];
        for (const l of lines) if (!uniq.includes(l)) uniq.push(l);
        return uniq.join(" ");
    }

    // ¿El portal exige este campo? Sin esto el bot no puede distinguir un campo obligatorio
    // de uno opcional, así que trataba igual a los dos: si no tenía respuesta lo saltaba y
    // enviaba el formulario incompleto, y el ATS lo rechazaba sin que el bot supiera por qué.
    //
    // Se miran las tres formas en que los ATS lo marcan, porque casi ninguno usa las tres:
    // la propiedad/atributo nativo, el ARIA, y el asterisco en la etiqueta (muy común en
    // portales que validan solo del lado del servidor).
    function isRequired(el, labelText) {
        if (el && typeof el.getAttribute === 'function') {
            if (el.required === true) return true;
            if (el.getAttribute('required') !== null) return true;
            if (el.getAttribute('aria-required') === 'true') return true;
            if (el.querySelector && el.querySelector('[required], [aria-required="true"]')) return true;
        }
        return !!(labelText && labelText.includes('*'));
    }

    function getValidationError(el) {
        // Semantic first (survives LinkedIn's hashed-class churn), legacy class as hint.
        if (el.getAttribute && el.getAttribute('aria-invalid') === 'true') {
            const described = el.getAttribute('aria-describedby');
            if (described) {
                const msg = document.getElementById(described);
                if (msg && msg.innerText.trim()) return msg.innerText.trim();
            }
            return 'Campo marcado como inválido';
        }
        let parent = el.parentElement;
        for (let i = 0; i < 3 && parent; i++) {
            const err = parent.querySelector("[role='alert'], .artdeco-inline-feedback--error");
            if (err && isVisible(err) && err.innerText.trim()) return err.innerText.trim();
            parent = parent.parentElement;
        }
        return null;
    }

    // Counts the form controls inside a subtree. Used to decide whether a label found by
    // crawling ancestors can be trusted to belong to `el` specifically.
    function controlCount(node) {
        return node.querySelectorAll('input, select, textarea').length;
    }

    function getLabel(el) {
        // NOTE (incident 2026-08-18): this used to jump straight to crawling ancestors and
        // calling `curr.querySelector('label')`, which returns the FIRST label anywhere in
        // that ancestor's subtree — not the label bound to `el`. As soon as the crawl
        // reached a container holding several fields, every input inside it inherited the
        // same label. Confirmed live on Miratech: the city typeahead (which has only a
        // placeholder, no label of its own) was reported as "First name*", so the bot typed
        // "Jesus" into the address field and the city suggestion list never closed.
        // Explicit, standards-defined associations are now tried first, and the ancestor
        // crawl only accepts a label from a container that holds exactly one control.

        // 1. aria-label directly on the control.
        const aria = (el.getAttribute('aria-label') || '').trim();
        if (aria) return aria;

        // 2. aria-labelledby (may reference several ids, space-separated).
        const labelledBy = (el.getAttribute('aria-labelledby') || '').trim();
        if (labelledBy) {
            const txt = labelledBy.split(/\s+/)
                .map(refId => { const r = document.getElementById(refId); return r ? r.innerText.trim() : ''; })
                .filter(Boolean).join(' ').trim();
            if (txt) return txt;
        }

        // 3. <label for="..."> — the real HTML association. LinkedIn DOES set this on every
        // labeled field; the ids are React-generated and contain non-ASCII characters
        // (e.g. «ro»), so they must go through CSS.escape to form a valid selector.
        if (el.id) {
            let bound = null;
            try {
                const sel = (window.CSS && CSS.escape) ? 'label[for="' + CSS.escape(el.id) + '"]' : null;
                if (sel) bound = document.querySelector(sel);
            } catch (e) { bound = null; }
            if (!bound) {
                // Fallback when CSS.escape is unavailable: scan labels and compare htmlFor.
                bound = Array.from(document.querySelectorAll('label')).find(l => l.htmlFor === el.id) || null;
            }
            if (bound) {
                const txt = bound.innerText.trim();
                if (txt) return txt;
            }
        }

        // 4. The control wrapped inside its own <label>.
        const wrapping = el.closest('label');
        if (wrapping) {
            const txt = wrapping.innerText.trim();
            if (txt) return txt;
        }

        // 5. Preceding sibling (Teamtailor, micro1, Greenhouse, Lever, etc.)
        let prev = el.previousElementSibling;
        while (prev) {
            const txt = (prev.innerText || prev.textContent || '').trim();
            if (txt && txt.length > 2 && txt.length < 300) {
                return txt;
            }
            prev = prev.previousElementSibling;
        }

        // 6. Ancestor crawl — finding label, paragraph, legend, heading or question title
        let curr = el;
        for (let i = 0; i < 5 && curr; i++) {
            curr = curr.parentElement;
            if (!curr) break;
            const labelEl = curr.querySelector('label, legend, p, h1, h2, h3, h4, h5, h6, [class*="question"], [class*="title"], [class*="label"], span.fb-dash-form-element__label');
            if (labelEl && isVisible(labelEl)) {
                const txt = (labelEl.innerText || labelEl.textContent || '').trim();
                if (txt && txt.length > 2 && txt.length < 300) return txt;
            }
        }

        // 7. Placeholder
        const ph = (el.getAttribute('placeholder') || '').trim();
        if (ph) return ph;

        const nameAttr = (el.getAttribute('name') || el.getAttribute('id') || el.getAttribute('data-testid') || '').trim();
        if (nameAttr) return nameAttr;

        return "Unknown Field";
    }

    function getLabelForGroup(el) {
        // 0. aria-label directly on the group.
        const ownAria = el.getAttribute('aria-label');
        if (ownAria && ownAria.trim()) return ownAria.trim();

        // 1. aria-labelledby.
        const idRef = el.getAttribute('aria-labelledby');
        if (idRef) {
            const refEl = document.getElementById(idRef);
            if (refEl && refEl.innerText.trim()) return refEl.innerText.trim();
        }

        // 2. The group's own text minus its option <label>s — many forms put the
        // question itself as a bare text node or <span>/<div> directly inside the
        // fieldset/group, before the radio/checkbox options, with no dedicated class.
        const clone = el.cloneNode(true);
        clone.querySelectorAll('label, input, select, textarea, button').forEach(n => n.remove());
        const ownText = (clone.innerText || '').trim();
        if (ownText.length > 2) return ownText;

        const parent = el.parentElement;
        if (parent) {
            // 3. A labeled element among the group's siblings (not inside the group itself).
            const potential = parent.querySelector("span.fb-dash-form-element__label, label, legend, h3, h4");
            if (potential && isVisible(potential) && !el.contains(potential)) return potential.innerText.trim();

            // 4. Walk backwards through previous siblings looking for any visible text —
            // covers "class/id tells you nothing" cases where the question sits right
            // before the group with no semantic markup at all.
            let sib = el.previousElementSibling;
            for (let hops = 0; sib && hops < 4; hops++) {
                const text = (sib.innerText || '').trim();
                if (text.length > 2 && text.length < 300) return text;
                sib = sib.previousElementSibling;
            }
        }

        // 5. Grandparent as a last resort.
        const grandparent = parent ? parent.parentElement : null;
        if (grandparent) {
            const potential = grandparent.querySelector("span.fb-dash-form-element__label, legend");
            if (potential && isVisible(potential) && !el.contains(potential)) return potential.innerText.trim();
        }

        return "";
    }

    const schema = [];
    let counter = 0;

    // Scan EVERY input/textarea in the root — never a hardcoded list of `type=`
    // selectors. A bare `<input>` (no type attribute) behaves as text in the browser but
    // does NOT match `input[type='text']`, so any such field was invisible to the scan
    // and therefore never filled. Confirmed live: LinkedIn's City typeahead showed its
    // suggestion list on screen yet never appeared in the scanned schema, leaving a
    // required field empty — LinkedIn then silently refused to advance, and the flow
    // re-scanned the same step 15 times in a row.
    //
    // Use the normalized `el.type` DOM *property* (always populated, defaults to "text")
    // rather than the `type` *attribute* (null on bare inputs).
    const SKIP_TYPES = ['hidden', 'submit', 'button', 'reset', 'image', 'file', 'checkbox', 'radio', 'password'];
    const TEXT_LIKE = ['text', 'search', 'url', 'email', 'tel'];
    // Exclude LinkedIn's own global chrome (top nav, site-wide search box) — confirmed
    // live: when modal-scoping falls back to the whole document, the global "Buscar"
    // search input (data-testid="typeahead-input", componentkey contains "Search") gets
    // scanned as if it were a form field, gets typed into (e.g. a city name), and Enter
    // submits a site-wide search instead of selecting a suggestion — the bot ends up
    // navigating away from the application entirely instead of filling the real field.
    function isGlobalChrome(el) {
        return !!el.closest('header, nav, [role="navigation"], [componentkey*="Search"], [data-testid*="search" i]');
    }

    root.querySelectorAll('input, textarea').forEach(inp => {
        if (inp.hasAttribute('data-tf-id')) return;
        if (isGlobalChrome(inp)) return;
        const rawType = (inp.tagName === 'TEXTAREA') ? 'text' : String(inp.type || 'text').toLowerCase();
        // radio/checkbox are handled by the group pass below; file by the resume manager;
        // password is never auto-filled by design.
        if (SKIP_TYPES.includes(rawType)) return;
        if (!isVisible(inp)) return;

        // Normalize to the categories form.rs dispatches on. Anything exotic
        // (date/range/color/…) is reported as "unknown" so it goes through the generic
        // fallback filler instead of being silently dropped.
        let reportedType;
        if (rawType === 'number') reportedType = 'number';
        else if (TEXT_LIKE.includes(rawType)) reportedType = 'text';
        else reportedType = 'unknown';

        const id = 'tf_' + (counter++);
        inp.setAttribute('data-tf-id', id);
        const label = cleanLabel(getLabel(inp));
        const autoComplete = inp.getAttribute('aria-autocomplete');
        schema.push({
            id, type: reportedType, label,
            value: inp.value || "",
            error: getValidationError(inp),
            required: isRequired(inp, label),
            options: [],
            // Diagnostic only — fill_text_like_field probes behaviorally instead of
            // trusting these attributes, which LinkedIn no longer sets reliably.
            is_combobox: inp.getAttribute('role') === 'combobox' || autoComplete === 'list' || autoComplete === 'both',
            raw_html: (reportedType === 'unknown') ? inp.outerHTML.slice(0, 2000) : null
        });
    });

    root.querySelectorAll('select').forEach(sel => {
        if (isGlobalChrome(sel)) return;
        if (!isVisible(sel)) return;
        const id = 'tf_' + (counter++);
        sel.setAttribute('data-tf-id', id);
        const label = cleanLabel(getLabel(sel));
        const options = Array.from(sel.querySelectorAll('option'))
            .map(o => o.innerText.trim())
            .filter(o => o && !o.toLowerCase().includes('selecciona') && !o.toLowerCase().includes('select'));
        schema.push({ id, type: 'select', label, value: sel.value || "", error: getValidationError(sel), required: isRequired(sel, label), options, is_combobox: false });
    });

    root.querySelectorAll("fieldset, div[role='group']").forEach(grp => {
        if (isGlobalChrome(grp)) return;
        if (!isVisible(grp)) return;
        let labelText = "";
        const legend = grp.querySelector('legend');
        if (legend) labelText = legend.innerText.trim();
        if (!labelText) labelText = getLabelForGroup(grp);
        if (!labelText) labelText = "Unknown Group Choice";
        labelText = cleanLabel(labelText);

        const labels = Array.from(grp.querySelectorAll('label'));
        if (labels.length === 0) return;

        const firstInput = grp.querySelector('input');
        const inputType = firstInput ? (firstInput.getAttribute('type') || 'radio') : 'radio';

        const id = 'tf_' + (counter++);
        grp.setAttribute('data-tf-id', id);
        const options = labels.map(l => l.innerText.trim()).filter(Boolean);
        const rawHtml = (labelText === "Unknown Group Choice") ? grp.outerHTML.slice(0, 4000) : null;
        schema.push({ id, type: inputType, label: labelText, value: "", error: getValidationError(grp), required: isRequired(grp, labelText), options, is_combobox: false, raw_html: rawHtml });
    });

    // Scan custom button choice groups (e.g. Recruiterflow, Workday, Greenhouse custom Yes/No toggle buttons).
    // Restricted to a closed set of answer words (not "any short button text") and requiring a real
    // question label nearby — otherwise this over-broad container selector (any *group*/*container*
    // class, which is nearly every wrapper div in a React app) matches unrelated button pairs like
    // cookie-banner Accept/Reject, modal Cancel/Confirm, or pagination Previous/Next, registers them
    // as a fake required radio field, and risks the agent clicking one of those buttons for real.
    const CHOICE_ANSWER_WORDS = new Set([
        'yes', 'no', 'si', 'sí', 'true', 'false', 'agree', 'disagree', 'n/a', 'na',
        'acepto', 'de acuerdo', 'verdadero', 'falso',
    ]);
    function choiceButtonText(el) {
        return (el.innerText || el.textContent || el.getAttribute('aria-label') || '').trim();
    }
    // El enunciado de la pregunta = el texto del contenedor una vez quitados los controles.
    // Sirve igual si la pregunta está en <p>, <label>, <legend>, un <span> suelto o un nodo
    // de texto pelado, sin depender de que alguien le haya puesto una clase reconocible.
    function questionTextOf(el) {
        if (!el) return "";
        const clone = el.cloneNode(true);
        clone.querySelectorAll("button, [role='button'], [role='radio'], [role='checkbox'], input, select, textarea").forEach(n => n.remove());
        return cleanLabel(clone.innerText || clone.textContent || '');
    }

    // Se parte de LOS BOTONES y se sube al contenedor. La versión anterior partía de un
    // selector de contenedor por nombre de clase, así que una pregunta envuelta en
    // `<div class="question-row">` o `<div class="field">` era invisible para el escáner y
    // el bot enviaba el formulario sin contestarla.
    const answerButtons = Array.from(root.querySelectorAll("button, [role='button'], [role='radio']"))
        .filter(b => isVisible(b) && !b.disabled && CHOICE_ANSWER_WORDS.has(choiceButtonText(b).toLowerCase()));

    const claimedButtons = new Set();
    for (const btn of answerButtons) {
        if (claimedButtons.has(btn) || btn.closest('[data-tf-id]')) continue;

        // Ancestro más pequeño que agrupe 2+ botones de respuesta: así dos preguntas
        // consecutivas no se fusionan en un solo campo.
        let container = null;
        let members = null;
        let anc = btn.parentElement;
        for (let i = 0; i < 5 && anc; i++) {
            const inside = answerButtons.filter(b => anc.contains(b));
            if (inside.length >= 2) { container = anc; members = inside; break; }
            anc = anc.parentElement;
        }
        if (!container || container.hasAttribute('data-tf-id') || container.closest('[data-tf-id]')) {
            claimedButtons.add(btn);
            continue;
        }

        let labelText = questionTextOf(container);
        if (!labelText || labelText.length > 300) labelText = questionTextOf(container.parentElement);

        // Sin enunciado no se registra el campo: es lo que evita inventar una pregunta falsa
        // para un par de botones cualquiera (cookies Aceptar/Rechazar, modal Cancelar/Confirmar).
        if (!labelText || labelText.length > 300) {
            members.forEach(m => claimedButtons.add(m));
            continue;
        }

        members.forEach(m => claimedButtons.add(m));
        const id = 'tf_' + (counter++);
        container.setAttribute('data-tf-id', id);
        const options = members.map(choiceButtonText).filter(Boolean);
        schema.push({ id, type: 'radio', label: labelText, value: "", error: getValidationError(container), required: isRequired(container, labelText), options, is_combobox: false, raw_html: null });
    }

    const ungrouped = {};
    root.querySelectorAll("input[type='radio'], input[type='checkbox']").forEach(inp => {
        if (inp.hasAttribute('data-tf-id') || inp.closest('[data-tf-id]')) return;
        if (!isVisible(inp) && !isVisible(inp.closest('label') || inp.parentElement)) return;
        const name = inp.getAttribute('name') || 'unnamed_' + inp.getAttribute('value');
        if (!ungrouped[name]) ungrouped[name] = [];
        ungrouped[name].push(inp);
    });

    for (const name in ungrouped) {
        const groupInputs = ungrouped[name];
        if (groupInputs.length === 0) continue;
        const first = groupInputs[0];
        const inputType = first.getAttribute('type') || 'radio';
        const id = 'tf_' + (counter++);
        // Mark the first one with the ID just so we have a target for DOM interactions
        first.setAttribute('data-tf-id', id);
        
        let labelText = cleanLabel(getLabelForGroup(first.closest('div') || first.parentElement) || getLabel(first) || "Ungrouped Options");
        const options = groupInputs.map(inp => {
            const lbl = inp.closest('label');
            if (lbl) return cleanLabel(lbl.innerText);
            if (inp.id) {
                const bound = document.querySelector(`label[for="${CSS.escape(inp.id)}"]`);
                if (bound) return cleanLabel(bound.innerText);
            }
            return inp.getAttribute('value') || '';
        }).filter(Boolean);
        
        schema.push({ id, type: inputType, label: labelText, value: "", error: getValidationError(first), required: isRequired(first, labelText), options, is_combobox: false, raw_html: null });
    }

    // Catch-all: any other visible, labeled, interactive element inside the form root

    // that wasn't already tagged (contenteditable widgets, date/range/color inputs,
    // custom role=combobox elements that aren't plain <input>, etc.) — instead of being
    // invisible to the schema (and therefore silently skipped), report it as
    // type "unknown" so form.rs can send it through the generic fallback filler and, if
    // that fails too, surface it as an explicit NeedsHuman rather than a silent no-op.
    const knownSelector = "input[type='text'], input[type='number'], input[type='email'], input[type='tel'], textarea, select, [data-tf-id]";
    const unknownSelector = "[contenteditable='true'], input[type='date'], input[type='range'], input[type='color'], input[type='month'], input[type='week'], [role='combobox']:not(input), [role='textbox']:not(input):not(textarea)";
    root.querySelectorAll(unknownSelector).forEach(el => {
        if (el.hasAttribute('data-tf-id') || el.closest('[data-tf-id]')) return;
        if (el.matches(knownSelector)) return;
        if (isGlobalChrome(el)) return;
        if (!isVisible(el)) return;
        const id = 'tf_' + (counter++);
        el.setAttribute('data-tf-id', id);
        const label = cleanLabel(getLabel(el));
        schema.push({
            id, type: 'unknown', label,
            value: (el.value || el.innerText || '').trim(),
            error: getValidationError(el),
            required: isRequired(el, label),
            options: [], is_combobox: false,
            raw_html: el.outerHTML.slice(0, 2000)
        });
    });

    const rootHtml = (root && root.outerHTML) ? root.outerHTML : (document.body ? document.body.outerHTML : '');
    return JSON.stringify({ fields: schema, root_html: rootHtml.slice(0, 300000) });
})()
"#;
