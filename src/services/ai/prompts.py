import os
import json
import yaml
from src.config.settings import Settings


class PromptManager:
    """
    Builds and manages all prompts sent to the AI evaluator.
    The system prompt is 100% dynamic — no hardcoded values.
    All scoring weights and levels are derived from profile_config.json at runtime.
    """

    def __init__(self):
        self.refresh_config()

    # ──────────────────────────────────────────────
    # PRIVATE HELPERS
    # ──────────────────────────────────────────────

    def _load_file(self, path: str) -> str:
        if not os.path.exists(path):
            return ""
        with open(path, "r", encoding="utf-8") as f:
            return f.read()

    def _load_json(self, path: str) -> dict:
        if not os.path.exists(path):
            return {}
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}

    def _build_profile_yaml(self, job_location: str = None) -> str:
        """
        Builds a compact but COMPLETE YAML representation of the candidate profile.
        Includes all dynamic data the AI needs to score jobs without hardcoded values:
          - english_level, years_of_experience
          - stack_priority (for priority multiplier logic)
          - skills (with level and years per skill, per category)
          - skill_clarifications (boundary rules for the AI)
        """
        full_profile = self._load_json(Settings.PROFILE_CONFIG)
        if not full_profile:
            return "{}"

        # Build enriched skills dict: category -> {skill: {level, years}}
        enriched_skills = {}
        for category, skills in full_profile.get("skills", {}).items():
            enriched_skills[category] = {
                name: {"level": details.get("level", 0), "years": details.get("years", 0)}
                for name, details in skills.items()
            }

        personal_info = full_profile.get("personal_info", {}).copy()
        if job_location:
            # Rule: if offer is Bogota -> Bogota, all others -> Medellin
            loc_lower = str(job_location).lower()
            if "bogotá" in loc_lower or "bogota" in loc_lower:
                personal_info["location"] = "Bogotá"
            else:
                personal_info["location"] = "Medellín"

        optimized = {
            "english_level": full_profile.get("english_level"),
            "years_of_experience": full_profile.get("years_of_experience"),
            "personal_info": personal_info,
            "stack_priority": full_profile.get("stack_priority", []),
            "skill_clarifications": full_profile.get("skill_clarifications", []),
            "salary_expectations": full_profile.get("salary_expectations", {}),
            "skills": enriched_skills,
        }

        return yaml.dump(
            optimized,
            sort_keys=False,
            allow_unicode=True,
            default_flow_style=False,
        )

    def refresh_config(self):
        """Reloads the profile config from disk and refreshes the internal system prompt."""
        self.system_prompt = self._load_file(
            os.path.join(Settings.BASE_DIR, "prompts/analyze_job.txt")
        )
        self.profile_yaml = self._build_profile_yaml()

    # ──────────────────────────────────────────────
    # PUBLIC PROMPT BUILDERS
    # ──────────────────────────────────────────────

    def get_analysis_prompt(self, job_text: str) -> str:
        """
        Builds the main job evaluation prompt.
        Job text is truncated to 6000 chars to prevent context overflow.
        """
        truncated_job = (
            job_text[:6000] + "...(TRUNCATED)" if len(job_text) > 6000 else job_text
        )

        return f"""{self.system_prompt}

### CANDIDATE_PROFILE_YAML
{self.profile_yaml}

### JOB_DESCRIPTION_TEXT
{truncated_job}

### RESPONSE
Return ONLY valid JSON using EXACTLY these keys:
"match_percentage": (integer 0-100),
"verdict": "APPLY" | "DEFER" | "REJECT",
"cv_selection_code": "B_D_P_ES" | "B_L_P_ES" | etc (City_Role_Tech_Lang),
"language_detected": "English" | "Spanish",
"ai_model": (MANDATORY: String naming the EXACT model and version you are, e.g. "Gemini 2.5 Flash" or "Qwen 2.5 72B"),
"fatal_filter_triggered": (string or null),
"reasoning": (string)

JSON:"""

    def get_initial_prompt(self) -> str:
        """
        Warm-up prompt for stateful backends (e.g., Gemini browser session).
        Not used in stateless local/API backends.
        """
        return (
            f"SESSION_ID: JOB_SEARCH_AUTO_2026\n\n"
            f"ACT AS A RECRUITER AI. HERE ARE THE RULES:\n{self.system_prompt}\n\n"
            f"HERE IS THE CANDIDATE PROFILE:\n{self.profile_yaml}\n\n"
            "Confirm with a simple 'READY' if you understood the rules and the profile."
        )

    def get_form_prompt(self, form_schema: dict, resolved_salary=None, resolved_currency=None, job_location=None) -> str:
        """Fills a job application form acting as the candidate."""
        dynamic_profile = self._build_profile_yaml(job_location) if job_location else self.profile_yaml
        
        salary_instruction = ""
        if resolved_salary:
            salary_instruction = f"\n        5. MANDATORY SALARY: For any question about salary expectations, use EXACTLY '{resolved_salary}'. Do not use currency symbols or text if the field seems numeric."
            if resolved_currency:
                salary_instruction += f" The currency for this value is {resolved_currency}."

        location_context = f"\n        CURRENT JOB LOCATION: {job_location}" if job_location else ""

        return f"""
        ROLE: Technical Recruiter / IT Talent Acquisition
        OBJECTIVE: Evaluar las respuestas del perfil para hacer match con las preguntas del formulario de empleo.
        CONTEXT: Estás operando como el motor de evaluación inicial de un sistema automatizado de reclutamiento. Tu objetivo es procesar las respuestas del candidato y estructurarlas para facilitar la decisión del equipo de recursos humanos.

        CANDIDATE PROFILE (YAML):
        {dynamic_profile}
        {location_context}
        CANDIDATE SUGGESTED SALARY: {resolved_salary or 'Check profile'} {resolved_currency or ''}

        FORM SCHEMA (JSON to fill):
        {json.dumps(form_schema, indent=2)}

        TASKS & INSTRUCTIONS:
        1. [x] Lee el esquema del formulario (FORM SCHEMA) para ver qué preguntas hay por responder.
        2. Responde las preguntas asumiendo la personalidad del candidato usando estrictamente su PROFILE.
        3. Fíjate si los inputs son numéricos o de texto. No inventes respuestas si los datos ya están proporcionados explicita o implicitamente.
        4. JUICIO PROFESIONAL: Si una pregunta solicita información que NO está en el perfil (ejemplo: años de experiencia en una tecnología que no manejas como GraphQL o Node.js), responde de manera profesional y coherente. Para años de experiencia en tecnologías ausentes, responde con "0". NUNCA devuelvas "null".
        5. UBICACIÓN / CIUDAD: Cualquier campo que pregunte por "Location", "City", "Ciudad", "Location (city)" DEBE responderse con la 'location' del perfil del candidato. NUNCA respondas "N/A" para campos de ubicación.
        6. OBJETIVO PRINCIPAL: Tu objetivo es QUE LA APLICACIÓN SE ENVÍE. Responde CUALQUIER pregunta sin dejar campos obligatorios nulos ("N/A"). Si es necesario, asume o deduce la respuesta más razonable y profesional que permita continuar, el objetivo es aplicar a la solicitud cueste lo que cueste.
{salary_instruction}

        RULES AND RESTRICTIONS:
        - No asumas ni infieras habilidades que no estén explícitamente escritas en el texto del candidato.
        - LÓGICA DE NEGOCIO: Al evaluar el perfil, utiliza la información proporcionada y respeta estrictamente el idioma indicado por las preguntas (inglés o español); no intentes adivinar el idioma buscando palabras clave aleatorias en el texto.
        - SELECCIÓN MULTIPLE: Para "select", "radio" o "checkbox", DEBES extraer la respuesta EXACTA de la lista proporcionada en las "options" del esquema. No inventes opciones nuevas.

        FORMAT RULE:
        "Bajo ninguna circunstancia devuelvas texto fuera de la estructura solicitada."
        Debes retornar ÚNICAMENTE un objeto JSON cuyas llaves sean EXACTAMENTE los "label" del esquema del formulario.

        EXAMPLES (FEW-SHOT PROMPTING):
        Input Schema:
        [
          {{ "label": "Years of experience in Python", "type": "number", "options": null }},
          {{ "label": "Years of experience in GraphQL", "type": "number", "options": null }},
          {{ "label": "Do you need sponsorship?", "type": "radio", "options": ["Yes", "No"] }}
        ]
        Output:
        {{
          "Years of experience in Python": "5",
          "Years of experience in GraphQL": "0",
          "Do you need sponsorship": "No"
        }}
        """

    def get_question_prompt(
        self, question: str, options=None, input_type: str = None, resolved_salary=None, job_location=None
    ) -> str:
        """Answers a single form question acting as the candidate."""
        dynamic_profile = self._build_profile_yaml(job_location) if job_location else self.profile_yaml
        salary_context = f"\n        CANDIDATE SUGGESTED SALARY: {resolved_salary}" if resolved_salary else ""
        location_context = f"\n        CURRENT JOB LOCATION: {job_location}" if job_location else ""
        options_text = f"OPTIONS: {options}" if options else "OPTIONS: Open text"
        return f"""
        TASK: Answer this job application question acting as the candidate.
        QUESTION: "{question}"
        CONTEXT: Input Field Type = "{input_type or 'text'}"{salary_context}{location_context}
        {options_text}
        CANDIDATE PROFILE (YAML):
        {dynamic_profile}
        RULES:
        1. MANDATORY COMPLETION: Provide a definitive answer. Never say "I don't know".
        2. INTELLIGENT JUDGMENT: If the exact data point is missing, use overall profile context to provide a REASONABLE professional estimate.
        3. NUMERIC CONSTRAINT: If the input type is 'number' or the question is about years of experience, salary, counts, or any quantity:
           - Return ONLY the raw digits (e.g., "5" or "4000").
           - NO text like "years", "approx", "expecting".
           - NO brackets or explanations.
           - EXAMPLE CORRECT: "5"
           - EXAMPLE INCORRECT: "5 years (Docker)", "approx 7", "8.5 years".
        FORMAT: Respond strictly as JSON: {{ "answer": "YOUR_ANSWER", "confidence": "High/Medium/Low" }}
        """
