import streamlit as st
import requests
import json
import sys
import os
from datetime import datetime, date, timedelta

# Add utils to path for seat map generator
sys.path.append(os.path.join(os.path.dirname(__file__), '..', 'utils'))
from seat_map_generator import generate_seat_map_bytes, SeatMapConfig

# ── Config ─────────────────────────────────────────────────────────────────────
FASTAPI_URL = os.getenv("FASTAPI_URL", "http://fastapi:8000")

st.set_page_config(
    page_title="BusGo Agent",
    page_icon="🚌",
    layout="centered",
    initial_sidebar_state="expanded"
)

# ── Custom CSS - Agent Style ──────────────────────────────────────────────────
@st.cache_data
def get_app_css():
    return """
<style>
html, body, [class*="css"] { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif; }

.main { background: #ffffff; }

/* Hide Streamlit branding */
#MainMenu {visibility: hidden;}
footer {visibility: hidden;}

/* Agent chat container */
.chat-container {
    max-width: 800px;
    margin: 0 auto;
    padding: 20px 0;
}

/* Message row */
.message-row {
    display: flex;
    gap: 12px;
    margin: 16px 0;
    align-items: flex-start;
}

.message-row.user {
    flex-direction: row-reverse;
}

/* Avatar */
.avatar {
    width: 36px;
    height: 36px;
    border-radius: 50%;
    display: flex;
    align-items: center;
    justify-content: center;
    font-size: 18px;
    flex-shrink: 0;
}

.avatar.agent {
    background: linear-gradient(135deg, #6366f1 0%, #8b5cf6 100%);
    color: white;
}

.avatar.user {
    background: #e5e7eb;
    color: #374151;
}

/* Message bubble */
.message-content {
    max-width: 75%;
    padding: 12px 16px;
    border-radius: 16px;
    font-size: 14px;
    line-height: 1.6;
}

.message-content.agent {
    background: #f3f4f6;
    color: #111827;
    border-bottom-left-radius: 4px;
}

.message-content.user {
    background: #6366f1;
    color: white;
    border-bottom-right-radius: 4px;
}

/* Agent name */
.agent-name {
    font-size: 12px;
    font-weight: 600;
    color: #6b7280;
    margin-bottom: 4px;
}

/* Schedule card */
.sched-card {
    background: #ffffff;
    border: 1px solid #e5e7eb;
    border-radius: 12px;
    padding: 16px;
    margin: 8px 0;
    box-shadow: 0 1px 3px rgba(0,0,0,0.1);
    transition: all 0.2s;
}
.sched-card:hover {
    border-color: #6366f1;
    box-shadow: 0 4px 12px rgba(99,102,241,0.15);
}
.sched-route { font-size: 15px; font-weight: 600; color: #111827; }
.sched-time  { font-size: 13px; color: #6b7280; margin-top: 4px; }
.sched-price { font-size: 20px; font-weight: 700; color: #6366f1; }
.sched-seats { font-size: 12px; padding: 4px 10px; border-radius: 20px; font-weight: 500; }
.seats-ok   { background: #d1fae5; color: #065f46; }
.seats-low  { background: #fef3c7; color: #92400e; }
.seats-full { background: #fee2e2; color: #991b1b; }

/* Payment info card */
.payment-card {
    background: linear-gradient(135deg, #fef3c7 0%, #fde68a 100%);
    border: 2px solid #f59e0b;
    border-radius: 12px;
    padding: 16px;
    margin: 12px 0;
}
.payment-header {
    font-weight: 700;
    color: #92400e;
    font-size: 14px;
    margin-bottom: 12px;
    display: flex;
    align-items: center;
    gap: 8px;
}
.payment-row {
    display: flex;
    justify-content: space-between;
    padding: 6px 0;
    font-size: 13px;
    border-bottom: 1px dashed #fbbf24;
}
.payment-row:last-child { border-bottom: none; }
.payment-label { color: #92400e; }
.payment-value { font-weight: 600; color: #78350f; }
.payment-ref {
    font-size: 18px;
    font-weight: 800;
    color: #b45309;
    text-align: center;
    margin: 12px 0;
    letter-spacing: 2px;
    background: white;
    padding: 8px;
    border-radius: 8px;
}

/* Receipt card */
.receipt-card {
    background: #ffffff;
    border: 2px solid #10b981;
    border-radius: 12px;
    padding: 16px;
    margin: 12px 0;
}
.receipt-header {
    font-weight: 700;
    color: #065f46;
    font-size: 14px;
    margin-bottom: 12px;
}
.receipt-id {
    font-size: 24px;
    font-weight: 800;
    color: #10b981;
    text-align: center;
    margin: 8px 0;
}
.receipt-row {
    display: flex;
    justify-content: space-between;
    padding: 6px 0;
    font-size: 13px;
    border-bottom: 1px solid #e5e7eb;
}
.receipt-row:last-child { border-bottom: none; }
.receipt-label { color: #6b7280; }
.receipt-value { font-weight: 600; color: #111827; }

/* ═══ Sidebar - Modern Dark Gradient ═══ */
[data-testid="stSidebar"] {
    background: linear-gradient(180deg, #0f0a1e 0%, #1a1145 35%, #12103a 70%, #0d0b2e 100%) !important;
    border-right: 1px solid rgba(99, 102, 241, 0.15);
    box-shadow: 4px 0 30px rgba(0, 0, 0, 0.2);
}
[data-testid="stSidebar"] > div:first-child {
    background: transparent;
    padding-top: 1.5rem;
}

/* Sidebar typography */
[data-testid="stSidebar"] [data-testid="stMarkdownContainer"] p,
[data-testid="stSidebar"] [data-testid="stMarkdownContainer"] li {
    color: #cbd5e1;
}
[data-testid="stSidebar"] [data-testid="stMarkdownContainer"] h3 {
    color: #ffffff !important;
    font-weight: 700;
    font-size: 1.25rem;
    letter-spacing: -0.01em;
}
[data-testid="stSidebar"] [data-testid="stMarkdownContainer"] strong {
    color: #a5b4fc !important;
    font-size: 0.7rem;
    text-transform: uppercase;
    letter-spacing: 0.1em;
}

/* Sidebar dividers */
[data-testid="stSidebar"] hr {
    border-color: rgba(99, 102, 241, 0.15) !important;
    margin: 0.75rem 0;
}

/* Sidebar header branding */
.sidebar-brand {
    padding: 0.5rem 0 1rem 0;
    margin-bottom: 0.5rem;
    border-bottom: 1px solid rgba(99, 102, 241, 0.15);
}
.sidebar-brand h3 {
    font-size: 1.3rem;
    font-weight: 800;
    margin: 0;
    background: linear-gradient(135deg, #818cf8 0%, #a78bfa 50%, #c084fc 100%);
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
    background-clip: text;
    letter-spacing: -0.02em;
}
.sidebar-brand p {
    font-size: 0.65rem;
    color: #64748b;
    margin: 0.25rem 0 0 0;
    letter-spacing: 0.12em;
    text-transform: uppercase;
}

/* Sidebar section labels */
.sidebar-section {
    font-size: 0.6rem;
    text-transform: uppercase;
    letter-spacing: 0.15em;
    color: #6366f1 !important;
    padding: 0.75rem 0 0.35rem 0.25rem;
    font-weight: 700;
}

/* Sidebar command buttons */
[data-testid="stSidebar"] .stButton > button {
    background: rgba(99, 102, 241, 0.06) !important;
    border: 1px solid rgba(99, 102, 241, 0.15) !important;
    border-radius: 10px !important;
    color: #e2e8f0 !important;
    font-weight: 500;
    font-size: 0.875rem;
    padding: 0.55rem 0.9rem;
    transition: all 0.25s cubic-bezier(0.4, 0, 0.2, 1) !important;
    text-align: left;
}
[data-testid="stSidebar"] .stButton > button:hover {
    background: rgba(99, 102, 241, 0.16) !important;
    border-color: rgba(99, 102, 241, 0.4) !important;
    box-shadow: 0 0 20px rgba(99, 102, 241, 0.12);
    transform: translateX(3px);
    color: #ffffff !important;
}
[data-testid="stSidebar"] .stButton > button:active {
    transform: translateX(1px);
}

/* Sidebar scrollbar */
[data-testid="stSidebar"] > div:first-child::-webkit-scrollbar {
    width: 4px;
}
[data-testid="stSidebar"] > div:first-child::-webkit-scrollbar-track {
    background: transparent;
}
[data-testid="stSidebar"] > div:first-child::-webkit-scrollbar-thumb {
    background: rgba(99, 102, 241, 0.25);
    border-radius: 10px;
}
[data-testid="stSidebar"] > div:first-child {
    scrollbar-width: thin;
    scrollbar-color: rgba(99, 102, 241, 0.25) transparent;
}

/* Language radio pills */
[data-testid="stSidebar"] .stRadio > div {
    gap: 4px;
}
[data-testid="stSidebar"] .stRadio label {
    color: #a5b4fc !important;
    font-weight: 500;
    font-size: 0.85rem;
}
[data-testid="stSidebar"] .stRadio label span {
    color: #a5b4fc !important;
}

/* New Chat button - distinct accent */
.new-chat-btn .stButton > button {
    background: rgba(99, 102, 241, 0.12) !important;
    border: 1px dashed rgba(99, 102, 241, 0.35) !important;
    color: #818cf8 !important;
}
.new-chat-btn .stButton > button:hover {
    background: rgba(99, 102, 241, 0.22) !important;
    border-style: solid !important;
    border-color: #6366f1 !important;
    box-shadow: 0 0 24px rgba(99, 102, 241, 0.18);
}

/* Sidebar collapse button */
[data-testid="stSidebar"] button[kind="header"] {
    color: #818cf8 !important;
    transition: color 0.2s ease, transform 0.2s ease;
}
[data-testid="stSidebar"] button[kind="header"]:hover {
    color: #ffffff !important;
    transform: scale(1.1);
    background: transparent !important;
}

/* Thinking indicator - Modern LLM style */
.thinking-container {
    display: flex;
    gap: 12px;
    margin: 16px 0;
    align-items: flex-start;
    animation: fadeIn 0.3s ease-out;
}

@keyframes fadeIn {
    from { opacity: 0; transform: translateY(10px); }
    to { opacity: 1; transform: translateY(0); }
}

.thinking-bubble {
    background: #f3f4f6;
    border-radius: 16px;
    border-bottom-left-radius: 4px;
    padding: 14px 18px;
    display: flex;
    align-items: center;
    gap: 12px;
}

.thinking-dots {
    display: flex;
    gap: 5px;
    align-items: center;
}

.thinking-dot {
    width: 8px;
    height: 8px;
    background: linear-gradient(135deg, #6366f1 0%, #8b5cf6 100%);
    border-radius: 50%;
    animation: pulse 1.4s ease-in-out infinite;
}

.thinking-dot:nth-child(1) { animation-delay: 0s; }
.thinking-dot:nth-child(2) { animation-delay: 0.2s; }
.thinking-dot:nth-child(3) { animation-delay: 0.4s; }

@keyframes pulse {
    0%, 80%, 100% {
        transform: scale(0.8);
        opacity: 0.5;
    }
    40% {
        transform: scale(1.2);
        opacity: 1;
    }
}

.thinking-text {
    font-size: 13px;
    color: #6b7280;
    font-weight: 500;
}

/* Shimmer effect for processing */
.thinking-shimmer {
    background: linear-gradient(90deg, #f3f4f6 25%, #e5e7eb 50%, #f3f4f6 75%);
    background-size: 200% 100%;
    animation: shimmer 1.5s infinite;
}

@keyframes shimmer {
    0% { background-position: 200% 0; }
    100% { background-position: -200% 0; }
}

/* Legacy typing indicator */
.typing-indicator {
    display: flex;
    gap: 4px;
    padding: 12px 16px;
}
.typing-dot-legacy {
    width: 8px;
    height: 8px;
    background: #9ca3af;
    border-radius: 50%;
    animation: typing 1.4s infinite;
}
.typing-dot-legacy:nth-child(2) { animation-delay: 0.2s; }
.typing-dot-legacy:nth-child(3) { animation-delay: 0.4s; }
@keyframes typing {
    0%, 60%, 100% { transform: translateY(0); opacity: 0.4; }
    30% { transform: translateY(-4px); opacity: 1; }
}

/* Input styling */
[data-testid="stChatInput"] {
    border-radius: 12px;
}

/* ═══ Login Screen ═══ */
.login-card {
    max-width: 420px;
    margin: 8vh auto 0 auto;
    background: linear-gradient(135deg, #0f0a1e 0%, #1a1145 50%, #12103a 100%);
    border-radius: 20px;
    padding: 40px 36px 36px 36px;
    box-shadow: 0 20px 60px rgba(0,0,0,0.3), 0 0 40px rgba(99,102,241,0.08);
    border: 1px solid rgba(99,102,241,0.15);
}
.login-logo {
    text-align: center;
    margin-bottom: 8px;
    font-size: 2rem;
    font-weight: 800;
    background: linear-gradient(135deg, #818cf8 0%, #a78bfa 50%, #c084fc 100%);
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
    background-clip: text;
    letter-spacing: -0.02em;
}
.login-subtitle {
    text-align: center;
    font-size: 0.8rem;
    color: #64748b;
    letter-spacing: 0.12em;
    text-transform: uppercase;
    margin-bottom: 28px;
}

/* Hide sidebar on login */
.hide-sidebar [data-testid="stSidebar"] { display: none; }
.hide-sidebar [data-testid="collapsedControl"] { display: none; }

/* User info card in sidebar */
.user-card {
    background: rgba(99,102,241,0.08);
    border: 1px solid rgba(99,102,241,0.2);
    border-radius: 10px;
    padding: 12px 14px;
    margin: 8px 0 4px 0;
}
.user-card-name {
    color: #e2e8f0;
    font-weight: 600;
    font-size: 0.95rem;
}
.user-card-phone {
    color: #94a3b8;
    font-size: 0.75rem;
    margin-top: 2px;
}
</style>
"""

st.markdown(get_app_css(), unsafe_allow_html=True)


# ── Session State ──────────────────────────────────────────────────────────────
for key, val in {
    "messages": [],
    "session_id": None,
    "lang": "EN",
    "mode": None,
    "last_schedules": [],
    "welcomed": False,
    "selected_schedule": None,  # For seat selection flow
    "seat_info": None,          # Seat availability data
    "book_schedules": [],       # Schedules found in booking flow
    "pending_booking": None,    # Pending booking awaiting confirmation
    "logged_in": False,
    "passenger_id": None,
    "passenger_name": "",
    "passenger_phone": "",
    "is_new_user": False,
}.items():
    if key not in st.session_state:
        st.session_state[key] = val


# ── Login Gate ─────────────────────────────────────────────────────────────────
if not st.session_state.logged_in:
    # Hide sidebar
    st.markdown('<style>[data-testid="stSidebar"]{display:none}[data-testid="collapsedControl"]{display:none}</style>', unsafe_allow_html=True)

    st.markdown("""
    <div class="login-card">
        <div class="login-logo">🚌 BusGo</div>
        <div class="login-subtitle">Your Travel Assistant</div>
    </div>
    """, unsafe_allow_html=True)

    with st.form("login_form"):
        login_name = st.text_input("Your Name", placeholder="e.g. Ahmad bin Ali")
        login_phone = st.text_input("Phone Number", placeholder="e.g. 0123456789")
        submitted = st.form_submit_button("🚀 Start Chatting", use_container_width=True, type="primary")

        if submitted:
            if not login_name or not login_phone:
                st.error("Please enter your name and phone number.")
            else:
                try:
                    resp = requests.post(
                        f"{FASTAPI_URL}/auth/login",
                        json={"name": login_name.strip(), "phone": login_phone.strip()},
                        timeout=10,
                    )
                    resp.raise_for_status()
                    data = resp.json()
                    st.session_state.logged_in = True
                    st.session_state.passenger_id = data["id"]
                    st.session_state.passenger_name = data["name"]
                    st.session_state.passenger_phone = data["phone"]
                    st.session_state.is_new_user = data.get("is_new", False)
                    st.rerun()
                except Exception:
                    st.error("Could not connect to server. Please try again.")

    st.stop()

# ── Language ───────────────────────────────────────────────────────────────────
T = {
    "EN": {
        "welcome": "Hi! I'm **BusGo Agent**, your Malaysia bus booking assistant. I can help you search for buses, make bookings, and manage your trips.\n\nUse the commands in the sidebar or just ask me anything!",
        "thinking": "Thinking...",
        "error": "Sorry, I'm having trouble connecting. Please try again.",
        "no_buses": "I couldn't find any buses for that route. Try a different route or date?",
        "all_dates": "Showing all upcoming schedules",
    },
    "BM": {
        "welcome": "Hai! Saya **BusGo Agent**, pembantu tempahan bas Malaysia anda. Saya boleh bantu anda cari bas, buat tempahan, dan urus perjalanan anda.\n\nGuna arahan di bar sisi atau tanya saya apa sahaja!",
        "thinking": "Sedang berfikir...",
        "error": "Maaf, saya ada masalah sambungan. Sila cuba lagi.",
        "no_buses": "Tiada bas dijumpai untuk laluan ini. Cuba laluan atau tarikh lain?",
        "all_dates": "Menunjukkan semua jadual akan datang",
    },
}

def t(key): return T[st.session_state.lang][key]


# ── Helpers ────────────────────────────────────────────────────────────────────
def add_msg(role, content, extra=None):
    st.session_state.messages.append({"role": role, "content": content, **(extra or {})})


def render_message(msg, is_latest=False, msg_index=0):
    """Render a single message in agent chat style."""
    role = msg["role"]
    content = msg["content"]

    if role == "user":
        st.markdown(f"""
        <div class="message-row user">
            <div class="avatar user">👤</div>
            <div class="message-content user">{content}</div>
        </div>
        """, unsafe_allow_html=True)
    else:
        st.markdown(f"""
        <div class="message-row">
            <div class="avatar agent">🚌</div>
            <div>
                <div class="agent-name">BusGo Agent</div>
                <div class="message-content agent">{content}</div>
            </div>
        </div>
        """, unsafe_allow_html=True)

        # Render schedules if present
        if msg.get("schedules"):
            render_schedule_cards(msg["schedules"])

        # Render booking result if present
        if msg.get("booking"):
            render_booking_result(msg["booking"], is_latest, msg_index=msg_index)


def render_schedule_cards(schedules):
    """Render schedule cards."""
    for i, s in enumerate(schedules):
        seats = s["available_seats"]
        seat_cls = "seats-ok" if seats > 10 else "seats-low" if seats > 3 else "seats-full"
        seat_txt = f"{seats} seats" if seats > 0 else "Full"
        st.markdown(f"""
        <div class="sched-card">
            <div style="display:flex; justify-content:space-between; align-items:flex-start">
                <div>
                    <div class="sched-route">#{i+1} {s['origin']} → {s['destination']}</div>
                    <div class="sched-time">🕐 {s['departure_time']} → {s['arrival_time']}</div>
                    <div class="sched-time">🚌 {s['bus_type']} • {s['plate_number']}</div>
                </div>
                <div style="text-align:right">
                    <div class="sched-price">RM {s['price']:.2f}</div>
                    <span class="sched-seats {seat_cls}">{seat_txt}</span>
                </div>
            </div>
        </div>
        """, unsafe_allow_html=True)


def render_booking_result(data, expanded=True, msg_index=0):
    """Render booking result with payment info."""
    booking = data.get("booking", {})
    payment = data.get("payment_info", {})
    message = data.get("message", "")

    # Determine status display
    status = booking.get('status', 'pending_payment')
    status_map = {
        "confirmed": ("Confirmed", "✅ Confirmed", "#22c55e"),
        "pending_payment": ("Pending Payment", "⏳ Pending Payment", "#f59e0b"),
        "cancelled": ("Cancelled", "❌ Cancelled", "#ef4444"),
    }
    status_label, status_display, status_color = status_map.get(
        status, (status.replace("_", " ").title(), status, "#6b7280")
    )

    with st.expander(f"🎫 Booking #{booking.get('booking_id')} - {status_label}", expanded=expanded):
        # Booking details
        st.markdown(f"""
        <div class="receipt-card">
            <div class="receipt-header">📋 Booking Details</div>
            <div class="receipt-id">#{booking.get('booking_id')}</div>
            <div class="receipt-row"><span class="receipt-label">Passenger</span><span class="receipt-value">{booking.get('passenger_name')}</span></div>
            <div class="receipt-row"><span class="receipt-label">Route</span><span class="receipt-value">{booking.get('origin')} → {booking.get('destination')}</span></div>
            <div class="receipt-row"><span class="receipt-label">Departure</span><span class="receipt-value">{booking.get('departure_time')}</span></div>
            <div class="receipt-row"><span class="receipt-label">Seat</span><span class="receipt-value">{booking.get('seat_number')}</span></div>
            <div class="receipt-row"><span class="receipt-label">Status</span><span class="receipt-value" style="color:{status_color}">{status_display}</span></div>
        </div>
        """, unsafe_allow_html=True)

        # Only show payment info and receipt upload for pending bookings
        if status == "pending_payment":
            # Payment info
            if payment:
                st.markdown(f"""
                <div class="payment-card">
                    <div class="payment-header">💳 Payment Instructions</div>
                    <div class="payment-ref">{payment.get('reference', 'N/A')}</div>
                    <div class="payment-row"><span class="payment-label">Bank</span><span class="payment-value">{payment.get('bank_name', 'N/A')}</span></div>
                    <div class="payment-row"><span class="payment-label">Account Number</span><span class="payment-value">{payment.get('account_number', 'N/A')}</span></div>
                    <div class="payment-row"><span class="payment-label">Account Name</span><span class="payment-value">{payment.get('account_holder', 'N/A')}</span></div>
                    <div class="payment-row"><span class="payment-label">Amount</span><span class="payment-value">RM {payment.get('amount', 0):.2f}</span></div>
                </div>
                """, unsafe_allow_html=True)

                st.warning(f"⏰ **Payment Deadline:** {booking.get('payment_deadline', 'N/A')}")
                st.info("📤 After transfer, upload your receipt below for verification.")

            # Receipt upload
            st.markdown("---")
            st.markdown("**Upload Payment Receipt**")
            uploaded_file = st.file_uploader(
                "Upload receipt image",
                type=["jpg", "jpeg", "png", "webp"],
                key=f"receipt_{msg_index}_{booking.get('booking_id')}",
                label_visibility="collapsed"
            )

            if uploaded_file:
                if st.button("✅ Verify Payment", type="primary", key=f"verify_{msg_index}_{booking.get('booking_id')}"):
                    # Show modern processing indicator
                    verify_placeholder = st.empty()
                    with verify_placeholder.container():
                        st.markdown("""
                        <div class="thinking-bubble" style="margin: 10px 0;">
                            <div class="thinking-dots">
                                <div class="thinking-dot"></div>
                                <div class="thinking-dot"></div>
                                <div class="thinking-dot"></div>
                            </div>
                            <span class="thinking-text">📸 Verifying receipt...</span>
                        </div>
                        """, unsafe_allow_html=True)

                    result = upload_receipt(booking.get('booking_id'), uploaded_file)
                    verify_placeholder.empty()

                    if result:
                        if result.get("status") == "verified":
                            st.success(f"✅ {result.get('message')}")
                        else:
                            st.error(f"❌ {result.get('message')}")
                    else:
                        st.error("Failed to verify receipt. Please try again.")


def render_messages():
    """Render all messages."""
    messages = st.session_state.messages
    for i, msg in enumerate(messages):
        is_latest = i == len(messages) - 1
        render_message(msg, is_latest, msg_index=i)


def render_thinking_indicator(text="Thinking", show_icon=True):
    """Render modern LLM-style thinking indicator.

    Args:
        text: The text to display (e.g., "Thinking", "Searching", "Processing")
        show_icon: Whether to show a contextual icon
    """
    # Choose icon based on text
    icon = ""
    if show_icon:
        icon_map = {
            "Thinking": "💭",
            "Searching": "🔍",
            "Processing": "⚙️",
            "Booking": "🎫",
            "Checking": "📋",
        }
        icon = icon_map.get(text, "💭")

    thinking_html = f"""
    <div class="thinking-container">
        <div class="avatar agent">🚌</div>
        <div>
            <div class="agent-name">BusGo Agent</div>
            <div class="thinking-bubble">
                <div class="thinking-dots">
                    <div class="thinking-dot"></div>
                    <div class="thinking-dot"></div>
                    <div class="thinking-dot"></div>
                </div>
                <span class="thinking-text">{icon} {text}...</span>
            </div>
        </div>
    </div>
    """
    return st.markdown(thinking_html, unsafe_allow_html=True)


def call_fastapi_stream(message, placeholder):
    """Call streaming chat API, progressively updating the placeholder."""
    try:
        resp = requests.post(
            f"{FASTAPI_URL}/chat/stream",
            json={
                "message": message,
                "session_id": st.session_state.session_id,
                "passenger_id": st.session_state.passenger_id,
            },
            stream=True,
            timeout=120
        )
        resp.raise_for_status()

        full_text = ""
        for line in resp.iter_lines(decode_unicode=True):
            if not line or not line.startswith("data: "):
                continue
            payload = line[6:]  # strip "data: " prefix

            if payload == "[DONE]":
                break

            try:
                event = json.loads(payload)
            except json.JSONDecodeError:
                continue

            if event.get("type") == "meta":
                st.session_state.session_id = event.get("session_id")
            elif event.get("type") == "token":
                full_text += event.get("text", "")
                # Update placeholder with growing agent message
                placeholder.markdown(
                    f'<div class="message-row">'
                    f'<div class="avatar agent">\U0001f68c</div>'
                    f'<div>'
                    f'<div class="agent-name">BusGo Agent</div>'
                    f'<div class="message-content agent">{full_text}</div>'
                    f'</div>'
                    f'</div>',
                    unsafe_allow_html=True
                )
        return full_text if full_text else None
    except Exception:
        return None


def search_direct(origin, destination, travel_date):
    """Search schedules via REST API."""
    try:
        params = {"origin": origin, "destination": destination}
        if travel_date:
            params["date"] = travel_date.strftime("%Y-%m-%d")
        resp = requests.get(f"{FASTAPI_URL}/schedules", params=params, timeout=10)
        resp.raise_for_status()
        return resp.json()
    except Exception:
        return []


def book_direct(schedule_id, name, phone, num_passengers):
    """Create booking via REST API."""
    try:
        resp = requests.post(f"{FASTAPI_URL}/bookings", json={
            "schedule_id": schedule_id,
            "passenger_name": name,
            "passenger_phone": phone,
            "num_passengers": num_passengers,
        }, timeout=10)
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        return None


def check_direct(booking_id):
    """Check booking via REST API."""
    try:
        resp = requests.get(f"{FASTAPI_URL}/bookings/{booking_id}", timeout=10)
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        return resp.json()
    except Exception:
        return None


def cancel_direct(booking_id):
    """Cancel booking via REST API."""
    try:
        resp = requests.delete(f"{FASTAPI_URL}/bookings/{booking_id}", timeout=10)
        return resp.status_code == 200
    except Exception:
        return False


def upload_receipt(booking_id, file):
    """Upload receipt for verification."""
    try:
        files = {"file": (file.name, file.getvalue(), file.type)}
        resp = requests.post(
            f"{FASTAPI_URL}/bookings/{booking_id}/receipt",
            files=files,
            timeout=120
        )
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        return None


@st.cache_data
def cached_seat_map(total_seats: int, seats_per_row: int, layout: str,
                    occupied_seats: tuple, selected_seats: tuple) -> bytes:
    """Cached seat map generation. Args must be hashable (tuples, not lists)."""
    config = SeatMapConfig(
        total_seats=total_seats,
        seats_per_row=seats_per_row,
        layout=layout,
    )
    buf = generate_seat_map_bytes(
        occupied_seats=list(occupied_seats),
        selected_seats=list(selected_seats),
        config=config,
    )
    return buf.getvalue()


def get_seat_info(schedule_id):
    """Get seat availability for a schedule."""
    try:
        resp = requests.get(f"{FASTAPI_URL}/schedules/{schedule_id}/seats", timeout=10)
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        return None


def book_with_seat(schedule_id, name, phone, seat_number, num_passengers=1):
    """Create booking with specific seat selection. Returns (result_dict, None) on success or (None, error_message) on failure."""
    try:
        resp = requests.post(f"{FASTAPI_URL}/bookings", json={
            "schedule_id": schedule_id,
            "passenger_name": name,
            "passenger_phone": phone,
            "num_passengers": num_passengers,
            "seat_number": seat_number,
        }, timeout=10)
        if resp.status_code == 400:
            detail = resp.json().get("detail", "Booking failed.")
            return None, detail
        resp.raise_for_status()
        return resp.json(), None
    except Exception as e:
        return None, "Connection error. Please try again."


# ── Sidebar ────────────────────────────────────────────────────────────────────
with st.sidebar:
    # Brand header
    st.markdown("""
    <div class="sidebar-brand">
        <h3>🚌 BusGo Agent</h3>
        <p>Your Travel Assistant</p>
    </div>
    """, unsafe_allow_html=True)

    # User info card
    st.markdown(f"""
    <div class="user-card">
        <div class="user-card-name">👤 {st.session_state.passenger_name}</div>
        <div class="user-card-phone">📞 {st.session_state.passenger_phone}</div>
    </div>
    """, unsafe_allow_html=True)

    # Commands section
    st.markdown('<div class="sidebar-section">Quick Commands</div>', unsafe_allow_html=True)
    search_click = st.button("🔍 Search Buses", use_container_width=True)
    book_click = st.button("🎫 Book Ticket", use_container_width=True)
    my_bookings_click = st.button("📋 My Bookings", use_container_width=True)
    check_click = st.button("🔎 Check Booking", use_container_width=True)
    cancel_click = st.button("❌ Cancel Booking", use_container_width=True)

    st.markdown("---")

    # Session section
    st.markdown('<div class="sidebar-section">Session</div>', unsafe_allow_html=True)
    with st.container():
        st.markdown('<div class="new-chat-btn">', unsafe_allow_html=True)
        if st.button("🔄 New Chat", use_container_width=True):
            for k in ["messages", "session_id", "mode", "last_schedules", "welcomed", "selected_schedule", "seat_info", "book_schedules"]:
                st.session_state[k] = [] if k in ["messages", "last_schedules", "book_schedules"] else None
            st.session_state.welcomed = False
            st.rerun()
        st.markdown('</div>', unsafe_allow_html=True)

    if st.button("🚪 Logout", use_container_width=True):
        for key in list(st.session_state.keys()):
            del st.session_state[key]
        st.rerun()

    st.markdown("---")

    # Language selector
    st.markdown('<div class="sidebar-section">Language</div>', unsafe_allow_html=True)
    lang = st.radio("", ["EN", "BM"], horizontal=True,
                    index=0 if st.session_state.lang == "EN" else 1,
                    label_visibility="collapsed")
    if lang != st.session_state.lang:
        st.session_state.lang = lang
        st.rerun()

    # Footer
    st.markdown("---")
    st.markdown("""
    <div style="text-align:center; padding: 0.5rem 0;">
        <span style="font-size:0.65rem; color:rgba(99,102,241,0.5); letter-spacing:0.05em;">v1.0 • 2026</span>
    </div>
    """, unsafe_allow_html=True)


# Handle command clicks
if search_click: st.session_state.mode = "search"
if book_click: st.session_state.mode = "book_select"
if my_bookings_click: st.session_state.mode = "my_bookings"
if check_click: st.session_state.mode = "check"
if cancel_click: st.session_state.mode = "cancel"


# ── Main Chat Area ─────────────────────────────────────────────────────────────

# Welcome message
if not st.session_state.welcomed:
    first_name = st.session_state.passenger_name.split()[0] if st.session_state.passenger_name else ""
    if st.session_state.is_new_user:
        welcome_text = t("welcome")
    else:
        welcome_text = f"Welcome back, **{first_name}**! 👋 How can I help you today? You can search for buses, check your bookings, or just ask me anything!"
    add_msg("assistant", welcome_text)
    st.session_state.welcomed = True

# Render messages
render_messages()

# ── Command Forms ──────────────────────────────────────────────────────────────
CITIES = ["Kuala Lumpur", "Penang", "Johor Bahru", "Ipoh", "Melaka", "Kuantan",
          "Kota Bharu", "Kuching", "Kota Kinabalu", "Alor Setar", "Seremban", "Taiping", "Muar"]

mode = st.session_state.mode

if mode == "search":
    with st.container(border=True):
        st.markdown("#### 🔍 Search Buses")
        c1, c2 = st.columns(2)
        with c1:
            origin = st.selectbox("From", CITIES, key="s_origin")
        with c2:
            dest = st.selectbox("To", [c for c in CITIES if c != origin], key="s_dest")

        use_date = st.checkbox("Specific date", value=False)
        travel_date = None
        if use_date:
            travel_date = st.date_input("Date", value=date.today() + timedelta(days=1), min_value=date.today())

        c1, c2 = st.columns(2)
        with c1:
            if st.button("🔍 Search", type="primary", use_container_width=True):
                add_msg("user", f"Search buses from {origin} to {dest}" + (f" on {travel_date}" if travel_date else ""))
                schedules = search_direct(origin, dest, travel_date)
                if schedules:
                    st.session_state.last_schedules = schedules
                    add_msg("assistant", f"Found **{len(schedules)}** bus(es) from {origin} to {dest}. Select one and click **Book Ticket** to reserve!", {"schedules": schedules})
                else:
                    add_msg("assistant", t("no_buses"))
                st.session_state.mode = None
                st.rerun()
        with c2:
            if st.button("Cancel", use_container_width=True):
                st.session_state.mode = None
                st.rerun()

elif mode == "book_select":
    with st.container(border=True):
        st.markdown("#### 🎫 Book Ticket")

        # Step 1: Select route and date
        c1, c2 = st.columns(2)
        with c1:
            origin = st.selectbox("From", CITIES, key="b_origin")
        with c2:
            dest = st.selectbox("To", [c for c in CITIES if c != origin], key="b_dest")

        travel_date = st.date_input("Travel Date", value=date.today() + timedelta(days=1), min_value=date.today(), key="b_date")

        c1, c2 = st.columns(2)
        with c1:
            if st.button("🔍 Find Buses", type="primary", use_container_width=True):
                schedules = search_direct(origin, dest, travel_date)
                st.session_state.book_schedules = schedules
                st.rerun()
        with c2:
            if st.button("Cancel", use_container_width=True):
                st.session_state.book_schedules = []
                st.session_state.mode = None
                st.rerun()

        # Step 2: Show available schedules
        if st.session_state.book_schedules:
            st.markdown("---")
            st.markdown(f"**Found {len(st.session_state.book_schedules)} bus(es)**")

            for i, s in enumerate(st.session_state.book_schedules):
                seats = s["available_seats"]
                seat_cls = "seats-ok" if seats > 10 else "seats-low" if seats > 3 else "seats-full"
                seat_txt = f"{seats} seats" if seats > 0 else "Full"

                col1, col2 = st.columns([3, 1])
                with col1:
                    st.markdown(f"""
                    <div class="sched-card" style="margin:4px 0; padding:12px;">
                        <div style="display:flex; justify-content:space-between; align-items:center;">
                            <div>
                                <div style="font-weight:600;">🕐 {s['departure_time'].split(' ')[1]} → {s['arrival_time'].split(' ')[1]}</div>
                                <div style="font-size:12px; color:#6b7280;">🚌 {s['bus_type']} • {s['plate_number']}</div>
                            </div>
                            <div style="text-align:right;">
                                <div style="font-size:18px; font-weight:700; color:#6366f1;">RM {s['price']:.2f}</div>
                                <span class="sched-seats {seat_cls}">{seat_txt}</span>
                            </div>
                        </div>
                    </div>
                    """, unsafe_allow_html=True)
                with col2:
                    if seats > 0:
                        if st.button("🪑 Select", key=f"select_{i}", use_container_width=True):
                            seat_info = get_seat_info(s["id"])
                            if seat_info:
                                st.session_state.selected_schedule = s
                                st.session_state.seat_info = seat_info
                                st.session_state.mode = "seat_select"
                                st.rerun()
                            else:
                                st.error("Failed to load seat info.")
                    else:
                        st.button("Full", key=f"full_{i}", disabled=True, use_container_width=True)

        elif st.session_state.get("book_schedules") is not None and len(st.session_state.book_schedules) == 0:
            st.warning("No buses found for this route and date. Try a different date.")

elif mode == "seat_select":
    with st.container(border=True):
        st.markdown("#### 🪑 Select Your Seat")

        schedule = st.session_state.selected_schedule
        seat_info = st.session_state.seat_info

        if not schedule or not seat_info:
            st.error("Session expired. Please start over.")
            if st.button("🎫 Start Over"):
                st.session_state.mode = "book_select"
                st.rerun()
        else:
            # Show selected route info
            st.markdown(f"""
            <div class="sched-card">
                <div class="sched-route">{schedule['origin']} → {schedule['destination']}</div>
                <div class="sched-time">🕐 {schedule['departure_time']} | 🚌 {schedule['bus_type']}</div>
                <div class="sched-price">RM {schedule['price']:.2f}</div>
            </div>
            """, unsafe_allow_html=True)

            st.markdown("---")

            # Generate and display seat map (cached)
            seat_map_bytes = cached_seat_map(
                total_seats=seat_info["total_seats"],
                seats_per_row=seat_info["seats_per_row"],
                layout=seat_info["seat_layout"],
                occupied_seats=tuple(seat_info["occupied_seats"]),
                selected_seats=(),
            )

            col1, col2 = st.columns([1, 1])

            with col1:
                st.image(seat_map_bytes, caption="Seat Map", use_container_width=True)

                # Legend
                st.markdown("""
                <div style="display:flex; gap:20px; justify-content:center; margin-top:10px;">
                    <div style="display:flex; align-items:center; gap:5px;">
                        <div style="width:20px; height:20px; background:#3B82F6; border-radius:4px;"></div>
                        <span style="font-size:12px;">Available</span>
                    </div>
                    <div style="display:flex; align-items:center; gap:5px;">
                        <div style="width:20px; height:20px; background:#EF4444; border-radius:4px;"></div>
                        <span style="font-size:12px;">Occupied</span>
                    </div>
                </div>
                """, unsafe_allow_html=True)

            with col2:
                # Seat selection dropdown (only available seats)
                available_seats = seat_info["available_seats"]
                if not available_seats:
                    st.error("No seats available for this schedule.")
                else:
                    selected_seat = st.selectbox(
                        "Choose your seat",
                        options=available_seats,
                        format_func=lambda x: f"Seat {x}"
                    )

                    st.markdown("---")
                    st.markdown("**Passenger Details**")

                    name = st.text_input("Full Name *", value=st.session_state.passenger_name, placeholder="Ahmad bin Ali", key="seat_name")
                    phone = st.text_input("Phone *", value=st.session_state.passenger_phone, placeholder="0123456789", key="seat_phone")

                    st.markdown("---")

                    c1, c2, c3 = st.columns(3)
                    with c1:
                        if st.button("📋 Review Booking", type="primary", use_container_width=True):
                            if not name or not phone:
                                st.error("Name and phone are required.")
                            else:
                                # Store pending booking for confirmation
                                st.session_state.pending_booking = {
                                    "schedule_id": schedule["id"],
                                    "schedule": schedule,
                                    "seat_number": selected_seat,
                                    "passenger_name": name,
                                    "passenger_phone": phone,
                                }
                                st.session_state.mode = "booking_confirm"
                                st.rerun()
                    with c2:
                        if st.button("⬅️ Back", use_container_width=True):
                            st.session_state.selected_schedule = None
                            st.session_state.seat_info = None
                            st.session_state.mode = "book_select"
                            st.rerun()
                    with c3:
                        if st.button("❌ Cancel", use_container_width=True):
                            st.session_state.selected_schedule = None
                            st.session_state.seat_info = None
                            st.session_state.book_schedules = []
                            st.session_state.mode = None
                            st.rerun()

elif mode == "booking_confirm":
    # ── Booking Confirmation Step ─────────────────────────────────────────────
    pending = st.session_state.pending_booking

    if not pending:
        st.error("No pending booking found. Please start over.")
        if st.button("🎫 Start Over"):
            st.session_state.mode = "book_select"
            st.rerun()
    else:
        schedule = pending["schedule"]

        with st.container(border=True):
            st.markdown("#### ✅ Confirm Your Booking")
            st.markdown("Please review your booking details before confirming.")

            st.markdown("---")

            # Booking Summary Card
            bus_type = schedule.get('bus_type') or 'Standard'
            st.success("**Booking Summary**")
            c1, c2 = st.columns(2)
            with c1:
                st.markdown(f"**Route:** {schedule['origin']} → {schedule['destination']}")
                st.markdown(f"**Seat Number:** Seat {pending['seat_number']}")
                st.markdown(f"**Passenger:** {pending['passenger_name']}")
            with c2:
                st.markdown(f"**Departure:** {schedule['departure_time']}")
                st.markdown(f"**Bus Type:** {bus_type}")
                st.markdown(f"**Phone:** {pending['passenger_phone']}")
            st.markdown("---")
            st.metric("Total Amount", f"RM {schedule['price']:.2f}")

            st.warning("⚠️ **Please verify all details are correct.** Once confirmed, you will have 10 minutes to complete payment.")

            st.markdown("---")

            c1, c2, c3 = st.columns(3)
            with c1:
                if st.button("✅ Confirm & Book", type="primary", use_container_width=True):
                    add_msg("user", f"Confirm booking: Seat {pending['seat_number']} on {schedule['origin']} → {schedule['destination']} for {pending['passenger_name']}")

                    # Execute the actual booking
                    result, error = book_with_seat(
                        pending["schedule_id"],
                        pending["passenger_name"],
                        pending["passenger_phone"],
                        pending["seat_number"]
                    )

                    if result:
                        add_msg("assistant", f"✅ Booking confirmed! Seat **{pending['seat_number']}** reserved. Please complete payment within the deadline.", {"booking": result})
                    else:
                        add_msg("assistant", f"❌ Booking failed: {error}")

                    # Clear all booking flow state
                    st.session_state.pending_booking = None
                    st.session_state.selected_schedule = None
                    st.session_state.seat_info = None
                    st.session_state.book_schedules = []
                    st.session_state.mode = None
                    st.rerun()

            with c2:
                if st.button("✏️ Edit Details", use_container_width=True):
                    # Go back to seat selection with data preserved
                    st.session_state.mode = "seat_select"
                    st.rerun()

            with c3:
                if st.button("❌ Cancel", use_container_width=True):
                    st.session_state.pending_booking = None
                    st.session_state.selected_schedule = None
                    st.session_state.seat_info = None
                    st.session_state.book_schedules = []
                    st.session_state.mode = None
                    st.rerun()

elif mode == "my_bookings":
    with st.container(border=True):
        st.markdown("#### 📋 My Bookings")
        try:
            resp = requests.get(
                f"{FASTAPI_URL}/passengers/{st.session_state.passenger_id}/bookings",
                timeout=10,
            )
            resp.raise_for_status()
            bookings = resp.json()
        except Exception:
            bookings = []

        if not bookings:
            st.info("You don't have any bookings yet. Use **Book Ticket** to get started!")
        else:
            for b in bookings:
                status = b.get("status", "unknown")
                status_map = {
                    "confirmed": ("✅ Confirmed", "#22c55e"),
                    "pending_payment": ("⏳ Pending Payment", "#f59e0b"),
                    "cancelled": ("❌ Cancelled", "#ef4444"),
                }
                status_display, status_color = status_map.get(status, (status.replace("_", " ").title(), "#6b7280"))
                st.markdown(f"""
                <div class="receipt-card">
                    <div class="receipt-id">#{b.get('booking_id')}</div>
                    <div class="receipt-row"><span class="receipt-label">Route</span><span class="receipt-value">{b.get('origin')} → {b.get('destination')}</span></div>
                    <div class="receipt-row"><span class="receipt-label">Departure</span><span class="receipt-value">{b.get('departure_time')}</span></div>
                    <div class="receipt-row"><span class="receipt-label">Seat</span><span class="receipt-value">{b.get('seat_number')}</span></div>
                    <div class="receipt-row"><span class="receipt-label">Price</span><span class="receipt-value">RM {b.get('total_price', 0):.2f}</span></div>
                    <div class="receipt-row"><span class="receipt-label">Status</span><span class="receipt-value" style="color:{status_color}">{status_display}</span></div>
                </div>
                """, unsafe_allow_html=True)

        if st.button("← Back to chat", use_container_width=True):
            st.session_state.mode = None
            st.rerun()

elif mode == "check":
    with st.container(border=True):
        st.markdown("#### 🔎 Check Booking")
        booking_id = st.number_input("Booking ID", min_value=1, step=1)
        c1, c2 = st.columns(2)
        with c1:
            if st.button("🔍 Check", type="primary", use_container_width=True):
                add_msg("user", f"Check booking #{int(booking_id)}")
                result = check_direct(int(booking_id))
                if result:
                    add_msg("assistant", f"Here are the details for booking **#{int(booking_id)}**:", {"booking": {"booking": result}})
                else:
                    add_msg("assistant", f"❌ Booking #{int(booking_id)} not found.")
                st.session_state.mode = None
                st.rerun()
        with c2:
            if st.button("Cancel", use_container_width=True):
                st.session_state.mode = None
                st.rerun()

elif mode == "cancel":
    with st.container(border=True):
        st.markdown("#### ❌ Cancel Booking")
        booking_id = st.number_input("Booking ID", min_value=1, step=1)
        c1, c2 = st.columns(2)
        with c1:
            if st.button("❌ Cancel Booking", type="primary", use_container_width=True):
                add_msg("user", f"Cancel booking #{int(booking_id)}")
                success = cancel_direct(int(booking_id))
                if success:
                    add_msg("assistant", f"✅ Booking #{int(booking_id)} has been cancelled.")
                else:
                    add_msg("assistant", f"❌ Could not cancel booking #{int(booking_id)}.")
                st.session_state.mode = None
                st.rerun()
        with c2:
            if st.button("Keep", use_container_width=True):
                st.session_state.mode = None
                st.rerun()

# ── Chat Input ─────────────────────────────────────────────────────────────────
st.markdown("---")
if user_input := st.chat_input("Ask me anything..."):
    add_msg("user", user_input)

    # Render the user message immediately
    render_message({"role": "user", "content": user_input})

    # Create placeholder for streaming response
    response_placeholder = st.empty()

    # Show thinking indicator initially
    with response_placeholder.container():
        render_thinking_indicator()

    # Stream response — placeholder updates progressively with tokens
    full_text = call_fastapi_stream(user_input, response_placeholder)

    if full_text:
        add_msg("assistant", full_text)
    else:
        add_msg("assistant", t("error"))
    st.rerun()
