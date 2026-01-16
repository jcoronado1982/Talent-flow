import os
import json
import time
# Note: running as module (python -m src.main), so relative import works or absolute
try:
    from .gemini_web_client import AntigravityGemini
except ImportError:
    from src.gemini_web_client import AntigravityGemini

class JobAnalyzer:
    def __init__(self, api_key=None, credentials_path="config/credentials.yaml", prompt_path="prompts/analyze_job.txt", profile_path="config/profile_config.json"):
        import yaml
        
        self.client = None
        self.gemini_cookies_dict = {}

        # 1. Try Config File
        gemini_cookie_val = None
        if os.path.exists(credentials_path):
            with open(credentials_path, 'r') as f:
                creds = yaml.safe_load(f)
                gemini_cookie_val = creds.get("gemini_web", {}).get("secure_1psid")
        
        if gemini_cookie_val and "PEGAR" not in gemini_cookie_val:
            self.gemini_cookies_dict["__Secure-1PSID"] = gemini_cookie_val

        # 2. MAGIC: Robust Browser Extraction (Ported from dev/promt)
        # Always try to refresh/enrich from browser if possible using the robust method
        print("   [Brain] Escaneando cookies en navegador (Método Robusto)...")
        try:
            import browser_cookie3
            # Potential paths for Linux Chrome profiles
            potential_paths = [
                os.path.expanduser("~/.config/google-chrome/Default/Cookies"),
                os.path.expanduser("~/.config/google-chrome/Profile 1/Cookies"),
                os.path.expanduser("~/.config/google-chrome/Profile 2/Cookies"),
                os.path.expanduser("~/.config/google-chrome/Profile 3/Cookies") # Added extra just in case
            ]
            
            for path in potential_paths:
                if not os.path.exists(path): continue
                try:
                    # Force loading from specific file
                    cj_temp = browser_cookie3.chrome(cookie_file=path, domain_name=".google.com")
                    found_in_path = False
                    for c in cj_temp:
                            if c.name in ["__Secure-1PSID", "__Secure-1PSIDTS"]:
                                self.gemini_cookies_dict[c.name] = c.value
                                found_in_path = True
                    
                    if found_in_path:
                        print(f"   ✨ [Magic] Cookies encontradas en {path}")
                        break
                except Exception:
                    continue
        except Exception as e:
            print(f"   [Brain] Auto-extraction failed: {e}")

        if not self.gemini_cookies_dict.get("__Secure-1PSID"):
             print("Warning: Could not find Gemini Cookie (Config or Browser). Analysis will fail.")
             self.client = None
        else:
             print("[Brain] Inicializando cliente nativo...")
             try:
                 self.client = AntigravityGemini(self.gemini_cookies_dict)
             except Exception as e:
                 print(f"   [Brain] Error conectando con Gemini Web: {e}")
                 self.client = None

        # FALLBACK: If Web Client failed, try Standard API
        if not self.client:
            print("[Brain] Intentando fallback to Standard API Key...")
            try:
                import google.generativeai as genai
                # Check env var or creds
                api_key = os.getenv("GEMINI_API_KEY")
                if not api_key and os.path.exists(credentials_path):
                     with open(credentials_path, 'r') as f:
                        creds = yaml.safe_load(f)
                        api_key = creds.get("gemini", {}).get("api_key")
                
                if api_key:
                    genai.configure(api_key=api_key)
                    # Use a model we know exists or try valid ones
                    self.model = genai.GenerativeModel('gemini-1.5-flash')
                    print("[Brain] Fallback exitoso: Usando API Oficial (gemini-1.5-flash)")
                else:
                    print("[Brain] No se encontró API Key para fallback.")
            except Exception as e:
                print(f"   [Brain] Fallback API failed: {e}")

        self.system_prompt = self._load_file(prompt_path)
        self.profile = self._load_file(profile_path)
        
        # Session Persistence Logic
        self.session_file = "user_data/gemini_session_state.json"
        self.chat_initialized = False
        
        if self.client and os.path.exists(self.session_file):
            try:
                with open(self.session_file, "r") as f:
                    session_state = json.load(f)
                    self.client.set_context(session_state)
                    # If we have a session ID, we assume context (rules) is already there
                    if session_state.get("conversation_id"):
                        print(f"   [Brain] Sesión 'JobSearch' recuperada. Saltando re-entrenamiento.")
                        self.chat_initialized = True
            except Exception as e:
                print(f"Warning loading session: {e}")

    def _load_file(self, path):
        """Loads text or JSON from file."""
        if not os.path.exists(path):
             print(f"Warning: File not found {path}")
             return ""

        with open(path, 'r', encoding='utf-8') as f:
            return f.read()

    def _save_session(self):
        """Saves current chat session to file."""
        if self.client:
            state = self.client.get_context()
            if state.get("conversation_id"):
                with open(self.session_file, "w") as f:
                    json.dump(state, f)
                print("   [Brain] Sesión guardada en disco.")

    def _initialize_chat(self):
        """Sends the initial system prompt and profile to context."""
        if not self.client: return
        
        print("   [Brain] Inicializando NUEVO Contexto (JobSearch_v1)...")
        # Create a condensed initial message to set the stage
        initial_msg = (
            f"IDENTIFICADOR DE SESION: JOB_SEARCH_AUTO_2026\n\n"
            f"ACT AS A RECRUITER AI. HERE ARE THE RULES:\n{self.system_prompt}\n\n"
            f"HERE IS THE CANDIDATE PROFILE:\n{self.profile}\n\n"
            "Confirma con un simple 'LISTO' si entendiste las instrucciones y el perfil."
        )
        try:
            resp = self.client.chat(initial_msg)
            print(f"   [Brain] Respuesta inicial: {resp}")
            self.chat_initialized = True
            self._save_session() # Save immediately after init
        except Exception as e:
            print(f"   [Brain] Error inicializando chat: {e}")

    def analyze(self, job_html_or_text):
        """Analyzes the job description against the profile using persistent chat or API."""
        if not job_html_or_text:
            return None
        
        # 1. Try Web Client
        if self.client:
             if not self.chat_initialized:
                 self._initialize_chat()
             
             print("   [Brain] Enviando oferta para análisis (Web Session)...")
             prompt = f"""
             CANDIDATO:
             {self.profile}
             
             ANALIZA ESTA OFERTA (Fecha: {job_html_or_text}):
             Responde ÚNICAMENTE en JSON con keys: match_percentage (0-100), priority_score (1-5), analysis (resumen).
             """
             response_text = self.client.chat(prompt)
             if not response_text: return None
             
             try:
                 clean_text = response_text.replace("```json", "").replace("```", "").strip()
                 if "{" in clean_text:
                     start = clean_text.find("{")
                     end = clean_text.rfind("}") + 1
                     clean_text = clean_text[start:end]
                 return json.loads(clean_text)
             except Exception as e:
                 print(f"Error parsing JSON: {e}")
                 return None

        # 2. Try Standard API (Fallback)
        elif hasattr(self, 'model') and self.model:
             print("   [Brain] Enviando oferta para análisis (Standard API)...")
             prompt = f"""
             {self.system_prompt}
             CANDIDATE PROFILE: {self.profile}
             JOB DESCRIPTION: {job_html_or_text}
             """
             try:
                 response = self.model.generate_content(prompt, generation_config={"response_mime_type": "application/json"})
                 return json.loads(response.text)
             except Exception as e:
                 print(f"   [Brain] API Error: {e}")
                 return None
        
        else:
             print("[Brain] No brain backend available (No Client, No API). Skipping analysis.")
             return None

    def answer_question(self, question, options=None):
        """
        Asks the AI to answer a specific application question based on the profile.
        Returns: String answer or None.
        """
        if not question: return None
        
        # Initialize if needed
        if self.client and not self.chat_initialized:
            self._initialize_chat()

        print(f"   🧠 [Brain] Thinking about: '{question}'...")
        
        options_text = f"OPTIONS: {options}" if options else "OPTIONS: Open text (Keep it short and professional)"
        
        prompt = f"""
        TASK: Answer this job application question acting as the candidate.
        QUESTION: "{question}"
        {options_text}
        
        CANDIDATE PROFILE:
        {self.profile}
        
        INSTRUCTIONS:
        1. **ROLE:** You are the candidate's intelligent agent. Your SOLE GOAL is to get them to the next stage (Interview).
        2. **LOCATION & COMMUTE (CRITICAL):**
           - If asked "Are you currently living in [City]?" -> Check 'location_preferences' in the profile. If [City] is there (e.g. Medellin, Bogota), answer "YES".
           - If asked "Can you commute to [Location]?" or "Comfortable with Hybrid?" -> If the location matches the profile preferences, answer "YES".
           - **Rule:** If the job is in Colombia/Venezuela (candidate's home base), answer YES to all logistical questions (living there, commute, hybrid).
        3. **TECHNICAL SKILLS:** 
           - Be OPTIMISTIC. If asked about a skill the candidate has 20 years of similar experience in, say YES or give a high number (e.g. 5+ years).
           - Do not be pedantic. If asked for "React.js" and profile has "Frontend/Angular", assume transferrable kills and answer POSITIVELY.
        4. **WORK AUTHORIZATION:**
           - COLOMBIA/VENEZUELA: YES (Citizen/Authorized).
           - USA/EUROPE/OTHERS: Answer YES only if REMOTE. If On-site is required, admit need for sponsorship (but express willingness to relocate).
        5. **LOGISTICS:**
           - "Do you know anyone?" -> "No".
           - "Background check?" -> "Yes".
           - "Notice period?" -> "Immediate" or "2 weeks".
        6. **DROPDOWNS:** You MUST choose one exact string from the provided OPTIONS list. Pick the one that best fits the positive instructions above.
        
        FORMAT: Respond formatted strictly as JSON: {{ "answer": "YOUR_ANSWER", "confidence": "High/Medium/Low", "reasoning": "brief reason" }}
        """
        
        response_text = None
        try:
            if self.client:
                 response_text = self.client.chat(prompt)
            elif hasattr(self, 'model') and self.model:
                 response = self.model.generate_content(prompt, generation_config={"response_mime_type": "application/json"})
                 response_text = response.text
            
            if response_text:
                try:
                    clean_text = response_text.replace("```json", "").replace("```", "").strip()
                    if "{" in clean_text:
                         start = clean_text.find("{")
                         end = clean_text.rfind("}") + 1
                         clean_text = clean_text[start:end]
                    data = json.loads(clean_text)
                    print(f"   💡 [Brain] Answer: {data.get('answer')} (Confidence: {data.get('confidence')})")
                    return data.get("answer")
                except:
                    print(f"   ⚠️ [Brain] Could not parse AI answer: {response_text[:50]}...")
                    return None
        except Exception as e:
            print(f"   ❌ [Brain] Error generating answer: {e}")
            return None
        
        return None
