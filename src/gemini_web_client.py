import requests
import json
import re
import random
import string
import os
import time
import socket

# --- FORCE IPV4 PATCH ---
# Esto obliga a requests a usar solo IPv4, evitando el bloqueo de rango IPv6 de Google.
orig_getaddrinfo = socket.getaddrinfo

def getaddrinfo_ipv4_only(host, port, family=0, type=0, proto=0, flags=0):
    return orig_getaddrinfo(host, port, socket.AF_INET, type, proto, flags)

socket.getaddrinfo = getaddrinfo_ipv4_only
# ------------------------

class AntigravityGemini:
    """
    Cliente nativo Antigravity para Gemini Web.
    Re-implementación limpia y controlada de la lógica de conexión.
    """
    
    HEADERS = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Referer": "https://gemini.google.com/",
        "Origin": "https://gemini.google.com",
        "X-Same-Domain": "1",
    }
    
    def __init__(self, cookies: dict):
        self.session = requests.Session()
        self.session.headers.update(self.HEADERS)
        self.session.cookies.update(cookies)
        self.snlm0e = None
        self.sid = None
        self.req_id = int("".join(random.choices(string.digits, k=4)))
        
        # Pre-cargar pixel fantasma para modo Pro/Ultra
        try:
            # 1x1 GIF transparente base64 decoded
            self.dummy_image = b'\x47\x49\x46\x38\x39\x61\x01\x00\x01\x00\x80\x00\x00\x00\x00\x00\xFF\xFF\xFF\x21\xF9\x04\x01\x00\x00\x00\x00\x2C\x00\x00\x00\x00\x01\x00\x01\x00\x00\x02\x01\x44\x00\x3B'
        except:
            self.dummy_image = None
            
        print("   🧱 [NativeLib] Inicializando cliente...")
        self._handshake()

    def _handshake(self):
        """Obtiene el SNlM0e (Nonce) necesario para firmar requests."""
        try:
            resp = self.session.get("https://gemini.google.com/app", timeout=10)
            resp.raise_for_status()
            
            # Buscar SNlM0e en el HTML
            match = re.search(r'"SNlM0e":"(.*?)"', resp.text)
            if match:
                self.snlm0e = match.group(1)
                self.sid = self.session.cookies.get("__Secure-1PSID")
                print(f"   🔑 [NativeLib] Handshake exitoso. SNlM0e: {self.snlm0e[:10]}...")
            else:
                print("   ❌ [NativeLib] Error: No se encontró SNlM0e.")
                raise Exception("SNlM0e not found")
        except Exception as e:
            print(f"   ❌ [NativeLib] Error de conexión: {e}")
            raise

    def chat(self, prompt, model="fast"):
        """
        Envía un mensaje. 
        model='pro' activa el hack de imagen para Ultra.
        """
        # Anti-Ban Jitter: Espera aleatoria para parecer humano
        jitter = random.uniform(1.0, 2.5)
        print(f"   ⏳ [NativeLib] Human-Delay: {jitter:.2f}s...")
        time.sleep(jitter)

        if not self.snlm0e:
            self._handshake()
            
        params = {
            "bl": "boq_assistant-bard-web-server_20240227.13_p0", # From constants.py
            "_reqid": str(self.req_id),
            "rt": "c"
        }
        
        # Construir payload
        # Si es PRO, inyectamos imagen para forzar endpoint multimodal
        image_data = None
        if model.lower() in ["pro", "thinking"]:
             image_data = self.dummy_image
             
        payload = self._construct_payload(prompt, image_data)
        
        # Form Data para batchexecute
        form_data = {
            "f.req": json.dumps([None, json.dumps(payload)]),
            "at": self.snlm0e
        }
        
        # Retry logic for 429 errors
        # import time removed (using global)
        max_retries = 3
        backoff = 2 # seconds
        
        for attempt in range(max_retries + 1):
            try:
                print(f"   📤 [NativeLib] Enviando (Mode={model}, Attempt={attempt+1})...")
                resp = self.session.post(
                    "https://gemini.google.com/_/BardChatUi/data/assistant.lamda.BardFrontendService/StreamGenerate",
                    params=params,
                    data=form_data,
                    timeout=60
                )
                resp.raise_for_status()
                self.req_id += 1000
                
                # Parsear respuesta (simplicado)
                return self._parse_response(resp.text)
                
            except requests.exceptions.HTTPError as e:
                if e.response.status_code == 429:
                    if attempt < max_retries:
                        wait_time = backoff * (2 ** attempt) + random.uniform(0, 1)
                        print(f"   ⏳ [NativeLib] Rate Limit (429). Esperando {wait_time:.2f}s...")
                        time.sleep(wait_time)
                        continue
                    else:
                        return f"Error: Rate Limit Exceeded (429) after {max_retries} retries."
                else:
                    return f"Error: {e}"
            except Exception as e:
                return f"Error: {e}"

    def _construct_payload(self, prompt, image_bytes=None):
        """Construye el array JSON esotérico de Google."""
        
        # Estructura BASE para texto (debe estar anidada correctamente)
        # [[prompt, 0, None, None], None, [IDs]]
        msg_internal = [prompt, 0, None, None]
        
        if image_bytes:
             # Si hay imagen, subimos y cambiamos la estructura
             image_url = self._upload_image(image_bytes)
             # Estructura multimodal: [prompt, 0, None, [[[url, 1]]], ...]
             msg_internal = [
                 prompt,
                 0, 
                 None, 
                 [[[image_url, 1]]],
                 None, None, None
             ]

        # Estructura final anidada
        # CORRECCION: msg_internal ya es una lista, no envolver de nuevo.
        # CORRECCION: Los IDs de contexto deben ser cadenas vacías para iniciar.
        return [
            msg_internal,
            None,
            [self.cid, self.rid, self.rcid]
        ]

    # Gestión básica de contexto (se actualizaría con la respuesta)
    rcid = ""
    rid = ""
    cid = ""

    def _upload_image(self, img_bytes):
        """Sube imagen a Google Content Push (Método Simple de Utils.py)."""
        url = "https://content-push.googleapis.com/upload/"
        headers = {
            "Push-ID": "feeds/mcudyrk2a4khkz", # From constants.py
            "Content-Type": "application/octet-stream"
        }
        
        # Subida directa simple (como hace la librería original)
        r = requests.post(url, data=img_bytes, headers=headers)
        r.raise_for_status()
        return r.text

    def _parse_response(self, text):
        """Extrae texto y actualiza IDs de conversación."""
        try:
            # Desempaquetar batchexecute
            lines = text.splitlines()
            for line in lines:
                if "wrb.fr" in line:
                    # Encontró un bloque de datos
                    raw_json = json.loads(line)
                    base_data = json.loads(raw_json[0][2])
                    
                    if len(base_data) > 1 and base_data[1]:
                        self.cid = base_data[1][0] # conversation_id
                        self.rid = base_data[1][1] # response_id
                        print(f"   🐛 [Debug] CID: {self.cid} | RID: {self.rid}")
                    
                    if len(base_data) > 4 and base_data[4]:
                         if len(base_data[4]) > 0 and len(base_data[4][0]) > 0:
                             self.rcid = base_data[4][0][0] # choice_id
                             print(f"   🐛 [Debug] RCID: {self.rcid}")

                    # 2. Extraer respuesta de texto
                    try:
                        response_text = base_data[4][0][1][0]
                        return response_text
                    except:
                        pass
                        
            return "No se pudo parsear respuesta. (Raw data received)"
        except Exception as e:
            print(f"Error parseando respuesta Gemini: {e}")
            return None

    def get_context(self):
        """Devuelve el estado actual de la sesión."""
        return {
            "conversation_id": self.cid, # map cid to conversation_id
            "response_id": self.rid,
            "choice_id": self.rcid
        }

    def set_context(self, context):
        """Restaura una sesión previa."""
        if not context: return
        self.cid = context.get("conversation_id", "")
        self.rid = context.get("response_id", "")
        self.rcid = context.get("choice_id", "")
        print(f"   🔄 [NativeLib] Sesión restaurada: {self.cid[:10]}...")
