---
description: Reset the TalentFlow system to a zero-state baseline for fresh testing.
---

# 🧹 TalentFlow Clean Protocol

Whenever the user says "limpia", "reinicia todo", or "reset", follow these steps strictly to ensure a clean testing environment.

## 1. Terminate Live Processes
Aggressively kill any background TalentFlow or Dashboard processes to prevent database locks or double-execution.
// turbo
```bash
pkill -9 -f "src.main" || true
pkill -9 -f "processor" || true
pkill -9 -f "dashboard/main.py" || true
sleep 2
```

## 2. Restore Master Database
Discard the current `talentflow.db` and restore from the golden backup.
// turbo
```bash
rm -f talentflow.db talentflow.db-shm talentflow.db-wal
cp talentflow_backup.db talentflow.db
```

## 3. Schema Synchronization
Ensure the restored database has all current columns required by the application.
// turbo
```bash
sqlite3 talentflow.db "ALTER TABLE jobs ADD COLUMN processing_time REAL; ALTER TABLE jobs ADD COLUMN raw_prompt TEXT; ALTER TABLE jobs ADD COLUMN language TEXT;" || true
```

## 4. Reset to Zero State (Essential)
Reset all job entries to `Pending` and clear all AI-generated scores and metadata.
// turbo
```bash
sqlite3 talentflow.db "UPDATE jobs SET status = 'Pending', match_score = 0, priority_score = 0, raw_analysis = NULL, audit_trail = NULL, applied_resume = NULL, language = NULL, skills = '-'; DELETE FROM traces;"
```

## 5. Clear Activity Logs
Wipe all dashboard logs and independent activity logs.
// turbo
```bash
rm -f dashboard/*.log dashboard/audit.csv dashboard/status.json dashboard/activity.log
echo '{"status": "Ready", "logs": []}' > dashboard/status.json
```

---
**System is now Ready.**
