import streamlit as st
import requests
import time
import os
from datetime import datetime
import base64

# ============================================================
# PAGE CONFIG - WIDE LAYOUT
# ============================================================
st.set_page_config(
    page_title="Ambient Intelligence Hub",
    page_icon="💠",
    layout="wide",
    initial_sidebar_state="collapsed"
)

API_URL = "http://127.0.0.1:5000"
FRAME_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "latest_frame.jpg")

# ============================================================
# ULTRA-MODERN SCI-FI CSS INJECTION
# ============================================================
st.markdown("""
<style>
    /* Google Fonts for a Sci-Fi / Tech look */
    @import url('https://fonts.googleapis.com/css2?family=Rajdhani:wght@400;500;600;700&family=Inter:wght@300;400;600&display=swap');

    /* Hide standard Streamlit elements */
    #MainMenu {visibility: hidden;}
    header {visibility: hidden;}
    footer {visibility: hidden;}
    
    /* Overall App Background & Padding */
    .block-container {
        padding: 1.5rem 3rem !important;
        max-width: 1800px;
        z-index: 10;
    }
    
    .stApp {
        background: radial-gradient(circle at 50% 30%, #0d1117 0%, #030407 100%);
        color: #e6edf3;
        font-family: 'Inter', sans-serif;
    }

    /* Subtle HUD Scanline Overlay */
    .stApp::before {
        content: "";
        position: fixed;
        top: 0; left: 0; width: 100vw; height: 100vh;
        background: linear-gradient(rgba(18, 16, 16, 0) 50%, rgba(0, 0, 0, 0.15) 50%);
        background-size: 100% 4px;
        z-index: 9999;
        pointer-events: none;
        opacity: 0.6;
    }

    /* Top Navigation Floating Header */
    .cyber-header {
        display: flex;
        justify-content: space-between;
        align-items: center;
        margin-bottom: 30px;
        padding-bottom: 15px;
        border-bottom: 1px solid rgba(0, 255, 204, 0.2);
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
        font-family: 'Rajdhani', sans-serif;
        font-size: 2.5rem;
        font-weight: 700;
        letter-spacing: 2px;
        display: flex;
        align-items: center;
        gap: 15px;
        text-transform: uppercase;
        text-shadow: 0 0 20px rgba(0, 255, 204, 0.4);
    }

    /* Pulsing HUD Status Dot */
    .hud-dot {
        width: 14px;
        height: 14px;
        border-radius: 50%;
        display: inline-block;
    }
    .hud-dot.online {
        background-color: #00ffcc;
        box-shadow: 0 0 15px #00ffcc, 0 0 30px #00ffcc;
        animation: pulse-cyan 2s infinite;
    }
    .hud-dot.offline {
        background-color: #ff3366;
        box-shadow: 0 0 15px #ff3366, 0 0 30px #ff3366;
        animation: pulse-red 2s infinite;
    }

    @keyframes pulse-cyan {
        0% { transform: scale(0.9); opacity: 0.7; }
        50% { transform: scale(1.1); opacity: 1; }
        100% { transform: scale(0.9); opacity: 0.7; }
    }
    @keyframes pulse-red {
        0% { box-shadow: 0 0 10px rgba(255, 51, 102, 0.4); }
        50% { box-shadow: 0 0 30px rgba(255, 51, 102, 0.8); }
        100% { box-shadow: 0 0 10px rgba(255, 51, 102, 0.4); }
    }

    /* Cybernetic Glass Panels */
    .cyber-panel {
        background: linear-gradient(135deg, rgba(13, 17, 23, 0.7) 0%, rgba(5, 7, 10, 0.8) 100%);
        backdrop-filter: blur(15px);
        -webkit-backdrop-filter: blur(15px);
        border: 1px solid rgba(255, 255, 255, 0.05);
        border-top: 1px solid rgba(0, 255, 204, 0.2);
        border-radius: 16px;
        padding: 25px;
        position: relative;
        overflow: hidden;
        margin-bottom: 25px;
        box-shadow: 0 10px 40px rgba(0, 0, 0, 0.5);
    }
    
    /* Subtle decorative corner */
    .cyber-panel::before {
        content: '';
        position: absolute;
        top: 0; left: 0;
        width: 40px; height: 40px;
        border-top: 2px solid rgba(0, 255, 204, 0.6);
        border-left: 2px solid rgba(0, 255, 204, 0.6);
        border-top-left-radius: 16px;
        box-shadow: -2px -2px 10px rgba(0, 255, 204, 0.2);
    }

    /* Dramatic Red Alert Panel */
    .panel-critical {
        border: 1px solid rgba(255, 51, 102, 0.4);
        border-top: 1px solid rgba(255, 51, 102, 0.8);
        animation: panel-flash-red 1.5s infinite;
    }
    .panel-critical::before {
        border-color: #ff3366;
        box-shadow: -2px -2px 10px rgba(255, 51, 102, 0.4);
    }
    @keyframes panel-flash-red {
        0% { box-shadow: 0 0 20px rgba(255, 51, 102, 0.1) inset, 0 10px 40px rgba(0,0,0,0.5); }
        50% { box-shadow: 0 0 50px rgba(255, 51, 102, 0.3) inset, 0 0 30px rgba(255, 51, 102, 0.2); }
        100% { box-shadow: 0 0 20px rgba(255, 51, 102, 0.1) inset, 0 10px 40px rgba(0,0,0,0.5); }
    }

    /* HUD Typography */
    .hud-title {
        font-family: 'Rajdhani', sans-serif;
        font-size: 1.4rem;
        color: #8892b0;
        text-transform: uppercase;
        letter-spacing: 2px;
        margin-top: 0;
        margin-bottom: 20px;
        display: flex;
        align-items: center;
        gap: 10px;
    }
    .hud-value {
        font-family: 'Rajdhani', sans-serif;
        font-size: 2.2rem;
        font-weight: 600;
        color: #e6edf3;
        line-height: 1.2;
    }

    /* Cinematic Camera Feed container */
    .hud-camera-wrapper {
        position: relative;
        border-radius: 12px;
        background: #000;
        border: 1px solid rgba(0, 255, 204, 0.3);
        box-shadow: 0 0 30px rgba(0, 255, 204, 0.1), inset 0 0 20px rgba(0, 255, 204, 0.05);
        overflow: hidden;
    }
    
    .hud-camera-wrapper img {
        width: 100%;
        display: block;
        opacity: 0.95;
    }

    /* Floating Overlay Badges */
    .overlay-badges {
        position: absolute;
        top: 20px;
        left: 20px;
        display: flex;
        flex-direction: column;
        gap: 8px;
        z-index: 20;
    }
    .cyber-badge {
        font-family: 'Rajdhani', monospace;
        font-size: 0.85rem;
        font-weight: 600;
        letter-spacing: 1px;
        padding: 4px 12px;
        border-radius: 4px;
        background: rgba(0, 0, 0, 0.6);
        backdrop-filter: blur(4px);
        text-transform: uppercase;
        display: inline-block;
        width: max-content;
    }
    .badge-cyan { border: 1px solid #00ffcc; color: #00ffcc; text-shadow: 0 0 5px #00ffcc; }
    .badge-purple { border: 1px solid #bd93f9; color: #bd93f9; text-shadow: 0 0 5px #bd93f9; }
    .badge-amber { border: 1px solid #ffb86c; color: #ffb86c; text-shadow: 0 0 5px #ffb86c; }

    .camera-timestamp {
        position: absolute;
        bottom: 20px;
        right: 20px;
        font-family: 'Rajdhani', monospace;
        font-size: 1rem;
        color: rgba(255,255,255,0.7);
        background: rgba(0,0,0,0.5);
        padding: 4px 10px;
        border: 1px solid rgba(255,255,255,0.1);
        border-radius: 4px;
        backdrop-filter: blur(4px);
    }

    /* Health Grid */
    .health-grid {
        display: grid;
        grid-template-columns: 1fr 1fr 1fr;
        gap: 15px;
    }
    .health-item {
        background: rgba(255, 255, 255, 0.03);
        border: 1px solid rgba(255, 255, 255, 0.05);
        border-radius: 8px;
        padding: 15px;
        text-align: center;
    }
    .health-label { font-size: 0.8rem; color: #8892b0; text-transform: uppercase; letter-spacing: 1px; margin-bottom: 5px; }
    .health-status { font-family: 'Rajdhani', sans-serif; font-size: 1.2rem; font-weight: 600; }
    .status-ok { color: #00ffcc; text-shadow: 0 0 8px rgba(0,255,204,0.4); }
    .status-err { color: #ff3366; text-shadow: 0 0 8px rgba(255,51,102,0.4); }

    /* Timeline Activity Log */
    .timeline {
        border-left: 2px solid rgba(255, 255, 255, 0.1);
        padding-left: 20px;
        margin-left: 10px;
    }
    .timeline-item {
        position: relative;
        margin-bottom: 20px;
    }
    .timeline-item::before {
        content: '';
        position: absolute;
        left: -27px;
        top: 5px;
        width: 12px;
        height: 12px;
        background: #0d1117;
        border: 2px solid #bd93f9;
        border-radius: 50%;
        box-shadow: 0 0 10px rgba(189, 147, 249, 0.6);
    }
    .timeline-time { font-family: 'Rajdhani', monospace; font-size: 0.85rem; color: #8892b0; margin-bottom: 2px; }
    .timeline-event { font-size: 1rem; color: #e6edf3; }

    /* Fix Streamlit UI Elements */
    div[data-testid="stVerticalBlock"] > div { padding: 0 !important; }
</style>
""", unsafe_allow_html=True)

# ============================================================
# STATE & DATA FETCHING
# ============================================================
try:
    res = requests.get(f"{API_URL}/state", timeout=1.0)
    state = res.json()
    api_online = True
except:
    api_online = False
    state = {
        "mic_muted": False,
        "last_alert": "API OFFLINE - Connection Lost",
        "last_alert_time": ""
    }

frame_exists = os.path.exists(FRAME_PATH)

# Initialize Session State Activity Log
if "activity_log" not in st.session_state:
    st.session_state.activity_log = [
        {"time": datetime.now().strftime("%H:%M:%S"), "event": "SYSTEM INITIALIZED"},
    ]

# Update Activity Log
current_alert = state.get("last_alert", "")
last_logged = st.session_state.activity_log[-1]["event"] if st.session_state.activity_log else ""

if current_alert and current_alert != last_logged and "Monitoring Active" not in current_alert and "API OFFLINE" not in current_alert:
    st.session_state.activity_log.append({
        "time": state.get("last_alert_time", datetime.now().strftime("%H:%M:%S")),
        "event": current_alert.upper()
    })
    if len(st.session_state.activity_log) > 5:
        st.session_state.activity_log.pop(0)

# ============================================================
# TOP NAVIGATION HEADER
# ============================================================
dot_class = "online" if api_online else "offline"
sys_text = "SYSTEM ONLINE" if api_online else "SYSTEM OFFLINE"
header_html = f"""
<div class="cyber-header">
    <div class="project-title">
        <span class="hud-dot {dot_class}"></span>
        AMBIENT INTELLIGENCE HUB
    </div>
    <div style="text-align: right;">
        <div style="font-family: 'Rajdhani', monospace; font-size: 1.2rem; color: #00ffcc; letter-spacing: 2px;">
            {sys_text}
        </div>
        <div style="font-family: 'Rajdhani', sans-serif; font-size: 1.1rem; color: #8892b0; letter-spacing: 1px;">
            {datetime.now().strftime('%Y.%m.%d // %H:%M:%S')}
        </div>
    </div>
</div>
"""
st.markdown(header_html, unsafe_allow_html=True)

# ============================================================
# MAIN LAYOUT: ASYMMETRIC GRID
# ============================================================
col_left, col_right = st.columns([1.7, 1.0], gap="large")

with col_left:
    # -----------------------------
    # 1. LIVE VISION FEED (CINEMATIC)
    # -----------------------------
    st.markdown("<div class='hud-title'>📺 LIVE VISION FEED // OP-CAM-01</div>", unsafe_allow_html=True)
    
    if frame_exists:
        try:
            with open(FRAME_PATH, "rb") as f:
                img_b64 = base64.b64encode(f.read()).decode()
            
            camera_html = f"""
            <div class="hud-camera-wrapper">
                <div class="overlay-badges">
                    <div class="cyber-badge badge-cyan">👁️ YOLOv8 ACTIVE</div>
                    <div class="cyber-badge badge-purple">⚠️ FALL DETECTION: ON</div>
                </div>
                <img src="data:image/jpeg;base64,{img_b64}" />
                <div class="camera-timestamp">SYNC: {datetime.now().strftime('%H:%M:%S.%f')[:-3]}</div>
            </div>
            """
            st.markdown(camera_html, unsafe_allow_html=True)
        except Exception:
            # Fallback during read/write conflict
            st.markdown("""
            <div class="hud-camera-wrapper" style="height: 500px; display:flex; align-items:center; justify-content:center;">
                <h3 style="color:#00ffcc; font-family:'Rajdhani', monospace;">[ SYNCING FEED... ]</h3>
            </div>
            """, unsafe_allow_html=True)
    else:
        st.markdown("""
        <div class="hud-camera-wrapper" style="height: 500px; display:flex; align-items:center; justify-content:center; border-color: rgba(255,51,102,0.3);">
            <div style="text-align:center;">
                <div style="font-size: 4rem; margin-bottom: 10px;">🔌</div>
                <h2 style="color:#ff3366; font-family:'Rajdhani', monospace; letter-spacing:2px;">[ SIGNAL LOST ]</h2>
                <p style="color:#8892b0;">INITIALIZE YOLO_TRACKER.PY TO RESTORE UPLINK</p>
            </div>
        </div>
        """, unsafe_allow_html=True)

with col_right:
    # -----------------------------
    # 2. SECURITY STATUS PANEL
    # -----------------------------
    alert_text = state.get("last_alert", "MONITORING ACTIVE")
    is_critical = "CRITICAL" in alert_text.upper() or "FALL" in alert_text.upper() or not api_online
    
    panel_class = "cyber-panel panel-critical" if is_critical else "cyber-panel"
    status_color = "#ff3366" if is_critical else "#00ffcc"
    
    status_html = f"""
    <div class="{panel_class}">
        <div class="hud-title">🛡️ SECURITY STATUS</div>
        <div class="hud-value" style="color: {status_color}; text-shadow: 0 0 15px {status_color}60;">
            {alert_text.upper()}
        </div>
        <div style="color: #8892b0; font-family: 'Rajdhani', monospace; margin-top:10px; font-size: 1.1rem;">
            LATEST EVENT: {state.get('last_alert_time', datetime.now().strftime('%H:%M:%S')) if state.get('last_alert_time') else datetime.now().strftime('%H:%M:%S')}
        </div>
    </div>
    """
    st.markdown(status_html, unsafe_allow_html=True)

    # -----------------------------
    # 3. HIGH-TECH MIC TOGGLE
    # -----------------------------
    is_muted = state.get("mic_muted", False)
    
    if is_muted:
        btn_bg = "linear-gradient(90deg, rgba(255, 51, 102, 0.1), rgba(255, 51, 102, 0.2))"
        btn_border = "#ff3366"
        btn_shadow = "rgba(255, 51, 102, 0.4)"
        btn_text = "🔇 MICROPHONE: MUTED (ENGAGE)"
        btn_color = "#ff3366"
    else:
        btn_bg = "linear-gradient(90deg, rgba(0, 255, 204, 0.05), rgba(0, 255, 204, 0.15))"
        btn_border = "#00ffcc"
        btn_shadow = "rgba(0, 255, 204, 0.3)"
        btn_text = "🎙️ MICROPHONE: LISTENING (MUTE)"
        btn_color = "#00ffcc"
        
    st.markdown(f"""
    <style>
    div.stButton > button {{
        background: {btn_bg} !important;
        border: 1px solid {btn_border} !important;
        border-left: 4px solid {btn_border} !important;
        color: {btn_color} !important;
        box-shadow: 0 0 15px {btn_shadow}, inset 0 0 10px {btn_shadow} !important;
        border-radius: 8px !important;
        height: 65px;
        width: 100%;
        font-family: 'Rajdhani', sans-serif;
        font-size: 1.3rem;
        font-weight: 700;
        letter-spacing: 2px;
        text-transform: uppercase;
        transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
        margin-bottom: 25px;
    }}
    div.stButton > button:hover {{
        background: {btn_border} !important;
        color: #000 !important;
        box-shadow: 0 0 30px {btn_shadow} !important;
    }}
    div.stButton > button:focus:not(:active) {{
        border-color: {btn_border} !important;
        color: {btn_color} !important;
    }}
    </style>
    """, unsafe_allow_html=True)
    
    if st.button(btn_text, disabled=not api_online):
        try:
            requests.post(f"{API_URL}/toggle_mic", timeout=1)
            time.sleep(0.1)
            st.rerun()
        except:
            st.error("UPLINK FAILED")

    # -----------------------------
    # 4. HEALTH MONITORS
    # -----------------------------
    api_stat = "ONLINE" if api_online else "OFFLINE"
    api_cls = "status-ok" if api_online else "status-err"
    
    vis_stat = "ACTIVE" if frame_exists else "OFFLINE"
    vis_cls = "status-ok" if frame_exists else "status-err"
    
    vox_stat = "STANDBY" if api_online else "ERROR"
    vox_cls = "status-ok" if api_online else "status-err"

    health_html = f"""
    <div class="cyber-panel" style="padding: 20px;">
        <div class="hud-title" style="font-size:1.1rem; margin-bottom: 15px;">⚙️ SUBSYSTEM DIAGNOSTICS</div>
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
    """
    st.markdown(health_html, unsafe_allow_html=True)

    # -----------------------------
    # 5. TIMELINE ACTIVITY LOG
    # -----------------------------
    log_html = """
    <div class="cyber-panel">
        <div class="hud-title">📝 EVENT LOG</div>
        <div class="timeline">
    """
    for item in reversed(st.session_state.activity_log):
        log_html += f"""<div class="timeline-item">
<div class="timeline-time">{item['time']}</div>
<div class="timeline-event">{item['event']}</div>
</div>"""
    log_html += "</div></div>"
    st.markdown(log_html, unsafe_allow_html=True)

# ============================================================
# NEW: GESTURE CONFIGURATION & SMART HOME
# ============================================================
st.markdown("<div class='cyber-header' style='margin-top: 40px;'><div class='project-title' style='font-size: 1.8rem;'>⚙️ GESTURE MAPPING & APPLIANCES</div></div>", unsafe_allow_html=True)

col_g1, col_g2 = st.columns([1, 1], gap="large")

gesture_options = ["None", "Toggle Mic", "Toggle Light", "Toggle Fan"]
current_config = state.get("gesture_config", {})
smart_home = state.get("smart_home", {"light": False, "fan": False})

with col_g1:
    st.markdown("<div class='cyber-panel' style='padding-bottom: 5px;'>", unsafe_allow_html=True)
    st.markdown("<div class='hud-title' style='font-size: 1.1rem;'>🎯 GESTURE BINDINGS</div>", unsafe_allow_html=True)
    
    # We use Streamlit selectboxes
    new_config = {}
    new_config["left_arm_up"] = st.selectbox("LEFT ARM RAISED", gesture_options, index=gesture_options.index(current_config.get("left_arm_up", "Toggle Mic")))
    new_config["right_arm_up"] = st.selectbox("RIGHT ARM RAISED", gesture_options, index=gesture_options.index(current_config.get("right_arm_up", "Toggle Light")))
    new_config["both_arms_up"] = st.selectbox("BOTH ARMS RAISED", gesture_options, index=gesture_options.index(current_config.get("both_arms_up", "Toggle Fan")))
    new_config["t_pose"] = st.selectbox("T-POSE (ARMS STRETCHED)", gesture_options, index=gesture_options.index(current_config.get("t_pose", "None")))
    
    if new_config != current_config and api_online:
        try:
            requests.post(f"{API_URL}/update_config", json=new_config, timeout=1)
        except:
            pass
    st.markdown("</div>", unsafe_allow_html=True)

with col_g2:
    st.markdown("<div class='cyber-panel' style='height: 100%;'>", unsafe_allow_html=True)
    st.markdown("<div class='hud-title' style='font-size: 1.1rem;'>🏠 SMART HOME APPLIANCES</div>", unsafe_allow_html=True)
    
    light_stat = "ON 💡" if smart_home.get("light") else "OFF ⚫"
    light_cls = "status-ok" if smart_home.get("light") else "status-err"
    
    fan_stat = "ON 🌀" if smart_home.get("fan") else "OFF ⚫"
    fan_cls = "status-ok" if smart_home.get("fan") else "status-err"
    
    st.markdown(f"""
    <div class="health-grid" style="grid-template-columns: 1fr 1fr; margin-top: 30px;">
        <div class="health-item" style="padding: 30px 15px;">
            <div class="health-label">SMART LIGHT</div>
            <div class="health-status {light_cls}" style="font-size: 2rem;">{light_stat}</div>
        </div>
        <div class="health-item" style="padding: 30px 15px;">
            <div class="health-label">SMART FAN</div>
            <div class="health-status {fan_cls}" style="font-size: 2rem;">{fan_stat}</div>
        </div>
    </div>
    """, unsafe_allow_html=True)
    st.markdown("</div>", unsafe_allow_html=True)

# ============================================================
# AUTO-REFRESH LOOP
# ============================================================
time.sleep(0.05)
st.rerun()
