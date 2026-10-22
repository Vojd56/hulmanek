"""Převod výřezu zvířete na číselný otisk pomocí MegaDescriptoru (ČVUT, open source)."""
import threading
from pathlib import Path

import numpy as np
import timm
import torch
import torchvision.transforms as T
from PIL import Image

from .config import settings
from .device import resolve_device

MODELS = {
    "L-384": ("hf-hub:BVRA/MegaDescriptor-L-384", 384),
    "B-224": ("hf-hub:BVRA/MegaDescriptor-B-224", 224),
    "T-224": ("hf-hub:BVRA/MegaDescriptor-T-224", 224),
}


def resolve_model_name() -> str:
    if settings.embedder != "auto":
        return settings.embedder
    return "L-384" if resolve_device() == "cuda" else "T-224"


def finetuned_path(model_name: str) -> Path:
    return settings.models_dir / f"finetuned-{model_name}.pth"


def build_transform(size: int):
    return T.Compose([
        T.Resize((size, size)),
        T.ToTensor(),
        T.Normalize([0.5, 0.5, 0.5], [0.5, 0.5, 0.5]),
    ])


def create_backbone(model_name: str, pretrained: bool = True):
    hub_id, _ = MODELS[model_name]
    return timm.create_model(hub_id, num_classes=0, pretrained=pretrained)


class Embedder:
    def __init__(self, model_name: str | None = None, pretrained: bool = True):
        self.model_name = model_name or resolve_model_name()
        self.device = resolve_device()
        self.size = MODELS[self.model_name][1]
        self.model = create_backbone(self.model_name, pretrained=pretrained)
        self.finetuned = False
        ft = finetuned_path(self.model_name)
        if ft.exists():
            state = torch.load(ft, map_location="cpu")
            self.model.load_state_dict(state["backbone"] if "backbone" in state else state)
            self.finetuned = True
        self.model.eval().to(self.device)
        self.transform = build_transform(self.size)
        self._lock = threading.Lock()

    @property
    def model_id(self) -> str:
        """Identifikátor, podle kterého se pozná, že otisky v galerii jsou ze stejného modelu."""
        if self.finetuned:
            mtime = int(finetuned_path(self.model_name).stat().st_mtime)
            return f"{self.model_name}+ft{mtime}"
        return self.model_name

    @torch.inference_mode()
    def embed(self, images: list[Image.Image], batch_size: int = 16) -> np.ndarray:
        if not images:
            return np.zeros((0, 0), dtype=np.float32)
        out = []
        with self._lock:
            for i in range(0, len(images), batch_size):
                batch = torch.stack([self.transform(im.convert("RGB")) for im in images[i:i + batch_size]])
                batch = batch.to(self.device)
                if self.device == "cuda":
                    with torch.autocast("cuda", dtype=torch.float16):
                        feats = self.model(batch)
                else:
                    feats = self.model(batch)
                feats = torch.nn.functional.normalize(feats.float(), dim=1)
                out.append(feats.cpu().numpy())
        return np.concatenate(out).astype(np.float32)
