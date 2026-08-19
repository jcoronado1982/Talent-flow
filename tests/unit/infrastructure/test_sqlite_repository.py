import pytest
import os
from unittest.mock import patch
from src.infrastructure.storage.sqlite_repository import SQLiteJobRepository
from src.domain.entities import Job, ApplicationStatus

# Helper to create a temp DB and initialize it
@pytest.fixture
def temp_db(tmp_path):
    db_file = tmp_path / "test_talentflow.db"
    
    # Mock settings to use this temp DB
    with patch("src.config.settings.Settings.DB_PATH", str(db_file)):
        from src.services.storage.database import init_db
        init_db()
        yield str(db_file)

@pytest.fixture
def repo(temp_db):
    # The repository will now use the patched Settings.DB_PATH
    with patch("src.config.settings.Settings.DB_PATH", temp_db):
        # We need to ensure SQLiteJobRepository imports database which uses patched settings
        return SQLiteJobRepository()

def test_save_and_get_job(repo, temp_db):
    job = Job(
        url="http://realtest.com",
        role="Senior Engineer",
        company="BigTech",
        location="Remote",
        match_score=95,
        status=ApplicationStatus.PENDING
    )
    
    # Save
    with patch("src.config.settings.Settings.DB_PATH", temp_db):
        repo.save(job)
    
    # Verify via the lower level db
    import src.services.storage.database as db
    with patch("src.config.settings.Settings.DB_PATH", temp_db):
        jobs = db.get_all_jobs()
    
    assert len(jobs) == 1
    assert jobs[0]['url'] == "http://realtest.com"
    assert jobs[0]['match_score'] == 95

def test_duplicate_url_upsert(repo, temp_db):
    job1 = Job(url="http://dup.com", role="Dev", company="A", match_score=50)
    job2 = Job(url="http://dup.com", role="Dev", company="B", match_score=80)
    
    with patch("src.config.settings.Settings.DB_PATH", temp_db):
        repo.save(job1)
        repo.save(job2)
    
    import src.services.storage.database as db
    with patch("src.config.settings.Settings.DB_PATH", temp_db):
        jobs = db.get_all_jobs()
    
    assert len(jobs) == 1
    assert jobs[0]['match_score'] == 80  # Should have been updated
