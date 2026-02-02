import os
import json
import time
import requests
import random
import re

class AntigravityGemini:
    """
    Cliente NO OFICIAL para interactuar con Gemini Web (gemini.google.com).
    Simula tener un navegador abierto para usar "Gemini Advanced" si la cuenta lo tiene.
    """
    
    def __init__(self, cookies_dict):
        self.session = requests.Session()
        
        # Headers que imitan un navegador real (Chrome Linux)
        self.headers = {
            "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Referer": "https://gemini.google.com/",
            "Origin": "https://gemini.google.com",
            "x-same-domain": "1"
        }
        self.session.headers.update(self.headers)
        
        # Cargar cookies
        # Necesitamos principalmente __Secure-1PSID y __Secure-1PSIDTS
        requests.utils.add_dict_to_cookiejar(self.session.cookies, cookies_dict)
        
        self.SNlM0e = None
        self.conversation_id = None
        self.response_id = None
        self.choice_id = None
        
        # Verificar Auth inicial (opcional, para obtener SNlM0e)
        self._handshake()

    def _handshake(self):
        print("   [Antigravity] Conectando a Gemini Web...")
        try:
            resp = self.session.get("https://gemini.google.com/app", timeout=10)
            if resp.status_code == 200:
                # Extraer SNlM0e (Nonce vital para Google)
                match = re.search(r'"SNlM0e":"(.*?)"', resp.text)
                if match:
                    self.SNlM0e = match.group(1)
                    print(f"   [Antigravity] Handshake exitoso. (Nonce: {self.SNlM0e[:10]}...)")
                else:
                    print("   [Antigravity] No se encontró SNlM0e. Es posible que las cookies hayan expirado.")
            else:
                print(f"   [Antigravity] Error de conexión: {resp.status_code}")
        except Exception as e:
            print(f"   [Antigravity] Error en Handshake: {e}")

    def chat(self, prompt, image_url=None):
        if not self.SNlM0e:
            print("   [Antigravity] No se puede chatear sin Handshake previo.")
            return None

        # Endpoint de chat RPC
        url = "https://gemini.google.com/_/BardChatUi/data/assistant.lamda.BardFrontendService/StreamGenerate"
        
        # Parámetros locos de Google RPC
        params = {
            "bl": "boq_assistant-bard-web-server_20260126.07_p2", # Updated
            "_reqid": str(random.randint(100000, 999999)),
            "rt": "c"
        }

        # Payload structure (Reverse-engineered)
        # Es un array anidado horrible. 
        # [None, "[[prompt], null, [conversation_id, response_id, choice_id]]"]
        
        message_struct = [
            [prompt],
            None,
            [self.conversation_id, self.response_id, self.choice_id] 
        ]
        
        f_req = json.dumps([None, json.dumps(message_struct)])
        
        data = {
            "f.req": f_req,
            "at": self.SNlM0e
        }
        
        try:
            resp = self.session.post(url, data=data, params=params, timeout=30)
            
            if resp.status_code != 200:
                print(f"   [Antigravity] Error {resp.status_code}")
                return None

            # Parsear respuesta (Stream de arrays JSON con prefijos raros)
            # Normalmente viene:  )]}'\n\n[[...]]
            text = resp.text
            if text.startswith(")]}'"):
                text = text[5:] # Quitar prefijo de seguridad
            
            try:
                response_json = json.loads(text)
            except json.JSONDecodeError as e:
                # Handle streaming response (Extra data) or multiple chunks
                if "Extra data" in str(e):
                    # Try splitting by newline and taking the largest/first valid one
                    # Usually the main payload is the first one
                    valid_json = None
                    for line in text.split('\n'):
                        line = line.strip()
                        if not line: continue
                        try:
                            valid_json = json.loads(line)
                            # Google payload is usually a list
                            if isinstance(valid_json, list):
                                response_json = valid_json
                                break
                        except: continue
                    
                    if not valid_json:
                        raise e # Re-raise if we couldn't rescue
                else:
                    raise e
            
            # Navegar la estructura anidada para encontrar el texto y los IDs de contexto
            # Esta estructura cambia a veces. Es frágil.
            # Normalmente: response_json[0][2] contiene el payload real
            
            chat_data = json.loads(response_json[0][2])
            
            # Texto de respuesta
            # chat_data[0][0] -> [content, ...]
            # chat_data[0][6] -> imagenes?
            # chat_data[1] -> [conversation_id, response_id]
            # chat_data[4] -> [ [choice_id, ...], ...]
            
            generated_text = chat_data[4][0][1][0]
            
            # Actualizar contexto
            self.conversation_id = chat_data[1][0]
            self.response_id = chat_data[1][1]
            self.choice_id = chat_data[4][0][0]
            
            return generated_text

        except Exception as e:
            print(f"   [Antigravity] Parse Error: {e}")
            # print(resp.text[:500]) # Debug
            return None

    def get_context(self):
        return {
            "conversation_id": self.conversation_id,
            "response_id": self.response_id,
            "choice_id": self.choice_id
        }

    def set_context(self, context):
        self.conversation_id = context.get("conversation_id")
        self.response_id = context.get("response_id")
        self.choice_id = context.get("choice_id")
