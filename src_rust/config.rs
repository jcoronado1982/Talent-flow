use crate::domain::models::{ProfileConfig, ResumeRules};
use anyhow::{Context, Result};
use std::fs;
use std::path::PathBuf;

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

#[derive(Debug, Clone)]
pub struct AppConfig {
    /// Repo root — used by the Apply flow's ResumeManager to resolve cv/ paths.
    pub base_dir: PathBuf,
    pub db_path: PathBuf,
    pub profile: ProfileConfig,
}

impl AppConfig {
    pub fn load() -> Result<Self> {
        let base_dir = std::env::current_dir().unwrap_or_else(|_| PathBuf::from("."));
        let db_path = base_dir.join("talentflow.db");
        let profile_path = base_dir.join("config").join("profile_config.json");

        let mut profile = if profile_path.exists() {
            let content = fs::read_to_string(&profile_path)
                .with_context(|| format!("Failed to read profile config at {:?}", profile_path))?;
            serde_json::from_str::<ProfileConfig>(&content).unwrap_or_else(|_| empty_profile())
        } else {
            empty_profile()
        };

        // Hybrid loading: cv_profile.json isn't part of profile_config.json, but the
        // Python side (Settings.load_profile) merges it in under "resume_rules" so the
        // resume-selection engine can use both files. Mirror that here.
        let cv_profile_path = base_dir.join("config").join("cv_profile.json");
        if cv_profile_path.exists() {
            if let Ok(content) = fs::read_to_string(&cv_profile_path) {
                if let Ok(resume_rules) = serde_json::from_str::<ResumeRules>(&content) {
                    profile.resume_rules = Some(resume_rules);
                }
            }
        }

        Ok(Self {
            base_dir,
            db_path,
            profile,
        })
    }
}
