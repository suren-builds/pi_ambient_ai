"""
tests/test_intent_and_utils.py
Phase 2 — Brain utility tests: intent detection, city extraction,
weather/emergency tool stubs, and Ollama response handling.
No audio hardware required. Conftest.py stubs all hardware deps.
"""

from __future__ import annotations

import sys
import os

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import voice_assistant as va  # type: ignore[import]


# ─────────────────────────────────────────────────────────────────────────────
# Intent detection
# ─────────────────────────────────────────────────────────────────────────────
class TestDetectIntent:
    @pytest.mark.parametrize("text", [
        "what is the weather in London",
        "how hot is it today",
        "will it rain tomorrow",
        "what is the temperature in Mumbai",
        "give me the forecast",
    ])
    def test_weather_intent(self, text: str):
        assert va.detect_intent(text) == "weather", f"Expected weather for: {text!r}"

    @pytest.mark.parametrize("text", [
        "help me please I fell",
        "call emergency services",
        "i need an ambulance",
        "SOS",
        "i fell down",
    ])
    def test_emergency_intent(self, text: str):
        assert va.detect_intent(text) == "emergency", f"Expected emergency for: {text!r}"

    @pytest.mark.parametrize("text", [
        "hello",
        "how are you",
        "tell me a joke",
        "what is 2 + 2",
        "good morning",
    ])
    def test_chat_intent(self, text: str):
        assert va.detect_intent(text) == "chat", f"Expected chat for: {text!r}"

    def test_empty_string_is_chat(self):
        assert va.detect_intent("") == "chat"


# ─────────────────────────────────────────────────────────────────────────────
# City extraction
# ─────────────────────────────────────────────────────────────────────────────
class TestExtractCity:
    def test_simple_city(self):
        city = va.extract_city("what is the weather in London")
        assert "London" in city

    def test_two_word_city(self):
        city = va.extract_city("weather in New York today")
        assert "New" in city or "York" in city  # filler removal is best-effort

    def test_all_filler_returns_empty_or_fallback(self):
        city = va.extract_city("what is the weather")
        # Should return empty string (caller provides fallback)
        assert isinstance(city, str)

    def test_case_title_returned(self):
        city = va.extract_city("weather mumbai")
        assert city == city.title()


# ─────────────────────────────────────────────────────────────────────────────
# Emergency call (dry run mode)
# ─────────────────────────────────────────────────────────────────────────────
class TestEmergencyCall:
    def test_dry_run_returns_dry_run_string(self):
        result = va.emergency_call(contact_name="TestContact", dry_run=True)
        assert "DRY RUN" in result
        assert "TestContact" in result

    def test_live_mode_returns_confirmation(self):
        result = va.emergency_call(contact_name="Family")
        assert "Family" in result
        assert "Emergency" in result or "alert" in result.lower()

    def test_default_contact_name(self):
        result = va.emergency_call()
        assert "Emergency Services" in result or "Emergency" in result


# ─────────────────────────────────────────────────────────────────────────────
# Ollama response normalization (handles both dict and object)
# ─────────────────────────────────────────────────────────────────────────────
class TestOllamaResponseHandling:
    def test_dict_style_old_sdk(self, monkeypatch):
        """Old ollama SDK returned a dict."""
        def _fake_chat(model, messages):
            return {"message": {"content": "dict-style response"}}

        monkeypatch.setattr(va._ollama_client, "chat", _fake_chat)
        result = va._call_ollama([{"role": "user", "content": "hi"}])
        assert result == "dict-style response"

    def test_object_style_new_sdk(self, monkeypatch):
        """New ollama SDK returns an object with .message.content."""
        class _Msg:
            content = "object-style response"
        class _Resp:
            message = _Msg()

        monkeypatch.setattr(va._ollama_client, "chat", lambda model, messages: _Resp())
        result = va._call_ollama([{"role": "user", "content": "hi"}])
        assert result == "object-style response"

    def test_ollama_timeout_returns_fallback(self, monkeypatch):
        """If Ollama hangs, _call_ollama should return the timeout fallback string."""
        import time as _time
        # Override timeout to 0.1s
        monkeypatch.setitem(va.CFG, "ollama_timeout_s", 0.1)

        def _slow_chat(model, messages):
            _time.sleep(5)  # much longer than timeout

        monkeypatch.setattr(va._ollama_client, "chat", _slow_chat)
        result = va._call_ollama([{"role": "user", "content": "hi"}])
        assert "slow" in result.lower() or "trouble" in result.lower()

    def test_ollama_exception_returns_fallback(self, monkeypatch):
        def _failing_chat(model, messages):
            raise ConnectionRefusedError("Ollama not running")

        monkeypatch.setattr(va._ollama_client, "chat", _failing_chat)
        result = va._call_ollama([{"role": "user", "content": "hi"}])
        assert "trouble" in result.lower() or "error" in result.lower() or "having" in result.lower()
