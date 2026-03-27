from sqlalchemy.orm import Session
from sqlalchemy import and_
from sqlalchemy.exc import IntegrityError
from datetime import datetime, date, timedelta
from typing import List, Optional
import sys, os
import random
import logging

logger = logging.getLogger(__name__)

sys.path.append(os.path.join(os.path.dirname(__file__), '..', 'admin_panel'))
from database import Route, Schedule, Passenger, Booking, Bus, PaymentReceipt, BankAccount
from schemas import BookingCreate, ScheduleResult, BookingResult, PaymentInfo, BookingWithPaymentInfo, SeatInfo, PassengerInfo

# Payment deadline in minutes
PAYMENT_DEADLINE_MINUTES = 10

# ── City Name Normalization ───────────────────────────────────────────────────
# Canonical city name → list of extra aliases (canonical name is auto-included)
_CITY_ALIAS_MAP = {
    "Kuala Lumpur":  ["kl", "klcc"],
    "Penang":        ["pulau pinang", "georgetown", "butterworth"],
    "Johor Bahru":   ["jb", "johor"],
    "Ipoh":          [],
    "Melaka":        ["malacca"],
    "Kuantan":       [],
    "Kota Bharu":    ["kb", "kelantan"],
    "Kuching":       ["sarawak"],
    "Kota Kinabalu": ["kk", "sabah"],
    "Alor Setar":    ["alor star", "kedah"],
    "Seremban":      ["negeri sembilan"],
    "Taiping":       [],
    "Muar":          [],
    "Shah Alam":     [],
    "Subang Jaya":   ["subang"],
    "Petaling Jaya": ["pj"],
}

# Build flat lookup: every alias (+ lowercased canonical name) → canonical
CITY_ALIASES = {}
for _canonical, _aliases in _CITY_ALIAS_MAP.items():
    CITY_ALIASES[_canonical.lower()] = _canonical
    for _alias in _aliases:
        CITY_ALIASES[_alias.lower()] = _canonical

# Try to import rapidfuzz for fuzzy matching (optional dependency)
try:
    from rapidfuzz import process, fuzz
    FUZZY_ENABLED = True
except ImportError:
    FUZZY_ENABLED = False
    logger.warning("rapidfuzz not installed. Fuzzy city matching disabled. Install with: pip install rapidfuzz")

# Try to import dateparser for natural language date parsing (optional dependency)
try:
    import dateparser
    DATEPARSER_ENABLED = True
except ImportError:
    DATEPARSER_ENABLED = False
    logger.warning("dateparser not installed. Natural language dates disabled. Install with: pip install dateparser")


def resolve_date(raw: Optional[str]) -> Optional[date]:
    """
    Parse natural language dates like "tomorrow", "next Saturday", "15 March".
    Returns a date object or None if parsing fails.
    """
    if not raw:
        return None

    # Step 1: Try standard format first
    try:
        return datetime.strptime(raw, "%Y-%m-%d").date()
    except (ValueError, TypeError):
        pass

    # Step 2: Try dateparser for natural language
    if DATEPARSER_ENABLED:
        parsed = dateparser.parse(
            raw,
            settings={
                "PREFER_DATES_FROM": "future",
                "RETURN_AS_TIMEZONE_AWARE": False,
                "RELATIVE_BASE": datetime.now()
            }
        )
        if parsed:
            logger.debug(f"Parsed date '{raw}' -> {parsed.date()}")
            return parsed.date()

    # Step 3: Try common formats
    for fmt in ["%d/%m/%Y", "%m/%d/%Y", "%d-%m-%Y", "%d %B", "%d %b", "%B %d", "%b %d"]:
        try:
            parsed = datetime.strptime(raw, fmt)
            # If no year, assume current or next year
            if "%Y" not in fmt:
                today = date.today()
                parsed = parsed.replace(year=today.year)
                if parsed.date() < today:
                    parsed = parsed.replace(year=today.year + 1)
            return parsed.date()
        except ValueError:
            continue

    logger.warning(f"Could not parse date: '{raw}'")
    return None


def normalize_city(city: str) -> str:
    """
    Normalize city name to canonical form.
    Uses exact alias matching first, then fuzzy matching as fallback.
    """
    if not city:
        return city

    clean = city.lower().strip()

    # Step 1: Exact alias match
    if clean in CITY_ALIASES:
        return CITY_ALIASES[clean]

    # Step 2: Fuzzy match (if rapidfuzz available)
    if FUZZY_ENABLED:
        match_result = process.extractOne(
            clean,
            CITY_ALIASES.keys(),
            scorer=fuzz.token_sort_ratio
        )
        if match_result:
            match, score, _ = match_result
            if score >= 80:
                logger.debug(f"Fuzzy matched '{city}' -> '{CITY_ALIASES[match]}' (score: {score})")
                return CITY_ALIASES[match]

    # Step 3: Return original (title case) as fallback
    return city.title()


def generate_payment_reference(db: Session) -> str:
    """Generate a payment reference."""
    return "S091838 621"


# ── Passenger Auth ────────────────────────────────────────────────────────────

def get_or_create_passenger(db: Session, name: str, phone: str) -> tuple[PassengerInfo, bool]:
    """Get existing passenger by phone or create a new one.
    Returns (PassengerInfo, is_new)."""
    passenger = db.query(Passenger).filter(Passenger.phone == phone).first()

    if passenger:
        # Update name if it changed
        if passenger.name != name:
            passenger.name = name
            db.commit()
            db.refresh(passenger)
        return PassengerInfo(
            id=passenger.id,
            name=passenger.name,
            phone=passenger.phone,
            email=passenger.email,
            is_new=False,
        ), False

    passenger = Passenger(name=name, phone=phone)
    db.add(passenger)
    db.commit()
    db.refresh(passenger)
    return PassengerInfo(
        id=passenger.id,
        name=passenger.name,
        phone=passenger.phone,
        email=passenger.email,
        is_new=True,
    ), True


def get_bookings_by_passenger(db: Session, passenger_id: int) -> List[BookingResult]:
    """Get all bookings for a passenger."""
    bookings = (
        db.query(Booking)
        .filter(Booking.passenger_id == passenger_id)
        .order_by(Booking.booked_at.desc())
        .all()
    )
    return [
        BookingResult(
            booking_id=b.id,
            passenger_name=b.passenger.name,
            origin=b.schedule.route.origin,
            destination=b.schedule.route.destination,
            departure_time=b.schedule.departure_time.strftime("%Y-%m-%d %H:%M"),
            seat_number=b.seat_number or "-",
            total_price=b.total_price,
            status=b.status,
            booked_at=b.booked_at.strftime("%Y-%m-%d %H:%M:%S") if b.booked_at else None,
            payment_deadline=b.payment_deadline.strftime("%Y-%m-%d %H:%M:%S") if b.payment_deadline else None,
            payment_reference=b.payment_reference,
        )
        for b in bookings
    ]


# ── Search Schedules ───────────────────────────────────────────────────────────

def search_schedules(
    db: Session,
    origin: str,
    destination: str,
    travel_date: Optional[str] = None
) -> List[ScheduleResult]:

    now = datetime.now()

    # Normalize city names for better matching
    norm_origin = normalize_city(origin)
    norm_dest = normalize_city(destination)
    logger.info(f"[Search] Searching: '{origin}'->'{norm_origin}' to '{destination}'->'{norm_dest}', date={travel_date}")

    query = (
        db.query(Schedule)
        .join(Route)
        .join(Bus)
        .filter(
            Route.origin.ilike(f"%{norm_origin}%"),
            Route.destination.ilike(f"%{norm_dest}%"),
            Schedule.status == "active",
            Schedule.departure_time >= now  # Only show upcoming schedules
        )
    )

    if travel_date:
        # Use resolve_date for natural language support (handles "tomorrow", "next Friday", etc.)
        d = resolve_date(travel_date)
        if d:
            query = query.filter(
                and_(
                    Schedule.departure_time >= datetime.combine(d, datetime.min.time()),
                    Schedule.departure_time <= datetime.combine(d, datetime.max.time())
                )
            )
        # If d is None, we just return all upcoming schedules (no date filter)

    schedules = query.order_by(Schedule.departure_time).all()
    logger.info(f"[Search] Found {len(schedules)} schedules for {norm_origin} -> {norm_dest}")

    return [
        ScheduleResult(
            id=s.id,
            origin=s.route.origin,
            destination=s.route.destination,
            departure_time=s.departure_time.strftime("%Y-%m-%d %H:%M"),
            arrival_time=s.arrival_time.strftime("%Y-%m-%d %H:%M"),
            price=s.price,
            available_seats=s.available_seats,
            bus_type=s.bus.bus_type,
            plate_number=s.bus.plate_number,
        )
        for s in schedules
    ]


# ── Seat Information ──────────────────────────────────────────────────────────

def get_occupied_seats(db: Session, schedule_id: int) -> SeatInfo:
    """Get occupied seats and bus configuration for a schedule."""
    schedule = db.query(Schedule).filter(Schedule.id == schedule_id).first()
    if not schedule:
        raise ValueError(f"Schedule {schedule_id} not found.")

    bus = schedule.bus
    total_seats = bus.total_seats
    seats_per_row = bus.seats_per_row or 4
    seat_layout = bus.seat_layout or "2-2"

    # Get all booked seats for this schedule (only non-cancelled bookings)
    bookings = db.query(Booking).filter(
        Booking.schedule_id == schedule_id,
        Booking.status.in_(["pending_payment", "confirmed"])
    ).all()

    occupied = []
    for b in bookings:
        if b.seat_number:
            try:
                occupied.append(int(b.seat_number))
            except ValueError:
                pass  # Skip non-numeric seat numbers

    # Calculate available seats
    all_seats = list(range(1, total_seats + 1))
    available = [s for s in all_seats if s not in occupied]

    return SeatInfo(
        schedule_id=schedule_id,
        total_seats=total_seats,
        seats_per_row=seats_per_row,
        seat_layout=seat_layout,
        occupied_seats=sorted(occupied),
        available_seats=sorted(available),
    )


# ── Create Booking ─────────────────────────────────────────────────────────────

def create_booking(db: Session, data: BookingCreate) -> BookingResult:

    # 1. Get schedule
    schedule = db.query(Schedule).filter(Schedule.id == data.schedule_id).first()
    if not schedule:
        raise ValueError(f"Schedule {data.schedule_id} not found.")
    if schedule.available_seats < data.num_passengers:
        raise ValueError(f"Not enough seats. Only {schedule.available_seats} left.")

    # 2. Get or create passenger
    passenger = db.query(Passenger).filter(
        Passenger.phone == data.passenger_phone
    ).first()

    if not passenger:
        passenger = Passenger(
            name=data.passenger_name,
            phone=data.passenger_phone,
            email=data.passenger_email,
            ic_number=data.passenger_ic,
        )
        db.add(passenger)
        db.flush()  # get passenger.id without full commit

    # 3. Assign seat number (user-selected or auto-assign)
    existing_seats = [
        int(b.seat_number) for b in
        db.query(Booking).filter(
            Booking.schedule_id == data.schedule_id,
            Booking.status.in_(["pending_payment", "confirmed"])
        ).all()
        if b.seat_number and b.seat_number.isdigit()
    ]

    total_seats = schedule.bus.total_seats

    if data.seat_number is not None:
        # User selected a specific seat - validate it
        if data.seat_number < 1 or data.seat_number > total_seats:
            raise ValueError(f"Invalid seat number. Must be between 1 and {total_seats}.")
        if data.seat_number in existing_seats:
            raise ValueError(f"Seat {data.seat_number} is already booked. Please choose another seat.")
        seat_num = data.seat_number
    else:
        # Auto-assign first available seat
        seat_num = 1
        while seat_num in existing_seats:
            seat_num += 1
        if seat_num > total_seats:
            raise ValueError("No seats available.")

    # 4. Create booking with pending_payment status
    total = schedule.price * data.num_passengers
    payment_deadline = datetime.now() + timedelta(minutes=PAYMENT_DEADLINE_MINUTES)
    payment_reference = generate_payment_reference(db)

    booking = Booking(
        passenger_id=passenger.id,
        schedule_id=data.schedule_id,
        seat_number=str(seat_num),
        payment_reference=payment_reference,
        status="pending_payment",
        total_price=total,
        payment_deadline=payment_deadline,
    )
    db.add(booking)

    # 5. Decrement available seats (reserved until payment deadline)
    schedule.available_seats -= data.num_passengers

    # Commit with race condition protection via unique index
    try:
        db.commit()
    except IntegrityError as e:
        db.rollback()
        logger.warning(f"Booking IntegrityError: {e} | seat {seat_num} on schedule {data.schedule_id}")
        raise ValueError(f"Seat {seat_num} was just booked by another user. Please select a different seat.")

    db.refresh(booking)

    booking_result = BookingResult(
        booking_id=booking.id,
        passenger_name=passenger.name,
        origin=schedule.route.origin,
        destination=schedule.route.destination,
        departure_time=schedule.departure_time.strftime("%Y-%m-%d %H:%M"),
        seat_number=booking.seat_number,
        total_price=total,
        status=booking.status,
        payment_deadline=payment_deadline.strftime("%Y-%m-%d %H:%M:%S"),
        payment_reference=payment_reference,
    )

    # Get active bank account from database
    bank_account = db.query(BankAccount).filter(BankAccount.is_active == 1).first()

    if bank_account:
        payment_info = PaymentInfo(
            bank_name=bank_account.bank_name,
            account_number=bank_account.account_number,
            account_holder=bank_account.account_holder,
            reference=payment_reference,
            amount=total,
        )
        # Template message with bank account details
        message = f"""Booking confirmed! Please complete payment within {PAYMENT_DEADLINE_MINUTES} minutes.

Transfer Details:
Bank: {bank_account.bank_name}
Account Number: {bank_account.account_number}
Account Name: {bank_account.account_holder}
Amount: RM {total:.2f}
Reference: {payment_reference}

IMPORTANT: Include the reference number "{payment_reference}" in your transfer notes.

Payment Deadline: {payment_deadline.strftime('%Y-%m-%d %H:%M:%S')}

After transfer, please upload your receipt for verification."""
    else:
        # Fallback if no bank account configured
        payment_info = PaymentInfo(
            reference=payment_reference,
            amount=total,
        )
        message = f"Booking confirmed! Amount: RM {total:.2f}. Reference: {payment_reference}. Please contact admin for payment details."

    return BookingWithPaymentInfo(
        booking=booking_result,
        payment_info=payment_info,
        message=message
    )


# ── Check Booking ──────────────────────────────────────────────────────────────

def get_booking(db: Session, booking_id: int) -> Optional[BookingResult]:
    booking = db.query(Booking).filter(Booking.id == booking_id).first()
    if not booking:
        return None
    return BookingResult(
        booking_id=booking.id,
        passenger_name=booking.passenger.name,
        origin=booking.schedule.route.origin,
        destination=booking.schedule.route.destination,
        departure_time=booking.schedule.departure_time.strftime("%Y-%m-%d %H:%M"),
        seat_number=booking.seat_number or "-",
        total_price=booking.total_price,
        status=booking.status,
        booked_at=booking.booked_at.strftime("%Y-%m-%d %H:%M:%S") if booking.booked_at else None,
        payment_deadline=booking.payment_deadline.strftime("%Y-%m-%d %H:%M:%S") if booking.payment_deadline else None,
        payment_reference=booking.payment_reference,
    )


# ── Cancel Booking ─────────────────────────────────────────────────────────────

def cancel_booking(db: Session, booking_id: int) -> bool:
    booking = db.query(Booking).filter(Booking.id == booking_id).first()
    if not booking:
        return False
    if booking.status == "cancelled":
        return False

    booking.status = "cancelled"
    # Return seats back (calculate from total_price / ticket price)
    num_seats = max(1, round(booking.total_price / booking.schedule.price)) if booking.schedule.price else 1
    booking.schedule.available_seats += num_seats
    db.commit()
    return True


# ── Database Summary (for agent context) ──────────────────────────────────────

def get_db_summary(db: Session) -> dict:
    """Get summary of database for agent context."""
    from sqlalchemy import func
    now = datetime.now()

    # Count active upcoming schedules
    total_schedules = db.query(Schedule).filter(
        Schedule.status == "active",
        Schedule.departure_time >= now
    ).count()

    # Total available seats across all upcoming schedules
    total_seats = db.query(func.sum(Schedule.available_seats)).filter(
        Schedule.status == "active",
        Schedule.departure_time >= now
    ).scalar() or 0

    # Get schedule summary by route — only include routes with upcoming active schedules
    routes = db.query(Route).all()
    schedule_summary = []
    active_routes = []
    for route in routes:
        schedules = db.query(Schedule).filter(
            Schedule.route_id == route.id,
            Schedule.status == "active",
            Schedule.departure_time >= now
        ).all()
        if schedules:
            total_route_seats = sum(s.available_seats for s in schedules)
            route_name = f"{route.origin} → {route.destination}"
            active_routes.append(route_name)
            schedule_summary.append({
                "route": route_name,
                "num_schedules": len(schedules),
                "total_seats": total_route_seats,
            })

    return {
        "routes": active_routes,
        "total_routes": len(active_routes),
        "total_schedules": total_schedules,
        "total_available_seats": total_seats,
        "schedule_by_route": schedule_summary,
    }


def get_route_schedules(db: Session, origin: str = None, destination: str = None, travel_date: Optional[str] = None) -> list:
    """Get upcoming schedules, optionally filtered by route and date."""
    now = datetime.now()

    query = (
        db.query(Schedule)
        .join(Route)
        .join(Bus)
        .filter(
            Schedule.status == "active",
            Schedule.departure_time >= now
        )
    )

    # Normalize city names for better matching
    if origin:
        norm_origin = normalize_city(origin)
        query = query.filter(Route.origin.ilike(f"%{norm_origin}%"))
    if destination:
        norm_dest = normalize_city(destination)
        query = query.filter(Route.destination.ilike(f"%{norm_dest}%"))

    # Filter by date if provided
    if travel_date:
        d = resolve_date(travel_date)
        if d:
            query = query.filter(
                and_(
                    Schedule.departure_time >= datetime.combine(d, datetime.min.time()),
                    Schedule.departure_time <= datetime.combine(d, datetime.max.time())
                )
            )

    schedules = query.order_by(Schedule.departure_time).limit(10).all()

    return [
        {
            "route": f"{s.route.origin} → {s.route.destination}",
            "departure": s.departure_time.strftime("%Y-%m-%d %H:%M"),
            "price": f"RM {s.price:.2f}",
            "available_seats": s.available_seats,
            "bus_type": s.bus.bus_type,
        }
        for s in schedules
    ]


# ── Bank Account Functions ─────────────────────────────────────────────────────

def get_active_bank_account(db: Session) -> Optional[dict]:
    """Get the active bank account for payments."""
    account = db.query(BankAccount).filter(BankAccount.is_active == 1).first()
    if not account:
        return None
    return {
        "bank_name": account.bank_name,
        "account_number": account.account_number,
        "account_holder": account.account_holder,
    }


# ── Payment Receipt Functions ─────────────────────────────────────────────────

def save_receipt(db: Session, booking_id: int, image_path: str) -> PaymentReceipt:
    """Save uploaded receipt image for a booking."""
    booking = db.query(Booking).filter(Booking.id == booking_id).first()
    if not booking:
        raise ValueError(f"Booking {booking_id} not found.")
    if booking.status != "pending_payment":
        raise ValueError(f"Booking {booking_id} is not pending payment (status: {booking.status}).")

    # Check if receipt already exists
    existing = db.query(PaymentReceipt).filter(PaymentReceipt.booking_id == booking_id).first()
    if existing:
        # Update existing receipt
        existing.image_path = image_path
        existing.uploaded_at = datetime.now()
        existing.verification_status = "pending"
        existing.verification_result = None
        existing.verified_at = None
        db.commit()
        db.refresh(existing)
        return existing

    # Create new receipt
    receipt = PaymentReceipt(
        booking_id=booking_id,
        image_path=image_path,
        verification_status="pending",
    )
    db.add(receipt)
    db.commit()
    db.refresh(receipt)
    return receipt


def update_receipt_status(db: Session, booking_id: int, is_valid: bool, reason: str,
                          verified_amount: float = None, verified_reference: str = None) -> dict:
    """Update receipt verification status and booking status."""
    receipt = db.query(PaymentReceipt).filter(PaymentReceipt.booking_id == booking_id).first()
    if not receipt:
        raise ValueError(f"No receipt found for booking {booking_id}.")

    booking = receipt.booking

    if is_valid:
        receipt.verification_status = "verified"
        receipt.verification_result = reason
        receipt.verified_at = datetime.now()
        booking.status = "confirmed"
        message = "Payment verified! Your booking is confirmed."
    else:
        receipt.verification_status = "rejected"
        receipt.verification_result = reason
        receipt.verified_at = datetime.now()
        message = f"Payment verification failed: {reason}. Please upload a valid receipt."

    db.commit()

    return {
        "booking_id": booking_id,
        "status": receipt.verification_status,
        "booking_status": booking.status,
        "message": message,
        "verified_amount": verified_amount,
        "verified_reference": verified_reference,
    }


def cancel_expired_bookings(db: Session) -> List[int]:
    """Cancel all bookings past their payment deadline. Returns list of cancelled booking IDs."""
    now = datetime.now()

    expired_bookings = db.query(Booking).filter(
        Booking.status == "pending_payment",
        Booking.payment_deadline < now
    ).all()

    cancelled_ids = []
    for booking in expired_bookings:
        booking.status = "cancelled"
        # Return seats back to schedule
        num_seats = max(1, round(booking.total_price / booking.schedule.price)) if booking.schedule.price else 1
        booking.schedule.available_seats += num_seats
        cancelled_ids.append(booking.id)

    if cancelled_ids:
        db.commit()
        logger.info(f"[Scheduler] Cancelled {len(cancelled_ids)} expired bookings: {cancelled_ids}")

    return cancelled_ids


def get_pending_payment_bookings(db: Session) -> List[Booking]:
    """Get all bookings waiting for payment."""
    return db.query(Booking).filter(Booking.status == "pending_payment").all()


def get_booking_payment_info(db: Session, booking_id: int) -> Optional[dict]:
    """Get booking + bank account details for payment instructions.

    Returns a dict with all template fields, or None if booking not found
    or not in pending_payment status.
    """
    booking = db.query(Booking).filter(Booking.id == booking_id).first()
    if not booking or booking.status != "pending_payment":
        return None

    bank_account = db.query(BankAccount).filter(BankAccount.is_active == 1).first()
    if not bank_account:
        return None

    schedule = booking.schedule
    route = schedule.route

    return {
        "booking_id": booking.id,
        "origin": route.origin,
        "destination": route.destination,
        "departure_time": schedule.departure_time.strftime("%Y-%m-%d %H:%M"),
        "seat_number": booking.seat_number or "-",
        "bank_name": bank_account.bank_name,
        "account_number": bank_account.account_number,
        "account_holder": bank_account.account_holder,
        "amount": booking.total_price,
        "payment_reference": booking.payment_reference,
        "payment_deadline": booking.payment_deadline.strftime("%Y-%m-%d %H:%M:%S") if booking.payment_deadline else "N/A",
        "status": booking.status,
    }