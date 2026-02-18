#!/usr/bin/env bash
set -euo pipefail

MODEL_PATH="./models/qwen3-coder-next/Qwen3-Coder-Next-UD-Q4_K_XL.gguf"

if [ ! -f "$MODEL_PATH" ]; then
    echo "ERROR: Model not found at $MODEL_PATH"
    echo "Download with:"
    echo '  HF_HUB_ENABLE_HF_TRANSFER=1 huggingface-cli download \'
    echo '    unsloth/Qwen3-Coder-Next-GGUF \'
    echo '    --include "*UD-Q4_K_XL*" \'
    echo '    --local-dir ./models/qwen3-coder-next'
    exit 1
fi

./build/bin/llama-server \
    --model "$MODEL_PATH" \
    --host 0.0.0.0 \
    --port 8080 \
    \
    --n-gpu-layers 99 \
    -ot ".ffn_.*_exps.=CPU" \
    \
    -np 5 \
    --slot-save-path ./kv-cache \
    \
    --ctx-size 32768 \
    -b 4096 \
    -ub 4096 \
    \
    --cache-type-k q8_0 \
    --cache-type-v q8_0 \
    \
    --cache-reuse 256 \
    -sps 0.3 \
    \
    --jinja \
    \
    --temp 1.0 \
    --top-p 0.95 \
    --top-k 40 \
    --min-p 0.01
