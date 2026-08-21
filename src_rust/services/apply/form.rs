use super::dom::{self, FormField};
use super::resume_manager::ResumeManager;
use crate::services::AiClient;
use anyhow::Result;
use chromiumoxide::Page;
use regex::Regex;
use std::collections::HashMap;

/// Everything the flow needs to know about the job currently being applied to.
/// Mirrors the `job_context` dict threaded through Python's application_flow.py /
/// form_handler.py / external_flow.py.
#[derive(Debug, Clone)]
pub struct JobContext {
    pub id: i64,
    pub role: String,
    pub company: String,
    pub location: String,
    pub description: String,
    /// Original LinkedIn job URL — kept so the flow can reload it after an ambiguous
    /// step and check LinkedIn's own "Application submitted" confirmation, instead of
    /// trusting that a click succeeded.
    pub url: String,
    pub target_resume: std::path::PathBuf,
    pub actual_resume: Option<String>,
    pub applied_salary: Option<String>,
    pub applied_currency: Option<String>,
}

const SALARY_KEYWORDS: &[&str] = &["salary", "expectation", "aspiración", "salario", "pretendido", "remuneration", "compensación", "tarifa", "expectativa"];
const YEARS_KEYWORDS: &[&str] = &["years of", "años de", "how many years", "cuántos años", "cuantos años", "years", "años", "experiencia", "experience"];

fn clean_label_for_match(label: &str) -> String {
    label.chars().filter(|c| !['*', '?', '¿', ':'].contains(c)).collect::<String>().trim().to_lowercase()
}

fn get_answer_for_label(label: &str, answers: &HashMap<String, String>) -> Option<String> {
    if let Some(v) = answers.get(label) {
        return Some(v.clone());
    }
    let clean_label = clean_label_for_match(label);
    for (k, v) in answers {
        let clean_k = clean_label_for_match(k);
        if clean_label == clean_k || clean_k.contains(&clean_label) || clean_label.contains(&clean_k) {
            return Some(v.clone());
        }
    }
    None
}

fn extract_first_number(text: &str) -> Option<String> {
    let re = Regex::new(r"(\d+(?:\.\d+)?)").ok()?;
    re.captures(text).map(|c| c[1].to_string())
}

/// Everything the caller needs to know about how a form step went: what salary/currency
/// were captured, and — critically — whether any field came back `NeedsHuman`. The flow
/// loops (application_flow.rs / external_flow.rs) must check `needs_human` and stop
/// immediately rather than clicking Next/Submit past a field known to be wrong.
pub struct FillResult {
    pub captured: HashMap<String, String>,
    pub needs_human: Vec<String>,
    /// Identity of the step that was just scanned (its field labels, joined). If two
    /// consecutive iterations produce the same fingerprint, the "Next" click didn't
    /// actually advance the form and the flow must stop instead of looping.
    pub fingerprint: String,
}

/// Scans the current form step, resolves deterministic answers (salary/years-per-skill)
/// locally, asks the AI for everything else, then fills the DOM. Returns any captured
/// salary/currency plus a list of fields that couldn't be resolved with confidence.
/// Mirrors src/app/bots/apply/form_handler.py::fill_form.
pub async fn fill_form(
    page: &Page,
    ai_client: &AiClient,
    resume_manager: &ResumeManager,
    ctx: &JobContext,
    profile_skills: &HashMap<String, HashMap<String, crate::domain::models::SkillInfo>>,
    prefer_modal: bool,
) -> Result<FillResult> {
    let schema = dom::scan_form_structure(page, prefer_modal).await?;
    if schema.is_empty() {
        return Ok(FillResult { captured: HashMap::new(), needs_human: Vec::new(), fingerprint: String::new() });
    }
    let fingerprint = schema.iter().map(|f| f.label.as_str()).collect::<Vec<_>>().join("|");
    println!(
        "   📝 Form Scan ({} @ {} — {} chars desc): {} campos detectados.",
        ctx.role,
        ctx.company,
        ctx.description.len(),
        schema.len()
    );

    // --- Deterministic fast path (no AI round-trip needed) ---
    let mut deterministic: HashMap<String, String> = HashMap::new();
    for field in &schema {
        let label_lower = field.label.to_lowercase();

        if SALARY_KEYWORDS.iter().any(|k| label_lower.contains(k)) {
            let val = ctx.applied_salary.clone().unwrap_or_else(|| "3000".to_string());
            deterministic.insert(field.label.clone(), val);
            continue;
        }

        if label_lower.contains("linkedin") || label_lower.contains("perfil") {
            deterministic.insert(field.label.clone(), "https://www.linkedin.com/in/jcoronado1982/".to_string());
            continue;
        }

        if label_lower.contains("first name") || label_lower.contains("primer nombre") || label_lower == "nombre" || label_lower == "nombre*" {
            deterministic.insert(field.label.clone(), "Jesus".to_string());
            continue;
        }

        if label_lower.contains("last name") || label_lower.contains("apellido") {
            deterministic.insert(field.label.clone(), "Coronado".to_string());
            continue;
        }

        if label_lower.contains("email") || label_lower.contains("correo") {
            deterministic.insert(field.label.clone(), "email.coronado@gmail.com".to_string());
            continue;
        }

        if label_lower.contains("country") || label_lower.contains("país") || label_lower.contains("pais") || label_lower.contains("código") || label_lower.contains("codigo") {
            deterministic.insert(field.label.clone(), "Colombia".to_string());
            continue;
        }

        if label_lower.contains("phone") || label_lower.contains("teléfono") || label_lower.contains("celular") || label_lower.contains("móvil") || label_lower.contains("telefono") {
            deterministic.insert(field.label.clone(), "3007128140".to_string());
            continue;
        }

        if label_lower.contains("disponibilidad") || label_lower.contains("on site") || label_lower.contains("hibrid") || label_lower.contains("modalidad") || label_lower.contains("presencial") {
            deterministic.insert(field.label.clone(), "Sí".to_string());
            continue;
        }

        if label_lower.contains("inglés") || label_lower.contains("ingles") || label_lower.contains("english") {
            deterministic.insert(field.label.clone(), "B2 - Conversational".to_string());
            continue;
        }

        if YEARS_KEYWORDS.iter().any(|k| label_lower.contains(k)) {
            'outer: for category in profile_skills.values() {
                for (skill_name, info) in category {
                    if label_lower.contains(&skill_name.to_lowercase()) {
                        deterministic.insert(field.label.clone(), info.years.to_string());
                        break 'outer;
                    }
                }
            }
        }
    }

    let form_payload: Vec<FormField> = schema.iter().filter(|f| !deterministic.contains_key(&f.label)).cloned().collect();

    let mut answers: HashMap<String, String> = HashMap::new();
    if !form_payload.is_empty() {
        println!("      🤖 Consultando IA para {} preguntas...", form_payload.len());
        let profile_yaml = resume_manager.build_profile_yaml(Some(&ctx.location));
        match ai_client
            .answer_form(&form_payload, &profile_yaml, ctx.applied_salary.as_deref(), ctx.applied_currency.as_deref(), Some(&ctx.location))
            .await
        {
            Ok(ai_answers) => answers.extend(ai_answers),
            Err(e) => eprintln!("      ⚠️ Error consultando IA para el formulario: {}", e),
        }
    }
    // Deterministic answers always win over the AI's for the same label.
    answers.extend(deterministic);

    if answers.is_empty() {
        println!("      ⚠️ No se generaron respuestas para este paso.");
        return Ok(FillResult { captured: HashMap::new(), needs_human: Vec::new(), fingerprint });
    }

    let mut captured = HashMap::new();
    let mut needs_human = Vec::new();

    for field in &schema {
        let label_lower = field.label.to_lowercase();
        let answer = get_answer_for_label(&field.label, &answers);
        let blank = answer.as_ref().map(|a| a.trim().is_empty()).unwrap_or(true);
        if blank {
            // A blank answer must never be "filled" — for choice fields, matching an
            // empty string against option text always matches the FIRST option
            // (every string contains ""), which would silently click a wrong,
            // unintended answer. Skip and let this surface as a stuck/Manual step
            // instead of picking a guess.
            //
            // Pero un campo OBLIGATORIO sin respuesta no se puede saltar en silencio: el
            // portal va a rechazar el envío entero y el bot se quedaba reintentando el mismo
            // paso sin saber por qué. Se reporta para que el agente (que ve la página real)
            // lo resuelva en vez de darlo por perdido.
            if field.required && field.value.trim().is_empty() {
                println!("      -> ❗ '{}' es OBLIGATORIO y quedó sin respuesta; se releva al agente.", field.label.chars().take(40).collect::<String>());
                needs_human.push(format!("{}: campo obligatorio sin respuesta resuelta", field.label));
            } else {
                println!("      -> [SKIP] '{}' sin respuesta resuelta (posible etiqueta mal detectada).", field.label.chars().take(40).collect::<String>());
            }
            continue;
        }
        let mut ans = answer.unwrap_or_default();

        let is_salary = SALARY_KEYWORDS.iter().any(|k| label_lower.contains(k));
        let is_years = YEARS_KEYWORDS.iter().any(|k| label_lower.contains(k));

        if is_salary {
            if let Some(resolved) = &ctx.applied_salary {
                ans = resolved.clone();
            }
            captured.insert("salary".to_string(), ans.clone());
            if let Some(c) = &ctx.applied_currency {
                captured.insert("currency".to_string(), c.clone());
            }
        }

        if is_salary || is_years || field.field_type == "number" {
            match extract_first_number(&ans) {
                Some(digits) => ans = digits,
                None if is_years => ans = "1".to_string(),
                None => {}
            }
        }

        let is_phone = field.field_type == "tel" || label_lower.contains("phone") || label_lower.contains("tel") || label_lower.contains("celular") || label_lower.contains("móvil");
        let val_trimmed = field.value.trim();
        let is_incomplete_phone = is_phone && (val_trimmed.len() < 7 || val_trimmed == "-57" || val_trimmed == "+57" || val_trimmed == "57");

        if !val_trimmed.is_empty() && field.error.is_none() && !is_incomplete_phone {
            println!("      -> [SKIP] '{}' ya está lleno.", label_lower.chars().take(20).collect::<String>());
            continue;
        }

        println!("      -> [FILL] '{}' con: '{}'", field.label.chars().take(30).collect::<String>(), ans);

        let outcome = match field.field_type.as_str() {
            "text" | "email" | "tel" | "number" => dom::fill_text_like_field(page, &field.id, &ans).await,
            "select" => match dom::fill_select_field(page, &field.id, &ans).await {
                Ok(true) => Ok(dom::FillOutcome::Filled),
                Ok(false) => {
                    if label_lower.contains("country") || label_lower.contains("país") || label_lower.contains("pais") || label_lower.contains("código") || label_lower.contains("code") {
                        println!("      ℹ️ Selector de país/código conservó su valor predeterminado.");
                        Ok(dom::FillOutcome::Filled)
                    } else {
                        Ok(dom::FillOutcome::NeedsHuman(format!("Select '{}' sin opción coincidente", field.label)))
                    }
                }
                Err(e) => Err(e),
            },
            "radio" | "checkbox" => {
                let targets: Vec<String> = ans.split(',').map(|s| s.trim().to_string()).collect();
                match dom::fill_choice_field(page, &field.id, &field.field_type, &targets).await {
                    Ok(true) => Ok(dom::FillOutcome::Filled),
                    Ok(false) => Ok(dom::FillOutcome::NeedsHuman(format!("Opción '{}' no encontrada en '{}'", ans, field.label))),
                    Err(e) => Err(e),
                }
            }
            "unknown" => dom::fill_generic_fallback(page, &field.id, &ans).await,
            other => Ok(dom::FillOutcome::NeedsHuman(format!("Tipo de campo no soportado '{}' en '{}'", other, field.label))),
        };

        match outcome {
            Ok(dom::FillOutcome::NeedsHuman(reason)) => {
                println!("         ⚠️ Necesita revisión humana: {}", reason);
                needs_human.push(format!("{}: {}", field.label, reason));
            }
            Ok(dom::FillOutcome::NotFound) => {
                println!("         ⚠️ El campo '{}' desapareció del DOM antes de llenarlo.", field.label);
            }
            Ok(_) => {}
            Err(e) => println!("         ❌ Error llenando campo: {}", e),
        }

        tokio::time::sleep(std::time::Duration::from_millis(150)).await;
    }

    Ok(FillResult { captured, needs_human, fingerprint })
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn matches_answer_by_exact_label() {
        let mut answers = HashMap::new();
        answers.insert("City".to_string(), "Bogotá".to_string());
        assert_eq!(get_answer_for_label("City", &answers), Some("Bogotá".to_string()));
    }

    #[test]
    fn matches_answer_fuzzily_ignoring_punctuation_and_substrings() {
        let mut answers = HashMap::new();
        answers.insert("Years of experience with Python?".to_string(), "7".to_string());
        assert_eq!(get_answer_for_label("Years of experience with Python", &answers), Some("7".to_string()));
    }

    #[test]
    fn no_match_returns_none() {
        let answers = HashMap::new();
        assert_eq!(get_answer_for_label("Unrelated question", &answers), None);
    }

    #[test]
    fn extracts_first_number_from_verbose_ai_answer() {
        assert_eq!(extract_first_number("Approximately 5 years"), Some("5".to_string()));
        assert_eq!(extract_first_number("4000 USD monthly"), Some("4000".to_string()));
        assert_eq!(extract_first_number("no digits here"), None);
    }
}
