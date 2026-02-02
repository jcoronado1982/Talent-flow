import random

class FormHandler:
    def __init__(self, browser, brain):
        self.browser = browser
        self.brain = brain

    def scan_form_structure(self):
        """Builds a semantic map of the entire form current step."""
        page = self.browser.page
        modal = page.locator(".jobs-easy-apply-modal")
        if not modal.is_visible(): return []

        schema = []

        # 1. Text/Number/Textarea
        inputs = modal.locator("input[type='text'], input[type='number'], textarea").all()
        for i, inp in enumerate(inputs):
            if not inp.is_visible(): continue
            label = self._get_label(inp)
            schema.append({
                "type": "text",
                "label": label,
                "id": f"input_{i}",
                "locator": inp,
                "value": inp.input_value(),
                "error": self._get_validation_error(inp),
                "constraints": {
                    "maxlength": inp.get_attribute("maxlength"),
                    "required": inp.get_attribute("required") == "true"
                }
            })

        # 2. Selects
        selects = modal.locator("select").all()
        for i, sel in enumerate(selects):
            if not sel.is_visible(): continue
            label = self._get_label(sel)
            options = sel.locator("option").all_inner_texts()
            schema.append({
                "type": "select",
                "label": label,
                "id": f"select_{i}",
                "locator": sel,
                "value": sel.input_value(),
                "error": self._get_validation_error(sel),
                "options": [o.strip() for o in options if o.strip()]
            })

        # 3. Fieldsets (Radios)
        fieldsets = modal.locator("fieldset").all()
        for i, fs in enumerate(fieldsets):
            if not fs.is_visible(): continue
            legend = fs.locator("legend").first
            if not legend.is_visible(): continue
            
            radios = fs.locator("label").all()
            schema.append({
                "type": "radio",
                "label": legend.inner_text().strip(),
                "id": f"radio_{i}",
                "locator": fs,
                "options": [r.inner_text().strip() for r in radios],
                "error": self._get_validation_error(fs)
            })

        return schema

    def fill_form(self, job_context):
        schema = self.scan_form_structure()
        if not schema: return {}

        print(f"   📝 Form Scan: Found {len(schema)} fields. Consulting AI...")
        
        form_payload = [
            {"label": f["label"], "type": f["type"], "options": f.get("options"), "error": f.get("error"), "constraints": f.get("constraints")}
            for f in schema
        ]
        
        answers = self.brain.answer_form(form_payload)
        captured_data = {}
        
        if not answers:
            print("      ⚠️ AI could not process batch form. Falling back to field-by-field.")
            for field in schema:
                self._fill_field(field)
            return {}

        salary_keywords = ["salary", "expectation", "aspiración", "salario", "pretendido", "remuneration", "compensación"]

        for field in schema:
            label = field["label"]
            ans = answers.get(label)
            if not ans: continue 
            
            # Capture salary data if label matches
            label_lower = label.lower()
            if any(k in label_lower for k in salary_keywords):
                print(f"      💰 Captured Salary Info: [{label}] -> {ans}")
                if any(c in str(ans) for c in ["$", "USD", "COP", "€", "MXN", "moneda"]):
                    captured_data["currency"] = str(ans)
                else:
                    captured_data["salary"] = str(ans)

            current_val = field.get("value", "").strip()
            has_error = field.get("error") is not None
            
            if current_val and not has_error:
                print(f"      -> [SKIP] [{label[:20]}...] is already filled.")
                continue

            print(f"      -> [FILL] [{label[:20]}...] with AI answer: '{ans}'")
            try:
                if field["type"] == "text":
                    is_combobox = field["locator"].get_attribute("role") == "combobox" or \
                                  field["locator"].get_attribute("aria-autocomplete") in ["list", "both"]
                    
                    if is_combobox:
                        self._smart_fill_combobox(field["locator"], str(ans))
                    else:
                        field["locator"].fill(str(ans))
                elif field["type"] == "select":
                    field["locator"].select_option(label=str(ans))
                elif field["type"] == "radio":
                    options_els = field["locator"].locator("label").all()
                    for opt_el in options_els:
                        if str(ans).lower() in opt_el.inner_text().lower():
                            opt_el.click()
                            break
                self.browser.human_delay(0.1, 0.3)
            except Exception as e:
                print(f"         ❌ Error filling field: {e}")
        
        return captured_data

    def _fill_field(self, field):
        label = field["label"]
        current_val = field.get("value", "").strip()
        has_error = field.get("error") is not None
        
        if current_val and not has_error:
            return

        print(f"      -> [Fallback] Asking AI about '{label[:30]}...'")
        ans = self.brain.answer_question(label, options=field.get("options"))
        
        if ans:
             try:
                 if field["type"] == "text":
                     field["locator"].fill(str(ans))
                 elif field["type"] == "select":
                     field["locator"].select_option(label=str(ans))
                 elif field["type"] == "radio":
                      radios = field["locator"].locator("label").all()
                      for r in radios:
                          if str(ans).lower() in r.inner_text().lower():
                              r.click()
                              break
             except Exception as e:
                 print(f"         ❌ Fallback error: {e}")

    def _smart_fill_combobox(self, locator, value):
        print(f"      🖱️ Smart Filling Combobox: '{value}'")
        try:
            locator.fill(value)
            self.browser.human_delay(1, 2)
            listbox_selectors = [".typeahead-suggestions", ".search-results__list", "[role='listbox']", ".basic-typeahead__results"]
            
            found_option = False
            for selector in listbox_selectors:
                options = self.browser.page.locator(f"{selector} >> text='{value}'").first
                if options.is_visible(timeout=2000):
                    options.click()
                    found_option = True
                    break
            
            if not found_option:
                locator.press("ArrowDown")
                self.browser.human_delay(0.5)
                locator.press("Enter")
        except Exception as e:
            print(f"         ❌ Smart Fill Error: {e}")
            locator.fill(value)

    def _get_validation_error(self, element):
        try:
             parent = element.locator("xpath=..")
             for _ in range(3):
                 err = parent.locator(".artdeco-inline-feedback--error").first
                 if err.is_visible():
                     return err.inner_text().strip()
                 parent = parent.locator("xpath=..")
        except: pass
        return None

    def _get_label(self, element):
        lbl = element.get_attribute("aria-label")
        if lbl: return lbl
        try:
            curr = element
            for _ in range(5):
                curr = curr.locator("xpath=..")
                label_el = curr.locator("label").first
                if label_el.is_visible():
                    txt = label_el.inner_text().strip()
                    if txt: return txt
                span_text = curr.locator("span.fb-dash-form-element__label").first
                if span_text.is_visible():
                    return span_text.inner_text().strip()
        except: pass
        return "Unknown Field"
