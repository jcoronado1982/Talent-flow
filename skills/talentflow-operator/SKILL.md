---
name: talentflow-operator
description: Skill maestro para operar el sistema TalentFlow (Búsqueda de Empleo en Rust 100% Nativo). Prohíbe Python, exige CDP en Modo Humano y aplica el protocolo del Supervisor.
---

# 🎖️ Manual Táctico del Operador TalentFlow (SOP)

Este repositorio es un sistema automatizado de búsqueda y postulación en LinkedIn de **alta criticidad**. Protege en todo momento la reputación de **Jesús Coronado**.

## 🛑 REGLAS DE ORO
1. **PROHIBIDO USAR PYTHON:** El sistema fue migrado a **100% Rust Nativo**. Prohibido ejecutar scripts viejos en `src/`, `.venv` o `pip`.
2. **MODO HUMANO PURO (CDP):** Chrome solo se controla mediante `chromiumoxide` conectado al proceso nativo de Chrome. Prohibido usar Playwright/Selenium estándar para no inyectar banderas de bot.
3. **EL SUPERVISOR:** Lee siempre `logs/audit.jsonl` antes de emitir cualquier diagnóstico.

## ⚙️ COMANDOS OFICIALES DE OPERACIÓN

```bash
# 1. Limpieza inicial obligatoria
rm -f user_data*/SingletonLock && pkill -9 -f chrome || true

# 2. Tarea 1: Autenticación y Supervisión de Identidad
cargo run -- step1-auth --profile user_data_safe

# 3. Tarea 3: Búsqueda con Física Humana 60 FPS y Lectura de Oferta
cargo run -- search --profile user_data_safe --country Colombia --limit 10

# 4. Iniciar Servidor Dashboard (Axum :8001)
cargo run -- dashboard

# 5. Estadísticas de la Base de Datos
cargo run -- stats

# 6. Apply Bot (Postulaciones automáticas)
cargo run -- apply --dry-run   # Modo auditoría
cargo run -- apply             # Envío real
```

## 📝 PROTOCOLO DE AUDITORÍA
Para responder sobre el estado de las tareas, revisa las últimas entradas en `logs/audit.jsonl`.
