"""Stáhne modely do obrazu při sestavení (spouští Dockerfile)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.detector import Detector  # noqa: E402
from app.embedder import Embedder  # noqa: E402

Embedder()
detector = Detector()
print("Modely připravené." if detector.available else detector.error)
