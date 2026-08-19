import json
import os
from typing import Dict, Any, List

class ResumeManagerAgent:
    """
    Talent Flow Automation Agent specialized in Python.
    Acts as a logical selector of CV files based on technical metadata.
    """
    
    def __init__(self, config_path: str = "config/cv_profile.json"):
        self.config_path = config_path
        self.rules = self._load_rules()
        self.agent_config = self.rules.get("agent_config", {})
        self.mapping_rules = self.rules.get("rules", {})

    def _load_rules(self) -> Dict[str, Any]:
        if not os.path.exists(self.config_path):
            return {}
        with open(self.config_path, 'r', encoding='utf-8') as f:
            return json.load(f)

    def get_resume_filename(self, data: Dict[str, str]) -> str:
        """
        Processes input data to determine the final CV filename.
        Input data: { ROLE, LOCATION, SKILLS, LANG }
        """
        role_txt = data.get("ROLE", "").lower()
        location_txt = data.get("LOCATION", "").lower()
        skills_txt = data.get("SKILLS", "").lower()
        lang_txt = data.get("LANG", "").lower()

        # 1. Identify City ({city})
        # Bogotá/D.C. -> B, Colombia (other) -> M, Outside -> EX
        colombian_cities = ["bogotá", "bogota", "distrito capital", "d.c.", "metropolitana", "santa fe"]
        if any(city in location_txt for city in colombian_cities):
            city_code = "B"
        else:
            city_code = "M" # Fallback to Medellin for everywhere else (national or international)

        # 2. Identify Profile ({role})
        # leader_keywords in ROLE or SKILLS -> L, else D
        leader_keywords = self.mapping_rules.get("role_mapping", {}).get("leader_keywords", [])
        is_leader = False
        for kw in leader_keywords:
            if kw.lower() in role_txt or kw.lower() in skills_txt:
                is_leader = True
                break
        role_code = "L" if is_leader else "D"

        # 3. Identify Technology ({tech})
        # Analyze predominant group J, C, or P
        tech_mapping = self.mapping_rules.get("tech_mapping", {})
        tech_counts = {group: 0 for group in tech_mapping.keys()}
        
        for group, keywords in tech_mapping.items():
            for kw in keywords:
                if kw.lower() in skills_txt:
                    # Count occurrences to find "predominant"
                    tech_counts[group] += skills_txt.count(kw.lower())

        # Select group with highest count. Fallback to 'P' if tie or none.
        if all(v == 0 for v in tech_counts.values()):
            tech_code = "P" # Default
        else:
            tech_code = max(tech_counts, key=tech_counts.get)

        # 4. Identify Language ({lang})
        # English -> EN, Spanish -> ES
        if "english" in lang_txt:
            lang_code = "EN"
        else:
            lang_code = "ES"

        # Construct final filename based on template
        # {prefix}_{exp}_{city}_{role}_{tech}_{lang}_{owner}{ext}
        # Everything uses 15 years in Colombia/International under 'M' logic.
        exp = "15"
        fmt = self.agent_config.get("naming_format", "{prefix}_{exp}_{city}_{role}_{tech}_{lang}_{owner}{ext}")
        filename = fmt.format(
            prefix=self.agent_config.get("prefix", "CV"),
            exp=exp,
            city=city_code,
            role=role_code,
            tech=tech_code,
            lang=lang_code,
            owner=self.agent_config.get("owner", "Jesus_Coronado"),
            ext=self.agent_config.get("file_extension", ".pdf")
        )

        return filename

    def get_filename_from_code(self, code: str) -> str:
        """
        Constructs the filename from a raw code like 'B_L_P_EN'
        """
        try:
            parts = code.split('_')
            if len(parts) != 4:
                return self.get_resume_filename({}) # Fallback
            
            city, role, tech, lang = parts
            
            # All city folders (B, M) currently standardizing on 15 years
            exp = "15"
            
            fmt = self.agent_config.get("naming_format", "{prefix}_{exp}_{city}_{role}_{tech}_{lang}_{owner}{ext}")
            return fmt.format(
                prefix=self.agent_config.get("prefix", "CV"),
                exp=exp,
                city=city,
                role=role,
                tech=tech,
                lang=lang,
                owner=self.agent_config.get("owner", "Jesus_Coronado"),
                ext=self.agent_config.get("file_extension", ".pdf")
            )
        except:
            return "CV_15_M_D_P_ES_Jesus_Coronado.pdf" # Safe fallback

if __name__ == "__main__":
    # Quick test if run directly
    agent = ResumeManagerAgent()
    input_data = {
        "ROLE": "Líder técnico",
        "LOCATION": "Distrito Capital, Colombia",
        "SKILLS": "Azure, Spring Boot, API-REST, .NET, Java, Angular",
        "LANG": "Spanish"
    }
    print(agent.get_resume_filename(input_data))
