"""Nasazení na Modal.com. Předpoklad: `.venv\\Scripts\\pip install modal` a `.venv\\Scripts\\modal setup`.

    python deploy/modal_deploy.py                # nasadí aplikaci
    python deploy/modal_deploy.py --upload-data  # navíc nahraje galerii z tohoto PC na Modal

PIN a tajný klíč pro Vercel se při prvním nasazení vygenerují a uloží do data/pin-web.txt
a data/proxy-key.txt na tomto PC.
"""
import argparse
import secrets
import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MODAL = [sys.executable, "-m", "modal"]


def modal(*args):
    subprocess.run([*MODAL, *args], check=True, cwd=ROOT)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--upload-data", action="store_true")
    args = parser.parse_args()

    pin = read_or_create(ROOT / "data" / "pin-web.txt", lambda: f"{secrets.randbelow(10**6):06d}")
    key = read_or_create(ROOT / "data" / "proxy-key.txt", lambda: secrets.token_urlsafe(32))
    modal("secret", "create", "hulmanek", f"HULMANY_PIN={pin}", f"HULMANY_PROXY_KEY={key}", "--force")

    if args.upload_data:
        if not volume_exists():
            modal("volume", "create", "hulmanek-data")
        with tempfile.TemporaryDirectory() as tmp:
            snap = Path(tmp) / "hulmany.db"
            src, dst = sqlite3.connect(ROOT / "data" / "hulmany.db"), sqlite3.connect(snap)
            src.backup(dst)
            src.close()
            dst.close()
            modal("volume", "put", "hulmanek-data", str(snap), "/hulmany.db", "--force")
        for name in ("media", "settings.json"):
            if (ROOT / "data" / name).exists():
                modal("volume", "put", "hulmanek-data", str(ROOT / "data" / name), f"/{name}", "--force")
        print("Galerie nahrána na Modal (volume hulmanek-data)")

    modal("deploy", "deploy/modal_app.py")


def read_or_create(path: Path, make) -> str:
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(make() + "\n", encoding="utf-8")
        print(f"Uloženo do {path}")
    return path.read_text(encoding="utf-8").strip()


def volume_exists() -> bool:
    out = subprocess.run([*MODAL, "volume", "list"], capture_output=True, text=True, cwd=ROOT).stdout
    return "hulmanek-data" in out


if __name__ == "__main__":
    main()
