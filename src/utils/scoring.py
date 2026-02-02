
def calculate_match_g_score(role: str, requirements: str) -> int:
    """
    Heuristic-based scoring (Match G) based on user's core profile and preferences.
    """
    role = role.lower()
    reqs = requirements.lower()
    
    score = 0
    
    # 1. Base Score por Rol Principal
    if any(x in role for x in ['lead', 'architect', 'principal', 'staff', 'manager', 'head']):
        score = 80 # Base alta para roles Lead
    elif 'senior' in role:
        score = 75 # Base para Senior
    elif 'mid' in role or 'junior' in role or 'associate' in role:
        score = 50 # Menor prioridad
    else:
        score = 60 # Genérico
        
    # 2. Stack Tecnológico (Bonus)
    # Target profile: .NET/C#, Python, AI, React/Angular, Azure/GCP, SQL
    stack_hits = 0
    if '.net' in reqs or 'c#' in reqs or 'dotnet' in reqs: stack_hits += 1
    if 'python' in reqs or 'django' in reqs or 'fastapi' in reqs: stack_hits += 1
    if 'azure' in reqs or 'gcp' in reqs: stack_hits += 1
    if 'react' in reqs or 'angular' in reqs or 'typescript' in reqs: stack_hits += 1
    if 'sql' in reqs or 'database' in reqs: stack_hits += 1
    if 'ai' in reqs or 'learning' in reqs or 'llm' in reqs: stack_hits += 1 # AI Bonus
    
    score += (stack_hits * 5) # +5 por cada hit de stack
    
    # 2.5 Especialidad IA (Premium match)
    if 'ai' in role or 'llm' in role or 'machine learning' in role:
        score += 10
    
    # 3. Penalizaciones y Ajustes de Nivel (Basado en 20 años de experiencia)
    if any(x in role for x in ['intern', 'pasantía', 'trainee', 'junior', 'jr', 'associate']):
        score -= 50 # Gran penalización por ser nivel inicial
    
    if 'sales' in role or 'marketing' in role or 'recruit' in role: 
        score = 10
    
    if 'java' in reqs and 'spring' in reqs and not 'python' in reqs and not '.net' in reqs: 
        score -= 10 # Java no es tu #1, aunque lo sabes, prefieres .NET/Python
    
    if 'php' in reqs or 'ruby' in reqs: 
        score -= 20 # Stack secundario/no deseado
    
    # RECHAZO: Data Engineering / BI Puro (No es tu perfil)
    if any(x in role for x in ['data engineer', 'bi developer', 'power bi', 'tableau', 'looker', 'business intelligence']):
        if not 'software engineer' in role: # A menos que sea un rol híbrido explícito
            return 0

    # 4. Detector de Salario (Banking security check)
    import re
    # Buscar patrones de salario evitando "allowance", "stipend", "bonus" si es posible
    # O simplemente buscar números grandes asociados a USD que parezcan salario mensual/anual
    found_salary = None
    
    # Intentar encontrar bloques de salario explícitos primero
    salary_block_match = re.search(r'(?:salary|compensation|remuneration|pay):\s*?[\$\s]*?(\d{1,3}(?:[.,]\d{3})*)', reqs)
    if salary_block_match:
        try:
            found_salary = int(salary_block_match.group(1).replace(',', '').replace('.', ''))
        except: pass

    if not found_salary:
        # Fallback a buscar USD con números que parezcan salario mensual (>1000) o anual (>20000)
        potential_salaries = re.findall(r'[\$\s](\d{1,3}(?:[.,]\d{3})*)\s?(?:usd|\$|monthly|month)', reqs)
        for val_str in potential_salaries:
            try:
                val = int(val_str.replace(',', '').replace('.', ''))
                # Si el texto cercano tiene "allowance" o "stipend", ignorar
                # Buscamos en un radio de 30 caracteres
                pos = reqs.find(val_str)
                context = reqs[max(0, pos-40):min(len(reqs), pos+40)]
                if any(x in context for x in ['allowance', 'stipend', 'setup', 'reimbursement', 'bonus']):
                    continue
                
                if val > 500: # Tomar el primero que sea > 500 y no sea un allowance
                    found_salary = val
                    break
            except: continue
            
    if found_salary:
        # Si el salario está en USD y es menor a 2500 (tu base es 3000)
        if found_salary < 2500 and found_salary > 400: # 400 por si es quincenal o algo raro
            score -= 60
            # print(f"   [Scoring] Salary Mismatch detected: {found_salary} USD. Critical Penalty.")

    # 5. Idioma (Flexibilidad sugerida: B2 vs C1)
    # RECHAZO TOTAL si está en el TÍTULO (indica que es filtro primario)
    if any(x in role for x in ['c1', 'advanced english', 'fluent english', 'bilingual']):
        return 0

    # Penalización moderada si está en los requerimientos
    if any(x in reqs for x in ['advanced english', 'c1 english', 'fluent english', 'bilingual']):
        score -= 20 

    # Cap Final por Nivel
    if any(x in role for x in ['intern', 'trainee']):
        score = min(5, score) # Casi 0% para Internships si eres Senior
    
    # Cap 0-100
    score = min(100, max(0, score))
    
    return score
