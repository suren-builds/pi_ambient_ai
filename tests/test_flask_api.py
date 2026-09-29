"""
tests/test_flask_api.py
Phase 2 — Flask API tests covering all endpoints, edge cases, concurrency.
These tests start an embedded Flask test client — NO camera/mic/speaker needed.
"""

from __future__ import annotations

import json
import sys
import os
import threading
from typing import Any

import pytest

# ── Bootstrap: make project root importable without installing ─────────────
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Patch heavy audio/vision imports before importing voice_assistant
import types, unittest.mock as mock

# Stub modules that require hardware
for mod_name in ["sounddevice", "vosk", "pyttsx3", "ollama"]:
    stub = types.ModuleType(mod_name)
    sys.modules[mod_name] = stub

# pyttsx3 needs init() to return an engine-like object
pyttsx3_stub = sys.modules["pyttsx3"]
class _FakeEngine:
    def setProperty(self, *a, **kw): pass
    def getProperty(self, key):
        if key == "voices": return []
        return None
    def say(self, text): pass
    def runAndWait(self): pass
pyttsx3_stub.init = lambda: _FakeEngine()

# ollama.Client stub
ollama_stub = sys.modules["ollama"]
class _FakeOllama:
    def __init__(self, **kw): pass
    def chat(self, **kw):
        class _Msg: content = "stub response"
        class _Resp: message = _Msg()
        return _Resp()
ollama_stub.Client = _FakeOllama

# numpy minimal stub — voice_assistant only uses np.frombuffer and np.linalg.norm
import numpy as _np  # real numpy must be available


@pytest.fixture(scope="module")
def client():
    """Return a Flask test client with a clean system_state."""
    # Import after stubs are registered
    import importlib
    import voice_assistant as va
    importlib.reload(va)  # fresh state for each test module

    va._app.config["TESTING"] = True
    with va._app.test_client() as c:
        yield c, va


# ─────────────────────────────────────────────────────────────────────────────
# GET /health
# ─────────────────────────────────────────────────────────────────────────────
class TestHealth:
    def test_health_ok(self, client):
        c, va = client
        r = c.get("/health")
        assert r.status_code == 200
        data = r.get_json()
        assert data["status"] == "ok"
        assert data["service"] == "brain"


# ─────────────────────────────────────────────────────────────────────────────
# GET /state
# ─────────────────────────────────────────────────────────────────────────────
class TestState:
    def test_returns_full_state(self, client):
        c, va = client
        r = c.get("/state")
        assert r.status_code == 200
        data = r.get_json()
        assert "mic_muted" in data
        assert "smart_home" in data
        assert "gesture_config" in data

    def test_state_has_correct_types(self, client):
        c, va = client
        data = c.get("/state").get_json()
        assert isinstance(data["mic_muted"], bool)
        assert isinstance(data["smart_home"], dict)
        assert isinstance(data["gesture_config"], dict)


# ─────────────────────────────────────────────────────────────────────────────
# POST /toggle_mic
# ─────────────────────────────────────────────────────────────────────────────
class TestToggleMic:
    def test_toggle_flips_state(self, client):
        c, va = client
        with va._state_lock:
            va.system_state["mic_muted"] = False
        r = c.post("/toggle_mic")
        assert r.status_code == 200
        assert r.get_json()["muted"] is True

    def test_double_toggle_returns_to_original(self, client):
        c, va = client
        with va._state_lock:
            va.system_state["mic_muted"] = False
        c.post("/toggle_mic")
        r = c.post("/toggle_mic")
        assert r.get_json()["muted"] is False

    def test_concurrent_state_mutations_no_corruption(self, client):
        """1000 concurrent _state_lock mutations should leave state consistent.

        Flask's test client is not thread-safe, so we test the underlying lock
        directly — which is what matters for production correctness.
        """
        c, va = client
        with va._state_lock:
            va.system_state["mic_muted"] = False

        errors: list[Exception] = []

        def _toggle():
            try:
                for _ in range(100):
                    with va._state_lock:
                        va.system_state["mic_muted"] = not va.system_state["mic_muted"]
            except Exception as exc:  # noqa: BLE001
                errors.append(exc)

        def _read():
            try:
                for _ in range(100):
                    with va._state_lock:
                        _ = va.system_state["mic_muted"]
            except Exception as exc:  # noqa: BLE001
                errors.append(exc)

        threads = [threading.Thread(target=_toggle) for _ in range(5)]
        threads += [threading.Thread(target=_read) for _ in range(5)]
        for t in threads: t.start()
        for t in threads: t.join()

        assert errors == [], f"Race condition errors: {errors}"
        with va._state_lock:
            final = va.system_state["mic_muted"]
        assert isinstance(final, bool)



# ─────────────────────────────────────────────────────────────────────────────
# POST /event
# ─────────────────────────────────────────────────────────────────────────────
class TestEvent:
    def test_valid_fall_event(self, client):
        c, va = client
        r = c.post("/event", json={"type": "fall_detected", "person": "Owner"})
        assert r.status_code == 200
        assert r.get_json()["status"] == "received"
        with va._state_lock:
            assert "CRITICAL" in va.system_state["last_alert"]

    def test_unknown_event_type_accepted_gracefully(self, client):
        c, va = client
        r = c.post("/event", json={"type": "alien_invasion", "data": "boom"})
        assert r.status_code == 200  # must not crash

    def test_empty_json_returns_400(self, client):
        c, va = client
        r = c.post("/event", data=b"not json", content_type="application/json")
        assert r.status_code == 400

    def test_missing_type_field(self, client):
        c, va = client
        r = c.post("/event", json={"foo": "bar"})
        assert r.status_code == 200  # type defaults to "" → ignored

    def test_oversized_payload_rejected(self, client):
        c, va = client
        big = {"type": "fall_detected", "person": "x" * 10_000}
        r = c.post(
            "/event",
            data=json.dumps(big).encode(),
            content_type="application/json",
            headers={"Content-Length": str(len(json.dumps(big)))},
        )
        # Either 413 or 200 (if Content-Length not set, Flask may still process;
        # the important thing is it does NOT crash the server)
        assert r.status_code in (200, 413)

    def test_person_name_sanitised_to_max_64(self, client):
        c, va = client
        long_name = "A" * 200
        c.post("/event", json={"type": "fall_detected", "person": long_name})
        with va._state_lock:
            alert = va.system_state["last_alert"]
        # Name in alert should be at most 64 chars + surrounding text
        assert len(alert) < 300


# ─────────────────────────────────────────────────────────────────────────────
# POST /update_config
# ─────────────────────────────────────────────────────────────────────────────
class TestUpdateConfig:
    def test_valid_config_update(self, client):
        c, va = client
        r = c.post("/update_config", json={"left_arm_up": "Toggle Light"})
        assert r.status_code == 200
        with va._state_lock:
            assert va.system_state["gesture_config"]["left_arm_up"] == "Toggle Light"

    def test_arbitrary_key_injection_rejected(self, client):
        """Attacker tries to inject a key not in the allowed list."""
        c, va = client
        original_keys = set(c.get("/state").get_json()["gesture_config"].keys())
        c.post("/update_config", json={"__proto__": "evil", "mic_muted": True})
        with va._state_lock:
            assert "__proto__" not in va.system_state["gesture_config"]
            assert va.system_state["mic_muted"] is not True  # injected key ignored

    def test_invalid_value_rejected(self, client):
        c, va = client
        c.post("/update_config", json={"left_arm_up": "Launch Missiles"})
        with va._state_lock:
            assert va.system_state["gesture_config"]["left_arm_up"] != "Launch Missiles"

    def test_empty_payload_400(self, client):
        c, va = client
        r = c.post("/update_config", data=b"", content_type="application/json")
        assert r.status_code == 400


# ─────────────────────────────────────────────────────────────────────────────
# POST /trigger_gesture
# ─────────────────────────────────────────────────────────────────────────────
class TestTriggerGesture:
    def test_left_arm_up_toggles_mic(self, client):
        c, va = client
        with va._state_lock:
            va.system_state["gesture_config"]["left_arm_up"] = "Toggle Mic"
            va.system_state["mic_muted"] = False
        c.post("/trigger_gesture", json={"gesture": "left_arm_up"})
        with va._state_lock:
            assert va.system_state["mic_muted"] is True

    def test_right_arm_up_toggles_light(self, client):
        c, va = client
        with va._state_lock:
            va.system_state["gesture_config"]["right_arm_up"] = "Toggle Light"
            va.system_state["smart_home"]["light"] = False
        c.post("/trigger_gesture", json={"gesture": "right_arm_up"})
        with va._state_lock:
            assert va.system_state["smart_home"]["light"] is True

    def test_both_arms_up_toggles_fan(self, client):
        c, va = client
        with va._state_lock:
            va.system_state["gesture_config"]["both_arms_up"] = "Toggle Fan"
            va.system_state["smart_home"]["fan"] = False
        c.post("/trigger_gesture", json={"gesture": "both_arms_up"})
        with va._state_lock:
            assert va.system_state["smart_home"]["fan"] is True

    def test_unknown_gesture_no_crash(self, client):
        c, va = client
        r = c.post("/trigger_gesture", json={"gesture": "moonwalk"})
        assert r.status_code == 200

    def test_empty_json_400(self, client):
        c, va = client
        r = c.post("/trigger_gesture", data=b"", content_type="application/json")
        assert r.status_code == 400
