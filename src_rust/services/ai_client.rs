use anyhow::{Context, Result};
use serde::{Deserialize, Serialize};
use serde_json::{json, Value};

#[derive(Debug, Clone)]
pub struct AiClient {
    client: reqwest::Client,
    gemini_api_key: Option<String>,
    gemini_model: String,
    wasp_url: String,
    local_ai_url: String,
    local_ai_model: String,
}

#[derive(Serialize)]
struct GeminiPart {
    text: String,
}

#[derive(Serialize)]
struct GeminiContent {
    parts: Vec<GeminiPart>,
}

#[derive(Serialize)]
struct GeminiPayload {
    contents: Vec<GeminiContent>,
}

#[derive(Deserialize)]
struct GeminiCandidatePart {
    text: Option<String>,
}

#[derive(Deserialize)]
struct GeminiCandidateContent {
    parts: Option<Vec<GeminiCandidatePart>>,
}

#[derive(Deserialize)]
struct GeminiCandidate {
    content: Option<GeminiCandidateContent>,
}

#[derive(Deserialize)]
struct GeminiResponse {
    candidates: Option<Vec<GeminiCandidate>>,
}

#[derive(Serialize)]
struct WaspPromptPayload {
    prompt: String,
}

#[derive(Deserialize)]
struct WaspPromptResponse {
    response: String,
}

/// Generic client for Ollama's native /api/chat endpoint (mirrors
/// src/services/ai/local_client.py::LocalLLMClient).
#[derive(Serialize)]
struct OllamaChatMessage {
    role: String,
    content: String,
}

#[derive(Serialize)]
struct OllamaChatPayload {
    model: String,
    messages: Vec<OllamaChatMessage>,
    stream: bool,
    format: String,
}

#[derive(Deserialize)]
struct OllamaChatMessageResponse {
    content: String,
}

#[derive(Deserialize)]
struct OllamaChatResponse {
    message: OllamaChatMessageResponse,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct AnalysisResult {
    pub match_score: f64,
    pub status: String,
    pub skills: Vec<String>,
    pub summary: String,
}

impl AiClient {
    pub fn new() -> Self {
        Self::with_profile(None)
    }

    /// Env vars always win (matches Python's Settings precedence); `config/profile_config.json`'s
    /// `ai_config` block fills in whatever the environment doesn't set.
    pub fn with_profile(profile: Option<&crate::domain::models::ProfileConfig>) -> Self {
        let ai_config = profile.and_then(|p| p.ai_config.as_ref());

        let gemini_key = std::env::var("GEMINI_API_KEY").ok().filter(|s| !s.is_empty());
        let gemini_model = std::env::var("GEMINI_MODEL").ok().or_else(|| ai_config.and_then(|c| c.cloud_model.clone())).unwrap_or_else(|| "gemini-1.5-pro".to_string());
        let wasp_url = std::env::var("WASP_URL").ok().or_else(|| ai_config.and_then(|c| c.wasp_url.clone())).unwrap_or_else(|| "http://localhost:3000".to_string());
        let local_ai_url = std::env::var("LOCAL_AI_URL").ok().or_else(|| ai_config.and_then(|c| c.local_url.clone())).unwrap_or_else(|| "http://localhost:11434".to_string());
        let local_ai_model = std::env::var("LOCAL_AI_MODEL").ok().or_else(|| ai_config.and_then(|c| c.local_model.clone())).unwrap_or_else(|| "llama3".to_string());

        Self {
            client: reqwest::Client::builder()
                .timeout(std::time::Duration::from_secs(120))
                .build()
                .unwrap_or_default(),
            gemini_api_key: gemini_key,
            gemini_model,
            wasp_url,
            local_ai_url,
            local_ai_model,
        }
    }

    pub async fn analyze_job(&self, role: &str, company: &str, requirements: &str) -> Result<AnalysisResult> {
        let current_dir = std::env::current_dir().unwrap_or_else(|_| std::path::PathBuf::from("."));
        let prompt_path = current_dir.join("prompts").join("analyze_job.txt");
        let profile_path = current_dir.join("config").join("profile_config.json");

        let base_prompt = std::fs::read_to_string(&prompt_path)
            .unwrap_or_else(|_| "You are an expert technical recruiter. Analyze the job description against candidate profile.".to_string());
        let profile_content = std::fs::read_to_string(&profile_path)
            .unwrap_or_else(|_| "{ \"personal_info\": { \"full_name\": \"Jesus Coronado\" } }".to_string());

        let prompt = format!(
            "{}\n\n=== CANDIDATE PROFILE (JSON) ===\n{}\n\n=== JOB TO ANALYZE ===\nROLE: {}\nCOMPANY: {}\nDESCRIPTION / REQUIREMENTS:\n{}\n\nRespond ONLY with the JSON schema requested in the prompt.",
            base_prompt, profile_content, role, company, requirements
        );

        // 1. Si hay Gemini API Key configurada, usar Gemini directamente
        if let Some(ref api_key) = self.gemini_api_key {
            println!("🤖 [AI Client] Consultando Gemini API ({}) para '{}' en '{}'...", self.gemini_model, role, company);
            match self.call_gemini(&prompt, api_key).await {
                Ok(raw_text) => {
                    return self.parse_json_response(&raw_text, role, company);
                }
                Err(e) => {
                    eprintln!("⚠️ [AI Client] Error con Gemini API: {}. Intentando fallback...", e);
                }
            }
        }

        // 2. Fallback a Steel Wasp si está disponible
        println!("🤖 [AI Client] Consultando Steel Wasp en {}...", self.wasp_url);
        match self.call_wasp(&prompt).await {
            Ok(raw_text) => {
                return self.parse_json_response(&raw_text, role, company);
            }
            Err(e) => {
                eprintln!("⚠️ [AI Client] Error con Steel Wasp: {}. Probando modelo local (Ollama)...", e);
            }
        }

        // 3. Fallback a modelo local vía Ollama (paridad con LocalLLMClient de Python)
        match self.call_local(&prompt).await {
            Ok(raw_text) => {
                return self.parse_json_response(&raw_text, role, company);
            }
            Err(e) => {
                eprintln!("⚠️ [AI Client] Error con modelo local: {}. Usando análisis heurístico...", e);
            }
        }

        // 4. Fallback Heurístico si no hay conexión a internet o fallan todos los LLMs
        let extracted_skills = crate::services::Normalizer::extract_skills_heuristic(requirements);
        let score = if !extracted_skills.is_empty() { 75.0 } else { 50.0 };
        let status = if score >= 60.0 { "Matched" } else { "Discarded" };

        Ok(AnalysisResult {
            match_score: score,
            status: status.to_string(),
            skills: extracted_skills,
            summary: format!("Análisis heurístico local para {} en {}", role, company),
        })
    }

    async fn call_gemini(&self, prompt: &str, api_key: &str) -> Result<String> {
        self.call_gemini_with_model(prompt, api_key, &self.gemini_model).await
    }

    async fn call_gemini_with_model(&self, prompt: &str, api_key: &str, model: &str) -> Result<String> {
        let endpoint = format!(
            "https://generativelanguage.googleapis.com/v1beta/models/{}:generateContent?key={}",
            model, api_key
        );

        let payload = GeminiPayload {
            contents: vec![GeminiContent {
                parts: vec![GeminiPart {
                    text: prompt.to_string(),
                }],
            }],
        };

        let res = self
            .client
            .post(&endpoint)
            .json(&payload)
            .send()
            .await
            .context("Fallo en solicitud HTTP a Gemini API")?;

        if !res.status().is_success() {
            let status = res.status();
            let text = res.text().await.unwrap_or_default();
            return Err(anyhow::anyhow!("Gemini API HTTP {}: {}", status, text));
        }

        let body: GeminiResponse = res.json().await.context("Error decodificando respuesta de Gemini")?;
        
        let text = body
            .candidates
            .and_then(|c| c.into_iter().next())
            .and_then(|c| c.content)
            .and_then(|c| c.parts)
            .and_then(|p| p.into_iter().next())
            .and_then(|p| p.text)
            .unwrap_or_default();

        Ok(text)
    }

    async fn call_wasp(&self, prompt: &str) -> Result<String> {
        let endpoint = format!("{}/api/prompt", self.wasp_url);
        let payload = WaspPromptPayload {
            prompt: prompt.to_string(),
        };

        let res = self
            .client
            .post(&endpoint)
            .json(&payload)
            .send()
            .await
            .context("Error conectando con Steel Wasp")?;

        if res.status().is_success() {
            let body: WaspPromptResponse = res.json().await?;
            Ok(body.response)
        } else {
            Err(anyhow::anyhow!("Steel Wasp HTTP error status: {}", res.status()))
        }
    }

    /// Answers a whole form step at once, mirroring JobAnalyzer.answer_form /
    /// AiPromptBuilder.get_form_prompt. Returns a flat label -> answer map.
    pub async fn answer_form(
        &self,
        schema: &[crate::services::apply::dom::FormField],
        profile_yaml: &str,
        resolved_salary: Option<&str>,
        resolved_currency: Option<&str>,
        job_location: Option<&str>,
    ) -> Result<std::collections::HashMap<String, String>> {
        let form_payload: Vec<Value> = schema
            .iter()
            .map(|f| {
                json!({
                    "label": f.label,
                    "type": f.field_type,
                    "options": f.options,
                    "error": f.error,
                })
            })
            .collect();

        let salary_instruction = resolved_salary
            .map(|s| {
                let mut instr = format!(
                    "\n5. MANDATORY SALARY: For any question about salary expectations, use EXACTLY '{}'. Do not use currency symbols or text if the field seems numeric.",
                    s
                );
                if let Some(c) = resolved_currency {
                    instr.push_str(&format!(" The currency for this value is {}.", c));
                }
                instr
            })
            .unwrap_or_default();
        let location_context = job_location.map(|l| format!("\nCURRENT JOB LOCATION: {}", l)).unwrap_or_default();

        let prompt = format!(
            "ROLE: Technical Recruiter / IT Talent Acquisition\n\
             OBJECTIVE: Completar un formulario de aplicación de empleo actuando como el candidato.\n\n\
             CANDIDATE PROFILE (YAML):\n{profile}\n{location}\n\
             CANDIDATE SUGGESTED SALARY: {salary} {currency}\n\n\
             FORM SCHEMA (JSON to fill):\n{schema}\n\n\
             TASKS & INSTRUCTIONS:\n\
             1. Responde cada pregunta del FORM SCHEMA usando estrictamente el PROFILE.\n\
             2. Si el input es numérico, responde solo con dígitos, sin texto adicional.\n\
             3. DATOS DE CONTACTO E IDENTIDAD (teléfono, email, nombre, documento/DNI, LinkedIn, GitHub, portafolio): copia el valor EXACTO del PROFILE. Está prohibido inventarlos, abreviarlos o poner un número de relleno. Si el PROFILE no trae ese dato, responde cadena vacía \"\" en vez de inventar.\n\
             4. JUICIO PROFESIONAL: SOLO para preguntas de años de experiencia en una tecnología ausente del PROFILE responde \"0\". Nunca uses \"0\" ni un número arbitrario para datos de contacto, ubicación, fechas o preferencias.\n\
             5. UBICACIÓN/CIUDAD: cualquier campo de location/city debe responderse con la location del perfil, escrita como texto (ej. \"Medellín, Colombia\"). Nunca \"N/A\" ni un número.\n\
             6. OBJETIVO PRINCIPAL: que la aplicación se pueda enviar; no dejes campos obligatorios sin responder.{salary_instruction}\n\
             7. Para \"select\", \"radio\" o \"checkbox\", usa EXACTAMENTE una de las \"options\" dadas.\n\n\
             FORMAT: Responde ÚNICAMENTE un objeto JSON plano {{\"<label exacto>\": \"<respuesta>\", ...}}. Nada de texto fuera del JSON.",
            profile = profile_yaml,
            location = location_context,
            salary = resolved_salary.unwrap_or("Check profile"),
            currency = resolved_currency.unwrap_or(""),
            schema = serde_json::to_string_pretty(&form_payload).unwrap_or_default(),
            salary_instruction = salary_instruction,
        );

        let raw_text = if let Some(ref api_key) = self.gemini_api_key {
            self.call_gemini(&prompt, api_key).await
        } else {
            Err(anyhow::anyhow!("Gemini not configured"))
        };

        let raw_text = match raw_text {
            Ok(t) => t,
            Err(_) => match self.call_wasp(&prompt).await {
                Ok(t) => t,
                Err(_) => self.call_local(&prompt).await?,
            },
        };

        let clean_json = raw_text
            .trim()
            .trim_start_matches("```json")
            .trim_start_matches("```")
            .trim_end_matches("```")
            .trim();

        let parsed: Value = serde_json::from_str(clean_json).ok().or_else(|| {
            // Some models wrap the object in prose; extract the outermost {...}.
            let start = clean_json.find('{');
            let end = clean_json.rfind('}');
            match (start, end) {
                (Some(s), Some(e)) if e > s => serde_json::from_str(&clean_json[s..=e]).ok(),
                _ => None,
            }
        }).unwrap_or(Value::Null);

        let mut answers = std::collections::HashMap::new();
        if let Value::Object(map) = parsed {
            for (k, v) in map {
                let answer = match v {
                    Value::String(s) => s,
                    Value::Number(n) => n.to_string(),
                    Value::Bool(b) => b.to_string(),
                    _ => continue,
                };
                answers.insert(k, answer);
            }
        }
        Ok(answers)
    }

    /// Picks the best resume for a job from the files that ACTUALLY exist on disk.
    ///
    /// The deterministic rules in cv_profile.json build a filename from fixed components
    /// and then hope it exists — which broke in practice: `experience` is pinned to "20"
    /// but no CV_20_* file exists for Leader roles, so every architect/lead role built a
    /// name with no file behind it. Handing the model the real inventory sidesteps that
    /// whole class of failure: it can only choose something that exists.
    ///
    /// The answer is validated against `candidates`; anything else is rejected so a
    /// hallucinated filename can never reach the uploader.
    pub async fn choose_resume(
        &self,
        role: &str,
        company: &str,
        description: &str,
        lang: &str,
        candidates: &[String],
    ) -> Option<String> {
        if candidates.is_empty() {
            return None;
        }

        let prompt = format!(
            "ROLE: Career coach seleccionando la hoja de vida correcta para una vacante.\n\n\
             VACANTE:\n\
             - Cargo: {role}\n\
             - Empresa: {company}\n\
             - Idioma detectado de la oferta: {lang}\n\
             - Descripción/requisitos:\n{description}\n\n\
             ARCHIVOS DE CV DISPONIBLES EN DISCO (elige EXACTAMENTE uno de esta lista):\n{list}\n\n\
             CONVENCIÓN DE NOMBRES: CV_{{experiencia}}_{{ciudad}}_{{rol}}_{{tecnología}}_{{idioma}}_{{dueño}}.pdf\n\
             - ciudad: B=Bogotá, M=Medellín\n\
             - rol: L=Líder/Arquitecto/Manager/Principal, D=Desarrollador\n\
             - tecnología: J=Java/Spring, C=C#/.NET/Azure/Angular, P=Python/Django/IA/ML\n\
             - idioma: EN=inglés, ES=español\n\n\
             PRIORIDAD AL ELEGIR (de más a menos importante):\n\
             1. ROL: si la vacante es de arquitecto/líder/manager/principal usa L; si es de desarrollador usa D.\n\
             2. TECNOLOGÍA: la tecnología dominante que pide la vacante.\n\
             3. IDIOMA: EN si la oferta está en inglés, ES si está en español.\n\
             4. CIUDAD: la de la vacante; si es remota o no se menciona, prefiere M.\n\
             5. EXPERIENCIA: si hay varias variantes válidas, prefiere el número más alto.\n\n\
             FORMAT: responde ÚNICAMENTE un JSON {{\"file\": \"<nombre exacto de la lista>\", \"reason\": \"<10 palabras máx>\"}}.",
            role = role,
            company = company,
            lang = lang,
            description = description.chars().take(1500).collect::<String>(),
            list = candidates.iter().map(|c| format!("- {}", c)).collect::<Vec<_>>().join("\n"),
        );

        let raw_text = if let Some(ref api_key) = self.gemini_api_key {
            self.call_gemini(&prompt, api_key).await
        } else {
            Err(anyhow::anyhow!("Gemini not configured"))
        };
        let raw_text = match raw_text {
            Ok(t) => t,
            Err(_) => match self.call_wasp(&prompt).await {
                Ok(t) => t,
                Err(_) => self.call_local(&prompt).await.ok()?,
            },
        };

        let cleaned = raw_text
            .trim()
            .trim_start_matches("```json")
            .trim_start_matches("```")
            .trim_end_matches("```")
            .trim()
            .to_string();
        let parsed: Value = serde_json::from_str(&cleaned).ok().or_else(|| {
            let start = cleaned.find('{');
            let end = cleaned.rfind('}');
            match (start, end) {
                (Some(s), Some(e)) if e > s => serde_json::from_str(&cleaned[s..=e]).ok(),
                _ => None,
            }
        })?;

        let picked = parsed.get("file")?.as_str()?.trim().to_string();
        // Only a filename the caller actually offered is acceptable.
        let valid = candidates.iter().find(|c| c.eq_ignore_ascii_case(&picked))?;
        let reason = parsed.get("reason").and_then(|r| r.as_str()).unwrap_or("");
        println!("      🧠 CV elegido por IA: {} ({})", valid, reason);
        Some(valid.clone())
    }

    /// Chooses the next single action for the application agent.
    ///
    /// Given a semantic snapshot of whatever page is on screen, the model returns ONE verb
    /// from a closed vocabulary. Nothing site-specific is encoded here — that is the whole
    /// point: hardcoded label lists could never cover the number of ATS products in the
    /// wild, and each gap showed up as a silent "button not found".
    pub async fn decide_next_action(
        &self,
        goal: &str,
        profile_yaml: &str,
        snapshot: &crate::services::apply::agent::PageSnapshot,
        history: &[String],
        dry_run: bool,
    ) -> Option<Value> {
        let snapshot_json = serde_json::to_string_pretty(&serde_json::json!({
            "url": snapshot.url,
            "title": snapshot.title,
            "fields": snapshot.fields,
            "actions": snapshot.actions,
            "page_text": snapshot.text,
        }))
        .ok()?;

        let history_block = if history.is_empty() {
            "(ninguna todavía)".to_string()
        } else {
            history.iter().rev().take(12).rev().cloned().collect::<Vec<_>>().join("\n")
        };

        let dry_run_rule = if dry_run {
            "\nMODO AUDITORÍA: está PROHIBIDO enviar. No elijas 'click' sobre botones de envío final \
             (Submit/Enviar/Finalizar). Llena los campos y cuando el paso esté completo responde 'needs_human' \
             con motivo 'auditoría completada'."
        } else {
            ""
        };

        let prompt = format!(
            "ROLE: Agente autónomo cuyo ÚNICO objetivo es completar y enviar una postulación de empleo.\n\n\
             OBJETIVO: {goal}\n\n\
             PERFIL DEL CANDIDATO (YAML) — única fuente de datos personales:\n{profile}\n\n\
             ESTADO ACTUAL DE LA PÁGINA (JSON):\n{snapshot}\n\n\
             ACCIONES YA EJECUTADAS (más reciente al final):\n{history}\n\n\
             VOCABULARIO DE ACCIONES (elige EXACTAMENTE una):\n\
             - {{\"action\":\"type\",\"id\":\"tf_N\",\"text\":\"...\"}}      escribir en un campo\n\
             - {{\"action\":\"select\",\"id\":\"tf_N\",\"text\":\"opción\"}}  elegir en un desplegable\n\
             - {{\"action\":\"check\",\"id\":\"tf_N\",\"checked\":true}}      marcar casilla/radio\n\
             - {{\"action\":\"click\",\"id\":\"tf_N\"}}                       pulsar botón o enlace\n\
             - {{\"action\":\"upload_resume\"}}                              adjuntar el CV del candidato\n\
             - {{\"action\":\"press_key\",\"id\":\"tf_N\",\"text\":\"Enter\"}} tecla sobre un campo\n\
             - {{\"action\":\"scroll\",\"y\":600}}                           desplazar la página\n\
             - {{\"action\":\"wait\",\"ms\":2000}}                           esperar a que cargue\n\
             - {{\"action\":\"navigate\",\"url\":\"https://...\"}}            ir a otra página\n\
             - {{\"action\":\"eval_js\",\"code\":\"return ...\"}}             ejecutar JavaScript propio en la página\n\
             - {{\"action\":\"done\",\"reason\":\"...\"}}                     la postulación YA fue enviada y confirmada\n\
             - {{\"action\":\"needs_human\",\"reason\":\"...\"}}              no puedes continuar de forma segura\n\n\
             REGLAS CRÍTICAS (lee PRIMERO):\n\
             1. Usa SOLO ids 'tf_N' que aparezcan en el JSON de arriba. Nunca inventes un id.\n\
             2. TELÉFONO Y NOMBRES: El candidato es de Colombia (código +57). \
             Si el formulario muestra una bandera o prefijo internacional (ej. +1 🇺🇸), PRIMERO cámbialo a Colombia (+57) antes de escribir el número. \
             Si pide 'First Name' escribe 'Jesus'. Si pide 'Last Name' escribe solo 'Coronado'. \
             Nunca pongas el nombre completo en el campo de apellido.\n\
             3. DATOS RESOLUBLES DEL PERFIL: Salario esperado, años de experiencia, disponibilidad, nivel de inglés \
             y nivel de español ESTÁN en el perfil YAML. Búscalos ahí y úsalos. \
             Ejemplo: si preguntan 'expected hourly rate' y el perfil dice salary_expectation, usa ese valor. \
             Si preguntan 'years of experience', usa years_of_experience del perfil. \
             NO respondas 'needs_human' por estas preguntas.\n\
             4. ABORTO TEMPRANO: Si tras analizar la página detectas alguno de estos bloqueantes, \
             responde 'needs_human' INMEDIATAMENTE sin intentar más acciones: \
             (a) muro de login sin ruta de invitado, \
             (b) captcha visual o reCAPTCHA, \
             (c) grabadora de audio/voz/video (micrófono, 'Click to record', elementos <audio>/<video> para subir), \
             (d) verificación por SMS/OTP. \
             No desperdicies pasos intentando interactuar con estos elementos.\n\n\
             REGLAS GENERALES:\n\
             5. Datos personales (nombre, email, teléfono, documento, enlaces): copia EXACTO del PERFIL. Prohibido inventar.\n\
             6. Una acción por respuesta. Prioriza: campos obligatorios vacíos > adjuntar CV > avanzar de paso (Next/Continue/Submit).\n\
             7. No repitas una acción que ya está en el historial si la página no cambió; prueba otra cosa.\n\
             8. NUNCA uses 'type' en un campo que ya tiene su valor puesto (mira 'value' en el JSON). \
             Si todos los campos requeridos tienen valor, pulsa el botón 'Next', 'Continue', 'Submit' o 'Apply' para avanzar.\n\
             9. 'done' SOLO si el texto de la página confirma explícitamente el envío exitoso.\n\
             10. 'eval_js' es tu recurso libre cuando los verbos no bastan: widgets a medida, shadow DOM, \
             selectores de fecha, subidas por arrastrar-soltar, o simplemente inspeccionar la página. \
             Escribe el cuerpo de una función JavaScript y usa 'return' para devolver lo que observes; \
             ese valor te llegará como observación en el siguiente turno.\n\n\
             REGLAS PARA COMPONENTES DIFÍCILES:\n\
             11. MENÚS DESPLEGABLES PERSONALIZADOS (react-select, combobox, listbox): \
             Paso A: usa 'type' para escribir el texto exacto (ej. 'Medellín'). \
             Paso B: en tu SIGUIENTE respuesta (otro turno), usa 'press_key' con 'Enter' sobre el MISMO campo para confirmar la opción. \
             Estos son DOS turnos separados. Nunca saltes el paso B.\n\
             12. RADIO/CHECKBOX ESCONDIDOS: Algunos portales usan 'div' o 'span' en lugar de <input type='radio'>. \
             Si ves preguntas de 'Yes' / 'No' que no reaccionan al verbo 'check', usa 'click' sobre el \
             id que corresponde exactamente al texto 'Yes' o 'No'.\n\
             13. Ante un muro de login, primero explora de verdad (eval_js, scroll, navigate) buscando una \
             ruta de invitado o un enlace de aplicación directa; solo responde 'needs_human' si realmente \
             no hay camino sin credenciales.{dry_run_rule}\n\n\
             FORMAT: responde ÚNICAMENTE el objeto JSON de la acción. Nada de texto fuera del JSON.",
            goal = goal,
            profile = profile_yaml,
            snapshot = snapshot_json,
            history = history_block,
            dry_run_rule = dry_run_rule,
        );

        let raw = if let Some(ref api_key) = self.gemini_api_key {
            // Intentar primero con gemini-3.7-flash para formularios externos
            match self.call_gemini_with_model(&prompt, api_key, "gemini-3.7-flash").await {
                Ok(t) => Ok(t),
                Err(e) => {
                    eprintln!("⚠️ [AI Client] gemini-3.7-flash no disponible ({}), usando fallback...", e);
                    self.call_gemini(&prompt, api_key).await
                }
            }
        } else {
            Err(anyhow::anyhow!("Gemini not configured"))
        };
        let raw = match raw {
            Ok(t) => t,
            Err(_) => match self.call_wasp(&prompt).await {
                Ok(t) => t,
                Err(_) => self.call_local(&prompt).await.ok()?,
            },
        };

        let cleaned = raw
            .trim()
            .trim_start_matches("```json")
            .trim_start_matches("```")
            .trim_end_matches("```")
            .trim()
            .to_string();
        serde_json::from_str::<Value>(&cleaned).ok().or_else(|| {
            let s = cleaned.find('{');
            let e = cleaned.rfind('}');
            match (s, e) {
                (Some(s), Some(e)) if e > s => serde_json::from_str(&cleaned[s..=e]).ok(),
                _ => None,
            }
        })
    }

    async fn call_local(&self, prompt: &str) -> Result<String> {
        let endpoint = format!("{}/api/chat", self.local_ai_url.trim_end_matches('/').replace("/v1", ""));
        let payload = OllamaChatPayload {
            model: self.local_ai_model.clone(),
            messages: vec![OllamaChatMessage {
                role: "user".to_string(),
                content: prompt.to_string(),
            }],
            stream: false,
            format: "json".to_string(),
        };

        let res = self
            .client
            .post(&endpoint)
            .json(&payload)
            .send()
            .await
            .context("Error conectando con modelo local (Ollama)")?;

        if !res.status().is_success() {
            return Err(anyhow::anyhow!("Ollama HTTP error status: {}", res.status()));
        }

        let body: OllamaChatResponse = res.json().await.context("Error decodificando respuesta de Ollama")?;
        Ok(body.message.content)
    }

    fn parse_json_response(&self, raw_text: &str, role: &str, company: &str) -> Result<AnalysisResult> {
        // Limpiar bloques markdown ```json ... ```
        let clean_json = raw_text
            .trim()
            .trim_start_matches("```json")
            .trim_start_matches("```")
            .trim_end_matches("```")
            .trim();

        if let Ok(parsed) = serde_json::from_str::<Value>(clean_json) {
            let score = Self::rescue_score(&parsed);
            let skills = Self::rescue_skills(&parsed, raw_text);
            let status = Self::rescue_status(&parsed, score);

            let summary = parsed
                .get("reasoning")
                .or_else(|| parsed.get("summary"))
                .or_else(|| parsed.get("justification"))
                .and_then(|v| v.as_str())
                .unwrap_or("Evaluado con IA")
                .to_string();

            return Ok(AnalysisResult {
                match_score: score,
                status,
                skills,
                summary,
            });
        }

        // Fallback si no es JSON puro
        let skills = crate::services::Normalizer::extract_skills_heuristic(raw_text);
        Ok(AnalysisResult {
            match_score: 75.0,
            status: "Matched".to_string(),
            skills,
            summary: format!("Análisis para {} en {}", role, company),
        })
    }

    /// SCHEMA RESCUE LAYER — mirrors src/app/bots/search/processor.py::normalize_analysis.
    /// When the LLM ignores the requested schema, probe alternate key names commonly
    /// used by different models so a job is never wrongly scored 0.
    fn rescue_score(parsed: &Value) -> f64 {
        if let Some(direct) = parsed.get("match_percentage").or_else(|| parsed.get("match_score")).and_then(|v| v.as_f64()) {
            return direct;
        }

        let mut candidates: Vec<&Value> = vec![
            parsed.get("match_percentage"),
            parsed.get("match_score"),
            parsed.get("score"),
            parsed.get("similarity_score"),
            parsed.get("fit_score"),
            parsed.get("overall_score"),
            parsed.get("compatibility_score"),
            parsed.get("match"),
        ]
        .into_iter()
        .flatten()
        .collect();

        for nested_key in ["analysis", "assessment", "evaluation", "result"] {
            if let Some(nested) = parsed.get(nested_key).filter(|v| v.is_object()) {
                for k in ["match_percentage", "match_score", "score", "fit_score"] {
                    if let Some(v) = nested.get(k) {
                        candidates.push(v);
                    }
                }
            }
        }

        for candidate in candidates {
            let raw = match candidate {
                Value::Number(n) => n.as_f64(),
                Value::String(s) => s.trim().trim_end_matches('%').parse::<f64>().ok(),
                _ => None,
            };
            if let Some(mut val) = raw {
                if val > 0.0 && val <= 1.0 {
                    val *= 100.0;
                }
                if val > 0.0 {
                    return val;
                }
            }
        }

        70.0
    }

    fn rescue_status(parsed: &Value, score: f64) -> String {
        if let Some(s) = parsed.get("status").and_then(|v| v.as_str()) {
            if !s.trim().is_empty() {
                return s.to_string();
            }
        }

        let mut rec = String::new();
        for key in ["recommendation", "suggested_action", "final_assessment", "overall_recommendation", "verdict"] {
            if let Some(v) = parsed.get(key).and_then(|v| v.as_str()) {
                rec.push_str(&v.to_lowercase());
            }
        }
        for nested_key in ["analysis", "assessment", "evaluation", "result", "recommendation"] {
            if let Some(nested) = parsed.get(nested_key).filter(|v| v.is_object()) {
                for k in ["recommendation", "suggested_action"] {
                    if let Some(v) = nested.get(k).and_then(|v| v.as_str()) {
                        rec.push_str(&v.to_lowercase());
                    }
                }
            }
        }

        if ["strong hire", "hire", "apply", "yes", "proceed", "good fit", "excellent", "recommend"]
            .iter()
            .any(|k| rec.contains(k))
        {
            "Matched".to_string()
        } else if ["defer", "consider", "maybe", "partial"].iter().any(|k| rec.contains(k)) {
            "Manual".to_string()
        } else if !rec.is_empty() {
            "Discarded".to_string()
        } else {
            // No verdict text anywhere: fall back to the numeric score.
            if score >= 60.0 { "Matched".to_string() } else { "Discarded".to_string() }
        }
    }

    fn rescue_skills(parsed: &Value, raw_text: &str) -> Vec<String> {
        if let Some(arr) = parsed.get("skills").and_then(|v| v.as_array()) {
            let skills: Vec<String> = arr.iter().filter_map(|s| s.as_str().map(str::to_string)).collect();
            if !skills.is_empty() {
                return skills;
            }
        }

        for skill_gap_key in ["skill_gap_analysis", "skill_gap"] {
            if let Some(gap) = parsed.get(skill_gap_key).filter(|v| v.is_object()) {
                for k in ["required_skills", "missing_skills"] {
                    if let Some(arr) = gap.get(k).and_then(|v| v.as_array()) {
                        let skills: Vec<String> = arr.iter().filter_map(|s| s.as_str().map(str::to_string)).collect();
                        if !skills.is_empty() {
                            return skills;
                        }
                    }
                }
            }
        }

        if let Some(arr) = parsed.get("required_skills").and_then(|v| v.as_array()) {
            let skills: Vec<String> = arr.iter().filter_map(|s| s.as_str().map(str::to_string)).collect();
            if !skills.is_empty() {
                return skills;
            }
        }

        crate::services::Normalizer::extract_skills_heuristic(raw_text)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn client() -> AiClient {
        AiClient {
            client: reqwest::Client::new(),
            gemini_api_key: None,
            gemini_model: "test".to_string(),
            wasp_url: "http://localhost:3000".to_string(),
            local_ai_url: "http://localhost:11434".to_string(),
            local_ai_model: "llama3".to_string(),
        }
    }

    #[test]
    fn parses_well_formed_schema_directly() {
        let raw = r#"{"match_score": 88.0, "status": "Matched", "skills": ["C#", "React"], "summary": "Great fit"}"#;
        let result = client().parse_json_response(raw, "Backend Dev", "Acme").unwrap();
        assert_eq!(result.match_score, 88.0);
        assert_eq!(result.status, "Matched");
        assert_eq!(result.skills, vec!["C#", "React"]);
    }

    #[test]
    fn rescues_score_from_alternate_key_and_normalizes_0_to_1_range() {
        let raw = r#"{"fit_score": 0.82, "recommendation": "Strong hire, apply now"}"#;
        let result = client().parse_json_response(raw, "Backend Dev", "Acme").unwrap();
        assert_eq!(result.match_score, 82.0);
        assert_eq!(result.status, "Matched");
    }

    #[test]
    fn rescues_skills_from_nested_skill_gap_analysis() {
        let raw = r#"{"score": 55, "skill_gap_analysis": {"required_skills": ["Kubernetes", "Terraform"]}}"#;
        let result = client().parse_json_response(raw, "DevOps", "Acme").unwrap();
        assert_eq!(result.skills, vec!["Kubernetes", "Terraform"]);
    }

    #[test]
    fn falls_back_to_score_derived_status_when_no_verdict_text() {
        let raw = r#"{"overall_score": 20}"#;
        let result = client().parse_json_response(raw, "Backend Dev", "Acme").unwrap();
        assert_eq!(result.status, "Discarded");
    }

    #[test]
    fn non_json_response_falls_back_to_heuristic_skills() {
        let raw = "Not JSON at all, just prose about Python and Docker.";
        let result = client().parse_json_response(raw, "Backend Dev", "Acme").unwrap();
        assert!(result.skills.contains(&"Python".to_string()));
        assert!(result.skills.contains(&"Docker".to_string()));
    }
}
