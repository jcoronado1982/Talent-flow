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
        Selects the best resume based on defined rules. 
        Improved to handle Spanish jobs with English titles and strict tech matching.
        """
        import re
        role_lower = role.lower()
        desc_lower = (desc or "").lower()
        text = (role_lower + " " + desc_lower)
        rules = self.config.get("resume_rules", [])
        
        # 0. Smart Language Detection
        # If the description has common Spanish words, it's a Spanish job regardless of the title.
        spanish_indicators = ["experiencia", "requisitos", "conocimientos", "manejo", "años", "responsabilidades"]
        is_actually_spanish = any(word in desc_lower for word in spanish_indicators)
        effective_lang = "es" if is_actually_spanish else lang

        print(f"   🔍 Selecting Resume for: {role[:30]}... (Detected: {effective_lang}, Original: {lang})")

        def word_in_text(word, target_text):
            word = word.lower()
            # If the word contains special chars like #, +, or starts with ., use a simpler boundary
            if any(c in word for c in ["#", "+", "."]):
                pattern = r'(?i)(?<![\w])' + re.escape(word) + r'(?![\w])'
            else:
                pattern = r'\b' + re.escape(word) + r'\b'
            return bool(re.search(pattern, target_text))

        is_dev_title = any(word_in_text(x, role_lower) for x in ["developer", "engineer", "desarrollador", "ingeniero", "full stack", "fullstack", "backend", "frontend"])
        is_lead_title = any(word_in_text(x, role_lower) for x in ["lead", "staff", "principal", "architect", "arquitecto", "líder", "lider", "manager", "head"])

        # First pass: Technology-specific rules (Developer)
        for rule in rules:
            if rule.get("language") != effective_lang or "match_all" in rule:
                continue
            
            # Check for EXACT technology match
            if any(word_in_text(k, text) for k in rule.get("keywords", [])):
                if is_dev_title and not is_lead_title:
                    print(f"      ✅ Match found (Tech Priority): {rule['file']}")
                    return self._resolve_resume_path(rule["file"])

        # Second pass: Leadership rules
        for rule in rules:
            if rule.get("language") != effective_lang or "match_all" not in rule:
                continue
            
            groups = rule["match_all"]
            if all(any(word_in_text(k, text) for k in group) for group in groups):
                print(f"      ✅ Match found (Leader Rule): {rule['file']}")
                return self._resolve_resume_path(rule["file"])

        # Third pass: Fallback to any technical match in the effective language
        for rule in rules:
            if rule.get("language") != effective_lang or "match_all" in rule:
                continue
            if any(word_in_text(k, text) for k in rule.get("keywords", [])):
                print(f"      ✅ Match found (Keyword Fallback): {rule['file']}")
                return self._resolve_resume_path(rule["file"])
        
        if effective_lang == "en":
            print(f"      ⚠️ No specific tech rule matched for EN. Checking for any C# or Python mention as fallback...")
            # Extra safety: if C# or .NET is in the text, FORCE the C# CV instead of defaulting to Java
            if any(word_in_text(k, text) for k in ["c#", ".net", "dotnet", "win32", "visual studio"]):
                 for rule in rules:
                     if rule["file"] == "CV_D_C_EN_Jesus_Coronado.pdf":
                         print(f"      🎯 Force matching C# CV due to explicit tech mention.")
                         return self._resolve_resume_path(rule["file"])

        print(f"      ⚠️ No specific rule matched for {effective_lang}. Using default.")
        for rule in rules:
            if rule.get("language") == effective_lang and "match_all" not in rule:
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
            "button[aria-label*='Upload']",
            "button[aria-label*='Cargar']"
        ]
        
        is_upload_visible = any(page.locator(sel).is_visible() for sel in upload_triggers)
        file_inputs = page.locator("input[type='file']").all()
        
        if not file_inputs:
             if is_upload_visible:
                 print("   📂 'Upload' button visible but no <input type='file'> found in DOM yet.")
             return

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
            target_input.set_input_files(file_path)
            print(f"      ✅ File uploaded: {basename}")
            self.browser.human_delay(2, 4)
        except Exception as e:
            print(f"      ❌ Smart Upload Error: {e}")
