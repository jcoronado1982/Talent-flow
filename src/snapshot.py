import sys
import os
import time
import json

# Ensure src modules can be imported
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.services.browser.client import JobSearchBrowser
from src.services.browser.heuristics import FIND_JOB_LIST_JS
import src.services.storage.database as db

def main():
    db.init_db() # Ensure DB is ready
    print(" [SNAPSHOT TOOL] FULL SCAN MODE")
    print("   Objective: Collect ALL 'Technical Lead' jobs in 'Medellin'")
    print("-" * 30)
    
    max_retries = 3
    for run_attempt in range(max_retries):
        browser = JobSearchBrowser(headless=False)
        total_jobs_found = 0
        
        try:
            if not browser.login("linkedin", "dummy", "dummy"):
                print("❌ Login failed")
                continue

            offset = 0
            while True:  # Page Loop
                print(f"\n📄 Scanning Page (Offset {offset}) with 24h Filter...")
                # SEARCH
                query = "Technical Lead"
                location = "Medellin, Antioquia, Colombia"
                browser.search_jobs("linkedin", query, location, offset=offset, time_filter="r86400")
                time.sleep(5) # Wait for initial render
                
                # 1. Identify Container
                found_data_json = browser.page.evaluate(FIND_JOB_LIST_JS)
                if not found_data_json:
                    print("   ❌ No list container found. Ending scan.")
                    break
                
                data = json.loads(found_data_json)
                container_sel = data.get("container")
                item_sel = data.get("item_tag")
                full_selector = f"{container_sel} > {item_sel}"
                
                print(f"   🎯 Container: {container_sel} | Item: {item_sel}")
                
                # 2. Scroll to load all items on this page
                print(f"      🔄 Starting incremental scroll to hydrate items...")
                for scroll_step in range(1, 7): # More granular steps
                    try:
                        # Scroll by increments
                        scroll_target = scroll_step * 500
                        browser.page.evaluate(f"document.querySelector('{container_sel}').scrollTop = {scroll_target}")
                        time.sleep(1.5)
                        
                        current_count = browser.page.locator(full_selector).count()
                        print(f"         Step {scroll_step}: Found {current_count} items")
                        
                        if current_count >= 25: 
                            browser.page.evaluate(f"document.querySelector('{container_sel}').scrollTop = document.querySelector('{container_sel}').scrollHeight")
                            time.sleep(2)
                            break
                    except:
                        pass

                current_count = browser.page.locator(full_selector).count()
                print(f"   ✅ Page Scroll Complete. Total items in DOM: {current_count}")
                
                if current_count == 0:
                    print("   ⚠️ Zero items found on this page. Stopping.")
                    break

                # EXTRACT TITLES
                print(f"      📝 Extracting titles and saving {current_count} jobs...")
                items = browser.page.locator(full_selector).all()
                valid_items_count = 0
                
                for i, item in enumerate(items):
                    try:
                        # 0. IGNORE EMPTY PLACEHOLDERS - WAIT FOR HYDRATION
                        try:
                            item_text = (item.text_content() or "").strip() 
                            if len(item_text) < 10:
                                print(f"         [DEBUG] Item {i+1} looks empty, attempting hydration...")
                                item.scroll_into_view_if_needed()
                                time.sleep(1.5)
                                item_text = (item.text_content() or "").strip()
                        except:
                            item_text = ""
                            
                        if len(item_text) < 10: 
                            print(f"         [DEBUG] Skipping Item {i+1}: Still too short ({len(item_text)} chars).")
                            continue
                            
                        # 1. INITIAL EXTRACTION (Fallback Data)
                        title = "Unknown Title"
                        url = ""
                        links = item.locator("a").all()
                        for link in links:
                            href = link.get_attribute("href")
                            if href and "/jobs/view/" in href:
                                url = href.split("?")[0]
                                if not url.startswith("http"):
                                    url = f"https://www.linkedin.com{url}"
                                    
                            aria = link.get_attribute("aria-label")
                            if aria and len(aria) > 5 and "LinkedIn" not in aria:
                                title = aria.split(" at ")[0]

                        if title == "Unknown Title":
                             for tag in ["strong", "h3", ".job-card-list__title"]:
                                el = item.locator(tag).first
                                if el.count() > 0:
                                    title = el.inner_text().strip()
                                    if len(title) > 3: break

                        # 2. CLICK TO LOAD DETAILS
                        try:
                            item.click()
                            time.sleep(1.5) 
                            try:
                                browser.page.wait_for_selector(".jobs-description__content", timeout=3000)
                            except: pass
                        except Exception as e:
                            print(f"         [Warning] Failed to click item: {e}")

                        # 3. DEEP EXTRACTION
                        details = browser.extractor.extract_details()
                        
                        # 4. CONSOLIDATE DATA
                        final_role = details.get("title") or title
                        job_data = {
                            "url": url if url else f"InternalId_{i}",
                            "role": final_role,
                            "source": f"LinkedIn Snapshot ({query} - {location})",
                            "company": details.get("company", "Unknown"),
                            "location": details.get("location", location),
                            "work_mode": details.get("work_mode", "Unknown"),
                            "date": details.get("date", "Unknown"),
                            "raw_requirements": (details.get("description") or item_text)[:5000]
                        }

                        # SAVE TO DATABASE
                        if db.save_job(job_data):
                            print(f"         {valid_items_count + 1}. [SAVED] {job_data['role']} @ {job_data['company']}")
                            valid_items_count += 1
                        else:
                            print(f"         {valid_items_count + 1}. [DB FAIL] {job_data['role']}")

                    except Exception as e:
                         print(f"         [Error processing Item {i+1}: {e}]")
                
                print(f"   ✅ Page Complete. Persisted {valid_items_count} valid jobs with full details.")
                
                total_jobs_found += valid_items_count
                offset += 25
            
            print("="*30)
            print(f"🎉 TOTAL JOBS COLLECTED: {total_jobs_found}")
            break # Success, exit retry loop

        except Exception as e:
            print(f"❌ Error in run {run_attempt+1}: {e}")
            import traceback
            traceback.print_exc()
        finally:
            browser.close()
            print("👋 Browser closed.")

if __name__ == "__main__":
    main()
