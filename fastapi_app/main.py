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
import sys
import os
import shutil
import time
import logging
import contextvars
from pathlib import Path

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
from database import SessionLocal, init_db

from schemas import ChatMessage, ChatResponse, BookingCreate, ReceiptVerificationResult, BookingWithPaymentInfo, SeatInfo
from agent import chat, chat_stream, check_ollama, OLLAMA_MODEL
from vlm_service import extract_receipt_data, check_vlm, VLM_MODEL
from receipt_verifier import verify_receipt
from scheduler import payment_scheduler
from rag import init_faq_store, get_vector_store
import crud
from notifications import (
    send_booking_confirmation_sms,
    send_payment_verified_sms,
    send_cancellation_sms,
    log_booking_event,
)

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
        yield db
    finally:
        db.close()




# ══════════════════════════════════════════════════════════════════════════════
# CHAT ENDPOINT - Simple Q&A
# ══════════════════════════════════════════════════════════════════════════════

@app.post("/chat", response_model=ChatResponse)
@limiter.limit("30/minute")
async def chat_endpoint(request: Request, req: ChatMessage, db: Session = Depends(get_db)):
    """Simple chat endpoint - just Q&A with the agent."""

    session_id = req.session_id or str(uuid.uuid4())

    # Get conversation history for context (last few messages)
    history = sessions.get(session_id) or []
    history_context = "\n".join(history[-6:]) if history else ""

    # Build database context for the agent
    db_summary = crud.get_db_summary(db)
    db_context = f"""
DATABASE INFO:
- Available routes: {', '.join(db_summary['routes'][:10])}
- Total routes: {db_summary['total_routes']}
- Total upcoming schedules: {db_summary['total_schedules']}
- Total available seats: {db_summary['total_available_seats']}
"""

    # If user asks about specific route, add schedule details
    msg_lower = req.message.lower()
    # Check for city mentions
    cities = ["kuala lumpur", "kl", "penang", "johor bahru", "jb", "ipoh", "melaka",
              "kuantan", "kota bharu", "kuching", "kota kinabalu", "alor setar",
              "seremban", "taiping", "muar"]
    mentioned_cities = [c for c in cities if c in msg_lower]

    # Initialize schedules
    schedules = []

    if mentioned_cities or any(word in msg_lower for word in ["schedule", "seat", "bus", "available", "price", "harga", "berapa"]):
        # Get relevant schedules
        origin = mentioned_cities[0] if mentioned_cities else None
        dest = mentioned_cities[1] if len(mentioned_cities) > 1 else None
        schedules = crud.get_route_schedules(db, origin, dest)
        if schedules:
            schedule_info = "\n".join([
                f"  - {s['route']}: {s['departure']} | {s['price']} | {s['available_seats']} seats | {s['bus_type']}"
                for s in schedules[:5]
            ])
            db_context += f"\nUPCOMING SCHEDULES:\n{schedule_info}"
        else:
            db_context += f"\nNo schedules found for the requested route."

    # Combine all context
    context = f"{db_context}\n\nCONVERSATION HISTORY:\n{history_context}" if history_context else db_context

    # Build db_info dict for fallback responses
    db_info = {
        "summary": db_summary,
        "schedules": schedules if schedules else None,
    }

    # Debug logging (PII masked)
    logger.info(f"[Chat] User message: {mask_message(req.message)}")
    logger.debug(f"[Chat] Context length: {len(context)} chars")

    # Get agent response
    reply = await chat(req.message, context, db_info)
    logger.info(f"[Chat] Reply length: {len(reply)} chars")

    # Store in history (using TTLDict)
    history = sessions.get(session_id) or []
    history.append(f"User: {req.message}")
    history.append(f"Assistant: {reply}")
    # Keep history manageable (last 20 messages)
    if len(history) > 20:
        history = history[-20:]
    sessions.set(session_id, history)

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
    history = sessions.get(session_id) or []
    history_context = "\n".join(history[-6:]) if history else ""

    # Build database context (same as /chat)
    db_summary = crud.get_db_summary(db)
    db_context = f"""
DATABASE INFO:
- Available routes: {', '.join(db_summary['routes'][:10])}
- Total routes: {db_summary['total_routes']}
- Total upcoming schedules: {db_summary['total_schedules']}
- Total available seats: {db_summary['total_available_seats']}
"""
    context = f"{db_context}\n\nCONVERSATION HISTORY:\n{history_context}" if history_context else db_context

    async def event_stream():
        full_reply = ""
        async for token in chat_stream(req.message, context):
            full_reply += token
            yield f"data: {json.dumps({'type': 'token', 'text': token})}\n\n"

        # Store in history after streaming completes (using TTLDict)
        hist = sessions.get(session_id) or []
        hist.append(f"User: {req.message}")
        hist.append(f"Assistant: {full_reply}")
        if len(hist) > 20:
            hist = hist[-20:]
        sessions.set(session_id, hist)

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

        # Queue background notification tasks
        background_tasks.add_task(
            send_booking_confirmation_sms,
            phone=data.passenger_phone,
            booking_id=result.booking.id,
            passenger_name=data.passenger_name,
            origin=schedule.origin if schedule else "Unknown",
            destination=schedule.destination if schedule else "Unknown",
            departure_time=str(schedule.departure_time) if schedule else "Unknown",
            seat_number=result.booking.seat_number,
            amount=result.payment_info.amount,
            payment_reference=result.payment_info.reference
        )

        # Log booking event for analytics
        background_tasks.add_task(
            log_booking_event,
            event_type="booking_created",
            booking_id=result.booking.id,
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
def get_booking(booking_id: int, db: Session = Depends(get_db)):
    """Get booking by ID."""
    booking = crud.get_booking(db, booking_id)
    if not booking:
        raise HTTPException(status_code=404, detail="Booking not found")
    return booking


@app.delete("/bookings/{booking_id}")
def cancel_booking(
    booking_id: int,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db)
):
    """Cancel a booking."""
    # Get booking info before cancellation for notification
    booking = db.query(crud.Booking).filter(crud.Booking.id == booking_id).first()

    success = crud.cancel_booking(db, booking_id)
    if not success:
        raise HTTPException(status_code=404, detail="Booking not found or already cancelled")

    # Queue cancellation notification
    if booking:
        background_tasks.add_task(
            send_cancellation_sms,
            phone=booking.passenger_phone,
            booking_id=booking_id,
            passenger_name=booking.passenger_name,
            reason="User requested"
        )

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
        "recipient": extraction_result.recipient,
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
        # Get full booking details for notification
        booking_obj = db.query(crud.Booking).filter(crud.Booking.id == booking_id).first()
        schedule = db.query(crud.Schedule).filter(crud.Schedule.id == booking_obj.schedule_id).first() if booking_obj else None

        if booking_obj and schedule:
            background_tasks.add_task(
                send_payment_verified_sms,
                phone=booking_obj.passenger_phone,
                booking_id=booking_id,
                passenger_name=booking_obj.passenger_name,
                origin=schedule.origin,
                destination=schedule.destination,
                departure_time=str(schedule.departure_time),
                seat_number=booking_obj.seat_number
            )

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

    from database import PaymentReceipt, Booking as BookingModel
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
        raise HTTPException(status_code=503, detail=f"VLM model '{VLM_MODEL}' not available")
    return {"status": "ok", "model": VLM_MODEL}
