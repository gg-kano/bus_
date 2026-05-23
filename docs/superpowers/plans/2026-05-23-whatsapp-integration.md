# WhatsApp Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the Streamlit chat frontend with a WhatsApp Business bot that receives messages via Meta Cloud API webhook and proxies them to the existing FastAPI backend.

**Architecture:** A new `whatsapp_app/` FastAPI service receives webhook POST requests from Meta, auto-registers users by phone number, calls the existing `/chat` endpoint, and sends replies back via the Meta Graph API. Image messages (payment receipts) are downloaded from Meta CDN and forwarded to the existing `/bookings/{id}/receipt` endpoint.

**Tech Stack:** Python 3.12, FastAPI, httpx, pytest, pytest-asyncio, respx, Meta WhatsApp Cloud API v22.0, Docker Compose

---

## File Map

| Action | Path | Responsibility |
|--------|------|----------------|
| Create | `whatsapp_app/main.py` | Webhook handler — verification, text, image |
| Create | `whatsapp_app/requirements.txt` | Python deps |
| Create | `whatsapp_app/Dockerfile` | Container definition |
| Create | `whatsapp_app/tests/__init__.py` | Test package marker |
| Create | `whatsapp_app/tests/test_webhook.py` | All webhook tests |
| Modify | `docker-compose.yml` | Remove `chat` service, add `whatsapp` service |
| Modify | `.env` | Add WhatsApp credentials |
| Modify | `.env.example` | Document new env vars |

---

## Task 1: Add credentials to .env

**Files:**
- Modify: `.env`
- Modify: `.env.example`

- [ ] **Step 1: Add WhatsApp env vars to .env**

Open `.env` and append these lines (fill in your real values):

```env
# WhatsApp Business API
WHATSAPP_TOKEN=EAAgucZAuXQm8BRllNu0CT9REsQZB17sZBuHft9WcLVtszaOob9ymnQBH9vm9Y8LTWrkirZA8shAmllrvAcZB4xxZBS1kae2Wf4NwPiimEaMkTZB7OKbTCfOFVBgiDWeKOwRoDZAQZAvTq6aTBGWnZBggZByANBS7ZBpZAwRFWFiSr6RGKKhXZAN4E2nCoMmVlVAz9W3az5lLOk7CUP1ZAxZC0xfmDM23h3ZAtmSZC5STFhlkEBZBMfO1IsZA0LzMvUYyZBCJRmAhVWrCHnX82DW298Vl60a3cxQ3uGeA5
WHATSAPP_PHONE_NUMBER_ID=1100273573171396
WEBHOOK_VERIFY_TOKEN=busgo_secret_2026
```

- [ ] **Step 2: Add placeholder vars to .env.example**

Open `.env.example` and append:

```env
# WhatsApp Business API (Meta Cloud API)
WHATSAPP_TOKEN=your_meta_access_token_here
WHATSAPP_PHONE_NUMBER_ID=your_phone_number_id_here
WEBHOOK_VERIFY_TOKEN=any_secret_string_you_choose
```

- [ ] **Step 3: Commit**

```bash
git add .env.example
git commit -m "chore: add WhatsApp env var placeholders to .env.example"
```

> Note: `.env` is gitignored — do not commit it.

---

## Task 2: Create whatsapp_app scaffold

**Files:**
- Create: `whatsapp_app/requirements.txt`
- Create: `whatsapp_app/Dockerfile`
- Create: `whatsapp_app/tests/__init__.py`

- [ ] **Step 1: Create requirements.txt**

Create `whatsapp_app/requirements.txt`:

```
fastapi>=0.115.0
uvicorn>=0.32.0
httpx>=0.27.0
python-dotenv>=1.0.0
pytest>=8.0.0
pytest-asyncio>=0.24.0
respx>=0.21.0
```

- [ ] **Step 2: Create Dockerfile**

Create `whatsapp_app/Dockerfile`:

```dockerfile
FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8080", "--reload"]
```

- [ ] **Step 3: Create tests package**

```bash
mkdir -p whatsapp_app/tests
touch whatsapp_app/tests/__init__.py
```

- [ ] **Step 4: Commit scaffold**

```bash
git add whatsapp_app/
git commit -m "chore: add whatsapp_app scaffold (Dockerfile, requirements)"
```

---

## Task 3: Implement GET /webhook (Meta verification)

**Files:**
- Create: `whatsapp_app/main.py`
- Create: `whatsapp_app/tests/test_webhook.py`

When Meta registers your webhook URL, it sends a GET request with `hub.mode=subscribe`, `hub.verify_token`, and `hub.challenge`. Your server must respond with the challenge string if the verify token matches.

- [ ] **Step 1: Write the failing test**

Create `whatsapp_app/tests/test_webhook.py`:

```python
import pytest
import os
import sys
import respx
from httpx import Response
from starlette.testclient import TestClient
from unittest.mock import patch

# These tests run against the app directly (no real network calls to Meta or FastAPI).
# respx mocks all outbound httpx calls made by the app.

@pytest.fixture(scope="module")
def app():
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
    with patch.dict(os.environ, {
        "WEBHOOK_VERIFY_TOKEN": "test_token",
        "WHATSAPP_TOKEN": "test_wa_token",
        "WHATSAPP_PHONE_NUMBER_ID": "123456",
        "FASTAPI_URL": "http://test-fastapi:8000",
    }):
        if "main" in sys.modules:
            del sys.modules["main"]
        import main as m
        yield m.app


@pytest.fixture
def client(app):
    return TestClient(app)


# ── GET /webhook ──────────────────────────────────────────────────────────────

def test_webhook_verification_success(client):
    resp = client.get("/webhook", params={
        "hub.mode": "subscribe",
        "hub.verify_token": "test_token",
        "hub.challenge": "CHALLENGE_STRING",
    })
    assert resp.status_code == 200
    assert resp.text == "CHALLENGE_STRING"


def test_webhook_verification_wrong_token(client):
    resp = client.get("/webhook", params={
        "hub.mode": "subscribe",
        "hub.verify_token": "wrong_token",
        "hub.challenge": "CHALLENGE_STRING",
    })
    assert resp.status_code == 403


def test_webhook_verification_wrong_mode(client):
    resp = client.get("/webhook", params={
        "hub.mode": "unsubscribe",
        "hub.verify_token": "test_token",
        "hub.challenge": "CHALLENGE_STRING",
    })
    assert resp.status_code == 403
```

- [ ] **Step 2: Run to verify it fails**

```bash
cd whatsapp_app
pip install -r requirements.txt
pytest tests/test_webhook.py::test_webhook_verification_success -v
```

Expected: `ModuleNotFoundError: No module named 'main'` or `ImportError`

- [ ] **Step 3: Create main.py with GET /webhook**

Create `whatsapp_app/main.py`:

```python
import os
import time
from collections import OrderedDict
from fastapi import FastAPI, Query, HTTPException, Request
from fastapi.responses import PlainTextResponse
import httpx

VERIFY_TOKEN = os.getenv("WEBHOOK_VERIFY_TOKEN", "busgo_secret")
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
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_webhook.py::test_webhook_verification_success tests/test_webhook.py::test_webhook_verification_wrong_token tests/test_webhook.py::test_webhook_verification_wrong_mode -v
```

Expected: `3 passed`

- [ ] **Step 5: Commit**

```bash
cd ..
git add whatsapp_app/main.py whatsapp_app/tests/test_webhook.py
git commit -m "feat: add WhatsApp webhook verification endpoint"
```

---

## Task 4: Implement POST /webhook — text message handler

**Files:**
- Modify: `whatsapp_app/main.py`
- Modify: `whatsapp_app/tests/test_webhook.py`

The POST handler receives a JSON payload from Meta. It extracts the sender's phone number and message text, calls `/auth/login` on first message, then calls `/chat` and sends the reply back.

- [ ] **Step 1: Write the failing tests**

Append to `whatsapp_app/tests/test_webhook.py`:

```python
import respx
from httpx import Response

# ── Helpers ────────────────────────────────────────────────────────────────────

def whatsapp_text_payload(from_phone: str, text: str) -> dict:
    return {
        "entry": [{
            "changes": [{
                "value": {
                    "messages": [{
                        "from": from_phone,
                        "type": "text",
                        "text": {"body": text},
                        "id": "msg_001",
                    }],
                    "contacts": [{"profile": {"name": "Test User"}}],
                }
            }]
        }]
    }


# ── POST /webhook — text messages ─────────────────────────────────────────────

@respx.mock
def test_text_message_auto_login_and_chat(client):
    """First message triggers /auth/login then /chat, reply is sent to Meta."""
    respx.post("http://test-fastapi:8000/auth/login").mock(
        return_value=Response(200, json={"id": 99, "name": "60123456789", "phone": "60123456789"})
    )
    respx.post("http://test-fastapi:8000/chat").mock(
        return_value=Response(200, json={"reply": "Hello! How can I help?", "session_id": "60123456789"})
    )
    respx.post("https://graph.facebook.com/v22.0/123456/messages").mock(
        return_value=Response(200, json={"messages": [{"id": "wamid.001"}]})
    )

    resp = client.post("/webhook", json=whatsapp_text_payload("60123456789", "hi"))

    assert resp.status_code == 200
    # Verify /chat was called with correct payload
    chat_call = respx.calls.last
    assert chat_call is not None


@respx.mock
def test_text_message_no_duplicate_login(client, app):
    """Second message from same number skips /auth/login."""
    # Pre-seed session via the already-loaded app module
    import sys
    m = sys.modules["main"]
    m.sessions.set("60111000001", {"passenger_id": 5})

    respx.post("http://test-fastapi:8000/chat").mock(
        return_value=Response(200, json={"reply": "Bus found!", "session_id": "60111000001"})
    )
    respx.post("https://graph.facebook.com/v22.0/123456/messages").mock(
        return_value=Response(200, json={})
    )

    resp = client.post("/webhook", json=whatsapp_text_payload("60111000001", "search bus"))
    assert resp.status_code == 200
    # /auth/login should NOT have been called
    login_calls = [c for c in respx.calls if "/auth/login" in str(c.request.url)]
    assert len(login_calls) == 0


@respx.mock
def test_text_message_no_messages_key(client):
    """Webhook payload without messages key returns ok without crashing."""
    payload = {"entry": [{"changes": [{"value": {"statuses": [{"status": "delivered"}]}}]}]}
    resp = client.post("/webhook", json=payload)
    assert resp.status_code == 200
    assert resp.json() == {"status": "no_messages"}
```

- [ ] **Step 2: Run to verify they fail**

```bash
cd whatsapp_app
pytest tests/test_webhook.py::test_text_message_auto_login_and_chat -v
```

Expected: `FAILED` — POST /webhook route does not exist yet.

- [ ] **Step 3: Add text message handler to main.py**

Append to `whatsapp_app/main.py` (after the `sessions = TTLDict()` line, before end of file):

```python
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
```

- [ ] **Step 4: Run all text message tests**

```bash
pytest tests/test_webhook.py -v -k "not image"
```

Expected: `5 passed`

- [ ] **Step 5: Commit**

```bash
cd ..
git add whatsapp_app/main.py whatsapp_app/tests/test_webhook.py
git commit -m "feat: handle incoming WhatsApp text messages and auto-login"
```

---

## Task 5: Implement POST /webhook — image (receipt) handler

**Files:**
- Modify: `whatsapp_app/main.py`
- Modify: `whatsapp_app/tests/test_webhook.py`

When a user sends a photo, the bot asks for the booking ID (if not already known), downloads the image from Meta CDN, then POSTs it to the existing `/bookings/{id}/receipt` endpoint.

- [ ] **Step 1: Write the failing tests**

Append to `whatsapp_app/tests/test_webhook.py`:

```python
# ── POST /webhook — image (receipt) messages ───────────────────────────────────

def whatsapp_image_payload(from_phone: str, media_id: str) -> dict:
    return {
        "entry": [{
            "changes": [{
                "value": {
                    "messages": [{
                        "from": from_phone,
                        "type": "image",
                        "image": {"id": media_id, "mime_type": "image/jpeg"},
                        "id": "msg_002",
                    }]
                }
            }]
        }]
    }


@respx.mock
def test_image_without_booking_id_asks_for_id(client, app):
    """Image sent without pending booking ID → bot asks for booking ID."""
    respx.post("http://test-fastapi:8000/auth/login").mock(
        return_value=Response(200, json={"id": 10, "name": "60199", "phone": "60199"})
    )
    respx.post("https://graph.facebook.com/v22.0/123456/messages").mock(
        return_value=Response(200, json={})
    )

    resp = client.post("/webhook", json=whatsapp_image_payload("60199", "media_abc"))
    assert resp.status_code == 200

    # Check the reply message asked for booking ID
    send_call = respx.calls[-1]
    body = send_call.request.content.decode()
    assert "booking ID" in body.lower() or "booking" in body.lower()


@respx.mock
def test_image_with_pending_booking_id_uploads_receipt(client, app):
    """Image sent when booking ID is pending → downloads and uploads receipt."""
    m = sys.modules["main"]
    m.sessions.set("60188", {"passenger_id": 7, "pending_receipt_booking_id": 42})

    media_bytes = b"fake_image_data"

    respx.get("https://graph.facebook.com/v22.0/media_xyz").mock(
        return_value=Response(200, json={"url": "https://cdn.meta.com/media_xyz", "mime_type": "image/jpeg"})
    )
    respx.get("https://cdn.meta.com/media_xyz").mock(
        return_value=Response(200, content=media_bytes, headers={"content-type": "image/jpeg"})
    )
    respx.post("http://test-fastapi:8000/bookings/42/receipt").mock(
        return_value=Response(200, json={"status": "verified", "message": "Payment confirmed!"})
    )
    respx.post("https://graph.facebook.com/v22.0/123456/messages").mock(
        return_value=Response(200, json={})
    )

    resp = client.post("/webhook", json=whatsapp_image_payload("60188", "media_xyz"))
    assert resp.status_code == 200

    # Check confirmation message was sent
    send_call = respx.calls[-1]
    body = send_call.request.content.decode()
    assert "verified" in body.lower() or "confirmed" in body.lower()


@respx.mock
def test_image_rejected_receipt_sends_error_message(client, app):
    """Rejected receipt → bot sends rejection reason."""
    m = sys.modules["main"]
    m.sessions.set("60177", {"passenger_id": 3, "pending_receipt_booking_id": 99})

    respx.get("https://graph.facebook.com/v22.0/media_bad").mock(
        return_value=Response(200, json={"url": "https://cdn.meta.com/media_bad", "mime_type": "image/jpeg"})
    )
    respx.get("https://cdn.meta.com/media_bad").mock(
        return_value=Response(200, content=b"bad_img", headers={"content-type": "image/jpeg"})
    )
    respx.post("http://test-fastapi:8000/bookings/99/receipt").mock(
        return_value=Response(200, json={"status": "rejected", "message": "Amount mismatch"})
    )
    respx.post("https://graph.facebook.com/v22.0/123456/messages").mock(
        return_value=Response(200, json={})
    )

    resp = client.post("/webhook", json=whatsapp_image_payload("60177", "media_bad"))
    assert resp.status_code == 200

    send_call = respx.calls[-1]
    body = send_call.request.content.decode()
    assert "rejected" in body.lower() or "amount mismatch" in body.lower()
```

- [ ] **Step 2: Run to verify they fail**

```bash
cd whatsapp_app
pytest tests/test_webhook.py::test_image_without_booking_id_asks_for_id -v
```

Expected: `FAILED` — `_handle_image` not defined yet.

- [ ] **Step 3: Add image handler to main.py**

Append to `whatsapp_app/main.py` (after the `_send_text` function):

```python
async def _handle_image(phone: str, media_id: str, session: dict):
    booking_id = session.get("pending_receipt_booking_id")

    if not booking_id:
        session["awaiting_booking_id"] = True
        sessions.set(phone, session)
        await _send_text(phone, "I received your receipt image! Please reply with your booking ID (e.g. 42).")
        return

    headers = {"Authorization": f"Bearer {WA_TOKEN}"}
    async with httpx.AsyncClient() as client:
        # Step 1: Get media URL from Meta
        meta_resp = await client.get(
            f"https://graph.facebook.com/v22.0/{media_id}",
            headers=headers,
            timeout=30,
        )
        if meta_resp.status_code != 200:
            await _send_text(phone, "Failed to download your receipt. Please try again.")
            return

        media_url = meta_resp.json()["url"]

        # Step 2: Download image bytes
        media_resp = await client.get(media_url, headers=headers, timeout=30)
        if media_resp.status_code != 200:
            await _send_text(phone, "Failed to download your receipt. Please try again.")
            return

        content_type = media_resp.headers.get("content-type", "image/jpeg")
        ext = content_type.split("/")[-1].split(";")[0]

        # Step 3: Upload to FastAPI
        files = {"file": (f"receipt.{ext}", media_resp.content, content_type)}
        upload_resp = await client.post(
            f"{FASTAPI_URL}/bookings/{booking_id}/receipt",
            files=files,
            timeout=120,
        )

    if upload_resp.status_code == 200:
        result = upload_resp.json()
        if result["status"] == "verified":
            await _send_text(phone, f"✅ Payment verified! Booking #{booking_id} is confirmed. Safe travels!")
        else:
            await _send_text(phone, f"❌ Receipt rejected: {result['message']}. Please check and resend.")
    else:
        await _send_text(phone, "Failed to verify receipt. Please try again.")

    # Clear pending receipt state
    session.pop("pending_receipt_booking_id", None)
    sessions.set(phone, session)
```

- [ ] **Step 4: Run all tests**

```bash
pytest tests/test_webhook.py -v
```

Expected: `8 passed`

- [ ] **Step 5: Commit**

```bash
cd ..
git add whatsapp_app/main.py whatsapp_app/tests/test_webhook.py
git commit -m "feat: handle WhatsApp image messages for payment receipt upload"
```

---

## Task 6: Update docker-compose.yml

**Files:**
- Modify: `docker-compose.yml`

Remove the `chat` service (Streamlit). Add the `whatsapp` service.

- [ ] **Step 1: Remove `chat` service and add `whatsapp` service**

In `docker-compose.yml`, delete the entire `chat:` block (lines 74–92) and replace with:

```yaml
  whatsapp:
    build:
      context: ./whatsapp_app
      dockerfile: Dockerfile
    container_name: bus_whatsapp
    restart: unless-stopped
    environment:
      FASTAPI_URL: http://fastapi:8000
      WHATSAPP_TOKEN: ${WHATSAPP_TOKEN}
      WHATSAPP_PHONE_NUMBER_ID: ${WHATSAPP_PHONE_NUMBER_ID}
      WEBHOOK_VERIFY_TOKEN: ${WEBHOOK_VERIFY_TOKEN}
      TZ: Asia/Kuala_Lumpur
    ports:
      - "8080:8080"
    networks:
      - bus_agent_net
    depends_on:
      - fastapi
```

- [ ] **Step 2: Verify docker-compose.yml is valid**

```bash
docker compose config --quiet
```

Expected: no errors, silent output.

- [ ] **Step 3: Commit**

```bash
git add docker-compose.yml
git commit -m "feat: replace chat_app with whatsapp_app in docker-compose"
```

---

## Task 7: Build and run locally

**Goal:** Confirm the whatsapp service starts and the webhook verification endpoint works.

- [ ] **Step 1: Build and start services**

```bash
docker compose up --build whatsapp fastapi postgres -d
```

Wait ~30 seconds for FastAPI to initialize.

- [ ] **Step 2: Check whatsapp service logs**

```bash
docker compose logs whatsapp
```

Expected output includes:
```
INFO:     Application startup complete.
INFO:     Uvicorn running on http://0.0.0.0:8080
```

- [ ] **Step 3: Test verification endpoint locally**

```bash
curl "http://localhost:8080/webhook?hub.mode=subscribe&hub.verify_token=busgo_secret_2026&hub.challenge=TEST123"
```

Expected: `TEST123`

- [ ] **Step 4: Install and run ngrok**

```bash
# Install ngrok (if not installed)
curl -sSL https://ngrok-agent.s3.amazonaws.com/ngrok.asc | sudo tee /etc/apt/trusted.gpg.d/ngrok.asc >/dev/null
echo "deb https://ngrok-agent.s3.amazonaws.com buster main" | sudo tee /etc/apt/sources.list.d/ngrok.list
sudo apt update && sudo apt install ngrok

# Or download directly:
# wget https://bin.equinox.io/c/bNyj1mQVY4c/ngrok-v3-stable-linux-amd64.tgz
# tar -xf ngrok-v3-stable-linux-amd64.tgz

ngrok http 8080
```

ngrok will print a public HTTPS URL like:
```
Forwarding  https://abc123.ngrok-free.app -> http://localhost:8080
```

Copy this URL.

- [ ] **Step 5: Register webhook in Meta Developer Console**

1. Go to [developers.facebook.com](https://developers.facebook.com) → your app
2. Left sidebar → **WhatsApp** → **Configuration**
3. Under **Webhook**, click **Edit**
4. Set **Callback URL** to: `https://abc123.ngrok-free.app/webhook`
5. Set **Verify token** to: `busgo_secret_2026`
6. Click **Verify and Save**

Meta sends a GET to your `/webhook` endpoint. If it responds correctly, the console shows a green checkmark.

- [ ] **Step 6: Subscribe to messages**

Still in Meta Developer Console → **Webhook Fields** → click **Manage** → tick `messages` → Save.

- [ ] **Step 7: Send a test WhatsApp message**

From your phone, send a WhatsApp message to the Meta test number `+1 (555) 648-5135`.

Watch logs:
```bash
docker compose logs -f whatsapp
```

Expected: logs show the incoming webhook, `/auth/login` call, `/chat` call, and the reply being sent back.

---

## Task 8: Production token (when ready to go live)

The test access token expires in ~24 hours. For production:

- [ ] **Step 1: Create a permanent System User token**

1. In Meta Business Manager (business.facebook.com) → **System Users** → **Add**
2. Assign the WhatsApp app with `whatsapp_business_messaging` permission
3. Generate a token → copy it
4. Update `WHATSAPP_TOKEN` in your server's `.env`
5. Restart: `docker compose restart whatsapp`

- [ ] **Step 2: Apply for official WhatsApp Business number**

In Meta Developer Console → **WhatsApp** → **Getting Started** → follow the "Add a phone number" flow to replace the test number with your real business number. This requires Meta Business Verification (upload business documents — takes 1–5 business days).
