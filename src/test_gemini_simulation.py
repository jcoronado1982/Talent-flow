from src.brain import JobAnalyzer
import time

print("--- SIMULACIÓN DE ANÁLISIS DE EMPLEO ---")

# 1. Fake Job Description (lo que extraería el browser)
fake_job_html = """
About the job
Estamos buscando nuestro próximo Head de Fábrica de Software para liderar un equipo de 50+ desarrolladores.
Requisitos:
- 10+ años de experiencia en desarrollo de software.
- Experiencia liderando equipos grandes.
- Inglés avanzado (C1).
- Conocimientos en Java, Python y AWS.
- Ubicación: Bogotá (Híbrido).
"""

try:
    # 2. Initialize Brain (Cookies + Session)
    print("\n1. Inicializando Cerebro...")
    brain = JobAnalyzer()
    
    if brain.client:
        # 3. Analyze
        print("\n2. Enviando oferta simulada a Gemini...")
        print(f"   (Texto simulado: {len(fake_job_html)} caracteres)")
        
        result = brain.analyze(fake_job_html)
        
        print("\n" + "="*50)
        print("✅ RESULTADO OBTENIDO:")
        print("="*50)
        print(result)
        print("="*50)
        
    else:
        print("\n❌ Error: No se pudo inicializar el cliente.")

except Exception as e:
    print(f"\n❌ Error Crítico: {e}")
