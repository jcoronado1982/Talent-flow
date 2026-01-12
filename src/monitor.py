import json
import os
import time

class SearchMonitor:
    def __init__(self, status_file="dashboard/status.json"):
        self.status_file = status_file
        # Ensure directory exists
        os.makedirs(os.path.dirname(self.status_file), exist_ok=True)
        
        self.state = {
            "total_combinations": 0,
            "current_combination_index": 0,
            "current_role": "Initializing...",
            "current_location": "...",
            "jobs_in_current_batch": 0,
            "current_job_index": 0,
            "total_matches": 0,
            "recent_matches": [],
            "logs": [],
            "status": "Ready",
            "last_updated": 0
        }
        self.save()

    def update(self, **kwargs):
        """Update arbitrary state keys."""
        for k, v in kwargs.items():
            self.state[k] = v
        self.save()

    def log(self, message):
        """Add a log message."""
        timestamp = time.strftime("%H:%M:%S")
        self.state["logs"].insert(0, f"[{timestamp}] {message}")
        self.state["logs"] = self.state["logs"][:20] # Keep last 20
        self.save()

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
        self.state["recent_matches"].insert(0, match_entry)
        self.state["recent_matches"] = self.state["recent_matches"][:10]
        self.state["total_matches"] += 1
        self.save()

    def save(self):
        self.state["last_updated"] = time.time()
        try:
            with open(self.status_file, "w") as f:
                json.dump(self.state, f, indent=2)
        except Exception as e:
            print(f"Monitor Save Error: {e}")
