#!/bin/bash
# Ollama entrypoint script - starts server and pulls required models

# Start Ollama server in background
ollama serve &
OLLAMA_PID=$!

# Wait for Ollama to be ready
echo "[Ollama] Waiting for server to start..."
until curl -s http://localhost:11434/api/tags > /dev/null 2>&1; do
    sleep 2
done
echo "[Ollama] Server is ready"

# Pull required models from OLLAMA_MODELS env var
if [ -n "$OLLAMA_MODELS" ]; then
    for model in $OLLAMA_MODELS; do
        echo "[Ollama] Checking model: $model"
        if ! ollama list | grep -q "^$model"; then
            echo "[Ollama] Pulling model: $model"
            ollama pull "$model"
        else
            echo "[Ollama] Model already exists: $model"
        fi
    done
fi

echo "[Ollama] All models ready"

# Keep the server running
wait $OLLAMA_PID
