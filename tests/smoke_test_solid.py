import os
import sys
from unittest.mock import MagicMock

# Add root to path
ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(ROOT_DIR)

def test_manager_init_default():
    print("Testing SearchBotManager initialization with defaults...")
    from src.app.bots.search.manager import SearchBotManager
    try:
        # We mock nuke_zombies and other heavy stuff if needed, 
        # but let's see if it just imports and inits.
        # We'll mock Settings to avoid loading real files
        manager = SearchBotManager(headless=True)
        print("✅ Manager initialized successfully with defaults.")
        assert manager.brain is not None
        assert manager.scraper_class is not None
        return True
    except Exception as e:
        print(f"❌ Manager initialization FAILED: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    success = test_manager_init_default()
    sys.exit(0 if success else 1)
