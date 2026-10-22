"""Ukázkový server s náhradními modely (bez GPU a bez stahování) pro vyzkoušení rozhraní."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import uvicorn  # noqa: E402

from app import main  # noqa: E402
from app.service import Service  # noqa: E402
from test_app import FakeDetector, FakeEmbedder  # noqa: E402

main.state["service"] = Service(detector=FakeDetector(), embedder=FakeEmbedder())
uvicorn.run(main.app, host="127.0.0.1", port=int(sys.argv[1]) if len(sys.argv) > 1 else 8765)
