import requests
import json
import os
import re

class OllamaClient:
    """
    Client for vLLM (OpenAI-Compatible) Server.
    Kept class name 'OllamaClient' for factory compatibility, but logic is pure OpenAI.
    """
    def __init__(self, model_name="casperhansen/deepseek-r1-distill-qwen-14b-awq", base_url="http://localhost:8000/v1"):
        self.model_name = model_name
        self.base_url = base_url
        self.api_url = f"{base_url}/chat/completions"
        print(f"[vLLM Client] Initialized for {self.model_name} @ {self.api_url}")

    def chat(self, prompt):
        """Send chat completion request to vLLM."""
        payload = {
            "model": self.model_name,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.0,
            "max_tokens": 2500,
            "stop": ["###", "<|endoftext|>"]
        }

        try:
            # vLLM (OpenAI API)
            response = requests.post(self.api_url, json=payload, timeout=300) # Higher timeout for heavy load
            
            if response.status_code != 200:
                print(f"[vLLM Error] Status: {response.status_code}, Body: {response.text}")
            
            response.raise_for_status()
            
            data = response.json()
            raw_text = data['choices'][0]['message']['content']
            print(f"[DEBUG] Raw LLM Response (FULL): {raw_text}") 
            
            # DeepSeek R1 cleanup (strip <think> tags)
            clean_text = re.sub(r'<think>.*?</think>', '', raw_text, flags=re.DOTALL).strip()
            
            # JSON cleanup (Robust Regex)
            try:
                # Find valid JSON block
                json_match = re.search(r'\{.*\}', clean_text, re.DOTALL)
                if json_match:
                    clean_text = json_match.group(0)
                else:
                    # Fallback for simple markdown stripping if regex fails (unlikely)
                    clean_text = clean_text.replace("```json", "").replace("```", "").strip()
            except:
                pass

            return clean_text
            
        except Exception as e:
            print(f"   [vLLM] Inference failed: {e}")
            raise e

    def close(self):
        pass
