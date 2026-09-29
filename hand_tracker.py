import cv2
import numpy as np
import mediapipe as mp
import time

# --- 1. NATIVE INGESTION ---
# If using a Pi Camera Module (CSI), uncomment the Picamera2 lines.
# from picamera2 import Picamera2
# picam2 = Picamera2()
# config = picam2.create_video_configuration({"main": {"format": "RGB888", "size": (640, 480)}})
# picam2.configure(config)
# picam2.start()

# If using a USB Webcam, use explicit V4L2 backend without libcamerify.
cap = cv2.VideoCapture(0, cv2.CAP_V4L2)
cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)

# --- 2. PIPELINE SETUP ---
mp_hands = mp.solutions.hands
hands = mp_hands.Hands(
    static_image_mode=False,
    max_num_hands=2,
    min_detection_confidence=0.6,
    min_tracking_confidence=0.5,
    model_complexity=0 # Essential for Pi 4 thermals
)

try:
    while True:
        # INGEST: Pi Camera Method
        # frame_rgb = picam2.capture_array("main")
        
        # INGEST: USB Camera Method
        ret, frame_bgr = cap.read()
        if not ret or frame_bgr is None:
            time.sleep(0.1) # Prevent CPU spinning on dropped frames
            continue
            
        # --- 3. THE MEMORY SAFETY LAYER ---
        # Convert BGR to RGB
        frame_rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
        
        # Guard 1: Ensure strict memory contiguity before hitting pybind11 (C++)
        if not frame_rgb.flags['C_CONTIGUOUS']:
            frame_rgb = np.ascontiguousarray(frame_rgb)
            
        # Guard 2: Reject corrupted dimensions which trigger cv::remap crashes
        if frame_rgb.shape != (480, 640, 3):
            continue

        # --- 4. INFERENCE ---
        # If a crash happens, it is isolated and won't kill the Python runtime
        try:
            results = hands.process(frame_rgb)
        except Exception as e:
            print(f"MediaPipe C++ Exception Caught (Ignored): {e}")
            continue

        # --- 5. SAFE RENDERING (No mp.drawing_utils) ---
        if results.multi_hand_landmarks:
            for hand_landmarks in results.multi_hand_landmarks:
                for landmark in hand_landmarks.landmark:
                    # Guard 3: Prevent out-of-bounds drawing coords
                    x = max(0, min(639, int(landmark.x * 640)))
                    y = max(0, min(479, int(landmark.y * 480)))
                    
                    cv2.circle(frame_bgr, (x, y), 3, (0, 255, 0), -1)

        cv2.imshow("Ambient AI Tracker", frame_bgr)
        
        if cv2.waitKey(1) & 0xFF == ord('q'):
            break

finally:
    # picam2.stop()
    cap.release()
    cv2.destroyAllWindows()
