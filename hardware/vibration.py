"""Vibration motor controller via GPIO."""

import threading
import time
from gpiozero import OutputDevice
from gpiozero.pins.lgpio import LGPIOFactory
from gpiozero import Device
from utils.logger import get_logger

Device.pin_factory = LGPIOFactory()
log = get_logger(__name__)


class VibrationMotor:
    """
    Patterns:
      - single pulse  → obstacle ahead
      - double pulse  → turn instruction
      - long pulse    → SOS confirmation
    """

    def __init__(self, pin: int):
        self._motor = None
        try:
            self._motor = OutputDevice(pin, active_high=True, initial_value=False)
            log.info("Vibration motor on GPIO %d", pin)
        except Exception as e:
            log.warning("Vibration motor on GPIO %d unavailable: %s", pin, e)
        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

    # ── patterns ──────────────────────────────────────────────────────────────

    def pulse(self, count: int = 1, on_ms: int = 200, off_ms: int = 100):
        """Blocking pulse pattern."""
        for _ in range(count):
            self._set(True)
            time.sleep(on_ms / 1000)
            self._set(False)
            time.sleep(off_ms / 1000)

    def navigate_left(self):
        """Two short pulses — turn left."""
        threading.Thread(target=self.pulse, args=(2, 150, 80), daemon=True).start()

    def navigate_right(self):
        """Three short pulses — turn right."""
        threading.Thread(target=self.pulse, args=(3, 150, 80), daemon=True).start()

    def obstacle_warning(self):
        """Single firm pulse."""
        threading.Thread(target=self.pulse, args=(1, 250, 0), daemon=True).start()

    def sos_confirm(self):
        """Long pulse + two short."""
        threading.Thread(
            target=self.pulse, args=(1, 800, 200), daemon=True
        ).start()

    def off(self):
        self._set(False)

    def close(self):
        self._stop_event.set()
        self.off()
        if self._motor:
            try:
                self._motor.close()
            except Exception:
                pass

    # ── internal ──────────────────────────────────────────────────────────────

    def _set(self, on: bool):
        if not self._motor:
            return
        with self._lock:
            try:
                self._motor.on() if on else self._motor.off()
            except Exception:
                pass
