import time
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

@dataclass(frozen=True)
class Job:
    """Represents a job opportunity (Pure Domain Entity)."""
    url: str
    id: Optional[int] = None
    company: str = "Unknown"
    role: str = "Unknown"
    location: str = "Unknown"
    work_mode: str = "Unknown"
    date_posted: str = "Unknown"
    source: str = "Unknown"
    raw_requirements: str = ""
    match_score: int = 0
    priority_score: int = 0
    analysis: Dict[str, Any] = field(default_factory=dict)
    status: ApplicationStatus = ApplicationStatus.PENDING
    applied_resume: Optional[str] = None
    language: Optional[str] = None
    created_at: Optional[datetime] = None

@dataclass(frozen=True)
class CandidateProfile:
    """Represents the candidate's profile (Pure Domain Entity)."""
    raw_data: str
    target_roles: List[str] = field(default_factory=list)
    locations: List[str] = field(default_factory=list)
    salary_expectations: Dict[str, Any] = field(default_factory=dict)
    resume_rules: List[Dict[str, Any]] = field(default_factory=list)

@dataclass(frozen=True)
class TraceSpan:
    """Represents a discrete unit of work (Span) for observability."""
    name: str
    trace_id: str
    parent_id: Optional[str] = None
    start_time: float = field(default_factory=time.time)
    end_time: Optional[float] = None
    attributes: Dict[str, Any] = field(default_factory=dict)
    exception: Optional[str] = None
    status: str = "OK"  # OK, ERROR
