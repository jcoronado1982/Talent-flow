from src.audit import AuditLogger

class SearchScanner:
    def __init__(self, page, interaction, extractor, monitor=None):
        self.page = page
        self.interaction = interaction
        self.extractor = extractor
        self.monitor = monitor
        self.audit = AuditLogger()

    def set_dynamic_selector(self, selector, item_tag="li"):
        self.dynamic_selector = selector
        self.dynamic_item_tag = item_tag

    def scan_results(self, site, limit, callback_fn, monitor=None):
        if monitor: self.monitor = monitor
        
        if site != "linkedin": return 0, None

        # 0. Check for "No Results" or "Error" screens early
        no_results_text = [
            "no matching jobs found", 
            "unfortunately, things aren't loading", 
            "no se encontraron empleos", 
            "no se encontraron resultados",
            "página no encontrada",
            "status-404"
        ]
        try:
            # Use inner_text() on body for a quick broad check
            body_text = (self.page.locator("body").inner_text() or "").lower()
            if any(msg in body_text for msg in no_results_text):
                if self.monitor: self.monitor.log("      ⚠️ [Scanner] LinkedIn muestra pantalla de 'Sin resultados'. Finalizando categoría.")
                return 0, 0 # Force break: 0 items, 0 total
        except: pass

        # 0. Get the True Total from LinkedIn Header via Extractor
        real_total = self.extractor.extract_total_results()
        if real_total is not None:
            msg = f"📊 [Scanner] LinkedIn reporta {real_total} resultados totales."
            if self.monitor: self.monitor.log(msg)
            # Adjust limit if real total is smaller
            if real_total < limit:
                limit = real_total
                if self.monitor: self.monitor.log(f"      📍 Ajustando límite a {limit} (total disponible).")

        # 1. Identify Container and Items
        list_selector = getattr(self, 'dynamic_selector', ".jobs-search-results-list")
        item_tag = getattr(self, 'dynamic_item_tag', "li")
        job_card_selector = f"{list_selector} > {item_tag}"
        
        msg = f"🔍 [Scanner] Escaneando {limit} de {real_total if real_total is not None else '???'} resultados..."
        if self.monitor: self.monitor.log(msg)

        # 2. Granular Scroll to Hydrate List
        if self.monitor: self.monitor.log("      🔄 Hidratando lista de resultados...")
        
        # If we didn't get a total, or the total is 0 but we might have content, 
        # ensure we scroll at least a bit to trigger lazy loading
        effective_limit = limit if limit > 0 else 25 
        
        for scroll_step in range(1, 11):
            try:
                scroll_target = scroll_step * 500
                self.page.evaluate(f"document.querySelector('{list_selector}').scrollTop = {scroll_target}")
                self.interaction.human_delay(1.5, 2.0)
                
                # OPTIMIZATION: If we already have enough items in DOM to satisfy current limit, stop scrolling early
                current_count = self.page.locator(job_card_selector).count()
                if current_count >= effective_limit: 
                    break
            except: break

        # Final scroll to bottom for stability
        try:
            self.page.evaluate(f"document.querySelector('{list_selector}').scrollTop = document.querySelector('{list_selector}').scrollHeight")
            self.interaction.human_delay(1.5, 2.0)
        except: pass

        # 3. Process Items
        items = self.page.locator(job_card_selector).all()
        total_in_dom = len(items)
        if self.monitor: self.monitor.log(f"   ✅ DOM hidratado: {total_in_dom} elementos encontrados.")
        
        if total_in_dom == 0:
            # If DOM is empty after 10 scrolls, and we check the message again
            # We return (0, 0) to signal exhaustion to the collector
            return 0, 0

        # If real_total was 0 but we found items, adjust limit to process them
        if limit <= 0 and total_in_dom > 0:
            limit = total_in_dom

        count = 0
        for i, item in enumerate(items):
            if limit > 0 and count >= limit: break
            
            try:
                # A. Hydrate Item if empty
                item_text = (item.text_content() or "").strip()
                if len(item_text) < 20: 
                    # AGGRESSIVE HYDRATION: If empty, try harder to trigger LinkedIn's lazy loading
                    try:
                        item.scroll_into_view_if_needed()
                        item.hover()
                        self.interaction.human_delay(1.5, 2.5)
                        item_text = (item.text_content() or "").strip()
                    except: pass
                
                if len(item_text) < 20: 
                    msg = f"      ❌ Ítem {i+1} descartado: Fallo de lectura (READ_FAILURE)."
                    if self.monitor: self.monitor.log(msg)
                    self.audit.log("SKIPPED", reason="READ_FAILURE", details="Bot failed to extract text from job card", url="")
                    continue

                # Log SEEN early
                self.audit.log("SEEN", details=f"Item index {i} in DOM")

                # B. Get Basic Info (Title/URL)
                title = "Unknown"
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

                # C. Deep Click to load Details
                try:
                    item.click()
                    self.interaction.human_delay(3.0, 4.0)
                    try:
                        self.page.wait_for_selector(".jobs-description__content", timeout=3000)
                    except: pass
                except: pass

                # D. Extract Features
                details = self.extractor.extract_details()
                
                # Consolidate
                final_details = {
                    "title": details.get("title") or title,
                    "company": details.get("company", "Unknown"),
                    "location": details.get("location", "Unknown"),
                    "work_mode": details.get("work_mode", "Unknown"),
                    "date": details.get("date", "Unknown"),
                    "description": details.get("description", item_text)
                }

                # Callback to Collector
                save_result = callback_fn(final_details, url)
                
                if save_result is False: # Stop Signal
                    self.audit.log("SKIPPED", company=final_details['company'], role=final_details['title'], reason="Callback Rejection (Stop Signal)", url=url)
                    return count, real_total
                
                if save_result == "DUPLICATE":
                    self.audit.log("DUPLICATE", company=final_details['company'], role=final_details['title'], url=url)
                else:
                    self.audit.log("SAVED", company=final_details['company'], role=final_details['title'], url=url)
                    count += 1
            except Exception as e:
                self.audit.log("ERROR", reason="Iteration Failure", details=str(e))
                print(f"   ⚠️ Error en ítem {i}: {e}")
                continue

        return count, real_total
