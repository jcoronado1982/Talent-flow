import os
import random
import json
import time
import src.services.storage.database as db
from src.config.settings import Settings

class ApplicationFlow:
    def __init__(self, browser, form_handler, resume_manager):
        self.browser = browser
        self.form_handler = form_handler
        self.resume_manager = resume_manager

    def handle_application_flow(self, job_context, dry_run=False, interactive=None):
        """Supervises the 'Easy Apply' modal flow."""
        self.dry_run = dry_run
        self.interactive = getattr(self, 'interactive', False)
        if interactive is not None:
            self.interactive = interactive
        page = self.browser.page
        max_steps = 15
        step = 0
        job_id = job_context["id"]
        
        while step < max_steps:
            if os.path.exists(Settings.STOP_SIGNAL):
                print("🛑 Stop signal detected in flow. Terminating...")
                return "Stopped"
            
            step += 1
            self.browser.human_delay(0.5, 1.5)
            
            # 1. Upload Resume
            target_file = job_context.get("target_resume")
            if target_file and not job_context.get("actual_resume"):
                job_context["actual_resume"] = self.resume_manager.smart_upload_resume(target_file)

            # 2. Fill Form (AHORA OCURRE ANTES DE EVALUAR EL DRY RUN)
            try:
                db.update_job_status(job_id, "Applying", error=f"Step {step}: Filling form...")
                captured = self.form_handler.fill_form(job_context, debug_mode=self.interactive)
                
                # PAUSA INTERACTIVA (PANEL DE CONTROL)
                if self.interactive:
                    if self.form_handler.monitor:
                        self.form_handler.monitor.push_inspection(None, None, event_name="📝 Llenado completado. ¿Continuar al siguiente paso?")
                        
                    print(f"\n⌨️  [INTERACTIVE] Form filled for step {step}.")
                    print(f"👉 Revisa LinkedIn y pulsa 'SIGUIENTE PASO' en el Web Dashboard para CONTINUAR...")
                    
                    signal_file = Settings.INTERACTION_FILE
                    if os.path.exists(signal_file):
                        try: os.remove(signal_file)
                        except: pass
                    
                    signal_received = False
                    while not signal_received:
                        if os.path.exists(Settings.STOP_SIGNAL): 
                            return "Stopped"
                            
                        if os.path.exists(signal_file):
                             try:
                                 with open(signal_file, "r") as f:
                                     sig = json.load(f)
                                     if sig.get("action") == "NEXT":
                                         print("🌐 Signal received from Web UI. Continuing...")
                                         signal_received = True
                                         os.remove(signal_file)
                                         break
                             except Exception as e:
                                 print(f"⚠️ Error leyendo señal: {e}")
                        
                        # USAR PAUSA DE PLAYWRIGHT PARA NO CONGELAR EL NAVEGADOR
                        self.browser.page.wait_for_timeout(1000)
                
                if captured:
                    if "salary" in captured: job_context["applied_salary"] = captured["salary"]
                    if "currency" in captured: job_context["applied_currency"] = captured["currency"]
            except Exception as e:
                print(f"   ⚠️ Error autofilling: {e}")

            # 3. Check for blocking errors AFTER interaction
            error_el = page.locator(".artdeco-inline-feedback--error").first
            if error_el.is_visible(timeout=500):
                txt = error_el.inner_text().strip()
                print(f"   [Flow] ⚠️ Error en formulario detectado: '{txt[:50]}...'")
                # No hacemos return directo, dejamos que el usuario lo vea.

            # 4. Check Submit / Done buttons (LA MAGIA DEL SHADOW MODE)
            submit_labels = ["Submit application", "Enviar solicitud", "Postularse"]
            is_submit_ready = any(page.get_by_text(lbl, exact=False).is_visible() for lbl in submit_labels)
            
            if is_submit_ready:
                # Si estamos en modo interactivo, permitimos el envío real porque fue auditado por el humano
                if self.dry_run and not self.interactive:
                    print("🛡️ [SHADOW MODE] Botón Submit detectado. Abortando envío real para auditoría automática.")
                    return "Debug"
                
                print("⚠️ [INSPECTOR] Ejecutando clic de ENVIAR APLICACIÓN definitiva...")
                if self.click_button(submit_labels):
                    db.update_job_status(job_id, "Applied", uploaded_cv=job_context.get("actual_resume") or job_context.get("target_resume"))
                    return "Submitted"

            # 5. Check Next/Review
            if self.click_button(["Continue to next step", "Next", "Siguiente", "Continue", "Review", "Revisar"]):
                continue

            # 6. Check Success
            if page.get_by_text("Application sent").is_visible() or page.get_by_text("Solicitud enviada").is_visible():
                 db.update_job_status(job_id, "Applied", uploaded_cv=job_context.get("actual_resume") or job_context.get("target_resume"))
                 return "Submitted"
            
            # Additional Success / Done check
            if self.click_button(["Done", "Hecho", "Finalizar"]):
                 db.update_job_status(job_id, "Applied", uploaded_cv=job_context.get("actual_resume") or job_context.get("target_resume"))
                 return "Submitted"

            print("   ❓ No actionable buttons found. Wait...")
        
        return "Manual"

    def click_button(self, labels):
        try:
            # 1. Búsqueda nativa del botón de Siguiente (Prioridad Absoluta)
            target = None
            lower_labels = [l.lower() for l in labels]
            is_next = any(w in " ".join(lower_labels) for w in ["next", "siguiente", "continue", "review", "revisar"])
            
            if is_next:
                # Buscar por el atributo exacto de LinkedIn
                # Para seguir: data-easy-apply-next-button
                # Para revisar: aria-label='Review your application' o 'Revisar tu solicitud'
                selectors = [
                    "button[data-easy-apply-next-button]",
                    "button[aria-label='Review your application']",
                    "button[aria-label='Revisar tu solicitud']",
                    "button.artdeco-button--primary:has-text('Review')",
                    "button.artdeco-button--primary:has-text('Revisar')"
                ]
                btn = self.browser.page.locator(", ".join(selectors)).first
                if btn.is_visible(timeout=500):
                    target = btn
            
            # 2. Búsqueda por rol y texto si no encontró el anterior
            if not target:
                for lbl in labels:
                    btn = self.browser.page.get_by_role("button", name=lbl, exact=False).first
                    if btn.is_visible(timeout=500):
                        target = btn
                        break
            
            if target:
                print(f"      🎯 [INSPECTOR] ¡Botón nativo detectado! Emulando clic físico de ratón...")
                try:
                    target.scroll_into_view_if_needed()
                    self.browser.human_delay(0.2, 0.4)
                    
                    # Clic Físico usando coordenadas exactas (Totalmente a prueba de bots y React)
                    box = target.bounding_box()
                    if box:
                        # Ir al centro con una dispersión de ruido (Jitter) para evitar detectar un "centro matemático perfecto"
                        offset_x = random.uniform(-box["width"] * 0.3, box["width"] * 0.3)
                        offset_y = random.uniform(-box["height"] * 0.3, box["height"] * 0.3)
                        
                        x = box["x"] + box["width"] / 2 + offset_x
                        y = box["y"] + box["height"] / 2 + offset_y
                        
                        # Mover con una cantidad de micro-pasos irregulares
                        self.browser.page.mouse.move(x, y, steps=random.randint(5, 15))
                        self.browser.human_delay(0.1, 0.3)
                        self.browser.page.mouse.down()
                        self.browser.human_delay(0.05, 0.15)
                        self.browser.page.mouse.up()
                        print(f"      🎯 [INSPECTOR] Clic físico ejecutado con éxito en ({int(x)}, {int(y)}).")
                    else:
                        # Si por algún motivo no hay coordenadas, usar el click estándar
                        target.hover()
                        target.click(delay=random.randint(50, 150))
                        print(f"      🎯 [INSPECTOR] Clic estándar ejecutado.")
                except Exception as click_err:
                    print(f"      ⚠️ Error en clic de ratón, forzando JS nativo: {click_err}")
                    target.evaluate("node => node.click()")

                # Esperar a que la página reaccione y haga la animación de deslizar
                self.browser.page.wait_for_timeout(2500)
                return True

            print(f"      ⚠️ No matching buttons found for labels: {labels}")
            return False
            
        except Exception as e:
            print(f"      ⚠️ Error in native stealth click logic: {e}")
            return False

    def cleanup_modal(self):
        """Ensures the modal is closed before moving on."""
        try:
            modal = self.browser.page.locator(".jobs-easy-apply-modal")
            if modal.is_visible():
                print("   🧹 Cleaning up open modal...")
                close_btn = modal.locator("button[aria-label='Dismiss']")
                if close_btn.is_visible():
                    close_btn.click()
                    self.browser.human_delay(0.5)
                    confirm_btn = self.browser.page.locator("button[data-control-name='discard_application_confirm_btn']")
                    if confirm_btn.is_visible(): confirm_btn.click()
                self.browser.page.keyboard.press("Escape")
                self.browser.human_delay(1)
        except: pass
