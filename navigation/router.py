"""
Turn-by-turn navigation using OSRM + Nominatim geocoding.

Flow:
  1. Geocode destination text → (lat, lon)
  2. Request route from current GPS fix → destination
  3. Parse steps into spoken instructions
  4. As user moves, determine which step they're on and announce transitions
"""

import math
import requests
from dataclasses import dataclass, field
from utils.logger import get_logger
import config

log = get_logger(__name__)


@dataclass
class NavStep:
    instruction: str
    distance_m: float
    lat: float
    lon: float


@dataclass
class Route:
    steps: list[NavStep] = field(default_factory=list)
    destination_name: str = ""
    total_distance_m: float = 0.0
    current_step: int = 0

    @property
    def done(self) -> bool:
        return self.current_step >= len(self.steps)

    @property
    def next_step(self) -> NavStep | None:
        if not self.done:
            return self.steps[self.current_step]
        return None


class Navigator:
    """Stateful turn-by-turn navigator."""

    def __init__(self):
        self._route: Route | None = None

    # ── public ────────────────────────────────────────────────────────────────

    def plan(self, origin: tuple[float, float], destination_text: str) -> Route | None:
        """
        Geocode destination and compute route from origin.
        Returns a Route or None on failure.
        """
        dest_coords = self._geocode(destination_text)
        if not dest_coords:
            log.warning("Could not geocode: %s", destination_text)
            return None

        route = self._osrm_route(origin, dest_coords)
        if route:
            route.destination_name = destination_text
            self._route = route
            log.info("Route planned to '%s': %d steps, %.0f m",
                     destination_text, len(route.steps), route.total_distance_m)
        return route

    def update(self, current_pos: tuple[float, float]) -> str | None:
        """
        Call this regularly with current GPS position.
        Returns a spoken instruction if the user reached a waypoint, else None.
        """
        if not self._route or self._route.done:
            return None

        step = self._route.next_step
        dist = _haversine(current_pos, (step.lat, step.lon))

        if dist <= config.WAYPOINT_RADIUS_M:
            self._route.current_step += 1
            if self._route.done:
                return f"You have arrived at {self._route.destination_name}"
            return self._route.next_step.instruction

        return None

    def current_instruction(self) -> str:
        if not self._route or self._route.done:
            return "Navigation ended"
        step = self._route.next_step
        return f"{step.instruction}, in {step.distance_m:.0f} metres"

    def cancel(self):
        self._route = None

    @property
    def active(self) -> bool:
        return self._route is not None and not self._route.done

    # ── geocoding ─────────────────────────────────────────────────────────────

    def _geocode(self, text: str) -> tuple[float, float] | None:
        try:
            r = requests.get(
                f"{config.NOMINATIM_URL}/search",
                params={"q": text, "format": "json", "limit": 1},
                headers={"User-Agent": "EchoSense/1.0"},
                timeout=10,
            )
            data = r.json()
            if data:
                return float(data[0]["lat"]), float(data[0]["lon"])
        except Exception as e:
            log.warning("Geocoding error: %s", e)
        return None

    # ── OSRM routing ──────────────────────────────────────────────────────────

    def _osrm_route(self, origin: tuple[float, float],
                    dest: tuple[float, float]) -> Route | None:
        olat, olon = origin
        dlat, dlon = dest
        url = (
            f"{config.OSRM_BASE_URL}/route/v1/foot/"
            f"{olon},{olat};{dlon},{dlat}"
            f"?steps=true&geometries=geojson&overview=false"
        )
        try:
            r = requests.get(url, timeout=15)
            data = r.json()
            if data.get("code") != "Ok":
                log.warning("OSRM error: %s", data.get("message"))
                return None

            leg = data["routes"][0]["legs"][0]
            steps = []
            for s in leg["steps"]:
                maneuver = s.get("maneuver", {})
                instruction = _osrm_instruction(maneuver, s.get("name", ""))
                loc = maneuver.get("location", [0, 0])   # [lon, lat]
                steps.append(NavStep(
                    instruction=instruction,
                    distance_m=s.get("distance", 0),
                    lat=loc[1],
                    lon=loc[0],
                ))

            return Route(
                steps=steps,
                total_distance_m=leg.get("distance", 0),
            )
        except Exception as e:
            log.warning("OSRM routing error: %s", e)
            return None


# ── helpers ───────────────────────────────────────────────────────────────────

def _haversine(a: tuple[float, float], b: tuple[float, float]) -> float:
    """Distance in metres between two (lat, lon) points."""
    R = 6_371_000
    lat1, lon1 = map(math.radians, a)
    lat2, lon2 = map(math.radians, b)
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    h = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return 2 * R * math.asin(math.sqrt(h))


_TURN_WORDS = {
    "turn": "Turn",
    "new name": "Continue onto",
    "depart": "Head",
    "arrive": "Arrive at",
    "merge": "Merge onto",
    "on ramp": "Take the ramp onto",
    "off ramp": "Take the exit onto",
    "fork": "Keep",
    "end of road": "Turn",
    "continue": "Continue on",
    "roundabout": "At the roundabout,",
    "rotary": "At the roundabout,",
    "roundabout turn": "At the roundabout, turn",
    "exit roundabout": "Exit the roundabout onto",
    "exit rotary": "Exit the roundabout onto",
    "notification": "Note:",
}


def _osrm_instruction(maneuver: dict, road_name: str) -> str:
    mtype = maneuver.get("type", "")
    modifier = maneuver.get("modifier", "")
    base = _TURN_WORDS.get(mtype, "Continue")
    parts = [base]
    if modifier:
        parts.append(modifier)
    if road_name:
        parts.append(f"onto {road_name}")
    return " ".join(parts)
