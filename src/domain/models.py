from dataclasses import dataclass, field
from typing import Optional, Dict, Any, List
from enum import Enum
from datetime import datetime

class ApplicationStatus(Enum):
    PENDING = "Pending"
    APPLIED = "Applied"
    FAILED = "Failed"
    MANUAL = "Manual"
    SKIPPED = "Skipped"
    MATCHED = "Matched"
    DISCARDED = "Discarded"

@dataclass
class JobConfig:
    """Runtime configuration for a job application process."""
    resume_path: Optional[str] = None
    answers: Dict[str, Any] = field(default_factory=dict)

@dataclass
class Job:
    """Represents a job opportunity."""
    url: str
    id: Optional[int] = None
    company: str = "Unknown"
    role: str = "Unknown"
    location: str = "Unknown"
    work_mode: str = "Unknown"
    date_posted: str = "Unknown"
    language: str = "Unknown"
    source: str = "Unknown"
    raw_requirements: str = ""
    match_score: int = 0
    priority_score: int = 0
    analysis: Dict[str, Any] = field(default_factory=dict)
    status: ApplicationStatus = ApplicationStatus.PENDING
    applied_resume: Optional[str] = None
    language: Optional[str] = None
    created_at: Optional[datetime] = None
    
    def to_dict(self):
        return {
            "id": self.id,
            "url": self.url,
            "company": self.company,
            "role": self.role,
            "match_score": self.match_score,
            "status": self.status.value
        }

@dataclass
class CandidateProfile:
    """Represents the candidate's profile and preferences."""
    raw_data: str # The text representation for the AI
    target_roles: List[str] = field(default_factory=list)
    locations: List[str] = field(default_factory=list)
    salary_expectations: Dict[str, Any] = field(default_factory=dict)
    resume_rules: List[Dict[str, Any]] = field(default_factory=list)
