#!/bin/bash
# Setup script to pull required Ollama models

OLLAMA_URL="${OLLAMA_URL:-http://localhost:11434}"
EMBEDDING_MODEL="${EMBEDDING_MODEL:-nomic-embed-text}"
CHAT_MODEL="${OLLAMA_MODEL:-llama3.2}"

echo "=== Ollama Model Setup ==="
echo "Ollama URL: $OLLAMA_URL"
echo ""

# Function to pull a model
pull_model() {
    local model=$1
    echo "Pulling model: $model..."
    curl -s -X POST "$OLLAMA_URL/api/pull" -d "{\"name\": \"$model\"}" | while read -r line; do
        status=$(echo "$line" | grep -o '"status":"[^"]*"' | cut -d'"' -f4)
        if [ -n "$status" ]; then
            echo "  $status"
        fi
    done
    echo "Done: $model"
    echo ""
}

# Check if Ollama is running
echo "Checking Ollama connection..."
if curl -s "$OLLAMA_URL/api/tags" > /dev/null 2>&1; then
    echo "Ollama is running."
    echo ""
else
    echo "ERROR: Cannot connect to Ollama at $OLLAMA_URL"
    echo "Make sure Ollama is running: docker-compose up -d ollama"
    exit 1
fi

# Pull embedding model
pull_model "$EMBEDDING_MODEL"

# Pull chat model
pull_model "$CHAT_MODEL"

echo "=== Setup Complete ==="
echo "Models ready:"
curl -s "$OLLAMA_URL/api/tags" | grep -o '"name":"[^"]*"' | cut -d'"' -f4 | while read -r model; do
    echo "  - $model"
done
