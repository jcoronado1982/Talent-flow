import random
import time
import re

class InteractionHandler:
    def __init__(self, page):
        self.page = page

    def human_delay(self, min_seconds=1, max_seconds=2):
        time.sleep(random.uniform(min_seconds, max_seconds))

    def simulate_human_reading(self):
        try:
            for _ in range(random.randint(1, 2)):
                self.page.mouse.move(random.randint(100, 1000), random.randint(100, 700))
                time.sleep(random.uniform(0.1, 0.15))
            
            total_height = self.page.evaluate("document.body.scrollHeight")
            curr = 0
            while curr < total_height:
                step = random.randint(600, 1000)
                curr += step
                self.page.mouse.wheel(0, step)
                time.sleep(random.uniform(0.3, 0.5))
                if curr > 2000: break
        except Exception as e: print(f"Warning: {e}")

    def click_like_an_ai(self):
        print("\n   🤖 [Browser] Protocolo de clic inteligente...")
        pattern = re.compile(r"(solicitar|apply|sencilla|now)", re.IGNORECASE)
        
        try:
            btn = self.page.get_by_role("button", name=pattern).first
            if btn.is_visible():
                btn.click(timeout=3000)
                return True
        except: pass

        try:
            text_btn = self.page.get_by_text(pattern).first
            if text_btn.is_visible():
                text_btn.click(force=True)
                return True
        except: pass

        selectors = [".jobs-apply-button", ".jobs-s-apply button", "button[aria-label*='Apply']", ".jobs-apply-button--top-card button"]
        for sel in selectors:
            if self.page.is_visible(sel):
                self.page.locator(sel).first.click()
                return True

        try:
            return self.page.evaluate("""
                () => {
                    const xpath = "//button[contains(translate(., 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'apply') or contains(translate(., 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'solicitar')]";
                    const btn = document.evaluate(xpath, document, null, XPathResult.FIRST_ORDERED_NODE_TYPE, null).singleNodeValue;
                    if (btn) { btn.click(); return true; }
                    return false;
                }
            """)
        except: pass
        return False
