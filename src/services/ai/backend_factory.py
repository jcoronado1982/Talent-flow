import os
from src.config.settings import Settings

try:
    from src.services.ai.gemini_browser_client import GeminiBrowserClient
except ImportError:
    GeminiBrowserClient = None

try:
    from src.services.ai.local_client import OllamaClient
except ImportError:
    OllamaClient = None

class AIBackendFactory:
    @staticmethod
    def get_backend(creds, cookies_dict):
        provider = Settings.AI_PROVIDER
        print(f"[Brain] ⚙️ AI Provider configured to: '{provider.upper()}'")

        # --- OPTION A: LOCAL AI (OLLAMA) ---
        if provider == "local":
            if OllamaClient:
                print("[Brain] Connecting to Local AI (Ollama)...")
                try:
                    import requests
                    resp = requests.get("http://localhost:8000/v1/models", timeout=1)
                    if resp.status_code == 200:
                        print("[Brain] 🏎️ Local GPU (vLLM) detected. Using DeepSeek R1 14B AWQ.")
                        return OllamaClient(model_name="casperhansen/deepseek-r1-distill-qwen-14b-awq")
                    else:
                        print("[Brain] ⚠️ Ollama service found but returned non-200.")
                except Exception:
                    print("[Brain] ❌ Ollama NOT reachable. Please run 'ollama serve'.")
            else:
                print("[Brain] ❌ OllamaClient class not imported.")
            
            # If user explicitly wanted local and it failed, we warn deeply but DO NOT fallback automatically
            # to respect the "Switch" decision, UNLESS we want to be nice. 
            # For this request, user implies strict switch ("si quiero cambiar... cambio el parametro").
            # But to avoid breaking app, we returns None or maybe fallback if critical?
            # Let's return None to force user to fix local if they selected local.
            print("[Brain] ⚠️ Strict Mode: Local AI failed and provider='local'. Returning None.")
            return None

        # --- OPTION B: CLOUD AI (GEMINI) ---
        elif provider == "gemini":
            print("[Brain] Checking for Official Gemini API Key...")
            try:
                import google.generativeai as genai
                key = os.getenv("GEMINI_API_KEY") 
                if not key:
                    key = creds.get("gemini", {}).get("api_key")
                
                if key:
                    print(f"[Brain] ✅ API Key found ({key[:5]}...). Testing Native Backend...")
                    genai.configure(api_key=key)
                    # Use flash-2.0 or whatever is standard
                    print(f"[Brain] 🤖 Using Model: {Settings.GEMINI_MODEL}")
                    model = genai.GenerativeModel(Settings.GEMINI_MODEL)
                    return model
                else:
                    print("[Brain] ❌ No Gemini API Key found in Environment or Credentials.")
            except Exception as e:
                print(f"[Brain] Native Backend test/load failed: {e}")

        return None
