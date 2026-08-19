use crate::domain::models::{ProfileConfig, ResumeRules};
use anyhow::Result;
use chromiumoxide::cdp::browser_protocol::dom::SetFileInputFilesParams;
use chromiumoxide::Page;
use regex::Regex;
use std::path::{Path, PathBuf};

/// Mirrors src/app/bots/apply/resume_manager.py::ResumeManager.
pub struct ResumeManager {
    pub base_dir: PathBuf,
    pub profile: ProfileConfig,
}

impl ResumeManager {
    pub fn new(base_dir: PathBuf, profile: ProfileConfig) -> Self {
        Self { base_dir, profile }
    }

    fn word_in_text(word: &str, target_text: &str) -> bool {
        let word_lower = word.to_lowercase();
        let pattern = if word_lower.contains(['#', '+', '.']) {
            format!(r"(?i)(?:^|[^\w]){}(?:[^\w]|$)", regex::escape(&word_lower))
        } else {
            format!(r"\b{}\b", regex::escape(&word_lower))
        };
        Regex::new(&pattern).map(|re| re.is_match(target_text)).unwrap_or(false)
    }

    /// Simple two-keyword language guess, distinct from Normalizer::detect_language —
    /// mirrors ResumeManager.detect_language in Python exactly (it's intentionally
    /// cruder than the job-language heuristic used elsewhere).
    pub fn detect_language(text: &str) -> String {
        let text_lower = text.to_lowercase();
        let mut score_en = 0;
        let mut score_es = 0;
        if text_lower.contains("software") { score_en += 1; }
        if text_lower.contains("ingeniero") { score_es += 1; }
        if score_es > score_en { "es".to_string() } else { "en".to_string() }
    }

    fn resolve_resume_path(&self, filename: &str) -> PathBuf {
        let base = self.base_dir.join("cv");
        if let Ok(walker) = walk_dir(&base) {
            for entry in walker {
                if entry.file_name().map(|f| f == filename).unwrap_or(false) {
                    return entry;
                }
            }
        }
        base.join(filename)
    }

    /// Selects the best resume using deterministic mapping from cv_profile.json.
    /// Naming Convention: CV_{prefix}_{exp}_{city}_{role}_{tech}_{lang}_{owner}.pdf
    pub fn get_resume_filename(&self, role: &str, desc: &str, lang: &str, stored_filename: Option<&str>) -> PathBuf {
        // 1. Pre-selected filename (manual bypass from DB)
        if let Some(stored) = stored_filename {
            let role_folder = if stored.contains("_L_") { "Leader" } else { "Developer" };
            let city_folder = if stored.contains("_B_") { "bogota" } else { "medellin" };
            let full_path = self.base_dir.join("cv").join(role_folder).join(city_folder).join(stored);
            if full_path.exists() {
                return full_path;
            }
            let resolved = self.resolve_resume_path(stored);
            if resolved.exists() {
                return resolved;
            }
        }

        let Some(ResumeRules { agent_config, rules }) = self.profile.resume_rules.as_ref() else {
            println!("   ⚠️  Warning: cv_profile.json ausente o inválido. Usando CV por defecto.");
            return self.resolve_resume_path("CV_15_M_D_P_ES_Jesus_Coronado.pdf");
        };

        let role_lower = role.to_lowercase();
        let desc_lower = desc.to_lowercase();
        let content_lower = format!("{} {}", role_lower, desc_lower);

        // A. Role (Leader vs Developer)
        let is_leader = rules.role_mapping.leader_keywords.iter().any(|kw| Self::word_in_text(kw, &role_lower));
        let role_code = rules.role_mapping.codes.get(if is_leader { "leader" } else { "developer" }).cloned().unwrap_or_else(|| "D".to_string());
        let role_folder = if is_leader { "Leader" } else { "Developer" };

        // B. Tech (J, C, P) — first match wins, same order as the JSON map's insertion in Python (dict order).
        let mut tech_code = "P".to_string();
        for (code, keywords) in rules.tech_mapping.iter() {
            if keywords.iter().any(|kw| Self::word_in_text(kw, &content_lower)) {
                tech_code = code.clone();
                break;
            }
        }

        // C. City (B, M)
        let mut city_code = rules.city_mapping.get("__default__").cloned().unwrap_or_else(|| "M".to_string());
        for (city, code) in rules.city_mapping.iter() {
            if city != "__default__" && content_lower.contains(city.as_str()) {
                city_code = code.clone();
                break;
            }
        }
        let city_folder = if city_code == "B" { "bogota" } else { "medellin" };

        // D. Language
        let lang_key = if lang == "es" { "spanish" } else { "english" };
        let lang_code = rules.language_mapping.get(lang_key).cloned().unwrap_or_else(|| "EN".to_string());

        // E. Build filename
        let fmt = agent_config.naming_format.clone().unwrap_or_else(|| "CV_{prefix}_{exp}_{city}_{role}_{tech}_{lang}_{owner}{ext}".to_string());
        let filename = fmt
            .replace("{prefix}", agent_config.prefix.as_deref().unwrap_or("CV"))
            .replace("{exp}", agent_config.experience.as_deref().unwrap_or("20"))
            .replace("{city}", &city_code)
            .replace("{role}", &role_code)
            .replace("{tech}", &tech_code)
            .replace("{lang}", &lang_code)
            .replace("{owner}", agent_config.owner.as_deref().unwrap_or("Jesus_Coronado"))
            .replace("{ext}", agent_config.file_extension.as_deref().unwrap_or(".pdf"));

        println!("   🔍 Choosing Resume for: {}...", role.chars().take(40).collect::<String>());
        println!("      📍 Components: Role={}, Tech={}, City={}, Lang={}", role_code, tech_code, city_code, lang_code);

        let final_path = self.base_dir.join("cv").join(role_folder).join(city_folder).join(&filename);
        if final_path.exists() {
            println!("      🎯 Deterministic Match: {}/{}/{}", role_folder, city_folder, filename);
            return final_path;
        }

        println!("      ⚠️  Built path not found, falling back to global search: {}", filename);
        let resolved = self.resolve_resume_path(&filename);
        if resolved.exists() {
            return resolved;
        }

        // NOTE (incident 2026-08-18): resolve_resume_path returns `cv/<filename>` when the
        // exact name matches nothing on disk — a path that does not exist. smart_upload_resume
        // then had nothing to upload, silently did nothing, and LinkedIn kept whatever resume
        // was already attached from a previous session. That is exactly how the Crossing
        // Hurdles application went out with the wrong CV.
        //
        // This is not a rare edge case: cv_profile.json pins experience=20, but the only
        // CV_20_* files on disk are under Developer/. EVERY Leader role therefore builds a
        // filename that cannot exist. Rather than hand back a phantom path, degrade to the
        // closest resume that actually exists, relaxing the least meaningful component first.
        if let Some((best, name)) = self.best_available_resume(&role_code, &tech_code, &city_code, &lang_code) {
            println!("      🔁 Degradado al CV real más cercano: {}", name);
            return best;
        }

        println!("      ❌ No hay ningún CV disponible en {:?}", self.base_dir.join("cv"));
        resolved
    }

    /// Every resume PDF that actually exists under `cv/`, as (filename, full path).
    pub fn available_resumes(&self) -> Vec<(String, PathBuf)> {
        let base = self.base_dir.join("cv");
        let mut out = Vec::new();
        if let Ok(files) = walk_dir(&base) {
            for path in files {
                if path.extension().map(|e| e == "pdf").unwrap_or(false) {
                    if let Some(name) = path.file_name().map(|f| f.to_string_lossy().to_string()) {
                        out.push((name, path));
                    }
                }
            }
        }
        out.sort_by(|a, b| a.0.cmp(&b.0));
        out
    }

    /// Selects the resume for a job by asking the AI to choose among the files that really
    /// exist on disk, falling back to the deterministic cv_profile.json rules if the model
    /// is unavailable or returns something not in the inventory.
    ///
    /// A manually pre-selected resume stored on the job row always wins — an explicit human
    /// choice must not be second-guessed by the model.
    pub async fn choose_resume_smart(
        &self,
        ai: &crate::services::AiClient,
        role: &str,
        company: &str,
        desc: &str,
        lang: &str,
        stored_filename: Option<&str>,
    ) -> PathBuf {
        let deterministic = self.get_resume_filename(role, desc, lang, stored_filename);

        if let Some(stored) = stored_filename {
            if !stored.trim().is_empty() && deterministic.exists() {
                println!("      📌 CV preseleccionado manualmente en la oferta: {}", stored);
                return deterministic;
            }
        }

        let inventory = self.available_resumes();
        if inventory.is_empty() {
            return deterministic;
        }
        let names: Vec<String> = inventory.iter().map(|(n, _)| n.clone()).collect();

        match ai.choose_resume(role, company, desc, lang, &names).await {
            Some(chosen) => inventory
                .into_iter()
                .find(|(n, _)| *n == chosen)
                .map(|(_, p)| p)
                .unwrap_or(deterministic),
            None => {
                println!("      ⚠️  La IA no eligió un CV válido; usando la selección determinista.");
                deterministic
            }
        }
    }

    /// Picks the closest resume that actually exists on disk when the deterministic name
    /// has no file behind it. Components are weighted by how wrong it would be to get them
    /// wrong: sending a Developer CV for an Architect role is a real mistake, whereas the
    /// experience prefix is just a variant of the same document.
    fn best_available_resume(&self, role: &str, tech: &str, city: &str, lang: &str) -> Option<(PathBuf, String)> {
        let base = self.base_dir.join("cv");
        let files = walk_dir(&base).ok()?;

        let mut best: Option<(i32, PathBuf, String)> = None;
        for path in files {
            if path.extension().map(|e| e != "pdf").unwrap_or(true) {
                continue;
            }
            let name = path.file_name()?.to_string_lossy().to_string();
            let parts: Vec<&str> = name.split('_').collect();
            // CV_{exp}_{city}_{role}_{tech}_{lang}_{owner}.pdf
            if parts.len() < 6 {
                continue;
            }
            let (f_exp, f_city, f_role, f_tech, f_lang) = (parts[1], parts[2], parts[3], parts[4], parts[5]);

            let mut score = 0;
            if f_role.eq_ignore_ascii_case(role) { score += 100; }
            if f_tech.eq_ignore_ascii_case(tech) { score += 50; }
            if f_lang.eq_ignore_ascii_case(lang) { score += 25; }
            if f_city.eq_ignore_ascii_case(city) { score += 10; }
            // Tie-breaker only: prefer the most senior variant available.
            score += f_exp.parse::<i32>().unwrap_or(0) / 5;

            if best.as_ref().map(|(b, _, _)| score > *b).unwrap_or(true) {
                best = Some((score, path, name));
            }
        }

        best.map(|(_, p, n)| (p, n))
    }

    /// Resolves the salary expectation based on role/language, mirroring
    /// ResumeManager.get_salary_expectation.
    pub fn get_salary_expectation(&self, role: &str, lang: &str) -> (String, String) {
        let default = ("Negotiable".to_string(), "COP".to_string());
        let Some(salary_cfg) = self.profile.salary_expectations.as_ref() else {
            return default;
        };

        let role_lower = role.to_lowercase();
        let lang_lower = lang.to_lowercase();
        let is_lead = ["lead", "staff", "principal", "architect", "arquitecto", "líder", "lider", "manager", "head"]
            .iter()
            .any(|x| role_lower.contains(x));

        // A rule's currency follows the language it is written for. profile_config.json
        // states monthly COP for the "es" rules (7.000.000 / 8.000.000) and monthly USD for
        // the "en" ones (2000 / 4000), but the "en" rules declare no `currency` field —
        // defaulting them to the global COP default made the bot tell employers it expected
        // "2000 COP" (about USD 0.50) for a senior role. Confirmed live on Miratech (4000)
        // and Grupo DEACERO (2000). An explicit per-rule currency still wins.
        let currency_for = |rule: &crate::domain::models::SalaryRule| -> String {
            if let Some(c) = rule.currency.clone().filter(|c| !c.trim().is_empty()) {
                return c;
            }
            if rule.language.to_lowercase().starts_with("en") {
                "USD".to_string()
            } else {
                salary_cfg.default.currency.clone()
            }
        };

        for rule in &salary_cfg.rules {
            let role_match = rule.role_match.to_lowercase();
            if rule.language.to_lowercase() != lang_lower {
                continue;
            }
            if role_match.contains("lead") && is_lead {
                return (rule.value.clone(), currency_for(rule));
            }
            if !is_lead && ["senior", "full stack", "developer"].iter().any(|x| role_match.contains(x)) {
                return (rule.value.clone(), currency_for(rule));
            }
        }

        for rule in &salary_cfg.rules {
            if rule.language.to_lowercase() == lang_lower {
                return (rule.value.clone(), currency_for(rule));
            }
        }

        (salary_cfg.default.value.clone(), salary_cfg.default.currency.clone())
    }

    /// Finds the most relevant file input on the page and uploads the resume via CDP
    /// (DOM.setFileInputFiles) — no JS hacks needed, chromiumoxide exposes this natively.
    pub async fn smart_upload_resume(&self, page: &Page, file_path: &Path) -> Result<Option<String>> {
        let abs_path = std::fs::canonicalize(file_path).unwrap_or_else(|_| {
            if file_path.is_absolute() {
                file_path.to_path_buf()
            } else {
                std::env::current_dir().unwrap_or_default().join(file_path)
            }
        });
        let basename = abs_path.file_name().and_then(|f| f.to_str()).unwrap_or("resume.pdf").to_string();

        println!("   📂 [CV Manager] Preparando subida con ruta absoluta: {:?}", abs_path);

        // Is the right resume already attached? Read the filename LinkedIn actually shows
        // rather than matching `.jobs-document-card__title` — that class is hashed now and
        // the stale selector is precisely what let a wrong CV through (incident 2026-08-18).
        let attached_before = crate::services::apply::dom::read_attached_resume_filename(page).await;
        if let Some(ref attached) = attached_before {
            if attached.trim().eq_ignore_ascii_case(&basename) {
                println!("      ✅ Resume '{}' ya está adjunto y es el correcto.", basename);
                return Ok(Some(basename));
            }
            println!("      ⚠️  Ya hay otro CV adjunto ('{}'); hay que reemplazarlo por '{}'.", attached.trim(), basename);
        }

        // Revelar cualquier input type file que esté oculto en el DOM sin abrir el selector del SO
        let unhide_script = r#"(() => {
            const inputs = Array.from(document.querySelectorAll("input[type='file']"));
            inputs.forEach(inp => {
                inp.style.display = 'block';
                inp.style.visibility = 'visible';
                inp.style.opacity = '1';
                inp.removeAttribute('hidden');
            });
            return inputs.length;
        })()"#;
        let _ = page.evaluate(unhide_script).await;

        let mut file_inputs = page.find_elements("input[type='file']").await.unwrap_or_default();

        // A different resume is attached and LinkedIn is showing the document card instead
        // of an upload field — click its replace/remove control to bring the input back.
        if file_inputs.is_empty() && attached_before.is_some() {
            if crate::services::apply::dom::click_replace_resume_control(page).await {
                tokio::time::sleep(std::time::Duration::from_millis(1200)).await;
                let _ = page.evaluate(unhide_script).await;
                file_inputs = page.find_elements("input[type='file']").await.unwrap_or_default();
            }
        }

        if file_inputs.is_empty() {
            println!("   ⚠️ No se encontró elemento input[type='file'] en el DOM.");
            return Ok(None);
        }

        println!("   📂 Subiendo archivo directamente vía CDP: {}", basename);
        let mut target = &file_inputs[0];
        for inp in &file_inputs {
            let name = inp.attribute("name").await.ok().flatten().unwrap_or_default();
            let id = inp.attribute("id").await.ok().flatten().unwrap_or_default();
            let combined = format!("{}{}", name, id).to_lowercase();
            if ["resume", "cv", "curriculum"].iter().any(|x| combined.contains(x)) {
                target = inp;
                break;
            }
        }

        let params = SetFileInputFilesParams::builder()
            .file(abs_path.to_string_lossy().to_string())
            .object_id(target.remote_object_id.clone())
            .build()
            .map_err(|e| anyhow::anyhow!("Failed to build SetFileInputFilesParams: {}", e))?;

        match page.execute(params).await {
            Ok(_) => {
                println!("      ✅ File uploaded exitosamente: {}", basename);
                tokio::time::sleep(std::time::Duration::from_secs(2)).await;
                Ok(Some(basename))
            }
            Err(e) => {
                println!("      ❌ Smart Upload Error: {}", e);
                Ok(Some("Upload Failed".to_string()))
            }
        }
    }

    /// Compact YAML-ish candidate profile block for AI prompts, mirroring
    /// src/services/ai/prompts.py::_build_profile_yaml (simplified but same fields).
    pub fn build_profile_yaml(&self, job_location: Option<&str>) -> String {
        let mut out = String::new();

        let location = job_location.map(|loc| {
            let loc_lower = loc.to_lowercase();
            if loc_lower.contains("bogotá") || loc_lower.contains("bogota") {
                "Bogotá".to_string()
            } else {
                "Medellín".to_string()
            }
        });

        if let Some(info) = &self.profile.personal_info {
            // Emit EVERY identity field the profile holds. These used to be omitted, so a
            // form asking for a phone number reached the model with no phone anywhere in the
            // prompt — and the "never answer null" instruction then made it invent one
            // (confirmed live: a location question was answered "1"). Contact details must
            // come from config/profile_config.json, never from the model's imagination.
            out.push_str("personal_info:\n");
            if let Some(v) = &info.full_name { out.push_str(&format!("  full_name: {}\n", v)); }
            if let Some(v) = &info.email { out.push_str(&format!("  email: {}\n", v)); }
            if let Some(v) = &info.phone { out.push_str(&format!("  phone: {}\n", v)); }
            if let Some(v) = location.as_ref().or(info.location.as_ref()) { out.push_str(&format!("  location: {}\n", v)); }
            if let Some(v) = &info.dni { out.push_str(&format!("  dni: {}\n", v)); }
            if let Some(v) = &info.linkedin_url { out.push_str(&format!("  linkedin_url: {}\n", v)); }
            if let Some(v) = &info.github_url { out.push_str(&format!("  github_url: {}\n", v)); }
            if let Some(v) = &info.portfolio_url { out.push_str(&format!("  portfolio_url: {}\n", v)); }
            if let Some(v) = &info.availability { out.push_str(&format!("  availability: {}\n", v)); }
        }
        if let Some(v) = self.profile.years_of_experience { out.push_str(&format!("years_of_experience: {}\n", v)); }
        if let Some(v) = &self.profile.spanish_level { out.push_str(&format!("spanish_level: {}\n", v)); }
        if let Some(v) = &self.profile.english_level { out.push_str(&format!("english_level: {}\n", v)); }
        if !self.profile.skill_clarifications.is_empty() {
            out.push_str("skill_clarifications:\n");
            for c in &self.profile.skill_clarifications {
                out.push_str(&format!("  - \"{}\"\n", c.replace('"', "'")));
            }
        }
        if !self.profile.skills.is_empty() {
            out.push_str("skills:\n");
            for (category, skills) in &self.profile.skills {
                out.push_str(&format!("  {}:\n", category));
                for (name, info) in skills {
                    out.push_str(&format!("    {}: {{level: {}, years: {}}}\n", name, info.level, info.years));
                }
            }
        }

        if out.is_empty() { "{}".to_string() } else { out }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::domain::models::{RoleMapping, ResumeAgentConfig, ResumeRulesMap, SalaryDefault, SalaryExpectations, SalaryRule};
    use std::collections::HashMap as Map;

    fn empty_profile() -> ProfileConfig {
        ProfileConfig {
            personal_info: None,
            ai_config: None,
            years_of_experience: None,
            spanish_level: None,
            english_level: None,
            target_roles: None,
            location_preferences: None,
            skills: Default::default(),
            salary_expectations: None,
            skill_clarifications: Vec::new(),
            resume_rules: None,
        }
    }

    #[test]
    fn word_in_text_handles_special_characters_like_csharp() {
        assert!(ResumeManager::word_in_text("c#", "5 years of c# experience"));
        assert!(!ResumeManager::word_in_text("c#", "javascript developer"));
    }

    #[test]
    fn word_in_text_respects_word_boundaries() {
        assert!(ResumeManager::word_in_text("go", "experience with go and docker"));
        assert!(!ResumeManager::word_in_text("go", "django backend developer"));
    }

    #[test]
    fn detect_language_defaults_to_english_without_keywords() {
        assert_eq!(ResumeManager::detect_language("We need a great teammate"), "en");
    }

    #[test]
    fn detect_language_picks_spanish_when_ingeniero_present() {
        // Note: this mirrors Python's ResumeManager.detect_language exactly, including
        // its tie-breaking quirk — ties (e.g. text containing both "ingeniero" AND
        // "software") resolve to "en", not "es".
        assert_eq!(ResumeManager::detect_language("Buscamos ingeniero titulado con experiencia"), "es");
    }

    #[test]
    fn salary_expectation_matches_language_and_seniority_rule() {
        let mut profile = empty_profile();
        profile.salary_expectations = Some(SalaryExpectations {
            default: SalaryDefault { value: "Negotiable".to_string(), currency: "COP".to_string() },
            rules: vec![
                SalaryRule { role_match: "Senior".to_string(), language: "es".to_string(), value: "7000000".to_string(), currency: None },
                SalaryRule { role_match: "Lead".to_string(), language: "es".to_string(), value: "8000000".to_string(), currency: None },
            ],
        });
        let rm = ResumeManager::new(PathBuf::from("."), profile);

        let (value, currency) = rm.get_salary_expectation("Senior Backend Developer", "es");
        assert_eq!(value, "7000000");
        assert_eq!(currency, "COP");

        let (value, _) = rm.get_salary_expectation("Tech Lead", "es");
        assert_eq!(value, "8000000");
    }

    #[test]
    fn english_salary_rules_are_reported_in_usd_not_the_cop_default() {
        // Regression (2026-08-18): the "en" rules in profile_config.json carry monthly USD
        // amounts and declare no currency, so they inherited the global COP default and the
        // bot told employers it expected "2000 COP" — roughly USD 0.50 — for a senior role.
        let mut profile = empty_profile();
        profile.salary_expectations = Some(SalaryExpectations {
            default: SalaryDefault { value: "7000000".to_string(), currency: "COP".to_string() },
            rules: vec![
                SalaryRule { role_match: "Senior".to_string(), language: "es".to_string(), value: "7000000".to_string(), currency: None },
                SalaryRule { role_match: "Senior".to_string(), language: "en".to_string(), value: "2000".to_string(), currency: None },
                SalaryRule { role_match: "Lead".to_string(), language: "en".to_string(), value: "4000".to_string(), currency: None },
                SalaryRule { role_match: "Lead".to_string(), language: "es".to_string(), value: "8000000".to_string(), currency: None },
            ],
        });
        let rm = ResumeManager::new(PathBuf::from("."), profile);

        assert_eq!(rm.get_salary_expectation("Senior Backend Developer", "en"), ("2000".to_string(), "USD".to_string()));
        assert_eq!(rm.get_salary_expectation("Software Architect", "en"), ("4000".to_string(), "USD".to_string()));
        // Spanish rules keep pesos.
        assert_eq!(rm.get_salary_expectation("Senior Backend Developer", "es"), ("7000000".to_string(), "COP".to_string()));
        assert_eq!(rm.get_salary_expectation("Software Architect", "es"), ("8000000".to_string(), "COP".to_string()));
    }

    #[test]
    fn explicit_rule_currency_still_wins_over_language_inference() {
        let mut profile = empty_profile();
        profile.salary_expectations = Some(SalaryExpectations {
            default: SalaryDefault { value: "0".to_string(), currency: "COP".to_string() },
            rules: vec![SalaryRule {
                role_match: "Senior".to_string(),
                language: "en".to_string(),
                value: "50".to_string(),
                currency: Some("EUR".to_string()),
            }],
        });
        let rm = ResumeManager::new(PathBuf::from("."), profile);
        assert_eq!(rm.get_salary_expectation("Senior Developer", "en"), ("50".to_string(), "EUR".to_string()));
    }

    #[test]
    fn salary_expectation_falls_back_to_default_when_no_rule_matches() {
        let mut profile = empty_profile();
        profile.salary_expectations = Some(SalaryExpectations {
            default: SalaryDefault { value: "Negotiable".to_string(), currency: "COP".to_string() },
            rules: vec![],
        });
        let rm = ResumeManager::new(PathBuf::from("."), profile);
        let (value, currency) = rm.get_salary_expectation("QA Analyst", "en");
        assert_eq!(value, "Negotiable");
        assert_eq!(currency, "COP");
    }

    #[test]
    fn resume_filename_builds_deterministic_path_from_rules() {
        let mut profile = empty_profile();
        let mut codes = Map::new();
        codes.insert("leader".to_string(), "L".to_string());
        codes.insert("developer".to_string(), "D".to_string());
        let mut tech_mapping = Map::new();
        tech_mapping.insert("P".to_string(), vec!["python".to_string()]);
        tech_mapping.insert("C".to_string(), vec!["c#".to_string()]);
        let mut city_mapping = Map::new();
        city_mapping.insert("bogota".to_string(), "B".to_string());
        city_mapping.insert("__default__".to_string(), "M".to_string());
        let mut language_mapping = Map::new();
        language_mapping.insert("spanish".to_string(), "ES".to_string());
        language_mapping.insert("english".to_string(), "EN".to_string());

        profile.resume_rules = Some(ResumeRules {
            agent_config: ResumeAgentConfig {
                prefix: Some("CV".to_string()),
                experience: Some("20".to_string()),
                owner: Some("Test_Owner".to_string()),
                naming_format: Some("{prefix}_{exp}_{city}_{role}_{tech}_{lang}_{owner}{ext}".to_string()),
                file_extension: Some(".pdf".to_string()),
            },
            rules: ResumeRulesMap {
                city_mapping,
                role_mapping: RoleMapping { leader_keywords: vec!["lead".to_string()], codes },
                tech_mapping,
                language_mapping,
            },
        });

        let rm = ResumeManager::new(PathBuf::from("/tmp/does-not-exist"), profile);
        let path = rm.get_resume_filename("Python Developer", "django python", "es", None);
        // Falls back to global search since the exact file doesn't exist on disk, but the
        // filename itself must reflect the deterministic components.
        assert_eq!(path.file_name().unwrap().to_string_lossy(), "CV_20_M_D_P_ES_Test_Owner.pdf");
    }
}

fn walk_dir(dir: &Path) -> Result<Vec<PathBuf>> {
    let mut out = Vec::new();
    if !dir.is_dir() {
        return Ok(out);
    }
    for entry in std::fs::read_dir(dir)? {
        let entry = entry?;
        let path = entry.path();
        if path.is_dir() {
            out.extend(walk_dir(&path)?);
        } else {
            out.push(path);
        }
    }
    Ok(out)
}
