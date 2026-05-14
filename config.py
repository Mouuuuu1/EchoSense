"""
EchoSense — central configuration.
Edit the GPIO pins and paths here to match your physical wiring.
"""

import sys
import os

# ── hailo-apps on PYTHONPATH ──────────────────────────────────────────────────
HAILO_APPS_PATH = "/home/echosense/hailo-apps"
if HAILO_APPS_PATH not in sys.path:
    sys.path.insert(0, HAILO_APPS_PATH)

# ── GPIO pin assignments (BCM numbering) ──────────────────────────────────────
# Buttons — connect each to GND; internal pull-up is used
BUTTON_LLM_PIN   = 16   # LLM / scene-describe button
BUTTON_SOS_PIN   = 20   # SOS / emergency button
BUTTON_POWER_PIN = 21   # Graceful shutdown button

# Buzzers (digital on/off via transistor)
BUZZER_1_PIN = 23
BUZZER_2_PIN = 24

# Vibration motor (digital on/off via transistor)
VIBRATION_PIN = 25

# LEDs (PWM-capable pins for dimming)
LED_1_PIN = 12   # GPIO 12 / PWM0
LED_2_PIN = 13   # GPIO 13 / PWM1

# ── Serial ports ──────────────────────────────────────────────────────────────
SIM808_PORT      = "/dev/serial0"
SIM808_BAUD      = 9600
LIDAR_PORT       = "/dev/ttyAMA0"
LIDAR_BAUD       = 115200

# ── AI model paths ────────────────────────────────────────────────────────────
MODELS_DIR = os.path.join(HAILO_APPS_PATH, "resources", "models", "hailo10h")

YOLO_HEF_PATH    = os.path.join(os.path.dirname(__file__), "yolov8s.hef")
WHISPER_HEF_PATH = os.path.join(MODELS_DIR, "Whisper-Base.hef")
VLM_HEF_PATH     = os.path.join(MODELS_DIR, "Qwen2-VL-2B-Instruct.hef")

PIPER_MODELS_DIR = os.path.join(HAILO_APPS_PATH, "local_resources", "piper_models")

# ── Detection thresholds ──────────────────────────────────────────────────────
DETECTION_CONF     = 0.4      # YOLO confidence threshold
DETECTION_IOU      = 0.45     # YOLO NMS IOU threshold

# Distance (cm) at which obstacle alerts trigger
ALERT_DISTANCE_CM  = 150      # ~1.5 m → start buzzing
DANGER_DISTANCE_CM = 60       # <60 cm → urgent buzz + vibration

# Seconds between consecutive TTS object-detection announcements
ANNOUNCE_INTERVAL  = 3.0

# ── Navigation ────────────────────────────────────────────────────────────────
# OSRM routing — public demo server (swap for self-hosted or Google Maps API key)
OSRM_BASE_URL      = "http://router.project-osrm.org"

# Optional Google Maps API key (leave empty to use OSRM)
GOOGLE_MAPS_KEY    = ""

# Nominatim geocoding (OpenStreetMap, no key needed)
NOMINATIM_URL      = "https://nominatim.openstreetmap.org"

# Turn-by-turn announcement distance threshold (metres)
WAYPOINT_RADIUS_M  = 15

# ── GPS polling ───────────────────────────────────────────────────────────────
GPS_POLL_INTERVAL  = 5        # seconds between GPS reads

# ── Caregiver server ──────────────────────────────────────────────────────────
SERVER_HOST        = "0.0.0.0"
SERVER_PORT        = 8080
STREAM_FPS         = 10       # MJPEG stream target FPS

# ── Firebase (optional) ───────────────────────────────────────────────────────
# Set FIREBASE_URL to your Realtime Database URL to enable cloud sync.
# Example: "https://your-project-default-rtdb.firebaseio.com"
FIREBASE_URL       = os.environ.get("FIREBASE_URL", "")
FIREBASE_SECRET    = os.environ.get("FIREBASE_SECRET", "")   # DB secret / token

# ── VLM system prompt ─────────────────────────────────────────────────────────
VLM_SYSTEM_PROMPT = (
    "You are EchoSense, an AI assistant for a visually impaired person. "
    "Describe what you see in the camera image in clear, concise spoken language. "
    "Focus on objects, hazards, people, and navigation cues. "
    "Respond in at most three sentences."
)

VLM_DEFAULT_QUESTION = "What do you see? Describe the scene for a visually impaired person."

# ── Voice assistant system prompt ─────────────────────────────────────────────
VOICE_SYSTEM_PROMPT = (
    "You are EchoSense, a voice assistant for a visually impaired person. "
    "Answer questions briefly and clearly in spoken language. "
    "If asked to navigate somewhere, respond with: NAVIGATE TO <destination>. "
    "Respond in at most two sentences."
)
