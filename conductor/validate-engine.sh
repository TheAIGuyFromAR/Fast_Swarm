#!/usr/bin/env bash
set -euo pipefail

BASE_URL="${1:-http://localhost:8080}"

echo "=== Validating Inference Engine at $BASE_URL ==="
echo ""

echo "--- /v1/models ---"
curl -sf "$BASE_URL/v1/models" | python3 -m json.tool
echo ""

echo "--- /health ---"
HEALTH=$(curl -sf "$BASE_URL/health")
echo "$HEALTH" | python3 -m json.tool
echo ""

echo "--- Chat Completions (hello world test) ---"
RESULT=$(curl -sf "$BASE_URL/v1/chat/completions" \
    -H "Content-Type: application/json" \
    -d '{
        "model": "qwen3-coder-next",
        "messages": [{"role": "user", "content": "Write a Python hello world"}],
        "max_tokens": 100
    }')
echo "$RESULT" | python3 -m json.tool

# Extract and display baseline metrics
PROMPT_TOKENS=$(echo "$RESULT" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('usage',{}).get('prompt_tokens','N/A'))" 2>/dev/null || echo "N/A")
COMPLETION_TOKENS=$(echo "$RESULT" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('usage',{}).get('completion_tokens','N/A'))" 2>/dev/null || echo "N/A")

echo ""
echo "=== Baseline Metrics ==="
echo "Prompt tokens:     $PROMPT_TOKENS"
echo "Completion tokens: $COMPLETION_TOKENS"
echo ""
echo "Record manually from llama-server logs:"
echo "  - prompt processing tok/s"
echo "  - generation tok/s"
echo "  - first-token latency"
echo ""
echo "=== Validation Complete ==="
