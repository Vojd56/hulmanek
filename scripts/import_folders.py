"""Hromadný import: složka s podsložkami pojmenovanými podle hulmanů.

    fotky/
      Bongo/   IMG_0001.jpg  video1.mov ...
      Kiki/    ...

    python scripts/import_folders.py fotky              # aplikace musí běžet
    python scripts/import_folders.py fotky --url http://localhost:8000 --pin 1234
"""
import argparse
import mimetypes
import sys
from pathlib import Path

import requests

EXT = {".jpg", ".jpeg", ".png", ".webp", ".heic", ".mp4", ".mov", ".m4v", ".avi", ".mkv"}


def main():
    p = argparse.ArgumentParser()
    p.add_argument("folder", type=Path)
    p.add_argument("--url", default="http://localhost:8000")
    p.add_argument("--pin", default="")
    args = p.parse_args()
    headers = {"x-pin": args.pin} if args.pin else {}
    existing = {i["name"].lower(): i["id"] for i in
                requests.get(f"{args.url}/api/individuals", headers=headers, timeout=30).json()}
    for sub in sorted(d for d in args.folder.iterdir() if d.is_dir()):
        name = sub.name
        iid = existing.get(name.lower())
        if iid is None:
            r = requests.post(f"{args.url}/api/individuals", json={"name": name}, headers=headers, timeout=30)
            r.raise_for_status()
            iid = r.json()["id"]
        files = sorted(f for f in sub.rglob("*") if f.suffix.lower() in EXT)
        added = 0
        for f in files:
            mime = mimetypes.guess_type(f.name)[0] or "application/octet-stream"
            with f.open("rb") as fh:
                r = requests.post(f"{args.url}/api/individuals/{iid}/media", headers=headers, timeout=3600,
                                  files=[("files", (f.name, fh, mime))])
            if r.status_code != 200:
                print(f"  ! {f.name}: {r.text}", file=sys.stderr)
                continue
            for rep in r.json()["reports"]:
                if "error" in rep:
                    print(f"  ! {f.name}: {rep['error']}", file=sys.stderr)
                added += rep.get("added", 0)
            print(f"  {name}: {f.name} hotovo", end="\r")
        print(f"{name}: {len(files)} souborů, přidáno {added} výřezů          ")


if __name__ == "__main__":
    main()
