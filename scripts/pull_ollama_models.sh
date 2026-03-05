#!/usr/bin/env bash
# scripts/pull_ollama_models.sh — Pull recommended local models

set -euo pipefail

MODELS=(
  "llama3.2"          # general purpose, fast
  "codellama"         # code generation
  "deepseek-coder"    # advanced code tasks
  "nomic-embed-text"  # embeddings for memory
)

if ! command -v ollama &>/dev/null; then
  echo "❌ Ollama not found. Install from https://ollama.ai"
  exit 1
fi

echo "=== Pulling Ollama models ==="
for model in "${MODELS[@]}"; do
  echo "⬇️  $model..."
  ollama pull "$model" || echo "⚠️  Failed to pull $model (skipping)"
done

echo "✅ Models available:"
ollama list
