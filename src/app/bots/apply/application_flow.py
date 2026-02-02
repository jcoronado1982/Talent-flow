import random
import src.services.storage.database as db

class ApplicationFlow:
    def __init__(self, browser, form_handler, resume_manager):
        self.browser = browser
        self.form_handler = form_handler
        self.resume_manager = resume_manager

    def handle_application_flow(self, job_context):
        """Supervises the 'Easy Apply' modal flow."""
        page = self.browser.page
        max_steps = 15
        step = 0
        job_id = job_context["id"]
        
        while step < max_steps:
            step += 1
            
            # 0. Check Success IMMEDIATE (Priority)
            if page.get_by_text("Application sent").is_visible() or page.get_by_text("Solicitud enviada").is_visible():
                 db.update_job_status(job_id, "Submitted", resume=job_context.get("target_resume"))
                 self.click_button(["Done", "Finalizar", "Dismiss", "Cerrar"]) 
                 return "Submitted"

            self.browser.human_delay(0.5, 1.5)
            
            if random.random() > 0.7:
                 try:
                     self.browser.page.mouse.wheel(0, random.randint(100, 300))
                     self.browser.human_delay(0.2, 0.5)
                 except: pass
            
            # 1. Check Submit / Done buttons
            if self.click_button(["Submit application", "Enviar solicitud"]):
                db.update_job_status(job_id, "Submitted", resume=job_context.get("target_resume"))
                return "Submitted"
            
            if self.click_button(["Done", "Hecho", "Finalizar"]):
                db.update_job_status(job_id, "Submitted", resume=job_context.get("target_resume"))
                return "Submitted"

            # 2. Upload Resume
            target_file = job_context.get("target_resume")
            if target_file:
                self.resume_manager.smart_upload_resume(target_file)

            # 3. Fill Form
            try:
                db.update_job_status(job_id, "Applying", error=f"Step {step}: Filling form...")
                captured = self.form_handler.fill_form(job_context)
                if captured:
                    if "salary" in captured: job_context["applied_salary"] = captured["salary"]
                    if "currency" in captured: job_context["applied_currency"] = captured["currency"]
            except Exception as e:
                print(f"   ⚠️ Error autofilling: {e}")
                db.update_job_status(job_id, "Applying", error=f"Step {step} Error: {str(e)[:50]}")

            # 4. Check for blocking errors
            error_el = page.locator(".artdeco-inline-feedback--error").first
            if error_el.is_visible():
                txt = error_el.inner_text().strip()
                print(f"   [Flow] ⚠️  Potential error visible: '{txt[:30]}...'")
                if step > 8: return "Manual"

            # 5. Check Next/Review
            if self.click_button(["Continue to next step", "Next", "Siguiente", "Continue", "Review", "Revisar"]):
                continue

            # 6. Safety Check
            if step > 2 and not page.is_visible(".jobs-easy-apply-modal"):
                 return "Submitted"
            
            print("   ❓ No actionable buttons found. Wait...")
        
        return "Manual"

    def click_button(self, labels):
        modal = self.browser.page.locator(".jobs-easy-apply-modal")
        if not modal.is_visible(): return False

        for lbl in labels:
            footer_btn = modal.locator(f"footer button[aria-label='{lbl}']").first
            if footer_btn.is_visible():
                footer_btn.click()
                return True
                
            footer_text_btn = modal.locator(f"footer button:has-text('{lbl}')").first
            if footer_text_btn.is_visible():
                footer_text_btn.click()
                return True

            candidates = modal.locator(f"button[aria-label='{lbl}']").all()
            for btn in candidates:
                if not btn.is_visible(): continue
                cls = btn.get_attribute("class") or ""
                if "pagination" in cls: continue
                btn.click()
                return True
                
            text_candidates = modal.locator(f"button:has-text('{lbl}')").all()
            for btn in text_candidates:
                if not btn.is_visible(): continue
                cls = btn.get_attribute("class") or ""
                if "pagination" in cls: continue
                btn.click()
                return True
        return False

    def cleanup_modal(self):
        """Ensures the modal is closed before moving on."""
        try:
            modal = self.browser.page.locator(".jobs-easy-apply-modal")
            if modal.is_visible():
                print("   🧹 Cleaning up open modal...")
                close_btn = modal.locator("button[aria-label='Dismiss']")
                if close_btn.is_visible():
                    close_btn.click()
                    self.browser.human_delay(0.5)
                    confirm_btn = self.browser.page.locator("button[data-control-name='discard_application_confirm_btn']")
                    if confirm_btn.is_visible(): confirm_btn.click()
                self.browser.page.keyboard.press("Escape")
                self.browser.human_delay(1)
        except: pass
