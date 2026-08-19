import json
import os
import time
import threading

class SearchMonitor:
    def __init__(self, status_file="dashboard/status.json"):
        self.status_file = status_file
        # Ensure directory exists
        os.makedirs(os.path.dirname(self.status_file), exist_ok=True)
        self.lock = threading.Lock()
        
        self.state = {
            "total_combinations": 0,
            "current_combination_index": 0,
            "current_role": "Initializing...",
            "current_location": "...",
            "jobs_in_current_batch": 0,
            "current_job_index": 0,
            "processing_count": 0,
            "total_matches": 0,
            "recent_matches": [],
            "logs": [],
            "status": "Ready",
            "target_resume": "-",
            "actual_resume": "-",
            "diagnostics": {
                "active": False,
                "schema": [],
                "answers": {},
                "last_event": ""
            },
            "last_updated": 0
        }
        
        # Load existing state if available to preserve "Running" status or logs
        if os.path.exists(self.status_file):
            try:
                with open(self.status_file, "r") as f:
                    data = json.load(f)
                    # Preserve all existing keys if they exist in the file
                    # This ensures matches and logs are kept across restarts
                    for key in self.state.keys():
                        if key in data:
                            self.state[key] = data[key]
            except Exception as e:
                print(f"Monitor Load Warning: {e}")
        
        self.save()

    def update(self, **kwargs):
        """Update arbitrary state keys."""
        with self.lock:
            for k, v in kwargs.items():
                self.state[k] = v
            self._save_unsafe()

    def log(self, message):
        """Add a log message."""
        timestamp = time.strftime("%H:%M:%S")
        full_timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
        
        # 1. Console Output
        print(f"[{timestamp}] {message}") 
        
        # 2. Persistent File Output
        log_file = "dashboard/activity.log"
        try:
            with open(log_file, "a", encoding="utf-8") as f:
                f.write(f"[{full_timestamp}] {message}\n")
        except Exception as e:
            print(f"Monitor Log File Error: {e}")

        # 3. UI Buffer (Last 20)
        with self.lock:
            self.state["logs"].insert(0, f"[{timestamp}] {message}")
            self.state["logs"] = self.state["logs"][:20]
            self._save_unsafe()

    def add_match(self, job_data, score):
        """Register a found match."""
        match_entry = {
            "role": job_data.get("role", "Unknown"), 
            "company": job_data.get("company", "Unknown"),
            "location": job_data.get("location", "Unknown"),
            "score": score,
            "url": job_data.get("url", "#"),
            "work_mode": job_data.get("work_mode", "Unknown"),
            "date": job_data.get("date", "Unknown")
        }
        with self.lock:
            self.state["recent_matches"].insert(0, match_entry)
            self.state["recent_matches"] = self.state["recent_matches"][:10]
            self.state["total_matches"] += 1
            self._save_unsafe()

    def push_inspection(self, schema=None, answers=None, traffic_in=None, traffic_out=None, event_name="Update"):
        """Pushes real-time form diagnostics and raw traffic to the UI.
        If a parameter is None, the previous value is preserved.
        """
        with self.lock:
            diag = self.state.get("diagnostics", {})
            self.state["diagnostics"] = {
                "active": True,
                "schema": schema if schema is not None else diag.get("schema", []),
                "answers": answers if answers is not None else diag.get("answers", {}),
                "traffic_in": traffic_in if traffic_in is not None else diag.get("traffic_in"),
                "traffic_out": traffic_out if traffic_out is not None else diag.get("traffic_out"),
                "last_event": event_name,
                "timestamp": time.time()
            }
            # Force save even if not master for diagnostics (special case)
            self._save_unsafe(force=True)

    def save(self):
        with self.lock:
            self._save_unsafe()

    def _save_unsafe(self, force=False):
        # AUTHORITY CHECK: Only the Master process is allowed to write to disk.
        # Subordinates can keep state in memory for their own logic if needed,
        # but they must NOT touch the shared status.json.
        if not force and os.environ.get("MONITOR_MASTER") != "true":
            return
            
        self.state["last_updated"] = time.time()
        try:
            with open(self.status_file, "w") as f:
                json.dump(self.state, f, indent=2)
        except Exception as e:
            print(f"Monitor Save Error: {e}")
