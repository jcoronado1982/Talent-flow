use serde::{Deserialize, Serialize};
use std::collections::HashMap;

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Job {
    pub id: Option<i64>,
    pub url: String,
    pub company: String,
    pub role: String,
    pub location: Option<String>,
    pub work_mode: Option<String>,
    pub date_posted: Option<String>,
    pub source: Option<String>,
    pub requirements: Option<String>,
    pub match_score: Option<f64>,
    pub priority_score: Option<f64>,
    pub created_at: Option<String>,
    pub status: String,
    pub applied_resume: Option<String>,
    pub applied_salary: Option<String>,
    pub applied_currency: Option<String>,
    pub error_log: Option<String>,
    pub raw_analysis: Option<String>,
    pub external_link: Option<String>,
    pub audit_trail: Option<String>,
    pub updated_at: Option<String>,
    pub skills: Option<String>,
    pub apply_type: Option<String>,
    pub processing_time: Option<f64>,
    pub raw_prompt: Option<String>,
    pub language: Option<String>,
    pub uploaded_cv: Option<String>,
    pub ai_model: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct PersonalInfo {
    pub full_name: Option<String>,
    pub email: Option<String>,
    pub phone: Option<String>,
    pub location: Option<String>,
    pub portfolio_url: Option<String>,
    pub github_url: Option<String>,
    pub linkedin_url: Option<String>,
    pub dni: Option<String>,
    pub availability: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct AiConfig {
    pub provider: String,
    pub cloud_model: Option<String>,
    #[serde(default)]
    pub openai_model: Option<String>,
    #[serde(default)]
    pub anthropic_model: Option<String>,
    pub local_model: Option<String>,
    pub local_url: Option<String>,
    pub wasp_url: Option<String>,
    pub max_workers: Option<usize>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct SkillInfo {
    #[serde(default)]
    pub level: u32,
    #[serde(default)]
    pub years: u32,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct SalaryRule {
    #[serde(default)]
    pub role_match: String,
    #[serde(default)]
    pub language: String,
    pub value: String,
    pub currency: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct SalaryDefault {
    pub value: String,
    pub currency: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct SalaryExpectations {
    pub default: SalaryDefault,
    #[serde(default)]
    pub rules: Vec<SalaryRule>,
}

/// Mirrors config/cv_profile.json::agent_config
#[derive(Debug, Clone, Serialize, Deserialize, Default)]
pub struct ResumeAgentConfig {
    pub prefix: Option<String>,
    pub experience: Option<String>,
    pub owner: Option<String>,
    pub naming_format: Option<String>,
    pub file_extension: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize, Default)]
pub struct RoleMapping {
    #[serde(default)]
    pub leader_keywords: Vec<String>,
    #[serde(default)]
    pub codes: HashMap<String, String>,
}

/// Mirrors config/cv_profile.json::rules
#[derive(Debug, Clone, Serialize, Deserialize, Default)]
pub struct ResumeRulesMap {
    #[serde(default)]
    pub city_mapping: HashMap<String, String>,
    #[serde(default)]
    pub role_mapping: RoleMapping,
    #[serde(default)]
    pub tech_mapping: HashMap<String, Vec<String>>,
    #[serde(default)]
    pub language_mapping: HashMap<String, String>,
}

/// Loaded from config/cv_profile.json and merged into ProfileConfig at startup,
/// mirroring src/config/settings.py::Settings.load_profile()'s hybrid loading.
#[derive(Debug, Clone, Serialize, Deserialize, Default)]
pub struct ResumeRules {
    #[serde(default)]
    pub agent_config: ResumeAgentConfig,
    #[serde(default)]
    pub rules: ResumeRulesMap,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ProfileConfig {
    pub personal_info: Option<PersonalInfo>,
    pub ai_config: Option<AiConfig>,
    pub years_of_experience: Option<u32>,
    pub spanish_level: Option<String>,
    pub english_level: Option<String>,
    pub target_roles: Option<Vec<String>>,
    pub location_preferences: Option<Vec<String>>,
    #[serde(default)]
    pub skills: HashMap<String, HashMap<String, SkillInfo>>,
    pub salary_expectations: Option<SalaryExpectations>,
    #[serde(default)]
    pub skill_clarifications: Vec<String>,
    /// Not present in profile_config.json itself — merged in from cv_profile.json
    /// by AppConfig::load(), same as Python's hybrid loader.
    #[serde(default)]
    pub resume_rules: Option<ResumeRules>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct StatsSummary {
    pub total_jobs: i64,
    pub matched_jobs: i64,
    pub discarded_jobs: i64,
    pub pending_jobs: i64,
    pub avg_match_score: f64,
}
