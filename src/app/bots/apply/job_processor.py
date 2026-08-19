import os
import src.services.storage.database as db

class JobProcessor:
    def __init__(self, browser, resume_manager, application_flow, external_flow, monitor=None):
        self.browser = browser
        self.resume_manager = resume_manager
        self.application_flow = application_flow
        self.external_flow = external_flow
        self.monitor = monitor

    def process_job(self, job, dry_run=False):
        from src.config.settings import Settings
        if os.path.exists(Settings.STOP_SIGNAL):
            print("🛑 Stop signal detected. Skipping job.")
            return

        url = job['url']
        role = job['role']
        reqs = job['requirements']
        job_id = job['id']
            
        print(f"\n👉 Processing Job ID {job_id}: {role}")
        db.update_job_status(job_id, "Applying", error="Starting application process...")
        
        try:
            print(f"   🌐 [Nav] Navigating to: {url}")
            self.browser.page.goto(str(url), wait_until="domcontentloaded", timeout=45000)
            self.browser.human_delay(4, 6) # Give LinkedIn time to render the right pane
            
            # Check applied
            if self.browser.page.is_visible("text=Application submitted") or \
               self.browser.page.is_visible("text=Postulación enviada"):
                 print("   ✅ Already applied to this job.")
                 db.update_job_status(job_id, "Applied", resume="Previously")
                 return
            
            # Robust wait for the button to appear (it sometimes lazy-loads)
            print("   ⏳ Waiting for 'Apply' button to be ready...")
            try:
                self.browser.page.wait_for_selector("button.jobs-apply-button, a.jobs-apply-button, .jobs-s-apply button", timeout=10000)
            except:
                print("   ⚠️  Button not found immediately, will try AI clicking anyway.")

            clicked = self.browser.click_like_an_ai()

            if clicked:
                self.browser.human_delay(2)
                # ... same tab check ...
                pages = self.browser.context.pages
                page_to_process = None
                
                if len(pages) > 1:
                    page_to_process = pages[-1]
                    print(f"   🌍 [External] New tab detected.")
                elif "linkedin.com/jobs" not in self.browser.page.url:
                    page_to_process = self.browser.page
                    print(f"   🌍 [External] Same-tab redirect detected.")

                if page_to_process:
                    try:
                        page_to_process.wait_for_load_state("domcontentloaded", timeout=10000)
                        ext_url = page_to_process.url
                        print(f"   🌍 [External] Processing: {ext_url}")
                        
                        # PREPARE CONTEXT FOR EXTERNAL
                        lang = self.resume_manager.detect_language(role + " " + (reqs or ""))
                        stored_filename = job.get('applied_resume')
                        target_res = self.resume_manager.get_resume_filename(job["role"], job["description"], job.get("language", "en"), stored_filename=job.get("applied_resume"))
                        print(f"      📍 RESUME SELECTED: {os.path.basename(target_res)}")
                        self.monitor.update(target_resume=os.path.basename(target_res), actual_resume="-")
                        
                        # CALCULATE SALARY EXPECTATION
                        salary_val, salary_curr = self.resume_manager.get_salary_expectation(role, lang)
                        print(f"      💰 RESOLVED SALARY: {salary_val} {salary_curr} ({lang})")

                        ext_context = {
                            "id": job_id,
                            "role": role,
                            "location": job.get('location', 'Unknown'),
                            "description": reqs,
                            "target_resume": target_res,
                            "applied_salary": salary_val,
                            "applied_currency": salary_curr
                        }

                        # HANDOVER TO EXTERNAL ENGINE
                        result = self.external_flow.handle_external_application(ext_context, page_to_process)
                        
                        if result == "Submitted":
                            print(f"   🎉 [External] Application Successful!")
                            db.update_job_status(job_id, "Applied", uploaded_cv=ext_context.get("actual_resume") or os.path.basename(target_res))
                        elif result == "Manual":
                            print(f"   ⚠️ [External] Manual intervention needed on external site.")
                            db.update_job_status(job_id, "Manual", external_link=ext_url)
                        else:
                            print(f"   ❌ [External] Failed: {result}")
                            db.update_job_status(job_id, "Manual", external_link=ext_url, error=str(result))
                            
                    except Exception as e:
                        print(f"   ⚠️ External Flow Error: {e}")
                        db.update_job_status(job_id, "Manual", error=f"External Error: {e}")
                    finally:
                        if page_to_process != self.browser.page:
                            try: page_to_process.close()
                            except: pass
                        else:
                            # If it was same tab, we need to go back for the next job
                            # although the next process_job does a .goto(), it's cleaner to reset
                            pass
                    return

                # Language Detection
                lang = self.resume_manager.detect_language(role + " " + (reqs or ""))
                
                # Resume Selection (Updated to use pre-selected resume from analysis)
                stored_filename = job.get('applied_resume')
                target_res = self.resume_manager.get_resume_filename(role, reqs, lang, stored_filename=stored_filename)
                db.update_job_status(job_id, "Applying", error=f"Resume selected: {os.path.basename(target_res)}")
                
                # CALCULATE SALARY EXPECTATION
                salary_val, salary_curr = self.resume_manager.get_salary_expectation(role, lang)
                print(f"      💰 RESOLVED SALARY: {salary_val} {salary_curr} ({lang})")

                job_context = {
                    "id": job_id,
                    "role": role,
                    "location": job.get('location', 'Unknown'),
                    "description": reqs,
                    "target_resume": target_res,
                    "applied_salary": salary_val,
                    "applied_currency": salary_curr,
                    "profile_skills": self.resume_manager.config.get("skills", {})
                }
                
                result = self.application_flow.handle_application_flow(job_context, dry_run=dry_run)
                
                if result == "Submitted":
                    print("   🎉 Application Successfully Submitted!")
                    actual = job_context.get("actual_resume") or os.path.basename(target_res)
                    self.monitor.update(actual_resume=actual)
                    db.update_job_status(
                        job_id, "Applied", 
                        uploaded_cv=actual,
                        salary=job_context.get("applied_salary"),
                        currency=job_context.get("applied_currency")
                    )
                elif result == "Manual":
                    print("   ⚠️  Complex form/Manual intervention needed.")
                    db.update_job_status(job_id, "Manual", resume=job_context.get("actual_resume") or os.path.basename(target_res))
                else:
                    db.update_job_status(job_id, "Failed", error=str(result))
            else:
                print("   ❌ Apply button not found.")
                db.update_job_status(job_id, "Failed", error="Apply button not found")

        except Exception as e:
            print(f"   [Error] {e}")
            db.update_job_status(job_id, "Failed", error=str(e))
        finally:
            self.application_flow.cleanup_modal()
