"""Three-button handler (LLM, SOS, Power) using gpiozero."""

from typing import Callable
from gpiozero import Button
from gpiozero.pins.lgpio import LGPIOFactory
from gpiozero import Device
from utils.logger import get_logger

Device.pin_factory = LGPIOFactory()
log = get_logger(__name__)


class ButtonController:
    """
    Registers callbacks for each button press.

    Usage:
        bc = ButtonController(llm_pin=16, sos_pin=20, power_pin=21)
        bc.on_llm   = lambda: ...
        bc.on_sos   = lambda: ...
        bc.on_power = lambda: ...
        bc.start()
    """

    def __init__(self, llm_pin: int, sos_pin: int, power_pin: int):
        self.on_llm:   Callable | None = None
        self.on_sos:   Callable | None = None
        self.on_power: Callable | None = None

        self._buttons: list[Button] = []
        self._pin_map = {
            llm_pin:   "_trigger_llm",
            sos_pin:   "_trigger_sos",
            power_pin: "_trigger_power",
        }

        for pin, method in self._pin_map.items():
            try:
                btn = Button(pin, pull_up=True, bounce_time=0.3)
                btn.when_pressed = getattr(self, method)
                self._buttons.append(btn)
                log.info("Button registered on GPIO %d → %s", pin, method)
            except Exception as e:
                log.warning("Button on GPIO %d unavailable: %s", pin, e)

    def _trigger_llm(self):
        log.info("LLM button pressed")
        if self.on_llm:
            self.on_llm()

    def _trigger_sos(self):
        log.info("SOS button pressed")
        if self.on_sos:
            self.on_sos()

    def _trigger_power(self):
        log.info("Power button pressed")
        if self.on_power:
            self.on_power()

    def close(self):
        for btn in self._buttons:
            try:
                btn.close()
            except Exception:
                pass
