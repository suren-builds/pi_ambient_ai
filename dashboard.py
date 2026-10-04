"""
Ambient AI Hub — Dashboard (dashboard.py)
Streamlit UI showing live camera feed, system state, and manual overrides.

Hardening:
  - Handles Brain offline gracefully (shows banner, never crashes)
  - Auto-refresh interval from config (not a busy 0.05s loop)
  - Strict input validation before sending to API
  - Google Fonts load has offline fallback
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

# ─── CSS ─────────────────────────────────────────────────────────────────────
st.markdown("""
<style>
    /* Google Fonts removed for full offline capability */

    #MainMenu {visibility: hidden;}
    header {visibility: hidden;}
    footer {visibility: hidden;}

    .block-container {
        padding: 1.5rem 3rem !important;
        max-width: 1800px;
        z-index: 10;
    }

    .stApp {
        background: radial-gradient(circle at 50% 30%, #0d1117 0%, #030407 100%);
        color: #e6edf3;
        font-family: 'Inter', system-ui, sans-serif;
    }

    .stApp::before {
        content: "";
        position: fixed;
        top: 0; left: 0; width: 100vw; height: 100vh;
        background: linear-gradient(rgba(18,16,16,0) 50%, rgba(0,0,0,0.15) 50%);
        background-size: 100% 4px;
        z-index: 9999;
        pointer-events: none;
        opacity: 0.6;
    }

    .cyber-header {
        display: flex;
        justify-content: space-between;
        align-items: center;
        margin-bottom: 30px;
        padding-bottom: 15px;
        border-bottom: 1px solid rgba(0,255,204,0.2);
        position: relative;
    }
    .cyber-header::after {
        content: '';
        position: absolute;
        bottom: -1px; left: 0;
        width: 150px; height: 2px;
        background: #00ffcc;
        box-shadow: 0 0 10px #00ffcc;
    }

    .project-title {
        font-family: 'Rajdhani', system-ui, sans-serif;
        font-size: 2.5rem;
        font-weight: 700;
        letter-spacing: 2px;
        display: flex;
        align-items: center;
        gap: 15px;
        text-transform: uppercase;
        text-shadow: 0 0 20px rgba(0,255,204,0.4);
    }

    .hud-dot { width: 14px; height: 14px; border-radius: 50%; display: inline-block; }
    .hud-dot.online { background-color: #00ffcc; box-shadow: 0 0 15px #00ffcc, 0 0 30px #00ffcc; animation: pulse-cyan 2s infinite; }
    .hud-dot.offline { background-color: #ff3366; box-shadow: 0 0 15px #ff3366, 0 0 30px #ff3366; animation: pulse-red 2s infinite; }
    @keyframes pulse-cyan { 0%,100% { transform:scale(0.9); opacity:0.7; } 50% { transform:scale(1.1); opacity:1; } }
    @keyframes pulse-red  { 0%,100% { box-shadow: 0 0 10px rgba(255,51,102,0.4); } 50% { box-shadow: 0 0 30px rgba(255,51,102,0.8); } }

    .cyber-panel {
        background: linear-gradient(135deg, rgba(13,17,23,0.7) 0%, rgba(5,7,10,0.8) 100%);
        backdrop-filter: blur(15px);
        border: 1px solid rgba(255,255,255,0.05);
        border-top: 1px solid rgba(0,255,204,0.2);
        border-radius: 16px;
        padding: 25px;
        position: relative;
        overflow: hidden;
        margin-bottom: 25px;
        box-shadow: 0 10px 40px rgba(0,0,0,0.5);
    }
    .cyber-panel::before {
        content: '';
        position: absolute;
        top: 0; left: 0;
        width: 40px; height: 40px;
        border-top: 2px solid rgba(0,255,204,0.6);
        border-left: 2px solid rgba(0,255,204,0.6);
        border-top-left-radius: 16px;
    }

    .panel-critical {
        border: 1px solid rgba(255,51,102,0.4);
        border-top: 1px solid rgba(255,51,102,0.8);
        animation: panel-flash-red 1.5s infinite;
    }
    .panel-critical::before { border-color: #ff3366; }
    @keyframes panel-flash-red {
        0%,100% { box-shadow: 0 0 20px rgba(255,51,102,0.1) inset, 0 10px 40px rgba(0,0,0,0.5); }
        50%      { box-shadow: 0 0 50px rgba(255,51,102,0.3) inset, 0 0 30px rgba(255,51,102,0.2); }
    }

    .hud-title {
        font-family: 'Rajdhani', system-ui, sans-serif;
        font-size: 1.4rem;
        color: #8892b0;
        text-transform: uppercase;
        letter-spacing: 2px;
        margin: 0 0 20px;
        display: flex;
        align-items: center;
        gap: 10px;
    }
    .hud-value { font-family: 'Rajdhani', system-ui, sans-serif; font-size: 2.2rem; font-weight: 600; color: #e6edf3; }

    .hud-camera-wrapper {
        position: relative; border-radius: 12px;
        background: #000; border: 1px solid rgba(0,255,204,0.3);
        box-shadow: 0 0 30px rgba(0,255,204,0.1), inset 0 0 20px rgba(0,255,204,0.05);
        overflow: hidden;
    }
    .hud-camera-wrapper img { width: 100%; display: block; opacity: 0.95; }

    .overlay-badges { position:absolute; top:20px; left:20px; display:flex; flex-direction:column; gap:8px; z-index:20; }
    .cyber-badge {
        font-family: 'Rajdhani', monospace; font-size:0.85rem; font-weight:600;
        letter-spacing:1px; padding:4px 12px; border-radius:4px;
        background:rgba(0,0,0,0.6); backdrop-filter:blur(4px);
        text-transform:uppercase; display:inline-block; width:max-content;
    }
    .badge-cyan   { border:1px solid #00ffcc; color:#00ffcc; }
    .badge-purple { border:1px solid #bd93f9; color:#bd93f9; }
    .badge-red    { border:1px solid #ff3366; color:#ff3366; }

    .camera-timestamp {
        position:absolute; bottom:20px; right:20px;
        font-family:'Rajdhani',monospace; font-size:1rem;
        color:rgba(255,255,255,0.7); background:rgba(0,0,0,0.5);
        padding:4px 10px; border:1px solid rgba(255,255,255,0.1);
        border-radius:4px; backdrop-filter:blur(4px);
    }

    .health-grid { display:grid; grid-template-columns:1fr 1fr 1fr; gap:15px; }
    .health-item { background:rgba(255,255,255,0.03); border:1px solid rgba(255,255,255,0.05); border-radius:8px; padding:15px; text-align:center; }
    .health-label { font-size:0.8rem; color:#8892b0; text-transform:uppercase; letter-spacing:1px; margin-bottom:5px; }
    .health-status { font-family:'Rajdhani',system-ui,sans-serif; font-size:1.2rem; font-weight:600; }
    .status-ok  { color:#00ffcc; text-shadow:0 0 8px rgba(0,255,204,0.4); }
    .status-err { color:#ff3366; text-shadow:0 0 8px rgba(255,51,102,0.4); }

    .timeline { border-left:2px solid rgba(255,255,255,0.1); padding-left:20px; margin-left:10px; }
    .timeline-item { position:relative; margin-bottom:20px; }
    .timeline-item::before {
        content:''; position:absolute; left:-27px; top:5px;
        width:12px; height:12px; background:#0d1117;
        border:2px solid #bd93f9; border-radius:50%;
        box-shadow:0 0 10px rgba(189,147,249,0.6);
    }
    .timeline-time  { font-family:'Rajdhani',monospace; font-size:0.85rem; color:#8892b0; margin-bottom:2px; }
    .timeline-event { font-size:1rem; color:#e6edf3; }

    div[data-testid="stVerticalBlock"] > div { padding: 0 !important; }
</style>
""", unsafe_allow_html=True)

# ─── Data fetching (safe — never crashes) ─────────────────────────────────────
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
        }, False


state, api_online = fetch_state()
frame_exists = os.path.exists(FRAME_PATH)

# ─── Session state activity log ───────────────────────────────────────────────
if "activity_log" not in st.session_state:
    st.session_state.activity_log = [{"time": datetime.now().strftime("%H:%M:%S"), "event": "DASHBOARD STARTED"}]

current_alert = state.get("last_alert", "")
last_logged = st.session_state.activity_log[-1]["event"]
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
    st.markdown("""
    <div style="background:rgba(255,51,102,0.15); border:1px solid #ff3366;
                border-radius:8px; padding:12px 20px; margin-bottom:20px;
                font-family:'Rajdhani',system-ui; font-size:1.1rem; color:#ff3366; letter-spacing:1px;">
        ⚠️  BRAIN OFFLINE — Dashboard is in read-only mode.
        Start <code>voice_assistant.py</code> to restore uplink.
    </div>
    """, unsafe_allow_html=True)

# ─── Header ───────────────────────────────────────────────────────────────────
dot_class = "online" if api_online else "offline"
sys_text = "SYSTEM ONLINE" if api_online else "SYSTEM OFFLINE"
st.markdown(f"""
<div class="cyber-header">
    <div class="project-title">
        <span class="hud-dot {dot_class}"></span>
        AMBIENT INTELLIGENCE HUB
    </div>
    <div style="text-align:right;">
        <div style="font-family:'Rajdhani',monospace;font-size:1.2rem;color:#00ffcc;letter-spacing:2px;">{sys_text}</div>
        <div style="font-family:'Rajdhani',sans-serif;font-size:1.1rem;color:#8892b0;letter-spacing:1px;">{datetime.now().strftime('%Y.%m.%d // %H:%M:%S')}</div>
    </div>
</div>
""", unsafe_allow_html=True)

# ─── Main grid ────────────────────────────────────────────────────────────────
col_left, col_right = st.columns([1.7, 1.0], gap="large")

with col_left:
    st.markdown("<div class='hud-title'>📺 LIVE VISION FEED // OP-CAM-01</div>", unsafe_allow_html=True)

    if frame_exists:
        try:
            with open(FRAME_PATH, "rb") as f:
                img_b64 = base64.b64encode(f.read()).decode()
            st.markdown(f"""
            <div class="hud-camera-wrapper">
                <div class="overlay-badges">
                    <div class="cyber-badge badge-cyan">👁️ YOLOv8 ACTIVE</div>
                    <div class="cyber-badge badge-purple">⚠️ FALL DETECTION: ON</div>
                </div>
                <img src="data:image/jpeg;base64,{img_b64}" />
                <div class="camera-timestamp">SYNC: {datetime.now().strftime('%H:%M:%S.%f')[:-3]}</div>
            </div>
            """, unsafe_allow_html=True)
        except OSError:
            st.markdown("""
            <div class="hud-camera-wrapper" style="height:360px;display:flex;align-items:center;justify-content:center;">
                <h3 style="color:#00ffcc;font-family:'Rajdhani',monospace;">[ SYNCING FEED... ]</h3>
            </div>""", unsafe_allow_html=True)
    else:
        st.markdown("""
        <div class="hud-camera-wrapper" style="height:360px;display:flex;align-items:center;justify-content:center;border-color:rgba(255,51,102,0.3);">
            <div style="text-align:center;">
                <div style="font-size:4rem;margin-bottom:10px;">🔌</div>
                <h2 style="color:#ff3366;font-family:'Rajdhani',monospace;letter-spacing:2px;">[ SIGNAL LOST ]</h2>
                <p style="color:#8892b0;">Start yolo_tracker.py to restore video feed.</p>
            </div>
        </div>""", unsafe_allow_html=True)

with col_right:
    # ── Security status ──────────────────────────────────────────
    alert_text = state.get("last_alert", "MONITORING ACTIVE")
    is_critical = "CRITICAL" in alert_text.upper() or "FALL" in alert_text.upper() or not api_online
    panel_class = "cyber-panel panel-critical" if is_critical else "cyber-panel"
    status_color = "#ff3366" if is_critical else "#00ffcc"

    st.markdown(f"""
    <div class="{panel_class}">
        <div class="hud-title">🛡️ SECURITY STATUS</div>
        <div class="hud-value" style="color:{status_color};text-shadow:0 0 15px {status_color}60;">
            {alert_text.upper()}
        </div>
        <div style="color:#8892b0;font-family:'Rajdhani',monospace;margin-top:10px;font-size:1.1rem;">
            LATEST EVENT: {state.get('last_alert_time') or datetime.now().strftime('%H:%M:%S')}
        </div>
    </div>
    """, unsafe_allow_html=True)

    # ── Mic toggle ───────────────────────────────────────────────
    is_muted = state.get("mic_muted", False)
    btn_color = "#ff3366" if is_muted else "#00ffcc"
    btn_shadow = "rgba(255,51,102,0.4)" if is_muted else "rgba(0,255,204,0.3)"
    btn_bg = (
        "linear-gradient(90deg,rgba(255,51,102,0.1),rgba(255,51,102,0.2))"
        if is_muted else
        "linear-gradient(90deg,rgba(0,255,204,0.05),rgba(0,255,204,0.15))"
    )
    btn_text = "🔇 MICROPHONE: MUTED (ENGAGE)" if is_muted else "🎙️ MICROPHONE: LISTENING (MUTE)"

    st.markdown(f"""
    <style>
    div.stButton > button {{
        background:{btn_bg} !important;
        border:1px solid {btn_color} !important;
        border-left:4px solid {btn_color} !important;
        color:{btn_color} !important;
        box-shadow:0 0 15px {btn_shadow},inset 0 0 10px {btn_shadow} !important;
        border-radius:8px !important;
        height:65px; width:100%;
        font-family:'Rajdhani',system-ui; font-size:1.3rem; font-weight:700;
        letter-spacing:2px; text-transform:uppercase;
        transition:all 0.3s ease;
        margin-bottom:25px;
    }}
    div.stButton > button:hover {{
        background:{btn_color} !important;
        color:#000 !important;
        box-shadow:0 0 30px {btn_shadow} !important;
    }}
    </style>
    """, unsafe_allow_html=True)

    if st.button(btn_text, key="mic_toggle", disabled=not api_online):
        try:
            requests.post(f"{API_URL}/toggle_mic", timeout=1.5)
            time.sleep(0.1)
            st.cache_data.clear()
            st.rerun()
        except Exception:  # noqa: BLE001
            st.error("Failed to reach Brain API.")

    # ── Subsystem diagnostics ────────────────────────────────────
    vis_stat = "ACTIVE" if frame_exists else "OFFLINE"
    vis_cls  = "status-ok" if frame_exists else "status-err"
    api_stat = "ONLINE" if api_online else "OFFLINE"
    api_cls  = "status-ok" if api_online else "status-err"
    vox_stat = "STANDBY" if api_online else "ERROR"
    vox_cls  = "status-ok" if api_online else "status-err"

    st.markdown(f"""
    <div class="cyber-panel" style="padding:20px;">
        <div class="hud-title" style="font-size:1.1rem;margin-bottom:15px;">⚙️ SUBSYSTEM DIAGNOSTICS</div>
        <div class="health-grid">
            <div class="health-item">
                <div class="health-label">API CORE</div>
                <div class="health-status {api_cls}">{api_stat}</div>
            </div>
            <div class="health-item">
                <div class="health-label">VISION</div>
                <div class="health-status {vis_cls}">{vis_stat}</div>
            </div>
            <div class="health-item">
                <div class="health-label">VOICE</div>
                <div class="health-status {vox_cls}">{vox_stat}</div>
            </div>
        </div>
    </div>
    """, unsafe_allow_html=True)

    # ── Event log ───────────────────────────────────────────────
    log_html = '<div class="cyber-panel"><div class="hud-title">📝 EVENT LOG</div><div class="timeline">'
    for item in reversed(st.session_state.activity_log[-5:]):
        log_html += f"""<div class="timeline-item">
<div class="timeline-time">{item['time']}</div>
<div class="timeline-event">{item['event']}</div>
</div>"""
    log_html += "</div></div>"
    st.markdown(log_html, unsafe_allow_html=True)

# ─── Gesture config & Smart Home ─────────────────────────────────────────────
st.markdown("""
<div class='cyber-header' style='margin-top:40px;'>
    <div class='project-title' style='font-size:1.8rem;'>⚙️ GESTURE MAPPING &amp; APPLIANCES</div>
</div>
""", unsafe_allow_html=True)

col_g1, col_g2 = st.columns([1, 1], gap="large")
GESTURE_OPTIONS = ["None", "Toggle Mic", "Toggle Light", "Toggle Fan"]
current_config = state.get("gesture_config", {})
smart_home = state.get("smart_home", {"light": False, "fan": False})

with col_g1:
    st.markdown("<div class='cyber-panel'>", unsafe_allow_html=True)
    st.markdown("<div class='hud-title' style='font-size:1.1rem;'>🎯 GESTURE BINDINGS</div>", unsafe_allow_html=True)

    def _safe_index(val: str) -> int:
        try:
            return GESTURE_OPTIONS.index(val)
        except ValueError:
            return 0

    new_config: dict[str, str] = {}
    new_config["left_arm_up"]   = st.selectbox("LEFT ARM RAISED",         GESTURE_OPTIONS, index=_safe_index(current_config.get("left_arm_up",   "Toggle Mic")),   key="g_left")
    new_config["right_arm_up"]  = st.selectbox("RIGHT ARM RAISED",        GESTURE_OPTIONS, index=_safe_index(current_config.get("right_arm_up",  "Toggle Light")), key="g_right")
    new_config["both_arms_up"]  = st.selectbox("BOTH ARMS RAISED",        GESTURE_OPTIONS, index=_safe_index(current_config.get("both_arms_up",  "Toggle Fan")),   key="g_both")
    new_config["t_pose"]        = st.selectbox("T-POSE (ARMS STRETCHED)", GESTURE_OPTIONS, index=_safe_index(current_config.get("t_pose",         "None")),         key="g_tpose")

    if new_config != current_config and api_online:
        try:
            requests.post(f"{API_URL}/update_config", json=new_config, timeout=1.5)
            st.cache_data.clear()
        except Exception:  # noqa: BLE001
            pass
    st.markdown("</div>", unsafe_allow_html=True)

with col_g2:
    light_on = smart_home.get("light", False)
    fan_on   = smart_home.get("fan",   False)
    light_stat = "ON 💡" if light_on else "OFF ⚫"
    fan_stat   = "ON 🌀" if fan_on   else "OFF ⚫"
    light_cls  = "status-ok" if light_on else "status-err"
    fan_cls    = "status-ok" if fan_on   else "status-err"

    st.markdown(f"""
    <div class="cyber-panel" style="height:100%;">
        <div class="hud-title" style="font-size:1.1rem;">🏠 SMART HOME APPLIANCES</div>
        <div class="health-grid" style="grid-template-columns:1fr 1fr;margin-top:30px;">
            <div class="health-item" style="padding:30px 15px;">
                <div class="health-label">SMART LIGHT</div>
                <div class="health-status {light_cls}" style="font-size:2rem;">{light_stat}</div>
            </div>
            <div class="health-item" style="padding:30px 15px;">
                <div class="health-label">SMART FAN</div>
                <div class="health-status {fan_cls}" style="font-size:2rem;">{fan_stat}</div>
            </div>
        </div>
    </div>
    """, unsafe_allow_html=True)

# ─── Auto-refresh  (respect config interval, not a tight busy-loop) ──────────
time.sleep(REFRESH_S)
st.rerun()
