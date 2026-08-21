# Análisis Técnico del DOM y Diagnóstico de Componentes Complejos en TalentFlow

Este documento detalla los hallazgos forenses del DOM en portales ATS (Recruiterflow, Dynamics ATS / Arkano, BairesDev, etc.), explicando por qué los motores tradicionales de automatización e IA no lograban identificar ni rellenar ciertos componentes y las soluciones implementadas en Rust.

---

## 1. Recruiterflow: Botones de Selección Personalizados (Tarjetas Yes / No)

### 🔴 El Problema
En el formulario de aplicación de Recruiterflow, las preguntas de selección única/múltiple (ej. *"Do you have experience working in startups?"*) no utilizan etiquetas HTML estándar como `<input type="radio">` ni contenedores `<fieldset>` / `<div role="group">`.

El marcado HTML real generado por React es el siguiente:

```html
<div class="yes-no-input-wrapper">
    <p class="form-label">Do you have experience working in startups? <span class="required">*</span></p>
    <div class="common-input-wrapper">
        <div class="yes-no-inputs">
            <button class="input-styles yes-input">Yes</button>
            <button class="input-styles no-input">No</button>
        </div>
    </div>
</div>
```

### 🧠 Por qué fallaba

1. **Motor Determinista (`dom.rs` / `SCAN_JS`):** 
   El escáner determinista solo buscaba etiquetas `<input>`, `<textarea>`, `<select>` y contenedores `<fieldset>`. Como Recruiterflow usa elementos `<button>`, las 5 preguntas de selección eran completamente invisibles para el escáner. El bot asumía que el formulario estaba "completo" y presionaba "Submit application", resultando en un error de validación de Recruiterflow.

2. **Agente de IA (`agent.rs` / `SNAPSHOT_JS`):**
   Al transferir el control al Agente IA, el `SNAPSHOT_JS` capturaba los botones como acciones individuales con la etiqueta genérica `"Yes"` o `"No"`. Como en la página existían 5 preguntas de Yes/No, el prompt recibía 5 botones idénticos llamados `"Yes"` y 5 llamados `"No"` sin contexto de la pregunta, impidiendo que el modelo determinara a qué pregunta pertenecía cada botón.

### ✅ La Solución Implementada
- **Detección Automática de Grupos de Botones (`dom.rs`):** Añadimos un escáner que identifica contenedores con 2 o más botones de opción (como Yes/No). Extrae el texto de la pregunta del párrafo `<p>` contenedor y lo registra en la estructura del formulario como un campo de tipo `radio` con sus opciones correspondientes `["Yes", "No"]`.
- **Hábiles clics en botones (`dom.rs::fill_choice_field`):** `fill_choice_field` hace clic directamente en el elemento `<button>` cuya etiqueta coincida con la respuesta de la IA.
- **Contextualización Semántica para el Agente (`agent.rs`):** En `SNAPSHOT_JS`, anteponemos el texto de la pregunta a los botones de opción (ej. `"Do you have experience working in startups? -> Yes"`). Ahora cualquier LLM (Gemini, Claude, GPT-5.6-Terra) reconoce unívocamente la acción.

#### ⚠️ Refinamiento posterior: falsos positivos del escáner de botones
La primera versión del escáner usaba un selector de contenedor muy genérico (`div[class*='group']`, `div[class*='container']` — nombres de clase casi universales en apps React) y aceptaba **cualquier** texto de botón menor a 25 caracteres, no solo Yes/No. En la práctica esto capturaba pares de botones no relacionados con preguntas del formulario (Accept/Reject de un banner de cookies, Cancel/Confirm de un modal, Previous/Next de paginación) como si fueran una pregunta `radio` real, arriesgando que la IA hiciera clic en un botón equivocado. Se corrigió exigiendo dos condiciones simultáneas: (1) el texto de cada botón debe pertenecer a una lista cerrada de respuestas típicas de formulario (yes/no/sí/no/true/false/agree/disagree/n-a), y (2) debe existir una pregunta real y visible (`<p>/<label>/legend/h3/h4/[class*="label"]`) cerca del grupo — si no hay pregunta, el grupo se descarta en vez de etiquetarse con el texto genérico `"Choice Question"`.

---

## 2. Dynamics ATS (Arkano): Dropdowns `<select>` en Frameworks React/Angular

### 🔴 El Problema
En el formulario de Arkano (`portal.dynamicsats.com`), los desplegables de **País**, **Estado** y **Ciudad** no son campos HTML tradicionales pasivos, sino componentes React controlados.

### 🧠 Por qué fallaba
El método original `fill_select_field` asignaba el valor directamente mediante la propiedad DOM `el.value = "Colombia"` y disparaba un evento `change`. 
Sin embargo, los componentes controlados de React interceptan las propiedades mediante setters sintéticos y rastrean los valores internos en un `_valueTracker`. La modificación directa actualizaba el texto visual pero no el estado interno de React (`""`). Al intentar enviar o avanzar, la plataforma lanzaba un error indicando que los campos eran requeridos.

### ✅ La Solución Implementada
- **Bypass de Setter Nativo (`dom.rs::fill_select_field`):** Se modificó la inyección para usar el setter nativo de la clase HTMLSelectElement (`Object.getOwnPropertyDescriptor(window.HTMLSelectElement.prototype, 'value').set`) y disparar eventos sintéticos `input` y `change` con `composed: true` y `bubbles: true`, forzando a React a actualizar su estado interno.
- **Eliminación de selección aleatoria:** Se eliminó la conducta legacy que seleccionaba la segunda opción de la lista si la búsqueda exacta fallaba, previniendo selecciones erróneas de países (ej. seleccionar Afganistán).

---

## 3. Falsos Positivos de Autocompletado por Listboxes Vecinos Ocultos

### 🔴 El Problema
En formularios con desplegables interactivos de ubicación, los campos de texto plano (Nombre, Apellido, Email, Teléfono) se rellenaban bien, pero la sonda de verificación `suggestion_popup_match` reportaba de forma persistente que una lista de sugerencias había quedado abierta.

### 🧠 Por qué fallaba
Arkano renderizaba el menú desplegable del País inmediatamente abajo utilizando un elemento `<input role="listbox">` que inicialmente contenía 0 opciones. La sonda de proximidad geométrica buscaba elementos cercanos con `role="listbox"`. Al encontrar este elemento cerca de los campos superiores, asumía erróneamente que la entrada de texto había abierto un menú de sugerencias no resuelto, interrumpiendo el flujo determinista y delegando innecesariamente al Agente IA.

### ✅ La Solución Implementada
- **Filtrado Riguroso en la Sonda (`dom.rs`):** Se actualizó la lógica en `suggestion_popup_match` para ignorar elementos que tengan la etiqueta `<input>` o que posean 0 elementos hijos (`el.children.length === 0`), garantizando que solo se consideren desplegables con opciones activas.

---

## 4. Preguntas de Botones sin Clases Reconocibles (detección invertida)

### 🔴 El Problema
La primera solución de la sección 1 buscaba los grupos de botones partiendo de un **selector de contenedor por nombre de clase**:

```js
root.querySelectorAll("div[class*='input-wrapper'], div[class*='yes-no'], div[class*='group'], div[class*='container']")
```

Esto tenía los dos defectos opuestos a la vez:

1. **Falsos negativos.** Una pregunta envuelta en `<div class="question-row">`, `<div class="field">` o cualquier clase fuera de esa lista era **invisible** para el escáner. El bot daba el formulario por completo y lo enviaba sin contestarla.
2. **Falsos positivos.** `class*='group'` y `class*='container'` son nombres de clase casi universales en apps React. Sumado a un filtro que aceptaba *cualquier* texto de botón de menos de 25 caracteres, cualquier par de botones cortos entraba como pregunta `radio` falsa: banners de cookies (Aceptar/Rechazar), modales (Cancelar/Confirmar), paginación (Anterior/Siguiente). Si la IA "respondía" esa pregunta inventada, `fill_choice_field` hacía clic real en ese botón.

### ✅ La Solución Implementada
Se invirtió el sentido de la búsqueda: **primero los botones, después el contenedor.**

1. **Se recolectan los botones de respuesta** (`button`, `[role='button']`, `[role='radio']`) cuyo texto pertenezca a una **lista cerrada**: `yes, no, si, sí, true, false, agree, disagree, n/a, na, acepto, de acuerdo, verdadero, falso`. Nunca "cualquier texto corto".
2. **Desde cada botón se sube** hasta el ancestro *más pequeño* que agrupe 2 o más botones de respuesta (máximo 5 niveles). Al tomar el más pequeño, dos preguntas consecutivas no se fusionan en un solo campo.
3. **El enunciado se obtiene clonando ese contenedor y quitándole todos los controles** (`button`, `[role=button]`, `[role=radio]`, `[role=checkbox]`, `input`, `select`, `textarea`). Lo que queda **es** la pregunta — funciona igual si está en `<p>`, `<label>`, `<legend>`, un `<span>` suelto o un nodo de texto pelado, sin depender de que alguien le haya puesto una clase reconocible.
4. **Sin enunciado no se registra el campo.** Es lo que evita inventar una pregunta falsa para un par de botones cualquiera: un banner de cookies no tiene un enunciado de pregunta arriba.

Resultado: *"¿Estás de acuerdo con ir a la oficina?" `[Sí] [No]`* se detecta sin importar cómo esté maquetado, y un modal Cancelar/Confirmar ya no entra al esquema.

---

## 5. Campos Obligatorios: el Esquema no los Distinguía

### 🔴 El Problema
`FormField` no tenía campo `required`. El escáner **nunca reportaba si un campo era obligatorio**, así que el motor trataba igual a uno obligatorio y a uno opcional: si no tenía respuesta resuelta, hacía `[SKIP]` en silencio y enviaba el formulario incompleto. El ATS lo rechazaba y el bot reintentaba el mismo paso sin saber por qué.

### 🧠 Por qué fallaba
Ningún ATS marca lo obligatorio de una sola forma, y el código no miraba ninguna:

* `required` como propiedad/atributo nativo.
* `aria-required="true"`.
* Un **asterisco en la etiqueta** — muy común en portales que solo validan del lado del servidor y no marcan nada en el HTML.

### ✅ La Solución Implementada
- **`isRequired(el, labelText)` en `SCAN_JS`** revisa las tres vías (más `querySelector('[required], [aria-required="true"]')` para contenedores de grupo) y el resultado viaja como `required: bool` en cada entrada del esquema.
- **El flag llega al prompt** (`answer_form`), con reglas explícitas: los obligatorios tienen prioridad y no pueden quedar vacíos; los opcionales sin respuesta se dejan vacíos en vez de inventar.
- **Un obligatorio sin respuesta ya no se salta en silencio** (`form.rs`): se reporta en `needs_human` para que el agente —que ve la página real— lo resuelva, en vez de enviar un formulario que se sabe que va a ser rechazado.

> ⚠️ Efecto colateral conocido: un texto tipo *"* campos obligatorios"* dentro de una etiqueta puede marcar un campo como obligatorio sin serlo. La consecuencia es solo que ese campo se prioriza, así que se aceptó a cambio de cubrir los portales que únicamente usan el asterisco.

---

## 6. Autocompletar: se Consultaba la Lista a los 0 ms

### 🔴 El Problema
`fill_text_like_field` escribía el valor y **en el mismo instante** preguntaba si había lista de sugerencias. Ningún typeahead que consulte la red alcanza a responder en ese tiempo: entre el evento `input` y la lista pintada pasan típicamente **300–1500 ms**.

El bot concluía *"es un campo de texto normal"*, dejaba el texto crudo sin ninguna opción seleccionada, y seguía adelante creyendo que había llenado bien. El portal lo rechazaba al enviar. Es exactamente el caso de un campo de **País que es autocompletado y no un `<select>`**.

### 🧠 Por qué fallaba (segunda causa, simultánea)
El script de llenado disparaba `blur` junto con `input` y `change`. Muchos autocompletar **cierran y descartan su lista al recibir blur** — el código cerraba el desplegable que un renglón después iba a buscar.

### ✅ La Solución Implementada
- **`wait_for_suggestion_popup`**: sondea cada 150 ms hasta `SUGGESTION_POPUP_WAIT` (900 ms) y devuelve **apenas** la lista aparece, así un typeahead rápido no paga la espera completa.
- **El `blur` se movió al final**, y solo se dispara una vez confirmado que el campo *no* es un typeahead (`blur_field`).

> ⚖️ Compromiso: un campo de texto plano ahora cuesta hasta 900 ms extra (la espera de un popup que nunca llega). En un formulario de 8 campos son ~7 s por paso. Es el precio de no enviar autocompletares vacíos; la constante `SUGGESTION_POPUP_WAIT` en `dom.rs` es el punto de ajuste.

---

## Resumen de la Arquitectura de Manejo de DOM

| Componente Portal | Marcado Real HTML | Detección Determinista (`dom.rs`) | Contexto para el Agente (`agent.rs`) |
| :--- | :--- | :--- | :--- |
| **Botones Sí/No (Recruiterflow y cualquier otro)** | `<div class="lo-que-sea"><p>Pregunta</p><button>Yes</button><button>No</button></div>` | Se buscan **los botones** por texto (lista cerrada) y se sube al ancestro común; el enunciado sale de clonar el contenedor y quitarle los controles | `"Pregunta -> Yes"` como `id` clickeable |
| **Arkano / React Select** | `<select>` o `div[role="combobox"]` controlados | Asignación con `prototype.value.set` + eventos `composed` | `select` o `type` + `Enter` en 2 turnos |
| **Typeahead / País autocompletado** | `<input>` + popups flotantes o `aria-controls` | Llenado con el setter nativo del prototipo + **espera activa** de la lista (900 ms) + sondeo de proximidad; `blur` solo al final | `type` + verificación del valor en el input |
| **Campos obligatorios** | `required`, `aria-required`, o solo un `*` en la etiqueta | `isRequired()` cubre las tres vías → `required: bool` en el esquema | Prioridad explícita en el prompt; si queda sin resolver, se releva al agente |
