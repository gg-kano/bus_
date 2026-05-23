import os
import time
from collections import OrderedDict
from fastapi import FastAPI, Query, HTTPException, Request
from fastapi.responses import PlainTextResponse
import httpx

VERIFY_TOKEN = os.environ["WEBHOOK_VERIFY_TOKEN"]
WA_TOKEN = os.getenv("WHATSAPP_TOKEN", "")
WA_PHONE_ID = os.getenv("WHATSAPP_PHONE_NUMBER_ID", "")
FASTAPI_URL = os.getenv("FASTAPI_URL", "http://fastapi:8000")

app = FastAPI(title="WhatsApp Webhook")


class TTLDict:
    """Simple TTL session store keyed by phone number."""

    def __init__(self, ttl: int = 1800):
        self._store: OrderedDict = OrderedDict()
        self.ttl = ttl

    def get(self, key: str, default=None):
        entry = self._store.get(key)
        if not entry:
            return default
        value, expires = entry
        if time.time() > expires:
            del self._store[key]
            return default
        return value

    def set(self, key: str, value):
        self._store[key] = (value, time.time() + self.ttl)


sessions = TTLDict()


@app.get("/webhook")
async def verify_webhook(
    hub_mode: str = Query(None, alias="hub.mode"),
    hub_verify_token: str = Query(None, alias="hub.verify_token"),
    hub_challenge: str = Query(None, alias="hub.challenge"),
):
    if hub_mode == "subscribe" and hub_verify_token == VERIFY_TOKEN:
        return PlainTextResponse(hub_challenge)
    raise HTTPException(status_code=403, detail="Verification failed")
