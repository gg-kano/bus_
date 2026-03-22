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


async def call_ollama_with_retry(payload: dict, retries: int = MAX_RETRIES, backoff: float = INITIAL_BACKOFF) -> dict:
    """Call Ollama API with exponential backoff retry."""
    last_error = None

    for attempt in range(retries):
        try:
            async with httpx.AsyncClient(timeout=CHAT_TIMEOUT) as client:
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


# ── Ollama Health Check ────────────────────────────────────────────────────────

async def check_ollama() -> bool:
    """Returns True if Ollama is reachable and model is available."""
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(5.0)) as client:
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
                "think": False,  # Disable qwen3 thinking mode
            }
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
    """Generate a helpful response when LLM fails, using DB info or FAQ if available."""
    msg_lower = user_message.lower()

    # Try FAQ first (with error handling to avoid cascading failures)
    try:
        faq_context = get_faq_context(user_message)
    except Exception as e:
        logger.warning(f"[Agent] FAQ fallback retrieval failed: {e}")
        faq_context = ""

    if faq_context:
        # Extract just the first answer from FAQ
        lines = faq_context.split('\n')
        for line in lines:
            if line.startswith('A1:'):
                return line[3:].strip()

    # Hardcoded FAQ answers as last resort when RAG system is unavailable
    if any(w in msg_lower for w in ["refund", "cancel", "cancellation", "batal", "pembatalan"]):
        return "You can cancel your booking by clicking the 'Cancel Booking' button in the sidebar and entering your booking ID. Cancellations made before departure are free. Your seat will be released and payment refunded within 3-5 business days."

    if any(w in msg_lower for w in ["payment", "pay", "bayar", "method"]):
        return "We accept online bank transfer. After booking, you'll receive payment instructions with a unique reference code. Upload your receipt for verification."

    if any(w in msg_lower for w in ["change seat", "tukar seat", "different seat"]):
        return "To change your seat, please cancel your current booking and make a new booking with your preferred seat selection."

    if any(w in msg_lower for w in ["missed", "terlepas", "late"]):
        return "If you missed your bus, please contact our customer service immediately. Depending on availability, we may be able to reschedule you to the next bus."

    if any(w in msg_lower for w in ["bring", "bawa", "luggage", "bagasi"]):
        return "Each passenger can bring one piece of luggage (max 20kg) and one small carry-on. Please arrive 15-30 minutes before departure."

    if db_info:
        # If asking about price/schedules and we have schedule data
        if db_info.get("schedules") and any(w in msg_lower for w in ["price", "cost", "how much", "harga"]):
            s = db_info["schedules"][0]
            return f"The bus from {s['route']} costs {s['price']}. Departure at {s['departure']} with {s['available_seats']} seats available. Use /search to see all options!"

        if db_info.get("schedules") and any(w in msg_lower for w in ["seat", "available", "bus"]):
            total_seats = sum(s["available_seats"] for s in db_info["schedules"])
            return f"We have {len(db_info['schedules'])} upcoming bus(es) with {total_seats} total seats available. Use /search to see the full schedule!"

        if db_info.get("summary"):
            summary = db_info["summary"]
            # Only show DB summary if user seems to be asking about buses/schedules
            if any(w in msg_lower for w in ["bus", "schedule", "route", "seat", "available", "jadual", "bas"]):
                return f"We have {summary['total_routes']} routes and {summary['total_schedules']} upcoming schedules with {summary['total_available_seats']} seats available. Use /search to find your bus!"

    return "I can help you find buses! Use /search in the sidebar to see available routes and schedules. You can also ask me about booking, cancellations, refunds, or payment methods."


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
        async with httpx.AsyncClient(timeout=CHAT_TIMEOUT) as client:
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
                        "think": False,  # Disable qwen3 thinking mode
                    }
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
