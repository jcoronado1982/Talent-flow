# 🤖 Manual Operativo Maestro de TalentFlow para Claude

> **PROPÓSITO:** Esta es la guía técnica y operativa definitiva para que Claude (y cualquier otro agente de IA) gestione el repositorio **TalentFlow** con precisión militar, sin cometer errores de automatización y protegiendo al 100% la cuenta y reputación de **Jesús Coronado**.

---

## 🛑 REGLAS DE ORO INQUEBRANTABLES (LÉELAS ANTES DE TOCAR CUALQUIER ARCHIVO)

1. **PROHIBIDO EL USO DE PYTHON:**
   * El sistema está **100% migrado a RUST NATIVO (`cargo`)**.
   * **NUNCA** ejecutes `./.venv3.13/bin/python`, `python3 -m src.main`, `pip`, ni intentes revivir entornos virtuales viejos. Esos archivos en `src/` están bloqueados por seguridad.
   * Toda la ejecución se realiza exclusivamente a través del binario nativo en Rust: `cargo run -- <comando>`.

2. **MODO HUMANO PURO (CDP NATIVO):**
   * **NUNCA** utilices librerías estándar de Playwright, Puppeteer o Selenium que inyecten `--enable-automation` o `navigator.webdriver = true`. LinkedIn y Google bloquean las cuentas de inmediato al detectar esas banderas.
   * El navegador se ejecuta como un proceso nativo del sistema conectándose vía WebSocket CDP a Chrome (`/usr/bin/google-chrome`).

3. **EL PROTOCOLO DEL SUPERVISOR (CERO BUCLES CIEGOS):**
   * Toda acción de autenticación y búsqueda está auditada por un **Supervisor Interno**.
   * Antes de reportar que algo funcionó o falló, **debes leer [`logs/audit.jsonl`](file:///home/jcoronado/Desktop/dev/TalentFlow/logs/audit.jsonl)**. Si el Supervisor dice `OK (VERIFIED)`, el paso es válido; si dice `FAIL`, se detiene de inmediato.

---

## 🚀 TABLA DE COMANDOS OFICIALES PARA CLAUDE

Cuando el usuario te pida ejecutar o probar cualquier parte del sistema, utiliza **únicamente** estos comandos desde la raíz del proyecto:

| Tarea Solicitada | Comando Exacto a Ejecutar en Rust | Qué Hace Internamente |
| :--- | :--- | :--- |
| **Limpieza previa** | `rm -f user_data*/SingletonLock && pkill -9 -f chrome \|\| true` | Elimina candados y procesos zombis de Chrome. |
| **1. Autenticación (Paso 1)** | `cargo run -- step1-auth --profile user_data_safe` | Abre Chrome en modo humano, va a `/in/me/`, verifica que la sesión sea de *Jesús Coronado*, lo audita en `logs/audit.jsonl` y sale. |
| **2. Búsqueda de Empleos (Paso 3)** | `cargo run -- search --profile user_data_safe --country Colombia --limit 10` | Ejecuta el flujo supervisado, realiza scroll con física de 60 FPS, hace clic en cada oferta, desplaza la descripción en la derecha y guarda vacantes en `talentflow.db`. |
| **3. Iniciar Dashboard** | `cargo run -- dashboard` | Inicia el servidor backend reactivo en Rust (Axum) en el puerto **http://localhost:8001**. |
| **4. Ver Estadísticas DB** | `cargo run -- stats` | Muestra el recuento de vacantes (`Total`, `Matched`, `Pending`, `Discarded`). |
| **5. Postulación (Apply Bot)** | `cargo run -- apply --dry-run` *(Auditoría)*<br>`cargo run -- apply` *(Envío real)* | Procesa las vacantes `Matched` pendientes seleccionando el PDF exacto en `cv/`. |
| **6. Postulación Externa Directa** | `cargo run -- apply-external --dry-run` *(Auditoría)*<br>`cargo run -- apply-external` *(Envío real)* | Aplica directamente a vacantes externas usando su `external_link` sin pasar por LinkedIn. Soporta `--job-id`, `--status` y `--limit`. |
| **7. Login Asistido (Manual)** | `cargo run -- login --profile user_data_safe` | Abre la ventana de login para que el usuario humano inicie sesión si las cookies expiraron. |
| **8. Rehidratar Vacantes Incompletas** | `cargo run -- rehydrate --profile user_data_safe` | Recorre las vacantes con descripción vacía en SQLite, visita su URL directa, extrae requisitos y re-evalúa con Gemini. |

---

## 🧠 CÓMO FUNCIONA EL MOTOR DE NAVEGACIÓN Y STEALTH

1. **Huella Digital Real:**
   * Chrome se ejecuta con el perfil persistente `user_data_safe`, que ya contiene la sesión de Google y LinkedIn activa.
   * `navigator.webdriver` es reescrito dinámicamente como `undefined`.
   * Se inyectan los plugins estándar de Chrome y el objeto `window.chrome.runtime`.

2. **Física de Desplazamiento y Clics (Física 60 FPS):**
   * **Lista izquierda (`.jobs-search-results-list`):** Se desplaza con aceleración y desaceleración suave (Easing cuadrático).
   * **Selección de Oferta:** Hace clic real en el título de la tarjeta para que LinkedIn abra el detalle en el panel derecho.
   * **Lectura del Panel Derecho (`#job-details`):** Desplaza suavemente la descripción del puesto hacia abajo (+300px y +350px) para simular la lectura humana de requisitos técnicos antes de registrarla en SQLite.

---

## 🔍 PROTOCOLO DE DIAGNÓSTICO PARA CLAUDE

Si el usuario te pregunta *"¿qué pasó?"*, *"¿por qué falló?"* o *"¿qué dice el log?"*:
1. **NO adivines ni inventes respuestas.**
2. Lee inmediatamente las últimas líneas del archivo **[`logs/audit.jsonl`](file:///home/jcoronado/Desktop/dev/TalentFlow/logs/audit.jsonl)**.
3. Informa al usuario:
   * El estado del Supervisor (`OK` o `FAIL`).
   * El nombre de la cuenta auditada.
   * La cantidad exacta de ofertas procesadas y guardadas.

---

## 📚 DOCUMENTACIÓN DEL MOTOR DE POSTULACIÓN

**Léelos antes de tocar `src_rust/services/apply/` o `ai_client.rs`.** Explican decisiones que no son evidentes desde el código y evitan "arreglar" cosas que son intencionales.

| Documento | Qué cubre |
| :--- | :--- |
| **[`MOTOR_DE_RESOLUCION.md`](./MOTOR_DE_RESOLUCION.md)** | La cadena de resolución (DOM → perfil JSON → deducción → agente → visión), selección de CV, ruteo de modelos, esperas adaptativas y **bugs conocidos pendientes**. |
| **[`ANALISIS_DOM_Y_LLENADO.md`](./ANALISIS_DOM_Y_LLENADO.md)** | Nivel DOM: por qué cada componente difícil (botones Sí/No, `<select>` de React, typeahead/autocompletar, campos obligatorios) fallaba y cómo se reconoce ahora. |

### ⚠️ Dos cosas que parecen bugs y NO lo son

1. **Los tres modelos hardcodeados** en `job_processor.rs` y `external_processor.rs` (`with_custom_model(...)`) son **intencionales**: el usuario los cambia a mano para probar proveedores. **No los conviertas en configuración** ni los "arregles" para que lean del `.env`.
2. **`DEVELOPER_ONLY = true`** en `resume_manager.rs`: hoy solo existen dos CVs (inglés y español) y **los de Leader no se envían nunca**, aunque la vacante sea de líder. Toda la lógica legacy de ciudad/tecnología/experiencia se dejó intacta a propósito para poder revertirlo con el flag. **No la borres.**
