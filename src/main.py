from src.app.bots.search.manager import SearchBotManager

# --- CONFIGURACIÓN DE PRODUCCIÓN / PRUEBA ---
# ¿Cuántas ofertas buscar por categoría? (25 para pruebas, 400 para buscar TODO)
LIMIT = 150 

# ¿Buscar solo la primera categoría (cargo/ubicación) o todas las configuradas?
# True = Solo la primera | False = Todas
SINGLE_CATEGORY = False 
# ¿Solo re-analizar las ofertas existentes o buscar nuevas?
# True = Solo re-analizar (sin abrir navegador) | False = Buscar y Analizar
RE_ANALYZE_ONLY = False
# --------------------------------------------

if __name__ == "__main__":
    # Modo Reclutamiento Completo (Con IA y Aplicación automática)
    bot = SearchBotManager()
    bot.run(
        job_limit=LIMIT, 
        single_combo_only=SINGLE_CATEGORY, 
        skip_processor=False,
        skip_collector=RE_ANALYZE_ONLY
    )
