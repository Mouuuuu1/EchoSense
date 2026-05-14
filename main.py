#!/usr/bin/env python3
"""
EchoSense — main orchestrator.

Threads:
  detection   — camera + YOLO + LiDAR → TTS announcements + obstacle alerts
  gps         — SIM808 GPS polling → DB + Firebase + WebSocket broadcast
  voice_vad   — continuous mic listening → STT → command dispatch
  server      — FastAPI caregiver web interface (uvicorn)

Buttons (event-driven, no thread):
  LLM   — capture frame → VLM describe → speak
  SOS   — send SMS with GPS coords
  Power — graceful shutdown
"""

import sys
import time
import threading
import signal
import asyncio
import cv2
import numpy as np

import config
from utils.logger import get_logger

from hardware.lidar   import TFLunaLIDAR
from hardware.buzzer  import BuzzerController
from hardware.vibration import VibrationMotor
from hardware.leds    import LEDController
from hardware.buttons import ButtonController
from hardware.sim808  import SIM808

from ai.detection   import ObjectDetector
from ai.voice_output import VoiceOutput
from ai.voice_input  import VoiceInput
from ai.vlm          import VLMProcessor

from navigation.gps    import GPSManager
from navigation.router import Navigator

from server.stream   import MJPEGStream
from server.database import Database
from server.app      import create_app, run_server

log = get_logger(__name__)

# ── shared state (read/written by multiple threads) ───────────────────────────
_state = {
    "latest_frame":    None,        # np.ndarray BGR
    "gps_coords":      None,        # (lat, lon) or None
    "lidar_distance":  0,           # cm
    "mode":            "detection", # "detection" | "vlm" | "navigation"
    "navigating":      False,
    "nav_destination": None,
    "last_detection":  "",
}
_state_lock = threading.Lock()
_shutdown_event = threading.Event()


def _update(key, value):
    with _state_lock:
        _state[key] = value


def _get(key):
    with _state_lock:
        return _state[key]


# ── detection thread ──────────────────────────────────────────────────────────

def detection_thread(detector: ObjectDetector, lidar: TFLunaLIDAR | None,
                     tts: VoiceOutput, buzzer: BuzzerController,
                     vibration: VibrationMotor, stream: MJPEGStream):
    log.info("Detection thread starting…")

    cap = _open_camera()
    if cap is None:
        log.error("No camera found — detection thread exiting")
        return

    last_announce = 0.0
    last_desc = ""

    while not _shutdown_event.is_set():
        ret, frame = cap.read()
        if not ret:
            time.sleep(0.05)
            continue

        # Skip detection while VLM is running to avoid Hailo conflicts
        if _get("mode") == "vlm":
            time.sleep(0.1)
            continue

        lidar_dist = lidar.distance if lidar else None
        _update("lidar_distance", lidar_dist or 0)
        _update("latest_frame", frame.copy())

        boxes, scores, class_ids = detector.detect(frame)
        desc = detector.describe(boxes, scores, class_ids,
                                 frame.shape[1], frame.shape[0], lidar_dist)
        _update("last_detection", desc)

        # ── obstacle alert ───────────────────────────────────────────────────
        if lidar_dist and lidar_dist > 0:
            if lidar_dist < config.DANGER_DISTANCE_CM:
                buzzer.alert_proximity(lidar_dist)
                vibration.obstacle_warning()
            elif lidar_dist < config.ALERT_DISTANCE_CM:
                buzzer.alert_proximity(lidar_dist)
            else:
                buzzer.stop_alert()

        # ── periodic TTS announcement ────────────────────────────────────────
        now = time.time()
        if now - last_announce >= config.ANNOUNCE_INTERVAL:
            if desc != last_desc or desc != "Path is clear":
                tts.speak(desc)
                last_desc = desc
                last_announce = now

        # ── push frame to MJPEG stream ───────────────────────────────────────
        annotated = detector.draw(frame.copy(), boxes, scores, class_ids)
        stream.push_frame(annotated)

    cap.release()
    log.info("Detection thread stopped")


def _open_camera():
    use_picam = False
    for idx in range(8):
        cap = cv2.VideoCapture(idx, cv2.CAP_V4L2)
        if not cap.isOpened():
            continue
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
        cap.set(cv2.CAP_PROP_FPS, 30)
        cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc('M', 'J', 'P', 'G'))
        for _ in range(10):
            ret, _ = cap.read()
            if ret:
                log.info("Camera opened at /dev/video%d", idx)
                return cap
            time.sleep(0.05)
        cap.release()

    # Fallback: Picamera2
    try:
        from picamera2 import Picamera2
        picam = Picamera2()
        picam.configure(picam.create_preview_configuration(
            main={"size": (640, 480), "format": "RGB888"}
        ))
        picam.start()
        time.sleep(0.3)
        log.info("Camera opened via Picamera2")
        # Wrap in a duck-typed object so the detection loop works uniformly
        return _Picamera2Wrapper(picam)
    except Exception as e:
        log.error("Picamera2 fallback failed: %s", e)
    return None


class _Picamera2Wrapper:
    def __init__(self, picam):
        self._picam = picam

    def read(self):
        rgb = self._picam.capture_array()
        return True, cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)

    def release(self):
        self._picam.stop()


# ── GPS thread ────────────────────────────────────────────────────────────────

def gps_thread(gps: GPSManager, db: Database, navigator: Navigator,
               tts: VoiceOutput, vibration: VibrationMotor,
               loop: asyncio.AbstractEventLoop, broadcast_fn):
    log.info("GPS thread starting…")
    while not _shutdown_event.is_set():
        coords = gps.fix
        if coords and coords.valid:
            pair = (coords.lat, coords.lon)
            _update("gps_coords", pair)
            db.log_location(coords.lat, coords.lon)

            # Push to WebSocket clients
            if broadcast_fn:
                asyncio.run_coroutine_threadsafe(
                    broadcast_fn(coords.lat, coords.lon), loop
                )

            # Navigation step check
            if navigator.active:
                instruction = navigator.update(pair)
                if instruction:
                    tts.speak(instruction)
                    if "left" in instruction.lower():
                        vibration.navigate_left()
                    elif "right" in instruction.lower():
                        vibration.navigate_right()

        _shutdown_event.wait(timeout=config.GPS_POLL_INTERVAL)
    log.info("GPS thread stopped")


# ── voice command dispatch ────────────────────────────────────────────────────

def _dispatch_voice(text: str, tts: VoiceOutput, navigator: Navigator,
                    sim808: SIM808, db: Database, vlm: VLMProcessor | None):
    log.info("Voice: %r", text)
    lower = text.lower()
    db.log_event("voice", text)

    # Navigate command
    if any(kw in lower for kw in ("navigate to", "take me to", "go to", "directions to")):
        dest = _extract_destination(lower)
        if dest:
            tts.speak(f"Planning route to {dest}")
            coords = _get("gps_coords")
            if not coords:
                tts.speak("No GPS fix available")
                return
            route = navigator.plan(coords, dest)
            if route:
                _update("navigating", True)
                _update("nav_destination", dest)
                first = route.steps[0].instruction if route.steps else "Start walking"
                tts.speak(f"Route found. {first}")
            else:
                tts.speak(f"Could not find a route to {dest}")
        return

    # Cancel navigation
    if any(kw in lower for kw in ("stop navigation", "cancel route", "stop navigating")):
        navigator.cancel()
        _update("navigating", False)
        _update("nav_destination", None)
        tts.speak("Navigation cancelled")
        return

    # What's around / describe scene
    if any(kw in lower for kw in ("what", "describe", "around", "see", "front")):
        if vlm and vlm.available:
            frame = _get("latest_frame")
            if frame is not None:
                _update("mode", "vlm")
                tts.speak("Analysing the scene")
                answer = vlm.describe(frame, question=text)
                tts.speak(answer)
                _update("mode", "detection")
            else:
                tts.speak("No camera frame available")
        else:
            desc = _get("last_detection")
            tts.speak(desc or "Nothing detected")
        return

    # Where am I
    if any(kw in lower for kw in ("where am i", "my location", "my position")):
        coords = _get("gps_coords")
        if coords:
            tts.speak(f"Your coordinates are {coords[0]:.4f} latitude, {coords[1]:.4f} longitude")
        else:
            tts.speak("GPS fix not available")
        return

    # Fallback — if VLM available, ask it with context
    if vlm and vlm.available:
        frame = _get("latest_frame")
        if frame is not None:
            _update("mode", "vlm")
            answer = vlm.describe(frame, question=text)
            tts.speak(answer)
            _update("mode", "detection")


def _extract_destination(text: str) -> str | None:
    for trigger in ("navigate to", "take me to", "go to", "directions to"):
        if trigger in text:
            return text.split(trigger, 1)[1].strip()
    return None


# ── button callbacks ──────────────────────────────────────────────────────────

def _make_llm_callback(vlm: VLMProcessor | None, tts: VoiceOutput, db: Database):
    def callback():
        db.log_event("llm_button", "LLM button pressed")
        frame = _get("latest_frame")
        if frame is None:
            tts.speak("No camera frame available")
            return
        if vlm and vlm.available:
            _update("mode", "vlm")
            tts.speak("Describing the scene")
            answer = vlm.describe(frame, question=config.VLM_DEFAULT_QUESTION)
            tts.speak(answer)
            _update("mode", "detection")
        else:
            tts.speak(_get("last_detection") or "Nothing detected")
    return callback


def _make_sos_callback(sim808: SIM808, tts: VoiceOutput, db: Database,
                       sos_number: str = ""):
    def callback():
        db.log_event("sos", "SOS button pressed")
        tts.speak("Sending SOS alert")
        coords = _get("gps_coords")
        if coords:
            msg = (f"SOS! EchoSense user needs help. "
                   f"Location: https://maps.google.com/?q={coords[0]},{coords[1]}")
        else:
            msg = "SOS! EchoSense user needs help. No GPS fix available."
        if sos_number and sim808:
            sim808.send_sms(sos_number, msg)
        log.warning("SOS triggered: %s", msg)
    return callback


def _make_power_callback(tts: VoiceOutput):
    def callback():
        tts.speak("Shutting down EchoSense")
        time.sleep(1.5)
        _shutdown_event.set()
    return callback


# ── main ──────────────────────────────────────────────────────────────────────

def main():
    log.info("═══ EchoSense starting ═══")

    # ── hardware init ─────────────────────────────────────────────────────────
    lidar = TFLunaLIDAR(port=config.LIDAR_PORT, baud_rate=config.LIDAR_BAUD)
    lidar_ok = lidar.connect()
    if lidar_ok:
        lidar.start()

    buzzer    = BuzzerController(config.BUZZER_1_PIN, config.BUZZER_2_PIN)
    vibration = VibrationMotor(config.VIBRATION_PIN)
    leds      = LEDController(config.LED_1_PIN, config.LED_2_PIN)

    sim808 = SIM808(port=config.SIM808_PORT, baud=config.SIM808_BAUD)
    sim808.connect()
    gps = GPSManager(sim808)
    gps.start()

    # ── AI init ───────────────────────────────────────────────────────────────
    log.info("Loading object detector…")
    detector = ObjectDetector(config.YOLO_HEF_PATH, config.DETECTION_CONF, config.DETECTION_IOU)

    log.info("Initialising TTS…")
    tts = VoiceOutput(piper_models_dir=config.PIPER_MODELS_DIR)

    log.info("Initialising VLM (subprocess)…")
    vlm = VLMProcessor(
        hef_path=config.VLM_HEF_PATH,
        system_prompt=config.VLM_SYSTEM_PROMPT,
    )

    # VoiceInput needs the Hailo VDevice — create after detector to avoid conflicts
    log.info("Initialising voice input (Whisper)…")
    try:
        from hailo_platform import VDevice
        from hailo_apps.python.core.common.defines import SHARED_VDEVICE_GROUP_ID
        params = VDevice.create_params()
        params.group_id = SHARED_VDEVICE_GROUP_ID
        shared_vdevice = VDevice(params)
        voice_in = VoiceInput(shared_vdevice, config.WHISPER_HEF_PATH)
    except Exception as e:
        log.warning("Voice input init failed: %s", e)
        voice_in = None
        shared_vdevice = None

    # ── navigation ────────────────────────────────────────────────────────────
    navigator = Navigator()

    # ── server ────────────────────────────────────────────────────────────────
    db = Database()
    stream = MJPEGStream()

    # Build the async event loop for the server + GPS WebSocket broadcast
    server_loop = asyncio.new_event_loop()

    app = create_app(stream, db, _state)

    # ── buttons ───────────────────────────────────────────────────────────────
    buttons = ButtonController(
        llm_pin=config.BUTTON_LLM_PIN,
        sos_pin=config.BUTTON_SOS_PIN,
        power_pin=config.BUTTON_POWER_PIN,
    )
    buttons.on_llm   = _make_llm_callback(vlm, tts, db)
    buttons.on_sos   = _make_sos_callback(sim808, tts, db)
    buttons.on_power = _make_power_callback(tts)

    # ── voice command wiring ──────────────────────────────────────────────────
    if voice_in:
        voice_in.on_transcription = lambda text: _dispatch_voice(
            text, tts, navigator, sim808, db, vlm
        )
        voice_in.start_vad()

    # ── signal handler ────────────────────────────────────────────────────────
    def _sig_handler(sig, frame):
        log.info("Signal %s received — shutting down", sig)
        _shutdown_event.set()

    signal.signal(signal.SIGINT,  _sig_handler)
    signal.signal(signal.SIGTERM, _sig_handler)

    # ── start server thread ───────────────────────────────────────────────────
    run_server(app, config.SERVER_HOST, config.SERVER_PORT)

    # ── start GPS thread ──────────────────────────────────────────────────────
    broadcast_fn = getattr(app.state, "broadcast_gps", None)
    gps_t = threading.Thread(
        target=gps_thread,
        args=(gps, db, navigator, tts, vibration, server_loop, broadcast_fn),
        daemon=True, name="gps",
    )
    gps_t.start()

    # ── start detection thread ────────────────────────────────────────────────
    det_t = threading.Thread(
        target=detection_thread,
        args=(detector, lidar if lidar_ok else None, tts, buzzer, vibration, stream),
        daemon=True, name="detection",
    )
    det_t.start()

    # ── startup announcement ──────────────────────────────────────────────────
    tts.speak("EchoSense is ready")
    leds.on(0.5)
    db.log_event("startup", "EchoSense started")
    log.info("All systems online. Caregiver dashboard → http://localhost:%d", config.SERVER_PORT)

    # ── main loop: keep alive until shutdown ──────────────────────────────────
    try:
        while not _shutdown_event.is_set():
            _shutdown_event.wait(timeout=1.0)
            # Push status to Firebase periodically
            coords = _get("gps_coords")
            db.firebase_update_status({
                "gps": list(coords) if coords else None,
                "lidar_cm": _get("lidar_distance"),
                "mode": _get("mode"),
                "navigating": _get("navigating"),
                "nav_destination": _get("nav_destination"),
                "last_detection": _get("last_detection"),
                "ts": time.time(),
            })
    except KeyboardInterrupt:
        _shutdown_event.set()

    # ── cleanup ───────────────────────────────────────────────────────────────
    log.info("Shutting down…")
    _shutdown_event.set()

    if voice_in:
        voice_in.stop()
    if shared_vdevice:
        try:
            shared_vdevice.release()
        except Exception:
            pass

    detector.close()
    vlm.close()
    sim808.stop()
    if lidar_ok:
        lidar.stop()
    buzzer.close()
    vibration.close()
    leds.close()
    buttons.close()

    db.log_event("shutdown", "EchoSense stopped")
    log.info("EchoSense stopped cleanly")


if __name__ == "__main__":
    main()
