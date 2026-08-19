import os
import re
from src.config.settings import Settings

class ResumeManager:
    def __init__(self, browser, config):
        self.browser = browser
        self.config = config

    def _word_in_text(self, word, target_text):
        import re
        word = word.lower()
        if any(c in word for c in ["#", "+", "."]):
            pattern = r'(?i)(?<![\w])' + re.escape(word) + r'(?![\w])'
        else:
            pattern = r'\b' + re.escape(word) + r'\b'
        return bool(re.search(pattern, target_text))

    def detect_language(self, text):
        text = text.lower()
        score_en = 0
        score_es = 0
        if "software" in text: score_en += 1
        if "ingeniero" in text: score_es += 1
        return "es" if score_es > score_en else "en"

    def get_resume_filename(self, role, desc, lang, stored_filename=None):
        """
        Selects the best resume using deterministic mapping from cv_profile.json.
        Naming Convention: CV_{prefix}_{exp}_{city}_{role}_{tech}_{lang}_{owner}.pdf
        """
        import re

        # 1. THROUGH PRE-SELECTED FILENAME (Manual bypass from DB)
        if stored_filename:
            role_folder = "Leader" if "_L_" in stored_filename else "Developer"
            city_folder = "bogota" if "_B_" in stored_filename else "medellin"
            full_path = os.path.join(Settings.BASE_DIR, "cv", role_folder, city_folder, stored_filename)
            if os.path.exists(full_path):
                return full_path
            resolved = self._resolve_resume_path(stored_filename)
            if os.path.exists(resolved): return resolved

        # 2. DETERMINISTIC ENGINE (Using cv_profile.json)
        config_data = self.config.get("resume_rules")
        
        # Fallback to legacy if config is a list (old format)
        if isinstance(config_data, list):
            return self._legacy_get_resume_filename(role, desc, lang, config_data)
        
        if not isinstance(config_data, dict) or "rules" not in config_data:
            print("   ⚠️  Warning: cv_profile.json missing or invalid. Using default CV.")
            return self._resolve_resume_path("CV_15_M_D_P_ES_Jesus_Coronado.pdf")

        agent_cfg = config_data.get("agent_config", {})
        rules_cfg = config_data.get("rules", {})
        
        role_lower = role.lower()
        desc_lower = (desc or "").lower()
        content_lower = role_lower + " " + desc_lower
        
        # A. Detect Role (L vs D)
        role_map = rules_cfg.get("role_mapping", {})
        leader_keywords = role_map.get("leader_keywords", [])
        is_leader = any(self._word_in_text(kw, role_lower) for kw in leader_keywords)
        role_code = role_map.get("codes", {}).get("leader" if is_leader else "developer", "D")
        role_folder = "Leader" if is_leader else "Developer"
        
        # B. Detect Tech (J, C, P)
        tech_map = rules_cfg.get("tech_mapping", {})
        tech_code = "P" # Default to Python
        for code, keywords in tech_map.items():
            if any(self._word_in_text(kw, content_lower) for kw in keywords):
                tech_code = code
                break
        
        # C. Detect City (B, M)
        city_map = rules_cfg.get("city_mapping", {})
        city_code = city_map.get("__default__", "M")
        for city, code in city_map.items():
            if city != "__default__" and city in content_lower:
                city_code = code
                break
        city_folder = "bogota" if city_code == "B" else "medellin"

        # D. Detect Language (EN, ES)
        # Use smart detection result passed in 'lang' but mapped to Profile codes
        lang_map = rules_cfg.get("language_mapping", {})
        lang_code = lang_map.get("spanish" if lang == "es" else "english", "EN")
        
        # E. Build Filename
        # Format: {prefix}_{exp}_{city}_{role}_{tech}_{lang}_{owner}{ext}
        fmt = agent_cfg.get("naming_format", "CV_{prefix}_{exp}_{city}_{role}_{tech}_{lang}_{owner}{ext}")
        filename = fmt.format(
            prefix=agent_cfg.get("prefix", "CV"),
            exp=agent_cfg.get("experience", "20"),
            city=city_code,
            role=role_code,
            tech=tech_code,
            lang=lang_code,
            owner=agent_cfg.get("owner", "Jesus_Coronado"),
            ext=agent_cfg.get("file_extension", ".pdf")
        )
        
        print(f"   🔍 Choosing Resume for: {role[:40]}...")
        print(f"      📍 Components: Role={role_code}, Tech={tech_code}, City={city_code}, Lang={lang_code}")
        
        final_path = os.path.join(Settings.BASE_DIR, "cv", role_folder, city_folder, filename)
        if os.path.exists(final_path):
             print(f"      🎯 Deterministic Match: {role_folder}/{city_folder}/{filename}")
             return final_path
        
        print(f"      ⚠️  Built path not found, falling back to global search: {filename}")
        return self._resolve_resume_path(filename)

    def _legacy_get_resume_filename(self, role, desc, lang, rules):
        role_lower = role.lower()
        desc_lower = (desc or "").lower()
        is_lead_match = any(self._word_in_text(x, role_lower) for x in ["lead", "staff", "architect", "manager", "head"])
        for rule in rules:
            if not isinstance(rule, dict): continue
            if rule.get("language") != lang: continue
            if is_lead_match == ("match_all" in rule):
                return self._resolve_resume_path(rule["file"])
        return self._resolve_resume_path("CV_Jesus_Coronado.pdf")

    def get_salary_expectation(self, role, lang):
        """
        Resolves the salary expectation based on the role and language detected.
        Uses rules from profile_config.json.
        """
        salary_config = self.config.get("salary_expectations", {})
        rules = salary_config.get("rules", [])
        default = salary_config.get("default", {"value": "Negotiable", "currency": "COP"})
        
        role_lower = role.lower()
        lang_lower = str(lang).lower()
        
        # Determine status (Lead/Manager vs Dev)
        is_lead = any(x in role_lower for x in ["lead", "staff", "principal", "architect", "arquitecto", "líder", "lider", "manager", "head"])
        
        # Search for best rule
        for rule in rules:
            role_match = rule.get("role_match", "").lower()
            if rule.get("language") == lang_lower:
                if "lead" in role_match and is_lead:
                    return rule.get("value"), rule.get("currency", default.get("currency", "COP"))
                if not is_lead and any(x in role_match for x in ["senior", "full stack", "developer"]):
                    return rule.get("value"), rule.get("currency", default.get("currency", "COP"))

        for rule in rules:
            if rule.get("language") == lang_lower:
                return rule.get("value"), rule.get("currency", default.get("currency", "COP"))

        return default.get("value"), default.get("currency")

    def _resolve_resume_path(self, filename):
        base_dir = os.path.join(Settings.BASE_DIR, "cv")
        for root, dirs, files in os.walk(base_dir):
            if filename in files:
                return os.path.join(root, filename)
        return os.path.join(base_dir, filename)

    def smart_upload_resume(self, file_path, page=None):
        """Finds the MOST RELEVANT file input and uploads the resume."""
        if not page: page = self.browser.page
        basename = os.path.basename(file_path)
        
        upload_triggers = [
            "button:has-text('Upload resume')",
            "button:has-text('Cargar curriculum')",
            "button[aria-label*='Upload resume']"
        ]
        
        try:
             resumes_list = page.locator(".jobs-document-card__title").all()
             for res in resumes_list:
                 res_text = res.inner_text().lower()
                 clean_basename = basename.lower().replace(".pdf", "")
                 if clean_basename in res_text:
                     print(f"      ✅ Resume '{basename}' already selected.")
                     res.click()
                     return basename
        except: pass

        file_inputs = page.locator("input[type='file']").all()
        if not file_inputs:
             for sel in upload_triggers:
                 btn = page.locator(sel).first
                 if btn.is_visible():
                     btn.click()
                     self.browser.human_delay(1)
                     file_inputs = page.locator("input[type='file']").all()
                     break
        
        if not file_inputs: return None

        print(f"   📂 Attempting intelligent upload: {basename}")
        target_input = file_inputs[0]
        for inp in file_inputs:
            attr_str = (inp.get_attribute("name") or "") + (inp.get_attribute("id") or "")
            if any(x in attr_str.lower() for x in ["resume", "cv", "curriculum"]):
                target_input = inp
                break

        try:
            target_input.set_input_files(file_path)
            print(f"      ✅ File uploaded: {basename}")
            self.browser.human_delay(3)
            return basename
        except Exception as e:
            print(f"      ❌ Smart Upload Error: {e}")
            return "Upload Failed"
