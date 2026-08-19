import pytest
import sqlite3
import os
from unittest.mock import MagicMock
from src.application.use_cases.analyze_job import AnalyzeAndStoreJobUseCase
from src.domain.interfaces import IJobAnalyzer, IJobRepository, IMonitor
from src.services.storage.database import get_connection, init_db
from src.config.settings import Settings

@pytest.fixture
def test_db(tmp_path):
    db_file = tmp_path / "test_talentflow.db"
    # Mock Settings.DB_PATH for the duration of the test
    original_db = Settings.DB_PATH
    Settings.DB_PATH = str(db_file)
    init_db()
    yield db_file
    Settings.DB_PATH = original_db

def test_observed_decorator_records_trace(test_db):
    # Setup mocks
    analyzer = MagicMock(spec=IJobAnalyzer)
    analyzer.analyze.return_value = {"match_percentage": 85}
    repo = MagicMock(spec=IJobRepository)
    monitor = MagicMock(spec=IMonitor)
    
    use_case = AnalyzeAndStoreJobUseCase(analyzer, repo, monitor)
    
    # Execute use case
    use_case.execute({"description": "Test Job Description"*10, "company": "TestCo"}, "http://test.com", "Engineer")
    
    # Verify traces table
    conn = sqlite3.connect(str(test_db))
    c = conn.cursor()
    c.execute("SELECT * FROM traces")
    traces = c.fetchall()
    conn.close()
    
    assert len(traces) > 0
    trace = traces[0]
    # columns: span_id, trace_id, parent_id, name, start_time, end_time, status, exception, attributes, created_at
    assert "AnalyzeAndStoreJobUseCase.execute" in trace[3]
    assert trace[6] == "OK"
    assert trace[7] is None

def test_observed_decorator_records_error(test_db):
    # Setup mocks that fail
    analyzer = MagicMock(spec=IJobAnalyzer)
    analyzer.analyze.side_effect = Exception("IA Explosion")
    repo = MagicMock(spec=IJobRepository)
    monitor = MagicMock(spec=IMonitor)
    
    use_case = AnalyzeAndStoreJobUseCase(analyzer, repo, monitor)
    
    # Execute use case and expect failure
    with pytest.raises(Exception):
        use_case.execute({"description": "Test Job Description"*10, "company": "TestCo"}, "http://test.com", "Engineer")
    
    # Verify traces table
    conn = sqlite3.connect(str(test_db))
    c = conn.cursor()
    c.execute("SELECT * FROM traces WHERE status = 'ERROR'")
    traces = c.fetchall()
    conn.close()
    
    assert len(traces) == 1
    trace = traces[0]
    assert trace[6] == "ERROR"
    assert "IA Explosion" in trace[7]
