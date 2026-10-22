import torch

from .config import settings


def resolve_device() -> str:
    if settings.device != "auto":
        return settings.device
    if torch.cuda.is_available():
        return "cuda"
    if getattr(torch.backends, "mps", None) and torch.backends.mps.is_available():
        return "mps"
    return "cpu"


def device_description() -> str:
    dev = resolve_device()
    if dev == "cuda":
        return f"GPU: {torch.cuda.get_device_name(0)}"
    if dev == "mps":
        return "Apple GPU (MPS)"
    return "CPU"
