# ==============================================================================
# ⚠️ CRITICAL COMPONENT - DO NOT MODIFY WITHOUT EXPLICIT USER INSTRUCTION ⚠️
# ==============================================================================
# This file handles the browser-based job collection.
# Any changes here can break the scraping logic/selectors.
# ==============================================================================
import os
import time
from src.config.settings import Settings
from src.services.browser.client import JobSearchBrowser
import src.services.storage.database as db

class JobCollector:
    def __init__(self, monitor, headless=False):
        self.monitor = monitor
        self.settings = Settings.load_credentials()
        self.profile = Settings.load_profile()
        self.headless = headless
        from src.audit import AuditLogger
        self.audit = AuditLogger()

    def collect(self, job_limit=200, max_pages=None, single_combo_only=False):
        self.monitor.log(f"Phase 1: Starting Job Collection (Limit: {job_limit}, MaxPages: {max_pages}, SingleCombo: {single_combo_only})...")
        browser = JobSearchBrowser(headless=self.headless)
        
        try:
            # Login
            site = "linkedin"
            email = self.settings.get(site, {}).get("email")
            password = self.settings.get(site, {}).get("password")
            
            if email and "CHANGE_ME" not in email:
                self.monitor.log("👤 Iniciando sesión en LinkedIn...")
                browser.login(site, email, password)
            else:
                self.monitor.log("⚠️ Credenciales no configuradas.")
                return 0

            target_roles = self.profile.get("target_roles", [])
            locations = self.profile.get("location_preferences", [])
            
            total_collected_count = 0
            
            # --- LOOP ---
            stop_requested = False
            combo_index = 0
            
            # Context for saving
            current_context = {"role": "Unknown"}

            def save_raw_callback(details, url):
                if os.path.exists(Settings.STOP_SIGNAL): return False
                
                # Check if exists to avoid dup work (optional, but DB handles unique URL)
                # Save as Pending
                job_item = {
                    "source": f"{site} ({current_context['role']})", # Save Category here
                    "url": url,
                    "role": details.get("title", "Unknown"), # Keep extraction as Role (Title)
                    "date": details.get("date", "Unknown"),
                    "company": details.get("company", "Unknown"),
                    "location": details.get("location", "Unknown"), 
                    "work_mode": details.get("work_mode", "Unknown"),
                    "raw_requirements": details.get("description", "")[:5000],
                    "analysis": None,
                }
                
                # We need a way to distinct "Pending Analysis" from "Processed". 
                # We'll use the 'status' field in DB default='Pending'.
                # But save_job logic needs to be checked.
                # Just saving it with 0 match score for now is safe.
                
                result = db.save_job(job_item) # Upsert
                if result == "INSERTED":
                    self.monitor.log(f"📥 [Fase 1] Oferta [{details.get('work_mode', '???')}] guardada: {details.get('company')}")
                elif result == "DUPLICATE":
                    self.monitor.log(f"♻️ [Fase 1] Oferta [{details.get('work_mode', '???')}] duplicada: {details.get('company')}")
                
                return result

            for role in target_roles:
                if stop_requested: break
                current_context["role"] = role
                
                for loc in locations:
                    if stop_requested: break
                    if os.path.exists(Settings.STOP_SIGNAL): 
                        stop_requested = True; break
                    
                    # Audit Constraint: Single Combo Check (Inner Loop)
                    if single_combo_only and combo_index >= 1:
                         self.monitor.log(f"🛑 [AUDIT] Deteniendo por restricción de combinación única.")
                         stop_requested = True
                         break

                    combo_index += 1
                    search_loc = loc.split("(")[0].strip()
                    self.monitor.log(f"🔎 Buscando: {role} en {search_loc}...")

                    try:
                        # URL-based Pagination Loop with Time Fallback
                        filters = ["r86400"] if single_combo_only else ["r86400", "r604800"] # 24h only for tests
                        current_filter_idx = 0
                        combo_collected = 0
                        
                        while current_filter_idx < len(filters) and combo_collected < job_limit:
                            current_filter = filters[current_filter_idx]
                            filter_label = "24h" if current_filter == "r86400" else "1 semana"
                            
                            offset = 0
                            page_num = 1
                            found_any_in_filter = False
                            
                            while combo_collected < job_limit:
                                if stop_requested: break
                                if os.path.exists(Settings.STOP_SIGNAL): 
                                    stop_requested = True; break

                                self.monitor.log(f"📄 [{role}] Página {page_num} (Offset: {offset})...")
                                
                                # 1. Search with current filter and offset
                                browser.search_jobs(site, role, search_loc, time_filter=current_filter, offset=offset)
                                
                                # 2. Scan current page deeply
                                current_page_limit = job_limit - combo_collected
                                count, real_total = browser.scan_search_results(site, limit=current_page_limit, callback_fn=save_raw_callback, monitor=self.monitor)
                                
                                # count only includes NEW items saved. 
                                # We need to know if the page was totally empty or just full of duplicates.
                                if real_total == 0:
                                    self.monitor.log(f"🏁 [Collector] Fin de resultados para {role} (LinkedIn agotado).")
                                    break # Truly no results
                                
                                found_any_in_filter = True
                                combo_collected += count
                                total_collected_count += count
                                offset += 25
                                page_num += 1

                                # Safety Cap: Don't paginate forever if real_total extraction failed
                                if offset > (job_limit + 100):
                                    self.monitor.log(f"🛑 [Collector] Límite de seguridad de offset alcanzado ({offset}). Avanzando.")
                                    break

                                # Dynamic Break: If we've reached the total LinkedIn results reported in the header
                                if real_total and offset >= (real_total + 10): # Small buffer for LinkedIn's "X+ results"
                                    self.monitor.log(f"🏁 [Collector] Se ha alcanzado el total de LinkedIn ({real_total}).")
                                    break
                                
                                # Audit Constraint: Max Pages Check
                                if max_pages and (page_num - 1) >= max_pages:
                                    self.monitor.log(f"🛑 [AUDIT] Límite de páginas alcanzado ({max_pages}).")
                                    break
                                
                                target_goal = real_total if real_total else job_limit
                                self.monitor.log(f"📊 Progreso [{role}]: {combo_collected}/{target_goal} recolectadas.")

                            if found_any_in_filter:
                                break # Move to next search combo
                            else:
                                if current_filter == "r86400":
                                    self.monitor.log(f"⚠️ Sin resultados en 24h para {role}. Probando 1 semana...")
                                    current_filter_idx += 1
                                else:
                                    break

                    except Exception as e:
                        self.monitor.log(f"⚠️ Error en colección: {e}")
                        
            browser.close()
            self.monitor.log(f"✅ Fase 1 Completada. Total recolectadas: {total_collected_count}")
            return total_collected_count

        except Exception as e:
            self.monitor.log(f"❌ Error Fatal en Colector: {e}")
            if browser: browser.close()
            return 0
