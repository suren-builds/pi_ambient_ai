"""
tests/test_failure_injection.py
Phase 2 — Failure injection tests:
  - Brain unreachable while Eyes run
  - Ollama unreachable
  - Corrupt face model
  - Oversized payloads
  - Graceful degradation verification
No camera/mic/speaker hardware required.
"""

from __future__ import annotations

import sys
import os
import types
import unittest.mock as mock

import numpy as np
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Stub heavy deps
for mod_name in ["sounddevice", "vosk", "ollama"]:
    sys.modules.setdefault(mod_name, types.ModuleType(mod_name))

import pyttsx3 as _p
if not hasattr(_p, "init"):
    _p.init = lambda: type("E", (), {"setProperty": lambda *a, **k: None,
                                      "getProperty": lambda s, k: [],
                                      "say": lambda *a: None,
                                      "runAndWait": lambda *a: None})()


# ─────────────────────────────────────────────────────────────────────────────
# Eyes → Brain HTTP failures (retry logic)
# ─────────────────────────────────────────────────────────────────────────────
class TestFallAlertRetry:
    def test_retry_on_transient_failure(self):
        """_post_with_retry should succeed after transient connection errors."""
        import yolo_tracker as yt
        import requests as _req

        call_count = [0]

        def _failing_then_ok(url, **kwargs):
            call_count[0] += 1
            if call_count[0] < 3:
                raise _req.ConnectionError("Brain not up yet")
            class _R:
                status_code = 200
            return _R()

        with mock.patch("requests.post", side_effect=_failing_then_ok):
            with mock.patch.dict(yt.CFG, {"http_max_retries": 5, "http_retry_backoff_s": 0.01}):
                success = yt._post_with_retry(f"{yt._BRAIN_API}/event", {"type": "fall_detected"})
        assert success, "Should succeed after retries"
        assert call_count[0] == 3

    def test_all_retries_exhausted_returns_false(self):
        """If all retries fail, _post_with_retry returns False without crashing."""
        import yolo_tracker as yt
        import requests as _req

        def _always_fail(url, **kwargs):
            raise _req.ConnectionError("Brain dead")

        with mock.patch("requests.post", side_effect=_always_fail):
            with mock.patch.dict(yt.CFG, {"http_max_retries": 3, "http_retry_backoff_s": 0.01}):
                result = yt._post_with_retry(f"{yt._BRAIN_API}/event", {"type": "fall_detected"})
        assert result is False

    def test_fall_alert_cooldown_prevents_spam(self):
        """Two consecutive fall alerts within cooldown window — only 1 HTTP call."""
        import yolo_tracker as yt

        post_calls = []

        def _capture(url, **kwargs):
            post_calls.append(url)
            class _R:
                status_code = 200
            return _R()

        with mock.patch("requests.post", side_effect=_capture):
            with mock.patch.dict(yt.CFG, {"fall_alert_cooldown_s": 30, "http_max_retries": 1, "http_retry_backoff_s": 0.01}):
                yt._last_fall_alert_time = 0.0
                yt.send_fall_alert("Owner")
                yt.send_fall_alert("Owner")  # within cooldown → should skip

        assert len(post_calls) == 1, f"Expected 1 fall alert, got {len(post_calls)}"



# ─────────────────────────────────────────────────────────────────────────────
# Corrupt face model
# ─────────────────────────────────────────────────────────────────────────────
class TestCorruptFaceModel:
    def test_missing_model_is_handled(self):
        """If face model is missing, recognize_face should return Unknown, not crash."""
        import yolo_tracker as yt

        # Force model to be flagged as not loaded
        original = yt._face_model_ok
        try:
            yt._face_model_ok = False
            frame = np.zeros((720, 1280, 3), dtype=np.uint8)
            kpts = np.zeros((17, 2), dtype=np.float32)
            kpts[0] = [640, 300]
            kpts[1] = [620, 280]
            kpts[2] = [660, 280]
            kpts[3] = [600, 285]
            kpts[4] = [680, 285]
            name, color, conf = yt.recognize_face(frame, kpts)
            assert name == "Unknown"
            assert conf == 999.0
        finally:
            yt._face_model_ok = original

    def test_no_face_points_returns_unknown(self):
        """Keypoints with no visible face landmarks → Unknown."""
        import yolo_tracker as yt

        frame = np.zeros((720, 1280, 3), dtype=np.uint8)
        kpts = np.zeros((17, 2), dtype=np.float32)  # all zeros = not visible
        name, color, conf = yt.recognize_face(frame, kpts)
        assert name == "Unknown"

    def test_empty_frame_does_not_crash(self):
        """Empty (0-size) frame crop triggers the face_crop.size == 0 guard."""
        import yolo_tracker as yt
        # Use a frame so small that the crop will be empty
        frame = np.zeros((10, 10, 3), dtype=np.uint8)
        kpts = np.zeros((17, 2), dtype=np.float32)
        kpts[0] = [5, 5]
        kpts[1] = [4, 4]
        kpts[2] = [6, 4]
        name, _, _ = yt.recognize_face(frame, kpts)
        assert name == "Unknown"  # should degrade gracefully


# ─────────────────────────────────────────────────────────────────────────────
# Brain API error handling (from Brain side)
# ─────────────────────────────────────────────────────────────────────────────
class TestBrainApiGracefulDegradation:
    def test_ollama_unavailable_returns_friendly_message(self, monkeypatch):
        """If Ollama is down, _call_ollama must return a friendly string, not crash."""
        import voice_assistant as va

        def _fail(model, messages):
            raise ConnectionRefusedError("Ollama not running")

        monkeypatch.setattr(va._ollama_client, "chat", _fail)
        result = va._call_ollama([{"role": "user", "content": "hi"}])
        assert isinstance(result, str)
        assert len(result) > 0
        assert "Error" not in result  # should be user-friendly

    def test_mic_muted_state_consistent_under_concurrent_access(self):
        """Simulate concurrent mic toggle and state read — no race condition."""
        import voice_assistant as va
        import threading

        errors = []
        iterations = 1000

        def _toggle_worker():
            try:
                for _ in range(iterations):
                    with va._state_lock:
                        va.system_state["mic_muted"] = not va.system_state["mic_muted"]
            except Exception as e:
                errors.append(e)

        def _read_worker():
            try:
                for _ in range(iterations):
                    with va._state_lock:
                        _ = va.system_state["mic_muted"]
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=_toggle_worker) for _ in range(4)]
        threads += [threading.Thread(target=_read_worker) for _ in range(4)]
        for t in threads: t.start()
        for t in threads: t.join()

        assert errors == [], f"Race condition errors: {errors}"


# ─────────────────────────────────────────────────────────────────────────────
# Atomic frame save
# ─────────────────────────────────────────────────────────────────────────────
class TestAtomicFrameSave:
    def test_atomic_save_no_partial_file(self, tmp_path):
        """Verify _atomic_save_frame writes .tmp then renames — no torn reads.

        We mock cv2.imwrite to actually write a small text file (so the
        rename path is tested without depending on JPEG codec availability).
        """
        import yolo_tracker as yt

        save_path = str(tmp_path / "test_frame.jpg")
        tmp_path_file = save_path + ".tmp"

        def _fake_imwrite(path, frame, params=None):
            # Write something real so os.replace has a source file
            with open(path, "wb") as f:
                f.write(b"FAKE_JPEG")
            return True

        original_path = yt._FRAME_SAVE_PATH
        try:
            yt._FRAME_SAVE_PATH = save_path
            yt._frame_save_confirmed = False

            frame = np.zeros((360, 640, 3), dtype=np.uint8)
            with mock.patch("cv2.imwrite", side_effect=_fake_imwrite):
                yt._atomic_save_frame(frame)

            # After save: final file must exist, temp must not exist
            assert os.path.exists(save_path), "Final file should exist"
            assert not os.path.exists(tmp_path_file), ".tmp file should be renamed away"
            # Verify it was the fake content (i.e., imwrite was called)
            with open(save_path, "rb") as f:
                assert f.read() == b"FAKE_JPEG"
        finally:
            yt._FRAME_SAVE_PATH = original_path

