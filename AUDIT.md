# AUDIT.md — Ambient AI Hub
*Auditor: Senior Embedded/AI Systems Engineer and QA Lead*
*Date: 2026-09-29*

---

## 1. File Inventory

| File | Lines | Purpose | Status |
|------|-------|---------|--------|
| `voice_assistant.py` | 362 | Brain: STT->LLM->TTS + Flask API (port 5000) | Present |
| `yolo_tracker.py` | 341 | Eyes: YOLOv8-pose, LBPH, fall + gesture | Present |
| `dashboard.py` | 578 | Streamlit UI (port 8501) | Present |
| `enroll_owner.py` | 95 | One-shot owner face enrollment | Present |
| `setup_pi.sh` | 35 | OS + Python dependency installer | Present |
| `install_services.sh` | 95 | systemd unit writer + enabler | Present |
| `requirements.txt` | 10 | Python package list (UNPINNED) | Present |
| `hand_tracker.py` | 79 | Experimental MediaPipe Pi tracker | Dead code |
| `hand_tracker_windows.py` | 76 | Experimental MediaPipe Windows tracker | Dead code |
| `hand_landmarker.task` | — | MediaPipe model blob | Orphaned |
| `yolov8n-pose.pt` | — | YOLOv8n-pose model weights | Present |
| `latest_frame.jpg` | — | Shared IPC frame | Present |
| `owner_face_model.yml` | — | LBPH trained model | MISSING |
| `config.yaml` | — | Central configuration | MISSING |
| `tests/` | — | Test suite | MISSING |

---

## 2. Ports and Endpoints

| Service | Port | Bind | Auth |
|---------|------|------|------|
| Brain Flask API | 5000 | 0.0.0.0 (CRITICAL) | NONE |
| Dashboard Streamlit | 8501 | 0.0.0.0 | NONE |

### Flask Endpoints
| Endpoint | Method | Validation | Problem |
|----------|--------|-----------|---------|
| GET /state | GET | None | Leaks full state |
| POST /toggle_mic | POST | None | No auth |
| POST /event | POST | Partial | No size limit, no auth |
| POST /update_config | POST | None | Arbitrary key injection |
| POST /trigger_gesture | POST | None | No auth |
| GET /health | — | — | MISSING |

---

## 3. Critical and High Bugs Found

### CRITICAL (5)
- C-1: yolo_tracker.py:316 — this_person_falling NameError crash when no persons detected
- C-2: voice_assistant.py:84 — Flask bound to 0.0.0.0 exposes unauthed API to LAN
- C-3: voice_assistant.py:59-73 — system_state mutated from two threads without lock (race condition)
- C-4: yolo_tracker.py:175 — cv2.imwrite non-atomic, Dashboard reads partial/corrupt JPEG
- C-5: voice_assistant.py:292-295 — TTS output echoes back into STT (assistant hears itself)

### HIGH (11)
- H-1: speak() blocks main loop — fall alerts missed while TTS runs
- H-2: HTTP POST to Brain has no retry logic — transient restart drops fall alert
- H-3: setup_pi.sh missing set -euo pipefail — failed pip install silently swallowed
- H-4: install_services.sh missing set -euo pipefail, no uninstall, no verify
- H-5: requirements.txt has no version pins — breaking update silently breaks system
- H-6: /event endpoint accepts arbitrary JSON with no size limit (DoS)
- H-7: /update_config calls dict.update() with raw client JSON (key injection)
- H-8: Missing owner_face_model.yml exception caught and ignored — later crash at predict()
- H-9: ollama client returns Message object not dict in newer SDK — AttributeError
- H-10: dashboard.py bare except: swallows KeyboardInterrupt
- H-11: No /health endpoint on either service

### MEDIUM (11)
- M-1: No structured logging, print() everywhere — fills SD card
- M-2: Ollama client has no timeout — hung inference blocks forever
- M-3: yolov8n-pose.pt relative path — fragile if CWD wrong
- M-4: enroll_owner.py hardcodes cv2.CAP_DSHOW (Windows-only)
- M-5: HEADLESS env var inconsistently applied
- M-6: MOG2 history=100 too short — false wakeups
- M-7: No graceful SIGTERM shutdown — camera/mic handles not released
- M-8: dashboard.py 0.05s rerun sleep — aggressive CPU burn on Pi
- M-9: LBPH confidence threshold < 120 too permissive — photo spoof possible
- M-10: Keyword intent detection — fragile
- M-11: Wants=ollama.service should be Requires= with ordering

### LOW (6)
- L-1: hand_tracker*.py dead code not referenced
- L-2: Voice selection uses Windows-only Zira name
- L-3: cv2.putText in sleep mode — waste on headless Pi
- L-4: opencv-python should be opencv-python-headless on Pi
- L-5: No type hints or docstrings
- L-6: Google Fonts CDN import — fails offline

---

## 4. Summary

| Severity | Count |
|---------|-------|
| CRITICAL | 5 |
| HIGH | 11 |
| MEDIUM | 11 |
| LOW | 6 |
| TOTAL | 33 |
