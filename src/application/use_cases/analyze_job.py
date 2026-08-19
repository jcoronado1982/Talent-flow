from typing import Dict, Any, Optional
from src.domain.entities import Job, ApplicationStatus
from src.domain.interfaces import IJobAnalyzer, IJobRepository, IMonitor
from src.agents.resume_manager import ResumeManagerAgent
from src.utils.observability import observed

class AnalyzeAndStoreJobUseCase:
    def __init__(self, analyzer: IJobAnalyzer, repository: IJobRepository, monitor: IMonitor):
        self.analyzer = analyzer
        self.repository = repository
        self.monitor = monitor
        self.resume_agent = ResumeManagerAgent()

    @observed
    def execute(self, raw_details: Dict[str, Any], url: str, current_role: str):
        description = raw_details.get("description", "")
        company = raw_details.get("company", "Unknown")
        date_posted = raw_details.get("date", "Unknown")
        
        self.monitor.log(f"▶️ [USE-CASE] Procesando oferta: {company}")
        
        if not description or len(description) < 50:
            self.monitor.log("⚠️ [USE-CASE] Cancelado: Descripción insuficiente.")
            return

        self.monitor.log(f"⏳ [USE-CASE] Analizando con IA ({len(description)} chars)...")
        
        prompt = (
            f"ROLE: {raw_details.get('title', current_role)}\n"
            f"LOCATION: {raw_details.get('location', 'Unknown')}\n"
            f"JOB DESCRIPTION:\n{description}"
        )
        analysis = self.analyzer.analyze(prompt)
        
        if not analysis:
            self.monitor.log("❌ [USE-CASE] Error: Falló el análisis de IA.")
            return

        match_score = analysis.get('match_percentage', 0)
        from src.utils.observability import record_decision
        record_decision({
            "ai_analysis": analysis,
            "job_url": url,
            "job_company": company
        })
        
        # Pure Business Logic: 50% Threshold
        is_match = match_score >= 50
        
        if is_match:
            job_entity = Job(
                url=url,
                source="linkedin",
                role=raw_details.get("title", current_role),
                company=company,
                location=raw_details.get("location", "Unknown"),
                work_mode=raw_details.get("work_mode", "Unknown"),
                date_posted=date_posted,
                raw_requirements=raw_details.get("raw_requirements", ""),
                match_score=match_score,
                analysis=analysis,
                status=ApplicationStatus.MATCHED,
                language=analysis.get("language_detected")
            )
            
            # CV Selection via deterministic business rules (overrides AI guess)
            # Use structured metadata so cv_profile.json rules are always applied correctly
            cv_input = {
                "ROLE":     raw_details.get("title", current_role),
                "LOCATION": analysis.get("location_detected", raw_details.get("location", "")),
                "SKILLS":   analysis.get("mandatory_skills", ""),
                "LANG":     analysis.get("language_detected", "Spanish"),
            }
            job_entity.applied_resume = self.resume_agent.get_resume_filename(cv_input)
            
            self.repository.save(job_entity)
            self.monitor.add_match(raw_details, match_score)
            self.monitor.log(f"✅ [USE-CASE] Éxito: {match_score}% de coincidencia.")
        else:
            self.monitor.log(f"📉 [USE-CASE] Descartada: {match_score}% de coincidencia.")
        
