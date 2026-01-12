from src.brain import JobAnalyzer

print("--- TEST CONEXIÓN GEMINI WEB ---")
try:
    # Initialize Brain (this triggers the cookie extraction code)
    brain = JobAnalyzer()
    
    if brain.client:
        print("\nSending 'Hola' to Gemini...")
        response = brain.client.chat("Hola, ¿estás funcionando? Responde brevemente.")
        print(f"\n✅ RESPUESTA DE GEMINI:\n{response}")
    else:
        print("\n❌ Error: No se pudo inicializar el cliente (No cookies found).")

except Exception as e:
    print(f"\n❌ Error Crítico: {e}")
