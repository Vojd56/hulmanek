"""Nasazení webu na Vercel (hulmanek.vercel.app). Předpoklad: `npx vercel login` a nasazený Modal.

Vercel servíruje rozhraní ze static/ a požadavky na /api a /media přeposílá na Modal
s hlavičkou x-proxy-key. Klíč se do repozitáře neukládá, vercel.json vzniká jen při nasazení.
"""
import json
import shutil
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BACKEND = "https://vojtech-blaha01--hulmanek-web.us-east.modal.run"


def main():
    key = (ROOT / "data" / "proxy-key.txt").read_text(encoding="utf-8").strip()
    proxy = [{"type": "request.headers", "op": "set", "target": {"key": "x-proxy-key"}, "args": key}]
    config = {
        "routes": [
            {"src": r"/(index\.html|sw\.js)?", "headers": {"Cache-Control": "no-cache"}, "continue": True},
            {"src": "/(api|media)/(.*)", "dest": f"{BACKEND}/$1/$2", "transforms": proxy},
        ],
    }
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:  # npx na Windows drží složku
        site = Path(tmp) / "hulmanek"
        shutil.copytree(ROOT / "static", site)
        if (ROOT / ".vercel").exists():  # propojení s existujícím projektem hulmanek
            shutil.copytree(ROOT / ".vercel", site / ".vercel")
        (site / "vercel.json").write_text(json.dumps(config, indent=2), encoding="utf-8")
        subprocess.run("npx --yes vercel@latest deploy --prod --yes", shell=True, check=True, cwd=site)
        if (site / ".vercel").exists():
            shutil.copytree(site / ".vercel", ROOT / ".vercel", dirs_exist_ok=True)


if __name__ == "__main__":
    main()
