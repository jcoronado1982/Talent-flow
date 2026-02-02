import os
import shutil
import sqlite3
from src.config.settings import Settings
from src.services.storage.database import init_db

def reset_project():
    print("🚀 Starting project reset protocol...")
    
    # 1. Reset Database
    if os.path.exists(Settings.DB_PATH):
        print(f"   🗑️ Deleting database: {Settings.DB_PATH}")
        os.remove(Settings.DB_PATH)
    
    print("   ✨ Re-initializing fresh database...")
    init_db()
    
    # 2. Clear User Data (AI Session)
    gemini_session = os.path.join(Settings.DATA_DIR, "gemini_session_state.json")
    if os.path.exists(gemini_session):
        print(f"   🗑️ Deleting AI session state: {gemini_session}")
        os.remove(gemini_session)
    
    # 3. Clear Browser Profile
    user_data_auth = os.path.join(Settings.BASE_DIR, "user_data_auth")
    if os.path.exists(user_data_auth):
        print(f"   🗑️ Deleting browser persistent profile: {user_data_auth}")
        try:
            shutil.rmtree(user_data_auth)
        except Exception as e:
            print(f"      ⚠️ Could not delete browser profile: {e}")

    # 4. Clear stop signal if exists
    if os.path.exists(Settings.STOP_SIGNAL):
        os.remove(Settings.STOP_SIGNAL)

    print("\n✅ Project and Database have been successfully reset!")

if __name__ == "__main__":
    reset_project()
