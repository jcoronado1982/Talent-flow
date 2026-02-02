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
    CREDENTIALS_CONFIG = os.path.join(CONFIG_DIR, "credentials.yaml")
    STOP_SIGNAL = os.path.join(DASHBOARD_DIR, "stop.signal")
    ABORT_SIGNAL = os.path.join(DASHBOARD_DIR, "abort.signal")
    INTERACTION_FILE = os.path.join(DASHBOARD_DIR, "interaction.json")
    
    # AI Configuration
    AI_PROVIDER = os.getenv("AI_PROVIDER", "gemini").lower() # Options: "local", "gemini"
    GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3-flash-preview")
    
    @classmethod
    def load_profile(cls):
        if os.path.exists(cls.PROFILE_CONFIG):
            with open(cls.PROFILE_CONFIG, "r") as f:
                return json.load(f)
        return {}

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
