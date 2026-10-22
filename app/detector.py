"""Hledání hulmanů (celé tělo) a jejich obličejů v obrázku pomocí YOLO-World.

YOLO-World je detektor s otevřeným slovníkem: třídy se zadávají textem, takže
není potřeba nic trénovat. Když detektor není dostupný nebo nic nenajde,
použije se celý obrázek.
"""
import logging
import threading
from dataclasses import dataclass, field

from PIL import Image

from .config import settings
from .device import resolve_device

log = logging.getLogger(__name__)


@dataclass
class Box:
    x1: float
    y1: float
    x2: float
    y2: float
    conf: float = 1.0

    @property
    def area(self) -> float:
        return max(0.0, self.x2 - self.x1) * max(0.0, self.y2 - self.y1)

    def contains_center(self, other: "Box") -> bool:
        cx, cy = (other.x1 + other.x2) / 2, (other.y1 + other.y2) / 2
        return self.x1 <= cx <= self.x2 and self.y1 <= cy <= self.y2

    def as_list(self) -> list[float]:
        return [round(self.x1, 1), round(self.y1, 1), round(self.x2, 1), round(self.y2, 1)]


@dataclass
class Animal:
    """Jeden hulman v obrázku: rámeček a výřezy podle druhu ("face" / "body").

    Když detektor nic nenajde, je celý obrázek brán jako "body" a fallback=True.
    """
    box: Box
    crops: dict = field(default_factory=dict)
    boxes: dict = field(default_factory=dict)
    fallback: bool = False


def crop(image: Image.Image, box: Box, pad: float = 0.05) -> Image.Image:
    w, h = image.size
    bw, bh = box.x2 - box.x1, box.y2 - box.y1
    x1 = max(0, int(box.x1 - bw * pad))
    y1 = max(0, int(box.y1 - bh * pad))
    x2 = min(w, int(box.x2 + bw * pad))
    y2 = min(h, int(box.y2 + bh * pad))
    return image.crop((x1, y1, x2, y2))


def iou(a: Box, b: Box) -> float:
    ix = max(0.0, min(a.x2, b.x2) - max(a.x1, b.x1))
    iy = max(0.0, min(a.y2, b.y2) - max(a.y1, b.y1))
    inter = ix * iy
    union = a.area + b.area - inter
    return inter / union if union else 0.0


def nms(boxes: list[Box], thr: float = 0.5) -> list[Box]:
    kept: list[Box] = []
    for b in sorted(boxes, key=lambda b: b.conf, reverse=True):
        if all(iou(b, k) < thr for k in kept):
            kept.append(b)
    return kept


def group_animals(image: Image.Image, bodies: list[Box], faces: list[Box]) -> list[Animal]:
    """Přiřadí obličeje k tělům (střed obličeje leží v rámečku těla)."""
    bodies = nms(bodies)
    faces = nms(faces)
    img_area = image.size[0] * image.size[1]
    # Obecný detektor občas označí celé zvíře jako „obličej“. Velký „obličej“ bez těla bereme
    # jako tělo a „obličej“ téměř totožný s rámečkem těla zahodíme.
    if not bodies:
        big = [f for f in faces if f.area > 0.35 * img_area]
        bodies = big
        faces = [f for f in faces if f not in big]
    faces = [f for f in faces if all(iou(f, b) < 0.6 for b in bodies)]
    animals: list[Animal] = []
    for b in sorted(bodies, key=lambda b: b.area, reverse=True):
        a = Animal(box=b)
        a.crops["body"] = crop(image, b)
        a.boxes["body"] = b
        animals.append(a)
    for f in sorted(faces, key=lambda f: f.conf, reverse=True):
        owner = next((a for a in animals if "face" not in a.crops and a.box.contains_center(f)), None)
        if owner is None:
            owner = Animal(box=f)
            animals.append(owner)
        owner.crops["face"] = crop(image, f, pad=0.15)
        owner.boxes["face"] = f
    if not animals:
        w, h = image.size
        whole = Box(0, 0, w, h)
        animals.append(Animal(box=whole, crops={"body": image}, boxes={"body": whole}, fallback=True))
    return animals


class Detector:
    def __init__(self):
        self.available = False
        self.error = None
        self._lock = threading.Lock()
        if not settings.detector_enabled:
            self.error = "Detektor je vypnutý v nastavení."
            return
        try:
            from ultralytics import YOLOWorld

            weights = settings.detector_weights
            if weights == "auto":
                weights = "yolov8x-worldv2.pt" if resolve_device() == "cuda" else "yolov8s-worldv2.pt"
            local = settings.models_dir / weights
            self.model = YOLOWorld(str(local) if local.exists() else weights)
            self.classes = list(settings.body_classes) + list(settings.face_classes)
            self.model.set_classes(self.classes)
            self.weights = weights
            self.available = True
        except Exception as exc:  # noqa: BLE001 - aplikace má fungovat i bez detektoru
            self.error = f"Detektor se nepodařilo načíst: {exc}"
            log.warning(self.error)

    def detect(self, image: Image.Image) -> tuple[list[Box], list[Box]]:
        if not self.available:
            return [], []
        with self._lock:
            result = self.model.predict(image.convert("RGB"), conf=settings.detector_conf,
                                        device=resolve_device(), verbose=False)[0]
        bodies, faces = [], []
        n_body = len(settings.body_classes)
        for xyxy, conf, cls in zip(result.boxes.xyxy.tolist(), result.boxes.conf.tolist(),
                                   result.boxes.cls.tolist()):
            box = Box(*xyxy, conf=conf)
            (bodies if int(cls) < n_body else faces).append(box)
        return bodies, faces

    def animals(self, image: Image.Image) -> list[Animal]:
        bodies, faces = self.detect(image)
        return group_animals(image, bodies, faces)
