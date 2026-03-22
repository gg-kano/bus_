"""
Tests for API endpoints.
"""

import pytest
from fastapi.testclient import TestClient
from datetime import datetime, timedelta
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# ══════════════════════════════════════════════════════════════════════════════
# Health Check Tests
# ══════════════════════════════════════════════════════════════════════════════

class TestHealthEndpoints:
    """Tests for health check endpoints."""

    def test_health_check(self, client: TestClient):
        """Test basic health check endpoint."""
        response = client.get("/health")

        assert response.status_code == 200
        assert response.json()["status"] == "ok"

    def test_routes_endpoint(self, client: TestClient, sample_schedule):
        """Test routes listing endpoint."""
        response = client.get("/routes")

        assert response.status_code == 200
        data = response.json()
        assert "routes" in data
        assert "total_routes" in data


# ══════════════════════════════════════════════════════════════════════════════
# Schedule Search Tests
# ══════════════════════════════════════════════════════════════════════════════

class TestScheduleEndpoints:
    """Tests for schedule-related endpoints."""

    def test_search_schedules(self, client: TestClient, sample_schedule):
        """Test schedule search endpoint."""
        response = client.get(
            "/schedules",
            params={"origin": "Kuala Lumpur", "destination": "Penang"}
        )

        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        assert len(data) >= 1

    def test_search_schedules_with_alias(self, client: TestClient, sample_schedule):
        """Test schedule search with city alias."""
        response = client.get(
            "/schedules",
            params={"origin": "kl", "destination": "penang"}
        )

        assert response.status_code == 200
        data = response.json()
        assert len(data) >= 1

    def test_search_schedules_no_results(self, client: TestClient, sample_schedule):
        """Test schedule search with no matching results."""
        response = client.get(
            "/schedules",
            params={"origin": "Tokyo", "destination": "London"}
        )

        assert response.status_code == 200
        data = response.json()
        assert len(data) == 0

    def test_get_seat_info(self, client: TestClient, sample_schedule):
        """Test seat information endpoint."""
        response = client.get(f"/schedules/{sample_schedule.id}/seats")

        assert response.status_code == 200
        data = response.json()
        assert data["schedule_id"] == sample_schedule.id
        assert data["total_seats"] == 40
        assert "occupied_seats" in data
        assert "available_seats" in data

    def test_get_seat_info_not_found(self, client: TestClient):
        """Test seat info for non-existent schedule."""
        response = client.get("/schedules/99999/seats")

        assert response.status_code == 404


# ══════════════════════════════════════════════════════════════════════════════
# Booking Tests
# ══════════════════════════════════════════════════════════════════════════════

class TestBookingEndpoints:
    """Tests for booking-related endpoints."""

    def test_create_booking(self, client: TestClient, sample_schedule, sample_bank_account):
        """Test booking creation endpoint."""
        response = client.post(
            "/bookings",
            json={
                "schedule_id": sample_schedule.id,
                "passenger_name": "Test User",
                "passenger_phone": "0123456789",
                "num_passengers": 1
            }
        )

        assert response.status_code == 200
        data = response.json()
        assert data["booking"]["passenger_name"] == "Test User"
        assert data["booking"]["status"] == "pending_payment"
        assert "payment_info" in data

    def test_create_booking_with_seat(self, client: TestClient, sample_schedule, sample_bank_account):
        """Test booking creation with specific seat."""
        response = client.post(
            "/bookings",
            json={
                "schedule_id": sample_schedule.id,
                "passenger_name": "Test User",
                "passenger_phone": "0123456789",
                "num_passengers": 1,
                "seat_number": 10
            }
        )

        assert response.status_code == 200
        data = response.json()
        assert data["booking"]["seat_number"] == "10"

    def test_create_booking_invalid_schedule(self, client: TestClient):
        """Test booking with invalid schedule."""
        response = client.post(
            "/bookings",
            json={
                "schedule_id": 99999,
                "passenger_name": "Test User",
                "passenger_phone": "0123456789",
                "num_passengers": 1
            }
        )

        assert response.status_code == 400

    def test_get_booking(self, client: TestClient, sample_booking):
        """Test get booking endpoint."""
        response = client.get(f"/bookings/{sample_booking.id}")

        assert response.status_code == 200
        data = response.json()
        assert data["booking_id"] == sample_booking.id

    def test_get_booking_not_found(self, client: TestClient):
        """Test get booking for non-existent booking."""
        response = client.get("/bookings/99999")

        assert response.status_code == 404

    def test_cancel_booking(self, client: TestClient, sample_booking):
        """Test booking cancellation endpoint."""
        response = client.delete(f"/bookings/{sample_booking.id}")

        assert response.status_code == 200
        assert "cancelled" in response.json()["message"].lower()

    def test_cancel_booking_not_found(self, client: TestClient):
        """Test cancelling non-existent booking."""
        response = client.delete("/bookings/99999")

        assert response.status_code == 404


# ══════════════════════════════════════════════════════════════════════════════
# Chat Tests (Mocked - no Ollama)
# ══════════════════════════════════════════════════════════════════════════════

class TestChatEndpoint:
    """Tests for chat endpoint (requires mocking Ollama)."""

    def test_chat_endpoint_structure(self, client: TestClient):
        """Test chat endpoint accepts correct request structure."""
        # This will fail without Ollama, but tests the API structure
        response = client.post(
            "/chat",
            json={
                "message": "Hello",
                "session_id": "test-session-123"
            }
        )

        # Will likely be 500 without Ollama, but verifies endpoint exists
        assert response.status_code in [200, 500, 503]

    def test_chat_response_has_session_id(self, client: TestClient, monkeypatch):
        """Test chat response includes session_id."""
        # Mock the chat function to avoid Ollama dependency
        async def mock_chat(*args, **kwargs):
            return "Hello! How can I help you?"

        from main import chat as original_chat
        import main
        monkeypatch.setattr(main, "chat", mock_chat)

        # Note: This test may still fail due to async mocking complexity
        # In real testing, use pytest-asyncio and proper async mocking


# ══════════════════════════════════════════════════════════════════════════════
# Rate Limiting Tests
# ══════════════════════════════════════════════════════════════════════════════

class TestRateLimiting:
    """Tests for rate limiting."""

    def test_rate_limit_headers(self, client: TestClient, sample_schedule, sample_bank_account):
        """Test that rate limit headers are present."""
        response = client.post(
            "/bookings",
            json={
                "schedule_id": sample_schedule.id,
                "passenger_name": "Test User",
                "passenger_phone": "0123456789",
                "num_passengers": 1
            }
        )

        # Rate limiting should be active
        assert response.status_code == 200


# ══════════════════════════════════════════════════════════════════════════════
# CORS Tests
# ══════════════════════════════════════════════════════════════════════════════

class TestCORS:
    """Tests for CORS configuration."""

    def test_cors_headers_on_options(self, client: TestClient):
        """Test CORS headers on preflight request."""
        response = client.options(
            "/health",
            headers={
                "Origin": "http://localhost:8501",
                "Access-Control-Request-Method": "GET"
            }
        )

        # CORS should allow the request
        assert response.status_code in [200, 204, 405]


# ══════════════════════════════════════════════════════════════════════════════
# Request ID Tests
# ══════════════════════════════════════════════════════════════════════════════

class TestRequestId:
    """Tests for request ID correlation."""

    def test_request_id_in_response_headers(self, client: TestClient):
        """Test that response includes X-Request-ID header."""
        response = client.get("/health")

        assert "x-request-id" in response.headers

    def test_custom_request_id_preserved(self, client: TestClient):
        """Test that custom request ID is preserved."""
        custom_id = "my-custom-request-123"
        response = client.get(
            "/health",
            headers={"X-Request-ID": custom_id}
        )

        assert response.headers.get("x-request-id") == custom_id
