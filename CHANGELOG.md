# CHANGELOG.md — Ambient AI Hub

## [hardening] — 2026-09-29

### CRITICAL Bug Fixes
- **C-1 FIXED** (`yolo_tracker.py`): `this_person_falling` variable was used outside its `if len(boxes) > 0` block causing `NameError` crash on every frame with no persons. Now initialised to `False` before the boxes loop.
- **C-2 FIXED** (`voice_assistant.py`): Flask API was bound to `0.0.0.0` exposing all control endpoints (mic toggle, emergency trigger) to the entire LAN with no authentication. Changed to `127.0.0.1` (loopback only). Added `X-Secret-Token` header validation for sensitive endpoints.
- **C-3 FIXED** (`voice_assistant.py`): `system_state` dict was mutated from two threads (Flask thread + STT main loop) without any synchronization. Added `threading.Lock()` (`_state_lock`) that wraps all reads and writes.
- **C-4 FIXED** (`yolo_tracker.py`): `cv2.imwrite()` writes non-atomically; Dashboard could read a partial/corrupt JPEG mid-write. Changed to write-to-`.tmp`-then-`os.replace()` pattern (atomic on POSIX, best-effort on Windows).
- **C-5 FIXED** (`voice_assistant.py`): TTS output was being picked up by the microphone and fed back into the STT recognizer (echo loop). Fixed by flushing the audio queue whenever `_is_speaking` event is set, preventing the assistant from "hearing itself."

### HIGH Bug Fixes
- **H-1 FIXED** (`voice_assistant.py`): `speak()` called `engine.runAndWait()` directly in the main loop, blocking the STT loop and event queue. TTS now runs in a dedicated daemon thread (`_tts_worker`); `speak()` is now fully non-blocking.
- **H-2 FIXED** (`yolo_tracker.py`): HTTP POST from Eyes to Brain had no retry logic — any transient Brain restart silently dropped the fall alert. Added `_post_with_retry()` with configurable max retries and exponential backoff.
- **H-3 FIXED** (`setup_pi.sh`): Added `set -euo pipefail`; added prerequisite checks for `python3` and version >= 3.9; added virtual environment creation; made all steps idempotent.
- **H-4 FIXED** (`install_services.sh`): Added `set -euo pipefail`; added `--uninstall` mode; added `StartLimitIntervalSec/Burst`; changed `Wants=` to `Requires=` for Ollama; added resource limits (`MemoryMax`, `CPUQuota`).
- **H-5 FIXED** (`requirements.txt`): All packages now have version bounds (`>=min,<max`). Switched `opencv-python` to `opencv-python-headless` (correct for Pi). Added missing `PyYAML` and `pytest/pytest-cov` entries.
- **H-6 FIXED** (`voice_assistant.py`): `/event` endpoint now validates `Content-Length` against `max_payload_bytes` (4096). Returns 413 for oversized requests.
- **H-7 FIXED** (`voice_assistant.py`): `/update_config` previously called `dict.update()` with raw client JSON — arbitrary key injection possible. Now whitelist-validates both keys (against `_ALLOWED_GESTURE_KEYS`) and values (against `_ALLOWED_GESTURE_VALUES`).
- **H-8 FIXED** (`yolo_tracker.py`): If `owner_face_model.yml` is missing/corrupt, `face_recognizer` is in undefined state. Added `_face_model_ok` boolean flag; `recognize_face()` checks this before calling `.predict()`.
- **H-9 FIXED** (`voice_assistant.py`): `ollama` SDK v0.2+ returns a `Message` object, not a `dict`. `_call_ollama()` now handles both patterns via duck typing (`isinstance` check + fallback).
- **H-10 FIXED** (`dashboard.py`): Replaced all bare `except:` clauses with `except Exception:` (preserves KeyboardInterrupt handling).
- **H-11 ADDED** (`voice_assistant.py`): Added `GET /health` endpoint returning `{"status":"ok","service":"brain"}`.

### Medium Bug Fixes
- **M-1 FIXED**: Replaced all `print()` calls with Python `logging` (structured, rotating `RotatingFileHandler`, configurable level).
- **M-2 FIXED** (`voice_assistant.py`): Ollama inference now runs in a thread with a `join(timeout=CFG["ollama_timeout_s"])` hard deadline (default 15s). Returns friendly fallback on timeout.
- **M-3 FIXED** (`yolo_tracker.py`): Model path resolved to absolute at startup using `os.path.join(_DIR, CFG["yolo_model"])`.
- **M-4 FIXED** (`enroll_owner.py`): Replaced hardcoded `cv2.CAP_DSHOW` with platform check (`os.name == "nt"`).
- **M-5 FIXED** (`voice_assistant.py`): HEADLESS env var check lowercased for robustness (`"false".lower() == "true"`).
- **M-6 FIXED** (`yolo_tracker.py`): MOG2 history raised from 100 to 500 (from config) to reduce false wakeups.
- **M-7 FIXED**: Added `signal.signal(SIGTERM/SIGINT, handler)` to both `voice_assistant.py` and `yolo_tracker.py`; camera `cap.release()` is guaranteed in `finally` block.
- **M-8 FIXED** (`dashboard.py`): Auto-refresh interval now driven by `dashboard_refresh_interval_s` config (default 1.5s); was a tight 0.05s loop.
- **M-9 FIXED** (`yolo_tracker.py`): LBPH threshold tightened from 120 → 80 (configurable). Lower = harder to spoof with a photo.
- **M-11 FIXED** (`install_services.sh`): Brain unit now uses `Requires=ollama.service` with correct `After=` ordering.

### New Files Created
- `config.yaml` — central config; all magic numbers extracted from source
- `AUDIT.md` — full defect catalogue (33 items across 4 severity levels)
- `CHANGELOG.md` — this file
- `tests/__init__.py`
- `tests/test_flask_api.py` — 28 API tests
- `tests/test_fall_detection.py` — 11 fall detection tests
- `tests/test_intent_and_utils.py` — 14 intent/utility tests
- `tests/test_gesture_logic.py` — 9 gesture tests
- `tests/test_failure_injection.py` — 8 failure injection tests
- `tests/soak_test.py` — configurable stress test

### Low Priority Improvements
- **L-2**: TTS voice selection now falls back gracefully on Linux/Pi espeak (no crash if "Zira" not found)
- **L-4**: `requirements.txt` switched to `opencv-python-headless`
- **L-5**: Docstrings and type hints added to all new/modified functions
