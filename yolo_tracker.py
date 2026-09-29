"""
Ambient AI Vision Engine - The Eyes
Handles: YOLOv8-Pose, Fall Detection, Face Recognition, Wake-on-Motion
"""

import cv2
import numpy as np
from ultralytics import YOLO
import requests
import time
import os

# ============================================================
# 1. INITIALIZE MODELS & CONFIG
# ============================================================
HEADLESS = os.environ.get('HEADLESS', 'False').lower() == 'true'
if HEADLESS:
    print("[!] RUNNING IN HEADLESS MODE (No Video Windows)")

print("Initializing YOLOv8-Pose Model...")
model = YOLO('yolov8n-pose.pt')

import sys

print("Initializing Laptop Webcam...")
if os.name == 'nt':
    cap = cv2.VideoCapture(0, cv2.CAP_DSHOW)
else:
    cap = cv2.VideoCapture(0) # Use default V4L2 on Raspberry Pi
cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)

print("Loading Owner Face Model...")
face_recognizer = cv2.face.LBPHFaceRecognizer_create()
try:
    face_recognizer.read('owner_face_model.yml')
    print("Owner Face Model loaded successfully!")
except Exception as e:
    print("Warning: Could not load owner_face_model.yml. Run enroll_owner.py first!")

# ============================================================
# 2. STATE VARIABLES
# ============================================================
last_fall_alert_time = 0
FRAME_SAVE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "latest_frame.jpg")

# Temporal fall filter: require N consecutive frames before triggering
# A real fall = person stays down. A false positive = 1-2 frames of weird skeleton.
fall_frame_counter = 0
FALL_CONFIRM_FRAMES = 3  # Reduced to 3 for almost immediate detection

last_gesture_time = 0
GESTURE_COOLDOWN = 3.0


# Wake-on-Motion optimization
motion_detector = cv2.createBackgroundSubtractorMOG2(history=100, varThreshold=50, detectShadows=False)
last_motion_time = time.time()
SLEEP_TIMEOUT = 5.0  # Seconds of stillness before YOLO shuts off

# ============================================================
# 3. HELPER FUNCTIONS
# ============================================================
def get_avg_y(kpts, indices):
    """Get average Y coordinate from a list of keypoint indices."""
    valid = [kpts[i][1] for i in indices if len(kpts) > i and kpts[i][1] > 0]
    return sum(valid) / len(valid) if valid else 0

def get_avg_x(kpts, indices):
    """Get average X coordinate from a list of keypoint indices."""
    valid = [kpts[i][0] for i in indices if len(kpts) > i and kpts[i][0] > 0]
    return sum(valid) / len(valid) if valid else 0

def recognize_face(frame, person_kpts):
    """Try to recognize the face using LBPH. Returns (name, color, confidence)."""
    face_pts = []
    for idx in range(5):
        if len(person_kpts) > idx and person_kpts[idx][0] > 0 and person_kpts[idx][1] > 0:
            face_pts.append((person_kpts[idx][0], person_kpts[idx][1]))

    if len(face_pts) < 3:
        return "Unknown", (200, 200, 200), 999

    xs = [p[0] for p in face_pts]
    ys = [p[1] for p in face_pts]
    min_x, max_x = min(xs), max(xs)
    min_y, max_y = min(ys), max(ys)

    fw = max_x - min_x
    fh = max_y - min_y
    pad_x = int(fw * 0.5)
    pad_y_top = int(fh * 0.8)
    pad_y_bot = int(fh * 0.6)

    fx1 = max(0, int(min_x - pad_x))
    fy1 = max(0, int(min_y - pad_y_top))
    fx2 = min(frame.shape[1], int(max_x + pad_x))
    fy2 = min(frame.shape[0], int(max_y + pad_y_bot))

    face_crop = frame[fy1:fy2, fx1:fx2]
    if face_crop.size == 0:
        return "Unknown", (200, 200, 200), 999

    try:
        gray = cv2.cvtColor(face_crop, cv2.COLOR_BGR2GRAY)
        resized = cv2.resize(gray, (100, 100))
        label, conf = face_recognizer.predict(resized)
        if conf < 120:
            return "Owner", (0, 255, 0), conf
        return "Unknown", (200, 200, 200), conf
    except:
        return "Unknown", (200, 200, 200), 999

def compute_fall_score(shoulder_x, shoulder_y, hip_x, hip_y, ankle_y, width, height, frame_height):
    """
    Compute fall detection score. Returns (score, is_on_floor, debug_text, is_corrupted).
    Score >= 3 AND is_on_floor => FALL DETECTED.
    """
    spine_x = abs(hip_x - shoulder_x)
    spine_y = abs(hip_y - shoulder_y)

    # Skeleton Corruption Check (multi-person overlap)
    if height > (width * 1.5) and spine_y < (height * 0.2):
        return 0, False, "CORRUPTED SKELETON (Overlap)", True

    score = 0

    # Signal 1: Box wider than tall
    if width > (height * 1.2):
        score += 1

    # Signal 2: Spine nearly horizontal
    if spine_x > (spine_y * 1.5):
        score += 1

    # Signal 3: Head dropped to hip level
    if shoulder_y > (hip_y - (height * 0.1)):
        score += 1

    # Signal 4: Legs collapsed
    if ankle_y > 0:
        if abs(ankle_y - hip_y) < (height * 0.5):
            score += 1
    else:
        score += 1  # Ankles hidden = probably collapsed

    # Floor zone check (hips must be in bottom 50% of frame)
    is_on_floor = hip_y > (frame_height * 0.5)

    debug = f"SpineX:{int(spine_x)} | SpineY:{int(spine_y)} | Score:{score}/4 | Floor:{is_on_floor}"
    return score, is_on_floor, debug, False

def send_fall_alert(person_name):
    """Send a JSON alert to the Brain API server with a 15-second cooldown."""
    global last_fall_alert_time
    now = time.time()
    if now - last_fall_alert_time > 15:
        print(f"[*] SENDING ALERT TO BRAIN FOR {person_name}...")
        try:
            requests.post(
                "http://127.0.0.1:5000/event",
                json={"type": "fall_detected", "person": person_name},
                timeout=1
            )
            last_fall_alert_time = now
        except Exception as e:
            print(f"[!] Failed to reach Brain API: {e}")

_frame_save_confirmed = False

def save_frame_for_dashboard(frame):
    """Write the latest annotated frame to disk for the web dashboard."""
    global _frame_save_confirmed
    try:
        cv2.imwrite(FRAME_SAVE_PATH, frame, [cv2.IMWRITE_JPEG_QUALITY, 80])
        if not _frame_save_confirmed:
            print(f"[*] Dashboard frame saved to: {FRAME_SAVE_PATH}")
            _frame_save_confirmed = True
    except Exception as e:
        print(f"[!] Frame save error: {e}")

# ============================================================
# 4. MAIN TRACKING LOOP
# ============================================================
try:
    print("Starting YOLO tracking loop! Press 'q' to quit.")
    while True:
        ret, frame = cap.read()
        if not ret or frame is None:
            continue

        current_time = time.time()
        annotated_frame = frame.copy()

        # --- LIGHTWEIGHT MOTION CHECK (~1% CPU) ---
        small = cv2.resize(frame, (320, 180))
        # Blur heavily to kill camera sensor noise and tiny pixel flicker
        blurred = cv2.GaussianBlur(small, (21, 21), 0)
        fg_mask = motion_detector.apply(blurred)
        # Morphological opening removes tiny noise dots, keeps real movement
        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
        fg_mask = cv2.morphologyEx(fg_mask, cv2.MORPH_OPEN, kernel)
        motion_pixels = cv2.countNonZero(fg_mask)

        # Threshold lowered to 500 to catch subtle movements when far away
        if motion_pixels > 500:
            last_motion_time = current_time

        # --- SLEEP MODE ---
        seconds_idle = current_time - last_motion_time
        if seconds_idle > 10.0:  # Increased sleep timeout to 10 seconds
            cv2.putText(annotated_frame, "SLEEP MODE (0% AI CPU)", (50, 80),
                        cv2.FONT_HERSHEY_SIMPLEX, 1.2, (0, 255, 255), 3)
            cv2.putText(annotated_frame, f"Room empty for {int(seconds_idle)}s...", (50, 130),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.9, (150, 150, 150), 2)
            save_frame_for_dashboard(annotated_frame)
            if not HEADLESS:
                cv2.imshow("YOLOv8 Ambient AI", annotated_frame)
                if cv2.waitKey(1) & 0xFF == ord('q'):
                    break
            else:
                time.sleep(0.1) # Prevent CPU spinning in headless sleep
            continue

        # --- WAKE MODE: Run YOLO ---
        results = model(frame, conf=0.5, verbose=False)
        annotated_frame = results[0].plot()
        fall_detected = False

        if results[0].keypoints is not None and results[0].boxes is not None and len(results[0].boxes) > 0:
            # IMPORTANT: If YOLO sees a human, keep the system awake!
            # This prevents it from sleeping while you are sitting still.
            last_motion_time = current_time
            
            keypoints = results[0].keypoints.xy.cpu().numpy()
            boxes = results[0].boxes.xyxy.cpu().numpy()

            for i in range(len(boxes)):
                x1, y1, x2, y2 = boxes[i]
                w = x2 - x1
                h = y2 - y1
                kpts = keypoints[i]

                sx = get_avg_x(kpts, [5, 6])
                sy = get_avg_y(kpts, [5, 6])
                hx = get_avg_x(kpts, [11, 12])
                hy = get_avg_y(kpts, [11, 12])
                ay = get_avg_y(kpts, [15, 16])

                # --- Gesture Recognition (Customizable) ---
                lsy = kpts[5][1] if len(kpts) > 5 else 0
                rsy = kpts[6][1] if len(kpts) > 6 else 0
                lwy = kpts[9][1] if len(kpts) > 9 else 0
                rwy = kpts[10][1] if len(kpts) > 10 else 0
                lwx = kpts[9][0] if len(kpts) > 9 else 0
                rwx = kpts[10][0] if len(kpts) > 10 else 0
                lsx = kpts[5][0] if len(kpts) > 5 else 0
                rsx = kpts[6][0] if len(kpts) > 6 else 0

                left_up = (lsy > 0 and lwy > 0 and lwy < lsy - 50)
                right_up = (rsy > 0 and rwy > 0 and rwy < rsy - 50)
                
                t_pose = False
                if lwy > 0 and rwy > 0 and abs(lwy - lsy) < 40 and abs(rwy - rsy) < 40:
                    # check if arms are stretched outward
                    if abs(lwx - lsx) > 50 and abs(rwx - rsx) > 50:
                        t_pose = True

                gesture_name = "None"
                if t_pose:
                    gesture_name = "t_pose"
                elif left_up and right_up:
                    gesture_name = "both_arms_up"
                elif left_up:
                    gesture_name = "left_arm_up"
                elif right_up:
                    gesture_name = "right_arm_up"

                if gesture_name != "None":
                    cv2.putText(annotated_frame, f"GESTURE: {gesture_name.upper()}", (int(x1), int(y1) - 60), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (255, 0, 255), 2)
                    if current_time - last_gesture_time > GESTURE_COOLDOWN:
                        print(f"[*] Gesture Detected: {gesture_name}. Sending to Brain API...")
                        try:
                            requests.post("http://127.0.0.1:5000/trigger_gesture", json={"gesture": gesture_name}, timeout=1)
                            last_gesture_time = current_time
                        except Exception as e:
                            print(f"[!] Gesture API Error: {e}")

                # --- Face Recognition ---
                name, color, conf = recognize_face(frame, kpts)
                cv2.rectangle(annotated_frame, (int(x1), int(y1)), (int(x2), int(y2)), color, 2)
                label = f"{name} ({int(conf)})" if conf != 999 else name
                cv2.putText(annotated_frame, label, (int(x1), int(y1) - 35),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.9, color, 2)

                # --- Fall Detection ---
                debug_text = "Tracking..."
                this_person_falling = False
                if sy > 0 and hy > 0:
                    score, on_floor, debug_text, corrupted = compute_fall_score(
                        sx, sy, hx, hy, ay, w, h, frame.shape[0]
                    )

                    if not corrupted and score >= 3 and on_floor:
                        this_person_falling = True
                        # Show warning but don't trigger alert yet
                        cv2.rectangle(annotated_frame, (int(x1), int(y1)), (int(x2), int(y2)), (0, 165, 255), 3)
                        cv2.putText(annotated_frame, f"Verifying fall... ({fall_frame_counter}/{FALL_CONFIRM_FRAMES})",
                                    (int(x1), int(y1) - 65), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 165, 255), 2)

                cv2.putText(annotated_frame, debug_text, (int(x1), int(y1) - 10),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 0), 2)

        # --- TEMPORAL FALL CONFIRMATION ---
        # Only trigger if we see a fall for FALL_CONFIRM_FRAMES consecutive frames
        if this_person_falling:
            fall_frame_counter += 1
        else:
            fall_frame_counter = 0  # Reset if even one frame is normal

        if fall_frame_counter >= FALL_CONFIRM_FRAMES:
            fall_detected = True
            send_fall_alert(name)
            cv2.putText(annotated_frame, "!!! CONFIRMED FALL !!!", (50, 100),
                        cv2.FONT_HERSHEY_SIMPLEX, 2, (0, 0, 255), 5)

        # Save a smaller frame for the dashboard (faster web loading)
        small_frame = cv2.resize(annotated_frame, (640, 360))
        save_frame_for_dashboard(small_frame)
        
        if not HEADLESS:
            cv2.imshow("YOLOv8 Ambient AI", annotated_frame)
            if cv2.waitKey(1) & 0xFF == ord('q'):
                break

finally:
    if cap:
        cap.release()
    if not HEADLESS:
        cv2.destroyAllWindows()
