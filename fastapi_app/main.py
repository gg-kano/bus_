from typing import Optional
from fastapi import FastAPI, Depends, HTTPException, UploadFile, File, Form, Request, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from contextlib import asynccontextmanager
from collections import OrderedDict
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
import uuid
import json
import random
import sys
import os
import shutil
import time
import logging
import re
import contextvars
from pathlib import Path
from datetime import datetime

# ── Structured Logging Setup ──────────────────────────────────────────────────

# Context variable for request correlation
request_id_var: contextvars.ContextVar[str] = contextvars.ContextVar('request_id', default='-')


class StructuredFormatter(logging.Formatter):
    """JSON formatter with correlation ID support."""

    def format(self, record):
        # Add request_id to all log records
        record.request_id = request_id_var.get('-')

        log_data = {
            "timestamp": self.formatTime(record, self.datefmt),
            "level": record.levelname,
            "logger": record.name,
            "request_id": record.request_id,
            "message": record.getMessage(),
        }

        # Add exception info if present
        if record.exc_info:
            log_data["exception"] = self.formatException(record.exc_info)

        return json.dumps(log_data)


def setup_logging():
    """Configure structured logging."""
    log_level = os.getenv("LOG_LEVEL", "INFO").upper()
    use_json = os.getenv("LOG_FORMAT", "text").lower() == "json"

    root_logger = logging.getLogger()
    root_logger.setLevel(getattr(logging, log_level, logging.INFO))

    # Remove existing handlers
    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)

    # Create console handler
    handler = logging.StreamHandler()

    if use_json:
        handler.setFormatter(StructuredFormatter())
    else:
        handler.setFormatter(logging.Formatter(
            '%(asctime)s [%(request_id)s] %(levelname)s %(name)s: %(message)s',
            defaults={'request_id': '-'}
        ))

    root_logger.addHandler(handler)


setup_logging()
logger = logging.getLogger(__name__)

# ── Rate Limiter ──────────────────────────────────────────────────────────────
limiter = Limiter(key_func=get_remote_address)


def mask_message(msg: str, max_len: int = 50) -> str:
    """Mask user message for logging - show only first/last chars."""
    if len(msg) <= 10:
        return "***"
    return f"{msg[:5]}...{msg[-5:]}" if len(msg) > max_len else f"{msg[:3]}...{msg[-3:]}"

sys.path.append(os.path.join(os.path.dirname(__file__), '..', 'admin_panel'))
from database import SessionLocal, init_db, PaymentReceipt, Booking as BookingModel

from schemas import ChatMessage, ChatResponse, BookingCreate, ReceiptVerificationResult, BookingWithPaymentInfo, SeatInfo, LoginRequest, PassengerInfo, BookingResult
from agent import chat, chat_stream, check_ollama, classify_intent, load_prompt, OLLAMA_MODEL, close_clients
from vlm_service import extract_receipt_data, check_vlm, close_vlm_clients
from receipt_verifier import verify_receipt
from scheduler import payment_scheduler
from rag import init_faq_store, get_vector_store
import crud
def log_booking_event(event_type: str, booking_id: int, details: dict) -> None:
    """Log booking events for analytics/audit purposes (background task)."""
    event = {
        "event_type": event_type,
        "booking_id": booking_id,
        "timestamp": datetime.now().isoformat(),
        **details
    }
    logger.info(f"[BookingEvent] {event}")


# Directory for uploaded receipts
UPLOAD_DIR = Path(os.getenv("UPLOAD_DIR", "/tmp/receipts"))
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan - startup and shutdown events."""
    # Startup
    init_db()
    logger.info("Database initialized")

    # Initialize FAQ vector store
    logger.info("Initializing FAQ vector store...")
    init_faq_store()
    logger.info("FAQ vector store ready")

    await payment_scheduler.start(SessionLocal)
    logger.info("Payment scheduler started")

    yield

    # Shutdown
    await payment_scheduler.stop()
    logger.info("Payment scheduler stopped")
    await close_clients()
    await close_vlm_clients()
    logger.info("HTTP clients closed")


app = FastAPI(title="Bus Booking API", version="1.0.0", lifespan=lifespan)


# ── Request ID Middleware ─────────────────────────────────────────────────────
@app.middleware("http")
async def add_request_id(request: Request, call_next):
    """Add correlation ID to each request for tracing."""
    # Use session_id if provided, otherwise generate a short request ID
    request_id = request.headers.get("X-Request-ID", str(uuid.uuid4())[:8])
    request_id_var.set(request_id)

    # Add request ID to response headers
    response = await call_next(request)
    response.headers["X-Request-ID"] = request_id
    return response

# ── CORS Middleware ───────────────────────────────────────────────────────────
# Configure allowed origins from environment variable (comma-separated)
ALLOWED_ORIGINS = os.getenv("ALLOWED_ORIGINS", "http://localhost:8501,http://streamlit:8501").split(",")

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE"],
    allow_headers=["*"],
)

# ── Rate Limiting ─────────────────────────────────────────────────────────────
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# ── In-memory session store with TTL ──────────────────────────────────────────

class TTLDict:
    """Simple LRU + TTL dict to prevent memory leaks."""

    def __init__(self, ttl: int = 1800, maxsize: int = 1000):
        self._store: OrderedDict = OrderedDict()
        self.ttl = ttl  # seconds (default 30 min)
        self.maxsize = maxsize

    def get(self, key: str, default=None):
        entry = self._store.get(key)
        if not entry:
            return default
        value, expires = entry
        if time.time() > expires:
            del self._store[key]
            return default
        return value

    def set(self, key: str, value):
        self._store[key] = (value, time.time() + self.ttl)
        self._store.move_to_end(key)
        # Evict oldest if over capacity
        while len(self._store) > self.maxsize:
            self._store.popitem(last=False)

    def __contains__(self, key: str) -> bool:
        return self.get(key) is not None


# Session store with 30-min TTL and max 1000 sessions
sessions = TTLDict(ttl=1800, maxsize=1000)


# ── DB Dependency ─────────────────────────────────────────────────────────────

def get_db():
    db = SessionLocal()
    try:
        # Expire all cached objects to ensure fresh reads from database
        db.expire_all()
        yield db
    finally:
        # Rollback any uncommitted transaction to release connection cleanly
        db.rollback()
        db.close()




# ── Canned Responses ──────────────────────────────────────────────────────────

GIBBERISH_RESPONSE = "Sorry, I didn't understand that. Could you rephrase your question? I can help with bus routes, schedules, bookings, and more!"

GREETING_RESPONSES = [
    "Hi there! I'm your bus booking assistant. How can I help you today? You can ask about routes, schedules, or make a booking!",
    "Hello! Welcome to our bus booking service. Feel free to ask about routes, prices, or use /search to find buses!",
    "Hey! I'm here to help with bus tickets in Malaysia. What would you like to know?",
]

# ── Payment Prompt Template ──────────────────────────────────────────────────
PAYMENT_PROMPT = load_prompt("payment_prompt.txt")

_BOOKING_ID_RE = re.compile(r'(?:booking\s*(?:no\.?|number|#)?\s*#?\s*(\d+))|(?:#(\d+))', re.IGNORECASE)


def extract_booking_id(message: str) -> int | None:
    """Extract a booking ID from a user message. Returns the first match or None."""
    m = _BOOKING_ID_RE.search(message)
    if m:
        return int(m.group(1) or m.group(2))
    return None


# ── Context Building ──────────────────────────────────────────────────────────

def build_db_context(db: Session, message: str) -> tuple[str, dict]:
    """Build database context and db_info for a user message. Returns (context_str, db_info)."""
    db_summary = crud.get_db_summary(db)

    origins = set()
    destinations = set()
    for route in db_summary.get('routes', []):
        if '\u2192' in route:
            parts = route.split('\u2192')
            origins.add(parts[0].strip())
            destinations.add(parts[1].strip())

    db_context = f"""
DATABASE INFO:
- Departure cities (origins): {', '.join(sorted(origins)) if origins else 'None'}
- Destination cities: {', '.join(sorted(destinations)) if destinations else 'None'}
- Available routes: {', '.join(db_summary['routes'][:10])}
- Total routes: {db_summary['total_routes']}
- Total upcoming schedules: {db_summary['total_schedules']}
- Total available seats: {db_summary['total_available_seats']}
"""

    msg_lower = message.lower()
    cities = ["kuala lumpur", "kl", "penang", "johor bahru", "jb", "ipoh", "melaka",
              "kuantan", "kota bharu", "kuching", "kota kinabalu", "alor setar",
              "seremban", "taiping", "muar", "shah alam", "subang jaya", "subang",
              "petaling jaya", "pj"]

    # Extract cities by order of appearance in the message (not list order)
    # This ensures "from Penang to KL" correctly assigns origin=Penang, dest=KL
    city_positions = []
    for city in cities:
        pos = msg_lower.find(city)
        if pos != -1:
            # Skip if this match is a substring of an already-found longer city
            # e.g. don't match "kl" if "kuala lumpur" was already found at an overlapping position
            is_substring = False
            for existing_city, existing_pos in city_positions:
                if pos >= existing_pos and pos + len(city) <= existing_pos + len(existing_city):
                    is_substring = True
                    break
            if not is_substring:
                # Remove any shorter city that is a substring of this one
                city_positions = [
                    (ec, ep) for ec, ep in city_positions
                    if not (ep >= pos and ep + len(ec) <= pos + len(city))
                ]
                city_positions.append((city, pos))

    # Sort by position in message to respect user's "from X to Y" order
    city_positions.sort(key=lambda x: x[1])
    mentioned_cities = [city for city, _ in city_positions]

    # Extract date hints from the message for schedule filtering
    date_hint = None
    date_keywords = ["today", "tomorrow", "tonight", "esok", "hari ini", "malam ini",
                     "next week", "minggu depan"]
    for kw in date_keywords:
        if kw in msg_lower:
            date_hint = kw
            break
    if not date_hint:
        # Try to find date patterns like "26 march", "2026-03-27", "27/3"
        date_match = re.search(r'\d{4}-\d{2}-\d{2}|\d{1,2}[/-]\d{1,2}(?:[/-]\d{2,4})?|\d{1,2}\s+(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)\w*', msg_lower)
        if date_match:
            date_hint = date_match.group(0)

    schedules = []
    if mentioned_cities or any(word in msg_lower for word in ["schedule", "seat", "bus", "available", "price", "harga", "berapa"]):
        origin = mentioned_cities[0] if mentioned_cities else None
        dest = mentioned_cities[1] if len(mentioned_cities) > 1 else None
        schedules = crud.get_route_schedules(db, origin, dest, travel_date=date_hint)
        if schedules:
            schedule_info = "\n".join([
                f"  - {s['route']}: {s['departure']} | {s['price']} | {s['available_seats']} seats | {s['bus_type']}"
                for s in schedules[:10]
            ])
            db_context += f"\nUPCOMING SCHEDULES:\n{schedule_info}"
        else:
            db_context += f"\nNo schedules found for the requested route."

    db_info = {
        "summary": db_summary,
        "schedules": schedules if schedules else None,
    }

    return db_context, db_info


def build_user_context(db: Session, passenger_id: int) -> str:
    """Build personalized user context for the LLM."""
    from database import Passenger as PassengerModel
    passenger = db.query(PassengerModel).filter(PassengerModel.id == passenger_id).first()
    if not passenger:
        return ""

    ctx = f"\nUSER INFO:\n- Name: {passenger.name}\n- Phone: {passenger.phone}\n"

    bookings = crud.get_bookings_by_passenger(db, passenger_id)
    active = [b for b in bookings if b.status in ("pending_payment", "confirmed")]
    if active:
        lines = []
        for b in active[:5]:
            lines.append(f"  - Booking #{b.booking_id}: {b.origin} → {b.destination} on {b.departure_time} (Seat {b.seat_number}, {b.status})")
        ctx += f"\nUSER'S ACTIVE BOOKINGS:\n" + "\n".join(lines) + "\n"

    return ctx


# ══════════════════════════════════════════════════════════════════════════════
# AUTH ENDPOINTS
# ══════════════════════════════════════════════════════════════════════════════

@app.post("/auth/login", response_model=PassengerInfo)
@limiter.limit("20/minute")
def login(request: Request, req: LoginRequest, db: Session = Depends(get_db)):
    """Login or register a passenger by phone number."""
    passenger_info, is_new = crud.get_or_create_passenger(db, req.name, req.phone)
    passenger_info.is_new = is_new
    return passenger_info


@app.get("/passengers/{passenger_id}/bookings", response_model=list[BookingResult])
def get_passenger_bookings(passenger_id: int, db: Session = Depends(get_db)):
    """Get all bookings for a passenger."""
    return crud.get_bookings_by_passenger(db, passenger_id)


# ── Session Helpers ───────────────────────────────────────────────────────────

def _get_session(session_id: str) -> dict:
    """Get session data dict, migrating old list format if needed."""
    data = sessions.get(session_id)
    if data is None:
        return {"history": [], "passenger_id": None}
    if isinstance(data, list):
        # Migrate old format
        return {"history": data, "passenger_id": None}
    return data


def _get_history(session_id: str) -> list:
    return _get_session(session_id)["history"]


def _save_history(session_id: str, history: list, passenger_id: int | None = None):
    if len(history) > 20:
        history = history[-20:]
    session = _get_session(session_id)
    session["history"] = history
    if passenger_id is not None:
        session["passenger_id"] = passenger_id
    sessions.set(session_id, session)


# ══════════════════════════════════════════════════════════════════════════════
# CHAT ENDPOINT - Simple Q&A
# ══════════════════════════════════════════════════════════════════════════════

@app.post("/chat", response_model=ChatResponse)
@limiter.limit("30/minute")
async def chat_endpoint(request: Request, req: ChatMessage, db: Session = Depends(get_db)):
    """Simple chat endpoint - just Q&A with the agent."""

    session_id = req.session_id or str(uuid.uuid4())

    # Debug logging (PII masked)
    logger.info(f"[Chat] User message: {mask_message(req.message)}")

    # ── Intent classification ────────────────────────────────────────────────
    intent = await classify_intent(req.message)
    logger.info(f"[Chat] Intent: {intent}")

    # ── Fast-path: gibberish / greeting → canned response, no LLM call ──────
    if intent == "gibberish":
        return ChatResponse(reply=GIBBERISH_RESPONSE, session_id=session_id)

    if intent == "greeting":
        reply = random.choice(GREETING_RESPONSES)
        history = _get_history(session_id)
        history.append(f"User: {req.message}")
        history.append(f"Assistant: {reply}")
        _save_history(session_id, history, req.passenger_id)
        return ChatResponse(reply=reply, session_id=session_id)

    # ── Build context based on intent ────────────────────────────────────────
    history = _get_history(session_id)
    history_context = "\n".join(history[-6:]) if history else ""

    db_info = None

    if intent == "faq":
        context = f"CONVERSATION HISTORY:\n{history_context}" if history_context else ""
    else:
        db_context, db_info = build_db_context(db, req.message)
        context = f"{db_context}\n\nCONVERSATION HISTORY:\n{history_context}" if history_context else db_context

    # ── Inject user context for logged-in users ──────────────────────────
    if req.passenger_id:
        user_ctx = build_user_context(db, req.passenger_id)
        if user_ctx:
            context = f"{user_ctx}\n{context}"

    # ── Inject payment instructions for booking intent ────────────────────
    if intent == "booking":
        bid = extract_booking_id(req.message)
        if bid:
            payment_info = crud.get_booking_payment_info(db, bid)
            if payment_info:
                payment_context = PAYMENT_PROMPT.format(**payment_info)
                context = f"{payment_context}\n\n{context}"

    logger.debug(f"[Chat] Context length: {len(context)} chars")

    # Get agent response
    reply = await chat(req.message, context, db_info)
    logger.info(f"[Chat] Reply length: {len(reply)} chars")

    # Store in history
    history = _get_history(session_id)
    history.append(f"User: {req.message}")
    history.append(f"Assistant: {reply}")
    _save_history(session_id, history, req.passenger_id)

    return ChatResponse(
        reply=reply,
        session_id=session_id
    )


# ══════════════════════════════════════════════════════════════════════════════
# STREAMING CHAT ENDPOINT
# ══════════════════════════════════════════════════════════════════════════════

@app.post("/chat/stream")
async def chat_stream_endpoint(req: ChatMessage, db: Session = Depends(get_db)):
    """Streaming chat endpoint - returns SSE tokens."""

    session_id = req.session_id or str(uuid.uuid4())

    # ── Intent classification ────────────────────────────────────────────────
    intent = await classify_intent(req.message)
    logger.info(f"[ChatStream] Intent: {intent}")

    # ── Fast-path: gibberish / greeting → emit canned response as single token
    if intent in ("gibberish", "greeting"):
        if intent == "gibberish":
            canned = GIBBERISH_RESPONSE
        else:
            import random
            canned = random.choice(GREETING_RESPONSES)

        async def canned_stream():
            yield f"data: {json.dumps({'type': 'meta', 'session_id': session_id})}\n\n"
            yield f"data: {json.dumps({'type': 'token', 'text': canned})}\n\n"
            hist = _get_history(session_id)
            hist.append(f"User: {req.message}")
            hist.append(f"Assistant: {canned}")
            _save_history(session_id, hist, req.passenger_id)
            yield "data: [DONE]\n\n"

        return StreamingResponse(canned_stream(), media_type="text/event-stream")

    # ── Build context based on intent ────────────────────────────────────────
    history = _get_history(session_id)
    history_context = "\n".join(history[-6:]) if history else ""

    if intent == "faq":
        context = f"CONVERSATION HISTORY:\n{history_context}" if history_context else ""
    else:
        db_context, _ = build_db_context(db, req.message)
        context = f"{db_context}\n\nCONVERSATION HISTORY:\n{history_context}" if history_context else db_context

    # ── Inject user context for logged-in users ──────────────────────────
    if req.passenger_id:
        user_ctx = build_user_context(db, req.passenger_id)
        if user_ctx:
            context = f"{user_ctx}\n{context}"

    # ── Inject payment instructions for booking intent ────────────────────
    if intent == "booking":
        bid = extract_booking_id(req.message)
        if bid:
            payment_info = crud.get_booking_payment_info(db, bid)
            if payment_info:
                payment_context = PAYMENT_PROMPT.format(**payment_info)
                context = f"{payment_context}\n\n{context}"

    async def event_stream():
        yield f"data: {json.dumps({'type': 'meta', 'session_id': session_id})}\n\n"
        full_reply = ""
        async for token in chat_stream(req.message, context):
            full_reply += token
            yield f"data: {json.dumps({'type': 'token', 'text': token})}\n\n"

        hist = _get_history(session_id)
        hist.append(f"User: {req.message}")
        hist.append(f"Assistant: {full_reply}")
        _save_history(session_id, hist, req.passenger_id)

        yield "data: [DONE]\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")


# ══════════════════════════════════════════════════════════════════════════════
# REST ENDPOINTS (for sidebar actions)
# ══════════════════════════════════════════════════════════════════════════════

@app.get("/schedules")
def search_schedules(
    origin: str,
    destination: str,
    date: str = None,
    db: Session = Depends(get_db)
):
    """Search for bus schedules."""
    return crud.search_schedules(db, origin, destination, date)


@app.get("/schedules/{schedule_id}/seats", response_model=SeatInfo)
def get_seat_info(schedule_id: int, db: Session = Depends(get_db)):
    """
    Get seat availability for a schedule.

    Returns:
        - total_seats: Total seats on the bus
        - seats_per_row: Number of seats per row (3 or 4)
        - seat_layout: Layout pattern ("2-2", "1-2", "2-1")
        - occupied_seats: List of seat numbers already booked
        - available_seats: List of seat numbers still available
    """
    try:
        return crud.get_occupied_seats(db, schedule_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@app.post("/bookings", response_model=BookingWithPaymentInfo)
@limiter.limit("10/minute")
def create_booking(
    request: Request,
    data: BookingCreate,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db)
):
    """
    Create a new booking.

    Returns booking details with payment instructions.
    User must upload receipt within 10 minutes or booking will be auto-cancelled.
    """
    try:
        result = crud.create_booking(db, data)

        # Get schedule info for notification
        schedule = db.query(crud.Schedule).filter(crud.Schedule.id == data.schedule_id).first()

        # Log booking event for analytics
        background_tasks.add_task(
            log_booking_event,
            event_type="booking_created",
            booking_id=result.booking.booking_id,
            details={
                "schedule_id": data.schedule_id,
                "num_passengers": data.num_passengers,
                "seat_number": data.seat_number,
            }
        )

        return result
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/bookings/{booking_id}")
def get_booking(booking_id: int, passenger_id: Optional[int] = None, db: Session = Depends(get_db)):
    """Get booking by ID. Optional passenger_id for ownership check."""
    booking_row = db.query(crud.Booking).filter(crud.Booking.id == booking_id).first()
    if not booking_row:
        raise HTTPException(status_code=404, detail="Booking not found")
    if passenger_id and booking_row.passenger_id != passenger_id:
        raise HTTPException(status_code=403, detail="This booking belongs to another passenger")
    booking = crud.get_booking(db, booking_id)
    return booking


@app.delete("/bookings/{booking_id}")
def cancel_booking(
    booking_id: int,
    background_tasks: BackgroundTasks,
    passenger_id: Optional[int] = None,
    db: Session = Depends(get_db)
):
    """Cancel a booking. Optional passenger_id for ownership check."""
    booking = db.query(crud.Booking).filter(crud.Booking.id == booking_id).first()
    if not booking:
        raise HTTPException(status_code=404, detail="Booking not found or already cancelled")
    if passenger_id and booking.passenger_id != passenger_id:
        raise HTTPException(status_code=403, detail="This booking belongs to another passenger")

    success = crud.cancel_booking(db, booking_id)
    if not success:
        raise HTTPException(status_code=404, detail="Booking not found or already cancelled")

    background_tasks.add_task(
        log_booking_event,
        event_type="booking_cancelled",
        booking_id=booking_id,
        details={"reason": "user_requested"}
    )

    return {"message": f"Booking #{booking_id} cancelled."}


# ══════════════════════════════════════════════════════════════════════════════
# PAYMENT VERIFICATION ENDPOINTS
# ══════════════════════════════════════════════════════════════════════════════

@app.post("/bookings/{booking_id}/receipt")
@limiter.limit("5/minute")
async def upload_receipt(
    request: Request,
    booking_id: int,
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    db: Session = Depends(get_db)
):
    """
    Upload payment receipt for a booking.

    This endpoint:
    1. Saves the uploaded receipt image
    2. Sends it to VLM for verification
    3. Updates booking status based on verification result
    """
    # Validate booking exists and is pending payment
    booking = crud.get_booking(db, booking_id)
    if not booking:
        raise HTTPException(status_code=404, detail="Booking not found")
    if booking.status != "pending_payment":
        raise HTTPException(
            status_code=400,
            detail=f"Booking is not pending payment (status: {booking.status})"
        )

    # Validate file type
    allowed_types = ["image/jpeg", "image/png", "image/webp"]
    if file.content_type not in allowed_types:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid file type. Allowed: {allowed_types}"
        )

    # Save file
    ext = file.filename.split(".")[-1] if "." in file.filename else "jpg"
    filename = f"receipt_{booking_id}_{uuid.uuid4().hex[:8]}.{ext}"
    file_path = UPLOAD_DIR / filename

    with open(file_path, "wb") as f:
        shutil.copyfileobj(file.file, f)

    # Save receipt record
    try:
        receipt = crud.save_receipt(db, booking_id, str(file_path))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    # Step 1: Extract data from receipt using VLM
    extraction_result = await extract_receipt_data(image_path=str(file_path))

    if not extraction_result.success:
        # VLM failed to extract data
        result = crud.update_receipt_status(
            db=db,
            booking_id=booking_id,
            is_valid=False,
            reason=f"Failed to extract receipt data: {extraction_result.error}"
        )
        return ReceiptVerificationResult(
            booking_id=booking_id,
            status="rejected",
            message=f"Failed to read receipt: {extraction_result.error}",
            verified_amount=None,
            verified_reference=None
        )

    # Step 2: Verify extracted data against database
    extracted_data = {
        "amount_found": extraction_result.amount_found,
        "recipient_account": extraction_result.recipient_account,
        "reference_found": extraction_result.reference_found,
        "transaction_time": extraction_result.transaction_time,
    }

    verification_result = verify_receipt(
        db=db,
        extracted_data=extracted_data,
        booking_id=booking_id
    )

    # Step 3: Update booking based on verification
    result = crud.update_receipt_status(
        db=db,
        booking_id=booking_id,
        is_valid=verification_result.is_valid,
        reason=verification_result.reason,
        verified_amount=extraction_result.amount_found,
        verified_reference=extraction_result.reference_found
    )

    # Send payment verified notification if successful
    if result["status"] == "confirmed":
        background_tasks.add_task(
            log_booking_event,
            event_type="payment_verified",
            booking_id=booking_id,
            details={
                "verified_amount": extraction_result.amount_found,
                "verified_reference": extraction_result.reference_found
            }
        )
    else:
        background_tasks.add_task(
            log_booking_event,
            event_type="payment_rejected",
            booking_id=booking_id,
            details={"reason": verification_result.reason}
        )

    return ReceiptVerificationResult(
        booking_id=booking_id,
        status=result["status"],
        message=result["message"],
        verified_amount=extraction_result.amount_found,
        verified_reference=extraction_result.reference_found
    )


@app.get("/bookings/{booking_id}/payment-status")
def get_payment_status(booking_id: int, db: Session = Depends(get_db)):
    """Get payment status for a booking."""
    booking = crud.get_booking(db, booking_id)
    if not booking:
        raise HTTPException(status_code=404, detail="Booking not found")

    receipt = db.query(PaymentReceipt).filter(
        PaymentReceipt.booking_id == booking_id
    ).first()

    return {
        "booking_id": booking_id,
        "booking_status": booking.status,
        "payment_deadline": booking.payment_deadline,
        "receipt_uploaded": receipt is not None,
        "receipt_status": receipt.verification_status if receipt else None,
        "receipt_result": receipt.verification_result if receipt else None,
    }


# ══════════════════════════════════════════════════════════════════════════════
# HEALTH ENDPOINTS
# ══════════════════════════════════════════════════════════════════════════════

@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/routes")
def list_routes(db: Session = Depends(get_db)):
    """List all available routes (for debugging)."""
    summary = crud.get_db_summary(db)
    return {
        "routes": summary["routes"],
        "total_routes": summary["total_routes"],
        "total_schedules": summary["total_schedules"],
        "total_available_seats": summary["total_available_seats"],
        "schedule_by_route": summary["schedule_by_route"],
    }


@app.get("/health/ollama")
async def ollama_health():
    ok = await check_ollama()
    if not ok:
        raise HTTPException(status_code=503, detail=f"Ollama model '{OLLAMA_MODEL}' not available")
    return {"status": "ok", "model": OLLAMA_MODEL}


@app.post("/faq/reload")
def reload_faq():
    """Reload FAQ embeddings (call after updating faq.json)."""
    try:
        store = get_vector_store()
        store.reload()
        return {"status": "ok", "message": "FAQ embeddings reloaded successfully"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to reload FAQ: {str(e)}")


@app.get("/health/vlm")
async def vlm_health():
    """Check VLM service health."""
    ok = await check_vlm()
    if not ok:
        raise HTTPException(status_code=503, detail=f"VLM model '{OLLAMA_MODEL}' not available")
    return {"status": "ok", "model": OLLAMA_MODEL}
