#!/bin/bash
GGUF="/home/user/.lmstudio/.internal/bundled-models/nomic-ai/nomic-embed-text-v1.5-GGUF/nomic-embed-text-v1.5.Q4_K_M.gguf"
WASM="/home/user/wasmedge-srv/llama-api-server.wasm"
PORT=55555
LOG="/tmp/wasmedge_cervelet.log"

source /home/user/.wasmedge/env

# kill existing
pkill -f "llama-api-server.wasm" 2>/dev/null && sleep 1

cd /home/user/wasmedge-srv

nohup wasmedge --dir .:. \
  --nn-preload default:GGML:AUTO:"$GGUF" \
  "$WASM" \
  --prompt-template embedding \
  --ctx-size 512 \
  --port $PORT > "$LOG" 2>&1 &

PID=$!
echo "Started PID=$PID on :$PORT"
sleep 3
if kill -0 $PID 2>/dev/null; then
    echo "Running OK"
    curl -s http://127.0.0.1:$PORT/v1/models | head -c 200
else
    echo "FAILED - log:"
    tail -20 "$LOG"
fi
