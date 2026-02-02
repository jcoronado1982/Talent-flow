import os
import time
from src.config.settings import Settings
from src.services.browser.client import JobSearchBrowser
from src.services.ai.client import JobAnalyzer
import src.services.storage.database as db

from .resume_manager import ResumeManager
from .form_handler import FormHandler
from .application_flow import ApplicationFlow
from .job_processor import JobProcessor

class ApplyBotSupervisor:
    def __init__(self, headless=False):
        self.settings = Settings.load_credentials()
        self.config = Settings.load_profile()
        self.browser = JobSearchBrowser(headless=headless)
        print("   ✅ Browser Interface Initialized (Launch Phase Complete)")
        self.brain = JobAnalyzer()
        
        # Initialize specialized components
        self.resume_manager = ResumeManager(self.browser, self.config)
        self.form_handler = FormHandler(self.browser, self.brain)
        self.application_flow = ApplicationFlow(self.browser, self.form_handler, self.resume_manager)
        self.job_processor = JobProcessor(self.browser, self.resume_manager, self.application_flow)

        self.global_start_time = time.time()
        print("🤖 ApplyBot Supervisor Initialized.")

    def run(self):
        print("🤖 Auto-Apply Bot Started (vModular)...")
        
        try:
             jobs = db.get_jobs_to_apply(limit=10)
             if not jobs:
                 print("✅ No 'Matched' jobs found to apply. I will wait 5 seconds so you can see the browser.")
                 time.sleep(5)
                 self.browser.close()
                 return
             print(f"📂 Found {len(jobs)} pending jobs in database.")
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

            for job in jobs:
                if self._check_stop_signal(): break
                self.job_processor.process_job(job)
                
            print("✅ Batch Completed.")
            time.sleep(5)
            
        except Exception as e:
            print(f"❌ Fatal Error: {e}")
        finally:
            print("   ✅ Batch process completed.")
            self.browser.close()

    def _check_stop_signal(self):
        if os.path.exists(Settings.STOP_SIGNAL):
            runtime = time.time() - self.global_start_time
            if runtime < 5: 
                try: os.remove(Settings.STOP_SIGNAL)
                except: pass
                return False 
            else:
                print("🛑 Stop received. Halting...")
                try: os.remove(Settings.STOP_SIGNAL)
                except: pass
                return True
        return False
