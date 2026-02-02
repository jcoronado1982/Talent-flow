import time
from .heuristics import FIND_JOB_LIST_JS
from .session import SessionManager
from .interaction import InteractionHandler
from .extractor import DataExtractor
from .scanners import SearchScanner

class JobSearchBrowser:
    def __init__(self, headless=False, user_data_dir="user_data_auth", chrome_profile=None):
        self.session = SessionManager(headless=headless, user_data_dir=user_data_dir, chrome_profile=chrome_profile)
        self.page = self.session.page
        self.context = self.session.context
        
        self.interaction = InteractionHandler(self.page)
        self.extractor = DataExtractor(self.page)
        self.scanner = SearchScanner(self.page, self.interaction, self.extractor, monitor=None) # Will be set or used via collector

    def human_delay(self, min_seconds=1, max_seconds=2):
        self.interaction.human_delay(min_seconds, max_seconds)

    def simulate_human_reading(self):
        self.interaction.simulate_human_reading()

    def click_like_an_ai(self):
        return self.interaction.click_like_an_ai()

    def close(self):
        self.session.close()

    def login(self, site, email, password):
        print(f"Checking session for {site}...")
        try:
            if site == "linkedin":
                # Quickly check if already logged in
                self.page.goto("https://www.linkedin.com/feed/", timeout=30000)
                self.human_delay(1.5, 2.5)
                
                if "/feed" in self.page.url:
                    print("   ✅ [Session] Sesión activa detectada. Saltando login.")
                    return True

                print(f"   🔑 [Login] Iniciando sesión manual...")
                self.page.goto("https://www.linkedin.com/login")
                self.page.fill("#username", email)
                self.page.fill("#password", password)
                self.page.click("button[type='submit']")
                
                # Faster wait
                try:
                    self.page.wait_for_url("**/feed/**", timeout=20000)
                    print("   ✅ [Login] Login exitoso.")
                    return True
                except:
                    print("   ⚠️ [Login] No se pudo confirmar el login o requiere verificación manual.")
                    return False
        except Exception as e: 
            print(f"Login error: {e}")
            return False

    def search_jobs(self, site, query, location, time_filter="r259200", offset=0):
        print(f"Searching {site} (Offset: {offset})...")
        if site == "linkedin":
            url = f"https://www.linkedin.com/jobs/search/?keywords={query}&location={location}&f_TPR={time_filter}"
            if offset > 0:
                url += f"&start={offset}"
            
            for attempt in range(3):
                try:
                    self.page.goto(url, timeout=60000)
                    self.human_delay(2.5, 3.5)
                    
                    # --- DYNAMIC LIST DISCOVERY ---
                    print("   🧠 [Nav] Analyzing DOM to find job list...")
                    import json
                    found_data_json = self.page.evaluate(FIND_JOB_LIST_JS)

                    
                    if found_data_json:
                        try:
                            # Try parsing JSON (new format)
                            data = json.loads(found_data_json)
                            container = data.get("container")
                            item_tag = data.get("item_tag", "li")
                            
                            print(f"   ✅ [Nav] Dynamic success! List: {container}, Items: {item_tag}")
                            self.scanner.set_dynamic_selector(container, item_tag)
                        except:
                            # Fallback for unexpected string return (legacy safety)
                            print(f"   ✅ [Nav] Dynamic success (Legacy String): {found_data_json}")
                            self.scanner.set_dynamic_selector(found_data_json, "li")
                            
                        break 
                    else:
                        print("   ⚠️ [Nav] Heuristic failed. Trying legacy wait...")
                        # Fallback to standard wait just in case
                        self.page.wait_for_selector(".jobs-search-results-list", timeout=5000)
                        self.scanner.set_dynamic_selector(".jobs-search-results-list", "li")
                        break
                        
                except Exception as e:
                    print(f"   ⚠️ [Nav] Error loading search (Attempt {attempt+1}/3): {e}")
                    
                    # Auto-Dump DOM for debugging (User Request)
                    try:
                        timestamp = int(time.time())
                        dump_path = f"debug_failure_{timestamp}.html"
                        with open(dump_path, "w") as f:
                            f.write(self.page.content())
                        print(f"   📸 [DEBUG] DOM Dump saved to: {dump_path}")
                    except: pass

                    if attempt < 2:
                        wait_time = (attempt + 1) * 5
                        print(f"   ⏳ Waiting {wait_time}s before retry...")
                        self.interaction.human_delay(wait_time, wait_time + 1)
                    else:
                        print("   ❌ [Nav] Failed to load search page after 3 attempts.")

    def scan_search_results(self, site, limit, callback_fn, monitor=None):
        return self.scanner.scan_results(site, limit, callback_fn, monitor=monitor)
