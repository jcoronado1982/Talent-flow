import requests
import json
import os
import re

class LocalLLMClient:
    """
    Generic client for Ollama and OpenAI-Compatible APIs.
    Uses native Ollama /api/chat with format='json' when possible.
    """
    def __init__(self, model_name=None, base_url=None):
        from src.config.settings import Settings
        self.model_name = model_name or Settings.get_local_model()
        raw_url = (base_url or Settings.get_local_url()).rstrip('/')

        # Detect Ollama native URL (http://localhost:11434)
        # Strip /v1 to get the base Ollama URL and use /api/chat for JSON mode
        if '/v1' in raw_url:
            self.ollama_base = raw_url.replace('/v1', '')
        else:
            self.ollama_base = raw_url

        self.api_url = f"{self.ollama_base}/api/chat"
        print(f"[Local AI] Initialized for model '{self.model_name}' @ {self.api_url} (JSON mode)")

    def chat(self, prompt):
        """Send chat completion request via native Ollama API with JSON mode enforced."""
        payload = {
            "model": self.model_name,
            "messages": [{"role": "user", "content": prompt}],
            "stream": False,
            "format": "json",
            "options": {"temperature": 0.0}
        }

        try:
            response = requests.post(self.api_url, json=payload, timeout=1200)

            if response.status_code != 200:
                print(f"[Local AI Error] Status: {response.status_code}, Body: {response.text[:500]}")

            response.raise_for_status()

            data = response.json()
            raw_text = data['message']['content']
            return raw_text

        except Exception as e:
            print(f"   [Local AI] Inference failed: {e}")
            raise e

    def generate_content(self, msg, **kwargs):
        """Compatibility method for standard interface."""
        return self.chat(msg)

    def close(self):
        pass
