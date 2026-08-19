import os
import json
import yaml

class Settings:
    BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    CONFIG_DIR = os.path.join(BASE_DIR, "config")
    DATA_DIR = os.path.join(BASE_DIR, "user_data")
    DB_PATH = os.path.join(BASE_DIR, "talentflow.db")
    DASHBOARD_DIR = os.path.join(BASE_DIR, "dashboard")
    
    # Files
    PROFILE_CONFIG = os.path.join(CONFIG_DIR, "profile_config.json")
    CV_CONFIG = os.path.join(CONFIG_DIR, "cv_profile.json")
    CREDENTIALS_CONFIG = os.path.join(CONFIG_DIR, "credentials.yaml")
    STOP_SIGNAL = os.path.join(DASHBOARD_DIR, "stop.signal")
    ABORT_SIGNAL = os.path.join(DASHBOARD_DIR, "abort.signal")
    INTERACTION_FILE = os.path.join(DASHBOARD_DIR, "interaction.json")
    
    # AI Configuration (Defaults/Fallbacks)
    _DEFAULT_AI_PROVIDER = os.getenv("AI_PROVIDER", "gemini").lower()
    _DEFAULT_GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3-flash-preview")
    _DEFAULT_LOCAL_MODEL = os.getenv("LOCAL_LLM_MODEL", "gemma4-optimized")
    _DEFAULT_LOCAL_URL = os.getenv("LOCAL_LLM_URL", "http://localhost:11434/v1")
    _DEFAULT_WASP_URL = "http://localhost:3000"
    _DEFAULT_WASP_MCP_BIN = "mcp_server"
    _DEFAULT_WASP_CWD = "/home/jcoronado/Desktop/steel_wasp"

    @classmethod
    def get_ai_provider(cls):
        profile = cls.load_profile()
        return profile.get("ai_config", {}).get("provider", cls._DEFAULT_AI_PROVIDER).lower()

    @classmethod
    def get_gemini_model(cls):
        profile = cls.load_profile()
        return profile.get("ai_config", {}).get("cloud_model", cls._DEFAULT_GEMINI_MODEL)

    @classmethod
    def get_local_model(cls):
        profile = cls.load_profile()
        return profile.get("ai_config", {}).get("local_model", cls._DEFAULT_LOCAL_MODEL)

    @classmethod
    def get_local_url(cls):
        profile = cls.load_profile()
        return profile.get("ai_config", {}).get("local_url", cls._DEFAULT_LOCAL_URL)

    @classmethod
    def get_wasp_url(cls):
        profile = cls.load_profile()
        return profile.get("ai_config", {}).get("wasp_url", cls._DEFAULT_WASP_URL)

    @classmethod
    def get_wasp_mcp_bin(cls):
        profile = cls.load_profile()
        return profile.get("ai_config", {}).get("wasp_mcp_bin", cls._DEFAULT_WASP_MCP_BIN)

    @classmethod
    def get_wasp_cwd(cls):
        profile = cls.load_profile()
        return profile.get("ai_config", {}).get("wasp_cwd", cls._DEFAULT_WASP_CWD)

    @classmethod
    def get_max_workers(cls):
        profile = cls.load_profile()
        # Default to 5 if not found, preserving the user's latest choice
        return profile.get("ai_config", {}).get("max_workers", 5)

    # Legacy attributes for backward compatibility (pointing to the methods)
    @property
    def AI_PROVIDER(self): return self.get_ai_provider()
    @property
    def GEMINI_MODEL(self): return self.get_gemini_model()
    @property
    def LOCAL_LLM_MODEL(self): return self.get_local_model()
    @property
    def LOCAL_LLM_URL(self): return self.get_local_url()

    @classmethod
    def load_profile(cls):
        profile = {}
        if os.path.exists(cls.PROFILE_CONFIG):
            try:
                with open(cls.PROFILE_CONFIG, "r") as f:
                    profile = json.load(f)
            except:
                pass
        
        # Backward compatibility / Hybrid loading:
        # If resume_rules not in profile (or as a safety), try to load from cv_profile.json
        cv_rules = cls.load_cv_profile()
        if cv_rules:
            profile["resume_rules"] = cv_rules
            
        return profile

    @classmethod
    def load_cv_profile(cls):
        if os.path.exists(cls.CV_CONFIG):
            try:
                with open(cls.CV_CONFIG, "r") as f:
                    return json.load(f)
            except:
                return []
        return []

    @classmethod
    def load_credentials(cls):
        if os.path.exists(cls.CREDENTIALS_CONFIG):
            with open(cls.CREDENTIALS_CONFIG, "r") as f:
                return yaml.safe_load(f)
        return {}

    @classmethod
    def ensure_dirs(cls):
        os.makedirs(cls.DATA_DIR, exist_ok=True)
        os.makedirs(cls.DASHBOARD_DIR, exist_ok=True)
