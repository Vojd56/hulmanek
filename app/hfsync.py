"""Záloha galerie do soukromého datasetu na Hugging Face.

Používá se na Hugging Face Spaces, kde se disk při restartu maže. Zapne se proměnnými
HULMANY_HF_DATASET (např. jmeno/hulmanek-data) a HF_TOKEN. Na PC v zoo se nepoužívá.
"""
import logging
import os
import shutil
import sqlite3

from .config import settings

log = logging.getLogger("hulmani")
SNAPSHOT = "hulmany.snapshot.db"
_scheduler = None


def enabled() -> bool:
    return bool(settings.hf_dataset and os.environ.get("HF_TOKEN"))


def restore():
    """Před otevřením databáze stáhne poslední zálohu (databázi, výřezy, nastavení)."""
    if not enabled():
        return
    from huggingface_hub import snapshot_download

    settings.data_dir.mkdir(parents=True, exist_ok=True)
    try:
        snapshot_download(settings.hf_dataset, repo_type="dataset", local_dir=settings.data_dir,
                          token=os.environ["HF_TOKEN"])
    except Exception as e:  # prázdný nebo ještě neexistující dataset
        log.warning("Záloha z %s nestažena: %s", settings.hf_dataset, e)
        return
    snap = settings.data_dir / SNAPSHOT
    if snap.exists() and not settings.db_path.exists():
        shutil.copyfile(snap, settings.db_path)
    log.info("Galerie obnovena z %s", settings.hf_dataset)


def start(every_minutes: float = 2):
    """Každé dvě minuty nahraje změny. Databáze se nahrává jako konzistentní kopie."""
    global _scheduler
    if not enabled() or _scheduler is not None:
        return
    from huggingface_hub import CommitScheduler

    class Scheduler(CommitScheduler):
        def push_to_hub(self):
            from . import db

            with db._lock:
                dst = sqlite3.connect(settings.data_dir / SNAPSHOT)
                db.connect().backup(dst)
                dst.close()
            return super().push_to_hub()

    _scheduler = Scheduler(repo_id=settings.hf_dataset, repo_type="dataset", folder_path=settings.data_dir,
                           every=every_minutes, private=True, token=os.environ["HF_TOKEN"],
                           ignore_patterns=["hulmany.db", "hulmany.db-*", ".cache/**", "*.lock"])
    log.info("Záloha galerie do %s zapnuta", settings.hf_dataset)
