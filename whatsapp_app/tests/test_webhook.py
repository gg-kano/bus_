import pytest
import os
import sys
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
