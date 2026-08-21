# 🧩 TalentFlow — Motor de Resolución de Postulaciones

> Cómo el bot decide **qué responder**, **con qué CV** y **con qué modelo** al postularse a una oferta.
> Complementa a [`ANALISIS_DOM_Y_LLENADO.md`](./ANALISIS_DOM_Y_LLENADO.md), que cubre el nivel de DOM (cómo se *reconoce* cada componente). Este documento cubre el nivel de decisión (qué se hace una vez reconocido).

**Última actualización:** 2026-08-21

---

## 1. La Cadena de Resolución (orden obligatorio)

El principio es **de lo barato y determinista a lo caro e incierto**. Cada escalón solo se activa si el anterior no resolvió.

```
1. DOM determinista      → gratis, instantáneo, reproducible
2. Perfil JSON           → gratis, el dato real del candidato
3. Deducción del LLM     → una llamada de API (solo campos obligatorios)
4. Agente de solo-texto  → varias llamadas, lee el DOM y actúa
5. Rescate visual        → captura de pantalla + visión (ÚLTIMO RECURSO)
```

### Escalón 1 — DOM determinista
`dom.rs::scan_form_structure` arma el esquema del formulario, y `form.rs` resuelve por coincidencia de etiqueta sin tocar ninguna IA: salario, LinkedIn, nombre, apellido, email, país, teléfono, modalidad, inglés y años de experiencia por skill.

### Escalón 2 — Perfil JSON
Lo que no se resolvió va al LLM **junto con el perfil** (`config/profile_config.json`). La instrucción es copiar el dato **exacto** del perfil.

### Escalón 3 — Deducción (solo si es obligatorio)
Reglas 8 y 9 del prompt de `answer_form`:

* **`required: true`** → si el perfil no trae el dato, el modelo **deduce la respuesta más razonable** del contexto de la vacante. Un solo obligatorio en blanco hace que el portal rechace el formulario entero, así que una respuesta sensata es preferible a un vacío.
* **`required: false`** → si no se puede resolver con el perfil, **se deja vacío**. No bloquea el envío y no vale la pena inventar.
* **Excepción absoluta:** teléfono, email, nombre, documento y enlaces **nunca** se inventan, ni siendo obligatorios. Si el perfil no los trae, va cadena vacía.

### Escalón 4 — Agente de solo-texto
Cuando el llenado determinista reporta `needs_human` (widget raro, obligatorio sin resolver, muro de login), se releva a `agent.rs::run_agent`, que trabaja sobre un snapshot semántico del DOM y elige **una acción por turno** de un vocabulario cerrado (`type`, `select`, `check`, `click`, `upload_resume`, `press_key`, `scroll`, `wait`, `navigate`, `eval_js`, `done`, `needs_human`).

### Escalón 5 — Rescate visual
Ver sección 4.

---

## 2. Selección del CV

> **Estado actual: solo se envían DOS hojas de vida**, inglés y español. La elección se reduce al idioma de la oferta.

| Idioma detectado | Archivo |
| :--- | :--- |
| Inglés | `cv/Developer/CV_D_EN_Jesus_Coronado.pdf` |
| Español | `cv/Developer/CV_D_ES_Jesus_Coronado.pdf` |

Los `cv/Leader/CV_15_*` que siguen en disco son **material viejo que no se envía**. Si una vacante se detecta como Leader/Arquitecto/Manager, **igual se manda el CV de Developer**.

### Por qué hay que cerrarlo en tres lugares
Cerrar solo la selección determinista no alcanzaba: había **tres** caminos por los que se podía colar un CV de Leader.

| # | Camino | Qué pasaba | Cierre |
| :-- | :--- | :--- | :--- |
| 1 | `get_resume_filename` | Rol "Lead/Architect" → carpeta `Leader/` | Fuerza `Developer` y lo avisa en el log |
| 2 | `available_resumes` → LLM | Le pasaba **los 12 archivos** de Leader al modelo, y el prompt decía *"si es arquitecto/líder/manager usa CV de Líder"* | El inventario excluye Leader; el prompt ahora dice que el cargo **no** cambia la elección |
| 3 | `best_available_resume` | El degradado podía caer en un Leader | Los salta |

Además, si una fila vieja de la DB trae un CV de Leader preseleccionado de una corrida anterior, **se ignora** en vez de reenviarlo.

### El interruptor
```rust
// src_rust/services/apply/resume_manager.rs
const DEVELOPER_ONLY: bool = true;
```

Toda la lógica legacy (ciudad / tecnología / experiencia / scoring) **quedó intacta a propósito**: poner el flag en `false` reactiva los CVs de Leader sin reescribir nada.

### Validación de la elección de la IA
`choose_resume_smart` sigue consultando al LLM, pero su respuesta ahora **se valida**: si devuelve el CV del idioma contrario al detectado, se descarta y se mantiene la selección determinista. Con dos archivos que solo difieren en el idioma —y el idioma ya detectado de forma determinista— el modelo no puede aportar nada que compense el riesgo de mandar el CV equivocado.

---

## 3. Ruteo de Modelos

### Cómo se elige el proveedor
**Por el nombre del modelo, no por configuración.** `query_llm_with_model` inspecciona el string:

| Contiene | Proveedor |
| :--- | :--- |
| `claude`, `anthropic` | Anthropic |
| `gpt`, `terra`, `o1`, `o3`, `o4` | OpenAI |
| `gemini`, `gemma` | Google |

Si el proveedor primario falla, cae en cascada: **Claude → OpenAI → Gemini → Steel Wasp → Ollama local**.

### Los tres modelos se cambian a mano
Es intencional. Están fijados en el código y el usuario los edita directamente:

```rust
// job_processor.rs:57        — LinkedIn / Easy Apply
AiClient::with_profile(...).with_custom_model("gemini-3.7-flash")

// job_processor.rs:233       — externas lanzadas desde LinkedIn
ai_client.with_custom_model("claude-sonnet-5")

// external_processor.rs:62   — externas directas
AiClient::with_profile(...).with_custom_model("claude-sonnet-5")
```

El **scraping/búsqueda** (`browser.rs`) usa `AiClient::new()`, que toma `GEMINI_MODEL` del `.env` → **siempre Gemini**.

### ⚠️ Trampa resuelta: `with_custom_model` pisaba el modelo de Gemini
`with_custom_model` sobrescribe el campo `gemini_model`, que es el que rutea. Pero ese **mismo campo** se usaba como "el modelo Gemini configurado" en el fallback:

```rust
// ANTES — bug
let actual_model = if model.contains("gemini") { model } else { &self.gemini_model };
```

Con `"claude-sonnet-5"` activo, el fallback armaba `…/v1beta/models/claude-sonnet-5:generateContent` → **404 garantizado**. El escalón Gemini del cascade **nunca podía funcionar** cuando el modelo activo era de otro proveedor.

**Corrección:** se agregó `gemini_model_configured`, fijado al construir desde `GEMINI_MODEL`/`cloud_model` y **nunca** pisado por `with_custom_model`. El fallback lo usa a él.

---

## 4. Rescate Visual (último recurso)

> **Regla:** primero los métodos tradicionales. La imagen solo si eso no resolvió.

### Cuándo se dispara
En los **dos** puntos donde el agente antes se rendía y saltaba a la siguiente oferta:

1. **La página dejó de cambiar** tras 3 acciones seguidas (`unchanged_rounds >= 3`).
2. **El modelo respondió `needs_human`** leyendo solo el DOM.

### Qué hace
1. Captura la pantalla (`capture_screenshot_base64`) y guarda copia en `debug/screenshots/agent_stuck_<timestamp>.png` para auditoría.
2. Manda la imagen **junto al mismo prompt del agente** (`build_agent_prompt` es compartido, así razona con reglas idénticas) más el motivo del atasco.
3. Le pide específicamente que busque **lo que el DOM no puede mostrar**:
   * Controles visibles que no están en el JSON (pintados en canvas, widgets sin texto ni ARIA).
   * Mensajes de error o campos marcados en rojo que expliquen por qué no avanza.
   * Preguntas cuyo enunciado está en una imagen.
   * Casillas obligatorias (términos, consentimiento) sin marcar.
4. Si propone una acción nueva, se ejecuta (`pending_decision`) y el agente continúa. Si tras ver la imagen **insiste** en rendirse, se respeta: ya no queda camino.

### Restricciones
* **Una sola vez por oferta** (`vision_attempted`). Es cara y lenta: es una alternativa a perder la oferta, no un atajo.
* Usa **el modelo que esté aplicando**. Como se cambian a mano, los **tres** proveedores tienen soporte de imagen y el ruteo se decide igual que en texto:

| Proveedor | Formato de imagen |
| :--- | :--- |
| Anthropic | bloque `image` con `source.type = base64` |
| OpenAI | `content` con `image_url` → `data:image/png;base64,…` |
| Gemini | `parts` con `inline_data.mime_type = image/png` |

* Dependencia agregada: `base64 = "0.22"` (ya estaba en `Cargo.lock` como transitiva).

---

## 5. Esperas Adaptativas en Formularios Externos

La espera de hidratación (20 s) solo corría **una vez, antes del bucle**. Todas las navegaciones *dentro* del bucle usaban sleeps fijos, y un ATS que redirige y monta el formulario por JS tardando más que el sleep hacía que el bot contara 0 campos, concluyera *"aquí no hay formulario"* y **quemara el paso entero** buscando un botón Apply que ya no existía. Con 8 pasos de presupuesto, dos o tres de esos y se quedaba sin intentos.

| Momento | Antes | Ahora |
| :--- | :--- | :--- |
| Tras clic en Apply | `sleep(2s)` fijo | 1 s (para descartar envío de un clic) + `wait_for_form_inputs` hasta **12 s** |
| Tras auth con Google | `sleep(3s)` fijo | 2 s + `wait_for_form_inputs` hasta **12 s** |
| Tras clic en Next | `sleep(1500ms)` fijo | 800 ms + `wait_for_form_inputs` hasta **10 s** |

`wait_for_form_inputs` devuelve **apenas** aparecen los campos, así que un sitio rápido es **más rápido que antes** (no paga los 2 s fijos) y uno lento tiene hasta 12 s en vez de rendirse.

### Autenticación con Google
Se intenta **antes** de llenar cualquier formulario de registro: Chrome corre el perfil persistente ya autenticado, así que un botón "Continuar con Google" es más rápido y confiable que inventar credenciales y quedarse trabado en una verificación por email.

Está **limitado a 2 intentos** (`MAX_GOOGLE_AUTH_ATTEMPTS`). Sin ese tope, un enlace persistente de "Sign in with Google" en el header —no relacionado con la postulación— se pulsaba en cada uno de los 8 pasos y el bot nunca llegaba al formulario real.

---

## 6. Bugs Conocidos Pendientes

> Documentados, verificados por lectura de código, **sin corregir**.

### 🟠 A. Checkboxes sin `name`: se fusionan y no se pueden llenar
`dom.rs` — agrupación de radios/checkboxes sueltos:
```js
const name = inp.getAttribute('name') || 'unnamed_' + inp.getAttribute('value');
```
Un input sin `name` **ni** `value` produce la clave `"unnamed_null"`, **la misma para todos**. Dos checkboxes independientes ("Acepto términos", "Quiero novedades") colapsan en un solo campo con las etiquetas mezcladas.

Peor: `fill_choice_field` exige `grp.tagName === 'INPUT' && grp.name`. Con `name` vacío cae al `else`, que hace `grp.querySelectorAll(...)` sobre un `<input>` —elemento vacío por definición— → siempre `[]` → devuelve `false` → `NeedsHuman` → relevo forzado al agente por un campo que el motor determinista debería resolver solo.

### 🟠 B. Doble toggle: el checkbox se marca y se desmarca
`dom.rs::fill_choice_field`:
```js
const input = opt.querySelector('input');
if (input) { input.checked = true; /* …dispatch… */ }
opt.click();
```
Si `opt` es un `<label>` que **envuelve** al input: se pone `checked = true`, y `label.click()` reenvía la activación al control → el navegador lo **alterna** → queda desmarcado. Los radios se salvan (no se destoglean), los checkboxes no.

Es preexistente, pero la rama nueva mapea `inp.closest('label')` **primero**, que es justo el patrón roto.

### 🟡 C. `data-tf-id` nunca se limpia entre escaneos
No existe ningún `removeAttribute('data-tf-id')`. Como los escáneres hacen `if (inp.hasAttribute('data-tf-id')) return;`, al re-escanear un DOM que **no navegó** (SPA) todos los campos ya etiquetados desaparecen del esquema — incluidos sus errores de validación. `fill_form` se llama en cada paso del bucle, así que desde el paso 2 puede estar operando sobre un esquema vacío y pulsando Submit a ciegas.
*Confianza media — conviene confirmarlo en vivo.*

### 🟡 D. Los CV de Leader nunca hacían match determinista
`cv_profile.json` fija `experience: "20"` pero **todos** los archivos en disco son `CV_15_*`. El nombre construido (`CV_20_M_L_P_EN_…`) no existe jamás → siempre degradaba por `best_available_resume`. Hoy es inofensivo porque `DEVELOPER_ONLY` corta antes, pero **reaparecería** al poner el flag en `false`.

También: el fallback sin config (`resume_manager.rs`) apunta a `CV_15_M_D_P_ES_Jesus_Coronado.pdf`, que **ya no existe** en disco.

---

## 7. Estado de Verificación

| Qué | Cómo se verificó |
| :--- | :--- |
| Compilación | `cargo check` / `cargo build` — limpio, sin warnings nuevos |
| Tests | `cargo test` — 30/30 pasan |
| Selección de CV | 3 tests unitarios: idioma correcto, vacante Leader → CV Developer, CV Leader guardado en DB → ignorado |
| Ruteo de modelos | Lectura de código + verificación de `.env` y `config/profile_config.json` |

> ⚠️ **Nada de esto se ha ejecutado contra un ATS real.** El rescate visual en particular hace llamadas de API con imágenes que no se han visto funcionar en vivo.
>
> Para probar sin enviar nada:
> ```bash
> cargo run -- apply-external --dry-run
> ```
