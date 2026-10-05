"""
Ambient AI Hub — Owner Face Enrollment (enroll_owner.py)
Captures 50 face samples from the webcam and trains an LBPH model.

Pi-ready fixes:
  - Absolute paths for model files; no CWD fragility.
  - cv2.imshow guarded by DISPLAY env check — safe to run headlessly over SSH.
  - CAP_DSHOW used only on Windows; Linux/Pi uses CAP_ANY.
  - --skip flag: writes a dummy placeholder model so yolo_tracker can start
    without face enrollment (all persons labelled "Person" instead of Owner).
"""

from __future__ import annotations

import argparse
import os
import sys
import time

import cv2
import numpy as np

# Resolve paths relative to this script regardless of CWD
_DIR = os.path.dirname(os.path.abspath(__file__))
_DEFAULT_FACE_MODEL_PATH = os.path.join(_DIR, "owner_face_model.yml")

# Display is available when running locally or via X11 forwarding
_HAS_DISPLAY = bool(os.environ.get("DISPLAY") or os.name == "nt")


def create_dummy_model(model_path: str) -> None:
    """
    Write a minimal LBPH model trained on a single blank image.
    This allows yolo_tracker.py to load a face_model without crashing,
    while gracefully falling back to treating everyone as 'Person'.
    The confidence will always be very high (>> threshold), so nobody
    will be recognised as Owner — which is fine for autonomous demo mode.
    """
    print("=" * 50)
    print("ENROLLMENT SKIPPED — CREATING PLACEHOLDER MODEL")
    print("=" * 50)
    print("The system will run in autonomous 'Person' mode:")
    print("  • Fall detection     ✅ FULLY ACTIVE")
    print("  • Arm-raise gestures ✅ FULLY ACTIVE")
    print("  • Voice assistant    ✅ FULLY ACTIVE")
    print("  • Face recognition   ⚠️  Bypassed (everyone = Person)")
    print()

    # Create a tiny synthetic dataset — 5 blank 100x100 grey images
    dummy_faces = [np.full((100, 100), fill_value=128, dtype=np.uint8) for _ in range(5)]
    dummy_labels = np.array([1] * 5, dtype=np.int32)

    recognizer = cv2.face.LBPHFaceRecognizer_create()
    recognizer.train(dummy_faces, dummy_labels)
    recognizer.save(model_path)
    print(f"Placeholder model saved to '{model_path}'.")
    print("Run enroll_owner.py (without --skip) later to enable real face recognition.\n")


def enroll_owner(captures_needed: int = 50, model_path: str = _DEFAULT_FACE_MODEL_PATH) -> None:
    """Enroll the owner's face and save the LBPH model to *model_path*."""
    # Lazy import — avoids loading YOLO/onnxruntime on the --skip path
    from ultralytics import YOLO  # noqa: PLC0415

    _YOLO_PATH = os.path.join(_DIR, "yolov8n-pose.onnx")
    print(f"Loading YOLOv8-Pose from {_YOLO_PATH}...")
    yolo = YOLO(_YOLO_PATH)

    print("Initialising webcam...")
    backend = cv2.CAP_DSHOW if os.name == "nt" else cv2.CAP_ANY
    cap = cv2.VideoCapture(0, backend)
    if not cap.isOpened():
        print("ERROR: Cannot open camera. Check that it is connected and not in use.")
        sys.exit(1)

    face_crops: list[np.ndarray] = []
    labels: list[int] = []

    print("\n" + "=" * 50)
    print("OWNER FACE ENROLLMENT")
    print("=" * 50)
    print("Please look directly at the camera.")
    print("Move your head slightly (up, down, left, right) for varied angles.")
    if not _HAS_DISPLAY:
        print("NOTE: No display detected — running headlessly. Progress will print to terminal.")
    print("Starting in 3 seconds...\n")
    time.sleep(3)

    while len(face_crops) < captures_needed:
        ret, frame = cap.read()
        if not ret or frame is None:
            continue

        results = yolo(frame, conf=0.5, verbose=False)
        annotated = frame.copy()

        if (
            results[0].keypoints is not None
            and results[0].boxes is not None
            and len(results[0].boxes) > 0
        ):
            keypoints = results[0].keypoints.xy.cpu().numpy()
            # Use the first (largest) detected person
            person_kpts = keypoints[0]

            # Keypoint indices: 0=Nose, 1=L-Eye, 2=R-Eye, 3=L-Ear, 4=R-Ear
            face_xs = [person_kpts[i][0] for i in range(5) if len(person_kpts) > i and person_kpts[i][0] > 0]
            face_ys = [person_kpts[i][1] for i in range(5) if len(person_kpts) > i and person_kpts[i][1] > 0]

            if len(face_xs) >= 3:
                fw = max(face_xs) - min(face_xs)
                fh = max(face_ys) - min(face_ys)
                pad_x     = int(fw * 0.5)
                pad_y_top = int(fh * 0.8)
                pad_y_bot = int(fh * 0.6)

                x1 = max(0, int(min(face_xs) - pad_x))
                y1 = max(0, int(min(face_ys) - pad_y_top))
                x2 = min(frame.shape[1], int(max(face_xs) + pad_x))
                y2 = min(frame.shape[0], int(max(face_ys) + pad_y_bot))

                face_crop = frame[y1:y2, x1:x2]
                if face_crop.size > 0:
                    cv2.rectangle(annotated, (x1, y1), (x2, y2), (0, 255, 0), 2)
                    gray = cv2.cvtColor(face_crop, cv2.COLOR_BGR2GRAY)
                    standard = cv2.resize(gray, (100, 100))
                    face_crops.append(standard)
                    labels.append(1)  # label 1 = Owner
                    print(f"Captured {len(face_crops)} / {captures_needed}", end="\r", flush=True)

        if _HAS_DISPLAY:
            cv2.putText(
                annotated,
                f"Capturing: {len(face_crops)}/{captures_needed}",
                (20, 50),
                cv2.FONT_HERSHEY_SIMPLEX,
                1,
                (0, 255, 0),
                2,
            )
            cv2.imshow("Owner Enrollment", annotated)
            cv2.waitKey(100)  # 10 FPS — ensures varied head angles
        else:
            time.sleep(0.1)  # headless Pi — throttle capture rate

    cap.release()
    if _HAS_DISPLAY:
        cv2.destroyAllWindows()

    print(f"\n\nTraining LBPH face model with {captures_needed} samples...")
    recognizer = cv2.face.LBPHFaceRecognizer_create()
    recognizer.train(face_crops, np.array(labels))
    recognizer.save(model_path)
    print(f"Model saved to '{model_path}'. Enrollment complete!")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Ambient AI — Owner Face Enrollment")
    parser.add_argument(
        "--skip",
        action="store_true",
        help=(
            "Skip webcam enrollment and write a placeholder model instead. "
            "Fall detection and gesture control remain fully active."
        ),
    )
    parser.add_argument("--captures", type=int, default=50,
                        help="Number of face captures to collect (default: 50)")
    parser.add_argument("--model", type=str, default=_DEFAULT_FACE_MODEL_PATH,
                        help=f"Output path for the LBPH model (default: {_DEFAULT_FACE_MODEL_PATH})")
    args = parser.parse_args()

    if args.skip:
        create_dummy_model(args.model)
    else:
        enroll_owner(captures_needed=args.captures, model_path=args.model)
