import os
import json
from src.config.settings import Settings
from .prompts import PromptManager
from .backend_factory import AIBackendFactory

class JobAnalyzer:
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
        
        try:
             with open(_debug_log, "a") as f: f.write(f"[{os.getpid()}] JobAnalyzer: Backend ready.\n")
        except: pass
        self.chat_initialized = False
        self.session_file = os.path.join(Settings.DATA_DIR, "gemini_session_state.json")
        self._load_session()

    def _extract_cookies(self):
        cookies = {}
        # From config
        psid = self.creds.get("gemini_web", {}).get("secure_1psid")
        if psid and "PEGAR" not in psid: cookies["__Secure-1PSID"] = psid
        
        # From Browser - DISABLED for stability in headless mode
        # try:
        #    import browser_cookie3
        #    ...
        # except: pass
        
        return cookies

    def _load_session(self):
        if hasattr(self.backend, "set_context") and os.path.exists(self.session_file):
            try:
                with open(self.session_file, "r") as f:
                    state = json.load(f)
                    self.backend.set_context(state)
                    if state.get("conversation_id"): self.chat_initialized = True
            except: pass

    def _initialize_chat(self):
        # SKIP initialization handshake to save time/tokens with vLLM
        self.chat_initialized = True
        return

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
        self._initialize_chat()
        resp = self._chat(self.prompts.get_analysis_prompt(job_text))
        return self._parse_json(resp)

    def answer_form(self, form_schema):
        self._initialize_chat()
        resp = self._chat(self.prompts.get_form_prompt(form_schema))
        return self._parse_json(resp) or {}

    def answer_question(self, question, options=None, input_type=None):
        self._initialize_chat()
        resp = self._chat(self.prompts.get_question_prompt(question, options, input_type))
        data = self._parse_json(resp)
        return data.get("answer") if data else None

    def _parse_json(self, text):
        if not text: return None
        try:
            clean = text.replace("```json", "").replace("```", "").strip()
            if "{" in clean:
                clean = clean[clean.find("{"):clean.rfind("}")+1]
            return json.loads(clean)
        except: return None
