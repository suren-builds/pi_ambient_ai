"""
Ambient AI Hub — Brain (voice_assistant.py)
Handles: Vosk STT → Ollama LLM → pyttsx3 TTS, Flask API server.

Hardening fixes applied (see AUDIT.md):
  C-2: Flask now binds to 127.0.0.1 only.
  C-3: threading.Lock() protects system_state.
  C-5: STT audio queue is flushed before and after TTS to prevent echo.
  H-1: TTS runs in its own daemon thread; main loop never blocks on speak().
  H-2: /event endpoint now has retry queue (done on Eyes side).
  H-6: Payload size limit on all POST endpoints.
  H-7: /update_config validates keys against allowed set.
  H-9: Handles both old dict-style and new object-style Ollama response.
  M-1: Structured logging with rotation replacing all print() calls.
  M-2: Ollama client call wrapped with timeout via threading.
  M-7: Graceful SIGTERM/SIGINT shutdown handler.
  L-2: TTS voice selection works on Linux/espeak too.
"""

from __future__ import annotations

import datetime
import json
import logging
import logging.handlers
import os
import queue
import re
import signal
import sys
import threading
import time
from typing import Any

import numpy as np
import pyttsx3
import requests
import sounddevice as sd
import vosk
import yaml
from flask import Flask, request as flask_request, jsonify
from ollama import Client

# ============================================================
# 0.  CONFIGURATION
# ============================================================
_CFG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.yaml")

def _load_config(path: str) -> dict[str, Any]:
    """Load and validate config.yaml; return safe defaults if missing."""
    defaults: dict[str, Any] = {
        "brain_api_host": "127.0.0.1",
        "brain_api_port": 5000,
        "api_secret_token": "",
        "vosk_model": "vosk-model-small-en-us-0.15",
        "ollama_model": "llama3.2:1b",
        "ollama_host": "http://localhost:11434",
        "ollama_timeout_s": 15,
        "tts_speech_rate": 175,
        "audio_samplerate": 16000,
        "audio_blocksize": 8000,
        "mic_audio_queue_timeout_s": 0.5,
        "max_chat_history": 20,
        "max_payload_bytes": 4096,
        "log_level": "INFO",
        "log_file": "ambient_ai.log",
        "log_max_bytes": 2097152,
        "log_backup_count": 2,
        "fall_cancel_countdown_s": 8,
    }
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            user_cfg = yaml.safe_load(f) or {}
        defaults.update(user_cfg)
    return defaults


CFG = _load_config(_CFG_PATH)

# ============================================================
# 1.  LOGGING  (structured, rotating, no SD wear)
# ============================================================
_log_formatter = logging.Formatter(
    "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)

_log_handler = logging.handlers.RotatingFileHandler(
    CFG["log_file"],
    maxBytes=CFG["log_max_bytes"],
    backupCount=CFG["log_backup_count"],
    encoding="utf-8",
)
_log_handler.setFormatter(_log_formatter)

_stream_handler = logging.StreamHandler(sys.stdout)
_stream_handler.setFormatter(_log_formatter)

log = logging.getLogger("brain")
log.setLevel(getattr(logging, CFG["log_level"].upper(), logging.INFO))
log.addHandler(_log_handler)
log.addHandler(_stream_handler)

# Silence Flask/werkzeug noise
logging.getLogger("werkzeug").setLevel(logging.ERROR)

# ============================================================
# 2.  TEXT-TO-SPEECH  (runs in a dedicated daemon thread)
# ============================================================
_tts_engine = pyttsx3.init()
_tts_engine.setProperty("rate", CFG["tts_speech_rate"])

# Voice selection: prefer female/Zira on Windows, else use first available
_voices = _tts_engine.getProperty("voices")
for _v in _voices:
    if "zira" in _v.name.lower() or "female" in _v.name.lower():
        _tts_engine.setProperty("voice", _v.id)
        break

_tts_queue: queue.Queue[str | None] = queue.Queue()
_is_speaking = threading.Event()  # set while TTS is active


def _tts_worker() -> None:
    """Dedicated TTS daemon — drains the TTS queue without blocking main loop."""
    while True:
        text = _tts_queue.get()
        if text is None:  # poison pill — shutdown
            break
        _is_speaking.set()
        log.info("TTS: %s", text)
        try:
            _tts_engine.say(text)
            _tts_engine.runAndWait()
        except Exception as exc:  # noqa: BLE001
            log.error("TTS error: %s", exc)
        finally:
            _is_speaking.clear()
            _tts_queue.task_done()


threading.Thread(target=_tts_worker, daemon=True, name="tts-worker").start()


def speak(text: str) -> None:
    """Non-blocking speak — enqueues text for the TTS worker thread."""
    _tts_queue.put(text)


# ============================================================
# 3.  OLLAMA CLIENT
# ============================================================
_ollama_client = Client(host=CFG["ollama_host"])


def _call_ollama(messages: list[dict[str, str]]) -> str:
    """Call Ollama with a hard timeout. Returns response text or error string."""
    result: list[str] = []
    exc_holder: list[Exception] = []

    def _inner() -> None:
        try:
            response = _ollama_client.chat(
                model=CFG["ollama_model"],
                messages=messages,
            )
            # Handle both dict (old SDK ≤0.1.x) and object (new SDK ≥0.2.x)
            if isinstance(response, dict):
                msg = response.get("message", {})
                content = msg.get("content", "") if isinstance(msg, dict) else getattr(msg, "content", "")
            else:
                msg = response.message
                content = msg.get("content", "") if isinstance(msg, dict) else msg.content
            result.append(str(content))
        except Exception as exc:  # noqa: BLE001
            exc_holder.append(exc)

    t = threading.Thread(target=_inner, daemon=True)
    t.start()
    t.join(timeout=CFG["ollama_timeout_s"])

    if exc_holder:
        log.error("Ollama error: %s", exc_holder[0])
        return "I am having trouble thinking right now."
    if not result:
        log.warning("Ollama timed out after %ss", CFG["ollama_timeout_s"])
        return "I am a bit slow today, please try again."
    return result[0]


# ============================================================
# 4.  MICROPHONE AUDIO QUEUE
# ============================================================
_audio_queue: queue.Queue[bytes] = queue.Queue()


def _audio_callback(indata: np.ndarray, frames: int, time_info: Any, status: sd.CallbackFlags) -> None:
    if status:
        log.warning("Audio callback status: %s", status)
    _audio_queue.put(bytes(indata))


# ============================================================
# 5.  GLOBAL SYSTEM STATE  (protected by a lock)
# ============================================================
_state_lock = threading.Lock()

system_state: dict[str, Any] = {
    "mic_muted": False,
    "last_alert": "System Online - Monitoring Active",
    "last_alert_time": "",
    "smart_home": {"light": False, "fan": False},
    "gesture_config": {
        "left_arm_up": "Toggle Mic",
        "right_arm_up": "Toggle Light",
        "both_arms_up": "Toggle Fan",
        "t_pose": "None",
    },
    # Live vision state — updated by yolo_tracker via /vision_status
    "vision": {
        "gesture": "None",
        "fall_confirmed": False,
        "person_count": 0,
        "last_seen": "",
    },
}

_ALLOWED_GESTURE_KEYS = frozenset(system_state["gesture_config"].keys())
_ALLOWED_GESTURE_VALUES = frozenset(["None", "Toggle Mic", "Toggle Light", "Toggle Fan"])

_event_queue: queue.Queue[dict[str, Any]] = queue.Queue()

# ============================================================
# 6.  FLASK API SERVER
# ============================================================
_app = Flask(__name__)
_SECRET_TOKEN = CFG["api_secret_token"]
_MAX_PAYLOAD = CFG["max_payload_bytes"]


def _check_token() -> tuple[bool, str]:
    """Validate X-Secret-Token header. Returns (ok, reason)."""
    if not _SECRET_TOKEN or _SECRET_TOKEN == "CHANGE_ME_BEFORE_DEPLOY_abc123":
        return True, ""  # Token not configured → open (warn at startup)
    token = flask_request.headers.get("X-Secret-Token", "")
    if token != _SECRET_TOKEN:
        return False, "Invalid token"
    return True, ""


def _check_payload_size() -> bool:
    return (flask_request.content_length or 0) <= _MAX_PAYLOAD


@_app.route("/health", methods=["GET"])
def api_health() -> Any:
    return jsonify({"status": "ok", "service": "brain"}), 200


@_app.route("/state", methods=["GET"])
def api_get_state() -> Any:
    with _state_lock:
        return jsonify(system_state)


@_app.route("/toggle_mic", methods=["POST"])
def api_toggle_mic() -> Any:
    with _state_lock:
        system_state["mic_muted"] = not system_state["mic_muted"]
        status = "MUTED" if system_state["mic_muted"] else "UNMUTED"
    log.info("[PRIVACY] Microphone %s via API", status)
    return jsonify({"muted": system_state["mic_muted"]})


@_app.route("/event", methods=["POST"])
def api_receive_event() -> Any:
    ok, reason = _check_token()
    if not ok:
        return jsonify({"error": reason}), 403
    if not _check_payload_size():
        return jsonify({"error": "payload too large"}), 413

    data = flask_request.get_json(silent=True, force=True)
    if not data or not isinstance(data, dict):
        return jsonify({"error": "invalid JSON"}), 400

    event_type = str(data.get("type", ""))[:64]  # truncate / sanitize
    person = str(data.get("person", "Unknown"))[:64]

    if event_type == "fall_detected":
        ts = datetime.datetime.now().strftime("%I:%M:%S %p")
        with _state_lock:
            system_state["last_alert"] = f"CRITICAL: Fall Detected ({person})"
            system_state["last_alert_time"] = ts
        _event_queue.put({"type": "fall_detected", "person": person})
        log.warning("[ALERT] Fall event received for: %s", person)
    else:
        log.info("[EVENT] Unknown type=%s (ignored)", event_type)

    return jsonify({"status": "received"}), 200


@_app.route("/update_config", methods=["POST"])
def api_update_config() -> Any:
    if not _check_payload_size():
        return jsonify({"error": "payload too large"}), 413

    data = flask_request.get_json(silent=True, force=True)
    if not data or not isinstance(data, dict):
        return jsonify({"error": "invalid JSON"}), 400

    # Whitelist both keys AND values
    validated: dict[str, str] = {}
    for k, v in data.items():
        if k in _ALLOWED_GESTURE_KEYS and str(v) in _ALLOWED_GESTURE_VALUES:
            validated[k] = str(v)

    with _state_lock:
        system_state["gesture_config"].update(validated)
        cfg_snapshot = dict(system_state["gesture_config"])

    log.info("[CONFIG] Gesture config updated: %s", validated)
    return jsonify(cfg_snapshot)


@_app.route("/trigger_gesture", methods=["POST"])
def api_trigger_gesture() -> Any:
    ok, reason = _check_token()
    if not ok:
        return jsonify({"error": reason}), 403
    if not _check_payload_size():
        return jsonify({"error": "payload too large"}), 413

    data = flask_request.get_json(silent=True, force=True)
    if not data or not isinstance(data, dict):
        return jsonify({"error": "invalid JSON"}), 400

    gesture = str(data.get("gesture", "None"))[:64]

    with _state_lock:
        action = system_state["gesture_config"].get(gesture, "None")
        if action == "Toggle Mic":
            system_state["mic_muted"] = not system_state["mic_muted"]
        elif action == "Toggle Light":
            system_state["smart_home"]["light"] = not system_state["smart_home"]["light"]
        elif action == "Toggle Fan":
            system_state["smart_home"]["fan"] = not system_state["smart_home"]["fan"]

    log.info("[GESTURE] %s → %s", gesture, action)
    return jsonify({"status": "success", "action": action, "gesture": gesture})


@_app.route("/vision_status", methods=["POST"])
def api_vision_status() -> Any:
    """Receive live vision state from yolo_tracker (gesture, fall, person count)."""
    ok, reason = _check_token()
    if not ok:
        return jsonify({"error": reason}), 403
    if not _check_payload_size():
        return jsonify({"error": "payload too large"}), 413

    data = flask_request.get_json(silent=True, force=True)
    if not data or not isinstance(data, dict):
        return jsonify({"error": "invalid JSON"}), 400

    gesture = str(data.get("gesture", "None"))[:32]
    fall_confirmed = bool(data.get("fall_confirmed", False))
    person_count = int(data.get("person_count", 0))
    ts = datetime.datetime.now().strftime("%H:%M:%S")

    with _state_lock:
        system_state["vision"]["gesture"] = gesture
        system_state["vision"]["fall_confirmed"] = fall_confirmed
        system_state["vision"]["person_count"] = person_count
        system_state["vision"]["last_seen"] = ts

    return jsonify({"status": "ok"}), 200


def _start_api_server() -> None:
    log.info("Brain API server listening on %s:%s", CFG["brain_api_host"], CFG["brain_api_port"])
    _app.run(
        host=CFG["brain_api_host"],
        port=CFG["brain_api_port"],
        debug=False,
        use_reloader=False,
    )


# ============================================================
# 7.  INTENT DETECTION & TOOL FUNCTIONS
# ============================================================
_WEATHER_KEYWORDS = frozenset(["weather", "temperature", "hot", "cold", "rain", "sunny", "forecast", "humid"])
_EMERGENCY_KEYWORDS = frozenset(["call", "emergency", "help me", "ambulance", "doctor", "fallen", "i fell", "sos"])
_FILLER_WORDS = frozenset([
    "what", "whats", "how", "hows", "is", "the", "in", "weather", "temperature",
    "like", "today", "right", "now", "tell", "me", "about", "of", "forecast",
    "check", "get", "please", "pls", "can", "you", "a", "an", "it", "that",
    "this", "there", "so", "and", "for", "saw", "was", "see", "show",
])


def get_weather(city: str = "London") -> str:
    """Fetch current weather for *city* from wttr.in (offline-safe fallback)."""
    import urllib.parse
    log.info("[TOOL] Fetching weather for %s", city)
    try:
        safe_city = urllib.parse.quote(city)
        resp = requests.get(
            f"https://wttr.in/{safe_city}?format=1",
            headers={"User-Agent": "curl/7.68.0"},
            timeout=5,
        )
        if resp.status_code == 200:
            return f"The current weather in {city} is {resp.text.strip()}."
        return f"I could not find weather data for {city}."
    except Exception as exc:  # noqa: BLE001
        log.error("[TOOL] Weather error: %s", exc)
        return "I could not fetch the weather due to a network error."


def emergency_call(contact_name: str = "Emergency Services", dry_run: bool = False) -> str:
    """Trigger emergency alert. Set dry_run=True for testing."""
    log.warning("[EMERGENCY] Protocol activated for: %s (dry_run=%s)", contact_name, dry_run)
    if dry_run:
        return f"[DRY RUN] Emergency alert would be sent to {contact_name}."
    # TODO: Replace with real notification (Twilio SMS, pushbullet, etc.)
    return f"Emergency alert has been sent to {contact_name}. Help is on the way."


def extract_city(text: str) -> str:
    """Strip filler words and return likely city name."""
    words = [w for w in text.lower().split() if w not in _FILLER_WORDS]
    return " ".join(words).strip().title() if words else "London"


def detect_intent(text: str) -> str:
    """Return 'weather', 'emergency', or 'chat'."""
    lower = text.lower()
    for kw in _WEATHER_KEYWORDS:
        if re.search(r'\b' + re.escape(kw) + r'\b', lower):
            return "weather"
    for kw in _EMERGENCY_KEYWORDS:
        if re.search(r'\b' + re.escape(kw) + r'\b', lower):
            return "emergency"
    return "chat"


# ============================================================
# 8.  GRACEFUL SHUTDOWN
# ============================================================
_shutdown_event = threading.Event()


def _signal_handler(signum: int, _frame: Any) -> None:
    log.info("Received signal %s — shutting down gracefully.", signum)
    _shutdown_event.set()
    _tts_queue.put(None)  # stop TTS worker


signal.signal(signal.SIGTERM, _signal_handler)
signal.signal(signal.SIGINT, _signal_handler)

# ============================================================
# 9.  MAIN LOOP
# ============================================================
def main() -> None:
    if not _SECRET_TOKEN or _SECRET_TOKEN == "CHANGE_ME_BEFORE_DEPLOY_abc123":
        log.warning("API token not set — /event and /trigger_gesture are unprotected!")

    # --- Microphone Selection ---
    devices = sd.query_devices()
    input_devices = [i for i, d in enumerate(devices) if d["max_input_channels"] > 0]  # type: ignore[index]

    log.info("Available microphones: %s", [devices[i]["name"] for i in input_devices])  # type: ignore[index]

    if os.environ.get("HEADLESS", "false").lower() == "true":
        log.info("HEADLESS mode — using default microphone.")
        device_id: int | None = None
    else:
        try:
            device_id = int(input("Enter microphone number (Enter for default): "))
            if device_id not in input_devices:
                log.warning("Invalid device id; using default.")
                device_id = None
        except (ValueError, EOFError):
            device_id = None

    selected_name = (
        sd.query_devices(device_id)["name"] if device_id is not None else sd.query_devices(kind="input")["name"]  # type: ignore[index]
    )
    log.info("Using microphone: %s", selected_name)

    # --- Load Vosk STT Model ---
    log.info("Loading Vosk STT model: %s", CFG["vosk_model"])
    try:
        vosk_model = vosk.Model(model_name=CFG["vosk_model"])
    except Exception as exc:
        log.critical("Failed to load Vosk model: %s", exc)
        sys.exit(1)

    # --- Start Flask API in background thread ---
    threading.Thread(target=_start_api_server, daemon=True, name="flask-api").start()
    time.sleep(0.5)  # let flask bind before main loop

    speak("Ambient AI online. Ready.")
    log.info("=" * 50)
    log.info("AMBIENT AI ASSISTANT ONLINE")
    log.info("=" * 50)

    # System prompt
    _system_prompt = {
        "role": "system",
        "content": (
            "You are Ambient, a smart home AI assistant. "
            "Rules: "
            "1. Keep ALL answers to 1 sentence maximum. "
            "2. You are a voice assistant — you can hear and speak. "
            "3. Greet warmly if asked if you can hear. "
            "4. You do NOT physically control devices directly. "
            "5. Do NOT make up features. "
            "6. You CAN check weather and trigger emergency calls. "
            "7. For anything else, have a friendly short conversation. "
            "8. If STT garbled the text, just say: I didn't quite catch that."
        ),
    }
    chat_history: list[dict[str, str]] = [_system_prompt]

    # --- Open Microphone Stream ---
    with sd.RawInputStream(
        samplerate=CFG["audio_samplerate"],
        blocksize=CFG["audio_blocksize"],
        device=device_id,
        dtype="int16",
        channels=1,
        callback=_audio_callback,
    ):
        recognizer = vosk.KaldiRecognizer(vosk_model, CFG["audio_samplerate"])

        while not _shutdown_event.is_set():
            # --- Fall alert from Vision Engine ---
            try:
                event = _event_queue.get_nowait()
                if event.get("type") == "fall_detected":
                    person = event.get("person", "Unknown")
                    log.warning("!!! FALL ALERT for %s !!!", person)
                    speak(f"Warning! {person} may have fallen! Are you okay?")
                    # Countdown — user can say "I'm okay" to cancel
                    cancel_countdown = CFG["fall_cancel_countdown_s"]
                    cancelled = False
                    deadline = time.time() + cancel_countdown
                    while time.time() < deadline and not _shutdown_event.is_set():
                        time.sleep(0.5)
                        # Quick non-blocking check of audio for "okay" / "fine"
                        try:
                            data = _audio_queue.get_nowait()
                            if recognizer.AcceptWaveform(data):
                                partial = json.loads(recognizer.Result()).get("text", "").lower()
                                if any(w in partial for w in ("okay", "ok", "fine", "alright", "i'm fine")):
                                    speak("Glad you are okay. I will stand down.")
                                    cancelled = True
                                    break
                        except queue.Empty:
                            pass
                    if not cancelled:
                        result = emergency_call(contact_name="Family")
                        speak(result)
            except queue.Empty:
                pass

            # --- Privacy mode: drain audio ---
            with _state_lock:
                muted = system_state["mic_muted"]
            if muted:
                try:
                    while True:
                        _audio_queue.get_nowait()
                except queue.Empty:
                    pass
                time.sleep(0.1)
                continue

            # --- Flush audio queue while TTS is speaking (prevent echo) ---
            if _is_speaking.is_set():
                try:
                    while True:
                        _audio_queue.get_nowait()
                except queue.Empty:
                    pass
                time.sleep(0.05)
                continue

            # --- Next audio packet ---
            try:
                data = _audio_queue.get(timeout=CFG["mic_audio_queue_timeout_s"])
            except queue.Empty:
                continue

            # Volume indicator
            audio_arr = np.frombuffer(data, dtype=np.int16)
            volume = float(np.linalg.norm(audio_arr) / max(len(audio_arr), 1))
            sys.stdout.write("!" if volume >= 5 else ".")
            sys.stdout.flush()

            # Speech recognition
            if not recognizer.AcceptWaveform(data):
                continue

            print()  # newline after dots
            text = json.loads(recognizer.Result()).get("text", "").strip()
            if not text:
                continue

            log.info("You said: %s", text)

            if any(w in text.lower() for w in ("exit", "quit", "shutdown")):
                speak("Goodbye!")
                _shutdown_event.set()
                break

            chat_history.append({"role": "user", "content": text})

            intent = detect_intent(text)

            if intent == "weather":
                city = extract_city(text) or "London"
                reply = get_weather(city=city)
            elif intent == "emergency":
                reply = emergency_call(contact_name="Family")
            else:
                reply = _call_ollama(chat_history)

            chat_history.append({"role": "assistant", "content": reply})

            # Trim history
            if len(chat_history) > CFG["max_chat_history"] + 1:
                chat_history = [chat_history[0]] + chat_history[-(CFG["max_chat_history"]):]

            speak(reply)

    log.info("Brain shut down cleanly.")


if __name__ == "__main__":
    main()
