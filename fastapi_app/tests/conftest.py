"""
Pytest fixtures for Bus Booking Agent tests.
"""

import pytest
import sys
import os
from datetime import datetime, timedelta
from typing import Generator

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), '..', 'admin_panel'))

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.pool import StaticPool

from database import Base, Route, Schedule, Bus, Passenger, Booking, BankAccount
from main import app, get_db


# ── Test Database Setup ───────────────────────────────────────────────────────

# Use in-memory SQLite for tests
TEST_DATABASE_URL = "sqlite:///:memory:"

engine = create_engine(
    TEST_DATABASE_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def override_get_db():
    """Override database dependency for tests."""
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture(scope="function")
def db() -> Generator[Session, None, None]:
    """Create a fresh database for each test."""
    # Create tables
    Base.metadata.create_all(bind=engine)

    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()
        # Drop all tables after test
        Base.metadata.drop_all(bind=engine)


@pytest.fixture(scope="function")
def client(db: Session) -> Generator[TestClient, None, None]:
    """Create a test client with database override."""
    app.dependency_overrides[get_db] = lambda: db

    with TestClient(app) as test_client:
        yield test_client

    app.dependency_overrides.clear()


@pytest.fixture
def sample_bus(db: Session) -> Bus:
    """Create a sample bus."""
    bus = Bus(
        plate_number="WKL1234",
        bus_type="Express",
        total_seats=40,
        seats_per_row=4,
        seat_layout="2-2",
        amenities="WiFi, USB, AC"
    )
    db.add(bus)
    db.commit()
    db.refresh(bus)
    return bus


@pytest.fixture
def sample_route(db: Session) -> Route:
    """Create a sample route."""
    route = Route(
        origin="Kuala Lumpur",
        destination="Penang",
        estimated_cost=150.0,
        duration_hours=4.5
    )
    db.add(route)
    db.commit()
    db.refresh(route)
    return route


@pytest.fixture
def sample_schedule(db: Session, sample_bus: Bus, sample_route: Route) -> Schedule:
    """Create a sample schedule."""
    departure = datetime.now() + timedelta(days=1)
    arrival = departure + timedelta(hours=4, minutes=30)

    schedule = Schedule(
        route_id=sample_route.id,
        bus_id=sample_bus.id,
        departure_time=departure,
        arrival_time=arrival,
        price=35.00,
        available_seats=40,
        status="active"
    )
    db.add(schedule)
    db.commit()
    db.refresh(schedule)
    return schedule


@pytest.fixture
def sample_passenger(db: Session) -> Passenger:
    """Create a sample passenger."""
    passenger = Passenger(
        name="Ahmad bin Ali",
        phone="0123456789",
        email="ahmad@example.com",
        ic_number="901234567890"
    )
    db.add(passenger)
    db.commit()
    db.refresh(passenger)
    return passenger


@pytest.fixture
def sample_bank_account(db: Session) -> BankAccount:
    """Create a sample bank account for payments."""
    account = BankAccount(
        bank_name="Maybank",
        account_number="1234567890",
        account_holder="Bus Booking Sdn Bhd",
        is_active=1
    )
    db.add(account)
    db.commit()
    db.refresh(account)
    return account


@pytest.fixture
def sample_booking(db: Session, sample_schedule: Schedule, sample_passenger: Passenger) -> Booking:
    """Create a sample booking."""
    booking = Booking(
        passenger_id=sample_passenger.id,
        schedule_id=sample_schedule.id,
        seat_number="1",
        payment_reference="BUS123456",
        status="pending_payment",
        total_price=35.00,
        payment_deadline=datetime.now() + timedelta(minutes=10)
    )
    db.add(booking)

    # Update available seats
    sample_schedule.available_seats -= 1

    db.commit()
    db.refresh(booking)
    return booking
