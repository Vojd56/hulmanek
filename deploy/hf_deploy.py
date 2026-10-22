"""Nasazení na Hugging Face Spaces.

Předpoklad: přihlášení na tomto PC přes `.venv\\Scripts\\hf auth login` (token typu Write).

    python deploy/hf_deploy.py                # založí/aktualizuje Space a soukromý dataset
    python deploy/hf_deploy.py --upload-data  # navíc nahraje galerii z tohoto PC do datasetu

Space je veřejný (jinak by na něj nedosáhl web na Vercelu), ale aplikace je za PINem
a fotky i databáze leží jen v soukromém datasetu. PIN se při prvním nasazení vygeneruje
a uloží do data/pin-hf.txt na tomto PC.
"""
import argparse
import secrets
import shutil
import sqlite3
import sys
import tempfile
from pathlib import Path

from huggingface_hub import HfApi, get_token

ROOT = Path(__file__).resolve().parent.parent
SPACE_README = """---
title: Hulmánek
emoji: 🐒
colorFrom: green
colorTo: yellow
sdk: docker
app_port: 7860
pinned: false
short_description: Neoficiální studentský projekt, rozpoznávání hulmanů
---

Neoficiální studentský projekt, nejde o produkt ani službu Zoo Ostrava. Aplikace je chráněná PINem.
"""
CODE = ["app/**", "static/**", "deploy/warmup.py", "Dockerfile", "requirements.txt"]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--name", default="hulmanek")
    parser.add_argument("--upload-data", action="store_true")
    args = parser.parse_args()

    token = get_token()
    if not token:
        sys.exit("Nejdřív se přihlaste: .venv\\Scripts\\hf auth login")
    api = HfApi(token=token)
    user = api.whoami()["name"]
    space, dataset = f"{user}/{args.name}", f"{user}/{args.name}-data"

    api.create_repo(dataset, repo_type="dataset", private=True, exist_ok=True)
    if args.upload_data:
        upload_data(api, dataset)

    pin_file = ROOT / "data" / "pin-hf.txt"
    new_space = not api.repo_exists(space, repo_type="space")
    api.create_repo(space, repo_type="space", space_sdk="docker", private=False, exist_ok=True)
    if new_space or not pin_file.exists():
        pin = f"{secrets.randbelow(10**6):06d}"
        pin_file.parent.mkdir(parents=True, exist_ok=True)
        pin_file.write_text(pin + "\n", encoding="utf-8")
        api.add_space_secret(space, "HULMANY_PIN", pin)
        print(f"PIN uložen do {pin_file}")
    api.add_space_secret(space, "HF_TOKEN", token)
    api.add_space_variable(space, "HULMANY_HF_DATASET", dataset)

    with tempfile.TemporaryDirectory() as tmp:
        (Path(tmp) / "README.md").write_text(SPACE_README, encoding="utf-8")
        api.upload_file(path_or_fileobj=str(Path(tmp) / "README.md"), path_in_repo="README.md",
                        repo_id=space, repo_type="space")
    api.upload_folder(folder_path=str(ROOT), repo_id=space, repo_type="space", allow_patterns=CODE,
                      ignore_patterns=["**/__pycache__/**", "*.pyc"], commit_message="Nasazení z PC")
    print(f"Space: https://huggingface.co/spaces/{space}")
    print(f"Adresa aplikace: https://{user}-{args.name}.hf.space".lower())


def upload_data(api: HfApi, dataset: str):
    data = ROOT / "data"
    with tempfile.TemporaryDirectory() as tmp:
        snap = Path(tmp) / "hulmany.snapshot.db"
        src = sqlite3.connect(data / "hulmany.db")
        dst = sqlite3.connect(snap)
        src.backup(dst)
        src.close()
        dst.close()
        if (data / "settings.json").exists():
            shutil.copy(data / "settings.json", tmp)
        api.upload_folder(folder_path=tmp, repo_id=dataset, repo_type="dataset", commit_message="Galerie z PC")
    if (data / "media").exists():
        api.upload_folder(folder_path=str(data / "media"), path_in_repo="media", repo_id=dataset,
                          repo_type="dataset", commit_message="Fotky z PC")
    print(f"Galerie nahrána do soukromého datasetu {dataset}")


if __name__ == "__main__":
    main()
