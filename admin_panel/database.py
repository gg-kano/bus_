from sqlalchemy import create_engine, Column, Integer, String, Float, DateTime, ForeignKey, Text, Index, text
from sqlalchemy.orm import declarative_base, sessionmaker, relationship
from datetime import datetime
import os

# ─── Config ───────────────────────────────────────────────────────────────────
# Change this to your actual PostgreSQL connection string
DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://postgres:password@localhost:5432/bus_booking"
)

engine = create_engine(
    DATABASE_URL,
    pool_pre_ping=True,        # Verify connections are alive before using
    pool_recycle=300,          # Recycle connections every 5 minutes
)
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
    payment_reference = Column(String(20), nullable=True)  # Fixed reference for payment
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
        db.expire_all()  # Ensure fresh reads
        yield db
    finally:
        db.rollback()
        db.close()


# ─── Dashboard Aggregation Functions ─────────────────────────────────────────

def get_dashboard_metrics(db) -> dict:
    """Calculate all KPI metrics for dashboard"""
    from sqlalchemy import func
    from datetime import timedelta

    now = datetime.now()
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    week_start = today_start - timedelta(days=today_start.weekday())
    month_start = today_start.replace(day=1)

    # Revenue metrics
    today_revenue = db.query(func.sum(Booking.total_price)).filter(
        Booking.status == 'confirmed',
        Booking.booked_at >= today_start
    ).scalar() or 0

    week_revenue = db.query(func.sum(Booking.total_price)).filter(
        Booking.status == 'confirmed',
        Booking.booked_at >= week_start
    ).scalar() or 0

    month_revenue = db.query(func.sum(Booking.total_price)).filter(
        Booking.status == 'confirmed',
        Booking.booked_at >= month_start
    ).scalar() or 0

    # Booking metrics
    today_bookings = db.query(Booking).filter(
        Booking.booked_at >= today_start
    ).count()

    pending_payments = db.query(Booking).filter(
        Booking.status == 'pending_payment'
    ).count()

    pending_amount = db.query(func.sum(Booking.total_price)).filter(
        Booking.status == 'pending_payment'
    ).scalar() or 0

    confirmed_today = db.query(Booking).filter(
        Booking.status == 'confirmed',
        Booking.booked_at >= today_start
    ).count()

    cancelled_today = db.query(Booking).filter(
        Booking.status == 'cancelled',
        Booking.booked_at >= today_start
    ).count()

    # Conversion rate
    total_bookings = db.query(Booking).count()
    total_confirmed = db.query(Booking).filter(Booking.status == 'confirmed').count()
    conversion_rate = (total_confirmed / total_bookings * 100) if total_bookings > 0 else 0

    # Average occupancy for upcoming schedules
    upcoming_schedules = db.query(Schedule).filter(Schedule.departure_time >= now).all()
    if upcoming_schedules:
        total_capacity = sum(s.bus.total_seats for s in upcoming_schedules)
        total_booked = sum(s.bus.total_seats - s.available_seats for s in upcoming_schedules)
        avg_occupancy = (total_booked / total_capacity * 100) if total_capacity > 0 else 0
    else:
        avg_occupancy = 0

    return {
        "today_revenue": today_revenue,
        "week_revenue": week_revenue,
        "month_revenue": month_revenue,
        "today_bookings": today_bookings,
        "pending_payments": pending_payments,
        "pending_amount": pending_amount,
        "confirmed_today": confirmed_today,
        "cancelled_today": cancelled_today,
        "conversion_rate": conversion_rate,
        "avg_occupancy": avg_occupancy,
    }


def get_booking_trends(db, days: int = 7) -> list:
    """Daily booking counts for trend chart"""
    from datetime import timedelta

    today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    results = []

    for i in range(days - 1, -1, -1):
        day_start = today - timedelta(days=i)
        day_end = day_start + timedelta(days=1)

        confirmed = db.query(Booking).filter(
            Booking.booked_at >= day_start,
            Booking.booked_at < day_end,
            Booking.status == 'confirmed'
        ).count()

        pending = db.query(Booking).filter(
            Booking.booked_at >= day_start,
            Booking.booked_at < day_end,
            Booking.status == 'pending_payment'
        ).count()

        cancelled = db.query(Booking).filter(
            Booking.booked_at >= day_start,
            Booking.booked_at < day_end,
            Booking.status == 'cancelled'
        ).count()

        results.append({
            "date": day_start.strftime("%Y-%m-%d"),
            "status": "confirmed",
            "count": confirmed
        })
        results.append({
            "date": day_start.strftime("%Y-%m-%d"),
            "status": "pending",
            "count": pending
        })
        results.append({
            "date": day_start.strftime("%Y-%m-%d"),
            "status": "cancelled",
            "count": cancelled
        })

    return results


def get_revenue_by_route(db) -> list:
    """Revenue breakdown by route"""
    from sqlalchemy import func

    results = db.query(
        Route.origin,
        Route.destination,
        func.sum(Booking.total_price).label('revenue'),
        func.count(Booking.id).label('bookings')
    ).join(Schedule, Schedule.route_id == Route.id
    ).join(Booking, Booking.schedule_id == Schedule.id
    ).filter(Booking.status == 'confirmed'
    ).group_by(Route.id, Route.origin, Route.destination
    ).order_by(func.sum(Booking.total_price).desc()
    ).limit(10).all()

    return [{
        "route": f"{r.origin} → {r.destination}",
        "revenue": float(r.revenue or 0),
        "bookings": r.bookings
    } for r in results]


def get_schedule_alerts(db) -> dict:
    """Urgent items requiring attention"""
    from datetime import timedelta

    now = datetime.now()
    two_hours_later = now + timedelta(hours=2)

    # Schedules departing in next 2 hours
    departing_soon = db.query(Schedule).filter(
        Schedule.departure_time >= now,
        Schedule.departure_time <= two_hours_later,
        Schedule.status == 'active'
    ).all()

    # Schedules with < 20% seats left (nearly full)
    upcoming = db.query(Schedule).filter(
        Schedule.departure_time >= now,
        Schedule.status == 'active'
    ).all()
    low_availability = [s for s in upcoming if s.bus.total_seats > 0 and (s.available_seats / s.bus.total_seats) < 0.2]

    # Upcoming schedules with 0 bookings
    no_bookings = []
    for s in upcoming:
        booking_count = db.query(Booking).filter(
            Booking.schedule_id == s.id,
            Booking.status.in_(['confirmed', 'pending_payment'])
        ).count()
        if booking_count == 0:
            no_bookings.append(s)

    # Payment receipts awaiting verification
    pending_verification = db.query(PaymentReceipt).filter(
        PaymentReceipt.verification_status == 'pending'
    ).all()

    return {
        "departing_soon": departing_soon,
        "low_availability": low_availability,
        "no_bookings": no_bookings,
        "pending_verification": pending_verification,
    }


def get_popular_routes(db, limit: int = 5) -> list:
    """Top routes by booking count"""
    from sqlalchemy import func

    results = db.query(
        Route.origin,
        Route.destination,
        func.count(Booking.id).label('booking_count')
    ).join(Schedule, Schedule.route_id == Route.id
    ).join(Booking, Booking.schedule_id == Schedule.id
    ).filter(Booking.status == 'confirmed'
    ).group_by(Route.id, Route.origin, Route.destination
    ).order_by(func.count(Booking.id).desc()
    ).limit(limit).all()

    return [{
        "route": f"{r.origin} → {r.destination}",
        "bookings": r.booking_count
    } for r in results]


def get_hourly_booking_distribution(db) -> list:
    """Booking counts by hour of day for pattern analysis"""
    from sqlalchemy import func, extract

    results = db.query(
        extract('hour', Booking.booked_at).label('hour'),
        func.count(Booking.id).label('count')
    ).group_by(extract('hour', Booking.booked_at)
    ).order_by(extract('hour', Booking.booked_at)).all()

    # Fill in missing hours with 0
    hour_counts = {int(r.hour): r.count for r in results}
    return [{"hour": h, "count": hour_counts.get(h, 0)} for h in range(24)]


if __name__ == "__main__":
    init_db()