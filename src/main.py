import os
import yaml
import json
from datetime import datetime
from src.browser import JobSearchBrowser
from src.brain import JobAnalyzer

# Helper to load yaml config
def load_config(path):
    with open(path, 'r') as f:
        return yaml.safe_load(f)

# --- USER CONFIGURATION ---
# Set to an integer (e.g., 10, 50) or None for UNLIMITED (all found jobs)
JOB_LIMIT = 5 
# --------------------------

def main():
    # Load configuration
    try:
        credentials = load_config("config/credentials.yaml")
        # For now, we expect the API key to be in the environment variable or passed strictly.
        # Ideally, we should not store API keys in plain text files if we can avoid it, 
        # but for this local tool, getting it from env is best.
        api_key = os.environ.get("GEMINI_API_KEY") 
        if not api_key:
            print("ERROR: GEMINI_API_KEY environment variable not set.")
            return
    except Exception as e:
        print(f"Error loading configuration: {e}")
        return

    # Initialize Monitor FIRST for immediate feedback
    from src.monitor import SearchMonitor
    monitor = SearchMonitor()
    monitor.log("⚙️ Inicializando proceso...")
    
    # Clean up stale signals
    try: os.remove("dashboard/stop.signal")
    except: pass
    
    # Initialize components
    monitor.log("🌐 Abriendo navegador...")
    browser = JobSearchBrowser(headless=False) # Headful for demo/debugging
    brain = JobAnalyzer(api_key=api_key)
    
    monitor.log("🔑 Verificando credenciales...")

    report_data = []

    try:
        # LinkedIn Test Workflow
        site = "linkedin"
        
        # 1. Login
        email = credentials.get(site, {}).get("email")
        password = credentials.get(site, {}).get("password")
        
        if email and "CHANGE_ME" not in email:
            monitor.log("👤 Iniciando sesión en LinkedIn...")
            browser.login(site, email, password)
        else:
            print("Warning: LinkedIn credentials missing.")
            monitor.log("⚠️ Credenciales no configuradas.")
            input("Press Enter in terminal if you need to log in manually...")

        # Load profile config
        profile = load_config("config/profile_config.json")
        target_roles = profile.get("target_roles", ["Technical Lead"])
        locations = profile.get("location_preferences", ["Bogotá"])
        
        # MONITOR INIT
        total_combos = len(target_roles) * len(locations)
        monitor.update(total_combinations=total_combos, status="Running")
        monitor.log(f"Configuración cargada: {total_combos} combinaciones.")
        
        print(f"Loaded {len(target_roles)} roles and {len(locations)} locations.")
        
        # Callback for processing jobs
        def process_job_callback(details, url):
            # Check for STOP SIGNAL (Instant)
            if os.path.exists("dashboard/stop.signal"):
                monitor.log("🛑 Deteniendo en oferta actual...")
                return False # Stop scanning

            # Update monitor: One more job processed (estimated)
            monitor.state["current_job_index"] += 1
            idx = monitor.state["current_job_index"]
            total = monitor.state["jobs_in_current_batch"]
            monitor.log(f"Analizando oferta {idx}/{total}: {url.split('?')[0]}")
            monitor.save()

            description = details.get("description", "")
            date_posted = details.get("date", "Unknown")
            
            print(f"   [Main] Analyze Job: {url}")
            if description:
                # Add date context to brain
                analysis = brain.analyze(f"PUBLICATION DATE: {date_posted}\n\n{description}")
                
                if analysis:
                    match_score = analysis.get('match_percentage', 0)
                    print(f"Analysis Result: {match_score}% Match")
                    
                    # Register match in monitor (even if low score, just for stats?) 
                    # Actually, let's only register 'good' matches in the list
                    
                    # Filter: Production Threshold >= 30%
                    if match_score >= 30:
                        # Append the details we enriched in browser.py
                        item = {
                            "source": site,
                            "url": url,
                            "role": details.get("title", current_role), # Use exact title if found
                            "date": date_posted,
                            "company": details.get("company", "Unknown"),
                            "location": details.get("location", "Unknown"), 
                            "work_mode": details.get("work_mode", "Unknown"),
                            "raw_requirements": details.get("raw_requirements", ""),
                            "analysis": analysis
                        }
                        report_data.append(item)
                        # Monitor Match
                        monitor.add_match(item, match_score)
                        monitor.log(f"✅ Coincidencia encontrada: {match_score}% ({details.get('company')})")
                    else:
                        print(f"   [Filter] Skipped job (Match {match_score}% < 30%)")
                else:
                    monitor.log("❌ Error en análisis de oferta.")
            else:
                 monitor.log("⚠️ No se pudo extraer descripción.")
            
            return True # Continue scanning

        # Prepare Report File
        timestamp = datetime.now().strftime('%d_%m_%Y_%H_%M')
        report_file = f"reports/report_RUNNING_{timestamp}.xlsx"
        monitor.log(f"Reporte: {report_file}")

        # --- DYNAMIC SEARCH LOOP ---
        combo_index = 0
        stop_requested = False
        current_role = "Unknown" # Initialize for callback scope
        
        for role in target_roles:
            current_role = role # Update for callback
            if stop_requested: break
            
            for loc in locations:
                if stop_requested: break
                
                # Check for STOP SIGNAL (File Check)
                if os.path.exists("dashboard/stop.signal"):
                    stop_requested = True
                    monitor.log("🛑 Deteniendo búsqueda por usuario...")
                    # Delete signal
                    try: os.remove("dashboard/stop.signal")
                    except: pass
                    break

                combo_index += 1
                search_loc = loc.split("(")[0].strip()
                
                # Update Monitor Context
                monitor.update(
                    current_combination_index=combo_index,
                    current_role=role,
                    current_location=search_loc,
                    current_job_index=0,
                    jobs_in_current_batch=JOB_LIMIT 
                )
                monitor.log(f"🔎 Buscando: {role} en {search_loc}...")
                print(f"\n--- Searching for: {role} in {search_loc} ---")
                
                try:
                    # Try 24 Hours First
                    browser.search_jobs(site, role, search_loc, time_filter="r86400") # Past 24 hours
                    count = browser.scan_search_results(site, limit=JOB_LIMIT, callback_fn=process_job_callback)
                    
                    # Fallback to Past Week if no results
                    if count == 0:
                        monitor.log(f"⚠️ Sin resultados en 24h. Ampliando a Semana Pasada...")
                        browser.search_jobs(site, role, search_loc, time_filter="r604800") # Past Week
                        browser.scan_search_results(site, limit=JOB_LIMIT, callback_fn=process_job_callback)
                    
                    # SAVE PROGRESS
                    if report_data:
                        monitor.log(f"💾 Guardando progreso ({len(report_data)} ofertas)...")
                        browser.create_google_sheet(report_data, output_filename=report_file)
                        
                except Exception as loop_e:
                    monitor.log(f"⚠️ Error en bucle: {loop_e}")
                    print(f"Error in search loop: {loop_e}")
                    continue
        
        # Final Save
        # Final Save Logic - EXECUTED ALWAYS IF DATA EXISTS
        if report_data:
            monitor.log("💾 Generando reporte FINAL...")
            final_name = report_file.replace("RUNNING", "FINAL")
            
            # Create (or Overwrite) the final file with all data
            browser.create_google_sheet(report_data, output_filename=final_name)
            
            monitor.log(f"🏁 Reporte guardado: {final_name}")
            monitor.update(status="Stopped")
            
            # Optional: Clean up the RUNNING file if it exists to avoid duplicates
            if os.path.exists(report_file):
                try: os.remove(report_file)
                except: pass
        else:
            monitor.log("🏁 Finalizado sin ofertas para reporte.")
            monitor.update(status="Stopped")

    except Exception as e:
        print(f"An error occurred: {e}")
    finally:
        if 'browser' in locals():
            browser.close()
        print("Browser session closed.")

    
    # Legacy report block removed (Integrated into loop)
    pass 

if __name__ == "__main__":
    main()
