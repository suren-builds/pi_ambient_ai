"""
Ambient AI Hub — Vision Engine (yolo_tracker.py)
Handles: YOLOv8n-pose, LBPH face recognition, fall detection,
         gesture control, MOG2 wake-on-motion.

Hardening fixes applied (see AUDIT.md):
  C-1: this_person_falling initialised before loop so no NameError.
  C-4: Atomic JPEG write (write to .tmp, rename) prevents torn reads.
  H-2: HTTP POST to Brain uses retry with exponential backoff.
  H-8: face_recognizer flag tracks whether model is usable; safe fallback.
  M-3: Model path resolved to absolute at startup.
  M-4: enroll_owner.py CAP_DSHOW bug documented; yolo_tracker uses correct Pi path.
  M-6: MOG2 history raised to 500 per config.
  M-7: SIGTERM/SIGINT handler releases camera gracefully.
  M-9: LBPH threshold tightened from 120 → config value (default 80).
  M-1: Structured logging replaces print().
"""

from __future__ import annotations

import logging
import logging.handlers
import os
import signal
import sys
import tempfile
import threading
import time
from typing import Any

import cv2
import numpy as np
import requests
import yaml

# ============================================================
# 0.  CONFIGURATION
# ============================================================
_DIR = os.path.dirname(os.path.abspath(__file__))
_CFG_PATH = os.path.join(_DIR, "config.yaml")


def _load_config(path: str) -> dict[str, Any]:
    defaults: dict[str, Any] = {
        "brain_api_host": "127.0.0.1",
        "brain_api_port": 5000,
        "api_secret_token": "",
        "yolo_model": "yolov8n-pose.pt",
        "face_model_path": "owner_face_model.yml",
        "yolo_confidence": 0.5,
        "yolo_frame_width": 1280,
        "yolo_frame_height": 720,
        "dashboard_frame_width": 640,
        "dashboard_frame_height": 360,
        "fall_confirm_frames": 3,
        "fall_alert_cooldown_s": 30,
        "fall_score_threshold": 3,
        "lbph_confidence_threshold": 80,
        "gesture_cooldown_s": 3.0,
        "gesture_arm_raise_threshold_px": 50,
        "motion_sleep_timeout_s": 10.0,
        "motion_pixel_threshold": 500,
        "mog2_history": 500,
        "mog2_var_threshold": 50,
        "http_timeout_s": 1.0,
        "http_max_retries": 3,
        "http_retry_backoff_s": 0.5,
        "log_level": "INFO",
        "log_file": "ambient_ai.log",
        "log_max_bytes": 2097152,
        "log_backup_count": 2,
        "cpu_throttle_temp_c": 75,
        "cpu_pause_temp_c": 85,
    }
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            user_cfg = yaml.safe_load(f) or {}
        defaults.update(user_cfg)
    return defaults


CFG = _load_config(_CFG_PATH)

_BRAIN_API = f"http://{CFG['brain_api_host']}:{CFG['brain_api_port']}"
_SECRET_TOKEN = CFG["api_secret_token"]
_HEADERS = {"X-Secret-Token": _SECRET_TOKEN} if _SECRET_TOKEN else {}

HEADLESS = os.environ.get("HEADLESS", "false").lower() == "true"

# ============================================================
# 1.  LOGGING
# ============================================================
_fmt = logging.Formatter("%(asctime)s [%(levelname)s] eyes: %(message)s", datefmt="%Y-%m-%dT%H:%M:%S")

_fh = logging.handlers.RotatingFileHandler(
    CFG["log_file"], maxBytes=CFG["log_max_bytes"],
    backupCount=CFG["log_backup_count"], encoding="utf-8",
)
_fh.setFormatter(_fmt)
_sh = logging.StreamHandler(sys.stdout)
_sh.setFormatter(_fmt)

log = logging.getLogger("eyes")
log.setLevel(getattr(logging, CFG["log_level"].upper(), logging.INFO))
log.addHandler(_fh)
log.addHandler(_sh)

# ============================================================
# 2.  THERMAL GUARDRAIL  (Pi-specific)
# ============================================================
def _get_cpu_temp() -> float:
    """Return Pi CPU temperature in °C, or 0.0 if unavailable."""
    try:
        with open("/sys/class/thermal/thermal_zone0/temp") as f:
            return int(f.read().strip()) / 1000.0
    except OSError:
        return 0.0


# ============================================================
# 3.  MODEL INITIALISATION
# ============================================================
# Resolve paths absolutely
_YOLO_PATH = os.path.join(_DIR, CFG["yolo_model"])
_FACE_MODEL_PATH = os.path.join(_DIR, CFG["face_model_path"])
_FRAME_SAVE_PATH = os.path.join(_DIR, "latest_frame.jpg")

log.info("Loading YOLOv8-Pose model from %s", _YOLO_PATH)
from ultralytics import YOLO  # noqa: E402 — import after logging setup
yolo_model = YOLO(_YOLO_PATH)

log.info("Initialising webcam...")
_cap_backend = cv2.CAP_DSHOW if os.name == "nt" else cv2.CAP_ANY
cap = cv2.VideoCapture(0, _cap_backend)
cap.set(cv2.CAP_PROP_FRAME_WIDTH, CFG["yolo_frame_width"])
cap.set(cv2.CAP_PROP_FRAME_HEIGHT, CFG["yolo_frame_height"])

if not cap.isOpened():
    log.critical("Cannot open camera — exiting.")
    sys.exit(1)

# Face recognizer — requires opencv-contrib-python-headless
# If that package is missing, face recognition is silently disabled.
log.info("Loading LBPH face model from %s", _FACE_MODEL_PATH)
_face_model_ok = False
try:
    face_recognizer = cv2.face.LBPHFaceRecognizer_create()
    face_recognizer.read(_FACE_MODEL_PATH)
    _face_model_ok = True
    log.info("Face model loaded successfully.")
except AttributeError:
    log.warning("cv2.face.LBPHFaceRecognizer_create not available — "
                "install opencv-contrib-python-headless to enable face recognition. "
                "Fall detection and gestures are unaffected.")
    face_recognizer = None
except Exception as exc:
    log.warning("Could not load face model (%s). "
                "Run enroll_owner.py --skip first.", exc)
    face_recognizer = None

# ============================================================
# 4.  STATE VARIABLES
# ============================================================
_last_fall_alert_time: float = 0.0
_fall_frame_counter: int = 0
_last_gesture_time: float = 0.0
_frame_save_confirmed: bool = False

_motion_detector = cv2.createBackgroundSubtractorMOG2(
    history=CFG["mog2_history"],
    varThreshold=CFG["mog2_var_threshold"],
    detectShadows=False,
)
_last_motion_time: float = time.time()

# ============================================================
# 5.  GRACEFUL SHUTDOWN
# ============================================================
_shutdown_event = threading.Event()


def _shutdown_handler(signum: int, _frame: Any) -> None:
    log.info("Signal %s received — shutting down vision engine.", signum)
    _shutdown_event.set()


signal.signal(signal.SIGTERM, _shutdown_handler)
signal.signal(signal.SIGINT, _shutdown_handler)

# ============================================================
# 6.  HELPER FUNCTIONS
# ============================================================
def _avg_y(kpts: np.ndarray, indices: list[int]) -> float:
    """Average Y coordinate for given keypoint indices (0 = not visible)."""
    vals = [kpts[i][1] for i in indices if len(kpts) > i and kpts[i][1] > 0]
    return float(np.mean(vals)) if vals else 0.0


def _avg_x(kpts: np.ndarray, indices: list[int]) -> float:
    vals = [kpts[i][0] for i in indices if len(kpts) > i and kpts[i][0] > 0]
    return float(np.mean(vals)) if vals else 0.0


def recognize_face(frame: np.ndarray, kpts: np.ndarray) -> tuple[str, tuple[int, int, int], float]:
    """LBPH face recognition using YOLO face keypoints. Returns (name, colour, confidence)."""
    # In autonomous mode (no enrollment), label everyone as 'Person' with a neutral colour
    PERSON = ("Person", (100, 200, 255), 999.0)

    if not _face_model_ok or face_recognizer is None:
        return PERSON

    face_pts = [(kpts[i][0], kpts[i][1]) for i in range(5) if len(kpts) > i and kpts[i][0] > 0 and kpts[i][1] > 0]
    if len(face_pts) < 3:
        return UNKNOWN

    xs = [p[0] for p in face_pts]
    ys = [p[1] for p in face_pts]
    fw = max(xs) - min(xs)
    fh = max(ys) - min(ys)
    pad_x = int(fw * 0.5)
    pad_y_top = int(fh * 0.8)
    pad_y_bot = int(fh * 0.6)

    x1 = max(0, int(min(xs) - pad_x))
    y1 = max(0, int(min(ys) - pad_y_top))
    x2 = min(frame.shape[1], int(max(xs) + pad_x))
    y2 = min(frame.shape[0], int(max(ys) + pad_y_bot))

    face_crop = frame[y1:y2, x1:x2]
    if face_crop.size == 0:
        return UNKNOWN

    try:
        gray = cv2.cvtColor(face_crop, cv2.COLOR_BGR2GRAY)
        resized = cv2.resize(gray, (100, 100))
        if face_recognizer is None:
            return PERSON
        label, conf = face_recognizer.predict(resized)
        threshold = float(CFG["lbph_confidence_threshold"])
        if conf < threshold:
            return ("Owner", (0, 255, 0), float(conf))
        # High confidence = dummy model or genuine stranger; show Person not Unknown
        return ("Person", (100, 200, 255), float(conf))
    except Exception as exc:
        log.debug("Face recognition error: %s", exc)
        return PERSON


def compute_fall_score(
    sx: float, sy: float, hx: float, hy: float,
    ay: float, width: float, height: float, frame_h: int,
) -> tuple[int, bool, str, bool]:
    """
    Compute fall detection score.
    Returns (score, is_on_floor, debug_text, is_corrupted_skeleton).
    Fall = score >= threshold AND is_on_floor.
    """
    spine_x = abs(hx - sx)
    spine_y = abs(hy - sy)

    # Skeleton corruption guard
    if height > (width * 1.5) and spine_y < (height * 0.2):
        return 0, False, "CORRUPTED SKELETON", True

    score = 0
    if width > (height * 1.2):      score += 1  # box wider than tall
    if spine_x > (spine_y * 1.5):   score += 1  # spine nearly horizontal
    if sy > (hy - height * 0.1):    score += 1  # head dropped to hip level
    if ay > 0:
        if abs(ay - hy) < (height * 0.5):
            score += 1  # ankles collapsed
    else:
        score += 1  # ankles hidden = probably collapsed

    is_on_floor = hy > (frame_h * 0.5)
    debug = f"SpX:{int(spine_x)} SpY:{int(spine_y)} Sc:{score}/4 Fl:{is_on_floor}"
    return score, is_on_floor, debug, False


def _post_with_retry(url: str, payload: dict[str, Any]) -> bool:
    """POST with exponential backoff. Returns True on success."""
    delay = float(CFG["http_retry_backoff_s"])
    for attempt in range(int(CFG["http_max_retries"])):
        try:
            resp = requests.post(url, json=payload, headers=_HEADERS, timeout=float(CFG["http_timeout_s"]))
            if resp.status_code < 500:
                return True
        except requests.RequestException as exc:
            log.warning("POST %s attempt %d failed: %s", url, attempt + 1, exc)
        time.sleep(delay)
        delay *= 2
    log.error("POST %s failed after %d attempts.", url, CFG["http_max_retries"])
    return False


def send_fall_alert(person_name: str) -> None:
    """Send fall alert to Brain API with cooldown."""
    global _last_fall_alert_time
    now = time.time()
    if now - _last_fall_alert_time < float(CFG["fall_alert_cooldown_s"]):
        return
    log.warning("Sending FALL ALERT to Brain for: %s", person_name)
    success = _post_with_retry(
        f"{_BRAIN_API}/event",
        {"type": "fall_detected", "person": person_name},
    )
    if success:
        _last_fall_alert_time = now


def _atomic_save_frame(frame: np.ndarray) -> None:
    """Write JPEG atomically: write to .tmp then rename, preventing torn reads."""
    global _frame_save_confirmed
    tmp_path = _FRAME_SAVE_PATH + ".tmp"
    try:
        cv2.imwrite(tmp_path, frame, [cv2.IMWRITE_JPEG_QUALITY, 80])
        os.replace(tmp_path, _FRAME_SAVE_PATH)  # atomic on POSIX; best-effort on Windows
        if not _frame_save_confirmed:
            log.info("Dashboard frame path: %s", _FRAME_SAVE_PATH)
            _frame_save_confirmed = True
    except OSError as exc:
        log.error("Frame save error: %s", exc)

# ============================================================
# 7.  VISION STATE BROADCAST (for mobile dashboard)
# ============================================================
_last_vision_broadcast: float = 0.0
_vision_broadcast_interval: float = 0.5  # seconds between state pushes


def _broadcast_vision_state(gesture: str, fall_confirmed: bool, person_count: int) -> None:
    """Push current vision state to Brain /vision_status so dashboard shows live data."""
    global _last_vision_broadcast
    now = time.time()
    if now - _last_vision_broadcast < _vision_broadcast_interval:
        return
    _last_vision_broadcast = now
    _post_with_retry(
        f"{_BRAIN_API}/vision_status",
        {
            "gesture": gesture,
            "fall_confirmed": fall_confirmed,
            "person_count": person_count,
        },
    )


# ============================================================
# 8.  MAIN TRACKING LOOP
# ============================================================
def main() -> None:
    """Entry point — runs the vision tracking loop."""
    global _last_motion_time, _fall_frame_counter, _last_gesture_time

    log.info("Vision engine starting. Headless=%s", HEADLESS)

    try:
        while not _shutdown_event.is_set():
            ret, frame = cap.read()
            if not ret or frame is None:
                time.sleep(0.05)
                continue

            current_time = time.time()
            annotated_frame = frame.copy()

            # ── Thermal guardrail ───────────────────────────────
            temp = _get_cpu_temp()
            if temp >= CFG["cpu_pause_temp_c"]:
                log.warning("CPU temp %.1f°C >= pause threshold — pausing YOLO.", temp)
                time.sleep(1.0)
                continue

            throttle = temp >= CFG["cpu_throttle_temp_c"]

            # ── Motion detection (~1% CPU) ─────────────────────
            small = cv2.resize(frame, (320, 180))
            blurred = cv2.GaussianBlur(small, (21, 21), 0)
            fg_mask = _motion_detector.apply(blurred)
            kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
            fg_mask = cv2.morphologyEx(fg_mask, cv2.MORPH_OPEN, kernel)
            motion_pixels = cv2.countNonZero(fg_mask)

            if motion_pixels > CFG["motion_pixel_threshold"]:
                _last_motion_time = current_time

            # ── Sleep mode ─────────────────────────────────────
            idle_s = current_time - _last_motion_time
            if idle_s > CFG["motion_sleep_timeout_s"]:
                if not HEADLESS:
                    cv2.putText(annotated_frame, "SLEEP MODE (0% AI CPU)", (50, 80),
                                cv2.FONT_HERSHEY_SIMPLEX, 1.2, (0, 255, 255), 3)
                    cv2.putText(annotated_frame, f"Idle {int(idle_s)}s...", (50, 130),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.9, (150, 150, 150), 2)
                    small_f = cv2.resize(annotated_frame, (CFG["dashboard_frame_width"], CFG["dashboard_frame_height"]))
                    _atomic_save_frame(small_f)
                    cv2.imshow("Ambient AI Eyes", annotated_frame)
                    if cv2.waitKey(1) & 0xFF == ord("q"):
                        break
                else:
                    time.sleep(0.1)
                continue

            # ── YOLO inference ─────────────────────────────────
            results = yolo_model(frame, conf=CFG["yolo_confidence"], verbose=False)
            annotated_frame = results[0].plot()

            # FIX C-1: initialise BEFORE the boxes loop
            this_person_falling = False
            name = "Unknown"

            if (
                results[0].keypoints is not None
                and results[0].boxes is not None
                and len(results[0].boxes) > 0
            ):
                _last_motion_time = current_time  # human present → keep awake
                keypoints = results[0].keypoints.xy.cpu().numpy()
                boxes = results[0].boxes.xyxy.cpu().numpy()

                for i in range(len(boxes)):
                    x1, y1, x2, y2 = boxes[i]
                    w, h = x2 - x1, y2 - y1
                    kpts = keypoints[i]

                    sx = _avg_x(kpts, [5, 6])
                    sy = _avg_y(kpts, [5, 6])
                    hx = _avg_x(kpts, [11, 12])
                    hy = _avg_y(kpts, [11, 12])
                    ay = _avg_y(kpts, [15, 16])

                    # ── Gesture detection ──────────────────────
                    lsy = float(kpts[5][1]) if len(kpts) > 5 else 0.0
                    rsy = float(kpts[6][1]) if len(kpts) > 6 else 0.0
                    lwy = float(kpts[9][1]) if len(kpts) > 9 else 0.0
                    rwy = float(kpts[10][1]) if len(kpts) > 10 else 0.0
                    lwx = float(kpts[9][0]) if len(kpts) > 9 else 0.0
                    rwx = float(kpts[10][0]) if len(kpts) > 10 else 0.0
                    lsx = float(kpts[5][0]) if len(kpts) > 5 else 0.0
                    rsx = float(kpts[6][0]) if len(kpts) > 6 else 0.0

                    thresh = float(CFG["gesture_arm_raise_threshold_px"])
                    left_up = lsy > 0 and lwy > 0 and lwy < lsy - thresh
                    right_up = rsy > 0 and rwy > 0 and rwy < rsy - thresh

                    t_pose = (
                        lwy > 0 and rwy > 0
                        and abs(lwy - lsy) < 40 and abs(rwy - rsy) < 40
                        and abs(lwx - lsx) > 50 and abs(rwx - rsx) > 50
                    )

                    gesture_name = "None"
                    if t_pose:               gesture_name = "t_pose"
                    elif left_up and right_up: gesture_name = "both_arms_up"
                    elif left_up:             gesture_name = "left_arm_up"
                    elif right_up:            gesture_name = "right_arm_up"

                    if gesture_name != "None":
                        cv2.putText(annotated_frame, f"GESTURE: {gesture_name.upper()}",
                                    (int(x1), int(y1) - 60), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (255, 0, 255), 2)
                        if current_time - _last_gesture_time > float(CFG["gesture_cooldown_s"]):
                            log.info("Gesture: %s", gesture_name)
                            _post_with_retry(f"{_BRAIN_API}/trigger_gesture", {"gesture": gesture_name})
                            _last_gesture_time = current_time

                    # ── Face recognition ───────────────────────
                    name, color, conf = recognize_face(frame, kpts)
                    cv2.rectangle(annotated_frame, (int(x1), int(y1)), (int(x2), int(y2)), color, 2)
                    face_label = f"{name} ({int(conf)})" if conf < 900 else name
                    cv2.putText(annotated_frame, face_label, (int(x1), int(y1) - 35),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.9, color, 2)

                    # ── Fall detection ─────────────────────────
                    if sy > 0 and hy > 0:
                        score, on_floor, debug_text, corrupted = compute_fall_score(
                            sx, sy, hx, hy, ay, w, h, frame.shape[0]
                        )
                        cv2.putText(annotated_frame, debug_text, (int(x1), int(y1) - 10),
                                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 0), 1)

                        if not corrupted and score >= CFG["fall_score_threshold"] and on_floor:
                            this_person_falling = True
                            cv2.rectangle(annotated_frame, (int(x1), int(y1)), (int(x2), int(y2)), (0, 165, 255), 3)
                            cv2.putText(annotated_frame,
                                        f"Verifying... ({_fall_frame_counter}/{CFG['fall_confirm_frames']})",
                                        (int(x1), int(y1) - 65), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 165, 255), 2)

            # ── Temporal fall confirmation ──────────────────────
            if this_person_falling:
                _fall_frame_counter += 1
            else:
                _fall_frame_counter = 0

            fall_confirmed_now = _fall_frame_counter >= CFG["fall_confirm_frames"]
            if fall_confirmed_now:
                cv2.putText(annotated_frame, "!!! CONFIRMED FALL !!!", (50, 100),
                            cv2.FONT_HERSHEY_SIMPLEX, 2, (0, 0, 255), 5)
                send_fall_alert(name)

            # ── Broadcast vision state for mobile dashboard ─────
            _broadcast_vision_state(
                gesture=gesture_name if 'gesture_name' in dir() else "None",
                fall_confirmed=fall_confirmed_now,
                person_count=len(results[0].boxes) if results[0].boxes is not None else 0,
            )

            # ── Save frame for dashboard (atomic) ──────────────
            small_frame = cv2.resize(annotated_frame, (CFG["dashboard_frame_width"], CFG["dashboard_frame_height"]))
            _atomic_save_frame(small_frame)

            # ── Display (non-headless) ─────────────────────────
            if not HEADLESS:
                cv2.imshow("Ambient AI Eyes", annotated_frame)
                key = cv2.waitKey(1 if not throttle else 1000) & 0xFF
                if key == ord("q"):
                    break
            elif throttle:
                time.sleep(1.0)

    finally:
        log.info("Releasing camera and cleaning up.")
        if cap:
            cap.release()
        if not HEADLESS:
            cv2.destroyAllWindows()
        log.info("Vision engine shut down cleanly.")


if __name__ == "__main__":
    main()

