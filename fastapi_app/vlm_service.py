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

# VLM Configuration
VLM_URL = os.getenv("VLM_URL", "http://ollama:11434")
VLM_MODEL = os.getenv("VLM_MODEL", "qwen3.5:9b")

# Timeout for VLM requests
VLM_TIMEOUT = httpx.Timeout(120.0, connect=10.0)

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
    recipient: Optional[str]
    reference_found: Optional[str]
    transaction_time: Optional[str]
    raw_response: str
    error: Optional[str]


# ── VLM Health Check ───────────────────────────────────────────────────────────

async def check_vlm() -> bool:
    """Check if VLM service is available."""
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(5.0)) as client:
            resp = await client.get(f"{VLM_URL}/api/tags")
            models = [m["name"] for m in resp.json().get("models", [])]
            logger.info(f"[VLM] Available models: {models}")
            return any(VLM_MODEL in m for m in models)
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
            image_data = base64.b64encode(f.read()).decode("utf-8")

        # Call VLM
        async with httpx.AsyncClient(timeout=VLM_TIMEOUT) as client:
            resp = await client.post(
                f"{VLM_URL}/api/chat",
                json={
                    "model": VLM_MODEL,
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
                        "num_predict": 512,  # Ensure complete JSON response
                        "think": False,
                    }
                }
            )
            resp.raise_for_status()
            raw_response = resp.json()["message"]["content"]

        logger.info(f"[VLM] Raw response length: {len(raw_response)} chars")

        # Strip any <think> blocks
        cleaned = re.sub(r"<think>.*?</think>", "", raw_response, flags=re.DOTALL).strip()

        # Parse JSON response
        return parse_extraction_response(cleaned, raw_response)

    except FileNotFoundError:
        return ExtractionResult(
            success=False,
            amount_found=None,
            recipient=None,
            reference_found=None,
            transaction_time=None,
            raw_response="",
            error="Receipt image file not found."
        )
    except httpx.HTTPError as e:
        return ExtractionResult(
            success=False,
            amount_found=None,
            recipient=None,
            reference_found=None,
            transaction_time=None,
            raw_response="",
            error=f"VLM service error: {str(e)}"
        )
    except Exception as e:
        return ExtractionResult(
            success=False,
            amount_found=None,
            recipient=None,
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


def parse_extraction_response(cleaned: str, raw_response: str) -> ExtractionResult:
    """Parse VLM response and extract fields."""
    data = safe_extract_json(cleaned)

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
            recipient=data.get("recipient"),
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
        recipient=None,
        reference_found=None,
        transaction_time=None,
        raw_response=raw_response,
        error="Could not parse VLM response as JSON"
    )
