# Port de Apply Automation a Rust — Bitácora de la sesión (2026-08-18)

Este documento resume el trabajo hecho para llevar el motor de aplicación automática
("Apply Bot") de Python a Rust, los incidentes reales ocurridos durante las pruebas,
y el estado actual del sistema. Léelo antes de retomar este trabajo.

## Contexto

El objetivo era que **todo el sistema (búsqueda + análisis + apply + dashboard)
corriera en Rust**, reemplazando por completo el bot en Python. La búsqueda/análisis
y el dashboard ya estaban portados; faltaba la automatización de aplicar a las
ofertas ("Apply"), que solo existía en `src/app/bots/apply/*.py`.

## Qué se construyó

Nuevo módulo `src_rust/services/apply/`:

- **`resume_manager.rs`** — selección de CV según reglas de `config/cv_profile.json`
  (rol/tecnología/ciudad/idioma) y expectativa salarial de `config/profile_config.json`.
  Sube el CV vía CDP (`DOM.setFileInputFiles`), y **verifica leyendo de vuelta** qué
  archivo quedó realmente adjunto (ver incidente #2 abajo).
- **`dom.rs`** — escaneo del formulario de aplicación (inputs, selects, grupos de
  radio/checkbox) inyectando JS y etiquetando cada campo con `data-tf-id`. Incluye
  detección de "muro de login" en sitios externos, y volcado de HTML crudo a
  `debug/dom/` para depuración (igual que hacía la versión Python).
- **`form.rs`** — motor determinista (salario/años de experiencia por skill) + IA
  (`AiClient::answer_form`, nuevo) para el resto de preguntas del formulario.
- **`application_flow.rs`** — el bucle del modal "Easy Apply" de LinkedIn.
- **`external_flow.rs`** — manejo de aplicaciones a sitios externos (ATS de cada
  empresa), incluyendo bypass de muros de login cuando el sitio lo permite.
- **`job_processor.rs`** — procesa una oferta (detecta si es Easy Apply o externa) y
  el bucle supervisor con pausa anti-baneo (45-90s) entre aplicaciones.

Conectado a `POST /apply` del dashboard y a `talentflow apply [--dry-run]` por CLI.
También se agregaron `talentflow whoami --profile <carpeta>` y
`talentflow login --profile <carpeta>` como herramientas de diagnóstico de cuentas.

## Incidentes reales durante las pruebas (importante — no repetir)

### Incidente 1: envío real no intencional (Synthires)
El botón final de un flujo de LinkedIn se llamaba **"Review"**, no "Submit application".
La validación de modo dry-run solo bloqueaba una lista fija de textos de "enviar", así
que el clic de "Review" pasó de largo y se envió una aplicación real sin querer.

**Fix:** el modo dry-run ya no confía en adivinar qué botón es "el final". Ahora llena
un paso del formulario y **se detiene ahí, sin hacer clic en nada** (ni Submit, ni
Next, ni Review, ni Done). Además, después de cualquier clic que parezca definitivo en
modo real, el código ya no asume éxito: **recarga la oferta original en LinkedIn y lee
la confirmación real** ("Application submitted" / "Postulación enviada") antes de
marcar `Applied`. Ver `application_flow.rs::verify_against_job_page`.

También se descubrió que `external_flow.rs` **no recibía el parámetro `dry_run` en
absoluto** — para ofertas externas el bot siempre habría enviado de verdad. Ya
corregido.

### Incidente 2: CV incorrecto adjuntado (Crossing Hurdles)
La aplicación se envió correctamente, pero el CV que quedó adjunto era
`CV_20_M_D_P_EN_...` (perfil Python) en vez de `CV_20_M_D_C_EN_...` (C#/.NET, el
correcto para esa oferta). Causa: LinkedIn cambió sus clases CSS a nombres hasheados
sin sentido (`_5e54ca0a`, etc.), y el selector `.jobs-document-card__title` que
detectaba "¿ya hay un CV adjunto?" quedó obsoleto — la función de subida no encontró
un campo nuevo para reemplazar el CV que ya estaba adjunto de una prueba anterior, y
no hizo nada, dejando el CV viejo.

**Fix:** ahora se **lee el nombre real** del CV que la página muestra adjunto
(buscando cualquier texto que termine en `.pdf`, sin depender de clases CSS) y se
compara contra el esperado. Si no coincide, reintenta una vez. Si sigue sin coincidir,
**la base de datos ya no miente** — antes, si no se podía verificar, se rellenaba con
el nombre del CV que se *pretendía* usar (falsa confianza). Ahora dice explícitamente
"SIN VERIFICAR" o "INCORRECTO" cuando no hay certeza real.

**Pendiente:** no se implementó un mecanismo para *forzar* el reemplazo de un CV ya
adjunto cuando LinkedIn insiste en quedarse con el viejo — solo detección + un
reintento simple.

### Incidente 3: confusión de cuentas de LinkedIn
Se creyó erróneamente que `user_data_auth`/`user_data_safe` debían usar una cuenta de
LinkedIn "segura" separada (`safe.jcoronado@gmail.com`). Verificación real (`whoami`)
mostró que ambas carpetas de perfil resuelven a la **misma cuenta real**
("Jesus Alberto Coronado / jcoronado1982"). Revisando `config/credentials.yaml` se
confirmó el diseño real:

```yaml
linkedin:
  email: "email.coronado@gmail.com"     # cuenta REAL — usada hoy para todo
computrabajo:
  email: "safe.jcoronado@gmail.com"     # es de Computrabajo, NO de LinkedIn
```

Decisión del usuario: **producción usará `email.coronado@gmail.com`; las pruebas
deben usar una cuenta de LinkedIn separada bajo `safe.jcoronado@gmail.com`**, pero esa
cuenta de LinkedIn **no existe todavía** — hay que crearla manualmente (fuera del
alcance de la automatización). El usuario quedó en crear esa cuenta por su cuenta.

**Herramientas disponibles para retomar esto:**
- `cargo run -- whoami --profile <carpeta>` — abre un perfil, no hace nada más que
  leer qué cuenta está logueada, y cierra. Solo lectura.
- `cargo run -- login --profile user_data_safe` — abre el navegador vacío en el login
  de LinkedIn y espera (hasta 10 min) a que el usuario inicie sesión manualmente.
- Orden de prioridad de perfiles en `launch_authenticated_browser()`
  (`src_rust/services/browser.rs`): `user_data_safe` > `user_data_auth` >
  `user_data_auth_profile_1` > `user_data`.

### Bug técnico pendiente: crash de Chrome bajo Wayland/Vulkan
El lanzador nativo de Chrome ("Modo Humano Puro", ver más abajo) se cae con
`WS Connection error: ResetWithoutClosingHandshake` a los pocos segundos de abrir,
precedido por el warning `'--ozone-platform=wayland' is not compatible with Vulkan`.
Esto causa falsos negativos (ej. "Apply button not found" cuando en realidad se cayó
la conexión, no que el botón no existiera).

**Fix sugerido, no aplicado:** agregar `--ozone-platform=x11` o `--disable-gpu` al
lanzador. **No se aplicó porque esa función está marcada explícitamente
`NO MODIFICAR` en el código** (ver siguiente sección) y no se recibió confirmación
para tocarla.

## Cambio de arquitectura del lanzador de Chrome (hecho por el usuario, no revertir)

El usuario reescribió `launch_browser_with_profile` en `src_rust/services/browser.rs`
para lanzar Chrome como **proceso nativo del SO** (`tokio::process::Command` +
`--remote-debugging-port=9222`) en vez de usar `chromiumoxide::Browser::launch()`.

**Motivo (documentado en el código):** `Browser::launch()` inyecta
`--enable-automation`, lo que dispara el banner "Chrome is being controlled by
automated test software" y **bloquea el login con Google OAuth** en LinkedIn. El
lanzamiento nativo evita esa bandera.

Esta función está marcada `NO MODIFICAR` en el código — respétalo.

También se agregó `src_rust/services/cookie_injector.rs`
(`extract_system_linkedin_cookies()`), que lee y desencripta cookies de LinkedIn
**directamente del Chrome personal del sistema** (`~/.config/google-chrome/...`), y se
usa en `NativeBrowserScraper::run_linkedin_continuous_search` (búsqueda) para inyectar
esa sesión. **Nota de precaución:** esto hace que la búsqueda dependa de qué cuenta
esté activa en el Chrome personal del usuario en cada momento, sin importar qué
carpeta de perfil del proyecto se configure — tenerlo presente si se retoma el tema de
cuentas separadas para pruebas.

## Estado de las pruebas reales realizadas

| Oferta | Empresa | Resultado |
|---|---|---|
| Job 2 | Synthires | Aplicó real sin querer (Incidente 1) — corregido en DB (`Applied`, CV real registrado) |
| Job 4 | Crossing Hurdles | Aplicó real, verificado por LinkedIn, pero con CV incorrecto (Incidente 2) — DB corregida para reflejarlo |
| Job 28 / Job 21 | FullStack / Miratech | Intento fallido por el crash de Wayland/Vulkan — no se llegó a intentar el envío real |

## Actualización 2026-08-18 (segunda mitad de la sesión): cuenta de pruebas y manejo genérico de campos

### Cuenta de pruebas resuelta
`safe.jcoronado@gmail.com` **sí es una cuenta de LinkedIn separada** ("Jesus Coronado",
`linkedin.com/in/jesus-coronado-570352368/`), distinta de la cuenta real
("Jesus Alberto Coronado", `jcoronado1982`). Ya está logueada en `user_data_safe` y
verificada con `cargo run -- whoami --profile user_data_safe`. El orden de prioridad en
`launch_authenticated_browser()` (`src_rust/services/browser.rs`) ya prioriza
`user_data_safe` sobre `user_data_auth`.

### Hallazgos en vivo con la cuenta de pruebas y fixes aplicados

**Bug: campo de ciudad (typeahead) nunca se llenaba.** Confirmado en vivo por el
usuario: el campo mostraba la lista de sugerencias pero nunca se seleccionaba nada, y
el paso quedaba trabado. Causa: `is_combobox` se decidía por adelantado a partir de
`role="combobox"`/`aria-autocomplete`, atributos que LinkedIn ya no expone de forma
confiable (mismo problema de clases hasheadas). **Fix:** `dom.rs::fill_text_like_field`
reemplaza a `fill_text_field`/`fill_combobox_field` — ya no predice si un campo es
autocompletar, siempre escribe con teclas reales y **sondea después** si apareció una
lista de sugerencias (por `aria-controls`/`aria-expanded`, `role=listbox`/`role=option`,
o como último recurso un popup flotante posicionado cerca del input). Si aparece,
la resuelve con teclado y confirma que se cerró antes de dar por bueno el campo.

**Bug: tipos de campo desconocidos se saltaban en silencio.** `form.rs` tenía un
`_ => Ok(false)` que descartaba cualquier campo no reconocido sin dejar rastro. **Fix:**
`scan_form_structure` ahora también detecta cualquier elemento interactivo visible no
clasificado (`contenteditable`, `date`/`range`/`color`, `role=combobox` no-`<input>`,
etc.) como `type: "unknown"`, con su HTML volcado a `debug/dom/unknown_field_*.html`.
`dom::fill_generic_fallback` intenta llenarlo (clic + escribir + Tab, con el mismo
sondeo de popup); si el valor no cambia, no lo "resuelve" — devuelve
`FillOutcome::NeedsHuman`. `fill_form` ahora devuelve un `FillResult` con
`needs_human: Vec<String>`, y tanto `application_flow.rs` como `external_flow.rs`
**se detienen de inmediato** (van a `Manual`, nunca a `Applied`) apenas un campo quede
sin resolver — así se evita seguir avanzando (y arriesgarse a enviar) sobre un
formulario que el bot sabe que no llenó bien.

**Bug: oferta externa en pestaña nueva, confirmado en vivo (Miratech).** El bot no
detectaba cuando "Apply" abría una pestaña nueva (solo detectaba redirección en la
misma pestaña), y se quedaba 15 pasos escaneando la pestaña vieja de LinkedIn mientras
la pestaña real quedaba sin tocar. **Fix:** nuevo módulo
`src_rust/services/apply/tabs.rs` — antes de hacer clic en "Apply" se toma una foto de
las pestañas abiertas (`Browser::pages()`); después del clic se espera hasta 4s a que
aparezca una pestaña nueva ya navegada. chromiumoxide 0.9.1 ya auto-descubre y
auto-adjunta pestañas nuevas por su cuenta (verificado contra el código fuente de la
librería), así que no hizo falta configuración extra. Si aparece una pestaña nueva, se
usa esa como la página activa para el resto del flujo (se trata como externa
automáticamente); si no, se mantiene el chequeo anterior de "misma pestaña cambió de
URL" como respaldo.

Todo compila limpio (`cargo build`) y los 20 tests unitarios siguen pasando. **Estos
tres fixes aún no se han vuelto a probar en vivo** — es lo primero a validar en la
próxima sesión.

## Pendientes para la próxima sesión

1. **Probar en vivo** los tres fixes de arriba (typeahead/ciudad, campos desconocidos,
   pestaña nueva) contra ofertas reales con la cuenta de pruebas (`user_data_safe`).
2. Decidir y aplicar el fix del crash Wayland/Vulkan en `launch_browser_with_profile`
   (pedir confirmación antes de tocar esa función, está marcada NO MODIFICAR).
3. Mecanismo para forzar reemplazo de un CV ya adjunto en LinkedIn cuando LinkedIn
   insiste en quedarse con un documento viejo (Incidente 2, sigue pendiente — hay un
   diseño ya pensado: buscar un botón "quitar/reemplazar" genérico cerca del nombre del
   PDF detectado por `read_attached_resume_filename`, sin depender de clases CSS).
4. Una vez validado, actualizar `.agent/workflows/`, los `.bat`, y los manuales
   (`MANUAL_DE_USO.md`) para que apunten al binario Rust en vez de Python.

---

# Sesión 2026-08-18 (noche): validación en vivo, 11 bugs corregidos y agente de Gemini

Continuación de la sesión anterior. El objetivo era **probar si el Apply Bot funciona de
verdad**. Se probó en vivo (5 corridas en dry-run + 3 envíos reales), lo que destapó una
cadena de bugs que impedían aplicar correctamente. Al final se construyó un agente autónomo
para dejar de depender de listas de etiquetas escritas a mano.

## Estado del entorno al empezar

- El crash de Wayland/Vulkan **no se reprodujo** en ninguna de las ~10 corridas. Chrome
  aguantó siempre. El pendiente #2 de la sesión anterior queda en observación, no aplicado.
- `get_jobs_to_apply` solo consulta `status = 'Matched'` y **no había ninguna oferta en ese
  estado**, así que el bot salía de inmediato. Para probar hay que marcar ofertas a mano:
  `sqlite3 talentflow.db "UPDATE jobs SET status='Matched' WHERE id=N;"`
- `apply_type` está vacío en las 41 ofertas, así que la priorización Easy Apply/Colombia de
  esa consulta hoy no ordena nada.
- Backup íntegro de la DB previo a todo: `talentflow.db.bak` (en el scratchpad de la sesión).

## Postulaciones reales enviadas

| Job | Empresa | Resultado |
|---|---|---|
| 21 | Miratech — Software Architect (R&D) | `Applied`, confirmado por LinkedIn. **CV incorrecto**: se envió `CV_20_M_D_J_EN` (Developer/Java) en vez de `CV_15_M_L_P_EN` (Leader/Python) |
| 21 (2º intento) | Miratech | Abortado por falso positivo de validación (bug #5), no se envió |
| 41 | Grupo DEACERO — AI Agent Engineer (Python/GCP/LLM) | `Applied`, confirmado. **CV correcto y verificado** (`CV_15_M_D_P_EN`) y teléfono real del perfil |

El Job 41 es el primer envío de la historia del proyecto con CV verificado y datos reales.

Todas las pruebas salieron desde `user_data_safe` (cuenta de pruebas
`linkedin.com/in/jesus-coronado-570352368`). **No** desde la cuenta real.

## Bugs corregidos (11)

Todos comparten la misma enfermedad de fondo: **listas de etiquetas y selectores CSS
escritos a mano** que no sobreviven a los rediseños ni a la interfaz en español.

### Lectura del formulario

1. **`dom.rs::getLabel` robaba la etiqueta del campo vecino.** Subía por los ancestros
   haciendo `curr.querySelector('label')`, que devuelve el *primer* `<label>` del subárbol,
   no el del input. Al llegar a un contenedor con varios campos, todos heredaban la misma
   etiqueta. En vivo: el campo de ciudad se leía como `First name*` y el bot escribía
   **"Jesus" en la dirección**. Se verificó contra el DOM real que LinkedIn **sí** pone
   `for=` en todos sus labels (`for="«ri»"`) y que el campo de ciudad no tiene label propio,
   solo `placeholder="Indica una ciudad o ubicación"`.
   *Fix:* orden estándar `aria-label` → `aria-labelledby` → `label[for]` (con `CSS.escape`,
   los ids traen caracteres no ASCII como `«ro»`) → `closest('label')` → ancestros **solo si
   contienen un único control** → placeholder → name.

2. **Falso negativo en el typeahead.** El campo se llenaba bien pero se reportaba como
   fallido y la oferta se iba a `Manual`. LinkedIn deja el `listbox` renderizado *después*
   de seleccionar, y la sonda tomaba "lista abierta" = fracaso.
   *Fix:* `suggestion_popup_match` (antes `has_suggestion_popup`) ahora está acotada al input
   (relación ARIA explícita o proximidad geométrica) y devuelve una descripción de lo que
   hizo match; y sobre todo **se lee el valor del campo**: si quedó resuelto
   (`Medellín, Antioquia, Colombia`), es éxito.

3. **`count_form_inputs` no veía inputs sin `type`.** Listaba `input[type='text']`, etc.; un
   `<input>` sin atributo `type` se comporta como texto pero no matchea. `scan_form_structure`
   ya estaba arreglado para esto, este contador no.
   *Fix:* usa la propiedad `.type` normalizada y excluye la barra de navegación del sitio.

### Selección y subida del CV

4. **La ruta del CV podía no existir.** `resolve_resume_path` devolvía `cv/<nombre>` cuando no
   encontraba coincidencia exacta — una ruta inexistente. El uploader no subía nada y LinkedIn
   **se quedaba con el CV pegado de una sesión anterior**. Causa raíz: `cv_profile.json` fija
   `experience: "20"` pero **no existe ningún `CV_20_*_L_*`** en disco (los `CV_20_*` solo están
   bajo `Developer/`), así que **todo rol de líder/arquitecto construía un nombre imposible**.
   *Fix:* `best_available_resume()` degrada al CV real más cercano ponderando
   rol > tecnología > idioma > ciudad, con la experiencia como desempate; y `job_processor`
   **no aplica** si el CV resuelto no existe (marca `Manual`).

5. **No se podía reemplazar un CV ya adjunto.** Cuando hay un CV pegado, LinkedIn **no
   renderiza ningún `input[type=file]`** (verificado en el volcado del DOM), así que
   `smart_upload_resume` no tenía dónde subir y se rendía en silencio. Este es el Incidente 2
   de la sesión anterior, que seguía abierto.
   *Fix:* `dom.rs::click_replace_resume_control()` busca por texto/ARIA el control que inyecta
   el campo — en la interfaz en español es **`Cargar currículum`**. Primer intento falló porque
   el patrón decía `curriculum` sin tilde; ahora **normaliza acentos (NFD + quita diacríticos)**
   antes de comparar. También se reemplazó la detección por la clase obsoleta
   `.jobs-document-card__title` por la lectura del nombre real del PDF.

### Datos enviados al empleador

6. **Toast de éxito leído como error bloqueante.** `visible_error_message` tomaba cualquier
   `[role='alert']`, y LinkedIn usa ese rol también para confirmaciones. El mensaje
   **"Se ha cargado el currículum"** (que es un éxito) abortó un envío real a mitad de flujo.
   *Fix:* se filtran los mensajes de confirmación antes de tratar un alert como fallo.

7. **El perfil llegaba incompleto a la IA.** `build_profile_yaml` solo emitía nombre,
   ubicación y disponibilidad. **Omitía teléfono, email, DNI, LinkedIn, GitHub y portafolio**,
   aunque `profile_config.json` los tiene. Como el prompt decía "nunca devuelvas null", el
   modelo **inventaba**: en vivo respondió `'1'` a "What is your preferred location".
   *Fix:* se emiten todos los campos de identidad, y el prompt ahora prohíbe explícitamente
   inventar datos de contacto (el "responde 0" quedó acotado a años de experiencia).

8. **Moneda del salario mal declarada.** Las reglas `en` de `salary_expectations` traen USD
   pero **no declaran `currency`**, así que heredaban el `default.currency` = `COP`. El bot
   registró **"2000 COP"** (~USD 0,50) para un rol senior y "4000 COP" para un arquitecto.
   *Fix:* la moneda se deriva del idioma de la regla (`en` → USD, `es` → COP); una `currency`
   explícita sigue mandando. **2 tests de regresión** lo fijan.
   *Nota:* al empleador le llegó solo el número (campo numérico), no la moneda; el error quedó
   en el registro interno. Las filas 21 y 41 de la DB siguen diciendo `COP`.

### Ofertas fuera de LinkedIn

9. **`click_apply_button` no encontraba nada en español.** Los selectores CSS eran clases
   legacy ya podridas (`.jobs-apply-button`, `data-control-name=...`) más aria-labels **solo en
   inglés**. En una cuenta en español, una oferta externa dice `Solicitar` y no la veía.
   *Fix:* selectores en español + recorrido completo del DOM por texto normalizado, y un
   volcado de diagnóstico (`debug/dom/no_apply_button_*.json`) con el inventario de botones y
   detección de "oferta cerrada" cuando falla.

10. **La búsqueda por texto estaba ciega fuera del footer.** `CANDIDATES_JS` hacía
    `return footerEls.length ? footerEls : allEls` — la presencia de **cualquier** `<footer>`
    ocultaba el resto de la página. Pensado para el modal de Easy Apply, rompía las páginas de
    oferta y los ATS. En BairesDev el botón `Apply` está en el contenido y Terms/Privacy/FAQ
    en el footer, así que solo miraba el footer.
    *Fix:* el footer se revisa **primero**, y luego el resto del documento.

11. **`APPLY_LABELS` no incluía el `"Apply"` a secas.** Todas las entradas eran frases
    (`"Apply Now"`, `"Apply for this job"`) y el test es `texto.includes(etiqueta)`, así que un
    botón que dice exactamente `Apply` no matcheaba ninguna. Es el caso de BairesDev.
    *Fix:* se añadieron `Apply` y `Solicitar` al final (el orden importa: las frases
    específicas van primero porque la comparación es por substring).

**Además:** `wait_for_form_inputs()` espera hasta 20s a que una SPA monte su formulario. El
portal de BairesDev es Angular y sirve **0 inputs y 0 forms** en el HTML inicial; el flujo
externo muestreaba a los ~4s y archivaba como `Manual` un formulario perfectamente utilizable.

## Nuevo: agente autónomo de Gemini (`src_rust/services/apply/agent.rs`)

Los 11 bugs de arriba son el mismo problema repetido: **ninguna lista de etiquetas puede
cubrir los miles de ATS que existen**. El agente invierte el diseño — en vez de que el código
decida qué significa cada control, se le entrega al modelo una foto semántica de lo que hay en
pantalla y decide él, una acción por turno.

- **Percepción** — `snapshot()` etiqueta cada elemento interactivo con `data-tf-id` y devuelve
  JSON: campos (nombre accesible, valor, opciones, obligatoriedad, error), botones y el texto
  visible. Cero clases CSS, cero conocimiento de ningún sitio.
- **Decisión** — `AiClient::decide_next_action()` manda snapshot + perfil + historial a Gemini.
- **Ejecución** — vocabulario cerrado sobre CDP: `type`, `select`, `check`, `click`,
  `upload_resume`, `press_key`, `scroll`, `wait`, `navigate`, `eval_js`, `done`, `needs_human`.

**`eval_js`** es el recurso libre: el agente escribe su propio JavaScript para lo que los
verbos no cubren (widgets a medida, shadow DOM, calendarios, arrastrar-soltar) y **lo que el
script devuelve le llega como observación** al turno siguiente, así que también sirve para
explorar antes de decidir.

**Salvaguardas que el modelo no puede saltarse**, todas derivadas de incidentes reales:
- Un `done` se **rechaza** si la página no muestra confirmación de envío.
- Si la página no cambia 3 veces seguidas, se detiene (el bucle de 15 iteraciones ya ocurrido).
- Un verbo desconocido se descarta en vez de reinterpretarse (hay test: `run_shell` se rechaza).
- `navigate` solo acepta `http(s)`; `file://`, `javascript:` y `data:` se rechazan.
- Los ids son siempre `tf_N` del snapshot, así que un id alucinado no resuelve en vez de
  pulsar algo al azar.

**Dónde está conectado hoy:** solo en el **flujo externo** (`external_flow.rs`), como relevo
cuando el camino determinista se atasca y también ante un muro de login sin bypass conocido.

**Primera prueba en vivo (BairesDev):** el agente leyó la página y respondió
`needs_human: "requiere un inicio de sesión (Username y Access Code) que no están en el
perfil"`. El código cableado solo sabía decir "requiere iniciar sesión"; el agente dice
exactamente qué pide, sin que nadie programara esos nombres.

## Bloqueado: agente en el flujo de Easy Apply

Se intentó enrutar al agente los tres puntos de parada de `application_flow.rs` (campo sin
resolver, paso atascado, error de validación). **El sistema de permisos de Claude Code lo
denegó**: dejar sin ningún punto de revisión humana el flujo que corre contra la sesión real
y autenticada de LinkedIn, con un agente que ejecuta JavaScript arbitrario y navega libre,
requiere autorización explícita del usuario. Queda pendiente de que el usuario levante ese
permiso.

## Estado del código

- `cargo build` limpio; **28 tests pasan** (6 nuevos: 4 del agente, 2 de moneda del salario).
- ⚠️ **`src_rust/` sigue sin trackear en git.** Nada de esta sesión tiene respaldo en el
  historial; no hay `git revert` posible.

## Pendientes

1. **Commitear `src_rust/`** — es lo más urgente.
2. Decidir si se levanta el permiso para que el agente entre en Easy Apply.
3. **Herramienta de correo para el agente.** BairesDev pide un `Access Code` que llega por
   email; `project_overview.md` indica que ya hay Gmail MCP accesible vía Steel Wasp. El
   usuario pidió explícitamente esta capacidad.
4. **Credenciales de ATS para el agente.** El usuario ofreció darlas; ya existe
   `config/credentials.yaml` con `linkedin`/`computrabajo`/`elempleo`.
5. Probar si el agente puede usar el **login de Google** de la sesión (el navegador se lanza
   en modo humano puro precisamente para no romper ese OAuth).
6. **Job 28 (FullStack): `Apply button not found`** — sin diagnosticar; ahora el volcado
   `debug/dom/no_apply_button_*.json` dará evidencia real en el próximo intento.
7. `applied_resume` en la DB guarda el nombre construido (posiblemente inexistente); la
   columna fiable es `uploaded_cv`. Conviene unificarlas.
8. Corregir a `USD` la moneda registrada en las filas 21 y 41.
9. Etiqueta basura persistente: el escáner toma el texto de la tarjeta del CV como si fuera un
   campo (`'PDFCV_15_M_D_P_EN_...pdf18/8'`). No hace daño (se salta) pero es ruido.
10. `PROFILES_MANAGEMENT.md` contiene una contraseña en texto plano y contradice lo verificado
    sobre las cuentas; `project_overview.md` sigue fechado 2026-04-13 y no menciona el port a
    Rust ni el Apply Bot.
