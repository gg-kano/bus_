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


@app.post("/webhook")
async def receive_message(request: Request):
    body = await request.json()
    try:
        value = body["entry"][0]["changes"][0]["value"]
        if "messages" not in value:
            return {"status": "no_messages"}
        message = value["messages"][0]
        from_phone = message["from"]
        msg_type = message["type"]
    except (KeyError, IndexError):
        return {"status": "ok"}

    session = sessions.get(from_phone) or {}

    # Auto-register on first contact
    if "passenger_id" not in session:
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{FASTAPI_URL}/auth/login",
                json={"name": from_phone, "phone": from_phone},
                timeout=10,
            )
            if resp.status_code == 200:
                session["passenger_id"] = resp.json()["id"]
                sessions.set(from_phone, session)

    if msg_type == "text":
        await _handle_text(from_phone, message["text"]["body"], session)
    elif msg_type == "image":
        await _handle_image(from_phone, message["image"]["id"], session)

    return {"status": "ok"}


async def _handle_text(phone: str, text: str, session: dict):
    # Waiting for user to type a booking ID (after sending a receipt image)
    if session.get("awaiting_booking_id"):
        try:
            booking_id = int(text.strip())
            session["pending_receipt_booking_id"] = booking_id
            session["awaiting_booking_id"] = False
            sessions.set(phone, session)
            await _send_text(phone, f"Got it! Now please send the payment receipt photo for booking #{booking_id}.")
            return
        except ValueError:
            await _send_text(phone, "Please reply with a valid booking ID number (e.g. 42).")
            return

    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{FASTAPI_URL}/chat",
            json={
                "message": text,
                "session_id": phone,
                "passenger_id": session.get("passenger_id"),
            },
            timeout=60,
        )
    if resp.status_code == 200:
        await _send_text(phone, resp.json()["reply"])
    else:
        await _send_text(phone, "Sorry, something went wrong. Please try again.")


async def _send_text(phone: str, text: str):
    headers = {"Authorization": f"Bearer {WA_TOKEN}", "Content-Type": "application/json"}
    async with httpx.AsyncClient() as client:
        await client.post(
            f"https://graph.facebook.com/v22.0/{WA_PHONE_ID}/messages",
            headers=headers,
            json={
                "messaging_product": "whatsapp",
                "to": phone,
                "type": "text",
                "text": {"body": text},
            },
            timeout=30,
        )


@app.get("/webhook")
async def verify_webhook(
    hub_mode: str = Query(None, alias="hub.mode"),
    hub_verify_token: str = Query(None, alias="hub.verify_token"),
    hub_challenge: str = Query(None, alias="hub.challenge"),
):
    if hub_mode == "subscribe" and hub_verify_token == VERIFY_TOKEN:
        return PlainTextResponse(hub_challenge)
    raise HTTPException(status_code=403, detail="Verification failed")
