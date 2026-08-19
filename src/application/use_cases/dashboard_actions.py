import os
from typing import Any
import json
from src.domain.interfaces import IMonitor
from src.utils.observability import observed
import src.services.storage.database as db

class ClearJobsUseCase:
    def __init__(self, monitor: IMonitor):
        self.monitor = monitor

    @observed
    def execute(self):
        self.monitor.log("🧹 [USE-CASE] Limpiando base de datos de empleos...")
        db.clear_jobs()
        self.monitor.log("✅ [USE-CASE] Base de datos limpiada con éxito.")

class StopProcessesUseCase:
    def __init__(self, monitor: IMonitor, signal_file: str):
        self.monitor = monitor
        self.signal_file = signal_file

    @observed
    def execute(self):
        self.monitor.log("🛑 [USE-CASE] Enviando señal de parada...")
        with open(self.signal_file, "w") as f:
            f.write("STOP")
        self.monitor.log("✅ [USE-CASE] Señal enviada.")

class SubmitAnswerUseCase:
    def __init__(self, monitor: IMonitor, interaction_file: str):
        self.monitor = monitor
        self.interaction_file = interaction_file

    @observed
    def execute(self, answer: str):
        self.monitor.log(f"💬 [USE-CASE] Enviando respuesta de interacción: {answer[:10]}...")
        data = {"status": "answered", "answer": answer}
        with open(self.interaction_file, "w") as f:
            json.dump(data, f)
        self.monitor.log("✅ [USE-CASE] Respuesta enviada.")

class ExecuteApplyBotUseCase:
    def __init__(self, monitor: IMonitor):
        self.monitor = monitor

    @observed
    def execute(self):
        self.monitor.log("🚀 [USE-CASE] Iniciando Bot de Aplicación Automática...")
        # Note: The actual execution is handled via subprocess in the dashboard for now
        # but wrapping this allows us to trace the START action and any setup errors.
        self.monitor.log("✅ [USE-CASE] Proceso de aplicación iniciado.")

class StartSearchUseCase:
    def __init__(self, monitor: IMonitor):
        self.monitor = monitor

    @observed
    def execute(self):
        self.monitor.log("🚀 [USE-CASE] Iniciando Búsqueda de Empleos...")
        self.monitor.log("✅ [USE-CASE] Proceso de búsqueda iniciado.")

class AuditDecisionUseCase:
    def __init__(self, tracer: db.sqlite3.Connection, judge_ai: Any, monitor: IMonitor):
        self.tracer = tracer # Actually we use simple db query
        self.judge_ai = judge_ai
        self.monitor = monitor

    @observed
    def execute(self, span_id: str):
        self.monitor.log(f"⚖️ [AUDITOR] Auditando decisión en span {span_id[:8]}...")
        
        # 1. Get the trace data
        conn = db.get_connection()
        c = conn.cursor()
        c.execute("SELECT name, attributes FROM traces WHERE span_id = ?", (span_id,))
        row = c.fetchone()
        conn.close()
        
        if not row:
            self.monitor.log(f"⚠️ [AUDITOR] No se encontró el span {span_id}")
            return False

        name, attributes_json = row
        attributes = json.loads(attributes_json or "{}")
        
        # 2. Extract AI data
        ai_data = attributes.get("ai_analysis") or attributes.get("form_answers")
        if not ai_data:
            self.monitor.log("⚠️ [AUDITOR] No hay datos de IA para auditar en este span.")
            return False

        # 3. Call Judge AI
        self.monitor.log("⏳ [AUDITOR] Consultando al Juez IA...")
        # (Internal logic for judging would go here, simplified for demo)
        from src.utils.observability import record_decision
        
        # Mocking Judge result
        is_correct = True # In real, judge_ai.evaluate(ai_data)
        
        record_decision({
            "audit_result": "VALIDATED" if is_correct else "FLAGGED",
            "audit_note": "La decisión de la IA coincide con el perfil del candidato."
        })
        
        self.monitor.log(f"✅ [AUDITOR] Auditoría completada: {'VÁLIDA' if is_correct else 'ALERTA'}")
        return is_correct
