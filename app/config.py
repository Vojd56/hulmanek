"""Nastavení aplikace. Každou hodnotu lze přepsat proměnnou prostředí HULMANY_<NÁZEV>."""
import os
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _env(name, default, cast=str):
    value = os.environ.get(f"HULMANY_{name}")
    if value is None:
        return default
    if cast is bool:
        return value.lower() in ("1", "true", "yes", "ano")
    return cast(value)


@dataclass
class Settings:
    data_dir: Path = field(default_factory=lambda: Path(_env("DATA_DIR", str(ROOT / "data"))))
    models_dir: Path = field(default_factory=lambda: Path(_env("MODELS_DIR", str(ROOT / "models"))))

    # Model pro otisky. L-384 je přesnější (pro GPU), T-224 je rychlý (pro CPU).
    # "auto" vybere L-384, pokud je k dispozici CUDA, jinak T-224.
    embedder: str = field(default_factory=lambda: _env("EMBEDDER", "auto"))
    device: str = field(default_factory=lambda: _env("DEVICE", "auto"))

    # Detektor YOLO-World s textovými třídami. Vypnutím se porovnává celý obrázek.
    # "auto" = yolov8x-worldv2 na GPU, yolov8s-worldv2 na CPU.
    detector_enabled: bool = field(default_factory=lambda: _env("DETECTOR", True, bool))
    detector_weights: str = field(default_factory=lambda: _env("DETECTOR_WEIGHTS", "auto"))
    detector_conf: float = field(default_factory=lambda: _env("DETECTOR_CONF", 0.15, float))
    body_classes: tuple = ("langur", "monkey", "primate")
    face_classes: tuple = ("monkey face", "langur face")

    # Rozpoznávání
    unknown_threshold: float = field(default_factory=lambda: _env("THRESHOLD", 0.55, float))
    # váha obličeje proti tělu, když jsou k dispozici oba (hulmani mají obličeje dost podobné)
    face_weight: float = field(default_factory=lambda: _env("FACE_WEIGHT", 0.5, float))
    top_k: int = 3

    # Video
    video_fps: float = field(default_factory=lambda: _env("VIDEO_FPS", 2.0, float))
    video_max_frames: int = field(default_factory=lambda: _env("VIDEO_MAX_FRAMES", 40, int))
    enroll_dedupe_similarity: float = 0.97

    # Volitelný PIN pro přístup z telefonu (prázdný = bez PINu)
    pin: str = field(default_factory=lambda: _env("PIN", ""))

    # Záloha galerie do soukromého datasetu na Hugging Face (jen pro běh na HF Spaces), viz hfsync.py
    hf_dataset: str = field(default_factory=lambda: _env("HF_DATASET", ""))

    @property
    def db_path(self) -> Path:
        return self.data_dir / "hulmany.db"

    @property
    def media_dir(self) -> Path:
        return self.data_dir / "media"


settings = Settings()
