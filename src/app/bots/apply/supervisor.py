import os
import time
from src.config.settings import Settings
from src.services.browser.client import JobSearchBrowser
from src.services.ai.client import JobAnalyzer
import src.services.storage.database as db

from .resume_manager import ResumeManager
from .form_handler import FormHandler
from .application_flow import ApplicationFlow
from .external_flow import ExternalFlow
from .job_processor import JobProcessor
from src.monitor import SearchMonitor

class ApplyBotSupervisor:
    def __init__(self, headless=False):
        self.settings = Settings.load_credentials()
        self.config = Settings.load_profile()
        self.browser = JobSearchBrowser(headless=headless, chrome_profile="Profile 1")
        print("   ✅ Browser Interface Initialized (Launch Phase Complete)")
        self.brain = JobAnalyzer()
        
        # Initialize specialized components
        status_file = os.path.join(Settings.BASE_DIR, "dashboard", "status.json")
        self.monitor = SearchMonitor(status_file)
        
        self.resume_manager = ResumeManager(self.browser, self.config)
        self.form_handler = FormHandler(self.browser, self.brain, monitor=self.monitor)
        self.application_flow = ApplicationFlow(self.browser, self.form_handler, self.resume_manager)
        self.external_flow = ExternalFlow(self.browser, self.form_handler, self.resume_manager)
        self.job_processor = JobProcessor(self.browser, self.resume_manager, self.application_flow, self.external_flow, monitor=self.monitor)

        self.global_start_time = time.time()
        print("🤖 ApplyBot Supervisor Initialized.")

    def run(self, dry_run=False):
        print("🤖 Auto-Apply Bot Started (vModular)...")
        
        try:
             jobs = db.get_jobs_to_apply(limit=30)
             if not jobs:
                 print("✅ No 'Matched' jobs found to apply. I will wait 5 seconds so you can see the browser.")
                 time.sleep(5)
                 self.browser.close()
                 return
             print(f"📂 Found {len(jobs)} pending jobs in database.")
             
             # Automatic Backup before applying
             db.create_backup("pre_apply")
        except Exception as e:
             print(f"❌ Database Error: {e}")
             self.browser.close()
             return

        print("   🔄 Checking session...")
        try:
            self.browser.page.goto("https://www.linkedin.com/feed/")
            self.browser.human_delay(2)
            if "login" in self.browser.page.url:
                 print("   ❌ Session invalid. Manual login required.")
            else:
                 print("   ✅ Session Loaded.")

            import random
            
            for job in jobs:
                if self._check_stop_signal(): break
                self.job_processor.process_job(job, dry_run=dry_run)
                
                # PAUSA ESTRATÉGICA ANTI-BAN ENTRE APLICACIONES (Límite dinámico)
                # Evita que aplique de forma veloz continuada.
                delay = random.uniform(45.0, 90.0)
                print(f"   ⏱️ [Anti-Ban] Pausando {int(delay)} segundos antes de la siguiente revisión para proteger la cuenta...")
                
                # Pausa segmentada para poder detectar el botón STOP del panel en cualquier momento
                for _ in range(int(delay)):
                    if self._check_stop_signal(): 
                        print("✅ Batch Cancelled.")
                        return
                    time.sleep(1)
                
            print("✅ Batch Completed.")
            time.sleep(5)
            
        except Exception as e:
            print(f"❌ Fatal Error: {e}")
        finally:
            print("   ✅ Batch process completed.")
            self.browser.close()

    def _check_stop_signal(self):
        if os.path.exists(Settings.STOP_SIGNAL):
            print("🛑 Stop received. Halting...")
            try: os.remove(Settings.STOP_SIGNAL)
            except: pass
            return True
        return False
