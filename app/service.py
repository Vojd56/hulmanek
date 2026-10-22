"""Hlavní logika: rozpoznání, zápis do galerie, přepočet otisků."""
import json
import logging
import threading

import numpy as np
from PIL import Image

from . import db, media
from .config import settings
from .detector import Animal, Detector
from .embedder import Embedder
from .gallery import Gallery, aggregate_frames

log = logging.getLogger(__name__)


class Service:
    def __init__(self, detector=None, embedder=None):
        self.detector = detector or Detector()
        self.embedder = embedder or Embedder()
        self.gallery = Gallery()
        self.rebuild_state = {"running": False, "done": 0, "total": 0}
        self.ensure_embeddings(background=False)

    # ---------- galerie ----------
    def names(self) -> dict[int, str]:
        return {r["id"]: r["name"] for r in db.query("SELECT id, name FROM individuals")}

    def reload(self):
        self.gallery.reload(self.embedder.model_id)

    def ensure_embeddings(self, background: bool = True):
        """Dopočítá otisky vzorků, které chybí nebo jsou z jiného (např. dříve doladěného) modelu."""
        stale = db.query("SELECT id, crop_path FROM samples WHERE model_id IS NULL OR model_id != ?",
                         (self.embedder.model_id,))
        if not stale:
            self.reload()
            return
        if background:
            threading.Thread(target=self._rebuild, args=(stale,), daemon=True).start()
        else:
            self._rebuild(stale)

    def _rebuild(self, rows):
        self.rebuild_state = {"running": True, "done": 0, "total": len(rows)}
        try:
            for i in range(0, len(rows), 32):
                chunk = rows[i:i + 32]
                images, ids = [], []
                for r in chunk:
                    try:
                        images.append(Image.open(media.media_path(r["crop_path"])).convert("RGB"))
                        ids.append(r["id"])
                    except OSError:
                        log.warning("Chybí výřez %s", r["crop_path"])
                vecs = self.embedder.embed(images) if images else []
                with db.tx() as conn:
                    for sid, vec in zip(ids, vecs):
                        conn.execute("UPDATE samples SET embedding = ?, model_id = ? WHERE id = ?",
                                     (vec.tobytes(), self.embedder.model_id, sid))
                self.rebuild_state["done"] += len(chunk)
        finally:
            self.rebuild_state["running"] = False
            self.reload()

    # ---------- analýza ----------
    def analyze(self, image: Image.Image) -> list[tuple[Animal, dict, list[dict]]]:
        animals = self.detector.animals(image)
        out = []
        for animal in animals:
            kinds = list(animal.crops)
            vecs = self.embedder.embed([animal.crops[k] for k in kinds])
            emb = dict(zip(kinds, vecs))
            out.append((animal, emb, self.gallery.rank(emb)))
        return out

    def _status(self, ranking: list[dict]) -> str:
        if not ranking:
            return "empty"
        top = ranking[0]["score"]
        if top < settings.unknown_threshold:
            return "unknown"
        if len(ranking) > 1 and top - ranking[1]["score"] < 0.03:
            return "uncertain"
        return "match"

    def _candidates(self, ranking, names):
        return [{**r, "name": names.get(r["individual_id"], "?"),
                 "score": round(r["score"], 4)} for r in ranking[:settings.top_k]]

    def _save_crops(self, animal: Animal, folder: str) -> list[dict]:
        return [{"kind": k, "path": media.save_image(im, folder, max_side=512)} for k, im in animal.crops.items()]

    def identify_image(self, data: bytes, filename: str) -> dict:
        image = media.load_image(data)
        rel = media.save_image(image, "queries", max_side=2048)
        names = self.names()
        animals = []
        for i, (animal, _emb, ranking) in enumerate(self.analyze(image)):
            crops = self._save_crops(animal, "queries/crops")
            animals.append({
                "index": i,
                "box": animal.box.as_list(),
                "boxes": {k: b.as_list() for k, b in animal.boxes.items()},
                "fallback": animal.fallback,
                "crops": [{**c, "url": media.media_url(c["path"])} for c in crops],
                "candidates": self._candidates(ranking, names),
                "status": self._status(ranking),
            })
        result = {"media_type": "image", "media_url": media.media_url(rel),
                  "width": image.width, "height": image.height, "animals": animals}
        return self._store_identification(rel, "image", result)

    def identify_video(self, data: bytes, filename: str) -> dict:
        rel = media.save_upload(data, "queries/video", filename)
        frames = media.video_frames(media.media_path(rel), settings.video_fps, settings.video_max_frames)
        if not frames:
            raise ValueError("Ve videu nejsou žádné čitelné snímky.")
        names = self.names()
        frame_rankings, best = [], None
        primary_crops = []
        keep_every = max(1, len(frames) // 8)
        for n, (t, frame) in enumerate(frames):
            analyzed = self.analyze(frame)
            merged: dict[int, dict] = {}
            for _animal, _emb, ranking in analyzed:
                for r in ranking:
                    if r["individual_id"] not in merged or r["score"] > merged[r["individual_id"]]["score"]:
                        merged[r["individual_id"]] = r
            frame_ranking = sorted(merged.values(), key=lambda r: r["score"], reverse=True)
            frame_rankings.append(frame_ranking)
            top = frame_ranking[0]["score"] if frame_ranking else -1
            if best is None or top > best[0]:
                best = (top, t, frame, analyzed)
            main = max(analyzed, key=lambda a: (not a[0].fallback, a[0].box.area))[0]
            if n % keep_every == 0 and not main.fallback:
                primary_crops += self._save_crops(main, "queries/crops")
        votes = aggregate_frames(frame_rankings)
        _, best_t, best_frame, best_analyzed = best
        frame_rel = media.save_image(best_frame, "queries", max_side=2048)
        animals = []
        for i, (animal, _emb, ranking) in enumerate(best_analyzed):
            crops = self._save_crops(animal, "queries/crops")
            animals.append({
                "index": i, "box": animal.box.as_list(),
                "boxes": {k: b.as_list() for k, b in animal.boxes.items()},
                "fallback": animal.fallback,
                "crops": [{**c, "url": media.media_url(c["path"])} for c in crops],
                "candidates": self._candidates(ranking, names), "status": self._status(ranking),
            })
        if not primary_crops:
            primary_crops = [c for a in animals[:1] if not a["fallback"] for c in a["crops"]]
        result = {
            "media_type": "video", "media_url": media.media_url(frame_rel),
            "video_url": media.media_url(rel), "best_frame_time": round(best_t, 2),
            "width": best_frame.width, "height": best_frame.height, "animals": animals,
            "video": {"frames": len(frames), "candidates": [
                {**v, "name": names.get(v["individual_id"], "?"), "score": round(v["score"], 4)}
                for v in votes[:settings.top_k]], "status": self._status(votes)},
            "primary_crops": [{"kind": c["kind"], "path": c["path"]} for c in primary_crops],
        }
        return self._store_identification(rel, "video", result)

    def _store_identification(self, rel, media_type, result) -> dict:
        with db.tx() as conn:
            cur = conn.execute("INSERT INTO identifications (media_path, media_type, result_json, created_at) "
                               "VALUES (?, ?, ?, ?)", (rel, media_type, json.dumps(result), db.now()))
            result["id"] = cur.lastrowid
        return result

    def confirm(self, identification_id: int, individual_id: int, animal_index: int | None, learn: bool = True,
                crop_kinds: list[str] | None = None):
        row = db.query("SELECT result_json FROM identifications WHERE id = ?", (identification_id,))
        if not row:
            raise KeyError("Rozpoznání neexistuje.")
        result = json.loads(row[0]["result_json"])
        with db.tx() as conn:
            conn.execute("UPDATE identifications SET confirmed_individual_id = ? WHERE id = ?",
                         (individual_id, identification_id))
        if not learn:
            return 0
        if animal_index is None and result.get("primary_crops"):
            crops = result["primary_crops"]
        else:
            idx = animal_index or 0
            crops = result["animals"][idx]["crops"] if idx < len(result["animals"]) else []
            if result["animals"] and result["animals"][idx].get("fallback") and self.detector.available:
                crops = []  # celý snímek bez nalezeného hulmana do galerie nepatří
        if crop_kinds and len(crop_kinds) == len(crops):  # uživatel přepnul obličej/tělo
            crops = [{**c, "kind": k} for c, k in zip(crops, crop_kinds) if k in ("face", "body")]
        images = [(c["kind"], Image.open(media.media_path(c["path"])).convert("RGB")) for c in crops]
        return self._add_samples(individual_id, images, source=f"identification:{identification_id}",
                                 origin="confirmed")

    # ---------- zápis do galerie ----------
    def _add_samples(self, individual_id: int, images: list[tuple[str, Image.Image]], source: str,
                     origin: str) -> int:
        if not images:
            return 0
        vecs = self.embedder.embed([im for _, im in images])
        existing = {k: self.gallery.vectors[k][self.gallery.owners[k] == individual_id]
                    if k in self.gallery.vectors else np.zeros((0, vecs.shape[1]), np.float32)
                    for k in ("face", "body")}
        added = 0
        with db.tx() as conn:
            for (kind, im), vec in zip(images, vecs):
                pool = existing[kind]
                if len(pool) and float((pool @ vec).max()) > settings.enroll_dedupe_similarity:
                    continue  # téměř stejný snímek už v galerii je
                rel = media.save_image(im, f"samples/{individual_id}", max_side=512)
                conn.execute("INSERT INTO samples (individual_id, kind, crop_path, source, origin, model_id, "
                             "embedding, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                             (individual_id, kind, rel, source, origin, self.embedder.model_id,
                              vec.tobytes(), db.now()))
                existing[kind] = np.vstack([pool, vec[None]]) if len(pool) else vec[None]
                added += 1
        self.reload()
        return added

    def enroll(self, individual_id: int, data: bytes, filename: str, content_type: str | None = None) -> dict:
        """Přidá fotku nebo video do galerie jedince. U videa bere snímky po sekundě."""
        report = {"file": filename, "frames": 0, "added": 0, "no_animal": 0, "multiple": 0}
        source = f"upload:{filename}:{len(data)}"
        if media.is_video(filename, content_type):
            rel = media.save_upload(data, "enroll", filename)
            frames = [f for _, f in media.video_frames(media.media_path(rel), 1.0, 60)]
            media.media_path(rel).unlink(missing_ok=True)
        else:
            frames = [media.load_image(data)]
        images = []
        for frame in frames:
            report["frames"] += 1
            animals = self.detector.animals(frame)
            real = [a for a in animals if not a.fallback]
            if self.detector.available and not real:
                report["no_animal"] += 1
                continue
            if len(real) > 1:
                report["multiple"] += 1
            main = max(real or animals, key=lambda a: a.box.area)
            images += list(main.crops.items())
        report["added"] = self._add_samples(individual_id, images, source=source, origin="enroll")
        return report

    # ---------- vyhodnocení ----------
    def evaluate(self) -> dict:
        """Křížová kontrola: každý vzorek se rozpozná proti galerii bez vzorků ze stejného souboru."""
        rows = db.query("SELECT id, individual_id, kind, source, embedding FROM samples "
                        "WHERE model_id = ? AND embedding IS NOT NULL", (self.embedder.model_id,))
        by_source: dict[str, list] = {}
        sources_of: dict[int, set] = {}
        for r in rows:
            by_source.setdefault(r["source"], []).append(r)
            sources_of.setdefault(r["individual_id"], set()).add(r["source"])
        hits1 = hits3 = total = 0
        correct_scores, wrong_scores = [], []
        per_individual: dict[int, list[int]] = {}
        for source, items in by_source.items():
            exclude = {r["id"] for r in items}
            for r in items:
                if len(sources_of[r["individual_id"]]) < 2:
                    continue  # jedinec nemá jiný soubor, se kterým by šel porovnat
                vec = np.frombuffer(r["embedding"], dtype=np.float32)
                ranking = self.gallery.rank({r["kind"]: vec}, exclude_samples=exclude)
                if not ranking:
                    continue
                total += 1
                ids = [x["individual_id"] for x in ranking]
                ok = ids[0] == r["individual_id"]
                hits1 += ok
                hits3 += r["individual_id"] in ids[:3]
                (correct_scores if ok else wrong_scores).append(ranking[0]["score"])
                per_individual.setdefault(r["individual_id"], []).append(int(ok))
        names = self.names()
        return {
            "samples": total,
            "skipped_individuals": [names.get(i, "?") for i, src in sources_of.items() if len(src) < 2],
            "top1": hits1 / total if total else None,
            "top3": hits3 / total if total else None,
            "suggested_threshold": _suggest_threshold(correct_scores, wrong_scores),
            "per_individual": sorted([
                {"individual_id": i, "name": names.get(i, "?"), "samples": len(v), "top1": sum(v) / len(v)}
                for i, v in per_individual.items()], key=lambda x: x["top1"]),
        }


def _suggest_threshold(correct: list[float], wrong: list[float]) -> float | None:
    """Práh, pod kterým výsledek označíme jako „neznámý“: maximalizuje správně rozhodnuté případy."""
    if not correct or not wrong:
        return None
    best_t, best_acc = None, -1.0
    for t in np.linspace(0, 1, 101):
        acc = (sum(s >= t for s in correct) + sum(s < t for s in wrong)) / (len(correct) + len(wrong))
        if acc > best_acc:
            best_t, best_acc = float(t), acc
    return round(best_t, 2)
