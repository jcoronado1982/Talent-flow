import os
import tempfile
from playwright.sync_api import sync_playwright
from src.config.settings import Settings

class SessionManager:
    def __init__(self, headless=False, user_data_dir="user_data_auth", guest_mode=False, chrome_profile=None):
        self.playwright = sync_playwright().start()
        self.guest_mode = guest_mode
        self.chrome_profile = chrome_profile
        
        if self.guest_mode:
            # En modo invitado usamos siempre un perfil temporal limpio
            self.user_data_path = tempfile.mkdtemp(prefix="talentflow_guest_")
            print(f"   [Browser] Modo Invitado: Usando perfil temporal {self.user_data_path}")
        else:
            # Separate user_data_dir by profile to avoid collisions
            suffix = f"_{chrome_profile.replace(' ', '_').lower()}" if chrome_profile else ""
            self.user_data_path = os.path.join(Settings.BASE_DIR, f"{user_data_dir}{suffix}")
            
        self.context = self._launch_context(headless)
        self.page = self.context.pages[0] if self.context.pages else self.context.new_page()
        
        if not self.guest_mode:
            self._inject_cookies()

    def _launch_context(self, headless):
        print(f"   [Browser] Launching with persistent profile: {self.user_data_path}")
        try:
            return self.playwright.chromium.launch_persistent_context(
                user_data_dir=self.user_data_path,
                headless=headless,
                executable_path="/usr/bin/google-chrome",
                viewport={"width": 1280, "height": 800},
                args=[
                    "--disable-blink-features=AutomationControlled",
                    "--disable-infobars",
                    "--no-sandbox",
                    "--start-maximized"
                ],
                ignore_default_args=["--enable-automation", "--no-sandbox"],
                java_script_enabled=True,
                timeout=20000 
            )
        except Exception as e:
            print(f"   [Browser] Primary launch failed: {e}. Falling back to temp profile.")
            temp_dir = tempfile.mkdtemp(prefix="talentflow_temp_")
            return self.playwright.chromium.launch_persistent_context(
                user_data_dir=temp_dir,
                headless=headless,
                executable_path="/usr/bin/google-chrome",
                args=[
                    "--disable-blink-features=AutomationControlled"
                ],
                ignore_default_args=["--enable-automation"],
                java_script_enabled=True
            )

    def _inject_cookies(self):
        # Check if we already have the critical cookie in our persistent profile
        # This prevents overwriting a valid manual login with stale system cookies
        try:
            existing = self.context.cookies("https://gemini.google.com")
            if any(c['name'] == '__Secure-1PSID' for c in existing):
                print("   [Browser] ✅ Sesión válida detectada. Omitiendo inyección de cookies del sistema.")
                return
        except Exception as e:
            print(f"   [Browser] Warning checking existing cookies: {e}")

        try:
            import browser_cookie3
            if self.chrome_profile:
                potential_paths = [os.path.expanduser(f"~/.config/google-chrome/{self.chrome_profile}/Cookies")]
            else:
                potential_paths = [
                    os.path.expanduser("~/.config/google-chrome/Profile 1/Cookies"),
                    os.path.expanduser("~/.config/google-chrome/Default/Cookies"),
                    os.path.expanduser("~/.config/google-chrome/Profile 2/Cookies")
                ]
            domains = [".google.com", ".linkedin.com"]
            
            all_cookies = []
            for domain in domains:
                for path in potential_paths:
                    if not os.path.exists(path): continue
                    try:
                        cj = browser_cookie3.chrome(cookie_file=path, domain_name=domain)
                        for c in cj:
                            all_cookies.append({
                                "name": c.name, 
                                "value": c.value, 
                                "domain": c.domain, 
                                "path": c.path, 
                                "secure": bool(c.secure), 
                                "expires": c.expires if c.expires else -1
                            })
                        if all_cookies: break # Found cookies for this domain, move to next
                    except: continue
            
            if all_cookies:
                print(f"   [Browser] Inyectando {len(all_cookies)} cookies de sesión desde Chrome...")
                self.context.add_cookies(all_cookies)
        except Exception as e:
            print(f"   [Browser] Error inyectando cookies: {e}")

    def close(self):
        self.context.close()
        self.playwright.stop()
