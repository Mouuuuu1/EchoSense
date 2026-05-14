"""
YOLOv8s object detector on Hailo AI HAT.
Extracted and cleaned from the original object_detection.py.
"""

import cv2
import numpy as np
from pathlib import Path
from hailo_platform import (
    HEF, VDevice, InferVStreams, ConfigureParams,
    InputVStreamParams, OutputVStreamParams, FormatType,
)
from utils.logger import get_logger

log = get_logger(__name__)

COCO_CLASSES = [
    "person","bicycle","car","motorcycle","airplane","bus","train","truck","boat",
    "traffic light","fire hydrant","stop sign","parking meter","bench","bird","cat",
    "dog","horse","sheep","cow","elephant","bear","zebra","giraffe","backpack",
    "umbrella","handbag","tie","suitcase","frisbee","skis","snowboard","sports ball",
    "kite","baseball bat","baseball glove","skateboard","surfboard","tennis racket",
    "bottle","wine glass","cup","fork","knife","spoon","bowl","banana","apple",
    "sandwich","orange","broccoli","carrot","hot dog","pizza","donut","cake","chair",
    "couch","potted plant","bed","dining table","toilet","tv","laptop","mouse",
    "remote","keyboard","cell phone","microwave","oven","toaster","sink","refrigerator",
    "book","clock","vase","scissors","teddy bear","hair drier","toothbrush",
]


class ObjectDetector:
    def __init__(self, hef_path: str, conf: float = 0.4, iou: float = 0.45):
        self.conf = conf
        self.iou = iou
        self.input_size = (640, 640)
        self._use_infer_model = False
        self._cfg_ctx = None
        self._cfg_model = None

        self._load(hef_path)

    # ── loading ───────────────────────────────────────────────────────────────

    def _load(self, path: str):
        self._hef = HEF(path)
        self._target = VDevice()

        if hasattr(self._hef, "get_network_groups"):
            ng = self._hef.get_network_groups()[0]
            params = self._target.create_configure_params(self._hef)
            info = self._hef.get_input_vstream_infos()[0]
            self.input_size = (info.shape[1], info.shape[0])
            self._ng = ng
            self._ng_params = params
            self._in_params = InputVStreamParams.make_from_network_group(
                ng, quantized=False, format_type=FormatType.FLOAT32
            )
            self._out_params = OutputVStreamParams.make_from_network_group(
                ng, quantized=False, format_type=FormatType.FLOAT32
            )
        else:
            infer_model = self._target.create_infer_model(path)
            infer_model.input().set_format_type(FormatType.UINT8)
            infer_model.output().set_format_type(FormatType.FLOAT32)
            infer_model.output().set_nms_score_threshold(self.conf)
            infer_model.output().set_nms_iou_threshold(self.iou)
            self._cfg_ctx = infer_model.configure()
            self._cfg_model = self._cfg_ctx.__enter__()
            shape = infer_model.input().shape
            self.input_size = (shape[1], shape[0])
            self._infer_model = infer_model
            self._use_infer_model = True

        log.info("ObjectDetector loaded: %s  input=%s", Path(path).name, self.input_size)

    # ── inference ─────────────────────────────────────────────────────────────

    def detect(self, image: np.ndarray):
        """Returns (boxes, scores, class_ids)."""
        orig_shape = image.shape[:2]

        if self._use_infer_model:
            inp, _ = self._preprocess(image, uint8=True)
            bindings = self._cfg_model.create_bindings()
            bindings.input().set_buffer(inp)
            out_shape = self._infer_model.output().shape
            bindings.output().set_buffer(np.empty(out_shape, dtype=np.float32))
            self._cfg_model.run([bindings], 10000)
            out = bindings.output().get_buffer()
            if isinstance(out, list):
                return self._postprocess_nms(out, orig_shape)
            return self._postprocess([out], orig_shape, 1.0)

        inp, scale = self._preprocess(image, uint8=False)
        with InferVStreams(self._ng, self._in_params, self._out_params) as pipe:
            key = self._hef.get_input_vstream_infos()[0].name
            with self._target.configure(self._hef, self._ng_params):
                outputs = pipe.infer({key: inp})
        out = list(outputs.values())[0]
        return self._postprocess([out], orig_shape, scale)

    def close(self):
        if self._cfg_ctx:
            try:
                self._cfg_ctx.__exit__(None, None, None)
            except Exception:
                pass
            self._cfg_ctx = self._cfg_model = None

    # ── pre/post processing ───────────────────────────────────────────────────

    def _preprocess(self, image, uint8: bool):
        h, w = image.shape[:2]
        scale = min(self.input_size[0] / w, self.input_size[1] / h)
        nw, nh = int(w * scale), int(h * scale)
        resized = cv2.resize(image, (nw, nh), interpolation=cv2.INTER_LINEAR)
        padded = np.zeros((self.input_size[1], self.input_size[0], 3), dtype=np.uint8)
        padded[:nh, :nw] = resized
        rgb = cv2.cvtColor(padded, cv2.COLOR_BGR2RGB)
        if uint8:
            return np.expand_dims(rgb, 0), scale
        fp = rgb.astype(np.float32) / 255.0
        return np.expand_dims(fp.transpose(2, 0, 1), 0), scale

    def _postprocess(self, outputs, orig_shape, scale):
        preds = outputs[0][0].transpose()   # (8400, 84)
        boxes, scores, class_ids = [], [], []
        for pred in preds:
            cx, cy, pw, ph = pred[:4]
            cls_scores = pred[4:]
            cid = int(np.argmax(cls_scores))
            conf = float(cls_scores[cid])
            if conf < self.conf:
                continue
            x1 = int((cx - pw / 2) / scale)
            y1 = int((cy - ph / 2) / scale)
            x2 = int((cx + pw / 2) / scale)
            y2 = int((cy + ph / 2) / scale)
            x1, y1 = max(0, x1), max(0, y1)
            x2, y2 = min(orig_shape[1], x2), min(orig_shape[0], y2)
            if x2 > x1 and y2 > y1:
                boxes.append([x1, y1, x2, y2])
                scores.append(conf)
                class_ids.append(cid)
        if boxes:
            idxs = cv2.dnn.NMSBoxes(boxes, scores, self.conf, self.iou)
            if len(idxs):
                idxs = idxs.flatten()
                boxes = [boxes[i] for i in idxs]
                scores = [scores[i] for i in idxs]
                class_ids = [class_ids[i] for i in idxs]
        return boxes, scores, class_ids

    def _postprocess_nms(self, nms_out, orig_shape):
        h, w = orig_shape
        boxes, scores, class_ids = [], [], []
        for cid, dets in enumerate(nms_out):
            if dets is None:
                continue
            dets = np.asarray(dets)
            if dets.size == 0:
                continue
            for det in dets:
                if len(det) < 5:
                    continue
                y1, x1, y2, x2, sc = det[:5]
                if sc < self.conf:
                    continue
                if max(abs(x1), abs(y1), abs(x2), abs(y2)) <= 1.5:
                    x1, x2, y1, y2 = x1 * w, x2 * w, y1 * h, y2 * h
                x1, y1 = int(max(0, x1)), int(max(0, y1))
                x2, y2 = int(min(w, x2)), int(min(h, y2))
                if x2 > x1 and y2 > y1:
                    boxes.append([x1, y1, x2, y2])
                    scores.append(float(sc))
                    class_ids.append(cid)
        return boxes, scores, class_ids

    # ── helpers ───────────────────────────────────────────────────────────────

    def describe(self, boxes, scores, class_ids, img_w: int, img_h: int,
                 lidar_dist: int | None = None) -> str:
        if not boxes:
            return "Path is clear"
        zones: dict[str, list[str]] = {}
        for box, _, cid in zip(boxes, scores, class_ids):
            name = COCO_CLASSES[cid]
            cx = (box[0] + box[2]) / 2
            if cx < img_w / 3:
                loc = "left"
            elif cx < 2 * img_w / 3:
                loc = "center"
            else:
                loc = "right"
            zones.setdefault(name, []).append(loc)

        parts = []
        for name, locs in zones.items():
            if len(locs) == 1:
                parts.append(f"{name} on the {locs[0]}")
            else:
                parts.append(f"{len(locs)} {name}s")
        desc = "; ".join(parts)

        if lidar_dist and lidar_dist > 0:
            center_box = self._closest_to_center(boxes, scores, class_ids, img_w, img_h)
            if center_box is not None:
                cname = COCO_CLASSES[center_box[2]]
                if lidar_dist < 100:
                    desc += f". {cname} ahead is {lidar_dist} cm away"
                else:
                    desc += f". {cname} ahead is {lidar_dist/100:.1f} metres away"
        return desc

    def _closest_to_center(self, boxes, scores, class_ids, w, h):
        cx, cy = w / 2, h / 2
        best, best_dist = None, float("inf")
        for box, score, cid in zip(boxes, scores, class_ids):
            bx = (box[0] + box[2]) / 2
            by = (box[1] + box[3]) / 2
            d = ((bx - cx) ** 2 + (by - cy) ** 2) ** 0.5
            if d < best_dist:
                best_dist = d
                best = (box, score, cid)
        return best

    def draw(self, image, boxes, scores, class_ids) -> np.ndarray:
        for box, score, cid in zip(boxes, scores, class_ids):
            color = tuple(int(c) for c in np.random.RandomState(cid).randint(0, 255, 3))
            x1, y1, x2, y2 = box
            cv2.rectangle(image, (x1, y1), (x2, y2), color, 2)
            label = f"{COCO_CLASSES[cid]}: {score:.2f}"
            (lw, lh), base = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 1)
            cv2.rectangle(image, (x1, y1 - lh - base - 5), (x1 + lw, y1), color, -1)
            cv2.putText(image, label, (x1, y1 - base - 5),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)
        return image
