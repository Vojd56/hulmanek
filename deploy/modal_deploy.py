"""Nasazení na Modal.com. Předpoklad: `.venv\\Scripts\\pip install modal` a `.venv\\Scripts\\modal setup`.

    python deploy/modal_deploy.py                # nasadí aplikaci
    python deploy/modal_deploy.py --upload-data  # navíc nahraje galerii z tohoto PC na Modal

PIN se při prvním nasazení vygeneruje a uloží do data/pin-web.txt na tomto PC.
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

    pin_file = ROOT / "data" / "pin-web.txt"
    if not pin_file.exists():
        pin_file.parent.mkdir(parents=True, exist_ok=True)
        pin_file.write_text(f"{secrets.randbelow(10**6):06d}\n", encoding="utf-8")
        print(f"PIN uložen do {pin_file}")
    modal("secret", "create", "hulmanek", f"HULMANY_PIN={pin_file.read_text().strip()}", "--force")

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


def volume_exists() -> bool:
    out = subprocess.run([*MODAL, "volume", "list"], capture_output=True, text=True, cwd=ROOT).stdout
    return "hulmanek-data" in out


if __name__ == "__main__":
    main()
