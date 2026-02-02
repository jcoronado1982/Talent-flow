from src.app.bots.search.manager import SearchBotManager

# --- CONFIGURACIÓN DE PRUEBA (MODIFICABLE) ---
# ¿Cuántas ofertas buscar en total? (Ejemplo: 25 para prueba rápida, 1000 para buscar todas)
LIMIT = 1000 

# ¿Buscar solo la primera categoría (cargo/ubicación) o todas las configuradas?
# True = Solo la primera | False = Todas
SINGLE_CATEGORY = True 
# --------------------------------------------

if __name__ == "__main__":
    # Modo Solo-Búsqueda (Sin IA, con tiempos de seguridad)
    bot = SearchBotManager()
    bot.run(
        job_limit=LIMIT, 
        single_combo_only=SINGLE_CATEGORY, 
        skip_processor=True
    )
