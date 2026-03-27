import streamlit as st
import pandas as pd
import altair as alt
import sys
from pathlib import Path
from datetime import datetime, timedelta
from sqlalchemy.orm import Session
from database import (
    SessionLocal, init_db, Bus, Route, Schedule, Passenger, Booking, BankAccount,
    get_dashboard_metrics, get_booking_trends, get_revenue_by_route, get_schedule_alerts
)

# Add parent path for utils import (mounted at /utils in Docker, or parent dir for local dev)
sys.path.insert(0, "/")  # Docker: /utils folder
sys.path.insert(0, str(Path(__file__).parent.parent))  # Local dev: parent directory
from utils import preview_seat_layout, SeatMapConfig, generate_seat_map

# ─── Page Config ──────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Bus Booking Admin",
    page_icon="🚌",
    layout="wide",
    initial_sidebar_state="expanded"
)

# ─── 2026 Trending Color Palette ──────────────────────────────────────────────
# Deep Ocean Breeze + Royal Blue Prestige (2026 trending colors)
# Primary: #0A1A3C (deep navy), #143A75 (royal blue)
# Accent: #009EC2 (ocean teal), #8AD9F2 (light cyan)
# Neutral: #E6FBFF (soft white-blue), #F9F9F9 (cloud white)

st.markdown("""
<style>
    /* ═══ Sidebar - Deep Ocean with Glassmorphism ═══ */
    [data-testid="stSidebar"] {
        background: linear-gradient(180deg, #061428 0%, #0A1A3C 25%, #143A75 65%, #0E2D5E 100%) !important;
        border-right: 1px solid rgba(138, 217, 242, 0.1);
        box-shadow: 4px 0 30px rgba(0, 0, 0, 0.25);
    }
    [data-testid="stSidebar"] > div:first-child {
        background: transparent;
        padding-top: 1.5rem;
    }
    [data-testid="stSidebar"] * {
        color: #E6FBFF !important;
    }

    /* Sidebar scrollbar */
    [data-testid="stSidebar"] > div:first-child::-webkit-scrollbar {
        width: 4px;
    }
    [data-testid="stSidebar"] > div:first-child::-webkit-scrollbar-track {
        background: transparent;
    }
    [data-testid="stSidebar"] > div:first-child::-webkit-scrollbar-thumb {
        background: rgba(138, 217, 242, 0.2);
        border-radius: 10px;
    }
    [data-testid="stSidebar"] > div:first-child {
        scrollbar-width: thin;
        scrollbar-color: rgba(138, 217, 242, 0.2) transparent;
    }

    /* Sidebar header with glass accent */
    .sidebar-header {
        padding: 0.75rem 1rem;
        margin-bottom: 1.5rem;
        border-bottom: 1px solid rgba(138, 217, 242, 0.12);
        background: rgba(138, 217, 242, 0.04);
        border-radius: 12px;
    }
    .sidebar-header h1 {
        font-size: 1.4rem;
        font-weight: 800;
        margin: 0;
        background: linear-gradient(135deg, #ffffff 0%, #8AD9F2 100%);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
        background-clip: text;
        letter-spacing: -0.02em;
    }
    .sidebar-header p {
        font-size: 0.7rem;
        color: #8AD9F2 !important;
        margin: 0.35rem 0 0 0;
        letter-spacing: 0.08em;
        text-transform: uppercase;
        font-weight: 500;
    }

    /* Section labels - Ocean Teal accent */
    .nav-section {
        font-size: 0.6rem;
        text-transform: uppercase;
        letter-spacing: 0.15em;
        color: #8AD9F2 !important;
        padding: 1rem 0 0.4rem 0.25rem;
        margin-top: 0.25rem;
        font-weight: 700;
    }

    /* Navigation buttons */
    [data-testid="stSidebar"] button {
        background: rgba(0, 158, 194, 0.05) !important;
        border: 1px solid rgba(138, 217, 242, 0.1) !important;
        border-radius: 10px !important;
        transition: all 0.25s cubic-bezier(0.4, 0, 0.2, 1) !important;
        margin: 2px 0 !important;
    }
    [data-testid="stSidebar"] button:hover {
        background: rgba(0, 158, 194, 0.15) !important;
        border-color: rgba(138, 217, 242, 0.3) !important;
        box-shadow: 0 0 20px rgba(0, 158, 194, 0.1);
        transform: translateX(3px);
    }
    [data-testid="stSidebar"] button[kind="primary"] {
        background: linear-gradient(135deg, #009EC2 0%, #006F87 100%) !important;
        border: 1px solid rgba(138, 217, 242, 0.3) !important;
        box-shadow: 0 4px 20px rgba(0, 158, 194, 0.3) !important;
    }
    [data-testid="stSidebar"] button[kind="primary"]:hover {
        box-shadow: 0 6px 25px rgba(0, 158, 194, 0.4) !important;
        transform: translateX(3px);
    }
    [data-testid="stSidebar"] button[kind="secondary"] {
        border-left: 3px solid transparent !important;
    }
    [data-testid="stSidebar"] button[kind="secondary"]:hover {
        border-left: 3px solid #8AD9F2 !important;
    }

    /* Sidebar collapse/expand button */
    [data-testid="stSidebar"] button[kind="header"] {
        color: #8AD9F2 !important;
        transition: color 0.2s ease, transform 0.2s ease;
        border: none !important;
        background: transparent !important;
    }
    [data-testid="stSidebar"] button[kind="header"]:hover {
        color: #ffffff !important;
        transform: scale(1.1);
        box-shadow: none !important;
        background: transparent !important;
    }

    /* Main content area - Soft cloud white */
    .main .block-container {
        background: #F9F9F9;
    }

    /* Main header */
    .main-header {
        padding: 0.75rem 0 1.5rem 0;
        border-bottom: 2px solid #E6FBFF;
        margin-bottom: 2rem;
    }
    .main-header h1 {
        font-size: 1.75rem;
        font-weight: 700;
        margin: 0;
        color: #0A1A3C;
        letter-spacing: -0.02em;
    }

    /* Custom colored metric cards */
    .metric-card {
        padding: 1.25rem;
        border-radius: 16px;
        text-align: center;
        box-shadow: 0 8px 24px rgba(0, 0, 0, 0.12);
    }
    .metric-card .metric-value {
        font-size: 2rem;
        font-weight: 800;
        color: white;
        margin-bottom: 0.25rem;
    }
    .metric-card .metric-label {
        font-size: 0.8rem;
        text-transform: uppercase;
        letter-spacing: 0.05em;
        color: rgba(255, 255, 255, 0.9);
    }
    .metric-card .metric-delta {
        font-size: 0.75rem;
        margin-top: 0.25rem;
        color: rgba(255, 255, 255, 0.8);
    }
    /* Blue - Fleet/Assets */
    .metric-blue { background: linear-gradient(135deg, #3B82F6 0%, #1D4ED8 100%); }
    /* Purple - Analytics/Routes */
    .metric-purple { background: linear-gradient(135deg, #8B5CF6 0%, #6D28D9 100%); }
    /* Orange - Time/Schedule */
    .metric-orange { background: linear-gradient(135deg, #F97316 0%, #EA580C 100%); }
    /* Green - Performance */
    .metric-green { background: linear-gradient(135deg, #10B981 0%, #059669 100%); }
    /* Emerald - Revenue/Money */
    .metric-emerald { background: linear-gradient(135deg, #34D399 0%, #10B981 100%); }
    /* Rose - Warnings */
    .metric-rose { background: linear-gradient(135deg, #F43F5E 0%, #BE123C 100%); }
    /* Slate - Neutral/Total */
    .metric-slate { background: linear-gradient(135deg, #475569 0%, #334155 100%); }
    /* Teal - Info */
    .metric-teal { background: linear-gradient(135deg, #14B8A6 0%, #0D9488 100%); }

    /* Hide default st.metric styling when using custom cards */
    [data-testid="stMetric"] {
        background: transparent;
        padding: 0;
        box-shadow: none;
        border: none;
    }

    /* Tabs styling - Modern card-style tabs */
    .stTabs [data-baseweb="tab-list"] {
        gap: 16px;
        background: transparent;
        padding: 0;
        border-radius: 0;
        border-bottom: 2px solid #E6FBFF;
        padding-bottom: 0;
    }
    .stTabs [data-baseweb="tab"] {
        border-radius: 12px 12px 0 0;
        color: #0A1A3C;
        font-weight: 600;
        font-size: 0.95rem;
        padding: 1rem 2rem !important;
        margin-bottom: -2px;
        background: #ffffff;
        border: 2px solid #E6FBFF;
        border-bottom: none;
        transition: all 0.3s ease;
        min-width: 160px;
        text-align: center;
        box-shadow: 0 2px 8px rgba(0, 111, 135, 0.08);
    }
    .stTabs [data-baseweb="tab"]:hover {
        background: #f0fbff;
        transform: translateY(-2px);
        color: #006F87;
        border-color: #8AD9F2;
    }
    .stTabs [aria-selected="true"] {
        background: linear-gradient(135deg, #009EC2 0%, #006F87 100%) !important;
        color: white !important;
        border: 2px solid #006F87 !important;
        border-bottom: 2px solid white !important;
        box-shadow: 0 -4px 20px rgba(0, 158, 194, 0.3);
        transform: translateY(-3px);
    }
    .stTabs [data-baseweb="tab-panel"] {
        padding-top: 1.5rem;
    }

    /* Buttons */
    .stButton > button[kind="primary"] {
        background: linear-gradient(135deg, #009EC2 0%, #006F87 100%);
        border: none;
        box-shadow: 0 4px 15px rgba(0, 158, 194, 0.25);
    }
    .stButton > button[kind="primary"]:hover {
        background: linear-gradient(135deg, #00B5D8 0%, #008DA8 100%);
        box-shadow: 0 6px 20px rgba(0, 158, 194, 0.35);
    }

    /* Dataframe */
    .stDataFrame {
        border-radius: 12px;
        overflow: hidden;
        box-shadow: 0 4px 12px rgba(10, 26, 60, 0.08);
    }

    /* Dividers */
    hr {
        border-color: #E6FBFF !important;
    }

    /* Info/Success/Warning boxes */
    .stAlert {
        border-radius: 12px;
    }

    /* Dashboard section headers */
    .dashboard-section {
        margin-top: 1.5rem;
        margin-bottom: 1rem;
    }

    /* Status cards for booking breakdown */
    .status-card {
        padding: 1rem;
        border-radius: 12px;
        text-align: center;
    }
    .status-card-confirmed {
        background: linear-gradient(135deg, #10B981 0%, #059669 100%);
        color: white;
    }
    .status-card-pending {
        background: linear-gradient(135deg, #F59E0B 0%, #D97706 100%);
        color: white;
    }
    .status-card-cancelled {
        background: linear-gradient(135deg, #EF4444 0%, #DC2626 100%);
        color: white;
    }

    /* Alert card styles */
    .alert-item {
        padding: 0.75rem 1rem;
        border-radius: 8px;
        margin-bottom: 0.5rem;
        font-size: 0.9rem;
    }
    .alert-warning {
        background: #FEF3C7;
        border-left: 4px solid #F59E0B;
        color: #92400E;
    }
    .alert-info {
        background: #E0F2FE;
        border-left: 4px solid #0EA5E9;
        color: #0C4A6E;
    }
    .alert-success {
        background: #D1FAE5;
        border-left: 4px solid #10B981;
        color: #065F46;
    }

    /* Sidebar dividers */
    [data-testid="stSidebar"] hr {
        border-color: rgba(138, 217, 242, 0.1) !important;
        margin: 1rem 0;
    }
    /* Sidebar footer */
    [data-testid="stSidebar"] .stCaption {
        color: rgba(138, 217, 242, 0.45) !important;
        font-size: 0.65rem;
        letter-spacing: 0.06em;
        text-align: center;
    }
</style>
""", unsafe_allow_html=True)

# ─── Init DB on startup ───────────────────────────────────────────────────────
init_db()

# ─── Session State for Success Messages ───────────────────────────────────────
if "success_message" not in st.session_state:
    st.session_state.success_message = None

def show_success_and_clear():
    """Display success message if exists, then clear it."""
    if st.session_state.success_message:
        st.success(st.session_state.success_message)
        st.session_state.success_message = None

# ─── DB Helper ────────────────────────────────────────────────────────────────
def get_db() -> Session:
    return SessionLocal()


# ─── Custom Metric Card Helper ────────────────────────────────────────────────
def metric_card(label: str, value: str, color: str = "blue", delta: str = None):
    """
    Render a colored metric card.
    Colors: blue, purple, orange, green, emerald, rose, slate, teal
    """
    delta_html = f'<div class="metric-delta">{delta}</div>' if delta else ''
    st.markdown(f"""
    <div class="metric-card metric-{color}">
        <div class="metric-value">{value}</div>
        <div class="metric-label">{label}</div>
        {delta_html}
    </div>
    """, unsafe_allow_html=True)


# ─── Sidebar Navigation ───────────────────────────────────────────────────────
with st.sidebar:
    # Header with glass accent
    st.markdown("""
    <div class="sidebar-header">
        <h1>🚌 BusTicket</h1>
        <p>Admin Console</p>
    </div>
    """, unsafe_allow_html=True)

    # Overview section
    st.markdown('<div class="nav-section">Overview</div>', unsafe_allow_html=True)

    nav_options = {
        "Dashboard": "dashboard",
        "Bookings": "bookings"
    }

    management_options = {
        "Buses": "buses",
        "Routes": "routes",
        "Schedules": "schedules"
    }

    settings_options = {
        "Bank Account": "bank"
    }

    # Initialize page state
    if "current_page" not in st.session_state:
        st.session_state.current_page = "dashboard"

    # Overview buttons
    for label, key in nav_options.items():
        if st.button(
            f"{'📊' if key == 'dashboard' else '📋'} {label}",
            key=f"nav_{key}",
            use_container_width=True,
            type="primary" if st.session_state.current_page == key else "secondary"
        ):
            st.session_state.current_page = key
            st.rerun()

    # Management section
    st.markdown('<div class="nav-section">Management</div>', unsafe_allow_html=True)

    icons = {"buses": "🚍", "routes": "🗺️", "schedules": "📅"}
    for label, key in management_options.items():
        if st.button(
            f"{icons[key]} {label}",
            key=f"nav_{key}",
            use_container_width=True,
            type="primary" if st.session_state.current_page == key else "secondary"
        ):
            st.session_state.current_page = key
            st.rerun()

    # Settings section
    st.markdown('<div class="nav-section">Settings</div>', unsafe_allow_html=True)

    for label, key in settings_options.items():
        if st.button(
            f"🏦 {label}",
            key=f"nav_{key}",
            use_container_width=True,
            type="primary" if st.session_state.current_page == key else "secondary"
        ):
            st.session_state.current_page = key
            st.rerun()

    # Footer
    st.markdown("---")
    st.markdown("""
    <div style="text-align:center; padding: 0.25rem 0;">
        <span style="font-size:0.6rem; color:rgba(138, 217, 242, 0.4); letter-spacing:0.06em;">v1.0 • 2026</span>
    </div>
    """, unsafe_allow_html=True)

# Get current page
page = st.session_state.current_page

# ══════════════════════════════════════════════════════════════════════════════
# DASHBOARD
# ══════════════════════════════════════════════════════════════════════════════
if page == "dashboard":
    st.markdown('<div class="main-header"><h1>📊 Dashboard</h1></div>', unsafe_allow_html=True)
    db = get_db()

    now = datetime.now()

    # Fetch all dashboard metrics
    metrics = get_dashboard_metrics(db)
    alerts = get_schedule_alerts(db)

    # ─── Two Main Tabs ────────────────────────────────────────────────────────
    tab_ops, tab_finance = st.tabs(["🚌 Bus Operations", "💰 Financial Overview"])

    # ══════════════════════════════════════════════════════════════════════════
    # TAB 1: BUS OPERATIONS
    # ══════════════════════════════════════════════════════════════════════════
    with tab_ops:
        # ─── Operations Snapshot ──────────────────────────────────────────────
        st.subheader("Operations Snapshot")
        col1, col2, col3, col4 = st.columns(4)
        with col1:
            metric_card("Total Buses", str(db.query(Bus).count()), "blue")
        with col2:
            metric_card("Total Routes", str(db.query(Route).count()), "purple")
        with col3:
            upcoming_count = db.query(Schedule).filter(Schedule.departure_time >= now).count()
            metric_card("Upcoming Schedules", str(upcoming_count), "orange")
        with col4:
            metric_card("Avg Occupancy", f"{metrics['avg_occupancy']:.1f}%", "green")

        st.divider()

        # ─── Operational Alerts ───────────────────────────────────────────────
        st.subheader("Operational Alerts")
        alert_col1, alert_col2 = st.columns(2)

        with alert_col1:
            if alerts['departing_soon']:
                st.markdown(f"""
                <div class="alert-item alert-info">
                    <strong>Departing Soon:</strong> {len(alerts['departing_soon'])} bus(es) in next 2 hours
                </div>
                """, unsafe_allow_html=True)
                for s in alerts['departing_soon'][:3]:
                    st.caption(f"  • {s.route.origin} → {s.route.destination} at {s.departure_time.strftime('%H:%M')}")
            else:
                st.info("No buses departing in the next 2 hours.")

        with alert_col2:
            if alerts['low_availability']:
                st.markdown(f"""
                <div class="alert-item alert-success">
                    <strong>Nearly Full:</strong> {len(alerts['low_availability'])} schedule(s) < 20% seats left
                </div>
                """, unsafe_allow_html=True)
                for s in alerts['low_availability'][:3]:
                    st.caption(f"  • {s.route.origin} → {s.route.destination} ({s.available_seats} seats left)")
            else:
                st.info("No schedules are nearly full.")

        if alerts['no_bookings'] and len(alerts['no_bookings']) <= 10:
            st.markdown(f"""
            <div class="alert-item alert-warning">
                <strong>No Bookings Yet:</strong> {len(alerts['no_bookings'])} upcoming schedule(s) have no bookings
            </div>
            """, unsafe_allow_html=True)

        st.divider()

        # ─── On the Way ───────────────────────────────────────────────────────
        st.subheader("On the Way")
        ontheway_count = db.query(Schedule).filter(
            Schedule.departure_time < now,
            Schedule.arrival_time >= now
        ).count()

        if ontheway_count > 0:
            col1, col2, col3, col4 = st.columns(4)
            with col1:
                metric_card("Buses En Route", str(ontheway_count), "teal")
            ontheway_schedules = (
                db.query(Schedule)
                .filter(
                    Schedule.departure_time < now,
                    Schedule.arrival_time >= now
                )
                .order_by(Schedule.arrival_time)
                .limit(10)
                .all()
            )
            rows = []
            for s in ontheway_schedules:
                # Calculate progress
                total_duration = (s.arrival_time - s.departure_time).total_seconds()
                elapsed = (now - s.departure_time).total_seconds()
                progress = min(100, max(0, (elapsed / total_duration) * 100)) if total_duration > 0 else 0

                rows.append({
                    "Route": f"{s.route.origin} → {s.route.destination}",
                    "Bus": s.bus.plate_number,
                    "Departed": s.departure_time.strftime("%H:%M"),
                    "ETA": s.arrival_time.strftime("%H:%M"),
                    "Progress": f"{progress:.0f}%",
                    "Passengers": s.bus.total_seats - s.available_seats,
                })
            st.dataframe(pd.DataFrame(rows), use_container_width=True)
        else:
            st.info("No buses currently on the way.")

        st.divider()

        # ─── Upcoming Schedules ───────────────────────────────────────────────
        st.subheader("Upcoming Schedules")
        upcoming_schedules = (
            db.query(Schedule)
            .filter(Schedule.departure_time >= now)
            .order_by(Schedule.departure_time)
            .limit(10)
            .all()
        )
        if upcoming_schedules:
            rows = []
            for s in upcoming_schedules:
                booked = s.bus.total_seats - s.available_seats
                occupancy = (booked / s.bus.total_seats * 100) if s.bus.total_seats > 0 else 0
                rows.append({
                    "ID": s.id,
                    "Route": f"{s.route.origin} → {s.route.destination}",
                    "Bus": s.bus.plate_number,
                    "Departure": s.departure_time.strftime("%Y-%m-%d %H:%M"),
                    "Seats Left": s.available_seats,
                    "Occupancy": f"{occupancy:.0f}%",
                    "Status": s.status,
                })
            st.dataframe(pd.DataFrame(rows), use_container_width=True)
        else:
            st.info("No upcoming schedules yet.")

    # ══════════════════════════════════════════════════════════════════════════
    # TAB 2: FINANCIAL OVERVIEW
    # ══════════════════════════════════════════════════════════════════════════
    with tab_finance:
        # ─── Revenue Snapshot ─────────────────────────────────────────────────
        st.subheader("Revenue Snapshot")
        col1, col2, col3 = st.columns(3)
        with col1:
            metric_card("Today's Revenue", f"RM {metrics['today_revenue']:,.2f}", "emerald")
        with col2:
            metric_card("This Week", f"RM {metrics['week_revenue']:,.2f}", "emerald")
        with col3:
            metric_card("This Month", f"RM {metrics['month_revenue']:,.2f}", "emerald")

        st.divider()

        # ─── Booking Metrics ──────────────────────────────────────────────────
        st.subheader("Booking Metrics")
        col1, col2, col3, col4 = st.columns(4)
        with col1:
            metric_card("Today's Bookings", str(metrics['today_bookings']), "blue")
        with col2:
            metric_card("Confirmed Today", str(metrics['confirmed_today']), "green")
        with col3:
            metric_card("Cancelled Today", str(metrics['cancelled_today']), "rose")
        with col4:
            metric_card("Conversion Rate", f"{metrics['conversion_rate']:.1f}%", "purple")

        st.divider()

        # ─── Pending Payments Alert ───────────────────────────────────────────
        if metrics['pending_amount'] > 0 or alerts['pending_verification']:
            st.subheader("Payment Alerts")
            col1, col2 = st.columns(2)
            with col1:
                if metrics['pending_amount'] > 0:
                    st.markdown(f"""
                    <div class="alert-item alert-warning">
                        <strong>Pending Payments:</strong> RM {metrics['pending_amount']:,.2f} ({metrics['pending_payments']} bookings)
                    </div>
                    """, unsafe_allow_html=True)
            with col2:
                if alerts['pending_verification']:
                    st.markdown(f"""
                    <div class="alert-item alert-warning">
                        <strong>Receipts to Verify:</strong> {len(alerts['pending_verification'])} receipt(s) awaiting review
                    </div>
                    """, unsafe_allow_html=True)
            st.divider()

        # ─── Charts Row ───────────────────────────────────────────────────────
        col1, col2 = st.columns(2)

        with col1:
            st.subheader("7-Day Booking Trend")
            trend_data = get_booking_trends(db, days=7)
            if trend_data and any(item['count'] > 0 for item in trend_data):
                trend_df = pd.DataFrame(trend_data)
                chart = alt.Chart(trend_df).mark_line(point=True).encode(
                    x=alt.X('date:T', title='Date', axis=alt.Axis(format='%b %d')),
                    y=alt.Y('count:Q', title='Bookings'),
                    color=alt.Color('status:N', scale=alt.Scale(
                        domain=['confirmed', 'pending', 'cancelled'],
                        range=['#10B981', '#F59E0B', '#EF4444']
                    ), legend=alt.Legend(title='Status'))
                ).properties(height=280)
                st.altair_chart(chart, use_container_width=True)
            else:
                st.info("No booking data available for the past 7 days.")

        with col2:
            st.subheader("Revenue by Route")
            route_data = get_revenue_by_route(db)
            if route_data:
                route_df = pd.DataFrame(route_data)
                chart = alt.Chart(route_df).mark_bar(color='#009EC2').encode(
                    x=alt.X('route:N', title='Route', sort='-y', axis=alt.Axis(labelAngle=-45)),
                    y=alt.Y('revenue:Q', title='Revenue (RM)')
                ).properties(height=280)
                st.altair_chart(chart, use_container_width=True)
            else:
                st.info("No revenue data available.")

        st.divider()

        # ─── Booking Status Breakdown ─────────────────────────────────────────
        st.subheader("Booking Status Breakdown")
        total_confirmed = db.query(Booking).filter(Booking.status == 'confirmed').count()
        total_pending = db.query(Booking).filter(Booking.status == 'pending_payment').count()
        total_cancelled = db.query(Booking).filter(Booking.status == 'cancelled').count()
        total_all = total_confirmed + total_pending + total_cancelled

        col1, col2, col3, col4 = st.columns(4)
        with col1:
            st.markdown(f"""
            <div class="status-card status-card-confirmed">
                <div style="font-size: 2rem; font-weight: 700;">{total_confirmed}</div>
                <div style="font-size: 0.85rem; opacity: 0.9;">Confirmed</div>
            </div>
            """, unsafe_allow_html=True)
        with col2:
            st.markdown(f"""
            <div class="status-card status-card-pending">
                <div style="font-size: 2rem; font-weight: 700;">{total_pending}</div>
                <div style="font-size: 0.85rem; opacity: 0.9;">Pending</div>
            </div>
            """, unsafe_allow_html=True)
        with col3:
            st.markdown(f"""
            <div class="status-card status-card-cancelled">
                <div style="font-size: 2rem; font-weight: 700;">{total_cancelled}</div>
                <div style="font-size: 0.85rem; opacity: 0.9;">Cancelled</div>
            </div>
            """, unsafe_allow_html=True)
        with col4:
            st.markdown(f"""
            <div class="status-card" style="background: linear-gradient(135deg, #0A1A3C 0%, #143A75 100%); color: white;">
                <div style="font-size: 2rem; font-weight: 700;">{total_all}</div>
                <div style="font-size: 0.85rem; opacity: 0.9;">Total</div>
            </div>
            """, unsafe_allow_html=True)

    db.close()


# ══════════════════════════════════════════════════════════════════════════════
# BUSES
# ══════════════════════════════════════════════════════════════════════════════
elif page == "buses":
    st.markdown('<div class="main-header"><h1>🚍 Manage Buses</h1></div>', unsafe_allow_html=True)
    db = get_db()

    tab1, tab2 = st.tabs(["➕ Add Bus", "📋 View All Buses"])

    with tab1:
        st.subheader("Add New Bus")
        show_success_and_clear()

        # Two column layout: form on left, preview on right
        form_col, preview_col = st.columns([1, 1])

        with form_col:
            plate = st.text_input("Plate Number *", placeholder="e.g. WXX 1234", key="bus_plate")
            total_seats = st.number_input("Total Seats *", min_value=10, max_value=60, value=36, key="bus_seats")

            st.divider()
            st.markdown("**Seat Layout Configuration**")

            seats_per_row = st.selectbox(
                "Seats Per Row",
                options=[4, 3],
                format_func=lambda x: f"{x} seats ({'2+2' if x == 4 else '1+2'})",
                key="bus_seats_per_row"
            )

            if seats_per_row == 4:
                layout = "2-2"
                st.info("Layout: 2 seats | aisle | 2 seats")
            else:
                layout = st.selectbox(
                    "Layout Style",
                    options=["1-2", "2-1"],
                    format_func=lambda x: "1 seat | aisle | 2 seats" if x == "1-2" else "2 seats | aisle | 1 seat",
                    key="bus_layout_style"
                )

            if st.button("✅ Add Bus", type="primary"):
                if not plate:
                    st.error("Plate number is required.")
                else:
                    existing = db.query(Bus).filter(Bus.plate_number == plate).first()
                    if existing:
                        st.error(f"Bus with plate {plate} already exists.")
                    else:
                        bus = Bus(
                            plate_number=plate,
                            total_seats=total_seats,
                            seats_per_row=seats_per_row,
                            seat_layout=layout
                        )
                        db.add(bus)
                        db.commit()
                        st.session_state.success_message = f"✅ Bus {plate} added successfully!"
                        # Clear form by deleting keys from session state
                        for key in ["bus_plate", "bus_seats", "bus_seats_per_row", "bus_layout_style"]:
                            if key in st.session_state:
                                del st.session_state[key]
                        st.rerun()

        with preview_col:
            st.markdown("**Seat Map Preview**")
            # Generate preview image in memory (not saved to disk)
            try:
                preview_img = preview_seat_layout(
                    total_seats=total_seats,
                    seats_per_row=seats_per_row,
                    layout=layout if seats_per_row == 3 else "2-2",
                )
                st.image(preview_img, caption=f"{total_seats} seats ({layout} layout)", width=250)
            except Exception as e:
                st.warning(f"Preview not available: {e}")

    with tab2:
        show_success_and_clear()
        buses = db.query(Bus).all()
        if buses:
            df = pd.DataFrame([{
                "ID": b.id,
                "Plate": b.plate_number,
                "Total Seats": b.total_seats,
                "Layout": f"{b.seats_per_row or 4} per row ({b.seat_layout or '2-2'})",
                "Created": b.created_at.strftime("%Y-%m-%d"),
            } for b in buses])
            st.dataframe(df, use_container_width=True)

            # View seat map for a bus
            st.subheader("🪑 View Seat Map")
            bus_options = {f"{b.plate_number} ({b.total_seats} seats)": b for b in buses}
            selected_bus_key = st.selectbox("Select Bus", list(bus_options.keys()))
            selected_bus = bus_options[selected_bus_key]

            if st.button("Show Seat Map"):
                try:
                    preview_img = preview_seat_layout(
                        total_seats=selected_bus.total_seats,
                        seats_per_row=selected_bus.seats_per_row or 4,
                        layout=selected_bus.seat_layout or "2-2",
                    )
                    st.image(preview_img, caption=f"{selected_bus.plate_number} - {selected_bus.total_seats} seats", width=300)
                except Exception as e:
                    st.error(f"Could not generate seat map: {e}")

            st.divider()
            st.subheader("🗑️ Delete Bus")
            bus_ids = [b.id for b in buses]
            del_id = st.selectbox("Select Bus ID to delete", bus_ids)
            if st.button("Delete Bus", type="secondary"):
                db.query(Bus).filter(Bus.id == del_id).delete()
                db.commit()
                st.session_state.success_message = "✅ Bus deleted successfully!"
                st.rerun()
        else:
            st.info("No buses added yet.")
    db.close()


# ══════════════════════════════════════════════════════════════════════════════
# ROUTES
# ══════════════════════════════════════════════════════════════════════════════
elif page == "routes":
    st.markdown('<div class="main-header"><h1>🗺️ Manage Routes</h1></div>', unsafe_allow_html=True)
    db = get_db()

    tab1, tab2 = st.tabs(["➕ Add Route", "📋 View All Routes"])

    with tab1:
        st.subheader("Add New Route")
        show_success_and_clear()
        col1, col2 = st.columns(2)

        MALAYSIA_CITIES = [
            "Kuala Lumpur", "Penang", "Johor Bahru", "Ipoh", "Kuching",
            "Kota Kinabalu", "Alor Setar", "Seremban", "Melaka", "Kuantan",
            "Kota Bharu", "Terengganu", "Muar", "Batu Pahat", "Taiping"
        ]

        with col1:
            origin = st.selectbox("Origin *", MALAYSIA_CITIES, key="route_origin")
            estimated_cost = st.number_input("Estimated Cost (RM)", min_value=0.0, value=0.0, step=5.0, key="route_cost", help="Operating cost (fuel, toll, etc.) for profit calculation")
        with col2:
            destination = st.selectbox("Destination *", MALAYSIA_CITIES, key="route_dest")
            st.markdown("**Estimated Duration**")
            dur_col1, dur_col2 = st.columns(2)
            with dur_col1:
                duration_hours = st.number_input("Hours", min_value=0, max_value=24, value=1, step=1, key="route_duration_hours")
            with dur_col2:
                duration_minutes = st.number_input("Minutes", min_value=0, max_value=59, value=0, step=5, key="route_duration_minutes")
            # Convert to decimal hours for storage
            duration = duration_hours + (duration_minutes / 60.0)

        if st.button("✅ Add Route", type="primary"):
            if origin == destination:
                st.error("Origin and destination cannot be the same.")
            elif duration_hours == 0 and duration_minutes == 0:
                st.error("Duration must be at least 1 minute.")
            else:
                existing = db.query(Route).filter(
                    Route.origin == origin, Route.destination == destination
                ).first()
                if existing:
                    st.error(f"Route {origin} → {destination} already exists.")
                else:
                    route = Route(
                        origin=origin,
                        destination=destination,
                        estimated_cost=estimated_cost if estimated_cost > 0 else None,
                        duration_hours=duration
                    )
                    db.add(route)
                    db.commit()
                    st.session_state.success_message = f"✅ Route {origin} → {destination} added!"
                    for key in ["route_origin", "route_dest", "route_cost", "route_duration_hours", "route_duration_minutes"]:
                        if key in st.session_state:
                            del st.session_state[key]
                    st.rerun()

    with tab2:
        show_success_and_clear()
        routes = db.query(Route).all()
        if routes:
            def format_duration(hours):
                if not hours:
                    return "-"
                h = int(hours)
                m = int((hours - h) * 60)
                return f"{h}h {m}m" if m > 0 else f"{h}h"

            df = pd.DataFrame([{
                "ID": r.id,
                "Origin": r.origin,
                "Destination": r.destination,
                "Est. Cost (RM)": f"{r.estimated_cost:.2f}" if r.estimated_cost else "-",
                "Duration": format_duration(r.duration_hours),
            } for r in routes])
            st.dataframe(df, use_container_width=True)

            st.subheader("🗑️ Delete Route")
            route_options_del = {f"{r.id}: {r.origin} → {r.destination}": r.id for r in routes}
            del_key = st.selectbox("Select Route to delete", list(route_options_del.keys()))
            if st.button("Delete Route", type="secondary"):
                db.query(Route).filter(Route.id == route_options_del[del_key]).delete()
                db.commit()
                st.session_state.success_message = "✅ Route deleted successfully!"
                st.rerun()
        else:
            st.info("No routes added yet.")
    db.close()


# ══════════════════════════════════════════════════════════════════════════════
# SCHEDULES
# ══════════════════════════════════════════════════════════════════════════════
elif page == "schedules":
    st.markdown('<div class="main-header"><h1>📅 Manage Schedules</h1></div>', unsafe_allow_html=True)
    db = get_db()

    tab1, tab2 = st.tabs(["➕ Add Schedule", "📋 View All Schedules"])

    with tab1:
        st.subheader("Add New Schedule")
        show_success_and_clear()

        routes = db.query(Route).all()
        buses = db.query(Bus).all()

        if not routes:
            st.warning("⚠️ Please add routes first.")
        elif not buses:
            st.warning("⚠️ Please add buses first.")
        else:
            def format_duration(hours):
                if not hours:
                    return "?"
                h = int(hours)
                m = int((hours - h) * 60)
                return f"{h}h {m}m" if m > 0 else f"{h}h"

            route_options = {f"{r.origin} → {r.destination} ({format_duration(r.duration_hours)})": r for r in routes}
            bus_options = {f"{b.plate_number} ({b.total_seats} seats)": b for b in buses}

            # Schedule Type Selection
            schedule_type = st.radio(
                "Schedule Type",
                ["Specific Date", "Daily", "Weekly"],
                horizontal=True,
                key="sched_type",
                help="Specific: one-time schedule. Daily/Weekly: recurring schedules."
            )

            col1, col2 = st.columns(2)
            with col1:
                selected_route_key = st.selectbox("Route *", list(route_options.keys()), key="sched_route")
                selected_bus_key = st.selectbox("Bus *", list(bus_options.keys()), key="sched_bus")
                price = st.number_input("Ticket Price (RM) *", min_value=1.0, value=30.0, step=0.50, key="sched_price")

            with col2:
                dep_time = st.time_input("Departure Time *", value=datetime.strptime("08:00", "%H:%M").time(), key="sched_dep_time")

                if schedule_type == "Specific Date":
                    dep_date = st.date_input("Departure Date *", value=datetime.now().date() + timedelta(days=1), key="sched_dep_date")
                elif schedule_type == "Daily":
                    num_days = st.number_input("Generate for next N days", min_value=1, max_value=30, value=7, key="sched_num_days")
                else:  # Weekly
                    selected_days = st.multiselect(
                        "Select Days *",
                        ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"],
                        default=["Monday", "Friday"],
                        key="sched_weekly_days"
                    )
                    num_weeks = st.number_input("Generate for next N weeks", min_value=1, max_value=8, value=4, key="sched_num_weeks")

                status = st.selectbox("Status", ["active", "cancelled"], key="sched_status")

            selected_route = route_options[selected_route_key]
            selected_bus = bus_options[selected_bus_key]
            duration_hours = selected_route.duration_hours or 1.0

            st.info(f"🪑 Available seats: **{selected_bus.total_seats}** (bus capacity)")

            # Preview schedules to be created
            schedules_to_create = []
            if schedule_type == "Specific Date":
                dep_dt = datetime.combine(dep_date, dep_time)
                arr_dt = dep_dt + timedelta(hours=duration_hours)
                schedules_to_create.append((dep_dt, arr_dt))
                st.success(f"🕐 **Arrival:** {arr_dt.strftime('%Y-%m-%d %H:%M')} (based on {format_duration(duration_hours)} duration)")

            elif schedule_type == "Daily":
                st.markdown(f"**Will create {num_days} schedules:**")
                preview_dates = []
                for i in range(num_days):
                    dep_dt = datetime.combine(datetime.now().date() + timedelta(days=i+1), dep_time)
                    arr_dt = dep_dt + timedelta(hours=duration_hours)
                    schedules_to_create.append((dep_dt, arr_dt))
                    if i < 5:  # Show first 5 in preview
                        preview_dates.append(dep_dt.strftime("%a, %d %b"))
                preview_text = ", ".join(preview_dates)
                if num_days > 5:
                    preview_text += f", ... (+{num_days - 5} more)"
                st.caption(f"📅 {preview_text}")

            else:  # Weekly
                if not selected_days:
                    st.warning("Please select at least one day.")
                else:
                    day_map = {"Monday": 0, "Tuesday": 1, "Wednesday": 2, "Thursday": 3, "Friday": 4, "Saturday": 5, "Sunday": 6}
                    selected_weekdays = [day_map[d] for d in selected_days]

                    st.markdown(f"**Will create schedules for {', '.join(selected_days)} over {num_weeks} weeks:**")
                    preview_dates = []
                    for week in range(num_weeks):
                        for weekday in selected_weekdays:
                            # Find next occurrence of this weekday
                            today = datetime.now().date()
                            days_ahead = weekday - today.weekday()
                            if days_ahead <= 0:  # Target day already happened this week
                                days_ahead += 7
                            next_date = today + timedelta(days=days_ahead + (week * 7))
                            dep_dt = datetime.combine(next_date, dep_time)
                            arr_dt = dep_dt + timedelta(hours=duration_hours)
                            schedules_to_create.append((dep_dt, arr_dt))
                            if len(preview_dates) < 5:
                                preview_dates.append(dep_dt.strftime("%a, %d %b"))

                    preview_text = ", ".join(preview_dates)
                    if len(schedules_to_create) > 5:
                        preview_text += f", ... (+{len(schedules_to_create) - 5} more)"
                    st.caption(f"📅 {preview_text}")
                    st.info(f"Total: **{len(schedules_to_create)}** schedules will be created")

            # Add Schedule Button
            can_submit = True
            if schedule_type == "Weekly" and not selected_days:
                can_submit = False

            if st.button("✅ Add Schedule", type="primary", disabled=not can_submit):
                if not schedules_to_create:
                    st.error("No schedules to create.")
                else:
                    created_count = 0
                    for dep_dt, arr_dt in schedules_to_create:
                        schedule = Schedule(
                            route_id=selected_route.id,
                            bus_id=selected_bus.id,
                            departure_time=dep_dt,
                            arrival_time=arr_dt,
                            price=price,
                            available_seats=selected_bus.total_seats,
                            status=status
                        )
                        db.add(schedule)
                        created_count += 1
                    db.commit()

                    if created_count == 1:
                        st.session_state.success_message = f"✅ Schedule added: {selected_route_key} on {schedules_to_create[0][0].strftime('%Y-%m-%d %H:%M')}"
                    else:
                        st.session_state.success_message = f"✅ {created_count} schedules created for {selected_route_key}"

                    for key in ["sched_route", "sched_dep_date", "sched_dep_time", "sched_price", "sched_bus", "sched_status", "sched_type", "sched_num_days", "sched_weekly_days", "sched_num_weeks"]:
                        if key in st.session_state:
                            del st.session_state[key]
                    st.rerun()

    with tab2:
        show_success_and_clear()
        schedules = db.query(Schedule).order_by(Schedule.departure_time.desc()).all()
        if schedules:
            rows = [{
                "ID": s.id,
                "Route": f"{s.route.origin} → {s.route.destination}",
                "Bus": s.bus.plate_number,
                "Departure": s.departure_time.strftime("%Y-%m-%d %H:%M"),
                "Arrival": s.arrival_time.strftime("%Y-%m-%d %H:%M"),
                "Price (RM)": f"{s.price:.2f}",
                "Seats Left": s.available_seats,
                "Status": s.status,
            } for s in schedules]
            st.dataframe(pd.DataFrame(rows), use_container_width=True)
        else:
            st.info("No schedules added yet.")
    db.close()


# ══════════════════════════════════════════════════════════════════════════════
# BOOKINGS - Schedule-based view
# ══════════════════════════════════════════════════════════════════════════════
elif page == "bookings":
    st.markdown('<div class="main-header"><h1>📋 Bookings Management</h1></div>', unsafe_allow_html=True)
    db = get_db()
    show_success_and_clear()

    # Initialize session state for selected schedule
    if "selected_schedule_id" not in st.session_state:
        st.session_state.selected_schedule_id = None

    now = datetime.now()

    # Back button if viewing schedule detail
    if st.session_state.selected_schedule_id:
        if st.button("← Back to Schedule List", type="secondary"):
            st.session_state.selected_schedule_id = None
            st.rerun()

        # ─── Schedule Detail View ─────────────────────────────────────────────
        schedule = db.query(Schedule).filter(Schedule.id == st.session_state.selected_schedule_id).first()

        if schedule:
            # Schedule Header
            st.markdown(f"""
            <div style="background: linear-gradient(135deg, #006F87 0%, #009EC2 100%);
                        padding: 1.5rem; border-radius: 16px; margin-bottom: 1.5rem;
                        box-shadow: 0 8px 24px rgba(0, 111, 135, 0.2);">
                <h2 style="color: white; margin: 0; font-size: 1.5rem;">
                    {schedule.route.origin} → {schedule.route.destination}
                </h2>
                <p style="color: #E6FBFF; margin: 0.5rem 0 0 0; font-size: 0.9rem;">
                    🚌 {schedule.bus.plate_number} ({schedule.bus.total_seats} seats)
                </p>
            </div>
            """, unsafe_allow_html=True)

            # Schedule Info Cards
            col1, col2, col3, col4 = st.columns(4)

            # Get bookings for this schedule
            schedule_bookings = db.query(Booking).filter(Booking.schedule_id == schedule.id).all()
            confirmed_bookings = [b for b in schedule_bookings if b.status == "confirmed"]
            pending_bookings = [b for b in schedule_bookings if b.status == "pending_payment"]
            total_revenue = sum(b.total_price for b in confirmed_bookings)
            booked_seats = schedule.bus.total_seats - schedule.available_seats

            with col1:
                st.metric("Departure", schedule.departure_time.strftime("%d %b, %H:%M"))
            with col2:
                st.metric("Seats Booked", f"{booked_seats} / {schedule.bus.total_seats}")
            with col3:
                st.metric("Available", schedule.available_seats)
            with col4:
                st.metric("Revenue", f"RM {total_revenue:.2f}")

            st.divider()

            # Two columns: Bookings list & Seat visualization
            left_col, right_col = st.columns([3, 2])

            with left_col:
                st.subheader("📋 Booking List")

                if schedule_bookings:
                    # Filter options
                    filter_status = st.selectbox(
                        "Filter by status",
                        ["All", "confirmed", "pending", "cancelled"],
                        key="booking_filter"
                    )

                    filtered_bookings = schedule_bookings
                    if filter_status != "All":
                        filtered_bookings = [b for b in schedule_bookings if b.status == filter_status]

                    if filtered_bookings:
                        for booking in filtered_bookings:
                            # Status color
                            status_colors = {
                                "confirmed": "#10B981",
                                "pending": "#F59E0B",
                                "cancelled": "#EF4444"
                            }
                            status_color = status_colors.get(booking.status, "#6B7280")

                            with st.container():
                                st.markdown(f"""
                                <div style="background: white; padding: 1rem; border-radius: 12px;
                                            margin-bottom: 0.75rem; border-left: 4px solid {status_color};
                                            box-shadow: 0 2px 8px rgba(0,0,0,0.05);">
                                    <div style="display: flex; justify-content: space-between; align-items: center;">
                                        <div>
                                            <strong style="color: #0A1A3C;">{booking.passenger.name}</strong>
                                            <span style="background: {status_color}; color: white; padding: 2px 8px;
                                                        border-radius: 12px; font-size: 0.7rem; margin-left: 8px;">
                                                {booking.status.upper()}
                                            </span>
                                        </div>
                                        <span style="color: #006F87; font-weight: 600;">Seat {booking.seat_number or '-'}</span>
                                    </div>
                                    <div style="color: #6B7280; font-size: 0.85rem; margin-top: 0.5rem;">
                                        📞 {booking.passenger.phone} • 💰 RM {booking.total_price:.2f} •
                                        🕐 {booking.booked_at.strftime("%d %b %H:%M")}
                                    </div>
                                </div>
                                """, unsafe_allow_html=True)

                        # Bulk actions
                        st.divider()
                        st.subheader("✏️ Update Booking")
                        booking_options = {f"#{b.id} - {b.passenger.name} (Seat {b.seat_number or '-'})": b.id for b in filtered_bookings}
                        selected_booking = st.selectbox("Select Booking", list(booking_options.keys()))
                        new_status = st.selectbox("New Status", ["pending_payment", "confirmed", "cancelled"], key="new_booking_status")

                        if st.button("Update Status", type="primary"):
                            db.query(Booking).filter(Booking.id == booking_options[selected_booking]).update({"status": new_status})
                            db.commit()
                            st.session_state.success_message = f"✅ Booking updated to '{new_status}'."
                            st.rerun()
                    else:
                        st.info(f"No {filter_status} bookings found.")
                else:
                    st.info("No bookings for this schedule yet.")

            with right_col:
                st.subheader("🪑 Seat Map")

                # Get booked seats
                booked_seat_numbers = [b.seat_number for b in schedule_bookings if b.seat_number and b.status != "cancelled"]

                try:
                    # Generate seat map with booked seats highlighted
                    seat_img = preview_seat_layout(
                        total_seats=schedule.bus.total_seats,
                        seats_per_row=schedule.bus.seats_per_row or 4,
                        layout=schedule.bus.seat_layout or "2-2",
                        booked_seats=booked_seat_numbers
                    )
                    st.image(seat_img, use_container_width=True)

                    # Legend
                    st.markdown("""
                    <div style="display: flex; gap: 1rem; margin-top: 0.5rem; font-size: 0.8rem;">
                        <span>🟩 Available</span>
                        <span>🟥 Booked</span>
                    </div>
                    """, unsafe_allow_html=True)
                except Exception as e:
                    st.warning(f"Seat map not available: {e}")

                # Schedule details
                st.divider()
                st.subheader("📅 Schedule Info")
                st.markdown(f"""
                | Detail | Value |
                |--------|-------|
                | **Schedule ID** | #{schedule.id} |
                | **Departure** | {schedule.departure_time.strftime("%Y-%m-%d %H:%M")} |
                | **Arrival** | {schedule.arrival_time.strftime("%Y-%m-%d %H:%M")} |
                | **Ticket Price** | RM {schedule.price:.2f} |
                | **Status** | {schedule.status} |
                | **Bus Plate** | {schedule.bus.plate_number} |
                | **Total Seats** | {schedule.bus.total_seats} |
                """)

                # Booking summary
                st.divider()
                st.subheader("📊 Summary")
                st.markdown(f"""
                | Metric | Count |
                |--------|-------|
                | ✅ Confirmed | {len(confirmed_bookings)} |
                | ⏳ Pending | {len(pending_bookings)} |
                | ❌ Cancelled | {len([b for b in schedule_bookings if b.status == 'cancelled'])} |
                | **Total Bookings** | {len(schedule_bookings)} |
                """)

        else:
            st.error("Schedule not found.")
            st.session_state.selected_schedule_id = None

    else:
        # ─── Schedule List View ───────────────────────────────────────────────
        st.markdown("Select a schedule to view its bookings and seat details.")

        # Filter tabs
        tab_upcoming, tab_ongoing, tab_past = st.tabs(["📅 Upcoming", "🚌 On The Way", "✅ Completed"])

        with tab_upcoming:
            upcoming_schedules = (
                db.query(Schedule)
                .filter(Schedule.departure_time >= now)
                .order_by(Schedule.departure_time)
                .all()
            )

            if upcoming_schedules:
                for s in upcoming_schedules:
                    bookings_count = db.query(Booking).filter(Booking.schedule_id == s.id).count()
                    confirmed_count = db.query(Booking).filter(Booking.schedule_id == s.id, Booking.status == "confirmed").count()
                    booked = s.bus.total_seats - s.available_seats
                    occupancy = (booked / s.bus.total_seats) * 100 if s.bus.total_seats > 0 else 0

                    # Occupancy color
                    if occupancy >= 80:
                        occ_color = "#10B981"  # Green - high
                    elif occupancy >= 50:
                        occ_color = "#F59E0B"  # Yellow - medium
                    else:
                        occ_color = "#6B7280"  # Gray - low

                    col1, col2 = st.columns([4, 1])

                    with col1:
                        st.markdown(f"""
                        <div style="background: white; padding: 1rem 1.25rem; border-radius: 12px;
                                    margin-bottom: 0.75rem; box-shadow: 0 2px 8px rgba(0,0,0,0.05);
                                    border-left: 4px solid #009EC2;">
                            <div style="display: flex; justify-content: space-between; align-items: center;">
                                <div>
                                    <strong style="color: #0A1A3C; font-size: 1.1rem;">
                                        {s.route.origin} → {s.route.destination}
                                    </strong>
                                    <div style="color: #6B7280; font-size: 0.85rem; margin-top: 0.25rem;">
                                        🚌 {s.bus.plate_number} ({s.bus.total_seats} seats)
                                    </div>
                                </div>
                                <div style="text-align: right;">
                                    <div style="color: #0A1A3C; font-weight: 600;">
                                        {s.departure_time.strftime("%d %b %Y")}
                                    </div>
                                    <div style="color: #009EC2; font-size: 0.9rem;">
                                        {s.departure_time.strftime("%H:%M")}
                                    </div>
                                </div>
                            </div>
                            <div style="display: flex; gap: 1.5rem; margin-top: 0.75rem; font-size: 0.85rem; color: #6B7280;">
                                <span>🎫 {bookings_count} bookings ({confirmed_count} confirmed)</span>
                                <span>🪑 {booked}/{s.bus.total_seats} seats</span>
                                <span style="color: {occ_color}; font-weight: 600;">{occupancy:.0f}% full</span>
                                <span>💰 RM {s.price:.2f}</span>
                            </div>
                        </div>
                        """, unsafe_allow_html=True)

                    with col2:
                        if st.button("View →", key=f"view_{s.id}", use_container_width=True):
                            st.session_state.selected_schedule_id = s.id
                            st.rerun()
            else:
                st.info("No upcoming schedules.")

        with tab_ongoing:
            ongoing_schedules = (
                db.query(Schedule)
                .filter(Schedule.departure_time < now, Schedule.arrival_time >= now)
                .order_by(Schedule.arrival_time)
                .all()
            )

            if ongoing_schedules:
                for s in ongoing_schedules:
                    bookings_count = db.query(Booking).filter(Booking.schedule_id == s.id).count()
                    confirmed_count = db.query(Booking).filter(Booking.schedule_id == s.id, Booking.status == "confirmed").count()

                    col1, col2 = st.columns([4, 1])

                    with col1:
                        st.markdown(f"""
                        <div style="background: white; padding: 1rem 1.25rem; border-radius: 12px;
                                    margin-bottom: 0.75rem; box-shadow: 0 2px 8px rgba(0,0,0,0.05);
                                    border-left: 4px solid #10B981;">
                            <div style="display: flex; justify-content: space-between; align-items: center;">
                                <div>
                                    <strong style="color: #0A1A3C; font-size: 1.1rem;">
                                        {s.route.origin} → {s.route.destination}
                                    </strong>
                                    <span style="background: #10B981; color: white; padding: 2px 8px;
                                                border-radius: 12px; font-size: 0.7rem; margin-left: 8px;">
                                        ON THE WAY
                                    </span>
                                </div>
                                <div style="text-align: right;">
                                    <div style="color: #6B7280; font-size: 0.85rem;">
                                        Arriving {s.arrival_time.strftime("%H:%M")}
                                    </div>
                                </div>
                            </div>
                            <div style="display: flex; gap: 1.5rem; margin-top: 0.75rem; font-size: 0.85rem; color: #6B7280;">
                                <span>🚌 {s.bus.plate_number}</span>
                                <span>🎫 {confirmed_count} passengers</span>
                            </div>
                        </div>
                        """, unsafe_allow_html=True)

                    with col2:
                        if st.button("View →", key=f"view_{s.id}", use_container_width=True):
                            st.session_state.selected_schedule_id = s.id
                            st.rerun()
            else:
                st.info("No buses currently on the way.")

        with tab_past:
            past_schedules = (
                db.query(Schedule)
                .filter(Schedule.arrival_time < now)
                .order_by(Schedule.departure_time.desc())
                .limit(20)
                .all()
            )

            if past_schedules:
                for s in past_schedules:
                    confirmed_bookings = db.query(Booking).filter(
                        Booking.schedule_id == s.id,
                        Booking.status == "confirmed"
                    ).all()
                    confirmed_count = len(confirmed_bookings)
                    total_rev = sum(b.total_price for b in confirmed_bookings)

                    col1, col2 = st.columns([4, 1])

                    with col1:
                        st.markdown(f"""
                        <div style="background: #F9F9F9; padding: 1rem 1.25rem; border-radius: 12px;
                                    margin-bottom: 0.75rem; border-left: 4px solid #9CA3AF;">
                            <div style="display: flex; justify-content: space-between; align-items: center;">
                                <div>
                                    <strong style="color: #6B7280; font-size: 1.1rem;">
                                        {s.route.origin} → {s.route.destination}
                                    </strong>
                                </div>
                                <div style="text-align: right;">
                                    <div style="color: #6B7280; font-size: 0.9rem;">
                                        {s.departure_time.strftime("%d %b %Y")}
                                    </div>
                                </div>
                            </div>
                            <div style="display: flex; gap: 1.5rem; margin-top: 0.75rem; font-size: 0.85rem; color: #9CA3AF;">
                                <span>🚌 {s.bus.plate_number}</span>
                                <span>🎫 {confirmed_count} passengers</span>
                                <span>💰 RM {total_rev:.2f}</span>
                            </div>
                        </div>
                        """, unsafe_allow_html=True)

                    with col2:
                        if st.button("View →", key=f"view_{s.id}", use_container_width=True):
                            st.session_state.selected_schedule_id = s.id
                            st.rerun()
            else:
                st.info("No completed schedules yet.")

    db.close()


# ══════════════════════════════════════════════════════════════════════════════
# BANK ACCOUNT
# ══════════════════════════════════════════════════════════════════════════════
elif page == "bank":
    st.markdown('<div class="main-header"><h1>🏦 Bank Account Settings</h1></div>', unsafe_allow_html=True)
    st.markdown("Configure the bank account for receiving payments. The **recipient name** will be used to verify payment receipts.")

    db = get_db()

    tab1, tab2 = st.tabs(["⚙️ Configure", "📋 View All"])

    with tab1:
        st.subheader("Add / Update Bank Account")
        show_success_and_clear()

        # Get current active account
        active_account = db.query(BankAccount).filter(BankAccount.is_active == 1).first()

        if active_account:
            st.info(f"Current active account: **{active_account.account_holder}** ({active_account.bank_name})")
            st.divider()

        col1, col2 = st.columns(2)
        with col1:
            bank_name = st.text_input(
                "Bank Name *",
                value=active_account.bank_name if active_account else "",
                placeholder="e.g. Maybank, CIMB, Public Bank",
                key="bank_name"
            )
            account_number = st.text_input(
                "Account Number *",
                value=active_account.account_number if active_account else "",
                placeholder="e.g. 1234567890",
                key="bank_account_number"
            )
        with col2:
            account_holder = st.text_input(
                "Account Holder Name *",
                value=active_account.account_holder if active_account else "",
                placeholder="e.g. BUS BOOKING SDN BHD",
                help="This name will be matched against the recipient name in payment receipts",
                key="bank_account_holder"
            )

        st.warning("**Important:** The Account Holder Name must match exactly how it appears on bank transfer receipts.")

        if st.button("💾 Save Bank Account", type="primary"):
            if not bank_name or not account_number or not account_holder:
                st.error("All fields are required.")
            else:
                # Deactivate all existing accounts
                db.query(BankAccount).update({"is_active": 0})

                # Add new active account
                new_account = BankAccount(
                    bank_name=bank_name.strip(),
                    account_number=account_number.strip(),
                    account_holder=account_holder.strip().upper(),  # Uppercase for matching
                    is_active=1
                )
                db.add(new_account)
                db.commit()
                st.session_state.success_message = f"✅ Bank account saved: {account_holder}"
                for key in ["bank_name", "bank_account_number", "bank_account_holder"]:
                    if key in st.session_state:
                        del st.session_state[key]
                st.rerun()

    with tab2:
        st.subheader("Bank Account History")
        show_success_and_clear()
        accounts = db.query(BankAccount).order_by(BankAccount.created_at.desc()).all()

        if accounts:
            rows = [{
                "ID": a.id,
                "Bank": a.bank_name,
                "Account Number": a.account_number,
                "Account Holder": a.account_holder,
                "Status": "✅ Active" if a.is_active else "Inactive",
                "Created": a.created_at.strftime("%Y-%m-%d %H:%M"),
            } for a in accounts]
            st.dataframe(pd.DataFrame(rows), use_container_width=True)

            # Set active account
            st.divider()
            st.subheader("Set Active Account")
            account_options = {f"{a.id}: {a.account_holder} ({a.bank_name})": a.id for a in accounts}
            selected_key = st.selectbox("Select Account", list(account_options.keys()))
            if st.button("Set as Active"):
                db.query(BankAccount).update({"is_active": 0})
                db.query(BankAccount).filter(BankAccount.id == account_options[selected_key]).update({"is_active": 1})
                db.commit()
                st.session_state.success_message = "✅ Bank account set as active."
                st.rerun()
        else:
            st.info("No bank accounts configured yet. Add one in the Configure tab.")

    db.close()