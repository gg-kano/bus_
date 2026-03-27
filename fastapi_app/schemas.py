from pydantic import BaseModel
from typing import Optional


# ── Chat ───────────────────────────────────────────────────────────────────────

class ChatMessage(BaseModel):
    message: str
    session_id: Optional[str] = None
    passenger_id: Optional[int] = None


# ── Auth ──────────────────────────────────────────────────────────────────────

class LoginRequest(BaseModel):
    name: str
    phone: str


class PassengerInfo(BaseModel):
    id: int
    name: str
    phone: str
    email: Optional[str] = None
    is_new: bool = False


class ChatResponse(BaseModel):
    reply: str
    session_id: str


# ── Schedule ───────────────────────────────────────────────────────────────────

class ScheduleResult(BaseModel):
    id: int
    origin: str
    destination: str
    departure_time: str
    arrival_time: str
    price: float
    available_seats: int
    bus_type: Optional[str] = None
    plate_number: Optional[str] = None


# ── Booking ────────────────────────────────────────────────────────────────────

class BookingCreate(BaseModel):
    schedule_id: int
    passenger_name: str
    passenger_phone: str
    passenger_email: Optional[str] = None
    passenger_ic: Optional[str] = None
    num_passengers: int = 1
    seat_number: Optional[int] = None  # User-selected seat number


class BookingResult(BaseModel):
    booking_id: int
    passenger_name: str
    origin: str
    destination: str
    departure_time: str
    seat_number: str
    total_price: float
    status: str
    booked_at: Optional[str] = None
    payment_deadline: Optional[str] = None
    payment_reference: Optional[str] = None


# ── Payment ───────────────────────────────────────────────────────────────────

class PaymentInfo(BaseModel):
    """Bank account details for payment."""
    bank_name: str = "Maybank"
    account_number: str = "1234567890"
    account_holder: str = "Bus Booking Sdn Bhd"
    reference: str  # Booking ID as reference
    amount: float


class BookingWithPaymentInfo(BaseModel):
    """Booking result with payment instructions."""
    booking: BookingResult
    payment_info: PaymentInfo
    message: str


class ReceiptUpload(BaseModel):
    booking_id: int


class ReceiptVerificationResult(BaseModel):
    booking_id: int
    status: str  # verified / rejected / pending
    message: str
    verified_amount: Optional[float] = None
    verified_reference: Optional[str] = None


# ── Seat Selection ────────────────────────────────────────────────────────────

class SeatInfo(BaseModel):
    """Seat availability information for a schedule."""
    schedule_id: int
    total_seats: int
    seats_per_row: int
    seat_layout: str  # "2-2", "1-2", "2-1"
    occupied_seats: list[int]
    available_seats: list[int]
