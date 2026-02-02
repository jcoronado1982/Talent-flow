import src.services.storage.database as db

class JobProcessor:
    def __init__(self, browser, resume_manager, application_flow):
        self.browser = browser
        self.resume_manager = resume_manager
        self.application_flow = application_flow

    def process_job(self, job):
        url = job['url']
        role = job['role']
        reqs = job['requirements']
        job_id = job['id']
            
        print(f"\n👉 Processing Job ID {job_id}: {role}")
        db.update_job_status(job_id, "Applying", error="Starting application process...")
        
        try:
            self.browser.page.goto(str(url))
            self.browser.human_delay(3)
            
            # Check applied
            if self.browser.page.is_visible("text=Application submitted"):
                 db.update_job_status(job_id, "Applied", resume="Previously")
                 return
            
            # Check Closed
            if self.browser.page.is_visible("text=No longer accepting applications") or \
               self.browser.page.is_visible("text=Ya no se aceptan solicitudes"):
                 print("   ⛔ Job is closed/expired.")
                 db.update_job_status(job_id, "Closed", error="Job expired")
                 return

            clicked = self.browser.click_like_an_ai()

            if clicked:
                self.browser.human_delay(2)
                
                # Check for External Link
                pages = self.browser.context.pages
                if len(pages) > 1:
                    new_page = pages[-1]
                    try:
                        new_page.wait_for_load_state("domcontentloaded", timeout=5000)
                        ext_url = new_page.url
                        print(f"   [External] Redirected to: {ext_url}")
                        db.update_job_status(job_id, "External", external_link=ext_url, error="External application detected")
                    except:
                        db.update_job_status(job_id, "External", error="External application detected (High Latency)")
                    finally:
                        new_page.close()
                    return

                # Language Detection
                lang = self.resume_manager.detect_language(role + " " + (reqs or ""))
                
                # Resume Selection
                target_res = self.resume_manager.get_resume_filename(role, reqs, lang)
                db.update_job_status(job_id, "Applying", error=f"Resume selected: {target_res}")
                
                job_context = {
                    "id": job_id,
                    "role": role,
                    "description": reqs,
                    "target_resume": target_res
                }
                
                result = self.application_flow.handle_application_flow(job_context)
                
                if result == "Submitted":
                    print("   🎉 Application Successfully Submitted!")
                    db.update_job_status(
                        job_id, "Applied", 
                        resume=target_res,
                        salary=job_context.get("applied_salary"),
                        currency=job_context.get("applied_currency")
                    )
                elif result == "Manual":
                    print("   ⚠️  Complex form/Manual intervention needed.")
                    db.update_job_status(job_id, "Manual", resume=target_res)
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
