"""TF-Luna single-point LiDAR — serial reader thread."""

import threading
import time
import serial
from utils.logger import get_logger

log = get_logger(__name__)


class TFLunaLIDAR:
    def __init__(self, port: str, baud_rate: int = 115200):
        self.port = port
        self.baud_rate = baud_rate
        self._serial: serial.Serial | None = None
        self._distance = 0
        self._strength = 0
        self._temperature = 0.0
        self._lock = threading.Lock()
        self._running = False
        self._thread: threading.Thread | None = None

    # ── public ────────────────────────────────────────────────────────────────

    def connect(self) -> bool:
        for candidate in (self.port, "/dev/serial0", "/dev/ttyAMA0"):
            try:
                self._serial = serial.Serial(candidate, self.baud_rate, timeout=0.1)
                self._serial.reset_input_buffer()
                self.port = candidate
                log.info("TF-Luna connected on %s", candidate)
                return True
            except serial.SerialException:
                continue
        log.warning("TF-Luna not found on any port — running without LiDAR")
        return False

    def start(self) -> bool:
        if not self._serial or not self._serial.isOpen():
            return False
        self._running = True
        self._thread = threading.Thread(target=self._read_loop, daemon=True, name="lidar")
        self._thread.start()
        return True

    def stop(self):
        self._running = False
        if self._thread:
            self._thread.join(timeout=1.0)
        if self._serial and self._serial.isOpen():
            self._serial.close()

    @property
    def distance(self) -> int:
        with self._lock:
            return self._distance

    @property
    def all_data(self) -> tuple[int, int, float]:
        with self._lock:
            return self._distance, self._strength, self._temperature

    # ── internal ──────────────────────────────────────────────────────────────

    def _read_loop(self):
        while self._running:
            try:
                if self._serial.in_waiting >= 9:
                    raw = self._serial.read(9)
                    if raw[0] == 0x59 and raw[1] == 0x59:
                        dist = raw[2] + raw[3] * 256
                        strength = raw[4] + raw[5] * 256
                        temp = (raw[6] + raw[7] * 256) / 8.0 - 256
                        with self._lock:
                            self._distance = dist
                            self._strength = strength
                            self._temperature = temp
                    self._serial.reset_input_buffer()
            except Exception:
                pass
            time.sleep(0.01)
