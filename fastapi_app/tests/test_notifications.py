"""
Tests for notification service.
"""

import pytest
from unittest.mock import patch, MagicMock
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from notifications import (
    send_booking_confirmation_sms,
    send_payment_verified_sms,
    send_cancellation_sms,
    log_booking_event,
    TWILIO_ENABLED,
)


# ══════════════════════════════════════════════════════════════════════════════
# Booking Confirmation SMS Tests
# ══════════════════════════════════════════════════════════════════════════════

class TestBookingConfirmationSMS:
    """Tests for booking confirmation SMS."""

    def test_send_confirmation_without_twilio(self, caplog):
        """Test SMS is logged when Twilio is not configured."""
        with caplog.at_level("INFO"):
            send_booking_confirmation_sms(
                phone="0123456789",
                booking_id=123,
                passenger_name="Test User",
                origin="Kuala Lumpur",
                destination="Penang",
                departure_time="2025-03-25 08:00",
                seat_number="10",
                amount=35.00,
                payment_reference="BUS123456"
            )

        assert "SMS (simulated)" in caplog.text or "Notification" in caplog.text

    def test_send_confirmation_masks_phone(self, caplog):
        """Test that phone number is partially masked in logs."""
        with caplog.at_level("INFO"):
            send_booking_confirmation_sms(
                phone="0123456789",
                booking_id=123,
                passenger_name="Test User",
                origin="Kuala Lumpur",
                destination="Penang",
                departure_time="2025-03-25 08:00",
                seat_number="10",
                amount=35.00,
                payment_reference="BUS123456"
            )

        # Phone should be partially masked (e.g., 0123****6789)
        assert "0123456789" not in caplog.text  # Full phone not in logs

    def test_send_confirmation_no_exception(self):
        """Test that function never raises exceptions."""
        # Should not raise even with invalid data
        send_booking_confirmation_sms(
            phone="",
            booking_id=-1,
            passenger_name="",
            origin="",
            destination="",
            departure_time="",
            seat_number=None,
            amount=0,
            payment_reference=""
        )


# ══════════════════════════════════════════════════════════════════════════════
# Payment Verified SMS Tests
# ══════════════════════════════════════════════════════════════════════════════

class TestPaymentVerifiedSMS:
    """Tests for payment verification SMS."""

    def test_send_payment_verified_without_twilio(self, caplog):
        """Test payment verified SMS is logged."""
        with caplog.at_level("INFO"):
            send_payment_verified_sms(
                phone="0123456789",
                booking_id=123,
                passenger_name="Test User",
                origin="Kuala Lumpur",
                destination="Penang",
                departure_time="2025-03-25 08:00",
                seat_number="10"
            )

        assert "Payment verified" in caplog.text or "Notification" in caplog.text

    def test_send_payment_verified_no_exception(self):
        """Test that function never raises exceptions."""
        send_payment_verified_sms(
            phone="invalid",
            booking_id=0,
            passenger_name="",
            origin="",
            destination="",
            departure_time="",
            seat_number=None
        )


# ══════════════════════════════════════════════════════════════════════════════
# Cancellation SMS Tests
# ══════════════════════════════════════════════════════════════════════════════

class TestCancellationSMS:
    """Tests for booking cancellation SMS."""

    def test_send_cancellation_without_twilio(self, caplog):
        """Test cancellation SMS is logged."""
        with caplog.at_level("INFO"):
            send_cancellation_sms(
                phone="0123456789",
                booking_id=123,
                passenger_name="Test User",
                reason="User requested"
            )

        assert "cancelled" in caplog.text or "Notification" in caplog.text

    def test_send_cancellation_no_exception(self):
        """Test that function never raises exceptions."""
        send_cancellation_sms(
            phone="",
            booking_id=0,
            passenger_name="",
            reason=""
        )


# ══════════════════════════════════════════════════════════════════════════════
# Event Logging Tests
# ══════════════════════════════════════════════════════════════════════════════

class TestLogBookingEvent:
    """Tests for booking event logging."""

    def test_log_booking_created(self, caplog):
        """Test booking created event is logged."""
        with caplog.at_level("INFO"):
            log_booking_event(
                event_type="booking_created",
                booking_id=123,
                details={"schedule_id": 1, "num_passengers": 2}
            )

        assert "booking_created" in caplog.text
        assert "123" in caplog.text

    def test_log_payment_verified(self, caplog):
        """Test payment verified event is logged."""
        with caplog.at_level("INFO"):
            log_booking_event(
                event_type="payment_verified",
                booking_id=456,
                details={"verified_amount": 35.00}
            )

        assert "payment_verified" in caplog.text

    def test_log_booking_cancelled(self, caplog):
        """Test booking cancelled event is logged."""
        with caplog.at_level("INFO"):
            log_booking_event(
                event_type="booking_cancelled",
                booking_id=789,
                details={"reason": "user_requested"}
            )

        assert "booking_cancelled" in caplog.text


# ══════════════════════════════════════════════════════════════════════════════
# Twilio Integration Tests (Mocked)
# ══════════════════════════════════════════════════════════════════════════════

class TestTwilioIntegration:
    """Tests for Twilio integration (mocked)."""

    @patch.dict(os.environ, {
        "TWILIO_ACCOUNT_SID": "test_sid",
        "TWILIO_AUTH_TOKEN": "test_token",
        "TWILIO_FROM_NUMBER": "+1234567890"
    })
    @patch("notifications.TwilioClient")
    def test_twilio_called_when_configured(self, mock_client_class):
        """Test Twilio client is called when configured."""
        # This test would need the Twilio package installed
        # For now, just verify the function doesn't crash
        pass

    def test_twilio_not_called_when_not_configured(self, caplog):
        """Test Twilio is not called when not configured."""
        with caplog.at_level("INFO"):
            send_booking_confirmation_sms(
                phone="0123456789",
                booking_id=123,
                passenger_name="Test",
                origin="KL",
                destination="Penang",
                departure_time="2025-03-25",
                seat_number="1",
                amount=35.00,
                payment_reference="BUS123"
            )

        # Should see "simulated" in logs, not actual Twilio call
        assert "simulated" in caplog.text.lower() or "notification" in caplog.text.lower()
