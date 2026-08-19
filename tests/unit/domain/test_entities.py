import pytest
from src.domain.entities import Job, ApplicationStatus, CandidateProfile

def test_job_initialization():
    job = Job(
        url="http://test.com",
        id=1,
        role="Developer",
        company="TechCorp",
        location="Remote",
        status=ApplicationStatus.PENDING,
        match_score=85
    )
    
    assert job.id == 1
    assert job.role == "Developer"
    assert job.status == ApplicationStatus.PENDING
    assert job.match_score == 85

def test_job_default_values():
    job = Job(
        url="http://test.com",
        role="Developer",
        company="TechCorp"
    )
    
    assert job.status == ApplicationStatus.PENDING
    assert job.match_score == 0
    assert job.id is None

def test_candidate_profile_initialization():
    profile = CandidateProfile(
        raw_data="John Doe, 5 years experience in Python",
        target_roles=["Developer", "Lead"]
    )
    
    assert "John Doe" in profile.raw_data
    assert "Developer" in profile.target_roles
