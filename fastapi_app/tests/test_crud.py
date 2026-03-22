"""
Tests for CRUD operations.
"""

import pytest
from datetime import datetime, timedelta
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from crud import (
    search_schedules,
    get_occupied_seats,
    create_booking,
    get_booking,
    cancel_booking,
    get_db_summary,
    get_route_schedules,
    generate_payment_reference,
)
from schemas import BookingCreate
from database import Schedule, Booking


# ══════════════════════════════════════════════════════════════════════════════
# Search Schedules Tests
# ══════════════════════════════════════════════════════════════════════════════

class TestSearchSchedules:
    """Tests for schedule search functionality."""

    def test_search_by_origin_destination(self, db, sample_schedule):
        """Test searching schedules by origin and destination."""
        results = search_schedules(db, "Kuala Lumpur", "Penang")

        assert len(results) == 1
        assert results[0].origin == "Kuala Lumpur"
        assert results[0].destination == "Penang"

    def test_search_with_city_alias(self, db, sample_schedule):
        """Test searching with city alias (e.g., KL)."""
        results = search_schedules(db, "kl", "penang")

        assert len(results) == 1
        assert results[0].origin == "Kuala Lumpur"

    def test_search_no_results(self, db, sample_schedule):
        """Test searching for non-existent route."""
        results = search_schedules(db, "Tokyo", "London")

        assert len(results) == 0

    def test_search_with_date(self, db, sample_schedule):
        """Test searching with specific date."""
        tomorrow = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")
        results = search_schedules(db, "kl", "penang", tomorrow)

        assert len(results) == 1

    def test_search_past_date_no_results(self, db, sample_schedule):
        """Test searching with past date returns no results."""
        yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
        results = search_schedules(db, "kl", "penang", yesterday)

        assert len(results) == 0

    def test_search_excludes_full_schedules(self, db, sample_schedule):
        """Test that full schedules are excluded."""
        # Set available seats to 0
        sample_schedule.available_seats = 0
        db.commit()

        results = search_schedules(db, "kl", "penang")

        assert len(results) == 0


# ══════════════════════════════════════════════════════════════════════════════
# Seat Information Tests
# ══════════════════════════════════════════════════════════════════════════════

class TestGetOccupiedSeats:
    """Tests for seat availability information."""

    def test_get_seats_no_bookings(self, db, sample_schedule):
        """Test getting seats with no bookings."""
        result = get_occupied_seats(db, sample_schedule.id)

        assert result.schedule_id == sample_schedule.id
        assert result.total_seats == 40
        assert len(result.occupied_seats) == 0
        assert len(result.available_seats) == 40

    def test_get_seats_with_booking(self, db, sample_schedule, sample_booking):
        """Test getting seats with existing booking."""
        result = get_occupied_seats(db, sample_schedule.id)

        assert 1 in result.occupied_seats
        assert 1 not in result.available_seats

    def test_get_seats_invalid_schedule(self, db):
        """Test getting seats for non-existent schedule."""
        with pytest.raises(ValueError, match="not found"):
            get_occupied_seats(db, 99999)


# ══════════════════════════════════════════════════════════════════════════════
# Create Booking Tests
# ══════════════════════════════════════════════════════════════════════════════

class TestCreateBooking:
    """Tests for booking creation."""

    def test_create_booking_success(self, db, sample_schedule, sample_bank_account):
        """Test successful booking creation."""
        booking_data = BookingCreate(
            schedule_id=sample_schedule.id,
            passenger_name="Test User",
            passenger_phone="0123456789",
            num_passengers=1
        )

        result = create_booking(db, booking_data)

        assert result.booking.passenger_name == "Test User"
        assert result.booking.status == "pending_payment"
        assert result.payment_info.amount == 35.00

    def test_create_booking_with_seat_selection(self, db, sample_schedule, sample_bank_account):
        """Test booking with specific seat selection."""
        booking_data = BookingCreate(
            schedule_id=sample_schedule.id,
            passenger_name="Test User",
            passenger_phone="0123456789",
            num_passengers=1,
            seat_number=5
        )

        result = create_booking(db, booking_data)

        assert result.booking.seat_number == "5"

    def test_create_booking_invalid_schedule(self, db):
        """Test booking with non-existent schedule."""
        booking_data = BookingCreate(
            schedule_id=99999,
            passenger_name="Test User",
            passenger_phone="0123456789",
            num_passengers=1
        )

        with pytest.raises(ValueError, match="not found"):
            create_booking(db, booking_data)

    def test_create_booking_not_enough_seats(self, db, sample_schedule, sample_bank_account):
        """Test booking when not enough seats available."""
        # Set available seats to 1
        sample_schedule.available_seats = 1
        db.commit()

        booking_data = BookingCreate(
            schedule_id=sample_schedule.id,
            passenger_name="Test User",
            passenger_phone="0123456789",
            num_passengers=5
        )

        with pytest.raises(ValueError, match="Not enough seats"):
            create_booking(db, booking_data)

    def test_create_booking_invalid_seat_number(self, db, sample_schedule, sample_bank_account):
        """Test booking with invalid seat number."""
        booking_data = BookingCreate(
            schedule_id=sample_schedule.id,
            passenger_name="Test User",
            passenger_phone="0123456789",
            num_passengers=1,
            seat_number=999  # Invalid - bus only has 40 seats
        )

        with pytest.raises(ValueError, match="Invalid seat number"):
            create_booking(db, booking_data)

    def test_create_booking_decrements_available_seats(self, db, sample_schedule, sample_bank_account):
        """Test that booking decrements available seats."""
        initial_seats = sample_schedule.available_seats

        booking_data = BookingCreate(
            schedule_id=sample_schedule.id,
            passenger_name="Test User",
            passenger_phone="0123456789",
            num_passengers=2
        )

        create_booking(db, booking_data)

        db.refresh(sample_schedule)
        assert sample_schedule.available_seats == initial_seats - 2


# ══════════════════════════════════════════════════════════════════════════════
# Get Booking Tests
# ══════════════════════════════════════════════════════════════════════════════

class TestGetBooking:
    """Tests for booking retrieval."""

    def test_get_existing_booking(self, db, sample_booking):
        """Test getting an existing booking."""
        result = get_booking(db, sample_booking.id)

        assert result is not None
        assert result.booking_id == sample_booking.id
        assert result.status == "pending_payment"

    def test_get_nonexistent_booking(self, db):
        """Test getting a non-existent booking."""
        result = get_booking(db, 99999)

        assert result is None


# ══════════════════════════════════════════════════════════════════════════════
# Cancel Booking Tests
# ══════════════════════════════════════════════════════════════════════════════

class TestCancelBooking:
    """Tests for booking cancellation."""

    def test_cancel_booking_success(self, db, sample_booking, sample_schedule):
        """Test successful booking cancellation."""
        initial_seats = sample_schedule.available_seats

        result = cancel_booking(db, sample_booking.id)

        assert result is True

        db.refresh(sample_booking)
        assert sample_booking.status == "cancelled"

        db.refresh(sample_schedule)
        assert sample_schedule.available_seats == initial_seats + 1

    def test_cancel_nonexistent_booking(self, db):
        """Test cancelling a non-existent booking."""
        result = cancel_booking(db, 99999)

        assert result is False

    def test_cancel_already_cancelled_booking(self, db, sample_booking):
        """Test cancelling an already cancelled booking."""
        # First cancellation
        cancel_booking(db, sample_booking.id)

        # Second cancellation should fail
        result = cancel_booking(db, sample_booking.id)

        assert result is False


# ══════════════════════════════════════════════════════════════════════════════
# Database Summary Tests
# ══════════════════════════════════════════════════════════════════════════════

class TestGetDbSummary:
    """Tests for database summary."""

    def test_get_summary_with_data(self, db, sample_schedule):
        """Test getting summary with existing data."""
        result = get_db_summary(db)

        assert result["total_routes"] >= 1
        assert result["total_schedules"] >= 1
        assert result["total_available_seats"] >= 1

    def test_get_summary_empty_db(self, db):
        """Test getting summary with empty database."""
        result = get_db_summary(db)

        assert result["total_routes"] == 0
        assert result["total_schedules"] == 0


# ══════════════════════════════════════════════════════════════════════════════
# Payment Reference Tests
# ══════════════════════════════════════════════════════════════════════════════

class TestGeneratePaymentReference:
    """Tests for payment reference generation."""

    def test_generate_unique_reference(self, db):
        """Test that generated references are unique."""
        ref1 = generate_payment_reference(db)
        ref2 = generate_payment_reference(db)

        assert ref1 != ref2
        assert ref1.startswith("BUS")
        assert ref2.startswith("BUS")

    def test_reference_format(self, db):
        """Test reference follows expected format."""
        ref = generate_payment_reference(db)

        assert ref.startswith("BUS")
        assert len(ref) == 9  # BUS + 6 digits
