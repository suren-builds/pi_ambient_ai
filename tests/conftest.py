"""
tests/conftest.py
Global pytest fixtures and module-level stubs.
All heavy hardware/ML imports are mocked here BEFORE any test module loads.
"""

from __future__ import annotations

import sys
import types
import unittest.mock as mock
import os

# ── Stub ultralytics (YOLOv8) ─────────────────────────────────────────────────
_ultralytics_stub = types.ModuleType("ultralytics")

class _FakeYOLO:
    def __init__(self, path=None): pass
    def __call__(self, *a, **kw):
        class _Res:
            keypoints = None
            boxes = None
            def plot(self): 
                import numpy as np
                return np.zeros((720,1280,3), dtype="uint8")
        class _Results:
            def __getitem__(self, i): return _Res()
        return _Results()

_ultralytics_stub.YOLO = _FakeYOLO
sys.modules["ultralytics"] = _ultralytics_stub

# ── Stub pyttsx3 ─────────────────────────────────────────────────────────────
_pyttsx3_stub = types.ModuleType("pyttsx3")
class _FakeEngine:
    def setProperty(self, *a, **kw): pass
    def getProperty(self, key):
        if key == "voices": return []
        return None
    def say(self, text): pass
    def runAndWait(self): pass
_pyttsx3_stub.init = lambda: _FakeEngine()
sys.modules["pyttsx3"] = _pyttsx3_stub

# ── Stub sounddevice ─────────────────────────────────────────────────────────
_sd_stub = types.ModuleType("sounddevice")
_sd_stub.query_devices = lambda *a, **kw: {"name": "Fake Mic", "max_input_channels": 1}
class _FakeRawInputStream:
    def __enter__(self): return self
    def __exit__(self, *a): pass
_sd_stub.RawInputStream = _FakeRawInputStream
_sd_stub.CallbackFlags = type("CallbackFlags", (), {})
sys.modules["sounddevice"] = _sd_stub

# ── Stub vosk ────────────────────────────────────────────────────────────────
_vosk_stub = types.ModuleType("vosk")
class _FakeVoskModel:
    def __init__(self, model_name=None): pass
class _FakeRecognizer:
    def AcceptWaveform(self, data): return False
    def Result(self): return '{"text": ""}'
_vosk_stub.Model = _FakeVoskModel
_vosk_stub.KaldiRecognizer = lambda model, rate: _FakeRecognizer()
sys.modules["vosk"] = _vosk_stub

# ── Stub ollama ───────────────────────────────────────────────────────────────
_ollama_stub = types.ModuleType("ollama")
class _FakeOllamaClient:
    def __init__(self, host=None): pass
    def chat(self, model=None, messages=None):
        class _Msg: content = "stub response"
        class _Resp: message = _Msg()
        return _Resp()
_ollama_stub.Client = _FakeOllamaClient
sys.modules["ollama"] = _ollama_stub

# ── Stub cv2.VideoCapture for yolo_tracker import ────────────────────────────
# We can't stub all of cv2, but we can pre-set the stub for VideoCapture
# so that yolo_tracker.py doesn't try to open a real camera at import time.
import cv2  # real cv2 must be installed

_original_video_capture = cv2.VideoCapture

class _FakeCapture:
    def __init__(self, *a, **kw): pass
    def isOpened(self): return True
    def set(self, *a): pass
    def read(self):
        import numpy as np
        return True, np.zeros((720, 1280, 3), dtype="uint8")
    def release(self): pass

# Patch VideoCapture globally for the test session
cv2.VideoCapture = _FakeCapture  # type: ignore[attr-defined]
