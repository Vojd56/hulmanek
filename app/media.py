"""Ukládání souborů a čtení snímků z videa."""
import io
import uuid
from pathlib import Path

import cv2
from PIL import Image, ImageOps

from .config import settings

VIDEO_EXT = {".mp4", ".mov", ".m4v", ".avi", ".mkv", ".webm", ".3gp"}
IMAGE_EXT = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".heic", ".heif"}


def media_path(rel: str) -> Path:
    return settings.media_dir / rel


def media_url(rel: str) -> str:
    return f"/media/{rel}"


# Náhledy pro web. Originály zůstávají, jak jsou (z nich se počítají otisky), web stahuje jen
# zmenšené kopie, které se vytvoří při prvním zobrazení a uloží do media/_thumbs.
THUMB_SIZES = {"s": 384, "m": 1280}
THUMB_PREFIX = "/media/_t/"


def thumb_url(url: str | None, size: str = "s") -> str | None:
    """Z adresy /media/... udělá adresu náhledu. Videa a cizí adresy nechá být."""
    if not url or not url.startswith("/media/") or Path(url).suffix.lower() in VIDEO_EXT:
        return url
    rel = url[len("/media/"):]
    if url.startswith(THUMB_PREFIX):
        rel = rel.split("/", 2)[2]  # už je to náhled: _t/<velikost>/<cesta>
    return f"{THUMB_PREFIX}{size}/{rel}"


def thumb_path(size: str, rel: str) -> Path | None:
    """Cesta k náhledu (vytvoří ho, když chybí). None = neznámá velikost nebo soubor."""
    if size not in THUMB_SIZES:
        return None
    root = settings.media_dir.resolve()
    src = (root / rel).resolve()
    if root not in src.parents or not src.is_file() or src.suffix.lower() in VIDEO_EXT:
        return None
    dst = root / "_thumbs" / size / Path(rel).with_suffix(".jpg")
    if not dst.exists():
        dst.parent.mkdir(parents=True, exist_ok=True)
        with Image.open(src) as im:
            im = im.convert("RGB")
            im.thumbnail((THUMB_SIZES[size], THUMB_SIZES[size]))
            tmp = dst.with_name(f"{dst.stem}.{uuid.uuid4().hex}.tmp")
            im.save(tmp, "JPEG", quality=78, optimize=True, progressive=True)
        tmp.replace(dst)
    return dst


def is_video(filename: str, content_type: str | None = None) -> bool:
    if content_type and content_type.startswith("video/"):
        return True
    return Path(filename or "").suffix.lower() in VIDEO_EXT


def save_upload(data: bytes, folder: str, filename: str) -> str:
    suffix = Path(filename or "").suffix.lower() or ".bin"
    rel = f"{folder}/{uuid.uuid4().hex}{suffix}"
    path = media_path(rel)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return rel


def save_image(image: Image.Image, folder: str, max_side: int = 1024) -> str:
    rel = f"{folder}/{uuid.uuid4().hex}.jpg"
    path = media_path(rel)
    path.parent.mkdir(parents=True, exist_ok=True)
    im = image.convert("RGB")
    im.thumbnail((max_side, max_side))
    im.save(path, quality=90)
    return rel


def load_image(data: bytes) -> Image.Image:
    try:
        import pillow_heif  # volitelné: fotky HEIC z iPhonu

        pillow_heif.register_heif_opener()
    except ImportError:
        pass
    image = Image.open(io.BytesIO(data))
    return ImageOps.exif_transpose(image).convert("RGB")


def video_frames(path: Path, fps: float, max_frames: int) -> list[tuple[float, Image.Image]]:
    """Vrátí rovnoměrně rozložené snímky (čas v s, obrázek)."""
    cap = cv2.VideoCapture(str(path))
    if not cap.isOpened():
        raise ValueError("Video se nepodařilo otevřít.")
    native_fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    step = max(1, int(round(native_fps / fps)))
    indices = list(range(0, total, step)) if total else []
    if len(indices) > max_frames:
        stride = len(indices) / max_frames
        indices = [indices[int(i * stride)] for i in range(max_frames)]
    frames = []
    if indices:
        for idx in indices:
            cap.set(cv2.CAP_PROP_POS_FRAMES, idx)
            ok, frame = cap.read()
            if ok:
                frames.append((idx / native_fps, Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))))
    else:  # některé kontejnery nehlásí počet snímků, čteme sekvenčně
        i = 0
        while len(frames) < max_frames:
            ok, frame = cap.read()
            if not ok:
                break
            if i % step == 0:
                frames.append((i / native_fps, Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))))
            i += 1
    cap.release()
    return frames
