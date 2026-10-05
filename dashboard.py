"""
Ambient AI Hub — Dashboard (dashboard.py)
Mobile-responsive Streamlit UI: live camera feed, gesture detection status,
fall detection, voice/mic status, smart-home appliance controls, event log.

Changes:
  - Mobile-first CSS with touch-friendly tap targets (min 48px height).
  - Live GESTURE panel: shows arm-raise / both-arms / T-pose in real time.
  - FALL STATUS card that flashes red when a fall is confirmed.
  - VOICE ACTIVITY indicator shows whether mic is listening or muted.
  - PERSON COUNTER badge on camera feed.
  - Handles Brain offline gracefully (shows banner, never crashes).
  - Auto-refresh interval from config.
"""

from __future__ import annotations

import base64
import os
import time
from datetime import datetime
from typing import Any

import requests
import streamlit as st
import yaml

# ─── Config ──────────────────────────────────────────────────────────────────
_DIR = os.path.dirname(os.path.abspath(__file__))
_CFG_PATH = os.path.join(_DIR, "config.yaml")


def _load_config(path: str) -> dict[str, Any]:
    defaults: dict[str, Any] = {
        "brain_api_host": "127.0.0.1",
        "brain_api_port": 5000,
        "dashboard_refresh_interval_s": 1.5,
    }
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            user_cfg = yaml.safe_load(f) or {}
        defaults.update(user_cfg)
    return defaults


CFG = _load_config(_CFG_PATH)
API_URL = f"http://{CFG['brain_api_host']}:{CFG['brain_api_port']}"
FRAME_PATH = os.path.join(_DIR, "latest_frame.jpg")
REFRESH_S = float(CFG["dashboard_refresh_interval_s"])

# ─── Page config ─────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Ambient Intelligence Hub",
    page_icon="💠",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# ─── CSS (mobile-first, touch-friendly) ──────────────────────────────────────
st.markdown("""
<style>
  @import url('https://fonts.googleapis.com/css2?family=Rajdhani:wght@400;600;700&family=Inter:wght@400;500;600&display=swap');

  #MainMenu {visibility: hidden;}
  header    {visibility: hidden;}
  footer    {visibility: hidden;}

  .block-container {
      padding: 1rem 1.2rem !important;
      max-width: 1800px;
  }
  .stApp {
      background: radial-gradient(circle at 50% 20%, #0a0f1a 0%, #020408 100%);
      color: #e6edf3;
      font-family: 'Inter', system-ui, sans-serif;
  }

  /* ── HUD Header ─────────────────────────────────────── */
  .amb-header {
      display: flex; justify-content: space-between; align-items: center;
      margin-bottom: 20px; padding-bottom: 12px;
      border-bottom: 1px solid rgba(0,255,204,0.2);
  }
  .amb-title {
      font-family: 'Rajdhani', system-ui; font-size: clamp(1.3rem, 4vw, 2.2rem);
      font-weight: 700; letter-spacing: 2px; text-transform: uppercase;
      color: #e6edf3; text-shadow: 0 0 20px rgba(0,255,204,0.35);
  }
  .amb-clock {
      font-family: 'Rajdhani', monospace; font-size: clamp(0.8rem, 2.5vw, 1.1rem);
      color: #8892b0; text-align: right; line-height: 1.5;
  }
  .hud-dot { width: 12px; height: 12px; border-radius: 50%; display: inline-block; margin-right: 8px; }
  .hud-dot.online  { background: #00ffcc; box-shadow: 0 0 12px #00ffcc; animation: pulse-c 2s infinite; }
  .hud-dot.offline { background: #ff3366; box-shadow: 0 0 12px #ff3366; animation: pulse-r 2s infinite; }
  @keyframes pulse-c { 0%,100% { opacity:.6; transform:scale(.9); } 50% { opacity:1; transform:scale(1.15); } }
  @keyframes pulse-r { 0%,100% { box-shadow:0 0 8px rgba(255,51,102,.4);  } 50% { box-shadow:0 0 28px rgba(255,51,102,.8); } }

  /* ── Glass card ─────────────────────────────────────── */
  .amb-card {
      background: linear-gradient(135deg, rgba(13,20,35,0.75) 0%, rgba(5,8,15,0.85) 100%);
      backdrop-filter: blur(14px); -webkit-backdrop-filter: blur(14px);
      border: 1px solid rgba(255,255,255,0.06);
      border-top: 1px solid rgba(0,255,204,0.25);
      border-radius: 14px; padding: 18px 20px;
      margin-bottom: 16px;
      box-shadow: 0 8px 32px rgba(0,0,0,0.45);
      position: relative; overflow: hidden;
  }
  .amb-card::before {
      content: ''; position: absolute; top: 0; left: 0;
      width: 35px; height: 35px;
      border-top: 2px solid rgba(0,255,204,0.5);
      border-left: 2px solid rgba(0,255,204,0.5);
      border-top-left-radius: 14px;
  }
  .amb-card.alert {
      border: 1px solid rgba(255,51,102,0.5);
      border-top: 2px solid #ff3366;
      animation: card-flash 1.2s infinite;
  }
  .amb-card.alert::before { border-color: #ff3366; }
  @keyframes card-flash {
      0%,100% { box-shadow: 0 0 18px rgba(255,51,102,0.1) inset, 0 8px 32px rgba(0,0,0,.45); }
      50%      { box-shadow: 0 0 45px rgba(255,51,102,0.3) inset, 0 0 25px rgba(255,51,102,0.15); }
  }

  .card-title {
      font-family: 'Rajdhani', system-ui; font-size: 0.85rem; font-weight: 600;
      color: #8892b0; text-transform: uppercase; letter-spacing: 2px;
      margin-bottom: 12px; display: flex; align-items: center; gap: 8px;
  }
  .card-value {
      font-family: 'Rajdhani', system-ui; font-size: clamp(1.4rem, 4vw, 2rem);
      font-weight: 700; color: #e6edf3; line-height: 1.1;
  }
  .card-sub {
      font-family: 'Rajdhani', monospace; font-size: 0.82rem;
      color: #8892b0; margin-top: 6px; letter-spacing: 1px;
  }

  /* ── Status colours ─────────────────────────────────── */
  .col-cyan   { color: #00ffcc !important; text-shadow: 0 0 10px rgba(0,255,204,0.5); }
  .col-red    { color: #ff3366 !important; text-shadow: 0 0 10px rgba(255,51,102,0.5); }
  .col-orange { color: #ff9500 !important; text-shadow: 0 0 10px rgba(255,149,0,0.5); }
  .col-blue   { color: #64b5f6 !important; text-shadow: 0 0 10px rgba(100,181,246,0.5); }
  .col-grey   { color: #8892b0 !important; }

  /* ── Gesture bar ─────────────────────────────────────── */
  .gesture-grid {
      display: grid; grid-template-columns: 1fr 1fr;
      gap: 10px; margin-top: 8px;
  }
  .gesture-item {
      background: rgba(255,255,255,0.03); border: 1px solid rgba(255,255,255,0.07);
      border-radius: 10px; padding: 12px 10px; text-align: center;
      transition: all 0.3s ease;
  }
  .gesture-item.active {
      background: rgba(0,255,204,0.08); border-color: rgba(0,255,204,0.4);
      box-shadow: 0 0 15px rgba(0,255,204,0.15);
  }
  .gesture-icon { font-size: 1.8rem; margin-bottom: 4px; }
  .gesture-label {
      font-family: 'Rajdhani'; font-size: 0.75rem; text-transform: uppercase;
      letter-spacing: 1px; color: #8892b0;
  }
  .gesture-label.active { color: #00ffcc; }

  /* ── Appliance toggles ───────────────────────────────── */
  .appliance-row { display: flex; gap: 12px; }
  .appliance-card {
      flex: 1; background: rgba(255,255,255,0.03);
      border: 1px solid rgba(255,255,255,0.07); border-radius: 12px;
      padding: 18px 10px; text-align: center;
      transition: all 0.4s ease;
  }
  .appliance-card.on {
      background: rgba(0,255,204,0.07); border-color: rgba(0,255,204,0.35);
      box-shadow: 0 0 20px rgba(0,255,204,0.12);
  }
  .appliance-icon { font-size: 2.2rem; margin-bottom: 8px; display: block; }
  .appliance-name {
      font-family: 'Rajdhani'; font-size: 0.8rem;
      text-transform: uppercase; letter-spacing: 1px; color: #8892b0; margin-bottom: 4px;
  }
  .appliance-state {
      font-family: 'Rajdhani'; font-size: 1.1rem; font-weight: 700;
  }

  /* ── Camera ─────────────────────────────────────────── */
  .cam-wrapper {
      position: relative; border-radius: 12px; overflow: hidden;
      background: #000; border: 1px solid rgba(0,255,204,0.25);
      box-shadow: 0 0 30px rgba(0,255,204,0.08), inset 0 0 20px rgba(0,255,204,0.04);
  }
  .cam-wrapper img { width: 100%; display: block; opacity: 0.95; }
  .cam-badges {
      position: absolute; top: 14px; left: 14px;
      display: flex; flex-direction: column; gap: 6px; z-index: 20;
  }
  .cam-badge {
      font-family: 'Rajdhani', monospace; font-size: 0.78rem; font-weight: 600;
      letter-spacing: 1px; padding: 3px 10px; border-radius: 4px;
      background: rgba(0,0,0,0.65); backdrop-filter: blur(4px);
      text-transform: uppercase; width: max-content;
  }
  .badge-c  { border: 1px solid #00ffcc; color: #00ffcc; }
  .badge-p  { border: 1px solid #bd93f9; color: #bd93f9; }
  .badge-r  { border: 1px solid #ff3366; color: #ff3366; animation: badge-flash 1s infinite; }
  .badge-o  { border: 1px solid #ff9500; color: #ff9500; }
  @keyframes badge-flash { 0%,100%{opacity:1;} 50%{opacity:0.4;} }
  .cam-ts {
      position: absolute; bottom: 14px; right: 14px;
      font-family: 'Rajdhani', monospace; font-size: 0.9rem;
      color: rgba(255,255,255,0.65); background: rgba(0,0,0,0.5);
      padding: 3px 9px; border-radius: 4px; backdrop-filter: blur(4px);
      border: 1px solid rgba(255,255,255,0.1);
  }

  /* ── Mic button override ─────────────────────────────── */
  div[data-testid="stButton"] > button {
      min-height: 52px !important;
      font-family: 'Rajdhani', system-ui !important;
      font-size: 1.1rem !important;
      font-weight: 700 !important;
      letter-spacing: 2px !important;
      text-transform: uppercase !important;
      border-radius: 10px !important;
      transition: all 0.3s ease !important;
      width: 100% !important;
  }

  /* ── Offline banner ─────────────────────────────────── */
  .offline-banner {
      background: rgba(255,51,102,0.12); border: 1px solid rgba(255,51,102,0.5);
      border-radius: 8px; padding: 10px 16px; margin-bottom: 16px;
      font-family: 'Rajdhani'; font-size: 1rem; color: #ff3366; letter-spacing: 1px;
  }

  /* ── Timeline ───────────────────────────────────────── */
  .timeline { border-left: 2px solid rgba(255,255,255,0.08); padding-left: 18px; margin-left: 8px; }
  .tl-item  { position: relative; margin-bottom: 16px; }
  .tl-item::before {
      content: ''; position: absolute; left: -25px; top: 4px;
      width: 10px; height: 10px; background: #0a0f1a;
      border: 2px solid #bd93f9; border-radius: 50%;
      box-shadow: 0 0 8px rgba(189,147,249,0.5);
  }
  .tl-time  { font-family: 'Rajdhani', monospace; font-size: 0.8rem; color: #8892b0; margin-bottom: 2px; }
  .tl-event { font-size: 0.95rem; color: #e6edf3; }

  /* ── Responsive: stack on phones ───────────────────── */
  @media (max-width: 600px) {
      .block-container { padding: 0.8rem !important; }
      .gesture-grid    { grid-template-columns: 1fr 1fr; gap: 8px; }
      .appliance-row   { gap: 8px; }
  }
</style>
""", unsafe_allow_html=True)

# ─── Data fetching ────────────────────────────────────────────────────────────
@st.cache_data(ttl=REFRESH_S)  # type: ignore[misc]
def fetch_state() -> tuple[dict[str, Any], bool]:
    """Fetch system state from Brain. Returns (state_dict, api_online)."""
    try:
        res = requests.get(f"{API_URL}/state", timeout=1.5)
        res.raise_for_status()
        return res.json(), True
    except Exception:  # noqa: BLE001
        return {
            "mic_muted": False,
            "last_alert": "API OFFLINE — Brain not reachable",
            "last_alert_time": "",
            "smart_home": {"light": False, "fan": False},
            "gesture_config": {
                "left_arm_up": "Toggle Mic",
                "right_arm_up": "Toggle Light",
                "both_arms_up": "Toggle Fan",
                "t_pose": "None",
            },
            "vision": {
                "gesture": "None",
                "fall_confirmed": False,
                "person_count": 0,
                "last_seen": "",
            },
        }, False


state, api_online = fetch_state()
frame_exists = os.path.exists(FRAME_PATH)

# Vision state
vision = state.get("vision", {})
v_gesture = vision.get("gesture", "None")
v_fall    = bool(vision.get("fall_confirmed", False))
v_people  = int(vision.get("person_count", 0))
v_seen    = vision.get("last_seen", "")

# ─── Activity log ─────────────────────────────────────────────────────────────
if "activity_log" not in st.session_state:
    st.session_state.activity_log = [{"time": datetime.now().strftime("%H:%M:%S"), "event": "DASHBOARD STARTED"}]

current_alert = state.get("last_alert", "")
last_logged   = st.session_state.activity_log[-1]["event"]
if (
    current_alert
    and current_alert != last_logged
    and "Monitoring Active" not in current_alert
    and "API OFFLINE" not in current_alert
):
    st.session_state.activity_log.append({
        "time": state.get("last_alert_time") or datetime.now().strftime("%H:%M:%S"),
        "event": current_alert.upper(),
    })
    if len(st.session_state.activity_log) > 10:
        st.session_state.activity_log.pop(0)

# ─── Offline banner ───────────────────────────────────────────────────────────
if not api_online:
    st.markdown(
        '<div class="offline-banner">⚠️  BRAIN OFFLINE — Dashboard is in read-only mode. '
        'Start <code>voice_assistant.py</code> to restore uplink.</div>',
        unsafe_allow_html=True,
    )

# ─── Header ───────────────────────────────────────────────────────────────────
dot_cls  = "online" if api_online else "offline"
sys_text = "SYSTEM ONLINE" if api_online else "SYSTEM OFFLINE"
st.markdown(f"""
<div class="amb-header">
    <div class="amb-title">
        <span class="hud-dot {dot_cls}"></span>AMBIENT AI
    </div>
    <div class="amb-clock">
        <div style="color:#00ffcc;font-size:0.85rem;letter-spacing:2px;">{sys_text}</div>
        <div>{datetime.now().strftime('%Y-%m-%d // %H:%M:%S')}</div>
    </div>
</div>
""", unsafe_allow_html=True)

# ─── LIVE ALERT BANNER (if fall or critical) ──────────────────────────────────
alert_text = state.get("last_alert", "MONITORING ACTIVE")
is_critical = "CRITICAL" in alert_text.upper() or "FALL" in alert_text.upper() or v_fall
if is_critical:
    st.markdown(f"""
    <div class="amb-card alert" style="text-align:center;padding:14px;">
        <span style="font-family:'Rajdhani';font-size:1.5rem;font-weight:700;letter-spacing:2px;"
              class="col-red">⚠️ {alert_text.upper()}</span>
    </div>""", unsafe_allow_html=True)

# ─── MAIN LAYOUT: Camera | Right Panel ───────────────────────────────────────
col_cam, col_panel = st.columns([1.6, 1.0], gap="large")

# ══ LEFT: Camera ══════════════════════════════════════════════════════════════
with col_cam:
    st.markdown('<div class="card-title">📺 LIVE VISION FEED</div>', unsafe_allow_html=True)

    fall_badge   = '<div class="cam-badge badge-r">🔴 FALL DETECTED</div>' if v_fall else ""
    people_badge = f'<div class="cam-badge badge-o">👤 PERSONS: {v_people}</div>' if v_people > 0 else ""
    gest_badge   = f'<div class="cam-badge badge-p">🤚 {v_gesture.upper()}</div>' if v_gesture not in ("None", "", "none") else ""

    if frame_exists:
        try:
            with open(FRAME_PATH, "rb") as f:
                img_b64 = base64.b64encode(f.read()).decode()
            st.markdown(f"""
            <div class="cam-wrapper">
                <div class="cam-badges">
                    <div class="cam-badge badge-c">👁️ YOLO ACTIVE</div>
                    <div class="cam-badge badge-p">⚠️ FALL DETECT: ON</div>
                    {people_badge}
                    {gest_badge}
                    {fall_badge}
                </div>
                <img src="data:image/jpeg;base64,{img_b64}" />
                <div class="cam-ts">SYNC: {datetime.now().strftime('%H:%M:%S.%f')[:-3]}</div>
            </div>
            """, unsafe_allow_html=True)
        except OSError:
            st.markdown("""
            <div class="cam-wrapper" style="height:300px;display:flex;align-items:center;justify-content:center;">
                <h3 style="color:#00ffcc;font-family:'Rajdhani',monospace;">[ SYNCING FEED... ]</h3>
            </div>""", unsafe_allow_html=True)
    else:
        st.markdown("""
        <div class="cam-wrapper" style="height:300px;display:flex;align-items:center;justify-content:center;
                    border-color:rgba(255,51,102,0.3);">
            <div style="text-align:center;">
                <div style="font-size:3.5rem;margin-bottom:8px;">🔌</div>
                <h2 style="color:#ff3366;font-family:'Rajdhani',monospace;letter-spacing:2px;">[ SIGNAL LOST ]</h2>
                <p style="color:#8892b0;font-size:0.9rem;">Start yolo_tracker.py to restore feed.</p>
            </div>
        </div>""", unsafe_allow_html=True)

# ══ RIGHT: Status Panels ══════════════════════════════════════════════════════
with col_panel:

    # ── 1. FALL DETECTION STATUS ──────────────────────────────────────────────
    fall_card_cls = "amb-card alert" if v_fall else "amb-card"
    fall_color    = "col-red"        if v_fall else "col-cyan"
    fall_label    = "⚠️ FALL CONFIRMED" if v_fall else "✅ ALL CLEAR"
    fall_sub      = f"Last update: {v_seen}" if v_seen else "Waiting for vision engine..."

    st.markdown(f"""
    <div class="{fall_card_cls}">
        <div class="card-title">🛡️ FALL DETECTION</div>
        <div class="card-value {fall_color}">{fall_label}</div>
        <div class="card-sub">{fall_sub}</div>
    </div>""", unsafe_allow_html=True)

    # ── 2. GESTURE DETECTION ──────────────────────────────────────────────────
    def _g_active(name: str) -> str:
        active = name.lower().replace(" ", "_") in v_gesture.lower()
        return "active" if active else ""

    left_a  = _g_active("left")
    right_a = _g_active("right")
    both_a  = _g_active("both")
    tpose_a = _g_active("t_pose")

    st.markdown(f"""
    <div class="amb-card">
        <div class="card-title">🤚 GESTURE DETECTION</div>
        <div style="font-family:'Rajdhani';font-size:0.75rem;color:#8892b0;letter-spacing:1px;margin-bottom:10px;">
            ACTIVE: <span style="color:#00ffcc;font-weight:700;">{v_gesture.upper()}</span>
        </div>
        <div class="gesture-grid">
            <div class="gesture-item {left_a}">
                <div class="gesture-icon">🙋</div>
                <div class="gesture-label {left_a}">LEFT ARM UP</div>
            </div>
            <div class="gesture-item {right_a}">
                <div class="gesture-icon">🙋</div>
                <div class="gesture-label {right_a}" style="transform:scaleX(-1);display:inline-block;">RIGHT ARM UP</div>
            </div>
            <div class="gesture-item {both_a}">
                <div class="gesture-icon">🙌</div>
                <div class="gesture-label {both_a}">BOTH ARMS UP</div>
            </div>
            <div class="gesture-item {tpose_a}">
                <div class="gesture-icon">🏊</div>
                <div class="gesture-label {tpose_a}">T-POSE</div>
            </div>
        </div>
    </div>""", unsafe_allow_html=True)

    # ── 3. VOICE / MIC STATUS ─────────────────────────────────────────────────
    is_muted   = state.get("mic_muted", False)
    mic_color  = "col-red"  if is_muted else "col-cyan"
    mic_label  = "🔇 MUTED" if is_muted else "🎙️ LISTENING"
    mic_sub    = "Tap to unmute" if is_muted else "Voice commands active"

    btn_bg     = ("linear-gradient(90deg,rgba(255,51,102,.1),rgba(255,51,102,.2))"
                  if is_muted else
                  "linear-gradient(90deg,rgba(0,255,204,.05),rgba(0,255,204,.15))")
    btn_border = "#ff3366" if is_muted else "#00ffcc"
    btn_shadow = "rgba(255,51,102,.4)" if is_muted else "rgba(0,255,204,.3)"
    btn_text   = "🔇 MIC: MUTED  (TAP TO UNMUTE)" if is_muted else "🎙️ MIC: ACTIVE  (TAP TO MUTE)"

    st.markdown(f"""
    <div class="amb-card" style="padding-bottom:12px;">
        <div class="card-title">🎙️ VOICE ASSISTANT</div>
        <div class="card-value {mic_color}" style="font-size:1.5rem;">{mic_label}</div>
        <div class="card-sub">{mic_sub}</div>
    </div>""", unsafe_allow_html=True)

    st.markdown(f"""<style>
    div[data-testid="stButton"] > button {{
        background:{btn_bg} !important;
        border:1px solid {btn_border} !important;
        border-left:4px solid {btn_border} !important;
        color:{btn_border} !important;
        box-shadow:0 0 14px {btn_shadow},inset 0 0 8px {btn_shadow} !important;
    }}
    div[data-testid="stButton"] > button:hover {{
        background:{btn_border} !important; color:#000 !important;
        box-shadow:0 0 28px {btn_shadow} !important;
    }}
    </style>""", unsafe_allow_html=True)

    if st.button(btn_text, key="mic_toggle", disabled=not api_online):
        try:
            requests.post(f"{API_URL}/toggle_mic", timeout=1.5)
            time.sleep(0.1)
            st.cache_data.clear()
            st.rerun()
        except Exception:  # noqa: BLE001
            st.error("Failed to reach Brain API.")

    # ── 4. SMART HOME APPLIANCES ──────────────────────────────────────────────
    smart_home = state.get("smart_home", {"light": False, "fan": False})
    light_on   = smart_home.get("light", False)
    fan_on     = smart_home.get("fan",   False)

    light_cls  = "on" if light_on else ""
    fan_cls    = "on" if fan_on   else ""
    light_col  = "#00ffcc" if light_on else "#8892b0"
    fan_col    = "#00ffcc" if fan_on   else "#8892b0"

    st.markdown(f"""
    <div class="amb-card">
        <div class="card-title">🏠 SMART HOME</div>
        <div class="appliance-row">
            <div class="appliance-card {light_cls}">
                <span class="appliance-icon">💡</span>
                <div class="appliance-name">Light</div>
                <div class="appliance-state" style="color:{light_col};">
                    {"ON" if light_on else "OFF"}
                </div>
            </div>
            <div class="appliance-card {fan_cls}">
                <span class="appliance-icon">🌀</span>
                <div class="appliance-name">Fan</div>
                <div class="appliance-state" style="color:{fan_col};">
                    {"ON" if fan_on else "OFF"}
                </div>
            </div>
        </div>
    </div>""", unsafe_allow_html=True)

# ─── BOTTOM ROW: Subsystems | Gesture Config | Event Log ──────────────────────
st.markdown("<div style='height:8px'></div>", unsafe_allow_html=True)
col_sys, col_gcfg, col_log = st.columns([1, 1.2, 1.1], gap="large")

# ── Subsystem diagnostics ────────────────────────────────────────────────────
with col_sys:
    vis_stat = "ACTIVE" if frame_exists else "OFFLINE"
    vis_cls  = "col-cyan" if frame_exists else "col-red"
    api_stat = "ONLINE"  if api_online   else "OFFLINE"
    api_cls  = "col-cyan" if api_online  else "col-red"
    vox_stat = "STANDBY" if api_online   else "ERROR"
    vox_cls  = "col-cyan" if api_online  else "col-red"
    ppl_col  = "col-cyan" if v_people > 0 else "col-grey"

    st.markdown(f"""
    <div class="amb-card">
        <div class="card-title">⚙️ SUBSYSTEMS</div>
        <table style="width:100%;border-collapse:collapse;font-family:'Rajdhani';font-size:0.9rem;">
            <tr><td style="color:#8892b0;padding:5px 0;letter-spacing:1px;">API CORE</td>
                <td class="{api_cls}" style="text-align:right;font-weight:700;">{api_stat}</td></tr>
            <tr><td style="color:#8892b0;padding:5px 0;letter-spacing:1px;">VISION</td>
                <td class="{vis_cls}" style="text-align:right;font-weight:700;">{vis_stat}</td></tr>
            <tr><td style="color:#8892b0;padding:5px 0;letter-spacing:1px;">VOICE</td>
                <td class="{vox_cls}" style="text-align:right;font-weight:700;">{vox_stat}</td></tr>
            <tr><td style="color:#8892b0;padding:5px 0;letter-spacing:1px;">PERSONS</td>
                <td class="{ppl_col}" style="text-align:right;font-weight:700;">{v_people}</td></tr>
        </table>
    </div>""", unsafe_allow_html=True)

# ── Gesture config ───────────────────────────────────────────────────────────
with col_gcfg:
    GESTURE_OPTIONS = ["None", "Toggle Mic", "Toggle Light", "Toggle Fan"]
    current_config  = state.get("gesture_config", {})

    def _safe_index(val: str) -> int:
        try:
            return GESTURE_OPTIONS.index(val)
        except ValueError:
            return 0

    st.markdown('<div class="amb-card">', unsafe_allow_html=True)
    st.markdown('<div class="card-title">🎯 GESTURE BINDINGS</div>', unsafe_allow_html=True)

    new_config: dict[str, str] = {}
    new_config["left_arm_up"]  = st.selectbox("LEFT ARM RAISED",         GESTURE_OPTIONS, index=_safe_index(current_config.get("left_arm_up",  "Toggle Mic")),   key="g_left")
    new_config["right_arm_up"] = st.selectbox("RIGHT ARM RAISED",        GESTURE_OPTIONS, index=_safe_index(current_config.get("right_arm_up", "Toggle Light")), key="g_right")
    new_config["both_arms_up"] = st.selectbox("BOTH ARMS RAISED",        GESTURE_OPTIONS, index=_safe_index(current_config.get("both_arms_up", "Toggle Fan")),   key="g_both")
    new_config["t_pose"]       = st.selectbox("T-POSE (ARMS STRETCHED)", GESTURE_OPTIONS, index=_safe_index(current_config.get("t_pose",       "None")),         key="g_tpose")

    if new_config != current_config and api_online:
        try:
            requests.post(f"{API_URL}/update_config", json=new_config, timeout=1.5)
            st.cache_data.clear()
        except Exception:  # noqa: BLE001
            pass
    st.markdown("</div>", unsafe_allow_html=True)

# ── Event log ────────────────────────────────────────────────────────────────
with col_log:
    log_html = '<div class="amb-card"><div class="card-title">📝 EVENT LOG</div><div class="timeline">'
    for item in reversed(st.session_state.activity_log[-6:]):
        log_html += f"""<div class="tl-item">
<div class="tl-time">{item['time']}</div>
<div class="tl-event">{item['event']}</div>
</div>"""
    log_html += "</div></div>"
    st.markdown(log_html, unsafe_allow_html=True)

# ─── Auto-refresh ─────────────────────────────────────────────────────────────
time.sleep(REFRESH_S)
st.rerun()