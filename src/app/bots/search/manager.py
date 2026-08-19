# ==============================================================================
# ⚠️ CRITICAL COMPONENT - DO NOT MODIFY WITHOUT EXPLICIT USER INSTRUCTION ⚠️
# ==============================================================================
# This file governs the orchestration of the search and match process.
# Any changes here can destabilize the parallel execution pipeline.
# ==============================================================================
import os
import sys
import time
import threading
import multiprocessing
import signal
import atexit
from typing import Optional, Type

import src.services.storage.database as db
from src.domain.interfaces import IJobAnalyzer, IJobScraper, IJobRepository, IMonitor
from src.services.browser.client import JobSearchBrowser
from src.services.ai.client import JobAnalyzer
from src.monitor import SearchMonitor
from src.config.settings import Settings
from src.utils.cleanup import nuke_zombies

from src.infrastructure.storage.sqlite_repository import SQLiteJobRepository
from src.application.use_cases.analyze_job import AnalyzeAndStoreJobUseCase
from src.application.use_cases.run_search import ExecuteSearchProjectUseCase

class SearchBotManager:
    def __init__(self, headless=False, analyzer: Optional[IJobAnalyzer] = None, scraper_class: Optional[Type[IJobScraper]] = None):
        # 1. First order of business: Clean the house
        nuke_zombies()
        
        self.headless = headless
        self.settings = Settings.load_credentials()
        self.profile = Settings.load_profile()
        self.api_key = os.environ.get("GEMINI_API_KEY") 
        
        self.scraper_class = scraper_class or JobSearchBrowser
        
        # 1.5 Set this process as the authority for dashboard updates
        os.environ["MONITOR_MASTER"] = "true"
        
        # Initialize Monitor
        self.monitor = SearchMonitor()
        self.monitor.log("⚙️ manager: Inicializando proceso...")
        
        # Register cleanup on exit
        atexit.register(self._cleanup)
        self._setup_signals()
        
        # Clean up stale signals
        self._clear_stale_signals()
            
        # Initialize Brain (AI Client) - Dependency Injection
        self.brain = analyzer or JobAnalyzer(api_key=self.api_key)

        # Infrastructure Adapters
        self.repository = SQLiteJobRepository()
        
        # Application Use Cases
        self.analyze_use_case = AnalyzeAndStoreJobUseCase(self.brain, self.repository, self.monitor)
        self.search_use_case = ExecuteSearchProjectUseCase(self.monitor)

        db.recover_crashed_jobs()
        
        # Process Tracking
        self.p_processor = None
        self.p_processor_pid = None
        self.t_collector = None

    def _setup_signals(self):
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)

    def _clear_stale_signals(self):
        for sig in [Settings.STOP_SIGNAL, Settings.ABORT_SIGNAL]:
            if os.path.exists(sig):
                try: os.remove(sig)
                except: pass

    def run(self, job_limit=40, max_pages=None, single_combo_only=False, skip_processor=False, skip_collector=False, re_analyze=False):
        sys.stdout.reconfigure(line_buffering=True)
        total_start_time = time.time()
        
        if re_analyze:
            self.monitor.log("🧹 [MANAGER] Re-análisis solicitado. Reiniciando registros con errores...")
            db.reset_failed_jobs()
            # If we also want to force re-analysis of EVERYTHING, we would use db.reset_all_analysis_status()
            # but usually users just want to fix the "Failed" ones.
        
        # ... (rest of search/manager.py's run method start)
        # Actually, let me see more of the file to be precise
        
        # Initialize Components
        from src.app.bots.search.collector import JobCollector
        # from src.app.bots.search.processor import JobProcessor <-- MOVED TO WORKER
        
        collector = JobCollector(self.monitor, headless=self.headless, scraper_class=self.scraper_class)
        # processor = JobProcessor(self.monitor) <-- MOVED TO WORKER
        
        # Parallel Execution Setup
        # Use multiprocessing Event for cross-process signaling
        stop_processing_event = multiprocessing.Event()
        results = {"collected": 0, "processed": 0}
        
        def run_collector():
            try:
                # Collector can stay in Thread for now (disabled anyway)
                # But if enabled, it might need similar treatment if it uses Playwright
                results["collected"] = collector.collect(
                    job_limit=job_limit,
                    max_pages=max_pages,
                    single_combo_only=single_combo_only
                )
            except Exception as e:
                self.monitor.log(f"❌ Error en hilo de colección: {e}")
        
        def run_dashboard_sync():
            """Third thread: periodically sync minor metadata to the monitor."""
            while not stop_processing_event.is_set():
                # The Dashboard is now updated IN REAL TIME by independent workers
                # using File Locking. The Manager only syncs global state if needed.
                time.sleep(5) 

        # 2. Hierarchy of Authority: The Top Boss Setup
        # Create a central queue for ALL subordinaries to report back.
        system_queue = multiprocessing.Queue()
        
        PROCESS_LIMIT = 1000
        def boss_listener():
            """The Top Boss Listener: Receives ALL reports and updates the hierarchy."""
            while not stop_processing_event.is_set():
                try:
                    report = system_queue.get(timeout=1)
                    if not report: continue
                    
                    if report['type'] == 'match':
                        self.monitor.add_match(report['job_data'], report['score'])
                        results["processed"] += 1
                        results["match"] = results.get("match", 0) + 1
                    elif report['type'] == 'reject':
                        results["processed"] += 1
                        results["reject"] = results.get("reject", 0) + 1
                    
                    # 🚩 TEST LIMIT: 10 Processed Jobs (Any result)
                    if results["processed"] >= PROCESS_LIMIT:
                        self.monitor.log(f"🚩 [MANAGER] Límite de {PROCESS_LIMIT} registros procesados alcanzado (Modo Prueba). Deteniendo...")
                        stop_processing_event.set()
                        with open(Settings.STOP_SIGNAL, 'w') as f: f.write("STOP")

                    if report['type'] == 'log':
                        self.monitor.log(report['message'])
                    elif report['type'] == 'progress':
                        # Use report value if strictly provided, else keep internal tally
                        p_current = report.get('current')
                        if p_current is not None:
                             results["processed"] = p_current
                        
                        self.monitor.update(
                            current_job_index=report.get('current', 0),
                            jobs_in_current_batch=report.get('total', 0),
                            processing_count=report.get('processing', 0)
                        )
                except: continue

        t_boss = threading.Thread(target=boss_listener, name="TopBossListener", daemon=True)
        t_boss.start()

        # DELEGATE TO USE CASE
        # Note: We use the static method for pickling safety
        proc = None
        t_collector = None

        if not skip_processor:
             # Spawn the processor as a separate process using a picklable entry point
             proc = multiprocessing.Process(
                 target=SearchBotManager._processor_worker_entry, 
                 args=(stop_processing_event, system_queue), 
                 name="ProcessorSubordinate"
             )
             proc.start()
        
        if not skip_collector:
            def run_coll():
                try:
                    res = collector.collect(
                        job_limit=job_limit,
                        max_pages=max_pages,
                        single_combo_only=single_combo_only
                    )
                    results["collected"] = res
                except Exception as e:
                    self.monitor.log(f"❌ Error en hilo de colección: {e}")
            
            t_collector = threading.Thread(target=run_coll, name="CollectorThread")
            t_collector.start()

        # Start Sync Thread
        t_sync = threading.Thread(target=run_dashboard_sync, name="SyncThread", daemon=True)
        t_sync.start()

        if proc:
            self.p_processor = proc
            self.p_processor_pid = proc.pid
        
        self.t_collector = t_collector

        if skip_processor:
            print("   [MANAGER] Collector ENABLED. System running in SEARCH-ONLY mode.")
        elif skip_collector:
            print(f"   [MANAGER] Processor Process Launched (PID: {self.p_processor_pid})")
            print("   [MANAGER] Standalone RE-ANALYSIS Mode ACTIVE.")
            print("   [MANAGER] Hierarchy: Manager (Top Boss) -> Processor (Middle Boss) -> Workers (Subordinates)")
        else:
            print(f"   [MANAGER] Processor Process Launched (PID: {self.p_processor_pid})")
            print("   [MANAGER] Collector ENABLED. System running in FULL PARALLEL mode.")
            print("   [MANAGER] Hierarchy: Manager (Top Boss) -> Processor (Middle Boss) -> Workers (Subordinates)")
        
        restart_count = 0
        max_restarts = 3
        idle_start_time = None
        # Dynamic Timeout: 30s for Search-Only (OnlyScan), 3min for AI-Match
        IDLE_TIMEOUT = 30 if skip_processor else 180 

        try:
            while True:
                try:
                    # 1. Check Supervisor & Persistence
                    collector_active = self.t_collector.is_alive() if self.t_collector else False
                    pending_count = db.get_pending_job_count()
                    
                    if not skip_processor:
                        should_be_running = collector_active or pending_count > 0
                        
                        if (not proc or not proc.is_alive()) and should_be_running and not stop_processing_event.is_set():
                            # The Boss (Processor) died or finished but there is still work or scout is active
                            if proc:
                                exit_code = proc.exitcode
                                self.monitor.log(f"💀 [SUPERVISOR] El Jefe (Processor) se detuvo inesperadamente (Code {exit_code}).")
                            
                            if restart_count < max_restarts or should_be_running:
                                restart_count += 1
                                self.monitor.log(f"🚑 [SUPERVISOR] Re-abriendo cocina... Reiniciando Jefe (Intento {restart_count}).")
                                time.sleep(2)
                                proc = multiprocessing.Process(
                                    target=SearchBotManager._processor_worker_entry,
                                    args=(stop_processing_event, system_queue)
                                )
                                proc.start()
                                self.p_processor = proc
                                self.p_processor_pid = proc.pid
                            else:
                                self.monitor.log("💀 [SUPERVISOR] Error fatal: El Jefe no puede reiniciar. Abortando.")
                                stop_processing_event.set()
                                break
                        
                        # If ABORT detected from inside processor
                        if os.path.exists(Settings.ABORT_SIGNAL):
                            with open(Settings.ABORT_SIGNAL, "r") as f: err = f.read()
                            self.monitor.log(f"🛑 [SUPERVISOR] ABORTO DETECTADO: {err}")
                            if "429" in err or "quota" in err.lower():
                                os.environ["FORCE_BROWSER_AI"] = "true"
                                if os.path.exists(Settings.ABORT_SIGNAL): os.remove(Settings.ABORT_SIGNAL)
                                # Let the loop restart it in the next iteration due to should_be_running
                            else:
                                stop_processing_event.set()
                                break
                    
                    # 2. Check Work Status & Idle Timeout
                    pending_count = db.get_pending_job_count()
                    collector_active = self.t_collector.is_alive() if self.t_collector else False
                    
                    if not collector_active and pending_count == 0:
                        if idle_start_time is None:
                            idle_start_time = time.time()
                            self.monitor.log("ℹ️ [SUPERVISOR] Sistema en espera. Iniciando temporizador de auto-apagado (5 min)...")
                        
                        idle_duration = time.time() - idle_start_time
                        if idle_duration >= IDLE_TIMEOUT:
                            self.monitor.log(f"⏰ [SUPERVISOR] Tiempo de espera agotado ({IDLE_TIMEOUT}s). Finalizando proceso automáticamente.")
                            stop_processing_event.set()
                            break
                    else:
                        # Reset idle if work found or collector still searching
                        if idle_start_time is not None:
                            self.monitor.log("🚀 [SUPERVISOR] Trabajo detectado. Temporizador de espera reseteado.")
                            idle_start_time = None
                    
                    # 3. Global Stop Signal (Graceful)
                    if os.path.exists(Settings.STOP_SIGNAL):
                        self.monitor.log("🏁 [STOP] Detención inmediata solicitada. Cerrando sistema...")
                        stop_processing_event.set()
                        break 
                    
                    time.sleep(5) # Manager check interval

                except KeyboardInterrupt:
                    stop_processing_event.set()
                    break
                except Exception as e:
                    print(f"Manager Loop Error: {e}")
                    time.sleep(5)
        finally:
            # Signal Processor and Sync to stop (Safety)
            stop_processing_event.set()
            
            # AG_GUARD: CRITICAL SHUTDOWN COORDINATION
            if proc and proc.is_alive():
                self.monitor.log("⏳ [SUPERVISOR] Esperando a que el Jefe (Processor) cierre la cocina...")
                proc.join(timeout=10)
            
            if 't_sync' in locals() and t_sync.is_alive():
                t_sync.join(timeout=2)
            
            self.monitor.log("💾 [SUPERVISOR] Guardando estado final...")
            self.monitor.save()
            
            self.monitor.log("🏁 [MANAGER] Proceso Finalizado.")
            self.monitor.update(status="Stopped")
            self._cleanup() # Force Chrome Closure

            try:
                from src.services.reporting import generate_excel_report
                self.monitor.log("📊 Generando reporte Excel...")
                generate_excel_report()
            except: pass

    def process_single_job(self, details, url, current_role):
        # DELEGATE TO USE CASE
        return self.analyze_use_case.execute(details, url, current_role)

    def _analyze_with_retry(self, description, date_posted):
        retries = 3
        for attempt in range(retries):
             try:
                 # Wait before request (Incremental backoff: 10s, 20s, 30s)
                 wait_time = 10 * (attempt + 1)
                 if attempt > 0:
                     self.monitor.log(f"⏳ Esperando {wait_time}s para reintentar (Intento {attempt+1}/{retries})...")
                 else:
                     # Initial wait to be safe
                     time.sleep(5)

                 if attempt > 0: time.sleep(wait_time)
                 
                 analysis = self.brain.analyze(f"PUBLICATION DATE: {date_posted}\n\n{description}")
                 if analysis: return analysis
                 
                 print(f"   [Manager] Analysis attempt {attempt+1} failed (None result).")
             except Exception as e:
                 print(f"   [Manager] Analysis attempt {attempt+1} error: {e}")
                 time.sleep(5)
                 
        return None

    def _get_audit_summary(self):
        """Parse audit.csv to get a tally of actions."""
        import csv
        path = "dashboard/audit.csv"
        if not os.path.exists(path): return "Sin datos"
        
        stats = {"SEEN": 0, "SAVED": 0, "DUPLICATE": 0, "SKIPPED": 0, "MATCHED": 0, "DISCARDED": 0, "ERROR": 0}
        try:
            with open(path, mode='r', encoding='utf-8') as f:
                reader = csv.DictReader(f)
                for row in reader:
                    action = row.get("Action")
                    if action in stats:
                        stats[action] += 1
            
            summary = f"Vistas: {stats['SEEN']} | Nuevas: {stats['SAVED']} | Duplicadas: {stats['DUPLICATE']} | IA-Match: {stats['MATCHED']} | IA-Reject: {stats['DISCARDED']}"
            if stats['SKIPPED'] > 0: summary += f" | Skipped: {stats['SKIPPED']}"
            return summary
        except:
            return "Error leyendo audit"

    def _signal_handler(self, signum, frame):
        print("\n🛑 [Manager] Signal received. Shutting down...")
        self._cleanup()
        sys.exit(0)

    def _cleanup(self):
        """Safe shutdown of all resources."""
        # Create stop signal file for child processes
        with open(Settings.STOP_SIGNAL, 'w') as f: f.write("STOP")
        
        # Wait a bit then force kill
        time.sleep(1)
        nuke_zombies()

    @staticmethod
    def _processor_worker_entry(stop_evt, queue):
        """Entry point for the subordinate processor process (Picklable)."""
        os.environ["MONITOR_MASTER"] = "false"
        from src.monitor import SearchMonitor
        from src.app.bots.search.processor import JobProcessor
        m = SearchMonitor()
        p = JobProcessor(m)
        p.process_continuous(stop_evt, queue)
