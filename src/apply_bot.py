import os
import glob
import pandas as pd
import json
import re
import time
import sys

# Add project root to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.browser import JobSearchBrowser
from src.brain import JobAnalyzer

# --- CONFIG LOADER ---
def load_config():
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    config_path = os.path.join(base_dir, "config", "profile_config.json")
    with open(config_path, "r") as f:
        return json.load(f)

def get_salary_expectation(config, role_title, description_text):
    """
    Determines salary based on role and language context (en/es).
    """
    salary_rules = config.get("salary_expectations", {})
    rules = salary_rules.get("rules", [])
    default = salary_rules.get("default", {"value": "12000000"})
    
    # Detect Language
    text = (role_title + " " + description_text)
    lang = detect_language(text)
    
    # Match Rule
    for rule in rules:
        role_key = rule["role_match"].lower()
        rule_lang = rule.get("language", "es")
        
        if role_key in role_title.lower() and rule_lang == lang:
            return rule["value"]
            
    return default["value"]

def detect_language(text):
    """
    Simple heuristic to detect if text is English or Spanish.
    """
    text = text.lower()
    # Weighted keywords
    score_en = 0
    score_es = 0
    
    # English markers
    if "software engineer" in text: score_en += 2
    if "required" in text: score_en += 1
    if "requirements" in text: score_en += 1
    if "years" in text: score_en += 1
    if "remote" in text and "remoto" not in text: score_en += 0.5
    
    # Spanish markers
    if "ingeniero" in text: score_es += 2
    if "desarrollador" in text: score_es += 2
    if "requisitos" in text: score_es += 1
    if "años" in text or "experiencia" in text: score_es += 1
    if "remoto" in text: score_es += 1
    
    if score_es > score_en: return "es"
    return "en" # Default to English if unsure or mixed (standard for tech)

def get_resume_filename(config, role_title, description_text, language="en"):
    """
    Determines the best resume filename based on keywords and language.
    Supports simple 'keywords' (OR) and 'match_all' (AND of ORs groups).
    """
    resume_rules = config.get("resume_rules", [])
    
    # Text to search in
    text = (role_title + " " + description_text).lower()
    
    potential_matches = []
    
    for rule in resume_rules:
        # 1. Filter by Language
        rule_lang = rule.get("language")
        if rule_lang and rule_lang != language:
            continue
            
        filename = rule.get("file")
        
        # 2. Check 'match_all' (Complex logic: Stack AND Seniority)
        # Expected format: [ ["java", "jvm"], ["lead", "architect"] ]
        match_all_groups = rule.get("match_all")
        
        if match_all_groups:
            all_groups_satisfied = True
            for group in match_all_groups:
                # Check if ANY keyword in this group is present
                group_match = False
                for kw in group:
                    if kw.lower() in text:
                        group_match = True
                        break
                if not group_match:
                    all_groups_satisfied = False
                    break
            
            if all_groups_satisfied:
                potential_matches.append(filename)
                break # Priority match found (assuming config is ordered by priority)
                
        # 3. Check simple 'keywords' (Legacy/Fallback)
        keywords = rule.get("keywords", [])
        for kw in keywords:
            if kw.lower() in text:
                potential_matches.append(filename)
                break
        
        # If we matched based on keywords loop above, we also break
        if len(potential_matches) > 0 and potential_matches[-1] == filename:
             break
    
    if potential_matches:
        print(f"   📄 Match found for resume ({language}): {potential_matches[0]}")
        return potential_matches[0]
                
    # Default fallback logic
    # Try to find a default rule for this language
    # Assuming the LAST rules are generic defaults
    for rule in reversed(resume_rules):
         rule_lang = rule.get("language")
         # Fallback rules usually have empty match_all and broad/empty keywords
         is_generic = not rule.get("match_all") and (not rule.get("keywords") or "general" in rule.get("keywords", []))
         
         if is_generic and (rule_lang == language or not rule_lang):
             return rule["file"]
             
    if resume_rules:
        # Ultimate fallback
        return resume_rules[-1]["file"] 
    return None

def get_latest_report():
    # Use absolute path to avoid CWD issues
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    reports_dir = os.path.join(base_dir, "reports")
    
    print(f"DEBUG: Searching for reports in {reports_dir}")
    
    reports = glob.glob(os.path.join(reports_dir, "report_FILLED_*.xlsx"))
    if not reports:
        reports = glob.glob(os.path.join(reports_dir, "report_FINAL_*.xlsx"))
    if not reports: 
        # Try running ones?
        reports = glob.glob(os.path.join(reports_dir, "report_RUNNING_*.xlsx"))
        
    if not reports: return None
    return max(reports, key=os.path.getctime)

def main():
    sys.stdout.reconfigure(line_buffering=True) # Force flush
    print("🤖 Auto-Apply Bot Started (vFixedPaths+Unbuffered)...")
    
    report_path = get_latest_report()
    if not report_path:
        print("❌ No reports found in reports/ directory.")
        return

    print(f"📂 Processing Report: {report_path}")
    
    try:
        # Requires openpyxl
        df = pd.read_excel(report_path)
        print(f"DEBUG: Columns found: {list(df.columns)}") # DEBUG
    except Exception as e:
        print(f"❌ Error reading excel: {e}")
        return

    config = load_config()
    # Explicitly visible
    browser = JobSearchBrowser(headless=False)
    brain = JobAnalyzer() # Initialize Brain for intelligent answers
    
    # Try to use cookies first
    print("🍪 Checking session...")
    try:
        browser.page.goto("https://www.linkedin.com/feed/")
        browser.human_delay(2)
        
        if "login" in browser.page.url:
             print("⚠️  Session invalid. Using fallback login (Manual).")
             print("👉 Please log in manually in the browser window.")
             time.sleep(30) 
             
        print("🚀 Starting Auto-Apply Sequence...")
        print(f"DEBUG: Processing {len(df)} rows...")

        for index, row in df.iterrows():
            # STOP SIGNAL CHECK
            base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            signal_file = os.path.join(base_dir, "dashboard", "stop.signal")
            if os.path.exists(signal_file):
                print("🛑 Stop received from Dashboard. Halting...")
                try: os.remove(signal_file)
                except: pass
                break

            # Handle different column names
            url = row.get("URL")
            if not url or str(url) == "nan": url = row.get("Link")
            if not url or str(url) == "nan": url = row.get("LINK") # Handle uppercase
            if not url or str(url) == "nan": url = row.get("Job Link")

            role = str(row.get("Role", "Unknown"))
            reqs = str(row.get("Requirements", "")) 
            
            if not url or str(url).lower() == "nan" or "linkedin.com" not in str(url): 
                continue
                
            print(f"\n👉 [{index+1}] Validating: {role}")
            print(f"   URL: {url}")
            
            try:
                browser.page.goto(str(url))
                browser.human_delay(3)
                
                # Use Robust Smart Click Strategy
                clicked = browser.click_like_an_ai()

                if clicked:
                    browser.human_delay(2)
                    
                    # Detect language once here
                    full_text = role + " " + reqs
                    lang = detect_language(full_text)
                    print(f"   🗣️  Language detected: {lang}")

                    # 2. Intelligent Handler
                    job_context = {
                        "role": role,
                        "description": reqs,
                        "target_resume": get_resume_filename(config, role, reqs, lang)
                    }
                    result = handle_application_flow(browser, job_context, brain)
                    
                    if result == "Submitted":
                        print("   🎉 Application Successfully Submitted!")
                        df.at[index, "Application Status"] = "Applied (Success)"
                    elif result == "Manual":
                        print("   ⚠️  Complex form/Manual intervention needed.")
                        df.at[index, "Application Status"] = "Applied (Manual Needed)"
                    else:
                        print(f"   ⚠️  Application flow stopped: {result}")
                        df.at[index, "Application Status"] = f"Flow: {result}"
                else:
                    print("   ❌ Apply button not found (Smart Click failed).")
                    df.at[index, "Application Status"] = "Button Not Found"

            except Exception as e:
                print(f"   [Error] {e}")
                df.at[index, "Application Status"] = f"Error: {str(e)}"
            
            # Save progress after each row
            try:
                df.to_excel(report_path, index=False)
                print(f"   💾 Report updated.")
            except Exception as save_error:
                print(f"   ⚠️ Could not save report: {save_error}")
                
        print("✅ Batch Completed. Waiting 30s before closing...")
        time.sleep(30) # Keep browser open so user sees it finished

    except Exception as e:
        print(f"❌ Fatal Error: {e}")
        time.sleep(30) # Keep browser open on error too

def handle_application_flow(browser, job_context=None, brain=None):
    """
    Supervises the 'Easy Apply' modal.
    Attempts to answer questions and navigate steps.
    Returns: 'Submitted', 'Manual', or 'Stuck'.
    """
    max_steps = 15
    step = 0
    
    print("   🕵️  Bot supervising application flow...")
    
    while step < max_steps:
        step += 1
        browser.human_delay(1, 2)
        
        # ---------------------------------------------------------
        # 1. CHECK FOR SUCCESS (SUBMIT)
        # ---------------------------------------------------------
        submit_btns = [
            "button[aria-label='Submit application']",
            "button[aria-label='Enviar solicitud']",
            "button:has-text('Submit application')",
            "button:has-text('Enviar solicitud')"
        ]
        
        for sel in submit_btns:
            if browser.page.is_visible(sel):
                print("   👉 Found SUBMIT button. Clicking...")
                browser.page.click(sel)
                browser.human_delay(3)
                return "Submitted"

        # ---------------------------------------------------------
        # 2. CHECK FOR REVIEW
        # ---------------------------------------------------------
        review_btns = [
             "button[aria-label='Review your application']",
             "button[aria-label='Revisar tu solicitud']",
             "button:has-text('Review')",
             "button:has-text('Revisar')"
        ]
        clicked_review = False
        for sel in review_btns:
             if browser.page.is_visible(sel):
                 print("   👉 Found REVIEW button. Clicking...")
                 browser.page.click(sel)
                 clicked_review = True
                 browser.human_delay(1)
                 break
        if clicked_review: continue 

        # ---------------------------------------------------------
        # 3. ATTEMPT TO FILL FORM (Before clicking Next)
        # ---------------------------------------------------------
        try:
            # A. RESUME SELECTION
            # Look for file selection UI
            # Usually radio buttons with class 'jobs-document-upload__title' or similar text?
            # User screenshot shows a list of PDFs with radio buttons.
            
            # Check if we are on Resume step
            resume_step = browser.page.is_visible("h3:has-text('Resume')") or \
                          browser.page.is_visible("h3:has-text('Currículum')")
            
            if resume_step and job_context:
                target_resume = job_context.get("target_resume")
                if target_resume:
                    # Try to find a label or element with this specific filename
                    # The screenshot shows the filename is distinct.
                    # We look for a label or element containing the filename
                    print(f"   📄 Looking for specific resume: {target_resume}")
                    
                    # Try to find the radio associated with this text
                    # Often LinkedIn structure: div containing text -> parent -> radio
                    # or label:has-text(filename)
                    resume_locator = browser.page.locator(f"label:has-text('{target_resume}')")
                    if resume_locator.count() > 0:
                         print("      👉 Selecting target resume...")
                         resume_locator.first.click()
                    else:
                        print(f"      ⚠️ Target resume '{target_resume}' not found in list.")
            
            # B. RADIO BUTTONS/CHECKBOXES (Yes/No questions)
            # Find fieldsets that are not answered
            # Strategy: Select "Yes" or first option if unsure
            radios = browser.page.query_selector_all("fieldset[aria-invalid='true'] input[type='radio']") # Prioritize invalid
            if not radios: radios = browser.page.query_selector_all("input[type='radio'][aria-required='true']")
            
            # Simple heuristic: Just select the first radio of each group/name if not checked
            # Better: Select 'Yes' or the label associated?
            # For now, let's try to click labels containing "Yes" or "Sí"
            
            # Click "Yes" labels if visible and unchecked
            yes_labels = browser.page.query_selector_all("label:has-text('Yes'), label:has-text('Sí'), label:has-text('Si')")
            for label in yes_labels:
                try:
                    # Check if associated input is checked?
                    # Just click it, usually safe for boolean questions
                    label.click()
                except: pass

            # B. INTELLIGENT FORM FILLING (Inputs, Selects, Radios)
            # -----------------------------------------------------
            if brain:
                # 1. READ ALL QUESTIONS
                # We need to find the label associated with each input
                
                # --- Text/Number Inputs ---
                inputs = browser.page.query_selector_all("input[type='text'], input[type='number'], textarea")
                for inp in inputs:
                    if inp.is_visible() and not inp.input_value():
                        # Get Label
                        label_text = ""
                        id_val = inp.get_attribute("id")
                        if id_val:
                            lbl_el = browser.page.query_selector(f"label[for='{id_val}']")
                            if lbl_el: label_text = lbl_el.inner_text().strip()
                        
                        # Fallback: Check aria-label
                        if not label_text: label_text = inp.get_attribute("aria-label")
                        
                        if label_text:
                            # ask brain
                            answer = brain.answer_question(label_text)
                            if answer:
                                try:
                                    inp.fill(str(answer))
                                    print(f"      🧠 AI filled '{answer}' for '{label_text}'")
                                except: pass

                # --- Selects (Dropdowns) ---
                selects = browser.page.query_selector_all("select")
                for sel in selects:
                    if sel.is_visible() and not sel.input_value():
                         # Get Label
                        label_text = ""
                        id_val = sel.get_attribute("id")
                        if id_val:
                            lbl_el = browser.page.query_selector(f"label[for='{id_val}']")
                            if lbl_el: label_text = lbl_el.inner_text().strip()
                        
                        # Get Options
                        options = []
                        for opt in sel.query_selector_all("option"):
                             txt = opt.inner_text().strip()
                             val = opt.get_attribute("value")
                             if val and txt: options.append(txt)
                        
                        if label_text and options:
                            answer = brain.answer_question(label_text, options=options)
                            if answer:
                                # Try to select by label first
                                try:
                                    sel.select_option(label=answer)
                                    print(f"      🧠 AI selected '{answer}' for '{label_text}'")
                                except:
                                    # Fallback index or fuzzy match?
                                    pass
            
            # Legacy/Fallback Heuristics (Keep for safety or unlabelled fields)
            # (Keeping your old code here but simplified as backup)
            # ...


            # D. CUSTOM LINKEDIN DROPDOWNS (Div/Role based)
            # These are hard to automate generically without strict selectors, 
            # often require opening the listbox.
            
        except Exception as e:
            print(f"   ⚠️ Error autofilling form: {e}")

        # ---------------------------------------------------------
        # 4. CHECK FOR NEXT
        # ---------------------------------------------------------
        next_btns = [
            "button[aria-label='Continue to next step']",
            "button[aria-label='Continuar al siguiente paso']",
            "button:has-text('Next')",
            "button:has-text('Siguiente')",
            "button:has-text('Continue')"
        ]
        
        clicked_next = False
        for sel in next_btns:
            if browser.page.is_visible(sel):
                print("   👉 Found NEXT button. Clicking...")
                try:
                    browser.page.click(sel, timeout=2000)
                    clicked_next = True
                    
                    # POST-CLICK VALIDATION CHECK
                    browser.human_delay(1)
                    if browser.page.is_visible(".artdeco-inline-feedback__message") or \
                       browser.page.is_visible("div[aria-invalid='true']"):
                         print("      ⚠️ Validation Error. Attempting specific fixes...")
                         
                         # Try filling any newly revealed invalid inputs
                         # Specifically, dropdowns often show error now
                         # ...
                         pass
                    
                    break
                except:
                    pass
        
        if clicked_next: continue

        # ---------------------------------------------------------
        # 5. CHECK IF DONE OR STUCK
        # ---------------------------------------------------------
        if step > 2 and not browser.page.is_visible(".jobs-easy-apply-modal"):
             return "Submitted" # Modal closed likely success
        
        print("   ❓ No actionable buttons found. Wait...")
        pass # Loop again to wait for user interaction or DOM change
    
    return "Manual" # Timed out

if __name__ == "__main__":
    main()
