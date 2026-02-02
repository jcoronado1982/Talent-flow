import sqlite3
import json
import os
import time
import functools
from src.config.settings import Settings
from src.domain.models import Job, ApplicationStatus

def retry_on_lock(func):
    """
    Decorator to retry database operations when locked.
    Banking-grade resilience: Don't crash, queue and retry.
    """
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        retries = 5
        for i in range(retries):
            try:
                return func(*args, **kwargs)
            except sqlite3.OperationalError as e:
                # If database is locked, wait and retry
                if "locked" in str(e).lower():
                    wait = (i + 1) * 0.2 # 0.2s, 0.4s, 0.6s...
                    print(f"   [DB] 🔒 Database locked. Retrying in {wait:.1f}s ({i+1}/{retries})...")
                    time.sleep(wait)
                else:
                    raise e
            except Exception as e:
                # If it's another error, we might still want to retry if it's transient, 
                # but for now let's only catch locks or specific OS errors.
                # Actually, raising other errors is safer to not hide bugs.
                raise e
        # If we exhausted retries:
        raise sqlite3.OperationalError("Database locked after multiple retries")
    return wrapper

def get_connection():
    conn = sqlite3.connect(Settings.DB_PATH, timeout=20.0) # Increase native timeout
    conn.row_factory = sqlite3.Row
    # Enable Write-Ahead Logging for better concurrency
    conn.execute('PRAGMA journal_mode=WAL;')
    conn.execute('PRAGMA synchronous=NORMAL;')
    return conn

def init_db():
    conn = get_connection()
    c = conn.cursor()
    
    # Jobs Table
    c.execute('''
        CREATE TABLE IF NOT EXISTS jobs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            url TEXT UNIQUE,
            company TEXT,
            role TEXT,
            location TEXT,
            work_mode TEXT,
            date_posted TEXT,
            source TEXT,
            requirements TEXT,
            match_score INTEGER,
            priority_score INTEGER,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            status TEXT DEFAULT 'Pending',
            applied_resume TEXT,
            applied_salary TEXT,
            applied_currency TEXT,
            error_log TEXT,
            raw_analysis TEXT,
            external_link TEXT,
            skills TEXT
        )
    ''')
    
    # Simple Migration Check (handled in CREATE TABLE now)
    try:
        # These are now in the CREATE TABLE above, but kept here for existing DBs
        pass
    except: pass 
    try:
        c.execute("ALTER TABLE jobs ADD COLUMN applied_salary TEXT")
    except: pass
    try:
        c.execute("ALTER TABLE jobs ADD COLUMN applied_currency TEXT")
    except: pass
    try:
        c.execute("ALTER TABLE jobs ADD COLUMN audit_trail TEXT")
    except: pass
    try:
        c.execute("ALTER TABLE jobs ADD COLUMN updated_at DATETIME")
    except: pass
    try:
        c.execute("ALTER TABLE jobs ADD COLUMN skills TEXT")
    except: pass

    conn.commit()
    conn.close()
    print(f"   [DB] Database initialized at {Settings.DB_PATH} (WAL Mode Enabled)")

@retry_on_lock
def save_job(job_data: dict) -> bool:
    """Upserts a job into the database. Accepts dict or Job model can be adapted."""
    conn = get_connection()
    c = conn.cursor()
    
    try:
        # Extract analysis data safely
        analysis = job_data.get('analysis', {})
        
        # Determine raw_analysis value: NULL if empty, else JSON string
        raw_analysis_val = json.dumps(analysis) if analysis and analysis.get("match_percentage") is not None else None
        
        # ... (Prepare requirements omitted for brevity if unchanged, but need to be careful with replace)
        reqs = job_data.get('raw_requirements') or job_data.get('requirements')
        if reqs: reqs = reqs[:5000]
        else: reqs = None 
        
        import datetime
        now_local = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')

        # Check if URL exists before
        c.execute("SELECT id FROM jobs WHERE url = ?", (job_data['url'],))
        exists = c.fetchone()
        
        c.execute('''
            INSERT INTO jobs (
                url, company, role, location, work_mode, date_posted, source, 
                requirements, match_score, priority_score, raw_analysis, created_at, updated_at, skills
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(url) DO UPDATE SET
                match_score = CASE 
                    WHEN excluded.raw_analysis IS NOT NULL THEN excluded.match_score 
                    ELSE jobs.match_score 
                END,
                priority_score = CASE 
                    WHEN excluded.raw_analysis IS NOT NULL THEN excluded.priority_score 
                    ELSE jobs.priority_score 
                END,
                role = excluded.role,
                status = CASE WHEN status='Failed' THEN 'Pending' ELSE status END,
                raw_analysis = COALESCE(excluded.raw_analysis, jobs.raw_analysis),
                requirements = COALESCE(excluded.requirements, jobs.requirements),
                updated_at = excluded.updated_at,
                source = CASE 
                    WHEN jobs.source LIKE '%' || excluded.source || '%' THEN jobs.source 
                    ELSE jobs.source || ' | ' || excluded.source 
                END,
                skills = COALESCE(excluded.skills, jobs.skills)
        ''', (
            job_data['url'],
            job_data.get('company', 'Unknown'),
            job_data.get('role', 'Unknown'),
            job_data.get('location', 'Unknown'),
            job_data.get('work_mode', 'Unknown'),
            job_data.get('date', 'Unknown'),
            job_data.get('source', 'Unknown'),
            reqs,
            int(analysis.get('match_percentage', 0)) if analysis else 0,
            int(analysis.get('priority_score', 0)) if analysis else 0,
            raw_analysis_val,
            now_local,
            now_local,
            job_data.get('skills')
        ))
        conn.commit()
        return "INSERTED" if not exists else "DUPLICATE"
    except Exception as e:
        print(f"   [DB] Error saving job: {e}")
        return "ERROR"
    finally:
        conn.close()

@retry_on_lock
def recover_crashed_jobs(timeout_minutes=5):
    """
    Finds jobs that were stuck in 'Processing' state for TOO LONG (default 5 mins)
    and resets them to 'Pending'. This avoids killing active workers 
    while recovering from actual crashes.
    """
    conn = get_connection()
    c = conn.cursor()
    
    try:
        # Only recover if updated_at is older than N minutes
        # SQLite uses UTC usually or local depending on how datetime('now') was called
        # Our updated_at is usually current local time string. 
        # Better use: datetime('now', '-5 minutes') if stored as ISO, 
        # but let's be safe with a generic SQL approach
        
        c.execute('''
            SELECT id, company 
            FROM jobs 
            WHERE status = 'Processing' 
            AND updated_at < datetime('now', 'localtime', ?)
        ''', (f'-{timeout_minutes} minutes',))
        
        stuck_jobs = c.fetchall()
        
        if stuck_jobs:
            print(f"   [DB] Found {len(stuck_jobs)} STUCK jobs. Recovering...")
            
            import datetime
            timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            error_msg = f"[{timestamp}] ⚠️ Process timeout/crash. Recovered."
            
            for job in stuck_jobs:
                jid = job['id']
                c.execute('''
                    UPDATE jobs 
                    SET status = 'Pending', 
                        updated_at = ?,
                        error_log = COALESCE(error_log, '') || '\n' || ? 
                    WHERE id = ?
                ''', (timestamp, error_msg, jid))
            
            conn.commit()
            print(f"   [DB] Recovered {len(stuck_jobs)} jobs.")
            
    except Exception as e:
        print(f"   [DB] Error recovering jobs: {e}")
    finally:
        conn.close()

@retry_on_lock
def get_pending_jobs(limit=10) -> list[dict]:
    conn = get_connection()
    c = conn.cursor()
    
    query = '''
        SELECT * FROM jobs 
        WHERE (raw_analysis IS NULL 
        OR raw_analysis = ''
        OR raw_analysis = 'null')
        AND status != 'Failed'
        AND status != 'Processing'
        ORDER BY priority_score DESC, match_score DESC
        LIMIT ?
    '''
    c.execute(query, (limit,))
    rows = c.fetchall()
    conn.close()
    return [dict(row) for row in rows]

@retry_on_lock
def get_jobs_to_apply(limit=10) -> list[dict]:
    """
    Gets jobs with status 'Matched' that are ready to be applied to.
    This is for the APPLY bot, not the analysis/search bot.
    """
    conn = get_connection()
    c = conn.cursor()
    
    query = '''
        SELECT * FROM jobs 
        WHERE status = 'Matched'
        ORDER BY match_score DESC, priority_score DESC
        LIMIT ?
    '''
    c.execute(query, (limit,))
    rows = c.fetchall()
    conn.close()
    return [dict(row) for row in rows]

@retry_on_lock
def update_job_status(job_id: int, status: str, resume=None, error=None, external_link=None, salary=None, currency=None):
    conn = get_connection()
    c = conn.cursor()
    
    import datetime
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    # 1. Prepare Audit Entry
    audit_msg = f"[{timestamp}] Status: {status}"
    if error: audit_msg += f" | Error: {str(error)[:200]}"
    
    updated_fields = "status = ?, updated_at = ?, audit_trail = COALESCE(audit_trail, '') || ? || '\n'"
    params = [status, timestamp, audit_msg]
    
    if resume:
        updated_fields += ", applied_resume = ?"
        params.append(resume)

    if external_link:
        updated_fields += ", external_link = ?"
        params.append(external_link)

    if salary:
        updated_fields += ", applied_salary = ?"
        params.append(salary)
    
    if currency:
        updated_fields += ", applied_currency = ?"
        params.append(currency)
        
    if error:
        # Append to existing log
        updated_fields += ", error_log = COALESCE(error_log, '') || '\n' || ?"
        params.append(f"[{timestamp}] {str(error)}")
        
    params.append(job_id)
    
    c.execute(f'''
        UPDATE jobs 
        SET {updated_fields}
        WHERE id = ?
    ''', params)
    
    conn.commit()
    conn.close()

def get_dashboard_stats():
    conn = get_connection()
    c = conn.cursor()
    
    stats = {}
    
    # Counts
    c.execute("SELECT COUNT(*) FROM jobs")
    stats['total_found'] = c.fetchone()[0]
    
    c.execute("SELECT COUNT(*) FROM jobs WHERE match_score >= 40")
    stats['total_matches'] = c.fetchone()[0]
    
    c.execute("SELECT status, COUNT(*) FROM jobs GROUP BY status")
    status_counts = dict(c.fetchall())
    stats['status_breakdown'] = status_counts
    
    # Recent Matches
    c.execute('''
        SELECT id, company, role, location, work_mode, match_score, date_posted as date, created_at 
        FROM jobs 
        WHERE match_score >= 40 
        ORDER BY created_at DESC 
        LIMIT 5
    ''')
    stats['recent_matches'] = [dict(row) for row in c.fetchall()]
    
    conn.close()
    return stats

def reconcile_dashboard_stats():
    """Banking reconciliation: Hard recount from DB to ensure Dashboard 100% matches truth."""
    return get_dashboard_stats()

def get_all_jobs():
    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT * FROM jobs ORDER BY created_at DESC")
    rows = c.fetchall()
    conn.close()
    return [dict(row) for row in rows]

def clear_jobs():
    conn = get_connection()
    c = conn.cursor()
    c.execute("DELETE FROM jobs")
    c.execute("DELETE FROM sqlite_sequence WHERE name='jobs'") # Reset ID 
    conn.commit()
    conn.close()
    print("   [DB] All jobs cleared from database.")

@retry_on_lock
def get_pending_job_count() -> int:
    """Returns the total number of jobs waiting to be (or currently being) processed."""
    conn = get_connection()
    c = conn.cursor()
    # Count both Pending and Processing to ensure manager waits for EVERY job during stop
    c.execute('''
        SELECT COUNT(*) FROM jobs 
        WHERE (status = 'Pending' OR status = 'Processing')
        AND (raw_analysis IS NULL OR raw_analysis = '' OR raw_analysis = 'null')
    ''')
    count = c.fetchone()[0]
    conn.close()
    return count

@retry_on_lock
def get_next_pollable_job() -> dict:
    """
    Atomically polls and RESERVES the next available job using SQLite 3.35+ RETURNING clause.
    This prevents race conditions between parallel workers.
    """
    conn = get_connection()
    c = conn.cursor()
    
    try:
        # ATOMIC CLAIM: Find Pending -> Update to Processing -> Return it
        # This is the "Queue Pop" operation
        c.execute('''
            UPDATE jobs 
            SET status = 'Processing', updated_at = datetime('now', 'localtime')
            WHERE id = (
                SELECT id 
                FROM jobs 
                WHERE status = 'Pending' 
                AND (raw_analysis IS NULL OR raw_analysis = '' OR raw_analysis = 'null')
                ORDER BY priority_score DESC, id ASC 
                LIMIT 1
            )
            RETURNING *
        ''')
        
        row = c.fetchone()
        conn.commit()
        
        if row:
            return dict(row)
        return None
        
    except sqlite3.OperationalError:
        # Fallback for older SQLite versions if RETURNING is not supported (just in case)
        # But we verified 3.37.2 so it should work.
        conn.rollback()
        return None
    except Exception as e:
        print(f"   [DB] Error polling job: {e}")
        conn.rollback()
        return None
    finally:
        conn.close()
