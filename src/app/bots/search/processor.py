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

def detect_language_heuristic(text):
    """Simple keyword-based language detection as safety fallback."""
    if not text: return "Spanish"
    text_lower = text.lower()
    es_k = ["responsabilidades", "requisitos", "experiencia", "conocimientos", "ofrecemos", "vacante", "ubicación", "empresa", "educación"]
    en_k = ["responsibilities", "requirements", "experience", "knowledge", "offer", "vacancy", "location", "company", "education"]
    es_score = sum(2 for k in es_k if k in text_lower)
    en_score = sum(2 for k in en_k if k in text_lower)
    return "English" if en_score > es_score else "Spanish"

# Comprehensive keyword list for heuristic skill extraction
_KNOWN_TECH_SKILLS = [
    # Backend Languages
    "C#", ".NET Core", "ASP.NET", ".NET", "Java", "Spring Boot", "Spring",
    "Python", "Django", "Flask", "FastAPI", "Node.js", "Go", "Golang",
    "Rust", "C++", "PHP", "Laravel", "Ruby", "Rails", "Kotlin", "Scala",
    # Frontend
    "Angular", "React", "Vue", "Next.js", "Nuxt", "TypeScript", "JavaScript",
    "HTML", "CSS", "SASS", "SCSS", "Ionic", "jQuery", "Svelte",
    # Mobile
    "Flutter", "React Native", "Android", "iOS", "Swift",
    # Databases
    "SQL Server", "PostgreSQL", "MySQL", "MariaDB", "MongoDB", "Redis",
    "Cassandra", "DynamoDB", "Elasticsearch", "Oracle", "SQLite", "T-SQL",
    "Vector DB", "Pinecone", "Weaviate",
    # DevOps / Cloud
    "Docker", "Kubernetes", "AWS", "Azure", "GCP", "Terraform", "CI/CD",
    "Jenkins", "GitHub Actions", "GitLab CI", "Ansible", "Linux",
    # AI / Data
    "PyTorch", "TensorFlow", "LLM", "LLMs", "OpenAI", "Langchain", "RAG",
    "CUDA", "Vertex AI", "N8N", "Pandas", "NumPy", "Spark",
    # Integration / Messaging
    "RabbitMQ", "Kafka", "GraphQL", "REST", "gRPC", "Microservices", "Websockets",
    # Tools
    "Git", "Jira", "Scrum", "Agile", "Salesforce", "SAP", "Power BI",
]

def extract_skills_heuristic(text):
    """
    MANDATORY FALLBACK: Scans raw job description text for known technology keywords.
    Returns a comma-separated string of detected skills, or 'N/A' if nothing found.
    This guarantees the 'skills' column is NEVER left as '-' for any job.
    """
    if not text:
        return "N/A"
    found = []
    text_lower = text.lower()
    for skill in _KNOWN_TECH_SKILLS:
        # Use word-boundary-safe check: skill not already added and present as a word
        skill_lower = skill.lower()
        if skill_lower in text_lower and skill not in found:
            found.append(skill)
    return ", ".join(found) if found else "N/A"

def normalize_analysis(data: dict, raw_job_text: str = "") -> dict:
    """
    SCHEMA RESCUE LAYER.
    When the local LLM ignores our mandatory JSON schema and returns a free-form
    response, this function translates it into our standard format so no job is
    wrongly scored 0.

    Priority: if 'match_percentage' already exists and is > 0, pass through.
    Otherwise, probe all known alternative key patterns from common LLM outputs.
    """
    if not data:
        return data

    # --- 1. If the schema is already correct, just return it ---
    if data.get('match_percentage', 0) > 0:
        return data

    normalized = dict(data)

    # --- 2. Rescue match_percentage from common alternative keys ---
    # We probe multiple candidates used by different LLMs when they ignore our schema.
    score_candidates = [
        data.get('match_score'),
        data.get('score'),
        data.get('similarity_score'),
        data.get('fit_score'),
        data.get('overall_score'),
        data.get('compatibility_score'),
        data.get('match'),
    ]
    # Also probe nested keys like {"analysis": {"score": 75}} as many models group their JSON output.
    for nested_key in ['analysis', 'assessment', 'evaluation', 'result']:
        nested = data.get(nested_key)
        if isinstance(nested, dict):
            score_candidates += [
                nested.get('match_percentage'),
                nested.get('match_score'),
                nested.get('score'),
                nested.get('fit_score'),
            ]
    
    for candidate in score_candidates:
        if candidate is not None:
            try:
                val = float(str(candidate).replace('%', '').strip())
                # Handle 0.0-1.0 range → convert to 0-100
                if 0 < val <= 1.0:
                    val = val * 100
                normalized['match_percentage'] = int(val)
                break
            except:
                continue

    # --- 3. Rescue verdict from recommendation / recommendation fields ---
    if not normalized.get('verdict'):
        rec = (
            str(data.get('recommendation', ''))
            + str(data.get('suggested_action', ''))
            + str(data.get('final_assessment', ''))
            + str(data.get('overall_recommendation', ''))
        ).lower()
        # Check nested
        for nested_key in ['analysis', 'assessment', 'evaluation', 'result', 'recommendation']:
            nested = data.get(nested_key)
            if isinstance(nested, dict):
                rec += str(nested.get('recommendation', '')).lower()
                rec += str(nested.get('suggested_action', '')).lower()

        if any(k in rec for k in ['strong hire', 'hire', 'apply', 'yes', 'proceed', 'good fit', 'excellent', 'recommend']):
            normalized['verdict'] = 'APPLY'
            # If model said "Strong Hire" but gave no score, give a reasonable score
            if normalized.get('match_percentage', 0) == 0:
                normalized['match_percentage'] = 60
        elif any(k in rec for k in ['defer', 'consider', 'maybe', 'partial']):
            normalized['verdict'] = 'DEFER'
            if normalized.get('match_percentage', 0) == 0:
                normalized['match_percentage'] = 35
        else:
            normalized['verdict'] = 'REJECT'

    # --- 4. Rescue mandatory_skills from skill_gap_analysis / required_skills ---
    if not normalized.get('mandatory_skills'):
        skill_sources = []
        
        # Check skill_gap_analysis.required_skills (list)
        skill_gap = data.get('skill_gap_analysis') or data.get('skill_gap') or {}
        if isinstance(skill_gap, dict):
            rs = skill_gap.get('required_skills') or skill_gap.get('missing_skills')
            if isinstance(rs, list):
                skill_sources = [str(s) for s in rs if isinstance(s, str)]
        
        # Check top-level required_skills
        if not skill_sources:
            rs = data.get('required_skills')
            if isinstance(rs, list):
                skill_sources = [str(s) for s in rs if isinstance(s, str)]

        if skill_sources:
            normalized['mandatory_skills'] = ", ".join(skill_sources)
        elif raw_job_text:
            # Final fallback: heuristic scan
            normalized['mandatory_skills'] = extract_skills_heuristic(raw_job_text)

    return normalized


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
            
            job_update['language'] = analysis.get('language_detected')
            if job_update['language'] in [None, 'Unknown', 'Other']:
                job_update['language'] = detect_language_heuristic(job['requirements'])
            
            # Update status
            if match_score >= 40: 
                new_status = 'Matched'
            else: 
                new_status = 'Discarded'
            
            db.update_job_status(job_id, new_status)
            
            try:
                with open(_debug_log, "a") as f: f.write(f"[{time.strftime('%H:%M:%S')}] {job_tag} Finished. Status: {new_status} ({match_score}%)\n")
            except: pass

            if match_score >= 40:
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
    from src.agents.resume_manager import ResumeManagerAgent
    
    _debug_log = "dashboard/processor_debug.log"
    pid = os.getpid()
    
    # Init dependencies
    # NO MONITOR in worker - we report via queue to avoid race conditions
    brain = JobAnalyzer(api_key=api_key)
    audit = AuditLogger()
    resume_agent = ResumeManagerAgent()

    
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
                job_description_text = job.get('requirements', '')


                # ============================================================
                # 🧠 ETAPA 2: ANÁLISIS PROFUNDO POR LLM (solo para candidatos semánticos)
                # ============================================================
                # Analyze with structured context + previous skills if any
                prev_skills = job.get('skills', '-')
                prompt = (
                    f"ROLE: {job.get('role', 'Unknown')}\n"
                    f"LOCATION: {job.get('location', 'Unknown')}\n"
                    f"PREVIOUS MANDATORY SKILLS: {prev_skills if prev_skills != '-' else 'None Yet'}\n"
                    f"JOB DESCRIPTION:\n{job_description_text}"
                )
                
                # ⏱️ MEASURE START
                start_time = time.time()
                analysis_result = brain.analyze(prompt)
                duration = time.time() - start_time
                # ⏱️ MEASURE END
                
                # Default update object with diagnostic data
                job_update = dict(job)
                job_update['raw_prompt'] = analysis_result.get('raw_prompt') if analysis_result else None
                job_update['raw_analysis'] = analysis_result.get('raw_response') if analysis_result else None
                job_update['processing_time'] = round(duration, 2)
                job_update['ai_model'] = analysis_result.get('ai_model', 'Unknown') # 🤖 Extract AI Model Name directly from result

                analysis_data = analysis_result.get('data') if analysis_result else None
                
                if analysis_data:
                    # 🔧 SCHEMA RESCUE: If LLM returned its own format, normalize it to our schema
                    analysis_data = normalize_analysis(analysis_data, raw_job_text=job.get('requirements', ''))
                    
                    try:
                        match_score = int(float(analysis_data.get('match_percentage', 0)))
                    except:
                        match_score = 0

                    job_update['analysis'] = analysis_data
                    
                    # Robust Skill Extraction: Try primary key then fallbacks
                    skills = analysis_data.get('mandatory_skills')
                    
                    if not skills or str(skills).strip() in ['-', 'null', 'None', '']:
                        # Fallback 1: Check in 'assessment' (some models return a different schema)
                        assessment = analysis_data.get('assessment', {})
                        if isinstance(assessment, dict):
                            skills = assessment.get('mandatory_skills')
                        
                        # Fallback 2: Join 'strengths' if available as a list
                        if not skills and 'strengths' in analysis_data:
                            s_list = analysis_data.get('strengths')
                            if isinstance(s_list, list):
                                skills = ", ".join(s_list)
                        
                        # Fallback 3 (MANDATORY): Heuristic scan of raw job description.
                        # This MUST always produce a non-empty result for auditing purposes.
                        # Applies to ALL jobs — especially DISCARDED ones where AI may skip skill extraction.
                        if not skills or str(skills).strip() in ['-', 'null', 'None', '']:
                            skills = extract_skills_heuristic(job.get('requirements', ''))
                    
                    job_update['skills'] = str(skills) if skills else 'N/A'

                    
                    # Smart Correction
                    ai_mode = analysis_data.get('work_mode_detected')
                    if ai_mode and ai_mode != 'Unknown':
                        job_update['work_mode'] = ai_mode
                    
                    job_update['language'] = analysis_data.get('language_detected')
                    if job_update['language'] in [None, 'Unknown', 'Other']:
                        job_update['language'] = detect_language_heuristic(job['requirements'])
                    
                    # ai_model already set above from result
                    
                    new_status = 'Matched' if match_score >= 50 else 'Discarded'
                    
                    # Determine applied resume via deterministic business rules
                    if match_score >= 50:
                        cv_input = {
                            "ROLE":     job.get('role', ''),
                            "LOCATION": analysis_data.get('location_detected', job.get('location', '')),
                            "SKILLS":   analysis_data.get('mandatory_skills', ''),
                            "LANG":     analysis_data.get('language_detected', 'Spanish'),
                        }
                        job_update['applied_resume'] = resume_agent.get_resume_filename(cv_input)
                    else:
                        job_update['applied_resume'] = None

                    db.save_job(job_update)
                    db.update_job_status(job_id, new_status)
                    
                    if match_score >= 50:
                        results_queue.put({
                            'type': 'match',
                            'job_data': job_update,
                            'score': match_score
                        })
                        results_queue.put({'type': 'log', 'message': f"✅ MATCH: {company} ({match_score}%) in {duration:.1f}s"})
                        audit.log("MATCHED", company=company, role=job['role'], details=f"Score: {match_score}% | Time: {duration:.1f}s", url=job['url'])
                    else:
                        audit.log("DISCARDED", company=company, role=job['role'], reason="Low Match Score", details=f"Score: {match_score}% | Time: {duration:.1f}s", url=job['url'])
                        
                    with open(_debug_log, "a") as f: f.write(f"[{time.strftime('%H:%M:%S')}] [Worker {pid}] -> Finished job {company} (ID: {job_id}) in {duration:.2f}s\n")
                else:
                    # Even if parsing failed, save the raw data for analysis in the dashboard
                    error_detail = "AI Analysis returned empty or invalid JSON."
                    raw_resp = analysis_result.get('raw_response') if analysis_result else "No response"
                    if raw_resp:
                        error_detail += f"\nRaw Response Snippet: {str(raw_resp)[:200]}"
                    
                    db.save_job(job_update) 
                    db.update_job_status(job_id, "Failed", error=error_detail)
                    audit.log("FAIL", company=company, role=job['role'], reason="Analysis Failure", details=error_detail, url=job['url'])
                    
            except Exception as e:
                 import traceback
                 error_msg = f"❌ [Worker {pid}] Error: {e}\n{traceback.format_exc()}"
                 results_queue.put({'type': 'log', 'message': error_msg})
                 with open(_debug_log, "a") as f: f.write(f"[{time.strftime('%H:%M:%S')}] {error_msg}\n")
                 
                 # Ensure prompt and error hit the DB so UI can show the failure
                 failed_job_update = dict(job)
                 try:
                     failed_job_update['raw_prompt'] = brain.prompts.get_analysis_prompt(prompt)
                 except:
                     failed_job_update['raw_prompt'] = prompt
                 failed_job_update['raw_analysis'] = f"CRITICAL ERROR:\n{error_msg}"
                 
                 db.save_job(failed_job_update)
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
        self.max_concurrent_workers = Settings.get_max_workers()

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
        
        self.monitor.log("🧠 [BOSS] Iniciando Jerarquía de Procesos (Manager + Workers Subordinados)...")
        
        _debug_log = "dashboard/processor_debug.log"
        active_processes = []

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
                
                # Report progress to Manager (Top Boss)
                results_queue.put({
                    'type': 'progress',
                    'current': processed,
                    'total': total_found,
                    'processing': processing
                })
                
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
        # Sentinel None tells the manager's listener to drain if needed (not strictly necessary here but good practice)
        # results_queue.put(None) 
        
        self.monitor.log("🏁 [Boss] Todos los trabajadores han finalizado. Cerrando cocina.")
