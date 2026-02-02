import os
from src.config.settings import Settings

class PromptManager:
    def __init__(self):
        self.system_prompt = self._load_file(os.path.join(Settings.BASE_DIR, "prompts/analyze_job.txt"))
        
        # Ultra-Light Profile for Low-Context Models (4K limit)
        import json
        full_profile = self._load_json(Settings.PROFILE_CONFIG)
        if full_profile:
            # Flatten skills to comma-separated strings
            flat_skills = {}
            if "skills" in full_profile:
                for category, skills in full_profile["skills"].items():
                    flat_skills[category] = list(skills.keys())
            
            optimized = {
                "name": full_profile.get("personal_info", {}).get("full_name"),
                "email": full_profile.get("personal_info", {}).get("email"),
                "phone": full_profile.get("personal_info", {}).get("phone"),
                "location": full_profile.get("personal_info", {}).get("location"),
                "portfolio": full_profile.get("personal_info", {}).get("portfolio_url"),
                "github": full_profile.get("personal_info", {}).get("github_url"),
                "english": full_profile.get("english_level"),
                "exp_years": full_profile.get("years_of_experience"),
                "roles": full_profile.get("target_roles"),
                "skills": flat_skills,
                "salary_expectations": full_profile.get("salary_expectations"),
                "clarifications": full_profile.get("skill_clarifications", [])
            }
            self.profile = json.dumps(optimized, separators=(',', ':')) # Minified JSON
        else:
            self.profile = "{}"

    def _load_json(self, path):
         import json
         if not os.path.exists(path): return {}
         try:
             with open(path, 'r', encoding='utf-8') as f: return json.load(f)
         except: return {}

    def _load_file(self, path):
        if not os.path.exists(path): return ""
        with open(path, 'r', encoding='utf-8') as f:
            return f.read()

    def get_initial_prompt(self):
        return (
            f"IDENTIFICADOR DE SESION: JOB_SEARCH_AUTO_2026\n\n"
            f"ACT AS A RECRUITER AI. HERE ARE THE RULES:\n{self.system_prompt}\n\n"
            f"HERE IS THE CANDIDATE PROFILE:\n{self.profile}\n\n"
            "Confirma con un simple 'LISTO' si entendiste las instrucciones y el perfil."
        )

    def get_analysis_prompt(self, job_text):
        # Truncate Job Text to prevent Context Overflow (6000 chars is a good balance)
        truncated_job = job_text[:6000] + "...(TRUNCATED)" if len(job_text) > 6000 else job_text

        # Forzamos al modelo a que su respuesta empiece con la llave del JSON
        format_enforcer = "### RESPONSE\nReturn ONLY JSON starting with '{' and ending with '}':"

        return f"""
{self.system_prompt}

### INPUT DATA
CANDIDATE_PROFILE_JSON:
{self.profile}

JOB_DESCRIPTION_TEXT:
{truncated_job}

{format_enforcer}
IMPORTANT: If the tech stack is NOT clearly mentioned in JOB_DESCRIPTION_TEXT, you MUST look for clues or assume MISMATCH if it's a high-seniority role. DO NOT guess the stack based on the candidate profile.
"""

    def get_form_prompt(self, form_schema):
        import json
        return f"""
        TASK: Complete this job application FORM as the candidate.
        CANDIDATE PROFILE: {self.profile}
        FORM SCHEMA (JSON): {json.dumps(form_schema, indent=2)}
        RULES: 
        1. Be the candidate. Optimize for success. 
        2. If a field has an "error" key, PROVIDE A CORRECTED VALUE. 
        3. MANDATORY COMPLETION: Do not leave fields empty. 
        4. INTELLIGENT JUDGMENT: If a specific data point (like years of a specific skill) is not explicitly in the profile, use the overall experience (20 years) and the skills list to provide a REASONABLE professional estimate. Never say "I don't know".
        5. MULTI-SELECT: For checkboxes or "select all that apply" fields, return a LIST of strings or a comma-separated string of all matching options from the candidate's profile.
        FORMAT: Respond with a JSON object where keys are the EXACT "label" from the schema.
        """

    def get_question_prompt(self, question, options=None, input_type=None):
        options_text = f"OPTIONS: {options}" if options else "OPTIONS: Open text"
        return f"""
        TASK: Answer this job application question acting as the candidate.
        QUESTION: "{question}"
        CONTEXT: Input Field Type = "{input_type or 'text'}"
        {options_text}
        CANDIDATE PROFILE: {self.profile}
        RULES:
        1. MANDATORY COMPLETION: Provide a definitive answer. Never say "I don't know".
        2. INTELLIGENT JUDGMENT: If the exact data point is missing, use the overall profile context (20 years experience) to provide a REASONABLE professional estimate. 
        FORMAT: Respond formatted strictly as JSON: {{ "answer": "YOUR_ANSWER", "confidence": "High/Medium/Low" }}
        """
