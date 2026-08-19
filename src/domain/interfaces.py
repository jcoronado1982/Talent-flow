from typing import Protocol, Dict, Any, Optional, List
from src.domain.entities import Job

class IJobAnalyzer(Protocol):
    def analyze(self, description: str) -> Optional[Dict[str, Any]]:
        """Analyzes a job description and returns match metrics."""
        ...

class IJobScraper(Protocol):
    def search_jobs(self, site: str, query: str, location: str, time_filter: str = "r259200", offset: int = 0):
        """Internal search logic."""
        ...

    def scan_search_results(self, site: str, limit: int, callback_fn: Any, monitor: Any = None):
        """Scans and triggers callbacks."""
        ...
    
    def close(self):
        """Clean up resources."""
        ...

class IJobRepository(Protocol):
    def save(self, job: Job) -> Job:
        """Persists a job entity."""
        ...
    
    def get_by_url(self, url: str) -> Optional[Job]:
        """Retrieves a job by its unique URL."""
        ...

class IMonitor(Protocol):
    def log(self, message: str):
        """Logs a message to the dashboard/console."""
        ...
    
    def update(self, **kwargs):
        """Updates real-time statistics (matches, processed, etc.)."""
        ...
        
    def add_match(self, job_data: Dict[str, Any], score: int):
        """Record a successful match."""
        ...

class ITracer(Protocol):
    def start_span(self, name: str, parent_id: Optional[str] = None, attributes: Optional[Dict[str, Any]] = None) -> str:
        """Starts a new trace span and returns its ID."""
        ...
        
    def end_span(self, span_id: str, status: str = "OK", exception: Optional[str] = None):
        """Ends a span and records results."""
        ...
        
    def update_span_attributes(self, span_id: str, attributes: Dict[str, Any]):
        """Adds or updates attributes of an existing span."""
        ...
