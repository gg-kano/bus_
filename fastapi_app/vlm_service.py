"""
VLM (Vision Language Model) Service for Receipt Data Extraction

Extracts information from receipt images using qwen3.5:9b.
Verification logic is handled separately by receipt_verifier.py.
"""

import httpx
import base64
import os
import re
import json
import logging
from typing import Optional
from dataclasses import dataclass

logger = logging.getLogger(__name__)

# VLM uses the same Ollama instance and model as LLM
OLLAMA_URL = os.getenv("OLLAMA_URL", "http://ollama:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen3.5:9b")

# Timeout for VLM requests
VLM_TIMEOUT = httpx.Timeout(120.0, connect=10.0)

# ── Persistent HTTP Clients ──────────────────────────────────────────────────
_vlm_client: httpx.AsyncClient | None = None
_vlm_health_client: httpx.AsyncClient | None = None


def get_vlm_client() -> httpx.AsyncClient:
    global _vlm_client
    if _vlm_client is None or _vlm_client.is_closed:
        _vlm_client = httpx.AsyncClient(timeout=VLM_TIMEOUT)
    return _vlm_client


def get_vlm_health_client() -> httpx.AsyncClient:
    global _vlm_health_client
    if _vlm_health_client is None or _vlm_health_client.is_closed:
        _vlm_health_client = httpx.AsyncClient(timeout=httpx.Timeout(5.0))
    return _vlm_health_client


async def close_vlm_clients():
    """Close all persistent VLM HTTP clients."""
    global _vlm_client, _vlm_health_client
    for client in (_vlm_client, _vlm_health_client):
        if client and not client.is_closed:
            await client.aclose()
    _vlm_client = _vlm_health_client = None


# ── Prompt Loading ─────────────────────────────────────────────────────────────

PROMPTS_DIR = os.path.join(os.path.dirname(__file__), "prompts")


def load_prompt(filename: str) -> str:
    """Load a prompt from the prompts directory."""
    filepath = os.path.join(PROMPTS_DIR, filename)
    with open(filepath, "r", encoding="utf-8") as f:
        return f.read()


RECEIPT_PROMPT = load_prompt("receipt_prompt.txt")


@dataclass
class ExtractionResult:
    """Result of receipt data extraction."""
    success: bool
    amount_found: Optional[float]
    recipient_account: Optional[str]
    reference_found: Optional[str]
    transaction_time: Optional[str]
    raw_response: str
    error: Optional[str]


# ── VLM Health Check ───────────────────────────────────────────────────────────

async def check_vlm() -> bool:
    """Check if VLM service is available."""
    try:
        client = get_vlm_health_client()
        resp = await client.get(f"{OLLAMA_URL}/api/tags")
        models = [m["name"] for m in resp.json().get("models", [])]
        logger.info(f"[VLM] Available models: {models}")
        return any(OLLAMA_MODEL in m for m in models)
    except Exception as e:
        logger.error(f"[VLM] Health check failed: {e}")
        return False


# ── Receipt Data Extraction ────────────────────────────────────────────────────

async def extract_receipt_data(image_path: str) -> ExtractionResult:
    """
    Extract data from receipt image using VLM.

    Returns extracted fields:
    - amount_found: Transfer amount
    - recipient: Recipient name
    - reference_found: Reference number
    - transaction_time: Transaction date/time
    """
    try:
        # Read and encode image
        with open(image_path, "rb") as f:
            image_bytes = f.read()
            image_data = base64.b64encode(image_bytes).decode("utf-8")

        logger.info(f"[VLM] Image size: {len(image_bytes) / 1024:.1f} KB, base64 length: {len(image_data)}")

        # Call VLM
        client = get_vlm_client()
        resp = await client.post(
            f"{OLLAMA_URL}/api/chat",
            json={
                "model": OLLAMA_MODEL,
                "messages": [
                    {
                        "role": "user",
                        "content": RECEIPT_PROMPT,
                        "images": [image_data]
                    }
                ],
                "stream": False,
                "keep_alive": "5m",  # Keep model loaded in VRAM
                "options": {
                    "temperature": 0.1,
                    "num_predict": 512,  # Short response for JSON only
                },
                "think": False  # Disable thinking mode for Qwen3
            }
        )
        resp.raise_for_status()
        response_json = resp.json()
        message = response_json.get("message", {})
        raw_response = message.get("content", "")

        # Fallback: if content is empty but thinking has data, try to extract JSON from thinking
        if not raw_response and message.get("thinking"):
            thinking = message.get("thinking", "")
            logger.warning(f"[VLM] Content empty, attempting to extract from thinking field")
            # Try to find JSON in thinking
            raw_response = thinking

        # Debug: log if response is still empty
        if not raw_response:
            logger.warning(f"[VLM] Empty response! Full API response: {response_json}")

        logger.info(f"[VLM] Raw response length: {len(raw_response)} chars")

        # Strip any <think> blocks
        cleaned = re.sub(r"<think>.*?</think>", "", raw_response, flags=re.DOTALL).strip()

        # Parse JSON response
        return parse_extraction_response(cleaned, raw_response)

    except FileNotFoundError:
        return ExtractionResult(
            success=False,
            amount_found=None,
            recipient_account=None,
            reference_found=None,
            transaction_time=None,
            raw_response="",
            error="Receipt image file not found."
        )
    except httpx.HTTPError as e:
        return ExtractionResult(
            success=False,
            amount_found=None,
            recipient_account=None,
            reference_found=None,
            transaction_time=None,
            raw_response="",
            error=f"VLM service error: {str(e)}"
        )
    except Exception as e:
        return ExtractionResult(
            success=False,
            amount_found=None,
            recipient_account=None,
            reference_found=None,
            transaction_time=None,
            raw_response="",
            error=f"Extraction error: {str(e)}"
        )


def safe_extract_json(raw: str) -> Optional[dict]:
    """
    Robustly extract JSON from LLM output.
    Handles: markdown fences, nested objects, single quotes, extra text.
    """
    # Step 1: Try direct parse
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass

    # Step 2: Strip markdown code fences
    cleaned = re.sub(r'```(?:json)?\s*', '', raw)
    cleaned = re.sub(r'```\s*$', '', cleaned)

    try:
        return json.loads(cleaned.strip())
    except json.JSONDecodeError:
        pass

    # Step 3: Find JSON object with balanced braces (handles nested)
    brace_count = 0
    start_idx = None
    for i, char in enumerate(cleaned):
        if char == '{':
            if brace_count == 0:
                start_idx = i
            brace_count += 1
        elif char == '}':
            brace_count -= 1
            if brace_count == 0 and start_idx is not None:
                json_str = cleaned[start_idx:i + 1]
                try:
                    return json.loads(json_str)
                except json.JSONDecodeError:
                    # Try fixing single quotes
                    fixed = json_str.replace("'", '"')
                    try:
                        return json.loads(fixed)
                    except json.JSONDecodeError:
                        pass
                start_idx = None

    return None


def extract_from_thinking(text: str) -> Optional[dict]:
    """
    Extract receipt data from model's thinking/reasoning text using regex.
    Fallback when JSON parsing fails.
    """
    result = {}

    # Extract amount - look for patterns like "RM 5.50", "amount_found` should be 5.50"
    amount_patterns = [
        r'amount_found[`\s:]+(?:should be\s+)?(\d+\.?\d*)',
        r'RM\s*(\d+\.?\d*)',
        r'amount[:\s]+(\d+\.?\d*)',
    ]
    for pattern in amount_patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            try:
                result["amount_found"] = float(match.group(1))
                break
            except ValueError:
                pass

    # Extract recipient - look for account name patterns
    recipient_patterns = [
        r'Recipient Account[:\s]+([A-Z][A-Z\s]+(?:SDN BHD|ENTERPRISE|COMPANY|LTD)?)',
        r'recipient_account[`\s:]+["\']?([^"\']+)["\']?',
        r'"([A-Z][A-Z\s]+(?:ENTERPRISE|SDN BHD|COMPANY))"',
    ]
    for pattern in recipient_patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            result["recipient_account"] = match.group(1).strip()
            break

    # Extract reference number - prioritize BUS references (Recipient Reference)
    ref_patterns = [
        r'(BUS\d+)',  # BUS123456 format - highest priority
        r'Recipient Reference[:\s]+([A-Z0-9\s]+)',
        r'reference_found[`\s:]+["\']?(\w+)["\']?',
        r'"reference_found"[:\s]+"(\w+)"',
    ]
    for pattern in ref_patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            result["reference_found"] = match.group(1).strip()
            break

    # Extract transaction time
    time_patterns = [
        r'(\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2})',  # Already formatted
        r'Date[:\s]+(\d{2}/\d{2}/\d{4})[,\s]+Time[:\s]+(\d{2}:\d{2})',
        r'(\d{2}/\d{2}/\d{4})\s+(\d{2}:\d{2}:\d{2}\s*[AP]M)',
    ]
    for pattern in time_patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            if len(match.groups()) == 1:
                result["transaction_time"] = match.group(1)
            else:
                # Parse date and time separately
                date_str = match.group(1)
                time_str = match.group(2)
                try:
                    # Convert DD/MM/YYYY to YYYY-MM-DD
                    if '/' in date_str:
                        parts = date_str.split('/')
                        date_str = f"{parts[2]}-{parts[1]}-{parts[0]}"
                    # Convert 12h to 24h
                    if 'PM' in time_str.upper():
                        time_parts = time_str.replace('PM', '').replace('pm', '').strip().split(':')
                        hour = int(time_parts[0])
                        if hour != 12:
                            hour += 12
                        time_str = f"{hour:02d}:{time_parts[1][:2]}"
                    elif 'AM' in time_str.upper():
                        time_parts = time_str.replace('AM', '').replace('am', '').strip().split(':')
                        hour = int(time_parts[0])
                        if hour == 12:
                            hour = 0
                        time_str = f"{hour:02d}:{time_parts[1][:2]}"
                    result["transaction_time"] = f"{date_str} {time_str}"
                except (ValueError, IndexError):
                    pass
            break

    return result if result else None


def parse_extraction_response(cleaned: str, raw_response: str) -> ExtractionResult:
    """Parse VLM response and extract fields."""
    data = safe_extract_json(cleaned)

    # Fallback: try to extract from thinking text if no JSON found
    if not data and cleaned:
        logger.info("[VLM] No JSON found, trying regex extraction from thinking text")
        data = extract_from_thinking(cleaned)

    if data:
        # Handle amount - could be string like "RM 35.00" or float
        amount = data.get("amount_found") or data.get("amount")
        if isinstance(amount, str):
            # Extract numeric value from string like "RM 35.00"
            amount_match = re.search(r'[\d,]+\.?\d*', amount.replace(',', ''))
            amount = float(amount_match.group()) if amount_match else None

        return ExtractionResult(
            success=True,
            amount_found=amount,
            recipient_account=data.get("recipient_account") or data.get("recipient"),
            reference_found=data.get("reference_found") or data.get("reference"),
            transaction_time=data.get("transaction_time") or data.get("time"),
            raw_response=raw_response,
            error=None
        )

    # Fallback: extraction failed
    logger.warning(f"[VLM] Failed to parse JSON from response: {cleaned[:200]}")
    return ExtractionResult(
        success=False,
        amount_found=None,
        recipient_account=None,
        reference_found=None,
        transaction_time=None,
        raw_response=raw_response,
        error="Could not parse VLM response as JSON"
    )
