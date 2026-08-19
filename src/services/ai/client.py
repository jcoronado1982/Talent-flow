import os
import json
from src.config.settings import Settings
from src.domain.interfaces import IJobAnalyzer
from .prompts import PromptManager
from .backend_factory import AIBackendFactory

class JobAnalyzer(IJobAnalyzer):
    def __init__(self, api_key=None):
        _debug_log = "dashboard/processor_debug.log"
        try:
             with open(_debug_log, "a") as f: f.write(f"[{os.getpid()}] JobAnalyzer: Init start.\n")
        except: pass

        self.prompts = PromptManager()
        self.creds = Settings.load_credentials()
        
        try:
             with open(_debug_log, "a") as f: f.write(f"[{os.getpid()}] JobAnalyzer: Extracting cookies...\n")
        except: pass
        self.cookies_dict = self._extract_cookies()
        
        try:
             with open(_debug_log, "a") as f: f.write(f"[{os.getpid()}] JobAnalyzer: Getting backend...\n")
        except: pass
        self.backend = AIBackendFactory.get_backend(self.creds, self.cookies_dict)
        
        # --- MODEL TRACKING ---
        self.model_name = "Unknown Model"
        if self.backend:
            # Try various common attributes for model identification
            if hasattr(self.backend, "model_name"):
                self.model_name = self.backend.model_name
            elif hasattr(self.backend, "_model_name"):
                self.model_name = self.backend._model_name
            elif hasattr(self.backend, "model"):
                self.model_name = str(self.backend.model)
        
        try:
             with open(_debug_log, "a") as f: f.write(f"[{os.getpid()}] JobAnalyzer: Backend ready ({self.model_name}).\n")
        except: pass

    def _extract_cookies(self):
        cookies = {}
        # From config
        psid = self.creds.get("gemini_web", {}).get("secure_1psid")
        if psid and "PEGAR" not in psid: cookies["__Secure-1PSID"] = psid
        return cookies

    def _chat(self, msg):
        if not self.backend:
            raise RuntimeError("No AI Backend initialized.")
            
        if hasattr(self.backend, "chat"): 
            return self.backend.chat(msg)
        elif hasattr(self.backend, "generate_content"):
            resp = self.backend.generate_content(msg, generation_config={"response_mime_type": "application/json"})
            return resp.text
        return None

    def analyze(self, job_text):
        if not job_text: return None
        full_prompt = self.prompts.get_analysis_prompt(job_text)
        resp = self._chat(full_prompt)
        
        data = self._parse_json(resp)
        if data and isinstance(data, dict):
            # Inject the model name into the parsed data only if the AI didn't provide one
            if not data.get("ai_model") or data.get("ai_model") in ["Unknown Model", "Unknown"]:
                data["ai_model"] = self.model_name

        return {
            "data": data,
            "raw_response": resp,
            "raw_prompt": full_prompt,
            "ai_model": self.model_name
        }

    def answer_form(self, form_schema, resolved_salary=None, resolved_currency=None, job_location=None):
        full_prompt = self.prompts.get_form_prompt(form_schema, resolved_salary, resolved_currency, job_location)
        resp = self._chat(full_prompt)
        return self._parse_json(resp) or {}, full_prompt

    def answer_question(self, question, options=None, input_type=None, resolved_salary=None, job_location=None):
        resp = self._chat(self.prompts.get_question_prompt(question, options, input_type, resolved_salary, job_location))
        data = self._parse_json(resp)
        return data.get("answer") if data else None

    def _parse_json(self, text):
        if not text: return None
        try:
            import re
            clean = re.sub(r'<think>.*?</think>', '', text, flags=re.DOTALL)
            clean = clean.replace("```json", "").replace("```", "").strip()
            if "{" in clean:
                clean = clean[clean.find("{"):clean.rfind("}")+1]
            
            data = json.loads(clean)
            if not isinstance(data, dict): return data

            # --- ROBUST KEY MAPPING ---
            # 1. Match Score
            if "match_percentage" not in data:
                for alt in ["match_score", "score", "fit_score", "percentage"]:
                    if alt in data:
                        data["match_percentage"] = data[alt]
                        break
            
            # 2. Verdict
            if "verdict" not in data:
                for alt in ["hiring_decision", "decision", "result"]:
                    if alt in data:
                        data["verdict"] = data[alt]
                        break
            
            # 3. Skills
            if "mandatory_skills" not in data:
                for alt in ["required_skills", "skills_identified", "skills"]:
                    if alt in data:
                        data["mandatory_skills"] = data[alt]
                        break
            
            return data
        except: return None

