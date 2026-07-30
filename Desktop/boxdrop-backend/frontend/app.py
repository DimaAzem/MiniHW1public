"""
BoxDrop Streamlit Frontend — Technion course submission
====================================================================
A single-file Streamlit app for the BoxDrop package-manager backend:
real JWT authentication, a package dashboard with Return-to-Sender expiry
tracking, a Smart Pickup Route Optimizer (TSP), and a Carrier Delay
Predictor.

Architecture (top to bottom):
    1. Configuration & page setup
    2. Custom CSS (dark "tech" theme)
    3. Session state initialization
    4. Backend API client (thread-safe, JWT-aware)
    5. UI helpers (badges, cards, formatting)
    6. Pages (Login/Register, Dashboard & Packages, Route Optimizer,
       Carrier Predictor, Settings & Profile)
    7. Sidebar & router
    8. Entrypoint

Authentication is real: registration and login hit the FastAPI backend
(POST /api/auth/register, POST /api/auth/login), which bcrypt-hashes
passwords and issues a signed JWT. Every subsequent request attaches that
token as `Authorization: Bearer <token>` - nothing here is hardcoded or
simulated.
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from datetime import time as dt_time
from typing import Optional

import pandas as pd
import requests
import streamlit as st
from dotenv import load_dotenv

load_dotenv()  # Loads a .env from the project root for local dev; harmless no-op if absent.

# =============================================================================
# 1. CONFIGURATION & PAGE SETUP
# =============================================================================
BACKEND_API_URL_DEFAULT = os.getenv("BACKEND_API_URL", "http://localhost:8000/api").rstrip("/")

REQUEST_TIMEOUT_SECONDS = 8

# Carriers the backend's predictive engines have historical data for.
KNOWN_CARRIERS = ["DHL", "FedEx", "UPS", "Israel Post", "USPS", "Amazon Logistics", "Other"]
PACKAGE_STATUSES = ["In Transit", "Ready for Pickup", "Delivered"]

EXPIRING_SOON_THRESHOLD_HOURS = 48

st.set_page_config(
    page_title="BoxDrop | Smart Package Manager",
    page_icon="📦",
    layout="wide",
    initial_sidebar_state="expanded",
)


# =============================================================================
# 2. CUSTOM CSS - glassmorphic dark theme (navy/slate + neon cyan/purple)
# =============================================================================
def inject_custom_css() -> None:
    """Injects a single CSS block. Called once per script run - cheap and idempotent."""
    st.markdown(
        """
        <style>
        /* Hide default Streamlit chrome so this reads as a standalone app.
           IMPORTANT: never hide the <header>/stToolbar CONTAINERS wholesale -
           the sidebar's own collapse/expand toggle lives inside them in
           current Streamlit versions, and hiding the container removes any
           way to reopen a collapsed sidebar. Target only the specific chrome
           widgets (menu, footer, deploy button, status spinner) instead. */
        #MainMenu, footer,
        [data-testid="stDecoration"],
        [data-testid="stStatusWidget"],
        [data-testid="stAppDeployButton"] {
            visibility: hidden;
            display: none;
        }

        /* Make the header bar itself blend away visually without removing it
           from the layout, so the sidebar toggle inside it stays clickable. */
        [data-testid="stHeader"] {
            background: transparent;
        }

        /* Belt-and-suspenders: whatever else changes above, the sidebar's own
           collapse/expand control must always stay visible and clickable. */
        [data-testid="stSidebarCollapsedControl"],
        [data-testid="stSidebarCollapsedControl"] * {
            visibility: visible !important;
            display: flex !important;
            opacity: 1 !important;
        }

        .stApp {
            background: radial-gradient(circle at 15% 0%, #14203a 0%, #0f172a 45%, #0b0f19 100%);
            color: #e2e8f0;
        }

        section[data-testid="stSidebar"] {
            background: rgba(11, 15, 25, 0.85);
            backdrop-filter: blur(14px);
            -webkit-backdrop-filter: blur(14px);
            border-right: 1px solid rgba(255, 255, 255, 0.07);
        }

        /* ---------- Glass surfaces: KPI cards, bordered containers, forms ---------- */
        .metric-card,
        div[data-testid="stVerticalBlockBorderWrapper"],
        [data-testid="stForm"],
        .alert-row {
            background: rgba(255, 255, 255, 0.035);
            backdrop-filter: blur(12px);
            -webkit-backdrop-filter: blur(12px);
            border: 1px solid rgba(255, 255, 255, 0.08);
            border-radius: 16px;
        }

        .metric-card {
            padding: 1.35rem;
            text-align: center;
            transition: transform .18s ease, box-shadow .18s ease;
        }
        .metric-card:hover { transform: translateY(-2px); }
        .metric-card__icon { font-size: 1.7rem; }
        .metric-card__value {
            font-size: 2.1rem; font-weight: 800; margin: .3rem 0;
            background: linear-gradient(90deg, #38bdf8, #a78bfa);
            -webkit-background-clip: text; background-clip: text; -webkit-text-fill-color: transparent;
        }
        .metric-card__label {
            font-size: .76rem; color: #94a3b8;
            text-transform: uppercase; letter-spacing: .07em;
        }
        /* Neon accent borders + glow per KPI priority */
        .metric-card--blue   { border-color: rgba(56, 189, 248, .5);  box-shadow: 0 0 22px rgba(56, 189, 248, .16); }
        .metric-card--green  { border-color: rgba(16, 185, 129, .5);  box-shadow: 0 0 22px rgba(16, 185, 129, .16); }
        .metric-card--orange { border-color: rgba(249, 115, 22, .55); box-shadow: 0 0 22px rgba(249, 115, 22, .18); }
        .metric-card--red    { border-color: rgba(239, 68, 68, .55);  box-shadow: 0 0 22px rgba(239, 68, 68, .18); }

        [data-testid="stForm"] { padding: 1.4rem 1.5rem; }

        /* ---------- Glass input fields ---------- */
        [data-testid="stTextInput"] input,
        [data-testid="stTextArea"] textarea,
        [data-testid="stNumberInput"] input,
        [data-testid="stDateInput"] input,
        [data-testid="stTimeInput"] input,
        [data-testid="stSelectbox"] div[data-baseweb="select"] > div,
        [data-testid="stMultiSelect"] div[data-baseweb="select"] > div {
            background: rgba(255, 255, 255, 0.045) !important;
            border: 1px solid rgba(255, 255, 255, 0.1) !important;
            border-radius: 10px !important;
            color: #e2e8f0 !important;
        }

        /* ---------- Badges (risk/status - semantic colors kept, glassified) ---------- */
        .badge {
            display: inline-block;
            padding: .3rem .7rem;
            border-radius: 999px;
            font-size: .78rem;
            font-weight: 700;
            letter-spacing: .02em;
            margin-right: .3rem;
            backdrop-filter: blur(6px);
        }
        .badge-high   { background: rgba(239,68,68,.16);  color: #f87171; border: 1px solid rgba(239,68,68,.45); }
        .badge-medium { background: rgba(245,158,11,.16); color: #fbbf24; border: 1px solid rgba(245,158,11,.45); }
        .badge-low    { background: rgba(34,197,94,.16);  color: #4ade80; border: 1px solid rgba(34,197,94,.45); }

        .badge-status-transit   { background: rgba(59,130,246,.16);  color: #60a5fa; border: 1px solid rgba(59,130,246,.45); }
        .badge-status-ready     { background: rgba(45,212,191,.16); color: #2dd4bf; border: 1px solid rgba(45,212,191,.45); }
        .badge-status-delivered { background: rgba(148,163,184,.16); color: #94a3b8; border: 1px solid rgba(148,163,184,.45); }

        .alert-row {
            border-left: 3px solid #f59e0b;
            padding: .7rem 1rem;
            margin-bottom: .6rem;
        }

        /* ---------- Buttons: smooth hover lift + glow ---------- */
        div.stButton > button {
            border-radius: 10px;
            font-weight: 700;
            background: rgba(255, 255, 255, 0.04);
            border: 1px solid rgba(255, 255, 255, 0.1);
            color: #e2e8f0;
            transition: transform .15s ease, box-shadow .15s ease, background .15s ease, border-color .15s ease;
        }
        div.stButton > button:hover {
            transform: translateY(-1px);
            box-shadow: 0 8px 22px rgba(56, 189, 248, .22);
            background: rgba(56, 189, 248, 0.09);
            border-color: rgba(56, 189, 248, .45);
        }
        div.stButton > button[kind="primary"] {
            background: linear-gradient(135deg, rgba(56,189,248,.28), rgba(167,139,250,.28));
            border: 1px solid rgba(56, 189, 248, .55);
            box-shadow: 0 0 16px rgba(56, 189, 248, .22);
        }
        div.stButton > button[kind="primary"]:hover {
            box-shadow: 0 10px 26px rgba(167, 139, 250, .32);
        }

        /* Sidebar nav buttons: full-width, left-aligned, active = glowing left border */
        section[data-testid="stSidebar"] div.stButton > button {
            justify-content: flex-start;
            text-align: left;
            border-radius: 10px;
            margin-bottom: .3rem;
        }
        section[data-testid="stSidebar"] div.stButton > button[kind="primary"] {
            border-left: 3px solid #38bdf8;
            background: rgba(56, 189, 248, 0.12);
            box-shadow: inset 0 0 0 1px rgba(56,189,248,.25), 0 0 14px rgba(56, 189, 248, .2);
            color: #7dd3fc;
        }
        section[data-testid="stSidebar"] div.stButton > button[kind="secondary"] {
            background: transparent;
            border: 1px solid transparent;
            border-left: 3px solid transparent;
            color: #cbd5e1;
        }
        section[data-testid="stSidebar"] div.stButton > button[kind="secondary"]:hover {
            background: rgba(255, 255, 255, 0.05);
            border-left: 3px solid rgba(56, 189, 248, .35);
        }

        /* ---------- Alerts: sleek transparent glass toasts, not solid blocks ---------- */
        [data-testid="stAlert"], [data-testid="stNotification"] {
            background: rgba(255, 255, 255, 0.04) !important;
            backdrop-filter: blur(10px);
            -webkit-backdrop-filter: blur(10px);
            border: 1px solid rgba(255, 255, 255, 0.1) !important;
            border-radius: 12px !important;
        }
        [data-testid="stAlertContentSuccess"] { border-left: 3px solid #10b981 !important; padding-left: .6rem; }
        [data-testid="stAlertContentInfo"]    { border-left: 3px solid #38bdf8 !important; padding-left: .6rem; }
        [data-testid="stAlertContentWarning"] { border-left: 3px solid #f59e0b !important; padding-left: .6rem; }
        [data-testid="stAlertContentError"]   { border-left: 3px solid #ef4444 !important; padding-left: .6rem; }

        [data-testid="stSpinner"] div {
            border-top-color: #a78bfa !important;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


# =============================================================================
# 3. SESSION STATE
# =============================================================================
def init_session_state() -> None:
    """Sets every key this app relies on exactly once per session."""
    defaults = {
        "logged_in": False,
        "username": None,
        "access_token": None,
        "backend_url": BACKEND_API_URL_DEFAULT,
        "current_page": "📦 My Dashboard & Packages",
    }
    for key, value in defaults.items():
        st.session_state.setdefault(key, value)


# =============================================================================
# 4. BACKEND API CLIENT
# =============================================================================
# IMPORTANT: these functions take `base_url` (and `token` where relevant) as
# explicit arguments and never touch st.session_state directly, so they stay
# safe to call from any context, including a future worker thread.
def api_request(
    method: str, path: str, base_url: str, token: Optional[str] = None, **kwargs
) -> tuple[bool, dict, Optional[int]]:
    """
    Low-level HTTP helper shared by every backend call.

    Returns (ok, payload, status_code). Never raises - all network failures
    are converted into a friendly message so the UI layer can just check
    `ok` and display a banner instead of a raw stack trace.
    """
    url = f"{base_url.rstrip('/')}{path}"
    headers = kwargs.pop("headers", {}) or {}
    if token:
        headers["Authorization"] = f"Bearer {token}"

    try:
        response = requests.request(method, url, timeout=REQUEST_TIMEOUT_SECONDS, headers=headers, **kwargs)
    except requests.exceptions.ConnectionError:
        return False, {"message": "Could not reach the BoxDrop backend. Is it running?"}, None
    except requests.exceptions.Timeout:
        return False, {"message": "The request to the backend timed out."}, None
    except requests.exceptions.RequestException as exc:
        return False, {"message": f"Unexpected network error: {exc}"}, None

    if response.status_code == 204:
        return True, {}, 204

    try:
        payload = response.json()
    except ValueError:
        payload = {}

    if response.status_code >= 400:
        error_body = payload.get("error", {}) if isinstance(payload, dict) else {}
        message = error_body.get("message", f"Backend returned HTTP {response.status_code}")
        return False, {"message": message, "code": error_body.get("code")}, response.status_code

    return True, payload, response.status_code


def fetch_health(base_url: str) -> dict:
    ok, payload, _ = api_request("GET", "/health", base_url)
    return payload if ok else {"status": "unreachable", "database": "unknown"}


def register_user_via_backend(username: str, password: str, base_url: str) -> tuple[bool, dict, Optional[int]]:
    return api_request("POST", "/auth/register", base_url, json={"username": username, "password": password})


def login_via_backend(username: str, password: str, base_url: str) -> tuple[bool, dict, Optional[int]]:
    return api_request("POST", "/auth/login", base_url, json={"username": username, "password": password})


def fetch_packages(base_url: str, token: str) -> list:
    ok, payload, _ = api_request("GET", "/packages", base_url, token=token)
    return payload if ok and isinstance(payload, list) else []


def create_package_via_backend(payload: dict, base_url: str, token: str) -> tuple[bool, dict, Optional[int]]:
    return api_request("POST", "/packages", base_url, token=token, json=payload)


def update_package_via_backend(
    tracking_number: str, updates: dict, base_url: str, token: str
) -> tuple[bool, dict, Optional[int]]:
    return api_request("PATCH", f"/packages/{tracking_number}", base_url, token=token, json=updates)


def delete_package_via_backend(tracking_number: str, base_url: str, token: str) -> tuple[bool, dict, Optional[int]]:
    return api_request("DELETE", f"/packages/{tracking_number}", base_url, token=token)


def optimize_route_via_backend(
    tracking_numbers: list, base_url: str, token: str
) -> tuple[bool, dict, Optional[int]]:
    return api_request(
        "POST", "/routing/optimize", base_url, token=token, json={"tracking_numbers": tracking_numbers}
    )


def predict_carrier_via_backend(carrier: str, base_url: str, token: str) -> tuple[bool, dict, Optional[int]]:
    return api_request("POST", "/analytics/predict", base_url, token=token, json={"carrier": carrier})


@st.cache_data(ttl=10, show_spinner=False)
def get_cached_packages(base_url: str, token: str) -> list:
    """Cached briefly so navigating between pages doesn't hammer the backend."""
    return fetch_packages(base_url, token)


# =============================================================================
# 5. UI HELPERS
# =============================================================================
def risk_tier(probability: float) -> str:
    pct = probability * 100
    if pct > 75:
        return "high"
    if pct >= 40:
        return "medium"
    return "low"


def risk_badge_html(probability: float) -> str:
    pct = probability * 100
    tier = risk_tier(probability)
    label = {"high": "🔴 High Risk", "medium": "🟡 Medium Risk", "low": "🟢 Low Risk"}[tier]
    return f'<span class="badge badge-{tier}">{label} ({pct:.0f}%)</span>'


def status_badge_html(status: str) -> str:
    styles = {
        "In Transit": ("badge-status-transit", "🚚"),
        "Ready for Pickup": ("badge-status-ready", "📍"),
        "Delivered": ("badge-status-delivered", "✅"),
    }
    css_class, icon = styles.get(status, ("badge-status-transit", "📦"))
    return f'<span class="badge {css_class}">{icon} {status}</span>'


def _parse_iso(value) -> Optional[datetime]:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _format_dt(value) -> str:
    dt = _parse_iso(value)
    return dt.strftime("%b %d, %Y %H:%M") if dt else "—"


def metric_card(label: str, value, accent: str, icon: str) -> None:
    st.markdown(
        f"""
        <div class="metric-card metric-card--{accent}">
            <div class="metric-card__icon">{icon}</div>
            <div class="metric-card__value">{value}</div>
            <div class="metric-card__label">{label}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_package_card(pkg: dict) -> None:
    """Renders a single package as a self-contained, color-coded card."""
    tier = risk_tier(pkg["delay_probability"])
    border_color = {"high": "#ef4444", "medium": "#f59e0b", "low": "#22c55e"}[tier]

    with st.container(border=True):
        st.markdown(
            f"""
            <div style="border-left: 4px solid {border_color}; padding-left: .7rem; margin-bottom: .4rem;">
                <div style="font-size:1.05rem; font-weight:800;">{pkg['carrier']}</div>
                <div style="color:#9aa4c2; font-size:.82rem;">#{pkg['tracking_number']}</div>
            </div>
            """,
            unsafe_allow_html=True,
        )
        st.markdown(status_badge_html(pkg["status"]) + risk_badge_html(pkg["delay_probability"]), unsafe_allow_html=True)
        st.caption(f"📅 Est. delivery: {_format_dt(pkg['estimated_delivery'])}")
        if pkg.get("pickup_location"):
            st.caption(f"📍 {pkg['pickup_location']}")
        if pkg.get("expiry_hours_left") is not None:
            hours = pkg["expiry_hours_left"]
            urgency = "🔴" if hours < EXPIRING_SOON_THRESHOLD_HOURS else "🟢"
            st.caption(f"{urgency} {hours:.0f}h left before Return-to-Sender risk")

        if tier in ("high", "medium"):
            with st.expander("Why this risk?"):
                for factor in pkg.get("contributing_factors", []):
                    st.write(f"- {factor}")

        action_cols = st.columns(2)
        with action_cols[0]:
            if pkg["status"] != "Delivered" and st.button("✅ Delivered", key=f"deliver_{pkg['tracking_number']}"):
                ok, _payload, _status = update_package_via_backend(
                    pkg["tracking_number"], {"status": "Delivered"}, st.session_state.backend_url, st.session_state.access_token
                )
                if ok:
                    get_cached_packages.clear()
                    st.rerun()
        with action_cols[1]:
            if st.button("🗑️ Delete", key=f"delete_{pkg['tracking_number']}"):
                ok, _payload, _status = delete_package_via_backend(
                    pkg["tracking_number"], st.session_state.backend_url, st.session_state.access_token
                )
                if ok:
                    get_cached_packages.clear()
                    st.rerun()


# =============================================================================
# 6. PAGES
# =============================================================================
def _render_sign_in_form() -> None:
    with st.form("sign_in_form"):
        username = st.text_input("Username", placeholder="dima_a")
        password = st.text_input("Password", type="password", placeholder="••••••••")
        submitted = st.form_submit_button("Sign In", width="stretch", type="primary")

    if not submitted:
        return

    if not username.strip() or not password:
        st.error("Enter both a username and a password.")
        return

    ok, payload, _status = login_via_backend(username.strip(), password, st.session_state.backend_url)
    if not ok:
        st.error(payload.get("message", "Invalid username or password."))
        return

    st.session_state.logged_in = True
    st.session_state.username = payload["username"]
    st.session_state.access_token = payload["access_token"]
    st.session_state.current_page = "📦 My Dashboard & Packages"
    st.rerun()


def _render_sign_up_form() -> None:
    with st.form("sign_up_form", clear_on_submit=True):
        username = st.text_input("Choose a Username", placeholder="dima_a")
        col1, col2 = st.columns(2)
        with col1:
            password = st.text_input("Choose a Password", type="password", placeholder="At least 8 characters")
        with col2:
            confirm_password = st.text_input("Confirm Password", type="password")
        submitted = st.form_submit_button("Create Account", width="stretch", type="primary")

    if not submitted:
        return

    if password != confirm_password:
        st.error("Passwords do not match.")
        return
    if len(password) < 8:
        st.error("Password must be at least 8 characters.")
        return
    if not username.strip():
        st.error("Username is required.")
        return

    ok, payload, _status = register_user_via_backend(username.strip(), password, st.session_state.backend_url)
    if not ok:
        st.error(payload.get("message", "Registration failed."))
        return

    st.success(f"Account '{payload['username']}' created! Switch to Sign In to log in.")
    # The "Auth mode" radio (key="auth_mode") has already been instantiated
    # earlier in THIS script run, so Streamlit forbids writing
    # st.session_state.auth_mode directly here. Stash the desired value and
    # rerun; render_login_page() applies it before the widget is recreated.
    st.session_state["_pending_auth_mode"] = "Sign In"
    st.rerun()


def render_login_page() -> None:
    """Real authentication only - registration/login both hit the FastAPI backend."""
    if "_pending_auth_mode" in st.session_state:
        st.session_state.auth_mode = st.session_state.pop("_pending_auth_mode")

    _, center, _ = st.columns([1, 1.2, 1])
    with center:
        st.markdown("# 📦 BoxDrop")
        st.markdown("#### Smart Package Manager — Route Optimization & Predictive Analytics")
        st.write("")

        st.session_state.setdefault("auth_mode", "Sign In")
        auth_mode = st.radio(
            "Auth mode", ["Sign In", "Sign Up"], horizontal=True, label_visibility="collapsed", key="auth_mode"
        )

        if auth_mode == "Sign In":
            _render_sign_in_form()
        else:
            _render_sign_up_form()


def render_manual_entry_expander() -> None:
    with st.expander("➕ Add a Package Manually"):
        # Status lives OUTSIDE the form so changing it reruns the script
        # immediately, letting the pickup fields below react to it - widgets
        # inside a form only fire on submit, so this couldn't be reactive in there.
        status_choice = st.selectbox("Status", PACKAGE_STATUSES, key="manual_add_status")

        with st.form("manual_package_form", clear_on_submit=True):
            col1, col2 = st.columns(2)
            with col1:
                tracking_number = st.text_input("Tracking Number*")
                carrier_choice = st.selectbox("Carrier*", KNOWN_CARRIERS)
                carrier_other = st.text_input("Carrier name (if 'Other')") if carrier_choice == "Other" else ""
            with col2:
                delivery_date = st.date_input("Estimated Delivery Date*")
                delivery_time = st.time_input("Estimated Delivery Time", value=dt_time(12, 0))

            pickup_location = None
            arrival_dt = None
            if status_choice == "Ready for Pickup":
                st.caption("📍 Pickup details (starts the Return-to-Sender expiry countdown)")
                pickup_location = st.text_input("Pickup Location", placeholder="Ullmann Building")
                arrival_col1, arrival_col2 = st.columns(2)
                with arrival_col1:
                    arrival_date_input = st.date_input("Arrival Date", value=datetime.now().date())
                with arrival_col2:
                    arrival_time_input = st.time_input("Arrival Time", value=dt_time(12, 0))
                arrival_dt = datetime.combine(arrival_date_input, arrival_time_input)

            submitted = st.form_submit_button("💾 Save Package", width="stretch", type="primary")
            if submitted:
                carrier = (carrier_other or "").strip() if carrier_choice == "Other" else carrier_choice
                if not tracking_number.strip() or not carrier:
                    st.error("Tracking number and carrier are required.")
                    return

                payload = {
                    "tracking_number": tracking_number.strip(),
                    "carrier": carrier,
                    "status": status_choice,
                    "estimated_delivery": datetime.combine(delivery_date, delivery_time).isoformat(),
                }
                if pickup_location:
                    payload["pickup_location"] = pickup_location.strip()
                if arrival_dt:
                    payload["arrival_date"] = arrival_dt.isoformat()

                ok, body, _status = create_package_via_backend(payload, st.session_state.backend_url, st.session_state.access_token)
                if ok:
                    get_cached_packages.clear()
                    st.success(f"Package {tracking_number} saved!")
                    st.rerun()
                else:
                    st.error(f"Could not save package: {body.get('message')}")


def render_expiring_soon_section(expiring: list) -> None:
    st.subheader("⏰ Expiring Soon — Return-to-Sender Risk")
    if not expiring:
        st.success("Nothing at risk of Return-to-Sender right now. ✅")
        st.divider()
        return

    for pkg in sorted(expiring, key=lambda p: p["expiry_hours_left"]):
        with st.container(border=True):
            st.markdown(
                f"""
                <div class="alert-row">
                    <b>{pkg['carrier']}</b> — #{pkg['tracking_number']}
                    &nbsp;&middot;&nbsp; {pkg['pickup_location']}
                    &nbsp;&middot;&nbsp; <b>{pkg['expiry_hours_left']:.0f}h</b> left
                </div>
                """,
                unsafe_allow_html=True,
            )
            if st.button("✅ Mark as Delivered", key=f"expiring_deliver_{pkg['tracking_number']}"):
                ok, _payload, _status = update_package_via_backend(
                    pkg["tracking_number"], {"status": "Delivered"}, st.session_state.backend_url, st.session_state.access_token
                )
                if ok:
                    get_cached_packages.clear()
                    st.rerun()
    st.divider()


def render_backend_offline_banner(base_url: str) -> None:
    st.markdown(
        f"""
        <div style="background: linear-gradient(160deg, #2a1418 0%, #1a1220 100%);
                    border: 1px solid #ef4444; border-radius: 14px; padding: 1.5rem; margin-bottom: 1rem;">
            <div style="font-size:1.3rem; font-weight:800; color:#f87171;">🔴 Backend Status: Offline</div>
            <div style="color:#c9ccd8; margin-top:.4rem;">
                BoxDrop cannot reach the FastAPI backend at <code>{base_url}</code>.
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    st.markdown("#### 🛠️ Troubleshooting checklist")
    st.markdown(
        "- **Is the backend actually running?** Check your terminal, or `docker compose ps` if you're using Docker.\n"
        "- **Is port 8000 already taken by something else?**\n"
        "- **Is MongoDB up?** `/api/health` only reports `database: connected` once Mongo answers.\n"
        "- **Check the backend logs** for a startup error (`docker compose logs backend`)."
    )
    if st.button("🔁 Retry connection"):
        get_cached_packages.clear()
        st.rerun()


def render_dashboard_page() -> None:
    st.title("📦 My Dashboard & Packages")
    st.caption("Everything you're tracking, and what needs attention first.")

    health = fetch_health(st.session_state.backend_url)
    if health.get("status") == "unreachable":
        render_backend_offline_banner(st.session_state.backend_url)
        return

    if st.button("🔄 Refresh Data"):
        get_cached_packages.clear()
        st.rerun()

    packages = get_cached_packages(st.session_state.backend_url, st.session_state.access_token)

    total = len(packages)
    ready_for_pickup = [p for p in packages if p["status"] == "Ready for Pickup"]
    expiring_soon = [
        p for p in ready_for_pickup
        if p.get("expiry_hours_left") is not None and p["expiry_hours_left"] < EXPIRING_SOON_THRESHOLD_HOURS
    ]

    render_expiring_soon_section(expiring_soon)

    c1, c2, c3 = st.columns(3)
    with c1:
        metric_card("Total Packages", total, "blue", "📦")
    with c2:
        metric_card("Ready for Pickup", len(ready_for_pickup), "green", "📍")
    with c3:
        metric_card("Expiring Soon", len(expiring_soon), "orange", "⏰")

    st.write("")
    render_manual_entry_expander()

    st.write("")
    if not packages:
        st.info("No packages tracked yet. Add one manually above to get started.")
        return

    st.subheader("📦 Tracked Packages")
    search = st.text_input("🔍 Search by tracking number or carrier", "")
    filtered = [
        p for p in packages
        if not search or search.lower() in p["tracking_number"].lower() or search.lower() in p["carrier"].lower()
    ]
    if not filtered:
        st.info("No packages match your search.")
        return

    columns_per_row = 3
    for row_start in range(0, len(filtered), columns_per_row):
        row = filtered[row_start: row_start + columns_per_row]
        cols = st.columns(columns_per_row)
        for col, pkg in zip(cols, row):
            with col:
                render_package_card(pkg)


def render_route_optimizer_page() -> None:
    st.title("🗺️ Smart Pickup Route Optimizer")
    st.caption("A greedy nearest-neighbor TSP heuristic finds a short route across your ready-for-pickup packages.")

    health = fetch_health(st.session_state.backend_url)
    if health.get("status") == "unreachable":
        render_backend_offline_banner(st.session_state.backend_url)
        return

    packages = get_cached_packages(st.session_state.backend_url, st.session_state.access_token)
    ready = [p for p in packages if p["status"] == "Ready for Pickup" and p.get("pickup_location")]

    if not ready:
        st.info("No packages are 'Ready for Pickup' with a pickup location set yet. Add or update one from the Dashboard.")
        return

    options = {f"{p['tracking_number']} — {p['pickup_location']}": p["tracking_number"] for p in ready}
    selected_labels = st.multiselect("Select packages to include in the route", list(options.keys()), default=list(options.keys()))
    selected_tracking_numbers = [options[label] for label in selected_labels]

    if st.button("🗺️ Optimize Route", type="primary") and selected_tracking_numbers:
        ok, result, _status = optimize_route_via_backend(
            selected_tracking_numbers, st.session_state.backend_url, st.session_state.access_token
        )
        if not ok:
            st.error(result.get("message", "Could not compute a route."))
            return

        c1, c2, c3 = st.columns(3)
        with c1:
            metric_card("Total Distance", f"{result['total_distance_km']:.1f} km", "blue", "📏")
        with c2:
            metric_card("Est. Time", f"{result['estimated_time_minutes']:.0f} min", "green", "⏱️")
        with c3:
            metric_card("Time Saved", f"{result['estimated_time_saved_minutes']:.0f} min", "orange", "⚡")

        st.write("")
        st.subheader("Optimized stop order")
        stops_df = pd.DataFrame(
            [
                {"#": i + 1, "Location": stop["name"], "Leg Distance (km)": stop["leg_distance_km"]}
                for i, stop in enumerate(result["stops"])
            ]
        )
        st.dataframe(stops_df, width="stretch", hide_index=True)

        st.write("")
        st.subheader("Route map (simulated coordinates)")
        depot_point = pd.DataFrame([{"x": 0.0, "y": 0.0, "label": "BoxDrop Pickup Hub (start)"}])
        stop_points = pd.DataFrame([{"x": s["x"], "y": s["y"], "label": s["name"]} for s in result["stops"]])
        st.scatter_chart(pd.concat([depot_point, stop_points]), x="x", y="y")
        st.caption(
            "Points are simulated local coordinates (km), not real GPS - the table above is the authoritative visit order."
        )


def render_carrier_predictor_page() -> None:
    st.title("📈 Carrier Delay Predictor")
    st.caption("Check a carrier's forecasted delay risk and dynamic ETA before placing an order.")

    health = fetch_health(st.session_state.backend_url)
    if health.get("status") == "unreachable":
        render_backend_offline_banner(st.session_state.backend_url)
        return

    carrier = st.selectbox("Carrier", [c for c in KNOWN_CARRIERS if c != "Other"])

    if st.button("🔮 Predict Delay", type="primary"):
        ok, forecast, _status = predict_carrier_via_backend(carrier, st.session_state.backend_url, st.session_state.access_token)
        if not ok:
            st.error(forecast.get("message", "Could not fetch a forecast."))
            return

        tier = risk_tier(forecast["delay_probability"])
        c1, c2 = st.columns(2)
        with c1:
            metric_card("Delay Probability", f"{forecast['delay_probability'] * 100:.0f}%", {"high": "red", "medium": "orange", "low": "green"}[tier], "📊")
        with c2:
            metric_card("Dynamic ETA", f"{forecast['dynamic_eta_days']} days", "blue", "🚚")

        st.write("")
        st.markdown(risk_badge_html(forecast["delay_probability"]), unsafe_allow_html=True)
        st.write("")
        st.info(forecast["narrative"])

        with st.expander("Why this forecast?"):
            for factor in forecast["contributing_factors"]:
                st.write(f"- {factor}")


def render_settings_page() -> None:
    st.title("⚙️ Settings & Profile")

    with st.container(border=True):
        st.markdown(f"### 👤 {st.session_state.username}")
        st.caption("Signed in with a JWT session token issued by the BoxDrop backend.")

    st.write("")
    backend_url = st.text_input("Backend API URL", value=st.session_state.backend_url)
    if st.button("Save Backend URL"):
        st.session_state.backend_url = backend_url.rstrip("/")
        get_cached_packages.clear()
        st.success("Backend URL updated.")

    health = fetch_health(st.session_state.backend_url)
    if health.get("status") == "healthy":
        st.success(f"✅ Connected — database {health.get('database')}")
    elif health.get("status") == "degraded":
        st.warning("⚠️ Backend reachable but its database connection is degraded.")
    else:
        st.error("❌ Backend is unreachable.")

    st.write("")
    if st.button("🚪 Log Out", type="primary"):
        st.session_state.logged_in = False
        st.session_state.username = None
        st.session_state.access_token = None
        get_cached_packages.clear()
        st.rerun()


# =============================================================================
# 7. SIDEBAR & ROUTER
# =============================================================================
def render_sidebar() -> None:
    with st.sidebar:
        st.markdown("## 📦 BoxDrop")
        st.caption("Smart Package Manager")

        st.divider()

        if st.session_state.logged_in:
            # Custom nav: real st.button widgets (not raw HTML <button> tags -
            # those can't trigger a Streamlit rerun or touch session_state at
            # all without much heavier machinery). Each button's `type` flips
            # to "primary" for the active page, which the CSS above turns
            # into the glowing-left-border active state; clicking always
            # updates current_page and reruns, exactly as before.
            pages = [
                "📦 My Dashboard & Packages",
                "🗺️ Smart Route Optimizer",
                "📈 Carrier Delay Predictor",
                "⚙️ Settings & Profile",
            ]
            for page_name in pages:
                is_active = st.session_state.current_page == page_name
                if st.button(
                    page_name,
                    key=f"nav_{page_name}",
                    width="stretch",
                    type="primary" if is_active else "secondary",
                ):
                    st.session_state.current_page = page_name
                    st.rerun()
        else:
            st.info("🔑 Log in or register to continue.")


def main() -> None:
    inject_custom_css()
    init_session_state()
    render_sidebar()

    if not st.session_state.logged_in:
        render_login_page()
        return

    page = st.session_state.current_page
    if page == "📦 My Dashboard & Packages":
        render_dashboard_page()
    elif page == "🗺️ Smart Route Optimizer":
        render_route_optimizer_page()
    elif page == "📈 Carrier Delay Predictor":
        render_carrier_predictor_page()
    elif page == "⚙️ Settings & Profile":
        render_settings_page()


if __name__ == "__main__":
    main()
