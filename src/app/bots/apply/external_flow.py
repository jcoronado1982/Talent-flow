
import os
import time
import src.services.storage.database as db

class ExternalFlow:
    def __init__(self, browser, form_handler, resume_manager):
        self.browser = browser
        self.form_handler = form_handler
        self.resume_manager = resume_manager

    def handle_external_application(self, job_context, page):
        """
        Takes control of an external tab and tries to apply.
        """
        url = page.url
        job_id = job_context["id"]
        role = job_context["role"]
        
        print(f"   🚀 Starting External Engine for: {url}")
        db.update_job_status(job_id, "Applying", error=f"External Flow: {url}")
        
        try:
            # 1. Detect ATS
            ats_type = self._detect_ats(url, page)
            print(f"   [External] ATS Detected: {ats_type or 'Generic'}")
            
            # 2. Main Loop for Multi-Step External Forms
            max_steps = 8
            for step in range(1, max_steps + 1):
                # Ensure the page is scrolled to see elements
                try: page.evaluate("window.scrollTo(0, 500)")
                except: pass
                
                # Search for Apply Button if not on form yet
                if not self._is_on_form(page):
                    print(f"      [External] Step {step}: Looking for Apply button...")
                    if self._click_apply_button(page):
                         self.browser.human_delay(2, 3)
                         if self._is_on_form(page):
                             print("      [External] Form found after clicking Apply.")
                
                # Check for form again
                if self._is_on_form(page):
                    # Try to upload resume first (common in external sites)
                    target_file = job_context.get("target_resume")
                    if target_file and not job_context.get("actual_resume"):
                        job_context["actual_resume"] = self.resume_manager.smart_upload_resume(target_file, page=page)

                    # Fill the current page form
                    self.form_handler.fill_form(job_context, root=page)
                    
                    # Check for Submit
                    if self._click_submit_button(page):
                        print("      [External] Submit clicked. Checking results...")
                        self.browser.human_delay(3, 5)
                        if self._check_success(page):
                            return "Submitted"
                        else:
                            print("      [External] No success message yet, might be multi-step.")
                
                # Check for Next/Continue
                if not self._click_next_button(page):
                    # If we can't find next/submit/apply and we've tried, break
                    if step > 2: break
                    
                self.browser.human_delay(1, 2)

            return "Manual"
            
        except Exception as e:
            print(f"   [External] ❌ Error: {e}")
            return str(e)

    def _detect_ats(self, url, page):
        url_lower = url.lower()
        if "workable.com" in url_lower: return "Workable"
        if "greenhouse.io" in url_lower: return "Greenhouse"
        if "lever.co" in url_lower: return "Lever"
        if "smartrecruiters.com" in url_lower: return "SmartRecruiters"
        
        # Check body for clues
        body = page.content().lower()
        if "workable" in body: return "Workable"
        if "greenhouse" in body: return "Greenhouse"
        return None

    def _is_on_form(self, page):
        # Look for multiple inputs or a file input
        inputs = page.locator("input[type='text'], input[type='email'], input[type='tel'], textarea, input[type='file']").count()
        return inputs >= 2

    def _click_apply_button(self, page):
        labels = ["Apply Now", "Apply for this job", "Postularse", "Apply on company site", "Join us", "Postulate", "Enviar mi CV"]
        for lbl in labels:
            try:
                # Try both button and link
                candidates = page.locator(f"button:has-text('{lbl}'), a:has-text('{lbl}')").all()
                for btn in candidates:
                    if btn.is_visible():
                        btn.click()
                        return True
            except: continue
        return False

    def _click_submit_button(self, page):
        labels = ["Submit application", "Submit", "Enviar solicitud", "Finalizar postulación"]
        for lbl in labels:
            btn = page.get_by_role("button", name=lbl).first
            if btn.is_visible():
                btn.click()
                return True
        return False

    def _click_next_button(self, page):
        labels = ["Next", "Continue", "Siguiente", "Continuar"]
        for lbl in labels:
            btn = page.get_by_role("button", name=lbl).first
            if btn.is_visible():
                btn.click()
                return True
        return False

    def _check_success(self, page):
        success_indicators = ["Application submitted", "Thank you for applying", "Success", "¡Gracias!", "Recibimos tu solicitud"]
        content = page.content().lower()
        return any(ind.lower() in content for ind in success_indicators)
