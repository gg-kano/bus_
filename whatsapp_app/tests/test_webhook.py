import json as _json
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
    # Verify /auth/login was called first
    assert any("/auth/login" in str(c.request.url) for c in respx.calls)
    # Verify /chat was called with correct passenger_id
    chat_calls = [c for c in respx.calls if "/chat" in str(c.request.url)]
    assert len(chat_calls) == 1
    chat_body = _json.loads(chat_calls[0].request.content)
    assert chat_body["passenger_id"] == 99
    assert chat_body["message"] == "hi"


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
    assert "booking" in body.lower()


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
