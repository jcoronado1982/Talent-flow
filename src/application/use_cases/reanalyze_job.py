import time
from typing import Optional
from src.domain.interfaces import IJobAnalyzer, IMonitor
import src.services.storage.database as db
from src.agents.resume_manager import ResumeManagerAgent

class ReanalyzeJobUseCase:
    """
    Use case to trigger a fresh AI analysis for an existing job offer.
    Fetches the original description and re-runs the evaluator.
    """
    def __init__(self, analyzer: IJobAnalyzer, monitor: IMonitor):
        self.analyzer = analyzer
        self.monitor = monitor
        self.resume_agent = ResumeManagerAgent()

    def execute(self, job_id: int) -> Optional[dict]:
        self.monitor.log(f"🔄 [RE-ANALYZE] Re-evaluando oferta ID: {job_id}...")
        
        # 0. Ensure AI has the latest profile config
        if hasattr(self.analyzer, "prompts") and hasattr(self.analyzer.prompts, "refresh_config"):
            self.analyzer.prompts.refresh_config()

        # 1. Fetch existing job
        job_data = db.get_job_by_id(job_id)
        if not job_data:
            self.monitor.log(f"❌ [RE-ANALYZE] Error: Job {job_id} no encontrado.")
            return None

        description = job_data.get("requirements") or job_data.get("raw_requirements") or ""
        if not description or len(description) < 50:
            self.monitor.log(f"⚠️ [RE-ANALYZE] Error: Descripción insuficiente para ID {job_id}.")
            return None

        # 2. Analyze
        start_time = time.time()
        date_posted = job_data.get("date_posted", "Unknown")
        analysis_result = self.analyzer.analyze(f"PUBLICATION DATE: {date_posted}\n\n{description}")
        
        if not analysis_result:
            self.monitor.log(f"❌ [RE-ANALYZE] Error de IA durante re-análisis.")
            return None

        # 3. Prepare Update
        analysis = analysis_result.get("data")
        raw_response = analysis_result.get("raw_response", "")

        if not analysis or not isinstance(analysis, dict):
            # AI returned something but it couldn't be parsed as our schema.
            # Store the raw response anyway so the user can inspect it.
            self.monitor.log(
                f"⚠️ [RE-ANALYZE] ID {job_id}: La IA respondió pero no se pudo extraer un puntaje válido."
            )
            import datetime
            conn = __import__("sqlite3").connect(db.Settings.DB_PATH)
            conn.execute(
                "UPDATE jobs SET raw_analysis = ?, updated_at = ? WHERE id = ?",
                (raw_response, datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"), job_id),
            )
            conn.commit()
            conn.close()
            return {"data": {}, "raw_response": raw_response}

        match_score = analysis.get("match_percentage")
        # Handle cases where match_score might be a string like "85%"
        if isinstance(match_score, str):
            try:
                match_score = int(''.join(filter(str.isdigit, match_score)))
            except:
                match_score = 0
        elif match_score is None:
            match_score = 0
        
        # We reuse the db.save_job logic which handles the UPSERT via URL
        # We need to map the DB row back to the dict format expected by save_job
        update_data = {
            "url": job_data["url"],
            "company": job_data["company"],
            "role": job_data["role"],
            "location": job_data["location"],
            "date": job_data["date_posted"],
            "source": job_data["source"],
            "raw_requirements": description,
            "analysis": analysis,
            "raw_analysis": raw_response,
            "processing_time": time.time() - start_time,
            "skills": analysis.get("mandatory_skills") or job_data.get("skills"),
            "apply_type": job_data.get("apply_type"),
            "raw_prompt": analysis_result.get("raw_prompt")
        }

        # 4. CV Selection via ResumeManagerAgent
        cv_input = {
            "ROLE":     job_data.get("role", "Unknown"),
            "LOCATION": analysis.get("location_detected") or job_data.get("location", ""),
            "SKILLS":   analysis.get("mandatory_skills") or job_data.get("skills", ""),
            "LANG":     analysis.get("language_detected") or "Spanish",
        }
        update_data["applied_resume"] = self.resume_agent.get_resume_filename(cv_input)

        db.save_job(update_data)

        # After re-analysis, status is based on score. Never 'Pending' (that's for unprocessed jobs).
        verdict = analysis.get("verdict", "").upper()
        if match_score >= 40 and verdict != "REJECT":
            new_status = "Matched"
        else:
            new_status = "Discarded"

        db.update_job_status(job_id, new_status)

        self.monitor.log(f"✅ [RE-ANALYZE] ID {job_id} → Match: {match_score}% | Status: {new_status}")
        return analysis_result
