# ==============================================================================
# ⚠️ CRITICAL COMPONENT - DO NOT MODIFY WITHOUT EXPLICIT USER INSTRUCTION ⚠️
# ==============================================================================
# This file governs the AI analysis and matching logic.
# Any changes here can disrupt the scoring precision or the parallel pipeline.
# ==============================================================================
import time
import os
import threading
import traceback
from src.services.ai.client import JobAnalyzer
import src.services.storage.database as db
from src.config.settings import Settings

class FatalAIError(Exception):
    """Exception to signal that AI service is permanently unavailable (quota/auth)."""
    pass

def execute_job_analysis(job):
    """
    Standalone worker function for ProcessPoolExecutor.
    Must be top-level to be pickleable.
    """
    import os
    import time
    from src.services.storage import database as db
    from src.monitor import SearchMonitor
    from src.services.ai.client import JobAnalyzer
    from src.app.bots.search.processor import FatalAIError # Local import to avoid circular dependency issues if any
    from src.audit import AuditLogger
    audit = AuditLogger()

    _debug_log = "dashboard/processor_debug.log"
    job_id = job['id']
    company = job['company']
    description = job['requirements']
    job_tag = f"[Job {job_id}]"
    
    # Re-init monitor for this process
    monitor = SearchMonitor() 
    
    # Re-init Brain for this process
    api_key = os.environ.get("GEMINI_API_KEY")
    brain = JobAnalyzer(api_key=api_key)

    try:
        with open(_debug_log, "a") as f: f.write(f"[{time.strftime('%H:%M:%S')}] {job_tag} (PID {os.getpid()}) Processing {company}...\n")
    except: pass

    # Log start of transaction
    db.update_job_status(job_id, 'Processing')
    
    try:
        # Internal analyze logic duplicated/adapted for standalone
        # We can't call self._analyze_with_retry, so we implement retry loop here
        analysis = None
        retries = 3
        last_error = None
        
        date_posted = job.get('date_posted', 'Unknown')
        
        for attempt in range(retries):
             try:
                 wait_time = 5 * (attempt + 1)
                 if attempt > 0: time.sleep(wait_time)
                 
                 prompt = f"PUBLICATION DATE: {date_posted}\n\n{description}"
                 
                 # Analyze
                 analysis = brain.analyze(prompt)
                 
                 if analysis: break
                 
                 last_error = f"Analysis returned None on attempt {attempt+1}"
                 monitor.log(f"⚠️ {job_tag} Attempt {attempt+1} failed: {last_error}")
                 time.sleep(2)
                 
             except Exception as e:
                 last_error = str(e)
                 monitor.log(f"⚠️ {job_tag} Attempt {attempt+1} failed ({type(e).__name__})")
                 time.sleep(2)
        
        if analysis:
            try:
                match_score = int(float(analysis.get('match_percentage', 0)))
            except:
                match_score = 0

            
            job_update = dict(job)
            job_update['analysis'] = analysis
            job_update['skills'] = analysis.get('mandatory_skills', '-')
            
            # Smart Correction: Use AI detection as ultimate fallback for everything
            ai_mode = analysis.get('work_mode_detected')
            if ai_mode and ai_mode != 'Unknown':
                job_update['work_mode'] = ai_mode
            
            # Check for Junk in Location or Company
            junk_patterns = r"(applicant|promoted|hirer|solicitud|ago|hace|semana|mes|hour|minute|day|match|preferences|job type)"
            
            ai_location = analysis.get('location_detected')
            curr_loc = job_update.get('location', 'Unknown')
            if ai_location and (curr_loc == 'Unknown' or len(curr_loc) > 40 or re.search(junk_patterns, curr_loc, re.IGNORECASE)):
                job_update['location'] = ai_location

            ai_company = analysis.get('company_detected')
            curr_comp = job_update.get('company', 'Unknown')
            if ai_company and (curr_comp == 'Unknown' or "about the job" in curr_comp.lower() or re.search(junk_patterns, curr_comp, re.IGNORECASE)):
                job_update['company'] = ai_company

            ai_date = analysis.get('date_posted_detected')
            if ai_date and (job_update.get('date') == 'Unknown' or not job_update.get('date')):
                job_update['date'] = ai_date
            
            # Update status
            if match_score >= 30: 
                new_status = 'Matched'
            else: 
                new_status = 'Discarded'
            
            db.update_job_status(job_id, new_status)
            
            try:
                with open(_debug_log, "a") as f: f.write(f"[{time.strftime('%H:%M:%S')}] {job_tag} Finished. Status: {new_status} ({match_score}%)\n")
            except: pass

            if match_score >= 30:
                monitor.log(f"✅ MATCH: {company} ({match_score}%)")
                audit.log("MATCHED", company=company, role=job['role'], details=f"Score: {match_score}%", url=job['url'])
            else:
                audit.log("DISCARDED", company=company, role=job['role'], reason="Low Match Score", details=f"Score: {match_score}%", url=job['url'])
            
            return True
        else:
            monitor.log(f"❌ {job_tag} Error analizando: {company}")
            db.update_job_status(job_id, "Failed")
            audit.log("FAIL", company=company, role=job['role'], reason="Analysis Error", details="Returned None", url=job['url'])
            return False
            
    except Exception as e:
         monitor.log(f"❌ {job_tag} Panic Error: {e}")
         db.update_job_status(job_id, "Failed")
         return False

# Worker Function (Process Payload)
def execute_worker_lifecycle(api_key, results_queue):
    """
    Life of a Worker Process (Subordinary):
    1. Loop requesting jobs from DB.
    2. If job found -> Process it.
    3. REPORT ALL RESULTS to the results_queue (The Parent Boss).
    """
    import os
    import time
    from src.services.storage import database as db
    from src.services.ai.client import JobAnalyzer
    from src.audit import AuditLogger
    
    _debug_log = "dashboard/processor_debug.log"
    pid = os.getpid()
    
    # Init dependencies
    # NO MONITOR in worker - we report via queue to avoid race conditions
    brain = JobAnalyzer(api_key=api_key)
    audit = AuditLogger()
    
    idle_start_time = time.time()
    idle_timeout = 120 # 2 minutes for workers to release resources
    
    try:
        with open(_debug_log, "a") as f: f.write(f"[{time.strftime('%H:%M:%S')}] [Worker {pid}] Born and ready.\n")
    except: pass

    while True:
        # Graceful check inside loop
        stop_requested = os.path.exists(Settings.STOP_SIGNAL)
        if stop_requested:
            # If shutdown is requested, don't take any MORE jobs. 
            with open(_debug_log, "a") as f: f.write(f"[{time.strftime('%H:%M:%S')}] [Worker {pid}] Stopping (Graceful). No more jobs will be taken.\n")
            break
            
        # 1. Try to fetch a job claiming it atomically
        try:
            job = db.get_next_pollable_job() 
        except: job = None
        
        if job:
            # RESET IDLE TIMER
            idle_start_time = time.time()
            
            # 2. Process Job
            job_id = job['id']
            company = job['company']
            
            with open(_debug_log, "a") as f: f.write(f"[{time.strftime('%H:%M:%S')}] [Worker {pid}] -> Taking job [{company}] (ID: {job_id})\n")
            
            try:
                # Analyze
                prompt = f"PUBLICATION DATE: {job.get('date_posted', 'Unknown')}\n\n{job['requirements']}"
                analysis = brain.analyze(prompt)
                
                if analysis:
                    try:
                        match_score = int(float(analysis.get('match_percentage', 0)))
                    except:
                        match_score = 0

                    job_update = dict(job)
                    job_update['analysis'] = analysis
                    job_update['skills'] = analysis.get('mandatory_skills', '-')
                    
                    # Smart Correction
                    ai_mode = analysis.get('work_mode_detected')
                    if ai_mode and ai_mode != 'Unknown':
                        job_update['work_mode'] = ai_mode

                    db.save_job(job_update)
                    new_status = 'Matched' if match_score >= 30 else 'Discarded'
                    db.update_job_status(job_id, new_status)
                    
                    if match_score >= 30:
                        results_queue.put({
                            'type': 'match',
                            'job_data': job_update,
                            'score': match_score
                        })
                        results_queue.put({'type': 'log', 'message': f"✅ MATCH: {company} ({match_score}%)"})
                        audit.log("MATCHED", company=company, role=job['role'], details=f"Score: {match_score}%", url=job['url'])
                    else:
                        audit.log("DISCARDED", company=company, role=job['role'], reason="Low Match Score", details=f"Score: {match_score}%", url=job['url'])
                        
                    with open(_debug_log, "a") as f: f.write(f"[{time.strftime('%H:%M:%S')}] [Worker {pid}] -> Finished job (ID: {job_id})\n")
                else:
                    db.update_job_status(job_id, "Failed")
                    audit.log("FAIL", company=company, role=job['role'], reason="Analysis Failure", details="Empty JSON response", url=job['url'])
                    
            except Exception as e:
                 results_queue.put({'type': 'log', 'message': f"❌ [Worker {pid}] Error: {e}"})
                 db.update_job_status(job_id, "Failed")
                 
            # Continue picking jobs even if STOP_SIGNAL is on (finishing pendings)
            continue 
            
            # After processing a job, check if we should stop
            if os.path.exists(Settings.STOP_SIGNAL):
                 break
            
            time.sleep(1) # Small breath


class JobProcessor:
    def __init__(self, monitor):
        self.monitor = monitor
        self.api_key = os.environ.get("GEMINI_API_KEY") 
        self.max_concurrent_workers = 10 # Scaled up for Gemini 3 Flash (Cloud API)

    def process_continuous(self, stop_event, results_queue):
        """
        ORCHESTRATOR LOOP (The 'Boss' Parent Process).
        1. Manages a Queue where workers (children) report back.
        2. Updates the Monitor as the SOLE AUTHORITY.
        """
        import multiprocessing
        import time
        import threading
        
        self.monitor.log("🧠 [BOSS] Iniciando Jerarquía de Procesos (Manager + Workers Subordinados)...")
        
        _debug_log = "dashboard/processor_debug.log"
        active_processes = []
        
        def listener():
            """The Boss's ear: listens to worker reports and updates the dashboard."""
            while True:
                try:
                    # Get report from worker
                    report = results_queue.get(timeout=1)
                    if report is None: # Sentinel value to stop
                        break
                    
                    if report['type'] == 'match':
                        self.monitor.add_match(report['job_data'], report['score'])
                    elif report['type'] == 'log':
                        self.monitor.log(report['message'])
                    elif report['type'] == 'progress':
                        self.monitor.update(
                            current_job_index=report.get('current', 0),
                            jobs_in_current_batch=report.get('total', 0)
                        )
                except: 
                    # If we are waiting for workers and queue is empty, just loop
                    continue

        # Start Listener
        t_listener = threading.Thread(target=listener, name="BossListener", daemon=True)
        t_listener.start()

        # Write initial log
        with open(_debug_log, "a") as f: 
            f.write(f"[{time.strftime('%H:%M:%S')}] [Boss] Started. Max Workers: {self.max_concurrent_workers}\n")

        while not stop_event.is_set():
            # 0. Clean up any stuck jobs from previous runs
            try:
                db.recover_crashed_jobs()
            except: pass

            # 1. Clean up dead processes (Zombies/Finished Workers)
            active_processes = [p for p in active_processes if p.is_alive()]
            
            # 2. Check Workload
            try:
                pending_count = db.get_pending_job_count() 
                total_found = db.get_dashboard_stats().get('total_found', 0)
                
                # Boss update progress based on aggregate DB state
                # (Workers don't need to report progress individually, Boss sees all)
                stats = db.get_dashboard_stats()
                breakdown = stats.get('status_breakdown', {})
                processed = breakdown.get('Matched', 0) + breakdown.get('Discarded', 0)
                processing = breakdown.get('Processing', 0)
                
                self.monitor.update(
                    current_job_index=processed, 
                    jobs_in_current_batch=total_found,
                    processing_count=processing
                )
                
            except: pending_count = 0
            
            # 3. Scale UP logic (Only if NO stop requested)
            slots_available = self.max_concurrent_workers - len(active_processes)
            stop_requested = os.path.exists(Settings.STOP_SIGNAL)
            
            if not stop_requested and slots_available > 0 and pending_count > len(active_processes):
                spawn_count = min(slots_available, pending_count - len(active_processes))
                
                with open(_debug_log, "a") as f: 
                    f.write(f"[{time.strftime('%H:%M:%S')}] [Boss] Scaling UP! +{spawn_count} workers (Pending: {pending_count}, Active: {len(active_processes)}).\n")
                
                for _ in range(spawn_count):
                    p = multiprocessing.Process(target=execute_worker_lifecycle, args=(self.api_key, results_queue))
                    p.daemon = False # Allow it to finish current job even if Boss wants to exit
                    p.start()
                    active_processes.append(p)
            
            # 4. Wait
            time.sleep(5) 
            
            # --- SHUTDOWN LOGIC ---
            # The Boss (Processor) should ONLY shut down if signaled by the Top Boss (Manager)
            # via the stop_event. We don't exit on Settings.STOP_SIGNAL here anymore
            # to prevent premature chef desertion.
            
            # (Optional) Log if signal exists but manager hasn't stopped us yet
            if os.path.exists(Settings.STOP_SIGNAL) and pending_count > 0:
                 # We stay alive! Manager will kill us when collector is dead and pending is 0
                 pass
            
            # Final cleanup on exit
            try:
                db.recover_crashed_jobs()
            except: pass

        # AG_GUARD: CRITICAL SHUTDOWN COORDINATION
        # Sentinel None tells the listener to drain the queue then exit.
        # DO NOT modify without running tests/regression_shutdown.py
        self.monitor.log("⏳ [Boss] Esperando a que los trabajadores terminen su última oferta...")
        for p in active_processes:
            if p.is_alive():
                p.join() # Wait for worker to finish its job
        
        # Now that workers are done, tell the listener to finish
        results_queue.put(None) 
        t_listener.join(timeout=5)
        
        self.monitor.log("🏁 [Boss] Todos los trabajadores han finalizado. Cerrando cocina.")
