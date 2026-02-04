
import sys
import os
import argparse
import time

# Add src to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '.')))

from src.services.browser.client import JobSearchBrowser
from src.services.storage import database as db
from src.monitor import SearchMonitor

def inject_url(url):
    print(f"🚀 Injecting job: {url}")
    monitor = SearchMonitor()
    browser = JobSearchBrowser(headless=False)
    
    try:
        browser.page.goto(url)
        browser.human_delay(3)
        
        # Scrape basic details
        # (This logic is usually in collector.py, we adapt it here)
        try:
            title = browser.page.inner_text("h1")
            company = browser.page.inner_text(".topcard__org-name-link")
        except:
            title = "Manual Job"
            company = "LinkedIn Job"
            
        print(f"   [Scraping] {company} - {title}")
        
        # Expand description
        try:
            browser.page.click("button.show-more-less-html__button--more")
            browser.human_delay(1)
        except: pass
        
        description = browser.page.inner_text(".jobs-description__content")
        
        item = {
            "source": "manual",
            "url": url,
            "role": title,
            "company": company,
            "location": "Manual",
            "work_mode": "Unknown",
            "raw_requirements": description,
            "requirements": description,
            "date": "Today"
        }
        
        status = db.save_job(item)
        print(f"   [DB] {status}")
        
        if status != "ERROR":
            print("\n✅ Job added to queue. Run 'PYTHONPATH=. python3 src/main.py' to analyze it.")
            
    except Exception as e:
        print(f"❌ Error: {e}")
    finally:
        browser.close()

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Inject a LinkedIn job URL manually")
    parser.add_argument("url", help="LinkedIn Job URL")
    args = parser.parse_args()
    
    inject_url(args.url)
