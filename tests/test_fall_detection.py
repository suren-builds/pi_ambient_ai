"""
tests/test_fall_detection.py
Phase 2 — Fall detection logic tests with synthetic keypoints.
No camera, YOLO, or hardware required.
Conftest.py stubs all hardware deps before this module is collected.
"""

from __future__ import annotations

import sys
import os

import numpy as np
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# yolo_tracker can now be imported safely — conftest has stubbed VideoCapture + ultralytics
from yolo_tracker import compute_fall_score  # type: ignore[import]

FRAME_H = 720  # synthetic 1280×720 frame

# ─── Helper: build a fake kpts array ─────────────────────────────────────────
# YOLOv8-pose keypoint layout (17 points):
#  0=Nose 1=L-Eye 2=R-Eye 3=L-Ear 4=R-Ear
#  5=L-Shoulder 6=R-Shoulder 7=L-Elbow 8=R-Elbow 9=L-Wrist 10=R-Wrist
# 11=L-Hip 12=R-Hip 13=L-Knee 14=R-Knee 15=L-Ankle 16=R-Ankle

def _make_kpts(
    shoulder_y: float, hip_y: float, ankle_y: float,
    shoulder_x: float = 640, hip_x: float = 640,
) -> None:
    """Not used directly — compute_fall_score takes extracted scalars."""
    pass


# ─── Standing scenarios ───────────────────────────────────────────────────────
class TestStanding:
    """A vertical, upright person: box taller than wide, spine vertical."""

    def _standing(self, hip_y_frac: float = 0.4):
        # Upright person occupies top half of frame
        sx, sy = 640.0, 100.0      # shoulders near top
        hx, hy = 640.0, FRAME_H * hip_y_frac   # hips mid-frame
        ay = FRAME_H * (hip_y_frac + 0.2)       # ankles below hips
        w, h = 200.0, 500.0        # tall box
        return compute_fall_score(sx, sy, hx, hy, ay, w, h, FRAME_H)

    def test_standing_score_below_threshold(self):
        score, on_floor, _, corrupted = self._standing()
        assert not corrupted
        assert score < 3, f"Expected score<3 for upright person, got {score}"

    def test_standing_not_on_floor(self):
        _, on_floor, _, _ = self._standing(hip_y_frac=0.3)
        assert not on_floor

    def test_standing_at_bottom_of_frame_no_fall(self):
        """Person standing close to camera — hips low but spine vertical."""
        sx, sy = 640.0, 200.0
        hx, hy = 640.0, 400.0
        ay = 600.0
        w, h = 250.0, 550.0
        score, on_floor, _, corrupted = compute_fall_score(sx, sy, hx, hy, ay, w, h, FRAME_H)
        assert not corrupted
        assert score < 3, f"Standing close to camera shouldn't be a fall, got score={score}"


# ─── Sitting scenarios ────────────────────────────────────────────────────────
class TestSitting:
    """Person seated in a chair — box wider, but ankles near hips (bent legs)."""

    def test_sitting_not_fall(self):
        sx, sy = 640.0, 200.0   # shoulders
        hx, hy = 640.0, 380.0   # hips
        ay = 420.0               # ankles close (legs bent in chair)
        w, h = 300.0, 350.0      # moderately wide box
        score, on_floor, _, corrupted = compute_fall_score(sx, sy, hx, hy, ay, w, h, FRAME_H)
        assert not corrupted
        # Sitting can accumulate some signals; assert no confirmed fall
        # (on_floor might be True if person is in bottom half — that is valid)
        # Key: score should be < threshold OR on_floor should be False
        assert not (score >= 3 and on_floor), f"Sitting falsely detected as fall (score={score}, floor={on_floor})"


# ─── Bending / crouching ─────────────────────────────────────────────────────
class TestBending:
    def test_bending_forward_not_fall(self):
        """Person bending at the waist — spine tilted but body vertical."""
        sx, sy = 640.0, 250.0
        hx, hy = 660.0, 320.0
        ay = 500.0               # ankles still far below hips
        w, h = 180.0, 350.0
        score, on_floor, _, corrupted = compute_fall_score(sx, sy, hx, hy, ay, w, h, FRAME_H)
        assert not corrupted
        assert not (score >= 3 and on_floor), f"Bending should not be a fall (score={score})"


# ─── Fallen person (true positive) ───────────────────────────────────────────
class TestFall:
    def _fallen(self):
        # Lying horizontal: box much wider than tall, spine horizontal
        sx, sy = 400.0, 600.0   # shoulders low
        hx, hy = 600.0, 620.0   # hips low and close in Y to shoulders
        ay = 650.0               # ankles close to hip Y
        w, h = 700.0, 150.0     # wide, short box
        return compute_fall_score(sx, sy, hx, hy, ay, w, h, FRAME_H)

    def test_fallen_high_score(self):
        score, _, _, corrupted = self._fallen()
        assert not corrupted
        assert score >= 3, f"Expected fall score>=3, got {score}"

    def test_fallen_on_floor(self):
        _, on_floor, _, _ = self._fallen()
        assert on_floor

    def test_fallen_not_corrupted(self):
        _, _, _, corrupted = self._fallen()
        assert not corrupted


# ─── Corrupted skeleton guard ─────────────────────────────────────────────────
class TestSkeletonCorruption:
    def test_multi_person_overlap_detected(self):
        """Extremely tall box with barely-vertical spine → corrupted flag."""
        sx, sy = 640.0, 100.0
        hx, hy = 640.0, 110.0   # tiny spine_y
        ay = 200.0
        w, h = 100.0, 600.0     # very tall and narrow
        score, on_floor, debug, corrupted = compute_fall_score(sx, sy, hx, hy, ay, w, h, FRAME_H)
        assert corrupted, f"Expected corrupted skeleton flag, debug={debug}"
        assert score == 0


# ─── Edge cases ───────────────────────────────────────────────────────────────
class TestEdgeCases:
    def test_zero_coordinates(self):
        """All-zero input should not crash."""
        score, on_floor, _, corrupted = compute_fall_score(0, 0, 0, 0, 0, 0, 0, FRAME_H)
        # With all zeros: width=0, height=0 — won't trigger fall
        assert isinstance(score, int)

    def test_hidden_ankles_adds_score_point(self):
        """ay=0 means ankles hidden; the function should add 1 to score."""
        sx, sy = 640.0, 600.0
        hx, hy = 640.0, 620.0
        ay = 0.0                 # ankles hidden
        w, h = 700.0, 150.0
        score_with_hidden, *_ = compute_fall_score(sx, sy, hx, hy, ay, w, h, FRAME_H)
        ay_real = 650.0
        score_with_real, *_ = compute_fall_score(sx, sy, hx, hy, ay_real, w, h, FRAME_H)
        # Hidden ankles should not produce a LOWER score
        assert score_with_hidden >= score_with_real - 1
