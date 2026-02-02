import os
import csv
import time
import threading
from datetime import datetime

class AuditLogger:
    _instance = None
    _lock = threading.Lock()
    
    def __new__(cls, *args, **kwargs):
        if not cls._instance:
            with cls._lock:
                if not cls._instance:
                    cls._instance = super(AuditLogger, cls).__new__(cls)
        return cls._instance

    def __init__(self, log_dir="dashboard", filename="audit.csv"):
        # Singleton init check
        if hasattr(self, "initialized"): return
        self.initialized = True
        
        self.log_path = os.path.join(log_dir, filename)
        os.makedirs(log_dir, exist_ok=True)
        
        # Initialize file with headers if not exists
        if not os.path.exists(self.log_path):
            with open(self.log_path, mode='w', newline='', encoding='utf-8') as f:
                writer = csv.writer(f)
                writer.writerow(["Timestamp", "Action", "Company", "Role", "Reason", "Details", "URL"])

    def log(self, action, company="Unknown", role="Unknown", reason="", details="", url=""):
        """
        Log an audit event.
        Actions: SEEN, SAVED, SKIPPED, ERROR
        """
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        # Sanitize text
        company = str(company).replace("\n", " ").strip()
        role = str(role).replace("\n", " ").strip()
        reason = str(reason).replace("\n", " ").strip()
        details = str(details).replace("\n", " ").strip()
        
        # Console output for immediate visibility (optional, maybe too noisy)
        # print(f"[AUDIT] {action}: {company} - {reason}")

        try:
            with self._lock:
                with open(self.log_path, mode='a', newline='', encoding='utf-8') as f:
                    writer = csv.writer(f)
                    writer.writerow([timestamp, action, company, role, reason, details, url])
        except Exception as e:
            print(f"FAILED TO WRITE AUDIT LOG: {e}")
