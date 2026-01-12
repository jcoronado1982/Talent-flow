import time
import yaml
import os
from playwright.sync_api import sync_playwright

def save_cookie_to_creds(cookie_value):
    creds_path = "config/credentials.yaml"
    if os.path.exists(creds_path):
        with open(creds_path, 'r') as f:
            creds = yaml.safe_load(f) or {}
    else:
        creds = {}

    if "gemini_web" not in creds:
        creds["gemini_web"] = {}
    
    creds["gemini_web"]["secure_1psid"] = cookie_value
    
    with open(creds_path, 'w') as f:
        yaml.dump(creds, f)
    print(f"✅ Cookie guardada exitosamente en {creds_path}")

def run_auth_wizard():
    print("🚀 Iniciando Asistente de Autenticación Gemini...")
    print("Se abrirá un navegador. Por favor INICIA SESIÓN EN GOOGLE manualmente.")
    
    with sync_playwright() as p:
        # Usamos un contexto persistente dedicado para auth
        browser = p.chromium.launch_persistent_context(
            user_data_dir="user_data_auth", # Saved separately or can be shared
            headless=False,
            viewport={"width": 1280, "height": 800}
        )
        page = browser.new_page()
        page.goto("https://gemini.google.com")
        
        print("\n⏳ Esperando a que inicies sesión y aparezca la cookie '__Secure-1PSID'...")
        
        found = False
        while not found:
            cookies = browser.cookies()
            for cookie in cookies:
                if cookie["name"] == "__Secure-1PSID" and cookie["domain"].endswith(".google.com"):
                    print("\n🎉 ¡CAPTURA EXITOSA!")
                    print(f"Valor encontrado: {cookie['value'][:10]}...")
                    save_cookie_to_creds(cookie["value"])
                    found = True
                    break
            
            if not found:
                time.sleep(2)
        
        print("Cerrando navegador en 5 segundos...")
        time.sleep(5)
        browser.close()

if __name__ == "__main__":
    run_auth_wizard()
