"""
EchoSense caregiver server — FastAPI.

Endpoints:
  GET  /              → Caregiver web dashboard
  GET  /stream        → MJPEG live camera feed
  WS   /ws/gps        → Real-time GPS WebSocket
  GET  /api/status    → Device status JSON
  GET  /api/locations → Recent location history
  GET  /api/events    → Recent event log
"""

import asyncio
import json
import threading
import time
from pathlib import Path

import uvicorn
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from server.stream import MJPEGStream
from server.database import Database
from utils.logger import get_logger

log = get_logger(__name__)

TEMPLATES_DIR = Path(__file__).parent / "templates"


def create_app(stream: MJPEGStream, db: Database, state: dict) -> FastAPI:
    """
    Factory — call once from main.py.
    `state` is the shared dict from the orchestrator.
    """
    app = FastAPI(title="EchoSense Caregiver", docs_url=None, redoc_url=None)

    # ── WebSocket connections ──────────────────────────────────────────────────
    _ws_clients: list[WebSocket] = []
    _ws_lock = threading.Lock()

    async def broadcast_gps(lat: float, lon: float):
        msg = json.dumps({"lat": lat, "lon": lon, "ts": time.time()})
        dead = []
        with _ws_lock:
            clients = list(_ws_clients)
        for ws in clients:
            try:
                await ws.send_text(msg)
            except Exception:
                dead.append(ws)
        with _ws_lock:
            for ws in dead:
                if ws in _ws_clients:
                    _ws_clients.remove(ws)

    # store broadcaster so main.py can call it
    app.state.broadcast_gps = broadcast_gps

    # ── routes ────────────────────────────────────────────────────────────────

    @app.get("/", response_class=HTMLResponse)
    async def dashboard():
        html = (TEMPLATES_DIR / "index.html").read_text()
        return HTMLResponse(content=html)

    @app.get("/stream")
    async def video_stream():
        return StreamingResponse(
            stream.generate_frames(),
            media_type="multipart/x-mixed-replace; boundary=frame",
        )

    @app.websocket("/ws/gps")
    async def gps_ws(ws: WebSocket):
        await ws.accept()
        with _ws_lock:
            _ws_clients.append(ws)
        try:
            while True:
                await ws.receive_text()   # keep connection alive
        except WebSocketDisconnect:
            with _ws_lock:
                if ws in _ws_clients:
                    _ws_clients.remove(ws)

    @app.get("/api/status")
    async def api_status():
        return {
            "ts": time.time(),
            "gps": state.get("gps_coords"),
            "lidar_cm": state.get("lidar_distance", 0),
            "mode": state.get("mode", "detection"),
            "navigating": state.get("navigating", False),
            "nav_destination": state.get("nav_destination"),
            "last_detection": state.get("last_detection", ""),
        }

    @app.get("/api/locations")
    async def api_locations():
        return db.recent_locations(100)

    @app.get("/api/events")
    async def api_events():
        return db.recent_events(50)

    return app


def run_server(app: FastAPI, host: str, port: int):
    """Start uvicorn in a daemon thread."""
    config = uvicorn.Config(app, host=host, port=port, log_level="warning")
    server = uvicorn.Server(config)

    def _run():
        asyncio.run(server.serve())

    t = threading.Thread(target=_run, daemon=True, name="uvicorn")
    t.start()
    log.info("Caregiver server at http://%s:%d", host, port)
    return t
