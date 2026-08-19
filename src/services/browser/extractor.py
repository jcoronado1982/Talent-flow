import re
from .heuristics import FIND_TOTAL_RESULTS_JS

class DataExtractor:
    def __init__(self, page):
        self.page = page

    def extract_total_results(self):
        """Extracts the total number of results from the search header."""
        # 1. NEW: Try Dynamic Discovery (Heuristic JS)
        try:
            val_str = self.page.evaluate(FIND_TOTAL_RESULTS_JS)
            if val_str:
                val = int(val_str)
                print(f"   [Extractor] Dynamic discovery found total: {val}")
                return val
        except: pass

        # 2. Fallback: Selector-based discovery
        selectors = [
            ".jobs-search-results-list__subtitle span",
            ".jobs-search-results-list__header h1",
            "header.jobs-search-results-list__header",
            "small.display-flex.mt4",
            ".results-context-header__job-count",
            ".jobs-search-results-list__subtitle"
        ]
        for sel in selectors:
            try:
                element = self.page.query_selector(sel)
                if not element or not element.is_visible(): continue
                
                text = (element.inner_text() or "").strip()
                if not text: continue
                
                match = re.search(r'([\d.,]+)', text)
                if match:
                    num_str = match.group(1).replace(',', '').replace('.', '')
                    if num_str:
                        val = int(num_str)
                        print(f"   [Extractor] Found total results via '{sel}': {val}")
                        return val
            except: continue
        return None

    def extract_details(self):
        details = {"description": "", "date": "Unknown", "company": "Unknown", "location": "Unknown", "work_mode": "Unknown", "apply_type": "Unknown"}
        try:
             # Title
             title_el = self.page.query_selector(".job-details-jobs-unified-top-card__job-title h1") or \
                        self.page.query_selector("h2.job-details-jobs-unified-top-card__job-title") or \
                        self.page.query_selector(".job-details-jobs-unified-top-card__job-title") or \
                        self.page.query_selector("h1")
             if title_el: details["title"] = title_el.inner_text().strip()

             # Top Card
             top_card_el = self.page.query_selector(".job-details-jobs-unified-top-card__primary-description-container") or \
                           self.page.query_selector(".job-details-jobs-unified-top-card__primary-description") or \
                           self.page.query_selector(".job-details-jobs-unified-top-card")
             
             if top_card_el:
                 full_text = top_card_el.inner_text().replace("\n", " ").strip()
                 date_patterns = [r"(\d+\s+(?:hour|minute|day|week|month)s?\s+ago)", r"(just\s+now)", r"(hace\s+\d+\s+(?:hora|minuto|día|semana|mes)s?)", r"(recién\s+publicado)", r"(\d+\s+(?:h|d|w|m|y)\s+ago)"]
                 
                 # DATE logic from TalentFlow_1
                 for span in top_card_el.query_selector_all("span.tvm__text--low-emphasis"):
                     span_text = span.inner_text().strip()
                     if any(re.search(pat, span_text, re.IGNORECASE) for pat in date_patterns):
                         details["date"] = span_text
                         break

                 if details["date"] == "Unknown":
                     for pat in date_patterns:
                         match = re.search(pat, full_text, re.IGNORECASE)
                         if match: details["date"] = match.group(1); break

                 # WORK MODE (Direct & Isolated Detection)
                 mode_val = self.page.evaluate("""() => {
                     const prefs = document.querySelectorAll('.job-details-fit-level-preferences strong, .jobs-unified-top-card__workplace-type, .ui-pill');
                     for (let p of prefs) {
                         const t = p.innerText.toLowerCase();
                         if (t.includes('remote') || t.includes('remoto')) return 'Remote';
                         if (t.includes('hybrid') || t.includes('híbrido')) return 'Hybrid';
                         if (t.includes('on-site') || t.includes('onsite') || t.includes('presencial')) return 'On-site';
                     }
                     const topCard = document.querySelector('.job-details-jobs-unified-top-card, .jobs-unified-top-card');
                     if (topCard) {
                         const t = topCard.innerText.toLowerCase() + " " + topCard.textContent.toLowerCase();
                         if (t.includes('remote') || t.includes('remoto')) return 'Remote';
                         if (t.includes('hybrid') || t.includes('híbrido')) return 'Hybrid';
                         if (t.includes('on-site') || t.includes('onsite') || t.includes('presencial')) return 'On-site';
                     }
                     return 'Unknown';
                 }""")
                 details["work_mode"] = mode_val
                 
                 # LOCATION logic from TalentFlow_1 (Intact)
                 parts = [p.strip() for p in re.sub(r"[·•|]", "###", full_text).split("###") if p.strip()]
                 for part in parts:
                     if details["date"] != "Unknown" and part in details["date"]: continue
                     if re.search(r"(applicant|solicitud|remote|remoto|hybrid|híbrido|onsite|presencial|ago|hace|promoted|hirer)", part, re.IGNORECASE): continue
                     details["location"] = part; break

             # Company
             company_el = self.page.query_selector(".job-details-jobs-unified-top-card__company-name") or \
                          self.page.query_selector(".job-card-container__company-name") or \
                          self.page.query_selector(".jobs-unified-top-card__company-name")
             if company_el: details["company"] = company_el.inner_text().strip()

             # Apply Type
             apply_btn = self.page.query_selector(".jobs-apply-button") or self.page.query_selector("button.jobs-apply-button--top-card")
             details["apply_type"] = "External"
             if apply_btn:
                 btn_text = (apply_btn.inner_text() or "").lower()
                 if "easy apply" in btn_text or "sencilla" in btn_text:
                     details["apply_type"] = "Easy Apply"

             # Description
             selectors = [".jobs-description__content", "#job-details", ".show-more-less-html__markup", "article", ".description"]
             found_el = None
             for s in selectors:
                  if self.page.is_visible(s): found_el = self.page.query_selector(s); break

             if found_el:
                 try:
                     more_btn = found_el.query_selector("button[aria-label*='Show more']")
                     if more_btn and more_btn.is_visible(): more_btn.click()
                 except: pass
                 details["description"] = found_el.inner_text()
                 req_regex = r"(?i)(?:Requisitos|Requirements|Perfil|Profile|What you need|Who you are|Experiencia|Experience|Qualifications)(?:[\s:]+)(.*?)(?:Benefits|Beneficios|Ofrecemos|Offer|About|Sobre|Compensation|What we offer|TalentFlow|$)"
                 match_req = re.search(req_regex, details["description"], re.DOTALL)
                 details["raw_requirements"] = match_req.group(1).strip()[:1000] if match_req and len(match_req.group(1).strip()) > 50 else details["description"][:1000]

        except Exception as e: 
            print(f"   [Extractor] Error en extracción: {e}")
        return details
