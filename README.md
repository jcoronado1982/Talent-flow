# 🦀 TalentFlow — Engine de Empleo y Postulación (100% Rust Nativo)

Sistema automatizado de alta resiliencia para búsqueda de empleo en LinkedIn, análisis con IA local (`llama.cpp`) y postulación inteligente.

---

### ⚠️ Regla de Oro del Proyecto
Este proyecto fue **100% migrado a Rust nativo**. 
* **NO se utiliza Python** para la ejecución, automatización ni backend del sistema.
* Quedan prohibidos comandos tipo `python`, `.venv` o `pip` en los flujos del sistema.
* *(Solo el agente de Gemini tiene autorización para crear scripts efímeros de apoyo analítico cuando actúa de forma independiente).*

---

### 🧠 Documentación Maestra
* 📄 **[`project_overview.md`](file:///home/jcoronado/Desktop/dev/TalentFlow/project_overview.md)**: Especificación técnica, componentes y arquitectura.
* 📄 **[`MANUAL_DE_USO.md`](file:///home/jcoronado/Desktop/dev/TalentFlow/MANUAL_DE_USO.md)**: Comandos de ejecución rápida (`cargo run -- ...`).
* 📄 **[`CLAUDE.md`](file:///home/jcoronado/Desktop/dev/TalentFlow/CLAUDE.md)**: Guía para Claude y agentes de IA sobre el modo humano puro y supervisión.
* 📄 **[`ARQUITECTURA_Y_PLAN_RUST.md`](file:///home/jcoronado/Desktop/dev/TalentFlow/ARQUITECTURA_Y_PLAN_RUST.md)**: Plan maestro y árbol de diagnóstico de 4 pasos.

---

### ⚡ Inicio Rápido

```bash
# 1. Limpieza de procesos
rm -f user_data*/SingletonLock && pkill -9 -f chrome || true

# 2. Verificar autenticación (Paso 1)
cargo run -- step1-auth --profile user_data_safe

# 3. Iniciar Dashboard
cargo run -- dashboard
```
