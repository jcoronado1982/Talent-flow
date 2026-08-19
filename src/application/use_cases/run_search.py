import os
import multiprocessing
import threading
from src.domain.interfaces import IMonitor
from src.config.settings import Settings
from src.utils.observability import observed

class ExecuteSearchProjectUseCase:
    def __init__(self, monitor: IMonitor):
        self.monitor = monitor

    @observed
    def execute(self, collector_fn, processor_fn, stop_event: multiprocessing.Event):
        self.monitor.log("🚀 [USE-CASE] Iniciando Proyecto de Búsqueda...")
        
        # This orchestrates the high-level threads/processes
        # It's an extraction of the run() logic from SearchBotManager
        
        t_collector = threading.Thread(target=collector_fn, name="CollectorThread")
        
        # Define the subordinate process
        # (In a real implementation, we'd pass the actual processor class)
        proc = multiprocessing.Process(target=processor_fn, name="ProcessorSubordinate")
        
        proc.start()
        t_collector.start()
        
        self.monitor.log(f"✅ [USE-CASE] Hilos y procesos orquestados con éxito.")
        
        return proc, t_collector
