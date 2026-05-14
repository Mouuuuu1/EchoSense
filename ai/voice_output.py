"""
Text-to-speech output.
Uses Piper TTS (via hailo-apps) if available, falls back to espeak.
"""

import subprocess
import threading
from utils.logger import get_logger

log = get_logger(__name__)


class VoiceOutput:
    """Non-blocking TTS. New speech cancels in-progress speech."""

    def __init__(self, piper_models_dir: str | None = None):
        self._lock = threading.Lock()
        self._speaking = threading.Event()
        self._piper: object | None = None
        self._audio_player = None

        self._init_piper(piper_models_dir)

    def _init_piper(self, models_dir: str | None):
        try:
            import sys
            sys.path.insert(0, "/home/echosense/hailo-apps")
            from hailo_apps.python.gen_ai_apps.gen_ai_utils.voice_processing.text_to_speech import TextToSpeechProcessor
            self._piper = TextToSpeechProcessor()
            log.info("TTS: using Piper via hailo-apps")
        except (Exception, SystemExit) as e:
            log.info("Piper TTS not available (%s) — using espeak", e)
            self._piper = None

    # ── public ────────────────────────────────────────────────────────────────

    def speak(self, text: str, interrupt: bool = True):
        """Speak text in a background thread."""
        if interrupt:
            self._interrupt()
        t = threading.Thread(target=self._speak_worker, args=(text,), daemon=True)
        t.start()

    def speak_blocking(self, text: str):
        self._interrupt()
        self._speak_worker(text)

    def stop(self):
        self._interrupt()

    # ── internal ──────────────────────────────────────────────────────────────

    def _interrupt(self):
        if self._piper:
            try:
                self._piper.interrupt()
            except Exception:
                pass

    def _speak_worker(self, text: str):
        if self._speaking.is_set():
            return
        self._speaking.set()
        try:
            if self._piper:
                self._piper.speak(text)
            else:
                subprocess.run(
                    ["espeak", "-s", "160", "-a", "200", text],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    timeout=30,
                )
        except Exception as e:
            log.debug("TTS error: %s", e)
        finally:
            self._speaking.clear()
