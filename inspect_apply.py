import sys
import os
import argparse

# Add current directory to path
sys.path.append(os.getcwd())

# Ensure we are the master of the monitor for the dashboard to show data
os.environ["MONITOR_MASTER"] = "true"

from src.app.bots.apply.supervisor import ApplyBotSupervisor
import src.services.storage.database as db

def main():
    parser = argparse.ArgumentParser(description="TalentFlow Inspector Bot (Shadow Mode)")
    parser.add_argument("--job-id", type=int, help="ID of a specific job to inspect")
    parser.add_argument("--limit", type=int, default=1, help="Number of 'Matched' jobs to test (default 1)")
    parser.add_argument("--step", action="store_true", help="Interactive Mode: Pause and review after each step")
    
    args = parser.parse_args()

    print("\n" + "═"*60)
    print("🕵️  TalentFlow Inspector Bot initialized.")
    print(f"🛡️  MODE: {'INTERACTIVE' if args.step else 'AUTOMATIC'} DRY RUN")
    print("👁️  BROWSER: Visual mode (Headless=False)")
    print("" + "═"*60 + "\n")

    # Initialize supervisor in visual mode
    supervisor = ApplyBotSupervisor(headless=False)

    import signal
    def stop_gracefully(signum, frame):
        print("\n🛑 Signal received. Closing browser and exiting...")
        try:
             supervisor.browser.close()
        except: pass
        sys.exit(0)
    
    signal.signal(signal.SIGTERM, stop_gracefully)
    signal.signal(signal.SIGINT, stop_gracefully)

    try:
        # Pass the interactive flag to the application flow through the supervisor
        supervisor.application_flow.interactive = args.step

        if args.job_id:
            print(f"🔍 Inspecting single Job ID: {args.job_id}")
            job = db.get_job_by_id(args.job_id)
            if job:
                supervisor.job_processor.process_job(job, dry_run=True)
            else:
                print(f"❌ Job ID {args.job_id} not found.")
        else:
            from src.config.settings import Settings
            print(f"🔍 Inspecting next {args.limit} 'Matched' jobs...")
            jobs = db.get_jobs_to_apply(limit=args.limit)
            
            # FALLBACK: If no Matched jobs, take Pending jobs instead of searching new ones
            if not jobs:
                print("ℹ️ No 'Matched' jobs found. Checking for 'Pending' jobs...")
                all_jobs = db.get_all_jobs()
                # Filter for jobs that haven't been processed yet (Pending)
                jobs = [j for j in all_jobs if j.get('status') == 'Pending'][:args.limit]

            if not jobs:
                print("⚠️ No jobs in DB (Matched or Pending). Launching Visual Explorer...")
                supervisor.monitor.log("🔍 Base de datos vacía. Iniciando explorador visual para buscar vacantes...")
                
                # 1. Initialize Collector (Sharing the visual session from supervisor)
                from src.app.bots.search.collector import JobCollector
                collector = JobCollector(supervisor.monitor, headless=False, existing_browser=supervisor.browser)
                
                # 2. Run it to find ONE job and open it.
                collector.collect(job_limit=1, single_combo_only=True, auto_open_modal=True)
                
                # 3. After modal is open, we need to 'connect' back to the apply supervisor
                # Since the browser is open and modal is there, we can just call form_handler manually
                # or wait for a bit. Actually, scan_results returned success if modal opened.
                
                print("✨ Form opened. Initializing inspector view...")
                # We need a job_context (even if empty) to run the step-by-step UI
                dummy_job = {"id": 0, "url": "EXPLORER", "company": "Explorer Mode", "role": "Investigating..."}
                supervisor.application_flow.handle_application_flow(dummy_job, dry_run=True, interactive=True)
            else:
                for job in jobs:
                    # PROACTIVE CHECK: Stop if signal is present
                    if os.path.exists(Settings.STOP_SIGNAL):
                        print("🛑 Stop signal detected. Clearing and exiting loop.")
                        try: os.remove(Settings.STOP_SIGNAL)
                        except: pass
                        break
                    
                    supervisor.job_processor.process_job(job, dry_run=True)
    
    except KeyboardInterrupt:
        print("\n🛑 Inspection stopped by user.")
    except Exception as e:
        import traceback
        traceback.print_exc()
        print(f"\n❌ Error during inspection: {e}")
    finally:
        print("\n🏁 Inspection phase ended.")
        print("🛑 Process exiting cleanly.")
        try:
             supervisor.browser.close()
        except: pass

if __name__ == "__main__":
    main()
