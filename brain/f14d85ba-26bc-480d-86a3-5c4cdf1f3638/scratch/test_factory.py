import os
import sys

# Add src to path
sys.path.append(os.getcwd())

from src.config.settings import Settings
from src.services.ai.backend_factory import AIBackendFactory

def test_local_factory():
    print("--- Testing Generic Local Factory ---")
    # Force local provider in Settings class
    Settings.AI_PROVIDER = "local"
    Settings.LOCAL_LLM_URL = "http://localhost:9999/v1"
    Settings.LOCAL_LLM_MODEL = "test-model-123"
    
    # Reload settings/config if needed or just trust the factory reads them
    # Note: Settings reads from os.environ
    
    backend = AIBackendFactory.get_backend({}, {})
    
    if backend:
        print(f"✅ Backend created: {type(backend).__name__}")
        print(f"✅ Target URL: {backend.api_url}")
        print(f"✅ Target Model: {backend.model_name}")
    else:
        print("❌ Backend creation failed.")

if __name__ == "__main__":
    test_local_factory()
