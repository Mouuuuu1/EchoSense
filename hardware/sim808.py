"""
SIM808 GPS/GSM module driver.

Responsibilities:
  - Continuous GPS polling (thread-safe lat/lon)
  - Send SMS (SOS)
  - Make voice call (SOS)
"""

import threading
import time
import serial
from dataclasses import dataclass
from utils.logger import get_logger

log = get_logger(__name__)


@dataclass
class GPSFix:
    lat: float
    lon: float
    timestamp: str = ""
    valid: bool = True


class SIM808:
    def __init__(self, port: str, baud: int = 9600):
        self._port = port
        self._baud = baud
        self._ser: serial.Serial | None = None
        self._fix: GPSFix | None = None
        self._lock = threading.Lock()
        self._running = False
        self._thread: threading.Thread | None = None
        self._connected = False

    # ── connection ────────────────────────────────────────────────────────────

    def connect(self) -> bool:
        try:
            self._ser = serial.Serial(self._port, self._baud, timeout=1)
            time.sleep(0.5)
            resp = self._cmd("AT")
            if "OK" in resp:
                self._connected = True
                log.info("SIM808 connected on %s", self._port)
                return True
            log.warning("SIM808 AT check failed: %r", resp)
            return False
        except Exception as e:
            log.warning("SIM808 not available: %s", e)
            return False

    # ── GPS thread ────────────────────────────────────────────────────────────

    def start_gps(self) -> bool:
        if not self._connected:
            return False
        self._cmd("AT+CGNSPWR=1")   # power on GPS engine
        self._cmd("AT+CGNSTST=0")   # disable raw NMEA streaming
        self._running = True
        self._thread = threading.Thread(target=self._poll_loop, daemon=True, name="gps")
        self._thread.start()
        log.info("GPS polling started")
        return True

    def stop(self):
        self._running = False
        if self._thread:
            self._thread.join(timeout=3)
        if self._ser and self._ser.isOpen():
            self._ser.close()

    @property
    def fix(self) -> GPSFix | None:
        with self._lock:
            return self._fix

    # ── SMS / call ────────────────────────────────────────────────────────────

    def send_sms(self, number: str, message: str) -> bool:
        if not self._connected:
            log.warning("SIM808 not connected — SMS not sent")
            return False
        try:
            self._cmd('AT+CMGF=1')                            # text mode
            self._ser.write(f'AT+CMGS="{number}"\r\n'.encode())
            time.sleep(0.5)
            self._ser.write((message + chr(26)).encode())     # Ctrl-Z sends
            time.sleep(3)
            resp = self._ser.read_all().decode(errors="ignore")
            ok = "+CMGS" in resp
            log.info("SMS to %s: %s", number, "sent" if ok else "failed")
            return ok
        except Exception as e:
            log.error("SMS error: %s", e)
            return False

    def call(self, number: str):
        if not self._connected:
            return
        self._cmd(f"ATD{number};")

    # ── internal ──────────────────────────────────────────────────────────────

    def _poll_loop(self):
        while self._running:
            fix = self._parse_cgnsinf(self._cmd("AT+CGNSINF", wait=0.5))
            if fix:
                with self._lock:
                    self._fix = fix
            time.sleep(5)

    def _cmd(self, command: str, wait: float = 1.0) -> str:
        if not self._ser:
            return ""
        try:
            self._ser.reset_input_buffer()
            self._ser.write((command + "\r\n").encode())
            time.sleep(wait)
            return self._ser.read_all().decode("utf-8", errors="ignore")
        except Exception as e:
            log.debug("SIM808 cmd error: %s", e)
            return ""

    @staticmethod
    def _parse_cgnsinf(response: str) -> GPSFix | None:
        if "+CGNSINF: 1,1" not in response:
            return None
        try:
            data = response.split("+CGNSINF: ")[1].split(",")
            return GPSFix(
                lat=float(data[3]),
                lon=float(data[4]),
                timestamp=data[2],
                valid=True,
            )
        except (IndexError, ValueError):
            return None
