import cv2
import numpy as np
import mediapipe as mp
from mediapipe.tasks import python
from mediapipe.tasks.python import vision
import time
import sys

print("1. Initializing Laptop Webcam...")
sys.stdout.flush()
cap = cv2.VideoCapture(0)
cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)

import os
current_dir = os.path.dirname(os.path.abspath(__file__))
model_path = os.path.join(current_dir, 'hand_landmarker.task')

print("2. Loading Modern MediaPipe...")
sys.stdout.flush()
base_options = python.BaseOptions(model_asset_path=model_path)
options = vision.HandLandmarkerOptions(
    base_options=base_options,
    num_hands=2,
    min_hand_detection_confidence=0.6,
    min_hand_presence_confidence=0.5,
    min_tracking_confidence=0.5
)
detector = vision.HandLandmarker.create_from_options(options)

print("3. Starting tracking loop!")
sys.stdout.flush()

try:
    while True:
        print("4. Reading frame...", end='\r')
        sys.stdout.flush()
        ret, frame = cap.read()
        
        if not ret or frame is None:
            time.sleep(0.1)
            continue
            
        print("5. Processing frame...", end='\r')
        sys.stdout.flush()
        
        # Convert BGR (OpenCV) to RGB (MediaPipe)
        frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        
        # Convert to MediaPipe Image object
        mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=frame_rgb)

        # Process the frame
        detection_result = detector.detect(mp_image)

        # Draw landmarks if a hand is detected
        if detection_result.hand_landmarks:
            for hand_landmarks in detection_result.hand_landmarks:
                for landmark in hand_landmarks:
                    # Get pixel coordinates
                    x = max(0, min(639, int(landmark.x * 640)))
                    y = max(0, min(479, int(landmark.y * 480)))
                    
                    # Draw a green dot
                    cv2.circle(frame, (x, y), 4, (0, 255, 0), -1)

        print("6. Showing frame...   ", end='\r')
        sys.stdout.flush()
        cv2.imshow("Laptop AI Tracker", frame)
        
        if cv2.waitKey(1) & 0xFF == ord('q'):
            break
finally:
    if cap: cap.release()
    cv2.destroyAllWindows()
