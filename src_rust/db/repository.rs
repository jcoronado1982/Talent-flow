use crate::domain::models::{Job, StatsSummary};
use anyhow::{Context, Result};
use rusqlite::Connection;
use serde::Deserialize;
use std::path::Path;

#[derive(Clone)]
pub struct DatabaseRepository {
    db_path: String,
}

/// Builder for DatabaseRepository::update_job_status, mirroring the optional
/// keyword args of src/services/storage/database.py::update_job_status.
#[derive(Debug, Default, Clone)]
pub struct JobStatusUpdate {
    pub status: String,
    pub resume: Option<String>,
    pub uploaded_cv: Option<String>,
    pub error: Option<String>,
    pub external_link: Option<String>,
    pub salary: Option<String>,
    pub currency: Option<String>,
}

impl JobStatusUpdate {
    pub fn new(status: impl Into<String>) -> Self {
        Self { status: status.into(), ..Default::default() }
    }
    pub fn resume(mut self, v: impl Into<String>) -> Self { self.resume = Some(v.into()); self }
    pub fn uploaded_cv(mut self, v: impl Into<String>) -> Self { self.uploaded_cv = Some(v.into()); self }
    pub fn error(mut self, v: impl Into<String>) -> Self { self.error = Some(v.into()); self }
    pub fn external_link(mut self, v: impl Into<String>) -> Self { self.external_link = Some(v.into()); self }
    pub fn salary(mut self, v: impl Into<String>) -> Self { self.salary = Some(v.into()); self }
    pub fn currency(mut self, v: impl Into<String>) -> Self { self.currency = Some(v.into()); self }
}

#[derive(Deserialize, Debug, Default, Clone)]
pub struct JobFilter {
    pub page: Option<usize>,
    pub page_size: Option<usize>,
    pub q: Option<String>,
    pub status: Option<String>,
    pub mode: Option<String>,
    pub apply_type: Option<String>,
    pub lang: Option<String>,
}

impl DatabaseRepository {
    pub fn db_path(&self) -> &str {
        &self.db_path
    }

    pub fn new(db_path: &Path) -> Result<Self> {
        let path_str = db_path.to_str().context("Invalid DB path")?.to_string();
        let repo = Self { db_path: path_str };
        repo.init()?;
        Ok(repo)
    }

    fn connect(&self) -> Result<Connection> {
        let conn = Connection::open(&self.db_path)
            .with_context(|| format!("Failed to open SQLite database at {}", self.db_path))?;
        
        conn.pragma_update(None, "journal_mode", "WAL")?;
        conn.pragma_update(None, "synchronous", "NORMAL")?;
        Ok(conn)
    }

    pub fn init(&self) -> Result<()> {
        let conn = self.connect()?;
        conn.execute(
            "CREATE TABLE IF NOT EXISTS jobs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                url TEXT UNIQUE NOT NULL,
                company TEXT NOT NULL,
                role TEXT NOT NULL,
                location TEXT,
                work_mode TEXT,
                date_posted TEXT,
                source TEXT,
                requirements TEXT,
                match_score REAL,
                priority_score REAL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                status TEXT DEFAULT 'Pending',
                applied_resume TEXT,
                applied_salary TEXT,
                applied_currency TEXT,
                error_log TEXT,
                raw_analysis TEXT,
                external_link TEXT,
                audit_trail TEXT,
                updated_at TIMESTAMP,
                skills TEXT,
                apply_type TEXT,
                processing_time REAL,
                raw_prompt TEXT,
                language TEXT,
                uploaded_cv TEXT,
                ai_model TEXT
            )",
            [],
        )?;

        // Mirrors src/services/storage/database.py::init_db — required so insert_trace()
        // and clear_all_jobs() don't fail with "no such table" on a fresh DB.
        conn.execute(
            "CREATE TABLE IF NOT EXISTS traces (
                span_id TEXT PRIMARY KEY,
                trace_id TEXT,
                parent_id TEXT,
                name TEXT,
                start_time REAL,
                end_time REAL,
                status TEXT,
                exception TEXT,
                attributes TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )",
            [],
        )?;

        conn.execute(
            "CREATE TABLE IF NOT EXISTS companies (
                name TEXT PRIMARY KEY,
                job_count INTEGER DEFAULT 1,
                last_seen TIMESTAMP,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )",
            [],
        )?;

        Ok(())
    }

    pub fn clear_all_jobs(&self) -> Result<()> {
        let conn = self.connect()?;
        conn.execute("DELETE FROM jobs;", [])?;
        conn.execute("DELETE FROM traces;", [])?;
        let _ = conn.execute("DELETE FROM sqlite_sequence;", []);
        Ok(())
    }

    pub fn get_stats(&self) -> Result<StatsSummary> {
        let conn = self.connect()?;
        
        let total: i64 = conn.query_row("SELECT count(*) FROM jobs", [], |r| r.get(0)).unwrap_or(0);
        let matched: i64 = conn.query_row("SELECT count(*) FROM jobs WHERE status = 'Matched'", [], |r| r.get(0)).unwrap_or(0);
        let discarded: i64 = conn.query_row("SELECT count(*) FROM jobs WHERE status = 'Discarded' OR status = 'Not Matched'", [], |r| r.get(0)).unwrap_or(0);
        let pending: i64 = conn.query_row("SELECT count(*) FROM jobs WHERE status = 'Pending'", [], |r| r.get(0)).unwrap_or(0);
        let avg_score: f64 = conn.query_row("SELECT COALESCE(AVG(match_score), 0.0) FROM jobs WHERE match_score IS NOT NULL", [], |r| r.get(0)).unwrap_or(0.0);

        Ok(StatsSummary {
            total_jobs: total,
            matched_jobs: matched,
            discarded_jobs: discarded,
            pending_jobs: pending,
            avg_match_score: (avg_score * 100.0).round() / 100.0,
        })
    }

    pub fn get_job_by_id(&self, id: i64) -> Result<Option<Job>> {
        let conn = self.connect()?;
        let mut stmt = conn.prepare(
            "SELECT id, url, company, role, location, work_mode, date_posted, source, requirements, match_score, priority_score, created_at, status, applied_resume, applied_salary, applied_currency, error_log, raw_analysis, external_link, audit_trail, updated_at, skills, apply_type, processing_time, raw_prompt, language, uploaded_cv, ai_model FROM jobs WHERE id = ?"
        )?;

        let mut job_iter = stmt.query_map([id], |row| {
            Ok(Job {
                id: row.get(0)?,
                url: row.get(1)?,
                company: row.get(2)?,
                role: row.get(3)?,
                location: row.get(4)?,
                work_mode: row.get(5)?,
                date_posted: row.get(6)?,
                source: row.get(7)?,
                requirements: row.get(8)?,
                match_score: row.get(9)?,
                priority_score: row.get(10)?,
                created_at: row.get(11)?,
                status: row.get(12)?,
                applied_resume: row.get(13)?,
                applied_salary: row.get(14)?,
                applied_currency: row.get(15)?,
                error_log: row.get(16)?,
                raw_analysis: row.get(17)?,
                external_link: row.get(18)?,
                audit_trail: row.get(19)?,
                updated_at: row.get(20)?,
                skills: row.get(21)?,
                apply_type: row.get(22)?,
                processing_time: row.get(23)?,
                raw_prompt: row.get(24)?,
                language: row.get(25)?,
                uploaded_cv: row.get(26)?,
                ai_model: row.get(27)?,
            })
        })?;

        if let Some(res) = job_iter.next() {
            Ok(Some(res?))
        } else {
            Ok(None)
        }
    }

    pub fn update_job_analysis(&self, id: i64, match_score: f64, status: &str, analysis: &str, skills: &str) -> Result<()> {
        let conn = self.connect()?;
        conn.execute(
            "UPDATE jobs SET match_score = ?1, status = ?2, raw_analysis = ?3, skills = ?4, updated_at = CURRENT_TIMESTAMP WHERE id = ?5",
            rusqlite::params![match_score, status, analysis, skills, id]
        )?;
        Ok(())
    }

    pub fn bulk_update_status(&self, ids: &[i64], new_status: &str) -> Result<()> {
        if ids.is_empty() {
            return Ok(());
        }
        let conn = self.connect()?;
        for id in ids {
            conn.execute(
                "UPDATE jobs SET status = ?1, updated_at = CURRENT_TIMESTAMP WHERE id = ?2",
                rusqlite::params![new_status, id]
            )?;
        }
        Ok(())
    }

    pub fn get_filtered_jobs(&self, filter: &JobFilter) -> Result<(Vec<Job>, usize)> {
        let conn = self.connect()?;
        let page = filter.page.unwrap_or(1).max(1);
        let page_size = filter.page_size.unwrap_or(100).max(1);
        let offset = (page - 1) * page_size;

        let mut where_clauses = Vec::new();
        let mut params_vec: Vec<Box<dyn rusqlite::ToSql>> = Vec::new();

        if let Some(ref q) = filter.q {
            if !q.trim().is_empty() {
                where_clauses.push("(role LIKE ? OR company LIKE ? OR skills LIKE ?)");
                let pattern = format!("%{}%", q.trim());
                params_vec.push(Box::new(pattern.clone()));
                params_vec.push(Box::new(pattern.clone()));
                params_vec.push(Box::new(pattern));
            }
        }

        if let Some(ref s) = filter.status {
            if s != "all" && !s.is_empty() {
                where_clauses.push("status = ?");
                params_vec.push(Box::new(s.clone()));
            }
        }

        if let Some(ref m) = filter.mode {
            if m != "all" && !m.is_empty() {
                where_clauses.push("work_mode = ?");
                params_vec.push(Box::new(m.clone()));
            }
        }

        if let Some(ref t) = filter.apply_type {
            if t != "all" && !t.is_empty() {
                where_clauses.push("apply_type = ?");
                params_vec.push(Box::new(t.clone()));
            }
        }

        if let Some(ref l) = filter.lang {
            if l != "all" && !l.is_empty() {
                where_clauses.push("language = ?");
                params_vec.push(Box::new(l.clone()));
            }
        }

        let where_str = if where_clauses.is_empty() {
            "".to_string()
        } else {
            format!("WHERE {}", where_clauses.join(" AND "))
        };

        let count_query = format!("SELECT count(*) FROM jobs {}", where_str);
        let mut count_stmt = conn.prepare(&count_query)?;
        let count_params: Vec<&dyn rusqlite::ToSql> = params_vec.iter().map(|b| b.as_ref()).collect();
        let total: usize = count_stmt.query_row(count_params.as_slice(), |r| r.get(0)).unwrap_or(0);

        let select_query = format!(
            "SELECT id, url, company, role, location, work_mode, date_posted, source, requirements, match_score, priority_score, created_at, status, applied_resume, applied_salary, applied_currency, error_log, raw_analysis, external_link, audit_trail, updated_at, skills, apply_type, processing_time, raw_prompt, language, uploaded_cv, ai_model FROM jobs {} ORDER BY id DESC LIMIT ? OFFSET ?",
            where_str
        );

        let mut select_stmt = conn.prepare(&select_query)?;
        let mut all_params = params_vec;
        all_params.push(Box::new(page_size as i64));
        all_params.push(Box::new(offset as i64));
        let all_rusqlite_params: Vec<&dyn rusqlite::ToSql> = all_params.iter().map(|b| b.as_ref()).collect();

        let job_iter = select_stmt.query_map(all_rusqlite_params.as_slice(), |row| {
            Ok(Job {
                id: row.get(0)?,
                url: row.get(1)?,
                company: row.get(2)?,
                role: row.get(3)?,
                location: row.get(4)?,
                work_mode: row.get(5)?,
                date_posted: row.get(6)?,
                source: row.get(7)?,
                requirements: row.get(8)?,
                match_score: row.get(9)?,
                priority_score: row.get(10)?,
                created_at: row.get(11)?,
                status: row.get(12)?,
                applied_resume: row.get(13)?,
                applied_salary: row.get(14)?,
                applied_currency: row.get(15)?,
                error_log: row.get(16)?,
                raw_analysis: row.get(17)?,
                external_link: row.get(18)?,
                audit_trail: row.get(19)?,
                updated_at: row.get(20)?,
                skills: row.get(21)?,
                apply_type: row.get(22)?,
                processing_time: row.get(23)?,
                raw_prompt: row.get(24)?,
                language: row.get(25)?,
                uploaded_cv: row.get(26)?,
                ai_model: row.get(27)?,
            })
        })?;

        let mut jobs = Vec::new();
        for j in job_iter {
            jobs.push(j?);
        }

        Ok((jobs, total))
    }

    /// Mirrors dashboard/main.py::get_audit_jobs — jobs that have already been analyzed
    /// (i.e. excludes ones still waiting in the queue).
    pub fn get_audit_jobs(&self) -> Result<Vec<Job>> {
        let conn = self.connect()?;
        let mut stmt = conn.prepare(
            "SELECT id, url, company, role, location, work_mode, date_posted, source, requirements, match_score, priority_score, created_at, status, applied_resume, applied_salary, applied_currency, error_log, raw_analysis, external_link, audit_trail, updated_at, skills, apply_type, processing_time, raw_prompt, language, uploaded_cv, ai_model FROM jobs WHERE status NOT IN ('Pending', 'Processing') ORDER BY updated_at DESC"
        )?;

        let job_iter = stmt.query_map([], |row| {
            Ok(Job {
                id: row.get(0)?,
                url: row.get(1)?,
                company: row.get(2)?,
                role: row.get(3)?,
                location: row.get(4)?,
                work_mode: row.get(5)?,
                date_posted: row.get(6)?,
                source: row.get(7)?,
                requirements: row.get(8)?,
                match_score: row.get(9)?,
                priority_score: row.get(10)?,
                created_at: row.get(11)?,
                status: row.get(12)?,
                applied_resume: row.get(13)?,
                applied_salary: row.get(14)?,
                applied_currency: row.get(15)?,
                error_log: row.get(16)?,
                raw_analysis: row.get(17)?,
                external_link: row.get(18)?,
                audit_trail: row.get(19)?,
                updated_at: row.get(20)?,
                skills: row.get(21)?,
                apply_type: row.get(22)?,
                processing_time: row.get(23)?,
                raw_prompt: row.get(24)?,
                language: row.get(25)?,
                uploaded_cv: row.get(26)?,
                ai_model: row.get(27)?,
            })
        })?;

        let mut jobs = Vec::new();
        for j in job_iter {
            jobs.push(j?);
        }
        Ok(jobs)
    }

    /// Mirrors src/services/storage/database.py::get_jobs_to_apply — jobs ready for the
    /// Apply bot, prioritizing Easy Apply + Colombia listings.
    pub fn get_jobs_to_apply(&self, limit: i64) -> Result<Vec<Job>> {
        let conn = self.connect()?;
        let mut stmt = conn.prepare(
            "SELECT id, url, company, role, location, work_mode, date_posted, source, requirements, match_score, priority_score, created_at, status, applied_resume, applied_salary, applied_currency, error_log, raw_analysis, external_link, audit_trail, updated_at, skills, apply_type, processing_time, raw_prompt, language, uploaded_cv, ai_model FROM jobs \
             WHERE status = 'Matched' \
             ORDER BY \
                (CASE \
                    WHEN apply_type = 'Easy Apply' AND location LIKE '%Colombia%' THEN 0 \
                    WHEN apply_type = 'Easy Apply' THEN 1 \
                    WHEN apply_type != 'Easy Apply' AND location LIKE '%Colombia%' THEN 2 \
                    ELSE 3 \
                END) ASC, \
                match_score DESC, \
                priority_score DESC \
             LIMIT ?1"
        )?;

        let job_iter = stmt.query_map([limit], |row| {
            Ok(Job {
                id: row.get(0)?,
                url: row.get(1)?,
                company: row.get(2)?,
                role: row.get(3)?,
                location: row.get(4)?,
                work_mode: row.get(5)?,
                date_posted: row.get(6)?,
                source: row.get(7)?,
                requirements: row.get(8)?,
                match_score: row.get(9)?,
                priority_score: row.get(10)?,
                created_at: row.get(11)?,
                status: row.get(12)?,
                applied_resume: row.get(13)?,
                applied_salary: row.get(14)?,
                applied_currency: row.get(15)?,
                error_log: row.get(16)?,
                raw_analysis: row.get(17)?,
                external_link: row.get(18)?,
                audit_trail: row.get(19)?,
                updated_at: row.get(20)?,
                skills: row.get(21)?,
                apply_type: row.get(22)?,
                processing_time: row.get(23)?,
                raw_prompt: row.get(24)?,
                language: row.get(25)?,
                uploaded_cv: row.get(26)?,
                ai_model: row.get(27)?,
            })
        })?;

        let mut jobs = Vec::new();
        for j in job_iter {
            jobs.push(j?);
        }
        Ok(jobs)
    }

    /// Retorna vacantes que tienen enlace de postulación externa (`external_link`) registrado en SQLite,
    /// para aplicación directa sin pasar por LinkedIn.
    pub fn get_external_jobs_to_apply(
        &self,
        limit: i64,
        status_filter: Option<&str>,
        job_id: Option<i64>,
    ) -> Result<Vec<Job>> {
        let conn = self.connect()?;
        let mut where_clauses = vec![
            "external_link IS NOT NULL".to_string(),
            "TRIM(external_link) != ''".to_string(),
        ];
        let mut params: Vec<Box<dyn rusqlite::ToSql>> = Vec::new();

        if let Some(id) = job_id {
            where_clauses.push("id = ?".to_string());
            params.push(Box::new(id));
        } else if let Some(status) = status_filter {
            if status != "all" {
                where_clauses.push("status = ?".to_string());
                params.push(Box::new(status.to_string()));
            }
        } else {
            // Por defecto: vacantes externas en estado Matched, Manual, Failed o Pending
            where_clauses.push("status IN ('Matched', 'Manual', 'Failed', 'Pending')".to_string());
        }

        let sql = format!(
            "SELECT id, url, company, role, location, work_mode, date_posted, source, requirements, \
             match_score, priority_score, created_at, status, applied_resume, applied_salary, applied_currency, \
             error_log, raw_analysis, external_link, audit_trail, updated_at, skills, apply_type, processing_time, \
             raw_prompt, language, uploaded_cv, ai_model FROM jobs \
             WHERE {} \
             ORDER BY \
                (CASE status \
                    WHEN 'Matched' THEN 0 \
                    WHEN 'Manual' THEN 1 \
                    WHEN 'Failed' THEN 2 \
                    ELSE 3 \
                END) ASC, \
                COALESCE(match_score, 0.0) DESC, \
                id DESC \
             LIMIT ?",
            where_clauses.join(" AND ")
        );

        params.push(Box::new(limit));
        let param_refs: Vec<&dyn rusqlite::ToSql> = params.iter().map(|b| b.as_ref()).collect();

        let mut stmt = conn.prepare(&sql)?;
        let job_iter = stmt.query_map(param_refs.as_slice(), |row| {
            Ok(Job {
                id: row.get(0)?,
                url: row.get(1)?,
                company: row.get(2)?,
                role: row.get(3)?,
                location: row.get(4)?,
                work_mode: row.get(5)?,
                date_posted: row.get(6)?,
                source: row.get(7)?,
                requirements: row.get(8)?,
                match_score: row.get(9)?,
                priority_score: row.get(10)?,
                created_at: row.get(11)?,
                status: row.get(12)?,
                applied_resume: row.get(13)?,
                applied_salary: row.get(14)?,
                applied_currency: row.get(15)?,
                error_log: row.get(16)?,
                raw_analysis: row.get(17)?,
                external_link: row.get(18)?,
                audit_trail: row.get(19)?,
                updated_at: row.get(20)?,
                skills: row.get(21)?,
                apply_type: row.get(22)?,
                processing_time: row.get(23)?,
                raw_prompt: row.get(24)?,
                language: row.get(25)?,
                uploaded_cv: row.get(26)?,
                ai_model: row.get(27)?,
            })
        })?;

        let mut jobs = Vec::new();
        for j in job_iter {
            jobs.push(j?);
        }
        Ok(jobs)
    }

    /// Mirrors src/services/storage/database.py::update_job_status — generic status
    /// update used throughout the Apply flow, appending to audit_trail/error_log
    /// instead of overwriting them.
    pub fn update_job_status(&self, id: i64, update: &JobStatusUpdate) -> Result<()> {
        let conn = self.connect()?;
        let timestamp = chrono::Local::now().format("%Y-%m-%d %H:%M:%S").to_string();

        let mut audit_msg = format!("[{}] Status: {}", timestamp, update.status);
        if let Some(ref err) = update.error {
            audit_msg.push_str(&format!(" | Error: {}", &err.chars().take(200).collect::<String>()));
        }

        let mut fields = vec!["status = ?1".to_string(), "updated_at = ?2".to_string(), "audit_trail = COALESCE(audit_trail, '') || ?3 || char(10)".to_string()];
        let mut params: Vec<Box<dyn rusqlite::ToSql>> = vec![
            Box::new(update.status.clone()),
            Box::new(timestamp.clone()),
            Box::new(audit_msg),
        ];

        if let Some(ref resume) = update.resume {
            fields.push(format!("applied_resume = ?{}", params.len() + 1));
            params.push(Box::new(resume.clone()));
        }
        if let Some(ref cv) = update.uploaded_cv {
            fields.push(format!("uploaded_cv = ?{}", params.len() + 1));
            params.push(Box::new(cv.clone()));
        }
        if let Some(ref link) = update.external_link {
            fields.push(format!("external_link = ?{}", params.len() + 1));
            params.push(Box::new(link.clone()));
        }
        if let Some(ref salary) = update.salary {
            fields.push(format!("applied_salary = ?{}", params.len() + 1));
            params.push(Box::new(salary.clone()));
        }
        if let Some(ref currency) = update.currency {
            fields.push(format!("applied_currency = ?{}", params.len() + 1));
            params.push(Box::new(currency.clone()));
        }
        if let Some(ref err) = update.error {
            fields.push(format!("error_log = COALESCE(error_log, '') || char(10) || ?{}", params.len() + 1));
            params.push(Box::new(format!("[{}] {}", timestamp, err)));
        }

        let id_placeholder = params.len() + 1;
        params.push(Box::new(id));

        let sql = format!("UPDATE jobs SET {} WHERE id = ?{}", fields.join(", "), id_placeholder);
        let param_refs: Vec<&dyn rusqlite::ToSql> = params.iter().map(|b| b.as_ref()).collect();
        conn.execute(&sql, param_refs.as_slice())?;
        Ok(())
    }

    pub fn insert_trace(&self, span_id: &str, trace_id: &str, name: &str, status: &str, attributes: &str) -> Result<()> {
        let conn = self.connect()?;
        let now = chrono::Utc::now().timestamp_millis() as f64 / 1000.0;
        conn.execute(
            "INSERT INTO traces (span_id, trace_id, name, start_time, end_time, status, attributes) VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7)",
            rusqlite::params![span_id, trace_id, name, now, now, status, attributes]
        )?;
        Ok(())
    }
}
