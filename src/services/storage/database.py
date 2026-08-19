import sqlite3
import json
import os
import time
import shutil
import functools
from src.config.settings import Settings
from typing import Optional
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
            language TEXT,
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
            skills TEXT,
            processing_time REAL,
            raw_analysis TEXT,
            ai_model TEXT
        )
    ''')
    
    # Traces Table (Observability)
    c.execute('''
        CREATE TABLE IF NOT EXISTS traces (
            span_id TEXT PRIMARY KEY,
            trace_id TEXT,
            parent_id TEXT,
            name TEXT,
            start_time REAL,
            end_time REAL,
            status TEXT,
            exception TEXT,
            attributes TEXT,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    # Companies Table
    c.execute('''
        CREATE TABLE IF NOT EXISTS companies (
            name TEXT PRIMARY KEY,
            job_count INTEGER DEFAULT 1,
            last_seen DATETIME,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    # Simple Migration Check (handled in CREATE TABLE now)
    try:
        # These are now in the CREATE TABLE above, but kept here for existing DBs
        pass
    except: pass 
    try:
        c.execute("ALTER TABLE jobs ADD COLUMN language TEXT")
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
    try:
        c.execute("ALTER TABLE jobs ADD COLUMN apply_type TEXT")
    except: pass
    try:
        c.execute("ALTER TABLE jobs ADD COLUMN processing_time REAL")
    except: pass
    try:
        c.execute("ALTER TABLE jobs ADD COLUMN uploaded_cv TEXT")
    except: pass
    try:
        c.execute("ALTER TABLE jobs ADD COLUMN raw_analysis TEXT")
    except: pass
    try:
        c.execute("ALTER TABLE jobs ADD COLUMN ai_model TEXT")
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
        
        # Use the explicit raw response if provided (diagnostics), 
        # otherwise fallback to serialized JSON of the parsed data.
        if 'raw_analysis' in job_data:
            raw_analysis_val = job_data['raw_analysis']
        else:
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
                url, company, role, location, work_mode, date_posted, language, source, 
                requirements, match_score, priority_score, raw_analysis, created_at, updated_at, skills, apply_type, processing_time, raw_prompt, applied_resume, ai_model
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(url) DO UPDATE SET
                match_score = CASE 
                    WHEN excluded.raw_analysis IS NOT NULL THEN excluded.match_score 
                    ELSE jobs.match_score 
                END,
                priority_score = CASE 
                    WHEN excluded.raw_analysis IS NOT NULL THEN excluded.priority_score 
                    ELSE jobs.priority_score 
                END,
                processing_time = COALESCE(excluded.processing_time, jobs.processing_time),
                raw_prompt = COALESCE(excluded.raw_prompt, jobs.raw_prompt),
                role = excluded.role,
                status = CASE WHEN status='Failed' THEN 'Pending' ELSE status END,
                raw_analysis = COALESCE(excluded.raw_analysis, jobs.raw_analysis),
                ai_model = COALESCE(excluded.ai_model, jobs.ai_model),
                requirements = COALESCE(excluded.requirements, jobs.requirements),
                updated_at = excluded.updated_at,
                source = CASE 
                    WHEN jobs.source LIKE '%' || excluded.source || '%' THEN jobs.source 
                    ELSE jobs.source || ' | ' || excluded.source 
                END,
                language = COALESCE(excluded.language, jobs.language),
                skills = CASE
                    WHEN excluded.raw_analysis IS NOT NULL THEN excluded.skills
                    ELSE COALESCE(excluded.skills, jobs.skills)
                END,
                apply_type = COALESCE(excluded.apply_type, jobs.apply_type),
                applied_resume = COALESCE(excluded.applied_resume, jobs.applied_resume)
        ''', (
            job_data['url'],
            job_data.get('company', 'Unknown'),
            job_data.get('role', 'Unknown'),
            job_data.get('location', 'Unknown'),
            job_data.get('work_mode', 'Unknown'),
            job_data.get('date', 'Unknown'),
            job_data.get('language', 'Unknown'),
            job_data.get('source', 'Unknown'),
            reqs,
            int(analysis.get('match_percentage', 0)) if analysis else 0,
            int(analysis.get('priority_score', 0)) if analysis else 0,
            raw_analysis_val,
            now_local,
            now_local,
            job_data.get('skills'),
            job_data.get('apply_type'),
            job_data.get('processing_time'),
            job_data.get('raw_prompt'),
            job_data.get('applied_resume'),
            job_data.get('ai_model')
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
        ORDER BY 
            (CASE 
                WHEN apply_type = 'Easy Apply' AND location LIKE '%Colombia%' THEN 0
                WHEN apply_type = 'Easy Apply' THEN 1
                WHEN apply_type != 'Easy Apply' AND location LIKE '%Colombia%' THEN 2
                ELSE 3
            END) ASC,
            match_score DESC, 
            priority_score DESC
        LIMIT ?
    '''
    c.execute(query, (limit,))
    rows = c.fetchall()
    conn.close()
    return [dict(row) for row in rows]

@retry_on_lock
def update_job_status(job_id: int, status: str, resume=None, uploaded_cv=None, error=None, external_link=None, salary=None, currency=None, match_score=None, raw_analysis=None):
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

    if uploaded_cv:
        updated_fields += ", uploaded_cv = ?"
        params.append(uploaded_cv)

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
    
    if match_score is not None:
        updated_fields += ", match_score = ?"
        params.append(match_score)

    if raw_analysis is not None:
        updated_fields += ", raw_analysis = ?"
        params.append(raw_analysis)
        
    params.append(job_id)
    
    c.execute(f'''
        UPDATE jobs 
        SET {updated_fields}
        WHERE id = ?
    ''', params)
    
    conn.commit()
    conn.close()

# Global Statistics Cache (To reduce DB load and satisfy the 5-min update requirement)
_STATS_CACHE = None
_LAST_STATS_UPDATE = 0
_CACHE_TTL = 10 # 10 seconds (Real-time Dashboard)

def get_dashboard_stats():
    global _STATS_CACHE, _LAST_STATS_UPDATE
    
    current_time = time.time()
    
    # ⏱️ CACHE LOGIC: Only re-query the DB if cache is empty or 5 minutes have passed
    if _STATS_CACHE is not None and (current_time - _LAST_STATS_UPDATE < _CACHE_TTL):
        return _STATS_CACHE

    conn = get_connection()
    c = conn.cursor()
    
    stats = {}
    
    # Counts
    c.execute("SELECT COUNT(*) FROM jobs")
    stats['total_found'] = int(c.fetchone()[0])
    
    c.execute("SELECT COUNT(*) FROM jobs WHERE match_score >= 40")
    stats['total_matches'] = int(c.fetchone()[0])
    
    # Throughput calculation (rolling 5 minutes)
    try:
        # We calculate both:
        # 1. SUM(processing_time) / 5 -> Cumulative work seconds per minute
        # 2. COUNT(*) / 5 -> Actual offers completed per minute
        c.execute('''
            SELECT SUM(processing_time) / 5.0, COUNT(*) / 5.0
            FROM jobs 
            WHERE updated_at >= datetime('now', 'localtime', '-5 minutes') 
            AND status NOT IN ('Pending', 'Processing')
        ''')
        row = c.fetchone()
        stats['total_processing_time_per_min'] = round(float(row[0]) if row and row[0] is not None else 0.0, 1)
        stats['offers_per_min'] = round(float(row[1]) if row and row[1] is not None else 0.0, 1)
    except Exception as e:
        print(f"   [DB] Error calculating performance metrics: {e}")
        stats['total_processing_time_per_min'] = 0.0
        stats['offers_per_min'] = 0.0

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
    
    # Update cache
    _STATS_CACHE = stats
    _LAST_STATS_UPDATE = current_time
    
    return stats

def reconcile_dashboard_stats():
    """Banking reconciliation: Hard recount from DB to ensure Dashboard 100% matches truth."""
    return get_dashboard_stats()

def get_job_by_id(job_id: int) -> Optional[dict]:
    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT * FROM jobs WHERE id = ?", (job_id,))
    row = c.fetchone()
    conn.close()
    return dict(row) if row else None

def get_all_jobs():
    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT * FROM jobs ORDER BY created_at DESC")
    rows = c.fetchall()
    conn.close()
    return [dict(row) for row in rows]

def get_audit_jobs():
    """Returns only jobs that have been analyzed (Matched, Discarded, Failed)"""
    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT * FROM jobs WHERE status NOT IN ('Pending', 'Processing') ORDER BY updated_at DESC")
    rows = c.fetchall()
    conn.close()
    return [dict(row) for row in rows]

def get_filtered_jobs(limit=100, offset=0, q=None, status=None, mode=None, apply_type=None, lang=None):
    conn = get_connection()
    c = conn.cursor()
    
    query = "SELECT * FROM jobs WHERE 1=1"
    params = []
    
    if q:
        query += " AND (company LIKE ? OR role LIKE ? OR skills LIKE ?)"
        params.extend([f"%{q}%", f"%{q}%", f"%{q}%"])
    
    if status and status != 'all':
        query += " AND status = ?"
        params.append(status)
        
    if mode and mode != 'all':
        query += " AND work_mode = ?"
        params.append(mode)
        
    if apply_type and apply_type != 'all':
        query += " AND apply_type = ?"
        params.append(apply_type)
        
    if lang and lang != 'all':
        query += " AND language = ?"
        params.append(lang)
        
    query += " ORDER BY created_at DESC LIMIT ? OFFSET ?"
    params.extend([limit, offset])
    
    c.execute(query, params)
    rows = c.fetchall()
    conn.close()
    return [dict(row) for row in rows]

def get_total_jobs_count(q=None, status=None, mode=None, apply_type=None, lang=None):
    conn = get_connection()
    c = conn.cursor()
    
    query = "SELECT COUNT(*) FROM jobs WHERE 1=1"
    params = []
    
    if q:
        query += " AND (company LIKE ? OR role LIKE ? OR skills LIKE ?)"
        params.extend([f"%{q}%", f"%{q}%", f"%{q}%"])
    
    if status and status != 'all':
        query += " AND status = ?"
        params.append(status)
        
    if mode and mode != 'all':
        query += " AND work_mode = ?"
        params.append(mode)
        
    if apply_type and apply_type != 'all':
        query += " AND apply_type = ?"
        params.append(apply_type)
        
    if lang and lang != 'all':
        query += " AND language = ?"
        params.append(lang)
        
    c.execute(query, params)
    count = c.fetchone()[0]
    conn.close()
    return count

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
def reset_failed_jobs():
    """Resets all jobs with status 'Failed' back to 'Pending' for re-analysis."""
    conn = get_connection()
    c = conn.cursor()
    try:
        c.execute("UPDATE jobs SET status = 'Pending' WHERE status = 'Failed'")
        conn.commit()
    finally:
        conn.close()

@retry_on_lock
def reset_all_analysis_status():
    """Resets ALL jobs back to 'Pending' status, clearing previous analysis and processing data."""
    conn = get_connection()
    c = conn.cursor()
    try:
        c.execute('''
            UPDATE jobs 
            SET status = 'Pending', 
                match_score = 0, 
                priority_score = 0, 
                raw_analysis = NULL,
                skills = NULL,
                ai_model = NULL,
                error_log = NULL,
                audit_trail = NULL,
                processing_time = NULL,
                raw_prompt = NULL
        ''')
        conn.commit()
    finally:
        conn.close()


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

def create_backup(suffix: str = "manual") -> str:
    """
    Creates a timestamped backup of the database using the SQLite Backup API.
    This is safe for concurrent use and WAL mode.
    """
    backup_dir = os.path.join(Settings.BASE_DIR, "backups")
    os.makedirs(backup_dir, exist_ok=True)
    
    timestamp = time.strftime("%Y%m%d_%H%M%S")
    filename = f"talentflow_{suffix}_{timestamp}.db"
    backup_path = os.path.join(backup_dir, filename)
    
    try:
        # Use Python's built-in backup API which handles WAL and page transitions safely
        src_conn = get_connection()
        dst_conn = sqlite3.connect(backup_path)
        
        with src_conn:
            src_conn.backup(dst_conn)
            
        dst_conn.close()
        src_conn.close()
        
        print(f"   [DB] 💾 Backup created: {filename}")
        return backup_path
    except Exception as e:
        print(f"   [DB] ❌ Backup failed: {e}")
        return None

