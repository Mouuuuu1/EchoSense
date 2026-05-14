"""
MJPEG camera stream helper.
Holds the latest frame so FastAPI can serve it efficiently.
"""

import cv2
import threading
import numpy as np
from utils.logger import get_logger

log = get_logger(__name__)


class MJPEGStream:
    """Thread-safe JPEG frame buffer for MJPEG streaming."""

    def __init__(self, quality: int = 70):
        self._quality = quality
        self._frame: bytes | None = None
        self._lock = threading.Lock()
        self._condition = threading.Condition(self._lock)

    def push_frame(self, frame: np.ndarray):
        """Called from the detection thread with the latest BGR frame."""
        ok, buf = cv2.imencode(
            ".jpg", frame,
            [cv2.IMWRITE_JPEG_QUALITY, self._quality]
        )
        if not ok:
            return
        with self._condition:
            self._frame = buf.tobytes()
            self._condition.notify_all()

    def get_frame(self) -> bytes | None:
        with self._lock:
            return self._frame

    async def generate_frames(self):
        """Async generator for FastAPI StreamingResponse."""
        import asyncio
        boundary = b"--frame\r\nContent-Type: image/jpeg\r\n\r\n"
        while True:
            frame = self.get_frame()
            if frame:
                yield boundary + frame + b"\r\n"
            await asyncio.sleep(1.0 / 10)   # ~10 fps
