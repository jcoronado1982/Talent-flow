import random
import json
import re

class FormHandler:
    def __init__(self, browser, brain, monitor=None):
        self.browser = browser
        self.brain = brain
        self.monitor = monitor

    def _clean_label(self, text):
        """Removes redundant lines and extra whitespace from labels."""
        if not text: return ""
        lines = [line.strip() for line in text.split("\n") if line.strip()]
        unique_lines = []
        for line in lines:
            if line not in unique_lines:
                unique_lines.append(line)
        return " ".join(unique_lines)

    def scan_form_structure(self, root=None):
        """Builds a semantic map of the entire form current step."""
        page = self.browser.page
        # If no root is provided, use the page or look for the LinkedIn modal fallback
        if not root:
            modal = page.locator(".jobs-easy-apply-modal")
            root = modal if modal.is_visible() else page
            
        import time
        import os
        from src.utils.cleanup import rotate_files
        
        os.makedirs("debug/dom", exist_ok=True)
        try:
            with open(f"debug/dom/raw_dom_{int(time.time())}.html", "w", encoding="utf-8") as f:
                f.write(root.inner_html())
            # Cleanup old snapshots
            rotate_files("debug/dom", "raw_dom_*.html", max_files=10)
        except Exception as e:
            print(f"   ⚠️ Could not save raw DOM: {e}")

        schema = []

        # 1. Text/Number/Textarea
        inputs = root.locator("input[type='text'], input[type='number'], input[type='email'], input[type='tel'], textarea").all()
        for i, inp in enumerate(inputs):
            if not inp.is_visible(): continue
            label = self._clean_label(self._get_label(inp))
            schema.append({
                "type": inp.get_attribute("type") or "text",
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
        selects = root.locator("select").all()
        for i, sel in enumerate(selects):
            if not sel.is_visible(): continue
            label = self._clean_label(self._get_label(sel))
            options = sel.locator("option").all_inner_texts()
            clean_options = [o.strip() for o in options if o.strip() and "selecciona" not in o.lower() and "select" not in o.lower()]
            schema.append({
                "type": "select",
                "label": label,
                "id": f"select_{i}",
                "locator": sel,
                "value": sel.input_value(),
                "error": self._get_validation_error(sel),
                "options": clean_options
            })

        # 3. Fieldsets and Choice Groups (Radios & Checkboxes)
        groups = root.locator("fieldset, div[role='group']").all()
        for i, grp in enumerate(groups):
            if not grp.is_visible(): continue
            
            # Label Detection: Check legend, then aria-labelledby, then sibling span
            label_text = ""
            legend = grp.locator("legend").first
            if legend.count() > 0:
                label_text = legend.inner_text().strip()
                
            if not label_text:
                # Try finding a label/span before the group
                label_text = self._get_label_for_group(grp)
                
            if not label_text: label_text = "Unknown Group Choice"
            label_text = self._clean_label(label_text)
            
            labels = grp.locator("label").all()
            if not labels: continue
            
            # Determine type based on first input
            first_input = grp.locator("input").first
            input_type = "radio"
            if first_input.count() > 0:
                input_type = first_input.get_attribute("type") or "radio"

            schema.append({
                "type": input_type,
                "label": label_text,
                "id": f"choice_{i}",
                "locator": grp,
                "options": [r.inner_text().strip() for r in labels if r.inner_text().strip()],
                "error": self._get_validation_error(grp)
            })

        return schema

    def _get_answer_for_label(self, label, answers):
        if label in answers: return answers[label]
        
        import re
        clean_label = re.sub(r'[\*\?¿:]', '', label).strip().lower()
        
        for k, v in answers.items():
            clean_k = re.sub(r'[\*\?¿:]', '', k).strip().lower()
            if clean_label == clean_k or clean_k in clean_label or clean_label in clean_k:
                return v
        return None

    def fill_form(self, job_context, root=None, debug_mode=False):
        # Initial Signal: Tell the monitor we are starting, but don't wipe everything yet
        if self.monitor:
            self.monitor.push_inspection(None, None, event_name="Scanning DOM...")

        schema = self.scan_form_structure(root=root)
        
        # Clean schema for Monitor (JSON serialization safety)
        monitor_schema = []
        for f in schema:
            clean_f = f.copy()
            if "locator" in clean_f: del clean_f["locator"]
            monitor_schema.append(clean_f)

        # Only push schema if we found something, to avoid wiping the last step during internal transitions
        if self.monitor and schema:
            self.monitor.push_inspection(monitor_schema, {}, event_name=f"Scan Complete ({len(schema)} fields)")

        if not schema: 
            print("      ⚠️ No fields detected in this form step.")
            # Final signal for "no fields" (don't wipe schema if it's the last step of a modal)
            if self.monitor:
                self.monitor.push_inspection(None, None, event_name="Scan: No new fields found")
            return {}

        salary_keywords = ["salary", "expectation", "aspiración", "salario", "pretendido", "remuneration", "compensación", "tarifa", "expectativa"]
        numeric_intent_keywords = ["years", "años", "how many", "cuántos", "muchos", "count", "experiencia", "experience"]

        # --- DETERMINISTIC FAST PATH (Local Brain) ---
        deterministic_answers = {}
        skills_map = job_context.get("profile_skills", {})
        
        for field in schema:
            label = field["label"]
            label_lower = label.lower()
            
            # 1. Salary (DETERMINISTIC)
            if any(k in label_lower for k in salary_keywords):
                val = job_context.get("applied_salary")
                if val: 
                    deterministic_answers[label] = str(val)
                    continue
            
            # 2. Skill Years (DETERMINISTIC)
            if any(k in label_lower for k in numeric_intent_keywords):
                # Try to find a skill name in the label
                for cat_name, category in skills_map.items():
                    for skill_name, info in category.items():
                        if skill_name.lower() in label_lower:
                            deterministic_answers[label] = str(info.get("years", "1"))
                            break
        # --- END FAST PATH ---

        if debug_mode:
            print("\n" + "="*60)
            print("🔍 [INSPECTOR] DOM SCHEMA MAPPING (What the Bot sees):")
            # Create a clean version for display
            display_schema = [
                {"label": f["label"], "type": f["type"], "options": f.get("options", [])}
                for f in schema
            ]
            print(json.dumps(display_schema, indent=2, ensure_ascii=False))
            
            if deterministic_answers:
                print("\n⚡ [INSPECTOR] DETERMINISTIC MATCHES (Fast Path):")
                print(json.dumps(deterministic_answers, indent=2, ensure_ascii=False))
            print("="*60 + "\n")

        print(f"   📝 Form Scan: Found {len(schema)} fields. ({len(deterministic_answers)} resolved locally).")
        
        # filter schema for AI to only process what's not determined
        form_payload = [
            {"label": f["label"], "type": f["type"], "options": f.get("options"), "error": f.get("error"), "constraints": f.get("constraints")}
            for f in schema if f["label"] not in deterministic_answers
        ]
        
        full_prompt_to_show = None
        answers = {}
        if form_payload:
            if debug_mode:
                print("\n" + "~"*60)
                print("📤 [INSPECTOR] PROMPT PAYLOAD (What is sent to AI):")
                print(json.dumps(form_payload, indent=2, ensure_ascii=False))
                print("~"*60 + "\n")
            
            # Traffic Signal
            if self.monitor:
                self.monitor.push_inspection(monitor_schema, answers, traffic_in=form_payload, event_name="Consulting AI...")

            print(f"      🤖 Consulting AI for {len(form_payload)} complex questions...")
            ai_answers, full_prompt = self.brain.answer_form(
                form_payload, 
                resolved_salary=job_context.get("applied_salary"),
                resolved_currency=job_context.get("applied_currency"),
                job_location=job_context.get("location")
            )
            full_prompt_to_show = full_prompt
            if ai_answers:
                answers.update(ai_answers)
                if self.monitor:
                     self.monitor.push_inspection(monitor_schema, answers, traffic_in=full_prompt, traffic_out=ai_answers, event_name="AI Response Received")
        
        # Merge deterministic answers
        answers.update(deterministic_answers)
        
        if self.monitor:
            # Preservar el prompt completo si existe, de lo contrario usar el payload
            payload_to_push = full_prompt_to_show if full_prompt_to_show else form_payload
            self.monitor.push_inspection(monitor_schema, answers, traffic_in=payload_to_push, traffic_out=answers, event_name="📊 Mapeo completo. Esperando autorización para llenar...")

        if debug_mode:
            print("\n" + "*"*60)
            print("🤖 [INSPECTOR] AI/RESOLVED ANSWERS (What the Bot decided):")
            print(json.dumps(answers, indent=2, ensure_ascii=False))
            print("*"*60 + "\n")
        
        captured_data = {}
        
        if not answers:
            print("      ⚠️ No answers generated. Falling back to field-by-field.")
            for field in schema:
                self._fill_field(field, job_context)
            return {}

        for field in schema:
            label = field["label"]
            label_lower = label.lower()
            ans = self._get_answer_for_label(label, answers)
            if not ans: continue 
            
            # --- START: STRICT NUMERIC ENFORCEMENT ---
            is_salary = any(k in label_lower for k in salary_keywords)
            is_years = any(k in label_lower for k in numeric_intent_keywords)
            
            # 1. Deterministic Salary Override (Priority)
            if is_salary:
                resolved_val = job_context.get("applied_salary")
                if resolved_val:
                    ans = resolved_val
                    print(f"      💰 FORCE-FILLING Salary: {ans}")
                captured_data["salary"] = str(ans)
            
            # 2. Strict Numeric Extraction (Clean up AI verbosity like '5 years' -> '5')
            if is_salary or is_years or field["type"] == "number":
                # Find the FIRST sequence of digits (including decimals)
                match = re.search(r'(\d+(?:\.\d+)?)', str(ans))
                if match:
                    clean_ans = match.group(1)
                    if clean_ans != str(ans):
                         print(f"      🧹 Numeric Extraction: '{ans}' -> '{clean_ans}'")
                         ans = clean_ans
                else:
                    # If no digits found but expected, fallback to a safe '0' or '1' depending on context
                    if is_years: 
                        print(f"      ⚠️ No digits found in '{ans}' for years field. Fallback to '1'.")
                        ans = "1"
            # --- END: STRICT NUMERIC ENFORCEMENT ---

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
                    options_texts = field.get("options", [])
                    ans_lower = str(ans).lower()
                    best_text = None
                    
                    # Fuzzy match index para encontrar el nombre de la opción real que el DOM tiene
                    for opt in options_texts:
                        opt_lower = opt.lower()
                        if ans_lower in opt_lower or opt_lower in ans_lower or (ans_lower=="yes" and "sí" in opt_lower) or (ans_lower=="no" and opt_lower == "no"):
                            best_text = opt
                            break
                            
                    if best_text:
                        print(f"         ⚙️ Mapeo de select: '{ans}' -> '{best_text}'")
                        try:
                             # Estrategia 1: Label directo
                             field["locator"].select_option(label=best_text, timeout=1000)
                        except:
                             # Estrategia 2: Extraer el "value" interno del DOM (Garantizado)
                             opts = field["locator"].locator("option").all()
                             for opt_el in opts:
                                 if best_text.strip() in opt_el.inner_text().strip():
                                     val = opt_el.get_attribute("value")
                                     if val:
                                          field["locator"].select_option(value=val, timeout=1000)
                                          break
                             # Forzar evento DOM
                             field["locator"].evaluate("node => node.dispatchEvent(new Event('change', { bubbles: true }))")
                    else:
                        print(f"         ⚠️ Opción '{ans}' no encontrada en el DOM. Seleccionando la 1ra válida.")
                        try: field["locator"].select_option(index=1, timeout=1000)
                        except: pass
                elif field["type"] in ["radio", "checkbox"]:
                    options_els = field["locator"].locator("label").all()
                    target_answers = ans if isinstance(ans, list) else [x.strip() for x in str(ans).split(",")]
                    
                    found_any = False
                    for opt_el in options_els:
                        opt_text = opt_el.inner_text().strip().lower()
                        
                        # Fuzzy Match: Check if answer is in option OR option is in answer
                        matches = False
                        for t_ans in target_answers:
                            t_lower = str(t_ans).lower()
                            if t_lower in opt_text or opt_text in t_lower:
                                matches = True
                                break
                                
                        if matches:
                            try:
                                # Prioritize clicking the input if possible, else the label
                                check_input = opt_el.locator("input").first
                                if check_input.count() > 0:
                                    if not check_input.is_checked():
                                        opt_el.click()
                                    else:
                                        print(f"         Already selected: {opt_text}")
                                else:
                                    opt_el.click()
                                found_any = True
                                print(f"         ✅ Selected option: {opt_text}")
                            except:
                                try: opt_el.click()
                                except: pass
                            
                            if field["type"] == "radio":
                                break
                    if not found_any:
                        print(f"         ⚠️ No matching option found for '{ans}' in {field['label']}")
                self.browser.human_delay(0.1, 0.3)
            except Exception as e:
                print(f"         ❌ Error filling field: {e}")
        
        return captured_data

    def _fill_field(self, field, job_context):
        label = field["label"]
        current_val = field.get("value", "").strip()
        has_error = field.get("error") is not None
        
        if current_val and not has_error:
            return

        print(f"      -> [Fallback] Asking AI about '{label[:30]}...'")
        ans = self.brain.answer_question(
            label, 
            options=field.get("options"), 
            input_type=field["type"],
            resolved_salary=job_context.get("applied_salary"),
            job_location=job_context.get("location")
        )
        
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
            # 1. Focus the field
            try: locator.click(timeout=1000)
            except: pass
            
            # Limpiar valor actual seleccionando todo
            locator.press("Control+A")
            locator.press("Backspace")
            self.browser.human_delay(0.2, 0.5)
            
            # Remover tildes problemáticas para LinkedIn
            search_val = str(value)
            if "medell" in search_val.lower(): search_val = "Medellin"
            if "bogot" in search_val.lower(): search_val = "Bogota"
            
            # 2. Type slowly to trigger AJAX
            try:
                locator.press_sequentially(search_val, delay=100)
            except AttributeError:
                locator.type(search_val, delay=100)
                
            # 3. Esperar explícitamente a que el autocompletado tenga opciones visibles
            try:
                self.browser.page.wait_for_selector(
                    "[role='option'], .search-results__list li, .typeahead-suggestions li", 
                    state="visible", 
                    timeout=5000
                )
            except:
                print("         ⚠️ Timeout esperando opciones del combobox. Procediendo ciego...")
                
            self.browser.human_delay(0.5, 1.0) # Breve pausa por renderizado React
            
            # 4. Use standard keyboard accessibility for Comboboxes
            locator.press("ArrowDown")
            self.browser.human_delay(0.3)
            locator.press("Enter")
            self.browser.human_delay(0.5)
            
        except Exception as e:
            print(f"         ❌ Smart Fill Error: {e}")
            try: locator.fill(str(value))
            except: pass

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

    def _get_label_for_group(self, element):
        """Tries to find a label for a fieldset or div group."""
        try:
            # 1. Search for aria-labelledby
            id_ref = element.get_attribute("aria-labelledby")
            if id_ref:
                ref_el = self.browser.page.locator(f"#{id_ref}").first
                if ref_el.count() > 0: return ref_el.inner_text().strip()
            
            # 2. Search for span/legend before the group
            parent = element.locator("xpath=..")
            # Usually the question is in a span with a specific class in LinkedIn
            potential_label = parent.locator("span.fb-dash-form-element__label, label").first
            if potential_label.count() > 0 and potential_label.is_visible():
                return potential_label.inner_text().strip()
                
            # 3. Look at preceding siblings
            # (Playwright doesn't have a direct preceding-sibling locator easily, but we can try xpath)
            # This is a bit advanced, let's keep it simple with parent-child first.
        except: pass
        return ""

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

    def _wait_for_signal(self):
        """Helper to wait for the Web Dashboard 'NEXT' signal."""
        from src.config.settings import Settings
        import os
        import json
        
        signal_file = Settings.INTERACTION_FILE
        if os.path.exists(signal_file):
            try: os.remove(signal_file)
            except: pass
            
        while True:
            if os.path.exists(Settings.STOP_SIGNAL): 
                raise InterruptedError("Stopped by user")
                
            if os.path.exists(signal_file):
                 try:
                     with open(signal_file, "r") as f:
                         sig = json.load(f)
                         if sig.get("action") == "NEXT":
                             os.remove(signal_file)
                             return
                 except: pass
            
            self.browser.page.wait_for_timeout(500)
