import random
import time
import re

class InteractionHandler:
    def __init__(self, page):
        self.page = page

    def human_delay(self, min_seconds=1, max_seconds=2):
        # Distribución de probabilidad para simular tiempo de reacción humana realista
        # La mayoría de los tiempos serán cercanos al mínimo, con pausas largas ocasionales
        base = random.betavariate(2, 5) * (max_seconds - min_seconds) + min_seconds
        
        # 5% de probabilidad de tener una "micro-distracción" simulando a un humano
        if random.random() < 0.05:
            base += random.uniform(1.5, 3.5)
            
        time.sleep(base)

    def simulate_human_reading(self):
        try:
            for _ in range(random.randint(1, 3)):
                target_x = random.randint(100, 1000)
                target_y = random.randint(100, 700)
                # Mover en pasos en lugar de 'teletransportar' el mouse
                self.page.mouse.move(target_x, target_y, steps=random.randint(5, 12))
                self.human_delay(0.1, 0.4)
            
            total_height = self.page.evaluate("document.body.scrollHeight")
            curr = 0
            while curr < total_height:
                step = random.randint(400, 800)
                curr += step
                self.page.mouse.wheel(0, step)
                self.human_delay(0.2, 0.7)
                if curr > 2500: break
        except Exception as e: print(f"Warning: {e}")

    def click_like_an_ai(self):
        print("\n   🤖 [Browser] Protocolo de clic inteligente...")
        self._hide_linkedin_overlays()
        
        # Ensure we are at the top to see the top-card buttons
        try:
            self.page.evaluate("window.scrollTo(0, 0)")
            time.sleep(0.5)
        except: pass

        # Priority 1: Official LinkedIn Selectors (High Precision)
        content_selectors = [
            "button[data-control-name='jobdetails_topcard_apply']",
            "a[data-control-name='jobdetails_topcard_apply']",
            ".jobs-apply-button--top-card button",
            ".jobs-apply-button--top-card a",
            ".jobs-s-apply button",
            ".jobs-s-apply a",
            "button.jobs-apply-button",
            "a.jobs-apply-button",
            "button[aria-label*='Solicitud sencilla']",
            "button[aria-label*='Easy Apply']",
            "button[aria-label*='Apply']",
            "a[aria-label*='Apply']"
        ]
        
        keywords = ["solicitar", "apply", "postularse", "sencilla", "easy"]
        
        # Optimization: Move the button into view before clicking
        for sel in content_selectors:
            try:
                elements = self.page.locator(sel).all()
                for el in elements:
                    if not el.is_visible(): continue
                    
                    txt = el.inner_text().lower()
                    aria = (el.get_attribute("aria-label") or "").lower()
                    
                    print(f"      [Scan] Found '{txt[:20].strip()}' | Aria: '{aria[:20]}...' (Sel: {sel})")
                    
                    if any(k in txt or k in aria for k in keywords):
                        # Block messaging buttons for sure
                        if any(x in txt or x in aria for x in ["mensaje", "message", "chat"]):
                             continue
                             
                        print(f"      🎯 Match found! Clicking: '{txt.strip() or aria.strip()}'")
                        el.scroll_into_view_if_needed()
                        el.click()
                        return True
            except: pass

        # Priority 2: Very Broad search (Final Effort)
        try:
            # Look for any button or link that contains "Apply" or similar and isn't in a bad place
            all_elements = self.page.locator("button, a").all()
            for el in all_elements:
                try:
                    if not el.is_visible(): continue
                    txt = el.inner_text().lower()
                    aria = (el.get_attribute("aria-label") or "").lower()
                    
                    if any(k in txt or k in aria for k in keywords):
                        # Filter out navigation, messaging, footer, share, etc.
                        if self.page.evaluate("(el) => el.closest('.msg-overlay-list-bubble, .msg-overlay-conversation-bubble, #msg-overlay, footer, nav, .artdeco-dropdown, .jobs-search-results-list')", el):
                            continue
                        
                        if any(x in txt or x in aria for x in ["mensaje", "message", "compartir", "share", "save", "guardar"]):
                            continue

                        print(f"      🎯 Found via broad scan: '{txt.strip() or aria.strip()}'")
                        el.scroll_into_view_if_needed()
                        el.click()
                        return True
                except: continue
        except: pass

        return False

    def _hide_linkedin_overlays(self):
        """Aggressively hides messaging drawer and other distractions via CSS injection."""
        try:
            # Inject CSS to force-hide all messaging artifacts
            self.page.add_style_tag(content="""
                .msg-overlay-list-bubble, 
                .msg-overlay-conversation-bubble, 
                #msg-overlay,
                .msg-overlay-bubble-header,
                aside#msg-overlay {
                    display: none !important;
                    visibility: hidden !important;
                    pointer-events: none !important;
                    height: 0 !important;
                    width: 0 !important;
                    opacity: 0 !important;
                }
            """)
            
            # Legacy JS removal for extra safety
            self.page.evaluate("""
                () => {
                    document.querySelectorAll('.msg-overlay-list-bubble, .msg-overlay-conversation-bubble, #msg-overlay').forEach(el => el.remove());
                }
            """)
        except: pass
