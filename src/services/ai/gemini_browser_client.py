import time
try:
    from src.services.browser.session import SessionManager
except ImportError:
    # Fallback to local import if needed or adjust path
    import sys
    import os
    sys.path.append(os.getcwd())
    from src.services.browser.session import SessionManager

class GeminiBrowserClient:
    def __init__(self, cookies_dict=None):
        """
        Initializes the Browser-based Gemini client.
        :param cookies_dict: Ignored, but kept for compatibility with Factory signature.
                             SessionManager handles cookies internally.
        """
        # Usamos modo invitado para evitar problemas de "Signed Out"
        # Esto permite chatear sin login, lo cual es suficiente para este caso.
        self.session = SessionManager(headless=True, guest_mode=True)
        self.page = self.session.page
        self.is_ready = False
        print("   [GeminiBrowser] Client initialized.")

    def _ensure_login(self):
        if self.is_ready: return
        
        print("   [GeminiBrowser] Navigating to Gemini...")
        try:
            self.page.goto("https://gemini.google.com/app", timeout=60000)
        except Exception as e:
            print(f"   [GeminiBrowser] Navigation warning: {e}")

        # Check if we are logged in by looking for the input box
        try:
            self.page.wait_for_selector("div[contenteditable='true']", timeout=10000)
            print("   [GeminiBrowser] Ready. Input box found.")
            self.is_ready = True
        except:
            print("   [GeminiBrowser] Input box not found immediately. Checking for login...")
            # Here we might need to handle login redirects if cookies failed, 
            # but SessionManager sends a persistent context, so it should be fine.
            # If consistent failure, we might need to dump page content.
            self.is_ready = True # Try anyway

    def chat(self, prompt, image_url=None):
        self._ensure_login()
        
        if image_url:
            print("   [GeminiBrowser] Warning: Image input not yet supported in Browser Client.")

        try:
            # 1. Select Input Box
            input_selector = "div[contenteditable='true']"
            # specific selector for Gemini's main input (changes often, but contenteditable is stable-ish)
            # A more robust one might be needed later (e.g., aria-label="Enter a prompt here")
            
            # Ensure focused and empty
            self.page.click(input_selector)
            
            # Clear existing text if any (sanity check)
            # self.page.evaluate("document.querySelector(\"div[contenteditable='true']\").innerText = ''") 
            # Better to just Fill empty
            # self.page.fill(input_selector, "") 

            # 2. Type like a human
            # print(f"   [GeminiBrowser] Typing prompt ({len(prompt)} chars)...")
            # For long prompts, type might be slow. 
            # self.page.keyboard.type(prompt, delay=5) 
            # Faster approach for long text: fill + verify
            self.page.fill(input_selector, prompt)
            
            time.sleep(0.5)
            self.page.keyboard.press("Enter")
            
            # 3. Wait for Response
            print("   [GeminiBrowser] Waiting for response...", end="", flush=True)
            
            # Strategy: Wait for the "model-response-text" or equivalent to appear and stabilize.
            # In Gemini, the response usually appears in a container.
            # We need to target the *last* response in the chat history.
            
            # Wait a bit for the backend to acknowledge
            time.sleep(2) 
            
            # Wait for at least one response text
            self.page.wait_for_selector(".model-response-text", timeout=45000)
            
            # Polling for stability
            last_text = ""
            stable_count = 0
            
            # Max wait 120 seconds (long analysis)
            for _ in range(60): 
                # Get all response texts
                elements = self.page.locator(".model-response-text").all()
                if not elements:
                    time.sleep(1)
                    continue
                
                # Get the last one
                try:
                    current_text = elements[-1].inner_text()
                except:
                    current_text = ""
                
                if current_text and len(current_text) > 10:
                    # Smart Exit: If we detect a valid JSON block, we can stop early
                    # We look for a closing brace '}' at the end (ignoring markdown wrappers like ```)
                    clean_check = current_text.strip().replace("```json", "").replace("```", "").strip()
                    if clean_check.startswith("{") and clean_check.endswith("}"):
                         # Double verify it's valid JSON? No, expensive. Just trust the structure.
                         print(" Fast exit (JSON detected).")
                         return current_text

                    if current_text == last_text:
                        stable_count += 1
                        if stable_count >= 2: # Stable for 2 seconds
                            print(" Done.")
                            return current_text
                    else:
                        stable_count = 0
                
                last_text = current_text
                print(".", end="", flush=True)
                time.sleep(1) # check every second
            
            print(" Timeout waiting for stability.")
            raise TimeoutError("Gemini response timed out (stability check failed).")

        except Exception as e:
            # Re-raise to let caller handle logging
            print(f"   [GeminiBrowser] Error during chat: {e}")
            raise e

    def close(self):
        self.session.close()
