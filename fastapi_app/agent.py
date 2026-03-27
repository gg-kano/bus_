import httpx
import json
import re
import os
import asyncio
import logging
from typing import AsyncGenerator
from rag import get_faq_context

logger = logging.getLogger(__name__)

OLLAMA_URL = os.getenv("OLLAMA_URL", "http://ollama:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen3.5:9b")

# Timeout for chat responses
CHAT_TIMEOUT = httpx.Timeout(120.0, connect=10.0)

# Retry configuration
MAX_RETRIES = 3
INITIAL_BACKOFF = 1.0  # seconds

# ── Persistent HTTP Clients (connection pooling) ─────────────────────────────
CLASSIFY_TIMEOUT = httpx.Timeout(30.0, connect=10.0)

_chat_client: httpx.AsyncClient | None = None
_classify_client: httpx.AsyncClient | None = None
_health_client: httpx.AsyncClient | None = None


def get_chat_client() -> httpx.AsyncClient:
    global _chat_client
    if _chat_client is None or _chat_client.is_closed:
        _chat_client = httpx.AsyncClient(timeout=CHAT_TIMEOUT)
    return _chat_client


def get_classify_client() -> httpx.AsyncClient:
    global _classify_client
    if _classify_client is None or _classify_client.is_closed:
        _classify_client = httpx.AsyncClient(timeout=CLASSIFY_TIMEOUT)
    return _classify_client


def get_health_client() -> httpx.AsyncClient:
    global _health_client
    if _health_client is None or _health_client.is_closed:
        _health_client = httpx.AsyncClient(timeout=httpx.Timeout(5.0))
    return _health_client


async def close_clients():
    """Close all persistent HTTP clients. Call from FastAPI lifespan shutdown."""
    global _chat_client, _classify_client, _health_client
    for client in (_chat_client, _classify_client, _health_client):
        if client and not client.is_closed:
            await client.aclose()
    _chat_client = _classify_client = _health_client = None


async def call_ollama_with_retry(payload: dict, retries: int = MAX_RETRIES, backoff: float = INITIAL_BACKOFF) -> dict:
    """Call Ollama API with exponential backoff retry."""
    last_error = None
    client = get_chat_client()

    for attempt in range(retries):
        try:
            resp = await client.post(f"{OLLAMA_URL}/api/chat", json=payload)
            resp.raise_for_status()
            return resp.json()
        except (httpx.ConnectError, httpx.TimeoutException, httpx.HTTPStatusError) as e:
            last_error = e
            if attempt < retries - 1:
                wait_time = backoff * (2 ** attempt)  # Exponential backoff
                logger.warning(f"[Ollama] Attempt {attempt + 1} failed: {e}. Retrying in {wait_time:.1f}s...")
                await asyncio.sleep(wait_time)
            else:
                logger.error(f"[Ollama] All {retries} attempts failed: {e}")

    raise last_error

# ── Prompt Loading ─────────────────────────────────────────────────────────────

PROMPTS_DIR = os.path.join(os.path.dirname(__file__), "prompts")


def load_prompt(filename: str) -> str:
    """Load a prompt from the prompts directory."""
    filepath = os.path.join(PROMPTS_DIR, filename)
    with open(filepath, "r", encoding="utf-8") as f:
        return f.read()


CHAT_PROMPT = load_prompt("chat_prompt.txt")
CLASSIFY_PROMPT = load_prompt("classify_prompt.txt")

VALID_INTENTS = {"gibberish", "greeting", "faq", "schedule", "booking", "general"}


# ── Intent Classification ─────────────────────────────────────────────────────

async def classify_intent(user_message: str) -> str:
    """Classify user message intent with a fast LLM call. Falls back to 'general' on any error."""
    try:
        prompt = CLASSIFY_PROMPT.replace("{message}", user_message)
        payload = {
            "model": OLLAMA_MODEL,
            "messages": [
                {"role": "user", "content": prompt}
            ],
            "stream": False,
            "keep_alive": "5m",
            "options": {
                "temperature": 0,
                "num_predict": 32,
            },
            "think": False,
        }
        client = get_classify_client()
        resp = await client.post(f"{OLLAMA_URL}/api/chat", json=payload)
        resp.raise_for_status()
        raw = resp.json()["message"]["content"].strip().lower()

        # Extract first word as intent
        intent = raw.split()[0] if raw else "general"
        if intent not in VALID_INTENTS:
            logger.warning(f"[Agent] Unknown intent '{intent}', falling back to general")
            intent = "general"

        logger.info(f"[Agent] Classified intent: {intent}")
        return intent
    except Exception as e:
        logger.warning(f"[Agent] Intent classification failed: {e}, falling back to general")
        return "general"


# ── Ollama Health Check ────────────────────────────────────────────────────────

async def check_ollama() -> bool:
    """Returns True if Ollama is reachable and model is available."""
    try:
        client = get_health_client()
        resp = await client.get(f"{OLLAMA_URL}/api/tags")
        models = [m["name"] for m in resp.json().get("models", [])]
        logger.info(f"[Ollama] Available models: {models}")
        return any(OLLAMA_MODEL in m for m in models)
    except Exception as e:
        logger.error(f"[Ollama] Health check failed: {e}")
        return False


# ── Chat Response ──────────────────────────────────────────────────────────────

async def chat(user_message: str, context: str = "", db_info: dict = None) -> str:
    """Generate a chat response to the user's message."""

    # Retrieve relevant FAQ context (with error handling)
    try:
        faq_context = get_faq_context(user_message)
    except Exception as e:
        logger.warning(f"[Agent] FAQ retrieval failed: {e}")
        faq_context = ""

    # Build the user prompt with optional context
    prompt = user_message
    context_parts = []

    if faq_context:
        context_parts.append(faq_context)
    if context:
        context_parts.append(context)

    if context_parts:
        full_context = "\n\n".join(context_parts)
        prompt = f"Context:\n{full_context}\n\nUser: {user_message}"

    try:
        payload = {
            "model": OLLAMA_MODEL,
            "messages": [
                {"role": "system", "content": CHAT_PROMPT},
                {"role": "user", "content": prompt}
            ],
            "stream": False,
            "keep_alive": "5m",  # Keep model loaded in VRAM for 5 minutes
            "options": {
                "temperature": 0.7,
                "num_predict": 512,  # Increased to prevent truncation
            },
            "think": False,  # Disable qwen3 thinking mode
        }
        response = await call_ollama_with_retry(payload)
        raw = response["message"]["content"]
        logger.info(f"[Agent] Raw response ({len(raw)} chars)")

        # Strip any <think> blocks (for models like qwen3)
        cleaned = re.sub(r"<think>.*?</think>", "", raw, flags=re.DOTALL).strip()
        logger.debug(f"[Agent] Cleaned response ({len(cleaned)} chars)")

        # If response is empty after stripping think blocks, generate fallback from db_info
        if not cleaned:
            logger.warning("[Agent] Empty response after stripping think blocks")
            return generate_fallback_response(user_message, db_info)

        return cleaned

    except Exception as e:
        logger.error(f"[Agent] Chat error: {type(e).__name__}: {e}")
        return generate_fallback_response(user_message, db_info)


def generate_fallback_response(user_message: str, db_info: dict = None) -> str:
    """Simple fallback when LLM is unavailable. No rule-based logic - just a helpful message."""
    logger.warning("[Agent] Using fallback response - LLM unavailable")
    return "Sorry, I'm having trouble connecting right now. Please try again in a moment, or use /search to find buses and /book to make a booking."


# ── Streaming Chat ─────────────────────────────────────────────────────────────

async def chat_stream(user_message: str, context: str = "") -> AsyncGenerator[str, None]:
    """Stream chat response tokens."""

    # Retrieve relevant FAQ context (with error handling)
    try:
        faq_context = get_faq_context(user_message)
    except Exception as e:
        logger.warning(f"[Agent] FAQ retrieval failed in stream: {e}")
        faq_context = ""

    # Build the user prompt with optional context
    prompt = user_message
    context_parts = []

    if faq_context:
        context_parts.append(faq_context)
    if context:
        context_parts.append(context)

    if context_parts:
        full_context = "\n\n".join(context_parts)
        prompt = f"Context:\n{full_context}\n\nUser: {user_message}"

    try:
        client = get_chat_client()
        async with client.stream(
            "POST",
            f"{OLLAMA_URL}/api/chat",
            json={
                "model": OLLAMA_MODEL,
                "messages": [
                    {"role": "system", "content": CHAT_PROMPT},
                    {"role": "user", "content": prompt}
                ],
                "stream": True,
                "keep_alive": "5m",  # Keep model loaded in VRAM
                "options": {
                    "temperature": 0.7,
                    "num_predict": 512,  # Increased to prevent truncation
                },
                "think": False,  # Disable qwen3 thinking mode
            }
        ) as resp:
            resp.raise_for_status()
            async for line in resp.aiter_lines():
                if line:
                    try:
                        chunk = json.loads(line)
                        token = chunk.get("message", {}).get("content", "")
                        if token:
                            yield token
                        if chunk.get("done"):
                            break
                    except json.JSONDecodeError:
                        continue
    except Exception as e:
        logger.error(f"[Agent] Stream error: {e}")
        yield "Sorry, I'm having trouble responding right now."
