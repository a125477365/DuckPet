"""视觉适配器：人脸识别、人体跟踪（跟随）、开放词汇物体检测、避障防跌。

全部懒加载，缺依赖时对应能力自动关闭，其余功能不受影响。
实现 VisionFacade 接口供行为层调用。
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

from ..core.registry import Person, PersonRegistry
from .base import Detection

if TYPE_CHECKING:
    pass

CAMERA_HFOV_DEG = 62.2   # 树莓派摄像头水平视场角（用于像素->方位角换算）


def _bearing_of_box(x1: float, x2: float, img_width: int) -> float:
    center = (x1 + x2) / 2
    return (center / img_width - 0.5) * CAMERA_HFOV_DEG


class FaceEngine:
    """InsightFace buffalo_sc：SCRFD 检测 + MobileFaceNet 识别，CPU 可跑。
    注意：模型权重仅授权非商业用途。"""

    def __init__(self, registry: PersonRegistry, threshold: float = 0.45):
        from insightface.app import FaceAnalysis  # noqa: PLC0415

        self.registry = registry
        self.threshold = threshold
        self.app = FaceAnalysis(name="buffalo_sc", providers=["CPUExecutionProvider"])
        self.app.prepare(ctx_id=0, det_size=(320, 320))

    def identify(self, frame) -> list[tuple[Person | None, float]]:
        """返回画面中每张脸对应的 (人, 方位角)。"""
        h, w = frame.shape[:2]
        out = []
        for face in self.app.get(frame):
            emb = list(map(float, face.normed_embedding))
            person, _ = self.registry.match_face(emb, self.threshold)
            out.append((person, _bearing_of_box(*face.bbox[[0, 2]], w)))
        return out

    def embedding_of(self, frame) -> list[float] | None:
        faces = self.app.get(frame)
        if not faces:
            return None
        return list(map(float, faces[0].normed_embedding))


class PersonTracker:
    """YOLO 检测 + BoTSORT(OSNet ReID) 跟踪：跟随目标丢失后靠 ReID 找回。"""

    def __init__(self, registry: PersonRegistry):
        from boxmot import BoTSORT  # noqa: PLC0415
        from ultralytics import YOLO  # noqa: PLC0415

        self.registry = registry
        self.detector = YOLO("yolo11n.pt")
        self.tracker = BoTSORT(reid_weights="osnet_x0_25_msmt17.pt", device="cpu")
        self._targets: dict[str, int] = {}   # person.name -> track_id

    def person_bearing(self, frame, person: Person) -> float | None:
        results = self.detector.predict(frame, classes=[0], verbose=False)[0]
        if results.boxes is None or len(results.boxes) == 0:
            return None
        dets = results.boxes.xyxy.cpu().numpy()
        conf = results.boxes.conf.cpu().numpy()
        cls = results.boxes.cls.cpu().numpy()
        import numpy as np  # noqa: PLC0415

        tracks = self.tracker.update(
            np.column_stack([dets, conf, cls]), frame)
        w = frame.shape[1]
        tid = self._targets.get(person.name)
        for trk in tracks:
            x1, y1, x2, y2, track_id = trk[:5]
            if tid is None or int(track_id) == tid:
                self._targets[person.name] = int(track_id)
                return _bearing_of_box(x1, x2, w)
        return None


class ObjectFinder:
    """开放词汇物体检测：YOLO-World（本地低频调用）。
    球直接用 COCO 的 sports ball 类（class 32），无需开放词汇。"""

    def __init__(self):
        from ultralytics import YOLO  # noqa: PLC0415

        self._coco = YOLO("yolo11n.pt")
        self._world = None

    def _world_model(self):
        if self._world is None:
            from ultralytics import YOLO  # noqa: PLC0415

            self._world = YOLO("yolov8s-worldv2.pt")
        return self._world

    def find_object(self, frame, prompt: str) -> Detection | None:
        w = frame.shape[1]
        if prompt == "sports ball":
            res = self._coco.predict(frame, classes=[32], verbose=False)[0]
        else:
            model = self._world_model()
            model.set_classes([prompt])
            res = model.predict(frame, verbose=False)[0]
        if res.boxes is None or len(res.boxes) == 0:
            return None
        box = max(res.boxes, key=lambda b: float(b.conf))
        x1, y1, x2, y2 = map(float, box.xyxy[0])
        area = (x2 - x1) * (y2 - y1) / (frame.shape[0] * frame.shape[1])
        size = "large" if area > 0.15 else "small"
        return Detection(label=prompt, bearing_deg=_bearing_of_box(x1, x2, w),
                         distance_m=None, size=size)


class SafetyEye:
    """防跌落：VL53L0X ToF（朝下）为主；OpenCV DIS 光流辅助检测前方障碍。"""

    def __init__(self, use_tof: bool = True):
        self._tofs = []
        if use_tof:
            try:
                import board  # noqa: PLC0415
                import busio  # noqa: PLC0415
                import adafruit_vl53l0x  # noqa: PLC0415

                i2c = busio.I2C(board.SCL, board.SDA)
                self._tofs.append(adafruit_vl53l0x.VL53L0X(i2c))
            except (ImportError, NotImplementedError, RuntimeError):
                self._tofs = []
        self._prev_gray = None

    def cliff_detected(self) -> bool:
        for tof in self._tofs:
            try:
                if tof.range > 200:   # 距地面突然变远 = 悬空
                    return True
            except (OSError, RuntimeError):
                continue
        return False

    def obstacle_ahead(self, frame) -> bool:
        """光流发散检测：前方物体快速逼近。"""
        import cv2  # noqa: PLC0415

        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        gray = cv2.resize(gray, (160, 120))
        if self._prev_gray is None:
            self._prev_gray = gray
            return False
        flow = cv2.calcOpticalFlowFarneback(self._prev_gray, gray, None,
                                            0.5, 2, 15, 3, 5, 1.2, 0)
        self._prev_gray = gray
        import numpy as np  # noqa: PLC0415

        mag = np.linalg.norm(flow, axis=2)
        center = mag[40:80, 60:100]
        return bool(center.mean() > 2.5)


class RealVision:
    """组合上面的适配器，实现行为层依赖的 VisionFacade。"""

    def __init__(self, registry: PersonRegistry, camera, face_threshold: float = 0.45):
        self.registry = registry
        self.camera = camera              # callable -> frame (numpy BGR)
        self.faces = self._lazy(lambda: FaceEngine(registry, face_threshold))
        self.tracker = self._lazy(PersonTracker, registry)
        self.objects = self._lazy(ObjectFinder)
        self.safety = self._lazy(SafetyEye)

    @staticmethod
    def _lazy(factory, *args):
        try:
            return factory(*args)
        except ImportError as e:
            print(f"[视觉] 适配器不可用（{e}），对应能力关闭")
            return None

    def find_object(self, prompt: str) -> Detection | None:
        if self.objects is None:
            return None
        return self.objects.find_object(self.camera(), prompt)

    def person_bearing(self, person: Person) -> float | None:
        if self.tracker is None:
            return None
        return self.tracker.person_bearing(self.camera(), person)

    def visible_people(self) -> list[tuple[Person | None, float]]:
        if self.faces is None:
            return []
        try:
            return self.faces.identify(self.camera())
        except Exception:  # noqa: BLE001 - 感知层异常不应打挂行为循环
            return []

    def poll_safety(self) -> str | None:
        if self.safety is None:
            return None
        if self.safety.cliff_detected():
            return "cliff"
        return None


class CameraSource:
    """摄像头封装：默认 OpenCV VideoCapture；树莓派上可换 picamzero。"""

    def __init__(self, index: int = 0):
        import cv2  # noqa: PLC0415

        self._cap = cv2.VideoCapture(index)
        self._last = None
        self._last_at = 0.0

    def __call__(self):
        now = time.time()
        if now - self._last_at < 0.15 and self._last is not None:
            return self._last
        ok, frame = self._cap.read()
        if ok:
            self._last = frame
            self._last_at = now
        return self._last
