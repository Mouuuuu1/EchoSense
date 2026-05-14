"""Dual-buzzer controller via GPIO."""

import threading
import time
from gpiozero import Buzzer as _GZBuzzer
from gpiozero.pins.lgpio import LGPIOFactory
from gpiozero import Device
from utils.logger import get_logger

Device.pin_factory = LGPIOFactory()
log = get_logger(__name__)


class BuzzerController:
    """Controls two buzzers with alert patterns."""

    def __init__(self, pin1: int, pin2: int):
        self._buzzers = []
        for pin in (pin1, pin2):
            try:
                self._buzzers.append(_GZBuzzer(pin))
            except Exception as e:
                log.warning("Buzzer on GPIO %d unavailable: %s", pin, e)
        self._lock = threading.Lock()
        self._alert_thread: threading.Thread | None = None
        self._stop_event = threading.Event()

    # ── patterns ──────────────────────────────────────────────────────────────

    def beep(self, count: int = 1, on_ms: int = 100, off_ms: int = 100):
        """Single or repeated beep (blocking)."""
        for _ in range(count):
            self._set(True)
            time.sleep(on_ms / 1000)
            self._set(False)
            time.sleep(off_ms / 1000)

    def alert_proximity(self, distance_cm: int):
        """
        Non-blocking proximity alert: faster beeps as distance shrinks.
        Cancels any ongoing alert before starting a new one.
        """
        self._stop_alert()
        interval = max(0.08, distance_cm / 1500)   # 80 ms … 1 s
        self._stop_event.clear()
        self._alert_thread = threading.Thread(
            target=self._pulse_loop, args=(interval,), daemon=True, name="buzzer-alert"
        )
        self._alert_thread.start()

    def stop_alert(self):
        self._stop_alert()
        self._set(False)

    def off(self):
        self._set(False)

    def close(self):
        self.stop_alert()
        for b in self._buzzers:
            try:
                b.close()
            except Exception:
                pass

    # ── internal ──────────────────────────────────────────────────────────────

    def _set(self, on: bool):
        with self._lock:
            for b in self._buzzers:
                try:
                    b.on() if on else b.off()
                except Exception:
                    pass

    def _stop_alert(self):
        self._stop_event.set()
        if self._alert_thread and self._alert_thread.is_alive():
            self._alert_thread.join(timeout=0.5)

    def _pulse_loop(self, interval: float):
        while not self._stop_event.is_set():
            self._set(True)
            time.sleep(min(interval, 0.05))
            self._set(False)
            self._stop_event.wait(timeout=interval)
