from src.browser import JobSearchBrowser
from src.brain import JobAnalyzer
import os

def test_browser():
    print("Testing Browser...")
    try:
        browser = JobSearchBrowser(headless=True)
        browser.navigate_to("https://example.com")
        content = browser.get_page_content()
        print(f"Browser validation: Page content length: {len(content)}")
        browser.close()
        print("Browser Test PASSED")
    except Exception as e:
        print(f"Browser Test FAILED: {e}")

def test_brain_init():
    print("Testing Brain Init...")
    # Mock key to test init structure, not actual call
    try:
        brain = JobAnalyzer(api_key="fake_key")
        print("Brain Init PASSED (Structure only)")
    except Exception as e:
        print(f"Brain Init FAILED: {e}")

if __name__ == "__main__":
    test_browser()
    test_brain_init()
