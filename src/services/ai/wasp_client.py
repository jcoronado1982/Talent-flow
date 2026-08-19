import requests
import json
import os

class WaspLLMClient:
    """
    Cliente para conectar con Steel Wasp (Agente Rust) 
    operando en modo Microservicio.
    """
    def __init__(self, host=None):
        from src.config.settings import Settings
        host = host or Settings.get_wasp_url()
        self.url = f"{host.rstrip('/')}/api/prompt"
        self.model_name = self._detect_real_model() or "Steel Wasp (REST)"
        print(f"🚀 [Steel Wasp] Conectado a {self.url} (Model: {self.model_name})")

    def _detect_real_model(self):
        """Intenta leer el modelo real desde el config.json de Steel Wasp."""
        try:
            from src.config.settings import Settings
            wasp_cwd = Settings.get_wasp_cwd()
            config_path = os.path.join(wasp_cwd, "config.json")
            if os.path.exists(config_path):
                import json
                with open(config_path, "r") as f:
                    cfg = json.load(f)
                    return cfg.get("model")
        except:
            pass
        return None

    def chat(self, prompt: str) -> str:
        """
        Envía un prompt al agente y recibe la respuesta síncrona.
        Refresca el nombre del modelo dinámicamente.
        """
        self.model_name = self._detect_real_model() or "Steel Wasp (REST)"
        try:
            # Cuerpo de la solicitud que espera el agente Rust
            payload = {"prompt": prompt}
            
            # Realizamos la petición POST
            response = requests.post(
                self.url, 
                json=payload, 
                timeout=180  # Tiempo de espera extendido para IA (180s)
            )
            
            if response.status_code == 200:
                # El agente responde con {"response": "..."}
                data = response.json()
                return data.get("response", "No se recibió contenido en la respuesta.")
            else:
                return f"⚠️ Error del Servidor ({response.status_code}): {response.text}"
                
        except requests.exceptions.Timeout:
            return "⏳ Error: El Agente tardó demasiado en responder (Timeout 180s)."
        except Exception as e:
            return f"❌ Error de conexión con Steel Wasp: {str(e)}"

    def generate_content(self, msg, **kwargs):
        """Método de compatibilidad para interfaces de IA estándar."""
        return self.chat(msg)

    def close(self):
        pass
