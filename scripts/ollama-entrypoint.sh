#!/bin/bash
# Ollama entrypoint script - starts server and pulls required models

# Start Ollama server in background
ollama serve &
OLLAMA_PID=$!

# Wait for Ollama to be ready (using ollama list instead of curl)
echo "[Ollama] Waiting for server to start..."
max_attempts=30
attempt=0
while [ $attempt -lt $max_attempts ]; do
    if ollama list > /dev/null 2>&1; then
        echo "[Ollama] Server is ready"
        break
    fi
    attempt=$((attempt + 1))
    echo "[Ollama] Waiting... (attempt $attempt/$max_attempts)"
    sleep 2
done

if [ $attempt -eq $max_attempts ]; then
    echo "[Ollama] ERROR: Server failed to start after $max_attempts attempts"
    exit 1
fi

# Pull required models from OLLAMA_MODELS env var
if [ -n "$OLLAMA_MODELS" ]; then
    for model in $OLLAMA_MODELS; do
        echo "[Ollama] Checking model: $model"
        # Check if model exists (handle model name with/without tag)
        if ollama list | grep -q "$model"; then
            echo "[Ollama] Model already exists: $model"
        else
            echo "[Ollama] Pulling model: $model (this may take a while...)"
            ollama pull "$model"
            if [ $? -eq 0 ]; then
                echo "[Ollama] Successfully pulled: $model"
            else
                echo "[Ollama] ERROR: Failed to pull $model"
            fi
        fi
    done
else
    echo "[Ollama] No OLLAMA_MODELS specified, skipping model pull"
fi

echo "[Ollama] All models ready"

# Keep the server running
wait $OLLAMA_PID
