"""
GPS module — thin wrapper around hardware.sim808.SIM808.
Provides a clean interface to the rest of the system.
"""

from __future__ import annotations
from hardware.sim808 import SIM808, GPSFix
from utils.logger import get_logger

log = get_logger(__name__)


class GPSManager:
    """
    High-level GPS access.  Delegates to SIM808 for the actual hardware.
    Exposes the latest fix and helpers for the navigation layer.
    """

    def __init__(self, sim808: SIM808):
        self._sim = sim808

    def start(self) -> bool:
        return self._sim.start_gps()

    def stop(self):
        pass   # SIM808.stop() is called by main orchestrator

    @property
    def fix(self) -> GPSFix | None:
        return self._sim.fix

    @property
    def coords(self) -> tuple[float, float] | None:
        """Returns (lat, lon) or None if no fix."""
        f = self.fix
        if f and f.valid:
            return f.lat, f.lon
        return None

    def coords_str(self) -> str:
        c = self.coords
        if c:
            return f"{c[0]:.6f},{c[1]:.6f}"
        return "No GPS fix"
