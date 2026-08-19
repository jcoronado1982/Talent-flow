import uuid
import json
import time
from typing import Optional, Dict, Any
from src.domain.interfaces import ITracer
from src.services.storage.database import get_connection, retry_on_lock

class SQLiteTracer(ITracer):
    """
    Local implementation of ITracer that saves spans to SQLite.
    Adheres to Clean Architecture while providing local observability.
    """
    
    def __init__(self):
        # We don't hold a connection here to avoid threading issues in multiprocess
        pass

    @retry_on_lock
    def start_span(self, name: str, parent_id: Optional[str] = None, attributes: Optional[Dict[str, Any]] = None) -> str:
        span_id = str(uuid.uuid4())
        trace_id = parent_id if parent_id else str(uuid.uuid4())
        
        conn = get_connection()
        c = conn.cursor()
        try:
            c.execute('''
                INSERT INTO traces (span_id, trace_id, parent_id, name, start_time, status, attributes)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            ''', (
                span_id, 
                trace_id, 
                parent_id, 
                name, 
                time.time(), 
                "RUNNING", 
                json.dumps(attributes or {})
            ))
            conn.commit()
            return span_id
        finally:
            conn.close()

    @retry_on_lock
    def end_span(self, span_id: str, status: str = "OK", exception: Optional[str] = None):
        conn = get_connection()
        c = conn.cursor()
        try:
            c.execute('''
                UPDATE traces 
                SET end_time = ?, status = ?, exception = ?
                WHERE span_id = ?
            ''', (time.time(), status, exception, span_id))
            conn.commit()
        finally:
            conn.close()

    @retry_on_lock
    def update_span_attributes(self, span_id: str, attributes: Dict[str, Any]):
        conn = get_connection()
        c = conn.cursor()
        try:
            # First get existing attributes
            c.execute("SELECT attributes FROM traces WHERE span_id = ?", (span_id,))
            row = c.fetchone()
            existing = {}
            if row and row[0]:
                existing = json.loads(row[0])
            
            existing.update(attributes)
            
            c.execute('''
                UPDATE traces SET attributes = ? WHERE span_id = ?
            ''', (json.dumps(existing), span_id))
            conn.commit()
        finally:
            conn.close()

    def record_event(self, span_id: str, name: str, attributes: Optional[Dict[str, Any]] = None):
        # Simple implementation could add a sub-span or a log entry
        # For now, let's keep it simple
        pass
