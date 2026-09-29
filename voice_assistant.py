"""
Ambient AI Voice Assistant - The Brain
Handles: STT (Vosk), TTS (pyttsx3), LLM (Ollama), API Server (Flask)
"""

import os
import queue
import sys
import json
import time
import threading
import logging
import numpy as np
import requests
import pyttsx3
import sounddevice as sd
import vosk
from ollama import Client
from flask import Flask, request as flask_request

# ============================================================
# 1. TEXT-TO-SPEECH SETUP
# ============================================================
engine = pyttsx3.init()
engine.setProperty('rate', 175)
voices = engine.getProperty('voices')
for voice in voices:
    if "Zira" in voice.name or "female" in voice.name.lower():
        engine.setProperty('voice', voice.id)
        break

def speak(text):
    """Speak text out loud. Thread-safe wrapper around pyttsx3."""
    print(f"Assistant: {text}")
    try:
        engine.say(text)
        engine.runAndWait()
    except Exception as e:
        print(f"[TTS Error]: {e}")

# ============================================================
# 2. OLLAMA LLM CLIENT
# ============================================================
ollama_client = Client(host='http://localhost:11434')

# ============================================================
# 3. MICROPHONE AUDIO QUEUE
# ============================================================
audio_queue = queue.Queue()

def audio_callback(indata, frames, time_info, status):
    if status:
        print(status, file=sys.stderr)
    audio_queue.put(bytes(indata))

# ============================================================
# 4. GLOBAL SYSTEM STATE (shared between Flask API + main loop)
# ============================================================
system_state = {
    "mic_muted": False,
    "last_alert": "System Online - Monitoring Active",
    "last_alert_time": "",
    "smart_home": {
        "light": False,
        "fan": False
    },
    "gesture_config": {
        "left_arm_up": "Toggle Mic",
        "right_arm_up": "Toggle Light",
        "both_arms_up": "Toggle Fan",
        "t_pose": "None"
    }
}
event_queue = queue.Queue()

# ============================================================
# 5. FLASK API SERVER (runs in background thread)
# ============================================================
log = logging.getLogger('werkzeug')
log.setLevel(logging.ERROR)

app = Flask(__name__)

@app.route('/state', methods=['GET'])
def api_get_state():
    return system_state

@app.route('/toggle_mic', methods=['POST'])
def api_toggle_mic():
    system_state["mic_muted"] = not system_state["mic_muted"]
    status = "MUTED" if system_state["mic_muted"] else "UNMUTED"
    print(f"\n[PRIVACY] Microphone has been {status} via Dashboard!")
    return {"muted": system_state["mic_muted"]}

@app.route('/event', methods=['POST'])
def api_receive_event():
    import datetime
    data = flask_request.json
    if data and data.get('type') == 'fall_detected':
        person = data.get('person', 'Unknown')
        system_state["last_alert"] = f"CRITICAL: Fall Detected ({person})"
        system_state["last_alert_time"] = datetime.datetime.now().strftime("%I:%M:%S %p")
    event_queue.put(data)
    return {"status": "received"}

@app.route('/update_config', methods=['POST'])
def api_update_config():
    data = flask_request.json
    if data:
        system_state["gesture_config"].update(data)
    return system_state["gesture_config"]

@app.route('/trigger_gesture', methods=['POST'])
def api_trigger_gesture():
    data = flask_request.json
    gesture = data.get('gesture', 'None')
    action = system_state["gesture_config"].get(gesture, "None")
    
    if action == 'Toggle Mic':
        system_state["mic_muted"] = not system_state["mic_muted"]
        print(f"\n[ACTION] Microphone toggled via Gesture: {gesture}")
    elif action == 'Toggle Light':
        system_state["smart_home"]["light"] = not system_state["smart_home"]["light"]
        print(f"\n[ACTION] Light toggled via Gesture: {gesture}")
    elif action == 'Toggle Fan':
        system_state["smart_home"]["fan"] = not system_state["smart_home"]["fan"]
        print(f"\n[ACTION] Fan toggled via Gesture: {gesture}")
        
    return {"status": "success", "action": action, "gesture": gesture}

def start_api_server():
    print("\n[*] Brain API Server listening on port 5000...")
    app.run(host='0.0.0.0', port=5000, debug=False, use_reloader=False)

# ============================================================
# 6. AI TOOL DEFINITIONS
# ============================================================
def get_weather(city: str = "London", **kwargs) -> str:
    """Get the current weather for a specific city."""
    print(f"[*] ACTION: Fetching weather for {city}...")
    try:
        import urllib.parse
        safe_city = urllib.parse.quote(city)
        # wttr.in often blocks Python's default User-Agent, so we pretend to be curl
        headers = {'User-Agent': 'curl/7.68.0'}
        res = requests.get(f"https://wttr.in/{safe_city}?format=1", headers=headers, timeout=5)
        
        if res.status_code == 200:
            # wttr.in format=1 returns something like "⛅️ +18°C"
            return f"The current weather in {city} is {res.text.strip()}."
        else:
            return f"I couldn't find the weather for {city}."
    except Exception as e:
        print(f"[!] Weather API Error: {e}")
        return "I could not fetch the weather due to a network error."

def emergency_call(contact_name: str = "Emergency Services", **kwargs) -> str:
    """Place an emergency call or alert to a specific contact."""
    print(f"[*] ACTION: ACTIVATING EMERGENCY PROTOCOL for {contact_name}!!!")
    return f"Emergency alert has been sent to {contact_name}."

TOOL_MAP = {
    'get_weather': get_weather,
    'emergency_call': emergency_call
}

# Keywords that signal the user actually wants a tool
WEATHER_KEYWORDS = ["weather", "temperature", "hot", "cold", "rain", "sunny", "forecast"]
EMERGENCY_KEYWORDS = ["call", "emergency", "help me", "ambulance", "doctor", "fallen", "i fell"]

def extract_city_from_text(text):
    """Extract a city name from the user's speech by removing known filler words."""
    filler = [
        "what", "what's", "whats", "how", "how's", "hows", "is", "the", "in", 
        "weather", "temperature", "like", "today", "right", "now", "tell", "me",
        "about", "of", "forecast", "check", "get", "please", "pls", "can", "you",
        "a", "an", "it", "that", "this", "there", "so", "and", "for",
        # Common Vosk STT misheard words
        "saw", "was", "see", "show"
    ]
    words = text.lower().split()
    city_words = [w for w in words if w not in filler]
    return " ".join(city_words).strip().title() if city_words else ""

def detect_intent(text):
    """Detect what the user wants: 'weather', 'emergency', or 'chat'."""
    text_lower = text.lower()
    for kw in WEATHER_KEYWORDS:
        if kw in text_lower:
            return "weather"
    for kw in EMERGENCY_KEYWORDS:
        if kw in text_lower:
            return "emergency"
    return "chat"

# ============================================================
# 7. MAIN LOOP
# ============================================================
def main():
    # --- Microphone Selection ---
    devices = sd.query_devices()
    input_devices = []

    print("\n" + "=" * 50)
    print("AVAILABLE MICROPHONES:")
    print("=" * 50)

    for i, dev in enumerate(devices):
        if dev['max_input_channels'] > 0:
            input_devices.append(i)
            print(f"[{i}] {dev['name']}")

    print()
    if os.environ.get('HEADLESS', 'False').lower() == 'true':
        print("Running in HEADLESS mode. Using default microphone.")
        device_id = None
    else:
        try:
            device_id = int(input("Type the number of your microphone and press Enter (or just press Enter for default): "))
        except (ValueError, EOFError):
            print("Using default microphone.")
            device_id = None

    if device_id is not None and device_id not in input_devices:
        print("That is not a valid microphone. Using default.")
        device_id = None

    selected = sd.query_devices(device_id) if device_id is not None else sd.query_devices(kind='input')
    print(f"\nUSING MICROPHONE: {selected['name']}")

    # --- Load Vosk STT Model ---
    print("Loading Offline Speech-to-Text Model...")
    model = vosk.Model(model_name="vosk-model-small-en-us-0.15")

    # --- Start Flask API in background ---
    threading.Thread(target=start_api_server, daemon=True).start()

    print("\n" + "=" * 50)
    print("AMBIENT AI ASSISTANT ONLINE")
    print("=" * 50)
    print("Listening... (Say 'exit' or 'quit' to stop)\n")

    # Chat history with a strict system prompt
    chat_history = [
        {
            "role": "system",
            "content": (
                "You are Ambient, a smart home AI assistant. "
                "Rules: "
                "1. Keep ALL answers to 1 sentence maximum. "
                "2. You are a voice assistant. You can hear and speak. "
                "3. If someone says hello or asks if you can hear them, just confirm warmly. "
                "4. You do NOT control any smart home devices (no locks, lights, thermostats). "
                "5. Do NOT make up features you don't have. "
                "6. You CAN check the weather and place emergency calls. "
                "7. For anything else, just have a friendly short conversation. "
                "8. If the user's text makes no sense (speech recognition error), just say 'I didn't quite catch that.'"
            )
        }
    ]

    # --- Open Microphone Stream ---
    with sd.RawInputStream(samplerate=16000, blocksize=8000, device=device_id,
                           dtype='int16', channels=1, callback=audio_callback):
        recognizer = vosk.KaldiRecognizer(model, 16000)

        while True:
            # --- Check for Vision Engine alerts ---
            try:
                event = event_queue.get_nowait()
                if event and event.get('type') == 'fall_detected':
                    person = event.get('person', 'Unknown')
                    print("\n!!! EXTERNAL VISION ALERT RECEIVED !!!")
                    speak(f"Warning! I have detected that {person} has fallen!")
                    result = emergency_call(contact_name="Family")
                    speak(result)
            except queue.Empty:
                pass

            # --- Privacy Mode: drain audio and skip ---
            if system_state["mic_muted"]:
                # Drain any buffered audio so it doesn't pile up
                try:
                    while True:
                        audio_queue.get_nowait()
                except queue.Empty:
                    pass
                time.sleep(0.1)
                continue

            # --- Get next audio packet (with timeout so mute can interrupt) ---
            try:
                data = audio_queue.get(timeout=0.5)
            except queue.Empty:
                continue

            # --- Volume indicator ---
            audio_data = np.frombuffer(data, dtype=np.int16)
            volume = np.linalg.norm(audio_data) / len(audio_data)
            if volume < 5:
                print(".", end="", flush=True)
            else:
                print("!", end="", flush=True)

            # --- Speech Recognition ---
            if recognizer.AcceptWaveform(data):
                print()  # newline after dots
                result = json.loads(recognizer.Result())
                text = result.get("text", "").strip()

                if not text:
                    continue

                print(f"\nYou said: {text}")

                if "exit" in text or "quit" in text:
                    speak("Goodbye!")
                    break

                chat_history.append({"role": "user", "content": text})

                try:
                    print("Thinking...")
                    intent = detect_intent(text)

                    if intent == "weather":
                        # Extract city directly from user's words - don't trust the AI
                        city = extract_city_from_text(text)
                        if not city:
                            city = "London"  # Fallback
                        reply = get_weather(city=city)
                        chat_history.append({"role": "assistant", "content": reply})
                        speak(reply)

                    elif intent == "emergency":
                        reply = emergency_call(contact_name="Family")
                        chat_history.append({"role": "assistant", "content": reply})
                        speak(reply)

                    else:
                        # Normal conversation - send to Ollama WITHOUT tools
                        response = ollama_client.chat(
                            model='llama3.2:1b',
                            messages=chat_history
                        )
                        message = response.get('message', {})
                        reply = message.get('content', 'Sorry, I did not understand.')
                        chat_history.append({"role": "assistant", "content": reply})
                        speak(reply)

                    # Keep chat history from growing forever (last 20 messages)
                    if len(chat_history) > 21:
                        chat_history = [chat_history[0]] + chat_history[-20:]

                except Exception as e:
                    print(f"Error: {e}")
                    speak("I am having trouble connecting to my brain.")


if __name__ == "__main__":
    main()
