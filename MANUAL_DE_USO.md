# 🚀 TalentFlow - Manual de Uso

Este archivo contiene toda la información necesaria para ejecutar el bot de búsqueda de empleo. Sigue estas instrucciones para iniciar el proyecto en cualquier momento.

## ⚡ Comando Rápido (Start Project)

Para iniciar la búsqueda, análisis y generación del reporte, solo ejecuta este comando en la terminal:

```bash
python3 -m src.main
```

## 🧠 ¿Qué hace este comando?

El script `src/main.py` ejecuta automáticamente todo el flujo de trabajo:

1.  **Autenticación Automática:**
    *   Roba la sesión de tu Chrome local (`/usr/bin/google-chrome`) para entrar a LinkedIn y Google sin pedir contraseñas.
    *   *Nota:* Si ves advertencias de seguridad, el script intentará manejarlas.

2.  **Búsqueda de Empleos:**
    *   Busca "Technical Lead" (configurado en `main.py`) en **Bogotá, Colombia**.
    *   Filtra ofertas de los **últimos 3 días**.
    *   Analiza las primeras **10 ofertas** encontradas.

3.  **Análisis con IA (Gemini):**
    *   Extrae la descripción de cada empleo.
    *   La compara con tu perfil (`config/profile_config.json`).
    *   Calcula un `% Match` (Porcentaje de Coincidencia).
    *   **Filtro:** Solo guarda empleos con **Match > 30%**.

4.  **Generación de Reporte:**
    *   Busca la plantilla Excel: `report_1_13_01_2026_10_31.xlsx`.
    *   Rellena los datos encontrados.
    *   Guarda un nuevo archivo: `report_FILLED_[FECHA]_[HORA].xlsx`.

## 📂 Archivos Importantes

*   `src/main.py`: El cerebro principal. Aquí puedes cambiar el cargo a buscar o la ubicación.
*   `src/browser.py`: Controla el navegador y el Excel.
*   `config/profile_config.json`: Tu perfil profesional. Modifícalo si aprendes nuevas skills.
*   `report_FILLED_...xlsx`: Los reportes generados.

## 🛠️ Solución de Problemas

*   **Error "SingletonLock":** Si el script falla y dice que Chrome está bloqueado, ejecuta:
    ```bash
    rm -f user_data/SingletonLock
    pkill -9 -f chrome
    ```
*   **Match 0%:** Verifica que `src/brain.py` esté leyendo bien tu perfil. (Ya fue corregido para inyectar el perfil en cada prompt).

---
**Nota para el Agente AI:**
Si el usuario dice "inicia el proyecto", tu única tarea es ejecutar `python3 -m src.main`. Todo lo demás está automatizado.
