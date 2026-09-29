import cv2
import numpy as np
import time
from ultralytics import YOLO

def enroll_owner():
    print("Loading YOLOv8...")
    model = YOLO('yolov8n-pose.pt')
    
    print("Initializing Webcam...")
    cap = cv2.VideoCapture(0, cv2.CAP_DSHOW)
    
    face_crops = []
    labels = []
    
    print("\n" + "="*50)
    print("OWNER FACE ENROLLMENT")
    print("="*50)
    print("Please look directly at the camera.")
    print("Move your head slightly (up, down, left, right) to capture different angles.")
    print("Starting in 3 seconds...\n")
    
    time.sleep(3)
    
    captures_needed = 50
    
    while len(face_crops) < captures_needed:
        ret, frame = cap.read()
        if not ret: continue
        
        # Run YOLO to find the face
        results = model(frame, conf=0.5, verbose=False)
        annotated_frame = frame.copy()
        
        if results[0].keypoints is not None and results[0].boxes is not None:
            keypoints = results[0].keypoints.xy.cpu().numpy()
            
            # Assume the closest/largest person is the owner
            person_kpts = keypoints[0] 
            
            # Indices: 0(Nose), 1(L-Eye), 2(R-Eye), 3(L-Ear), 4(R-Ear)
            face_pts_x = [person_kpts[i][0] for i in range(5) if len(person_kpts) > i and person_kpts[i][0] > 0]
            face_pts_y = [person_kpts[i][1] for i in range(5) if len(person_kpts) > i and person_kpts[i][1] > 0]
            
            if len(face_pts_x) >= 3: # Need at least 3 points to define a face box
                min_x, max_x = min(face_pts_x), max(face_pts_x)
                min_y, max_y = min(face_pts_y), max(face_pts_y)
                
                # Add padding to capture forehead and chin
                width = max_x - min_x
                height = max_y - min_y
                pad_x = int(width * 0.5)
                pad_y_top = int(height * 0.8) # Forehead
                pad_y_bot = int(height * 0.6) # Chin
                
                x1 = max(0, int(min_x - pad_x))
                y1 = max(0, int(min_y - pad_y_top))
                x2 = min(frame.shape[1], int(max_x + pad_x))
                y2 = min(frame.shape[0], int(max_y + pad_y_bot))
                
                face_crop = frame[y1:y2, x1:x2]
                
                if face_crop.size > 0:
                    # Draw a green box around the face being captured
                    cv2.rectangle(annotated_frame, (x1, y1), (x2, y2), (0, 255, 0), 2)
                    
                    # Convert to grayscale and resize to standard 100x100 for LBPH
                    gray_face = cv2.cvtColor(face_crop, cv2.COLOR_BGR2GRAY)
                    standard_face = cv2.resize(gray_face, (100, 100))
                    
                    face_crops.append(standard_face)
                    labels.append(1) # Label 1 = Owner
                    
                    print(f"Captured {len(face_crops)} / {captures_needed}")
                    
        
        cv2.putText(annotated_frame, f"Capturing: {len(face_crops)}/{captures_needed}", (20, 50), 
                    cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 255, 0), 2)
        cv2.imshow("Owner Enrollment", annotated_frame)
        cv2.waitKey(100) # Small delay to ensure varied angles
        
    cap.release()
    cv2.destroyAllWindows()
    
    print("\nTraining local face model...")
    # LBPH (Local Binary Patterns Histograms) is lightweight and runs perfectly on Raspberry Pi
    recognizer = cv2.face.LBPHFaceRecognizer_create()
    recognizer.train(face_crops, np.array(labels))
    
    recognizer.save('owner_face_model.yml')
    print("Training complete! Model saved to 'owner_face_model.yml'.")

if __name__ == "__main__":
    enroll_owner()
