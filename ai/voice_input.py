"""
Speech-to-text input via Hailo Whisper.
Wraps the hailo-apps SpeechToTextProcessor.
"""

import sys
import numpy as np
import threading
from utils.logger import get_logger

log = get_logger(__name__)

sys.path.insert(0, "/home/echosense/hailo-apps")


class VoiceInput:
    """
    Listens for speech and transcribes it via Whisper on the Hailo chip.

    Usage (VAD-triggered):
        vi = VoiceInput(vdevice, whisper_hef_path)
        vi.on_transcription = lambda text: print(text)
        vi.start()

    Usage (manual):
        audio_np = vi.record_once(seconds=4)
        text = vi.transcribe(audio_np)
    """

    def __init__(self, vdevice, hef_path: str | None = None):
        self._vdevice = vdevice
        self._hef_path = hef_path
        self._stt = None
        self._recorder = None
        self._interaction = None
        self.on_transcription: callable | None = None
        self._running = False
        self._thread: threading.Thread | None = None

        self._init_stt()

    def _init_stt(self):
        try:
            from hailo_apps.python.gen_ai_apps.gen_ai_utils.voice_processing.speech_to_text import SpeechToTextProcessor
            from hailo_apps.python.gen_ai_apps.gen_ai_utils.voice_processing.audio_recorder import AudioRecorder
            self._stt = SpeechToTextProcessor(self._vdevice, self._hef_path)
            self._recorder = AudioRecorder()
            log.info("VoiceInput: Whisper STT ready")
        except Exception as e:
            log.warning("VoiceInput: Whisper not available: %s", e)

    # ── public ────────────────────────────────────────────────────────────────

    @property
    def available(self) -> bool:
        return self._stt is not None

    def transcribe(self, audio: np.ndarray) -> str:
        """Transcribe pre-recorded audio numpy array (float32, 16kHz mono)."""
        if not self._stt:
            return ""
        try:
            result = self._stt.transcribe(audio)
            return result.strip() if result else ""
        except Exception as e:
            log.debug("STT transcribe error: %s", e)
            return ""

    def record_once(self, seconds: float = 4.0) -> np.ndarray | None:
        """Record audio for a fixed duration and return numpy array."""
        if not self._recorder:
            return None
        try:
            return self._recorder.record(duration=seconds)
        except Exception as e:
            log.debug("Record error: %s", e)
            return None

    def start_vad(self):
        """Start continuous VAD-triggered listening in a background thread."""
        if not self._stt or not self._recorder:
            log.warning("VoiceInput: STT or recorder not available, skipping VAD")
            return
        self._running = True
        self._thread = threading.Thread(target=self._vad_loop, daemon=True, name="vad")
        self._thread.start()
        log.info("VoiceInput: VAD loop started")

    def stop(self):
        self._running = False
        if self._thread:
            self._thread.join(timeout=2)

    # ── internal ──────────────────────────────────────────────────────────────

    def _vad_loop(self):
        """Simple polling VAD: record in chunks and transcribe when speech detected."""
        try:
            from hailo_apps.python.gen_ai_apps.gen_ai_utils.voice_processing.vad import VAD
            vad = VAD()
        except Exception:
            vad = None

        import time
        while self._running:
            try:
                audio = self._recorder.record(duration=3.0)
                if audio is None:
                    time.sleep(0.1)
                    continue
                # Skip if mostly silence (simple energy check)
                energy = float(np.abs(audio).mean())
                if energy < 0.005:
                    continue
                text = self.transcribe(audio)
                if text and self.on_transcription:
                    self.on_transcription(text)
            except Exception as e:
                log.debug("VAD loop error: %s", e)
