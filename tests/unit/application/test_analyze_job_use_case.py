import pytest
from unittest.mock import MagicMock
from src.application.use_cases.analyze_job import AnalyzeAndStoreJobUseCase
from src.domain.entities import Job, ApplicationStatus
from src.domain.interfaces import IJobRepository, IMonitor, IJobAnalyzer

@pytest.fixture
def mock_repo():
    return MagicMock(spec=IJobRepository)

@pytest.fixture
def mock_monitor():
    return MagicMock(spec=IMonitor)

@pytest.fixture
def mock_analyzer():
    return MagicMock(spec=IJobAnalyzer)

def test_analyze_job_matched(mock_repo, mock_monitor, mock_analyzer):
    # Setup
    use_case = AnalyzeAndStoreJobUseCase(
        analyzer=mock_analyzer,
        repository=mock_repo,
        monitor=mock_monitor
    )
    
    raw_details = {
        "description": "This is a long description for a senior developer role with lots of python.",
        "company": "TechCorp",
        "title": "Senior Dev",
        "location": "Remote",
        "date": "2024-01-01"
    }
    
    mock_analyzer.analyze.return_value = {
        "match_percentage": 90,
        "role": "Dev",
        "company": "Comp",
        "priority_score": 10
    }
    
    # Execute
    use_case.execute(raw_details, url="http://job.com", current_role="Dev")
    
    # Verify
    mock_repo.save.assert_called_once()
    saved_job = mock_repo.save.call_args[0][0]
    assert saved_job.match_score == 90
    assert saved_job.status == ApplicationStatus.PENDING
    mock_monitor.add_match.assert_called_once()

def test_analyze_job_rejected(mock_repo, mock_monitor, mock_analyzer):
    # Setup
    use_case = AnalyzeAndStoreJobUseCase(
        analyzer=mock_analyzer,
        repository=mock_repo,
        monitor=mock_monitor
    )
    
    raw_details = {
        "description": "This is a long description for a junior role.",
        "company": "Comp",
        "date": "2024-01-01"
    }
    
    mock_analyzer.analyze.return_value = {
        "match_percentage": 20,
        "role": "Jun",
        "company": "Comp",
        "priority_score": 0
    }
    
    # Execute
    use_case.execute(raw_details, url="http://job.com", current_role="Jun")
    
    # Verify
    # Should NOT be saved in repository if < 30% (current logic in use_case)
    mock_repo.save.assert_not_called()
    mock_monitor.log.assert_called()
