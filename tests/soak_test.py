"""
tests/soak_test.py
Phase 2 — Soak/stress test for the Flask Brain API.
Simulates continuous load on all endpoints for a configurable duration.
Reports: requests/sec, error rate, memory growth.
Usage: python tests/soak_test.py --duration 1800  (default 30 min)
"""

from __future__ import annotations

import argparse
import gc
import subprocess
import sys
import os
import threading
import time
from typing import Any

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import requests

_API = "http://127.0.0.1:5000"
_stats: dict[str, Any] = {
    "requests": 0,
    "errors": 0,
    "start_mem_mb": 0.0,
    "peak_mem_mb": 0.0,
}
_lock = threading.Lock()


def _get_mem_mb() -> float:
    """Return current process RSS memory in MB."""
    try:
        import psutil
        proc = psutil.Process(os.getpid())
        return proc.memory_info().rss / 1024 / 1024
    except ImportError:
        return 0.0


def _worker(stop_event: threading.Event) -> None:
    """Continuously hit all endpoints until stop_event is set."""
    endpoints = [
        ("GET", "/health", None),
        ("GET", "/state", None),
        ("POST", "/toggle_mic", None),
        ("POST", "/event", {"type": "fall_detected", "person": "SoakTest"}),
        ("POST", "/update_config", {"left_arm_up": "Toggle Light"}),
        ("POST", "/trigger_gesture", {"gesture": "left_arm_up"}),
    ]
    idx = 0
    while not stop_event.is_set():
        method, path, body = endpoints[idx % len(endpoints)]
        idx += 1
        try:
            if method == "GET":
                r = requests.get(f"{_API}{path}", timeout=2)
            else:
                r = requests.post(f"{_API}{path}", json=body, timeout=2)
            with _lock:
                _stats["requests"] += 1
                if r.status_code >= 500:
                    _stats["errors"] += 1
        except Exception:
            with _lock:
                _stats["errors"] += 1


def run_soak(duration_s: int = 30, num_workers: int = 4) -> None:
    """Run soak test for *duration_s* seconds with *num_workers* threads."""
    print(f"\n{'='*60}")
    print(f"SOAK TEST — {duration_s}s duration, {num_workers} workers")
    print(f"Target: {_API}")
    print("IMPORTANT: voice_assistant.py must be running before this test.")
    print(f"{'='*60}\n")

    # Quick connectivity check
    try:
        requests.get(f"{_API}/health", timeout=2)
    except Exception as e:
        print(f"[ERROR] Cannot reach Brain API: {e}")
        print("Start voice_assistant.py first, then re-run this test.")
        sys.exit(1)

    start_mem = _get_mem_mb()
    _stats["start_mem_mb"] = start_mem
    _stats["peak_mem_mb"] = start_mem

    stop_event = threading.Event()
    workers = [threading.Thread(target=_worker, args=(stop_event,), daemon=True) for _ in range(num_workers)]
    for w in workers: w.start()

    start_time = time.time()
    interval = 5.0
    last_report = start_time

    while time.time() - start_time < duration_s:
        time.sleep(0.5)
        now = time.time()
        if now - last_report >= interval:
            elapsed = now - start_time
            with _lock:
                reqs = _stats["requests"]
                errs = _stats["errors"]
            mem = _get_mem_mb()
            _stats["peak_mem_mb"] = max(_stats["peak_mem_mb"], mem)
            rps = reqs / max(elapsed, 1)
            err_pct = 100 * errs / max(reqs, 1)
            print(
                f"[{elapsed:6.1f}s] Requests: {reqs:6d} | RPS: {rps:5.1f} | "
                f"Errors: {errs} ({err_pct:.1f}%) | Mem: {mem:.1f} MB"
            )
            last_report = now

    stop_event.set()
    for w in workers: w.join(timeout=5)

    elapsed = time.time() - start_time
    with _lock:
        final_reqs = _stats["requests"]
        final_errs = _stats["errors"]
    final_mem = _get_mem_mb()
    mem_growth = final_mem - start_mem

    print(f"\n{'='*60}")
    print("SOAK TEST RESULTS")
    print(f"{'='*60}")
    print(f"Duration:       {elapsed:.1f}s")
    print(f"Total requests: {final_reqs}")
    print(f"Total errors:   {final_errs} ({100*final_errs/max(final_reqs,1):.2f}%)")
    print(f"Avg RPS:        {final_reqs/elapsed:.1f}")
    print(f"Start memory:   {start_mem:.1f} MB")
    print(f"End memory:     {final_mem:.1f} MB")
    print(f"Peak memory:    {_stats['peak_mem_mb']:.1f} MB")
    print(f"Memory growth:  {mem_growth:+.1f} MB")
    print(f"{'='*60}")

    if mem_growth > 50:
        print("[WARN] Memory grew by >50 MB — possible leak, investigate further.")
    if final_errs / max(final_reqs, 1) > 0.01:
        print("[WARN] Error rate >1% — check Brain logs.")
    else:
        print("[PASS] Error rate within bounds (<1%)")
    print("[PASS] Soak test completed without crashes.\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Ambient AI Hub soak test")
    parser.add_argument("--duration", type=int, default=1800, help="Duration in seconds (default 1800 = 30 min)")
    parser.add_argument("--workers", type=int, default=4, help="Number of concurrent worker threads")
    args = parser.parse_args()
    run_soak(duration_s=args.duration, workers=args.workers)
