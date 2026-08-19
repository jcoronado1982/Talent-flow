# 🕵️ Guía del Panel de Inspección - TalentFlow

Este documento detalla el funcionamiento interno del bot de aplicación y cómo interpretar los datos que fluyen a través del dashboard de inspección.

---

## 1. El Flujo de Trabajo del Bot
El bot sigue un ciclo repetitivo de **"Mapeo ➔ Decisión ➔ Acción"** en cada página de un formulario de empleo:

1.  **Navegación:** Abre la vacante en LinkedIn y detecta el modal "Easy Apply".
2.  **Preparación de CV:** Evalúa qué perfil (CV) es el más adecuado y lo prepara para la subida.
3.  **DOM Mapping (Escaneo):** Analiza el código HTML para entender los campos presentes.
4.  **AI Decision:** Envía el contexto a la IA y recibe las respuestas.
5.  **Acción (Llenado):** Ejecuta físicamente el tipeo y los clics en el navegador.
6.  **Auditoría (Pausa):** Si el modo interactivo está activo, espera tu aprobación.
7.  **Navegación/Envío:** Pasa a la siguiente página o presiona "Submit" para finalizar.

---

## 2. Definiciones de la Interfaz de Inspección

### 🔍 DOM MAPPING (Schema)
Es el **mapa conceptual** de la página web. 
- **Qué es:** Una traducción del código HTML complejo a una lista simple de campos (IDs, tipos de entrada y etiquetas legibles).
- **Para qué sirve:** Es lo que permite que la IA "vea" qué preguntas le está haciendo el formulario.

### 📤 TRAFFIC IN (AI Prompt Payload)
Es el **paquete de información** que se envía a la Inteligencia Artificial.
- **Contenido:** Incluye tu perfil profesional, las reglas del sistema ("responde solo en JSON") y el **DOM Mapping** de la página actual.
- **Utilidad:** Permite auditar qué datos tuyos se le están entregando a la IA en cada paso.

### 📥 TRAFFIC OUT (Raw AI Response)
Es la **respuesta en crudo** (sin procesar) que devuelve la IA.
- **Contenido:** Generalmente un bloque de texto en formato JSON que contiene los valores asignados a cada ID del formulario.
- **Utilidad:** Sirve para detectar "alucinaciones" de la IA o entender el razonamiento detrás de una respuesta específica.

---

## 3. Arquitectura de Datos (Alimentación del Dashboard)

El panel de inspección se mantiene actualizado mediante una arquitectura reactiva:

1.  **Fuente de Verdad (`status.json`):** El bot escribe su estado actual y diagnósticos en este archivo cada vez que ocurre un evento.
2.  **Transmisión (SSE - Server-Sent Events):** El servidor utiliza una conexión permanente unidireccional para empujar los cambios al navegador de forma instantánea (0.5s de latencia).
3.  **Persistencia (`database.db`):** Los resultados finales de cada aplicación (si fue exitosa, el puntaje obtenido, etc.) se guardan permanentemente en la base de datos SQLite.

---

## 4. Comandos de Control
- **INICIAR:** Lanza el proceso de inspección paso a paso.
- **SIGUIENTE PASO:** Autoriza al bot a avanzar después de haber llenado los campos.
- **BORRAR DATA:** Limpia los logs de diagnóstico y el estado actual de la sesión para iniciar una prueba desde cero, sin afectar el historial permanente en la base de datos.
