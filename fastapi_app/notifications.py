"""
Background notification service for post-booking notifications.

This module provides async notification capabilities that run in the background
without blocking the main API response. Supports SMS (Twilio) and logging-based
notifications with graceful fallbacks.
"""

import logging
import os
from typing import Optional
from datetime import datetime

logger = logging.getLogger(__name__)

# ══════════════════════════════════════════════════════════════════════════════
# Configuration
# ══════════════════════════════════════════════════════════════════════════════

# Twilio configuration (optional - falls back to logging if not configured)
TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID")
TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN")
TWILIO_FROM_NUMBER = os.getenv("TWILIO_FROM_NUMBER")

# Check if Twilio is configured
TWILIO_ENABLED = all([TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_FROM_NUMBER])

# Try to import Twilio
try:
    from twilio.rest import Client as TwilioClient
    TWILIO_AVAILABLE = True
except ImportError:
    TWILIO_AVAILABLE = False
    logger.info("Twilio not installed - SMS notifications will be logged only")


# ══════════════════════════════════════════════════════════════════════════════
# Notification Functions (Background Tasks)
# ══════════════════════════════════════════════════════════════════════════════

def send_booking_confirmation_sms(
    phone: str,
    booking_id: int,
    passenger_name: str,
    origin: str,
    destination: str,
    departure_time: str,
    seat_number: Optional[str],
    amount: float,
    payment_reference: str
) -> None:
    """
    Send SMS confirmation for a new booking.

    This runs as a background task and should not raise exceptions
    to avoid affecting the main response.
    """
    message = (
        f"Bus Booking Confirmed!\n"
        f"Booking #{booking_id}\n"
        f"Passenger: {passenger_name}\n"
        f"Route: {origin} → {destination}\n"
        f"Departure: {departure_time}\n"
        f"Seat: {seat_number or 'Any available'}\n"
        f"Amount: RM{amount:.2f}\n"
        f"Payment Ref: {payment_reference}\n"
        f"Please upload payment receipt within 10 mins."
    )

    try:
        if TWILIO_ENABLED and TWILIO_AVAILABLE:
            client = TwilioClient(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)
            client.messages.create(
                body=message,
                from_=TWILIO_FROM_NUMBER,
                to=phone
            )
            logger.info(f"[Notification] SMS sent to {phone[:4]}****{phone[-4:]} for booking #{booking_id}")
        else:
            # Log the message if Twilio is not configured
            logger.info(
                f"[Notification] SMS (simulated) to {phone[:4]}****{phone[-4:]}: "
                f"Booking #{booking_id} confirmed"
            )
    except Exception as e:
        # Never raise - this is a background task
        logger.error(f"[Notification] Failed to send SMS for booking #{booking_id}: {e}")


def send_payment_verified_sms(
    phone: str,
    booking_id: int,
    passenger_name: str,
    origin: str,
    destination: str,
    departure_time: str,
    seat_number: Optional[str]
) -> None:
    """
    Send SMS notification when payment is verified.

    This runs as a background task and should not raise exceptions.
    """
    message = (
        f"Payment Verified! ✓\n"
        f"Booking #{booking_id}\n"
        f"Passenger: {passenger_name}\n"
        f"Route: {origin} → {destination}\n"
        f"Departure: {departure_time}\n"
        f"Seat: {seat_number or 'Any available'}\n"
        f"Please show this message when boarding."
    )

    try:
        if TWILIO_ENABLED and TWILIO_AVAILABLE:
            client = TwilioClient(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)
            client.messages.create(
                body=message,
                from_=TWILIO_FROM_NUMBER,
                to=phone
            )
            logger.info(f"[Notification] Payment confirmation SMS sent for booking #{booking_id}")
        else:
            logger.info(
                f"[Notification] SMS (simulated) to {phone[:4]}****{phone[-4:]}: "
                f"Payment verified for booking #{booking_id}"
            )
    except Exception as e:
        logger.error(f"[Notification] Failed to send payment SMS for booking #{booking_id}: {e}")


def send_cancellation_sms(
    phone: str,
    booking_id: int,
    passenger_name: str,
    reason: str = "User requested"
) -> None:
    """
    Send SMS notification when booking is cancelled.

    This runs as a background task and should not raise exceptions.
    """
    message = (
        f"Booking Cancelled\n"
        f"Booking #{booking_id}\n"
        f"Passenger: {passenger_name}\n"
        f"Reason: {reason}\n"
        f"If this was an error, please make a new booking."
    )

    try:
        if TWILIO_ENABLED and TWILIO_AVAILABLE:
            client = TwilioClient(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)
            client.messages.create(
                body=message,
                from_=TWILIO_FROM_NUMBER,
                to=phone
            )
            logger.info(f"[Notification] Cancellation SMS sent for booking #{booking_id}")
        else:
            logger.info(
                f"[Notification] SMS (simulated) to {phone[:4]}****{phone[-4:]}: "
                f"Booking #{booking_id} cancelled"
            )
    except Exception as e:
        logger.error(f"[Notification] Failed to send cancellation SMS for booking #{booking_id}: {e}")


def log_booking_event(
    event_type: str,
    booking_id: int,
    details: dict
) -> None:
    """
    Log booking events for analytics/audit purposes.

    This runs as a background task to avoid blocking the response.
    """
    event = {
        "event_type": event_type,
        "booking_id": booking_id,
        "timestamp": datetime.now().isoformat(),
        **details
    }
    logger.info(f"[BookingEvent] {event}")
