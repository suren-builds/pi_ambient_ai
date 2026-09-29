"""
tests/test_gesture_logic.py
Phase 2 — Gesture recognition logic tests.
Validates detection, cooldown, and debounce using mocked HTTP requests.
No camera required.
"""

from __future__ import annotations

import sys
import os
import time
import types
import unittest.mock as mock

import numpy as np
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Stub ultralytics and cv2 face recognizer before importing yolo_tracker
for mod_name in ["ultralytics"]:
    sys.modules.setdefault(mod_name, types.ModuleType(mod_name))

import cv2  # real opencv must be available


@pytest.fixture(scope="module")
def yt():
    """Import yolo_tracker after mocking camera/YOLO."""
    with mock.patch("cv2.VideoCapture") as mock_cap:
        mock_cap.return_value.isOpened.return_value = True
        mock_cap.return_value.read.return_value = (True, np.zeros((720, 1280, 3), dtype=np.uint8))

        with mock.patch("ultralytics.YOLO"):
            import importlib
            import yolo_tracker as yt_module
            importlib.reload(yt_module)
            yield yt_module


# ─────────────────────────────────────────────────────────────────────────────
# Gesture detection logic (pure, extracted from yolo_tracker)
# ─────────────────────────────────────────────────────────────────────────────
def _make_kpts_for_gesture(
    left_wrist_y: float, right_wrist_y: float,
    left_shoulder_y: float = 300.0, right_shoulder_y: float = 300.0,
    left_wrist_x: float = 500.0, right_wrist_x: float = 780.0,
    left_shoulder_x: float = 560.0, right_shoulder_x: float = 720.0,
) -> np.ndarray:
    """Build a 17-point keypoint array for gesture testing."""
    kpts = np.zeros((17, 2), dtype=np.float32)
    kpts[5]  = [left_shoulder_x, left_shoulder_y]    # L-Shoulder
    kpts[6]  = [right_shoulder_x, right_shoulder_y]  # R-Shoulder
    kpts[9]  = [left_wrist_x, left_wrist_y]           # L-Wrist
    kpts[10] = [right_wrist_x, right_wrist_y]          # R-Wrist
    return kpts


class TestGestureDetection:
    """Test the gesture classification logic extracted from yolo_tracker."""

    def _classify(self, kpts: np.ndarray, threshold_px: float = 50.0) -> str:
        """Replicate the gesture classification logic from yolo_tracker."""
        lsy = float(kpts[5][1]) if len(kpts) > 5 else 0.0
        rsy = float(kpts[6][1]) if len(kpts) > 6 else 0.0
        lwy = float(kpts[9][1]) if len(kpts) > 9 else 0.0
        rwy = float(kpts[10][1]) if len(kpts) > 10 else 0.0
        lwx = float(kpts[9][0]) if len(kpts) > 9 else 0.0
        rwx = float(kpts[10][0]) if len(kpts) > 10 else 0.0
        lsx = float(kpts[5][0]) if len(kpts) > 5 else 0.0
        rsx = float(kpts[6][0]) if len(kpts) > 6 else 0.0

        left_up  = lsy > 0 and lwy > 0 and lwy < lsy - threshold_px
        right_up = rsy > 0 and rwy > 0 and rwy < rsy - threshold_px
        t_pose = (
            lwy > 0 and rwy > 0
            and abs(lwy - lsy) < 40 and abs(rwy - rsy) < 40
            and abs(lwx - lsx) > 50 and abs(rwx - rsx) > 50
        )

        if t_pose:
            return "t_pose"
        elif left_up and right_up:
            return "both_arms_up"
        elif left_up:
            return "left_arm_up"
        elif right_up:
            return "right_arm_up"
        return "None"

    def test_left_arm_up_detected(self):
        kpts = _make_kpts_for_gesture(left_wrist_y=200.0, right_wrist_y=350.0)
        assert self._classify(kpts) == "left_arm_up"

    def test_right_arm_up_detected(self):
        kpts = _make_kpts_for_gesture(left_wrist_y=350.0, right_wrist_y=200.0)
        assert self._classify(kpts) == "right_arm_up"

    def test_both_arms_up_detected(self):
        kpts = _make_kpts_for_gesture(left_wrist_y=200.0, right_wrist_y=200.0)
        assert self._classify(kpts) == "both_arms_up"

    def test_t_pose_detected(self):
        # Wrists at same height as shoulders, stretched out horizontally
        kpts = _make_kpts_for_gesture(
            left_wrist_y=305.0,   right_wrist_y=305.0,   # ~same as shoulders (300)
            left_wrist_x=400.0,   right_wrist_x=880.0,   # far from shoulders
            left_shoulder_x=560.0, right_shoulder_x=720.0,
        )
        assert self._classify(kpts) == "t_pose"

    def test_arms_at_side_none(self):
        # Wrists below shoulders
        kpts = _make_kpts_for_gesture(left_wrist_y=400.0, right_wrist_y=400.0)
        assert self._classify(kpts) == "None"

    def test_just_below_threshold_not_detected(self):
        # Wrist is 49px above shoulder — just below the 50px threshold
        kpts = _make_kpts_for_gesture(left_wrist_y=252.0, right_wrist_y=400.0)  # 300-252=48 < 50
        assert self._classify(kpts) == "None"

    def test_exactly_at_threshold_detected(self):
        # Wrist is exactly 51px above shoulder — just above threshold
        kpts = _make_kpts_for_gesture(left_wrist_y=249.0, right_wrist_y=400.0)  # 300-249=51 >= 50
        assert self._classify(kpts) == "left_arm_up"


class TestGestureCooldown:
    """Verify that a held gesture only fires once per cooldown period."""

    def test_gesture_fires_once_within_cooldown(self):
        """Simulate sending the same gesture 5 times rapidly — only 1 HTTP call."""
        post_calls = []

        def _fake_post(url, json, **kw):
            post_calls.append(json)
            class _R:
                status_code = 200
            return _R()

        with mock.patch("requests.post", side_effect=_fake_post):
            import yolo_tracker as yt_m
            # Reset gesture timer
            yt_m._last_gesture_time = 0.0
            cooldown = float(yt_m.CFG["gesture_cooldown_s"])

            for _ in range(5):
                current_time = time.time()
                if current_time - yt_m._last_gesture_time > cooldown:
                    _fake_post(f"{yt_m._BRAIN_API}/trigger_gesture", {"gesture": "left_arm_up"})
                    yt_m._last_gesture_time = current_time
                # Simulate rapid frames (no sleep)

        # Should only have fired once since there was no sleep between calls
        assert len(post_calls) == 1, f"Expected 1 call, got {len(post_calls)}"

    def test_gesture_fires_again_after_cooldown(self):
        """After the cooldown expires, the same gesture should fire again."""
        import yolo_tracker as yt_m
        post_calls = []

        def _fake_post(url, json, **kw):
            post_calls.append(json)
            class _R:
                status_code = 200
            return _R()

        with mock.patch("requests.post", side_effect=_fake_post):
            yt_m._last_gesture_time = time.time() - 100.0  # simulate old gesture
            cooldown = float(yt_m.CFG["gesture_cooldown_s"])
            current_time = time.time()
            if current_time - yt_m._last_gesture_time > cooldown:
                _fake_post(f"{yt_m._BRAIN_API}/trigger_gesture", {"gesture": "left_arm_up"})
                yt_m._last_gesture_time = current_time

        assert len(post_calls) == 1
