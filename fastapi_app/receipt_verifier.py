"""
Receipt Verification Service

Verifies extracted receipt data against database records.
VLM only extracts data, this module handles the actual verification logic.
"""

from datetime import datetime, timedelta
from dataclasses import dataclass
from typing import Optional
from sqlalchemy.orm import Session
import sys
import os

sys.path.append(os.path.join(os.path.dirname(__file__), '..', 'admin_panel'))
from database import BankAccount, Booking

# Verification time window (minutes after booking)
VERIFICATION_TIME_WINDOW_MINUTES = 30


@dataclass
class VerificationResult:
    """Result of receipt verification."""
    is_valid: bool
    recipient_match: bool
    amount_match: bool
    reference_match: bool
    time_valid: bool
    reason: str
    details: dict


def verify_receipt(
    db: Session,
    extracted_data: dict,
    booking_id: int
) -> VerificationResult:
    """
    Verify extracted receipt data against database.

    Args:
        db: Database session
        extracted_data: JSON extracted by VLM containing:
            - amount_found: float or None
            - recipient: str or None
            - reference_found: str or None
            - transaction_time: str "YYYY-MM-DD HH:MM" or None
        booking_id: The booking ID to verify against

    Returns:
        VerificationResult with all verification details
    """
    # Get booking
    booking = db.query(Booking).filter(Booking.id == booking_id).first()
    if not booking:
        return VerificationResult(
            is_valid=False,
            recipient_match=False,
            amount_match=False,
            reference_match=False,
            time_valid=False,
            reason="Booking not found.",
            details={}
        )

    # Get active bank account
    bank_account = db.query(BankAccount).filter(BankAccount.is_active == 1).first()
    if not bank_account:
        return VerificationResult(
            is_valid=False,
            recipient_match=False,
            amount_match=False,
            reference_match=False,
            time_valid=False,
            reason="No active bank account configured.",
            details={}
        )

    # Extract values
    amount_found = extracted_data.get("amount_found")
    recipient_account = extracted_data.get("recipient_account")
    reference_found = extracted_data.get("reference_found")
    transaction_time_str = extracted_data.get("transaction_time")

    reasons = []
    details = {
        "expected_recipient": bank_account.account_holder,
        "expected_amount": booking.total_price,
        "expected_reference": booking.payment_reference,
        "booking_time": booking.booked_at.strftime("%Y-%m-%d %H:%M") if booking.booked_at else None,
        "extracted_recipient": recipient_account,
        "extracted_amount": amount_found,
        "extracted_reference": reference_found,
        "extracted_time": transaction_time_str,
    }

    # 1. Verify recipient name
    recipient_match = False
    if recipient_account and bank_account.account_holder:
        # Case-insensitive comparison, allow partial match
        recipient_lower = recipient_account.lower().strip()
        expected_lower = bank_account.account_holder.lower().strip()
        recipient_match = (
            recipient_lower == expected_lower or
            expected_lower in recipient_lower or
            recipient_lower in expected_lower
        )
    if not recipient_match:
        reasons.append(f"Recipient mismatch: expected '{bank_account.account_holder}', found '{recipient_account}'")

    # 2. Verify amount
    amount_match = False
    if amount_found is not None and booking.total_price:
        # Allow small tolerance for rounding
        tolerance = 0.01
        amount_match = abs(float(amount_found) - float(booking.total_price)) <= tolerance
    if not amount_match:
        reasons.append(f"Amount mismatch: expected RM {booking.total_price:.2f}, found RM {amount_found}")

    # 3. Verify reference number
    reference_match = False
    if reference_found and booking.payment_reference:
        # Case-insensitive, strip whitespace
        ref_lower = reference_found.lower().strip()
        expected_ref_lower = booking.payment_reference.lower().strip()
        reference_match = ref_lower == expected_ref_lower or expected_ref_lower in ref_lower
    if not reference_match:
        reasons.append(f"Reference mismatch: expected '{booking.payment_reference}', found '{reference_found}'")

    # 4. Verify transaction time
    time_valid = False
    if transaction_time_str and booking.booked_at:
        try:
            transaction_time = datetime.strptime(transaction_time_str, "%Y-%m-%d %H:%M")
            booking_time = booking.booked_at
            deadline = booking_time + timedelta(minutes=VERIFICATION_TIME_WINDOW_MINUTES)

            # Transaction must be after booking and within time window
            time_valid = booking_time <= transaction_time <= deadline
            details["deadline"] = deadline.strftime("%Y-%m-%d %H:%M")

            if not time_valid:
                if transaction_time < booking_time:
                    reasons.append(f"Transaction time ({transaction_time_str}) is before booking time")
                else:
                    reasons.append(f"Transaction time ({transaction_time_str}) exceeds {VERIFICATION_TIME_WINDOW_MINUTES} min window")
        except ValueError:
            reasons.append(f"Invalid transaction time format: {transaction_time_str}")
    else:
        if not transaction_time_str:
            reasons.append("Transaction time not found in receipt")

    # Overall validity
    is_valid = recipient_match and amount_match and reference_match and time_valid

    if is_valid:
        reason = "Payment verified successfully."
    else:
        reason = "; ".join(reasons)

    return VerificationResult(
        is_valid=is_valid,
        recipient_match=recipient_match,
        amount_match=amount_match,
        reference_match=reference_match,
        time_valid=time_valid,
        reason=reason,
        details=details
    )
