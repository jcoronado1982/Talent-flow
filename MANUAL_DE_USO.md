# 🚀 TalentFlow — Manual de Uso (100% Rust Nativo)

Este documento contiene la guía operativa para ejecutar el motor de búsqueda, análisis y monitoreo en Rust.

---

## ⚡ Inicio Rápido (Step-by-Step)

### 1. Limpieza de Procesos Residuales
Antes de iniciar, asegúrate de que no haya procesos de Chrome o candados bloqueando el perfil:
```bash
rm -f user_data*/SingletonLock
pkill -9 -f chrome
```

---

### 2. Tarea 1: Verificación de Login y Supervisión de Identidad
Valida en segundos que la sesión de LinkedIn esté activa y a nombre de tu cuenta:
```bash
cargo run -- step1-auth --profile user_data_safe
```
*Si la sesión expiró o es la primera vez que configuras una cuenta, ejecuta:*
```bash
cargo run -- login --profile user_data_safe
```

---

### 3. Iniciar el Dashboard en Vivo (Rust + Axum)
Inicia el servidor backend en el puerto **8001**:
```bash
cargo run -- dashboard
```
*El dashboard estará disponible en: **http://localhost:8001***

---

### 4. Consultar Estadísticas de la Base de Datos
Para ver el resumen de vacantes en `talentflow.db`:
```bash
cargo run -- stats
```

---

### 5. Ejecutar Postulación Automática (Apply Bot)
* **Modo Auditoría (Dry-Run — llena formularios sin enviar):**
  ```bash
  cargo run -- apply --dry-run
  ```
* **Modo Real (Envía aplicaciones y verifica contra LinkedIn):**
  ```bash
  cargo run -- apply
  ```

---

## 📂 Archivos y Configuraciones Críticas

* `config/profile_config.json`: Perfil profesional, roles objetivo, pretensión salarial y datos de contacto.
* `config/cv_profile.json`: Matriz de selección de CVs por rol, tecnología e idioma.
* `cv/`: Carpeta con los archivos PDF de currículums.
* `logs/audit.jsonl`: Bitácora forense de auditoría paso a paso.
* `talentflow.db`: Base de datos SQLite (WAL) con todo el historial de vacantes.
