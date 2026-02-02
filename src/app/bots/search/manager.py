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

import src.services.storage.database as db
from src.services.browser.client import JobSearchBrowser
from src.services.ai.client import JobAnalyzer
from src.monitor import SearchMonitor
from src.config.settings import Settings
from src.utils.cleanup import nuke_zombies

class SearchBotManager:
    def __init__(self, headless=False):
        # 1. First order of business: Clean the house
        nuke_zombies()
        
        self.headless = headless
        self.settings = Settings.load_credentials()
        self.profile = Settings.load_profile()
        self.api_key = os.environ.get("GEMINI_API_KEY") 
        
        # 1.5 Set this process as the authority for dashboard updates
        os.environ["MONITOR_MASTER"] = "true"
        
        # Initialize Monitor
        self.monitor = SearchMonitor()
        self.monitor.log("⚙️ manager: Inicializando proceso...")
        
        # Register cleanup on exit
        atexit.register(self._cleanup)
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)
        
        # Initialize Brain (AI Client)
        self.brain = JobAnalyzer(api_key=self.api_key)

        # Clean up stale signals
        if os.path.exists(Settings.STOP_SIGNAL):
            try: os.remove(Settings.STOP_SIGNAL)
            except: pass

        if os.path.exists(Settings.ABORT_SIGNAL):
            try: os.remove(Settings.ABORT_SIGNAL)
            except: pass
            
        # Initialize DB
        db.init_db()
        db.recover_crashed_jobs()

    def run(self, job_limit=200, max_pages=None, single_combo_only=False, skip_processor=False, skip_collector=False):
        sys.stdout.reconfigure(line_buffering=True)
        total_start_time = time.time()
        
        # ... (rest of search/manager.py's run method start)
        # Actually, let me see more of the file to be precise
        
        # Initialize Components
        from src.app.bots.search.collector import JobCollector
        # from src.app.bots.search.processor import JobProcessor <-- MOVED TO WORKER
        
        collector = JobCollector(self.monitor, headless=self.headless)
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
        
        def boss_listener():
            """The Top Boss Listener: Receives ALL reports and updates the hierarchy."""
            while not stop_processing_event.is_set():
                try:
                    report = system_queue.get(timeout=1)
                    if not report: continue
                    
                    if report['type'] == 'match':
                        self.monitor.add_match(report['job_data'], report['score'])
                    elif report['type'] == 'log':
                        self.monitor.log(report['message'])
                    elif report['type'] == 'progress':
                        self.monitor.update(
                            current_job_index=report.get('current', 0),
                            jobs_in_current_batch=report.get('total', 0)
                        )
                except: continue

        t_boss = threading.Thread(target=boss_listener, name="TopBossListener", daemon=True)
        t_boss.start()

        if skip_processor:
            self.monitor.log("ℹ️ [MANAGER] Saltando lanzamiento del Processor (Modo Solo-Búsqueda)")
            proc = None
        else:
            # Launch Processor as a Subordinate Process
            self.monitor.log("🚀 [MANAGER] Lanzando Processor como Subordinado Directo...")
            from src.app.bots.search.processor import JobProcessor
            
            def run_processor_subordinate():
                # Re-init monitor for the process but it won't write to disk (MONITOR_MASTER is False)
                os.environ["MONITOR_MASTER"] = "false"
                mid_boss_monitor = SearchMonitor()
                processor = JobProcessor(mid_boss_monitor)
                processor.process_continuous(stop_processing_event, system_queue)

            proc = multiprocessing.Process(target=run_processor_subordinate, name="ProcessorSubordinate")
            proc.start()
            self.p_processor_pid = proc.pid
            self.monitor.log(f"✅ [MANAGER] Subordinado Processor iniciado con PID: {self.p_processor_pid}")

        t_collector = threading.Thread(target=run_collector, name="CollectorThread")
        t_sync = threading.Thread(target=run_dashboard_sync, name="SyncThread", daemon=True)
        
        t_sync.start()
        
        if not skip_processor:
            time.sleep(2) # Give processor a moment to initialize
            
        if not skip_collector:
            self.monitor.log("✅ [MANAGER] Búsqueda (Collector) INICIADA.")
            t_collector.start()
        else:
            self.monitor.log("ℹ️ [MANAGER] Saltando lanzamiento del Collector (Modo Solo-Match)")
        
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
        IDLE_TIMEOUT = 360 # 6 minutes patient window

        while True:
            try:
                # 1. Check Supervisor & Persistence
                collector_active = t_collector.is_alive() if not skip_collector else False
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
                            proc = multiprocessing.Process(target=run_processor_subordinate)
                            proc.start()
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
                collector_active = t_collector.is_alive() if not skip_collector else False
                
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
                    if not collector_active:
                         # Collector is already dead, now check Processor
                         if pending_count > 0:
                             self.monitor.log(f"⏳ [GRACEFUL STOP] Búsqueda detenida. Procesando {pending_count} ofertas restantes...")
                             self.monitor.update(status="Closing (Processing Pending)")
                         else:
                             self.monitor.log("🏁 [GRACEFUL STOP] Sin tareas pendientes. Cerrando sistema...")
                             stop_processing_event.set()
                             break 
                    else:
                        # Collector is still alive, we just let it die naturally or it will see the STOP_SIGNAL itself
                        # Most code in collector.py checks Settings.STOP_SIGNAL
                        pass
                
                time.sleep(5) # Manager check interval

                    
            except KeyboardInterrupt:
                stop_processing_event.set()
                break
            except Exception as e:
                print(f"Manager Loop Error: {e}")
                time.sleep(5)

        # Signal Processor and Sync to stop (Safety)
        stop_processing_event.set()
        
        # AG_GUARD: CRITICAL SHUTDOWN COORDINATION
        # This section ensures the Manager waits for the Processor before closing.
        # DO NOT modify without running tests/regression_shutdown.py
        if proc and proc.is_alive():
            self.monitor.log("⏳ [SUPERVISOR] Esperando a que el Jefe (Processor) cierre la cocina...")
            proc.join()
        
        # Stop sync thread and do ONE FINAL SAVE
        stop_processing_event.set()
        if t_sync.is_alive():
            t_sync.join(timeout=2)
        
        self.monitor.log("💾 [SUPERVISOR] Guardando estado final...")
        self.monitor.save()
        
        # --- REPORTING ---
        total_duration = time.time() - total_start_time
        
        # Performance Stats
        self.monitor.log("="*40)
        self.monitor.log("⏱️ REPORTE FINAL (PARALELO)")
        self.monitor.log(f"   • Tiempo Total: {total_duration:.2f}s")
        self.monitor.log(f"   • Ofertas Recolectadas: {results['collected']}")
        self.monitor.log(f"   • Ofertas Procesadas (IA): {results['processed']}")
        
        if results['processed'] > 0:
            avg_time = total_duration / results['processed'] # Rough estimate
            self.monitor.log(f"   • Rendimiento: ~{avg_time:.2f}s/oferta (Efectivo)")
        
        # Audit Summary
        try:
            audit_summary = self._get_audit_summary()
            self.monitor.log(f"   • Audit: {audit_summary}")
        except: pass

        self.monitor.log("="*40)

        self.monitor.log("🏁 [MANAGER] Proceso Finalizado.")
        self.monitor.update(status="Stopped")
        
        from src.services.reporting import generate_excel_report
        self.monitor.log("📊 Generando reporte Excel...")
        generate_excel_report()

    def process_single_job(self, details, url, current_role):
        description = details.get("description", "")
        company = details.get("company", "Unknown")
        date_posted = details.get("date", "Unknown")
        site = "linkedin" 

        print(f"   [Manager] Analyze Job: {url}")
        
        # TRANSACCIÓN: INICIO
        self.monitor.log(f"▶️ [INICIO] Procesando oferta: {company}")
        
        analysis = None
        if description and len(description) > 50:
            # TRANSACCIÓN: EN PROCESO
            self.monitor.log(f"⏳ [EN PROCESO] Analizando con IA ({len(description)} chars)...")
            analysis = self._analyze_with_retry(description, date_posted)
        else:
            self.monitor.log("⚠️ [FINALIZADO] Cancelado: Sin descripción válida.")
            return

        if analysis:
            match_score = analysis.get('match_percentage', 0)
            print(f"Analysis Result: {match_score}% Match")
            
            if match_score >= 30:
                item = {
                    "source": site,
                    "url": url,
                    "role": details.get("title", current_role),
                    "date": date_posted,
                    "company": company,
                    "location": details.get("location", "Unknown"), 
                    "work_mode": details.get("work_mode", "Unknown"),
                    "raw_requirements": details.get("raw_requirements", ""),
                    "analysis": analysis
                }
                
                # match_score is taken from analysis
                db.save_job(item)
                self.monitor.add_match(item, match_score)
                # TRANSACCIÓN: FINALIZADA (EXITO)
                self.monitor.log(f"✅ [FINALIZADO] Éxito: {match_score}% de coincidencia.")
            else:
                # TRANSACCIÓN: FINALIZADA (DESCARTE)
                self.monitor.log(f"📉 [FINALIZADO] Descartada: {match_score}% de coincidencia.")
        else:
            # TRANSACCIÓN: FINALIZADA (ERROR)
            self.monitor.log("❌ [FINALIZADO] Error: Falló el análisis tras reintentos.")

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
