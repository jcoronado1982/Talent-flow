import os
from src.config.settings import Settings

class ResumeManager:
    def __init__(self, browser, config):
        self.browser = browser
        self.config = config

    def detect_language(self, text):
        text = text.lower()
        score_en = 0
        score_es = 0
        if "software" in text: score_en += 1
        if "ingeniero" in text: score_es += 1
        return "es" if score_es > score_en else "en"

    def get_resume_filename(self, role, desc, lang):
        """
        Selects the best resume with high-intelligence matching.
        PRIORITY: 
        1. Tech in TITLE + Leader/Dev status match.
        2. Tech in DESC + Leader/Dev status match.
        3. Fallbacks.
        """
        import re
        role_lower = role.lower()
        desc_lower = (desc or "").lower()
        rules = self.config.get("resume_rules", [])
        
        # 0. Smart Language Detection
        spanish_indicators = ["experiencia", "requisitos", "conocimientos", "manejo", "años", "responsabilidades", "vacante"]
        is_actually_spanish = any(word in desc_lower for word in spanish_indicators)
        effective_lang = "es" if is_actually_spanish else lang

        print(f"   🔍 Choosing Resume for: {role[:40]}... (Lang: {effective_lang})")

        def word_in_text(word, target_text):
            word = word.lower()
            if any(c in word for c in ["#", "+", "."]):
                pattern = r'(?i)(?<![\w])' + re.escape(word) + r'(?![\w])'
            else:
                pattern = r'\b' + re.escape(word) + r'\b'
            return bool(re.search(pattern, target_text))

        is_lead_match = any(word_in_text(x, role_lower) for x in ["lead", "staff", "principal", "architect", "arquitecto", "líder", "lider", "manager", "head"])
        is_dev_match = any(word_in_text(x, role_lower) for x in ["developer", "engineer", "desarrollador", "ingeniero", "full stack", "fullstack", "backend", "frontend", "senior", "sr"])

        # detected_status is True for Leader, False for Developer
        # Logic: If it mentions Lead/Architect, it's Leader. 
        # If it ONLY mentions Senior/Engineer/Developer, it's Developer.
        detected_status_leader = is_lead_match

        # PASS 1: TECHNOLOGY IN TITLE (Strongest Match)
        for rule in rules:
            if rule.get("language") != effective_lang: continue
            tech_keywords = rule.get("keywords") or (rule.get("match_all")[0] if "match_all" in rule else [])
            
            if any(word_in_text(k, role_lower) for k in tech_keywords):
                is_leader_rule = "match_all" in rule
                if is_leader_rule == detected_status_leader:
                    print(f"      🎯 TITLE MATCH (Tech + Status): {rule['file']}")
                    return self._resolve_resume_path(rule["file"])

        # PASS 2: LEADERSHIP RULES (Description Match)
        # Only if detected as Leader or ambiguous
        if detected_status_leader:
            for rule in rules:
                if rule.get("language") != effective_lang or "match_all" not in rule: continue
                groups = rule["match_all"]
                if all(any(word_in_text(k, role_lower + " " + desc_lower) for k in group) for group in groups):
                    print(f"      ✅ LEADER MATCH (Desc keywords): {rule['file']}")
                    return self._resolve_resume_path(rule["file"])

        # PASS 3: DEVELOPER RULES (Description Match)
        # Only if detected as Developer or ambiguous
        if not detected_status_leader:
            for rule in rules:
                if rule.get("language") != effective_lang or "match_all" in rule: continue
                if any(word_in_text(k, role_lower + " " + desc_lower) for k in rule.get("keywords", [])):
                    print(f"      ✅ TECH MATCH (Desc keywords): {rule['file']}")
                    return self._resolve_resume_path(rule["file"])

        # PASS 4: SMART FALLBACKS BY STATUS
        print(f"      ⚠️ No specific rule matched for {effective_lang}. Looking for status fallback...")
        # 4a. Best match for status and language
        for rule in rules:
            if rule.get("language") != effective_lang: continue
            is_leader_rule = "match_all" in rule
            if is_leader_rule == detected_status_leader:
                print(f"      ✅ FALLBACK MATCH (Status + Lang): {rule['file']}")
                return self._resolve_resume_path(rule["file"])

        # 4b. Just language
        for rule in rules:
            if rule.get("language") == effective_lang:
                return self._resolve_resume_path(rule["file"])

        filename = rules[0]["file"] if rules else "default.pdf"
        return self._resolve_resume_path(filename)

    def _resolve_resume_path(self, filename):
        base_dir = os.path.join(Settings.BASE_DIR, "cv")
        for root, dirs, files in os.walk(base_dir):
            if filename in files:
                return os.path.join(root, filename)
        return os.path.join(base_dir, filename)

    def smart_upload_resume(self, file_path):
        """Finds the MOST RELEVANT file input and uploads the resume."""
        page = self.browser.page
        basename = os.path.basename(file_path)
        
        upload_triggers = [
            "button:has-text('Upload resume')",
            "button:has-text('Cargar currículum')",
            "button:has-text('Subir currículum')",
            "button[aria-label*='Upload resume']",
            "button[aria-label*='Cargar currículum']"
        ]
        
        # 1. Check if we are already using the correct one (if list is visible)
        try:
             resumes_list = page.locator(".jobs-document-card__title").all()
             for res in resumes_list:
                 res_text = res.inner_text().lower()
                 clean_basename = basename.lower().replace(".pdf", "")
                 if clean_basename in res_text or (len(clean_basename) > 10 and res_text.startswith(clean_basename[:15])):
                     print(f"      ✅ Resume '{basename}' (or match) already selected in list.")
                     res.click()
                     return basename # Confirmed match
        except: pass

        # 2. Try to find the file input
        file_inputs = page.locator("input[type='file']").all()
        
        if not file_inputs:
             for sel in upload_triggers:
                 btn = page.locator(sel).first
                 if btn.is_visible():
                     print(f"      🖱️ Clicking '{sel}' to reveal file input...")
                     btn.click()
                     self.browser.human_delay(1, 2)
                     file_inputs = page.locator("input[type='file']").all()
                     break
        
        if not file_inputs:
             # Fallback: Capture whatever is currently selected title if possible
             try:
                 selected = page.locator(".jobs-document-card--active .jobs-document-card__title").first
                 if selected.is_visible():
                     return f"[LinkedIn Default] {selected.inner_text().strip()}"
             except: pass
             
             # If we see any indicator that we SHOULD be on resume step but found nothing, return failure
             # otherwise return None to keep trying.
             resume_indicators = ["resume", "currículum", "curriculum", "cv"]
             page_text = page.content().lower()
             if any(x in page_text for x in resume_indicators):
                 print("      ⚠️ Resume indicators found but no input/button accessible.")
                 # Don't return yet, maybe it's just slow.
             
             return None # Keep trying on next steps

        print(f"   📂 Attempting intelligent upload: {basename}")
        
        target_input = None
        if len(file_inputs) == 1:
            target_input = file_inputs[0]
        else:
            for inp in file_inputs:
                attr_str = (inp.get_attribute("name") or "") + (inp.get_attribute("id") or "") + (inp.get_attribute("aria-label") or "")
                if any(x in attr_str.lower() for x in ["resume", "cv", "curriculum", "file"]):
                    target_input = inp
                    break
            if not target_input: target_input = file_inputs[0]

        try:
            target_input.attach_file(file_path)
            print(f"      ✅ File uploaded: {basename}")
            self.browser.human_delay(3, 5)
            return basename
        except Exception as e:
            try:
                target_input.set_input_files(file_path)
                print(f"      ✅ File uploaded (fallback): {basename}")
                self.browser.human_delay(3, 5)
                return basename
            except Exception as e2:
                print(f"      ❌ Smart Upload Error: {e2}")
                return "Upload Failed"
