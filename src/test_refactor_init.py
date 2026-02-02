import sys
import os

# Ensure src is in path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

try:
    print("🧪 Testing ApplyBotSupervisor initialization...")
    from src.app.bots.apply.supervisor import ApplyBotSupervisor
    supervisor = ApplyBotSupervisor(headless=True)
    print("✅ ApplyBotSupervisor initialized successfully.")
    supervisor.browser.close()
    
    print("\n🧪 Testing JobSearchBrowser initialization...")
    from src.services.browser.client import JobSearchBrowser
    browser = JobSearchBrowser(headless=True)
    print("✅ JobSearchBrowser initialized successfully.")
    
    print("\n🧪 Testing JobAnalyzer initialization...")
    from src.services.ai.client import JobAnalyzer
    analyzer = JobAnalyzer()
    print("✅ JobAnalyzer initialized successfully.")
    
    print("\n🎉 All core components initialized successfully with the new modular architecture!")
    
    # Cleanup browser if it was started
    if hasattr(browser, "close"):
        browser.close()

except Exception as e:
    print(f"\n❌ Verification Failed: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)
