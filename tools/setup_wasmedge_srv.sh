#!/bin/bash
set -e
GGUF="/home/user/.lmstudio/.internal/bundled-models/nomic-ai/nomic-embed-text-v1.5-GGUF/nomic-embed-text-v1.5.Q4_K_M.gguf"
DIR="/home/user/wasmedge-srv"
WASM_URL="https://github.com/LlamaEdge/LlamaEdge/releases/latest/download/llama-api-server.wasm"

mkdir -p "$DIR"
cd "$DIR"

if [ ! -f "llama-api-server.wasm" ]; then
    echo "Downloading llama-api-server.wasm..."
    curl -L "$WASM_URL" -o llama-api-server.wasm
fi

ls -lh
echo "GGUF: $GGUF"
ls -lh "$GGUF" 2>/dev/null || echo "GGUF NOT FOUND"

source /home/user/.wasmedge/env
echo "wasmedge: $(wasmedge --version)"
