#!/bin/bash

# Script para iniciar el modelo via Ollama para TalentFlow
# Ollama se ejecuta como servicio del sistema - solo verificamos que esté activo

echo "-------------------------------------------------------"
echo "Verificando servidor Ollama para TalentFlow"
echo "Modelo: gemma4:27b"
echo "Puerto: 11434 (OpenAI-compatible)"
echo "-------------------------------------------------------"

# Verificar que Ollama esté corriendo
if ! curl -s http://localhost:11434/api/version > /dev/null; then
    echo "[ERROR] Ollama no está corriendo. Inícialo con:"
    echo "  sudo systemctl start ollama"
    exit 1
fi

echo "[OK] Ollama está activo."

# Verificar que el modelo gemma4:27b ya esté descargado
if curl -s http://localhost:11434/api/tags | python3 -c "import sys, json; models = [m['name'] for m in json.load(sys.stdin)['models']]; sys.exit(0 if 'gemma4:27b' in models else 1)" 2>/dev/null; then
    echo "[OK] Modelo gemma4:27b encontrado. Listo para usar."
    echo ""
    echo "Inicia TalentFlow con:"
    echo "  AI_PROVIDER=local python3 -m src.main"
else
    echo "[INFO] Modelo gemma4:27b no encontrado. Descargando..."
    echo "       (Esto puede tardar varios minutos - ~14GB)"
    curl -s -X POST http://localhost:11434/api/pull \
        -d '{"model": "gemma4:27b"}' \
        --no-buffer
fi
