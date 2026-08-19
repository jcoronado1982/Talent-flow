
pub struct Normalizer;

/// Mirrors src/app/bots/search/processor.py::_KNOWN_TECH_SKILLS
const KNOWN_TECH_SKILLS: &[&str] = &[
    // Backend Languages
    "C#", ".NET Core", "ASP.NET", ".NET", "Java", "Spring Boot", "Spring",
    "Python", "Django", "Flask", "FastAPI", "Node.js", "Go", "Golang",
    "Rust", "C++", "PHP", "Laravel", "Ruby", "Rails", "Kotlin", "Scala",
    // Frontend
    "Angular", "React", "Vue", "Next.js", "Nuxt", "TypeScript", "JavaScript",
    "HTML", "CSS", "SASS", "SCSS", "Ionic", "jQuery", "Svelte",
    // Mobile
    "Flutter", "React Native", "Android", "iOS", "Swift",
    // Databases
    "SQL Server", "PostgreSQL", "MySQL", "MariaDB", "MongoDB", "Redis",
    "Cassandra", "DynamoDB", "Elasticsearch", "Oracle", "SQLite", "T-SQL",
    "Vector DB", "Pinecone", "Weaviate",
    // DevOps / Cloud
    "Docker", "Kubernetes", "AWS", "Azure", "GCP", "Terraform", "CI/CD",
    "Jenkins", "GitHub Actions", "GitLab CI", "Ansible", "Linux",
    // AI / Data
    "PyTorch", "TensorFlow", "LLM", "LLMs", "OpenAI", "Langchain", "RAG",
    "CUDA", "Vertex AI", "N8N", "Pandas", "NumPy", "Spark",
    // Integration / Messaging
    "RabbitMQ", "Kafka", "GraphQL", "REST", "gRPC", "Microservices", "Websockets",
    // Tools
    "Git", "Jira", "Scrum", "Agile", "Salesforce", "SAP", "Power BI",
];

impl Normalizer {
    /// MANDATORY FALLBACK: scans raw job description text for known technology keywords.
    /// Guarantees the 'skills' column is never left empty when the AI response has none.
    pub fn extract_skills_heuristic(text: &str) -> Vec<String> {
        let mut found = Vec::new();
        let text_lower = text.to_lowercase();

        for skill in KNOWN_TECH_SKILLS {
            let skill_lower = skill.to_lowercase();
            if text_lower.contains(&skill_lower) && !found.contains(&skill.to_string()) {
                found.push(skill.to_string());
            }
        }

        found
    }

    /// Mirrors src/app/bots/search/processor.py::detect_language_heuristic
    pub fn detect_language(text: &str) -> String {
        let text_lower = text.to_lowercase();

        const ES_KEYWORDS: &[&str] = &[
            "responsabilidades", "requisitos", "experiencia", "conocimientos",
            "ofrecemos", "vacante", "ubicación", "empresa", "educación",
        ];
        const EN_KEYWORDS: &[&str] = &[
            "responsibilities", "requirements", "experience", "knowledge",
            "offer", "vacancy", "location", "company", "education",
        ];

        let es_score: usize = ES_KEYWORDS.iter().filter(|k| text_lower.contains(*k)).count() * 2;
        let en_score: usize = EN_KEYWORDS.iter().filter(|k| text_lower.contains(*k)).count() * 2;

        if en_score > es_score {
            "en".to_string()
        } else {
            "es".to_string()
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn extracts_known_skills_case_insensitively() {
        let skills = Normalizer::extract_skills_heuristic("Buscamos experto en python, REACT y kubernetes.");
        assert!(skills.contains(&"Python".to_string()));
        assert!(skills.contains(&"React".to_string()));
        assert!(skills.contains(&"Kubernetes".to_string()));
    }

    #[test]
    fn extract_skills_returns_empty_when_nothing_found() {
        let skills = Normalizer::extract_skills_heuristic("Se busca cocinero con experiencia en parrilla.");
        assert!(skills.is_empty());
    }

    #[test]
    fn detects_spanish_by_keyword_density() {
        assert_eq!(Normalizer::detect_language("Requisitos: experiencia en ventas. Ubicación: Bogotá."), "es");
    }

    #[test]
    fn detects_english_by_keyword_density() {
        assert_eq!(Normalizer::detect_language("Requirements: 5 years experience. Location: remote."), "en");
    }
}
