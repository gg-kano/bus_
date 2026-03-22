from sqlalchemy import create_engine, Column, Integer, String, Float, DateTime, ForeignKey, Text, Index, text
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, relationship
from datetime import datetime
import os

# ─── Config ───────────────────────────────────────────────────────────────────
# Change this to your actual PostgreSQL connection string
DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://postgres:password@localhost:5432/bus_booking"
)

engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


# ─── Models ───────────────────────────────────────────────────────────────────

class Bus(Base):
    __tablename__ = "buses"

    id = Column(Integer, primary_key=True, index=True)
    plate_number = Column(String(20), unique=True, nullable=False)
    bus_type = Column(String(50))          # e.g. Express, VIP, Economy
    total_seats = Column(Integer, nullable=False)
    seats_per_row = Column(Integer, default=4)        # 3 or 4 seats per row
    seat_layout = Column(String(10), default="2-2")   # "2-2", "1-2", "2-1"
    amenities = Column(Text)               # e.g. "WiFi, USB, AC"
    created_at = Column(DateTime, default=datetime.now)

    schedules = relationship("Schedule", back_populates="bus")


class Route(Base):
    __tablename__ = "routes"

    id = Column(Integer, primary_key=True, index=True)
    origin = Column(String(100), nullable=False)
    destination = Column(String(100), nullable=False)
    estimated_cost = Column(Float)         # estimated cost (fuel, toll, etc.)
    duration_hours = Column(Float)         # estimated travel time
    created_at = Column(DateTime, default=datetime.now)

    schedules = relationship("Schedule", back_populates="route")


class Schedule(Base):
    __tablename__ = "schedules"

    id = Column(Integer, primary_key=True, index=True)
    route_id = Column(Integer, ForeignKey("routes.id"), nullable=False)
    bus_id = Column(Integer, ForeignKey("buses.id"), nullable=False)
    departure_time = Column(DateTime, nullable=False)
    arrival_time = Column(DateTime, nullable=False)
    price = Column(Float, nullable=False)
    available_seats = Column(Integer, nullable=False)
    status = Column(String(20), default="active")  # active / cancelled / full
    created_at = Column(DateTime, default=datetime.now)

    route = relationship("Route", back_populates="schedules")
    bus = relationship("Bus", back_populates="schedules")
    bookings = relationship("Booking", back_populates="schedule")


class Passenger(Base):
    __tablename__ = "passengers"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), nullable=False)
    phone = Column(String(20), nullable=False)
    email = Column(String(100))
    ic_number = Column(String(20))         # Malaysian IC
    created_at = Column(DateTime, default=datetime.now)

    bookings = relationship("Booking", back_populates="passenger")


class Booking(Base):
    __tablename__ = "bookings"
    __table_args__ = (
        # Partial unique index: prevent double-booking of same seat (only for non-cancelled bookings)
        Index(
            'ix_booking_schedule_seat_active',
            'schedule_id',
            'seat_number',
            unique=True,
            postgresql_where=text("status IN ('pending_payment', 'confirmed')")
        ),
    )

    id = Column(Integer, primary_key=True, index=True)
    passenger_id = Column(Integer, ForeignKey("passengers.id"), nullable=False)
    schedule_id = Column(Integer, ForeignKey("schedules.id"), nullable=False)
    seat_number = Column(String(10))
    payment_reference = Column(String(20), unique=True, nullable=True)  # Random 6-digit reference for payment
    status = Column(String(20), default="pending_payment")  # pending_payment / confirmed / cancelled
    total_price = Column(Float, nullable=False)
    booked_at = Column(DateTime, default=datetime.now)
    payment_deadline = Column(DateTime, nullable=True)  # Auto-cancel after this time

    passenger = relationship("Passenger", back_populates="bookings")
    schedule = relationship("Schedule", back_populates="bookings")
    payment_receipt = relationship("PaymentReceipt", back_populates="booking", uselist=False)


class PaymentReceipt(Base):
    __tablename__ = "payment_receipts"

    id = Column(Integer, primary_key=True, index=True)
    booking_id = Column(Integer, ForeignKey("bookings.id"), nullable=False, unique=True)
    image_path = Column(String(500), nullable=False)  # Path to uploaded receipt image
    uploaded_at = Column(DateTime, default=datetime.now)
    verification_status = Column(String(20), default="pending")  # pending / verified / rejected
    verification_result = Column(Text, nullable=True)  # VLM response/reason
    verified_at = Column(DateTime, nullable=True)

    booking = relationship("Booking", back_populates="payment_receipt")


class BankAccount(Base):
    """Bank account for receiving payments. Managed by admin."""
    __tablename__ = "bank_accounts"

    id = Column(Integer, primary_key=True, index=True)
    bank_name = Column(String(100), nullable=False)
    account_number = Column(String(50), nullable=False)
    account_holder = Column(String(100), nullable=False)  # Recipient name to match on receipt
    is_active = Column(Integer, default=1)  # 1 = active, 0 = inactive
    created_at = Column(DateTime, default=datetime.now)


# ─── Init DB ──────────────────────────────────────────────────────────────────

def init_db():
    Base.metadata.create_all(bind=engine)
    print("✅ All tables created successfully.")


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


if __name__ == "__main__":
    init_db()