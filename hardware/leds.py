"""Dual LED controller with PWM dimming."""

from gpiozero import PWMLED
from gpiozero.pins.lgpio import LGPIOFactory
from gpiozero import Device
from utils.logger import get_logger

Device.pin_factory = LGPIOFactory()
log = get_logger(__name__)


class LEDController:
    """Controls two PWM LEDs (dark-assist lighting)."""

    def __init__(self, pin1: int, pin2: int):
        self._leds = []
        for pin in (pin1, pin2):
            try:
                self._leds.append(PWMLED(pin))
                log.info("LED on GPIO %d", pin)
            except Exception as e:
                log.warning("LED on GPIO %d unavailable: %s", pin, e)

    def on(self, brightness: float = 1.0):
        """Turn both LEDs on at given brightness (0.0–1.0)."""
        brightness = max(0.0, min(1.0, brightness))
        for led in self._leds:
            try:
                led.value = brightness
            except Exception:
                pass

    def off(self):
        for led in self._leds:
            try:
                led.off()
            except Exception:
                pass

    def dim(self):
        self.on(0.3)

    def close(self):
        self.off()
        for led in self._leds:
            try:
                led.close()
            except Exception:
                pass
