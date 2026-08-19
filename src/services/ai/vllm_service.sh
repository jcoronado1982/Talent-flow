#!/bin/bash
# vLLM Server Launcher for TalentFlow
# Wraps vLLM to provide an OpenAI-compatible API for the bot.

# Configuration
MODEL="casperhansen/deepseek-r1-distill-qwen-14b-awq"
PORT=8005
GPU_UTIL=0.80
MAX_LEN=4096
export HF_HUB_OFFLINE=1

echo "🚀 [vLLM] Starting High-Throughput Inference Server (AWQ Quantized)..."
echo "   Model: $MODEL"
echo "   Port:  $PORT"
echo "   GPU Memory Utilization: $GPU_UTIL"

# Ensure vllm is installed
if ! python3 -c "import vllm" &> /dev/null; then
    echo "❌ vllm not found. Installing..."
    pip install vllm
fi

# Run Server
# --trust-remote-code is often needed for newer architectures like DeepSeek
python3 -m vllm.entrypoints.openai.api_server \
    --model $MODEL \
    --port $PORT \
    --host 0.0.0.0 \
    --gpu-memory-utilization $GPU_UTIL \
    --max-model-len $MAX_LEN \
    --trust-remote-code \
    --dtype auto 

