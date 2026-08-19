import os
from src.config.settings import Settings

try:
    from src.services.ai.gemini_browser_client import GeminiBrowserClient
except ImportError:
    GeminiBrowserClient = None

try:
    from src.services.ai.local_client import LocalLLMClient
except ImportError:
    LocalLLMClient = None

try:
    from src.services.ai.wasp_client import WaspLLMClient
except ImportError:
    WaspLLMClient = None

try:
    from src.services.ai.wasp_mcp_client import WaspMCPClient
except ImportError:
    WaspMCPClient = None

class AIBackendFactory:
    @staticmethod
    def get_backend(creds, cookies_dict):
        provider = Settings.get_ai_provider()
        print(f"[Brain] ⚙️ AI Provider configured to: '{provider.upper()}'")

        # --- OPTION A: LOCAL AI (Generic OpenAI-Compatible) ---
        if provider == "local":
            if LocalLLMClient:
                print(f"[Brain] Connecting to Local AI @ {Settings.get_local_url()}...")
                try:
                    return LocalLLMClient(
                        model_name=Settings.get_local_model(),
                        base_url=Settings.get_local_url()
                    )
                except Exception as e:
                    print(f"[Brain] ❌ Local LLM Connection failed: {e}")
            else:
                print("[Brain] ❌ LocalLLMClient class not imported.")
            
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
                    model_name = Settings.get_gemini_model()
                    print(f"[Brain] 🤖 Using Model: {model_name}")
                    model = genai.GenerativeModel(model_name)
                    return model
                else:
                    print("[Brain] ❌ No Gemini API Key found in Environment or Credentials.")
            except Exception as e:
                print(f"[Brain] Native Backend test/load failed: {e}")

        # --- OPTION C: WASP AGENT ---
        elif provider == "wasp":
            if WaspLLMClient:
                print(f"[Brain] Connecting to Wasp Agent @ {Settings.get_wasp_url()}...")
                return WaspLLMClient()
            else:
                print("[Brain] ❌ WaspLLMClient class not imported.")
            return None

        # --- OPTION D: WASP MCP ---
        elif provider == "wasp-mcp":
            if WaspMCPClient:
                print(f"[Brain] Connecting to Wasp Agent via MCP...")
                return WaspMCPClient()
            else:
                print("[Brain] ❌ WaspMCPClient class not imported.")
            return None

        return None
