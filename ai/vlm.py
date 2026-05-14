"""
Vision-Language Model (Qwen2-VL-2B) on Hailo AI HAT.
Used for:
  - LLM button: "What do you see?" scene description
  - Answering spoken questions about the current camera frame
"""

import sys
import time
import multiprocessing as mp
import numpy as np
from utils.logger import get_logger

sys.path.insert(0, "/home/echosense/hailo-apps")
log = get_logger(__name__)


class VLMProcessor:
    """
    Runs Hailo VLM inference in a separate process so it doesn't block
    the detection thread and can safely acquire its own VDevice.
    """

    def __init__(self, hef_path: str, system_prompt: str = "",
                 max_tokens: int = 150, temperature: float = 0.1):
        self._hef_path = hef_path
        self._system_prompt = system_prompt
        self._max_tokens = max_tokens
        self._temperature = temperature

        self._req_q: mp.Queue = mp.Queue()
        self._res_q: mp.Queue = mp.Queue()
        self._proc: mp.Process | None = None
        self._ready = False

        self._start_worker()

    def _start_worker(self):
        self._proc = mp.Process(
            target=_vlm_worker,
            args=(self._req_q, self._res_q, self._hef_path,
                  self._max_tokens, self._temperature),
            daemon=True,
            name="vlm-worker",
        )
        self._proc.start()
        # Wait for worker ready signal
        try:
            sig = self._res_q.get(timeout=60)
            if sig == "READY":
                self._ready = True
                log.info("VLM worker ready")
        except Exception as e:
            log.warning("VLM worker did not start: %s", e)

    @property
    def available(self) -> bool:
        return self._ready and self._proc is not None and self._proc.is_alive()

    def describe(self, frame: np.ndarray, question: str | None = None) -> str:
        """
        Run VLM on a BGR frame and return the text response.
        Blocks until inference completes (may take several seconds).
        """
        if not self.available:
            return "VLM not available"

        user_prompt = question or "What do you see? Describe the scene for a visually impaired person."
        prompts = {
            "system": self._system_prompt,
            "user": user_prompt,
        }
        self._req_q.put({"image": frame, "prompts": prompts})
        try:
            result = self._res_q.get(timeout=60)
            if result.get("error"):
                log.warning("VLM error: %s", result["error"])
                return "Could not analyse the scene"
            answer = result.get("answer", "")
            return answer.strip()
        except Exception as e:
            log.warning("VLM timeout or error: %s", e)
            return "Scene analysis timed out"

    def close(self):
        if self._proc and self._proc.is_alive():
            self._req_q.put(None)
            self._proc.join(timeout=5)


# ── worker process ─────────────────────────────────────────────────────────────

def _vlm_worker(req_q: mp.Queue, res_q: mp.Queue, hef_path: str,
                max_tokens: int, temperature: float):
    """Runs inside a subprocess — owns its own VDevice + VLM instance."""
    try:
        sys.path.insert(0, "/home/echosense/hailo-apps")
        import cv2
        from hailo_platform import VDevice
        from hailo_platform.genai import VLM
        from hailo_apps.python.core.common.defines import SHARED_VDEVICE_GROUP_ID

        params = VDevice.create_params()
        params.group_id = SHARED_VDEVICE_GROUP_ID
        vdevice = VDevice(params)
        vlm = VLM(vdevice, hef_path)
        res_q.put("READY")

        while True:
            item = req_q.get()
            if item is None:
                break
            try:
                frame = item["image"]
                prompts = item["prompts"]
                rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                answer = ""
                t0 = time.time()
                for token in vlm.generate(
                    image=rgb,
                    system_prompt=prompts.get("system", ""),
                    user_prompt=prompts.get("user", ""),
                    max_tokens=max_tokens,
                    temperature=temperature,
                ):
                    answer += token
                elapsed = time.time() - t0
                res_q.put({"answer": answer, "time": elapsed, "error": None})
            except Exception as e:
                res_q.put({"answer": "", "error": str(e)})

        vlm.release()
        vdevice.release()

    except Exception as e:
        res_q.put({"answer": "", "error": str(e)})
