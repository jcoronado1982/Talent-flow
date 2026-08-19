from typing import Optional, Dict, Any
from src.domain.entities import Job, ApplicationStatus
from src.domain.interfaces import IJobRepository
import src.services.storage.database as db

class SQLiteJobRepository(IJobRepository):
    def __init__(self):
        db.init_db()

    def save(self, job: Job) -> Job:
        # Convert Entity to DB Dict
        # The legacy db.save_job expects match_percentage and priority_score inside 'analysis'
        analysis = dict(job.analysis)
        if "match_percentage" not in analysis:
            analysis["match_percentage"] = job.match_score
        if "priority_score" not in analysis:
            analysis["priority_score"] = job.priority_score

        job_dict = {
            "source": job.source,
            "url": job.url,
            "role": job.role,
            "company": job.company,
            "location": job.location,
            "work_mode": job.work_mode,
            "date": job.date_posted,
            "raw_requirements": job.raw_requirements,
            "analysis": analysis,
            "status": job.status.value if hasattr(job.status, 'value') else job.status,
            "applied_resume": job.applied_resume,
            "language": job.language
        }
        db.save_job(job_dict)
        return job

    def get_by_url(self, url: str) -> Optional[Job]:
        # This would require an implementation in database.py
        # For now, we use it for existence checks
        return None 
