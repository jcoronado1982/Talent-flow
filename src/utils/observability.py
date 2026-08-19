import functools
import traceback
import os
from typing import Any, Callable, Optional
from contextvars import ContextVar
from src.infrastructure.storage.sqlite_tracer import SQLiteTracer

# Context variable to store the current span_id for the thread/async context
_current_span_id: ContextVar[Optional[str]] = ContextVar("current_span_id", default=None)

# Singleton or factory for the tracer
_tracer = SQLiteTracer()

def observed(func: Callable) -> Callable:
    """
    Decorator to automatically trace a Use Case execution.
    Captures timing, status, and exceptions.
    """
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        class_name = ""
        if args and hasattr(args[0], "__class__"):
            class_name = args[0].__class__.__name__
        
        span_name = f"{class_name}.{func.__name__}" if class_name else func.__name__
        
        attributes = {
            "pid": os.getpid(),
            "args_count": len(args),
            "kwargs_keys": list(kwargs.keys())
        }
        
        span_id = _tracer.start_span(span_name, attributes=attributes)
        token = _current_span_id.set(span_id)
        
        try:
            result = func(*args, **kwargs)
            _tracer.end_span(span_id, status="OK")
            return result
        except Exception as e:
            error_msg = traceback.format_exc()
            _tracer.end_span(span_id, status="ERROR", exception=error_msg)
            raise e
        finally:
            _current_span_id.reset(token)
            
    return wrapper

def get_current_span_id() -> Optional[str]:
    return _current_span_id.get()

def record_decision(attributes: dict):
    """Utility to record an AI decision in the current span."""
    span_id = get_current_span_id()
    if span_id:
        _tracer.update_span_attributes(span_id, attributes)

def get_tracer():
    return _tracer
