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
