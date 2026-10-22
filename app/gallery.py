"""Porovnání otisků s galerií pojmenovaných hulmanů."""
import threading
from collections import defaultdict

import numpy as np

from . import db
from .config import settings

KINDS = ("face", "body")


class Gallery:
    def __init__(self):
        self._lock = threading.Lock()
        self.vectors: dict[str, np.ndarray] = {}
        self.owners: dict[str, np.ndarray] = {}
        self.sample_ids: dict[str, np.ndarray] = {}

    def reload(self, model_id: str):
        rows = db.query("SELECT id, individual_id, kind, embedding FROM samples "
                        "WHERE model_id = ? AND embedding IS NOT NULL", (model_id,))
        by_kind = defaultdict(list)
        for r in rows:
            by_kind[r["kind"]].append(r)
        with self._lock:
            for kind in KINDS:
                items = by_kind.get(kind, [])
                if items:
                    self.vectors[kind] = np.stack([np.frombuffer(r["embedding"], dtype=np.float32) for r in items])
                    self.owners[kind] = np.array([r["individual_id"] for r in items])
                    self.sample_ids[kind] = np.array([r["id"] for r in items])
                else:
                    self.vectors.pop(kind, None)
                    self.owners.pop(kind, None)
                    self.sample_ids.pop(kind, None)

    def size(self) -> int:
        return sum(len(v) for v in self.owners.values())

    def kind_scores(self, kind: str, query: np.ndarray, exclude_samples: set | None = None,
                    top_n: int = 3) -> dict[int, float]:
        """Skóre pro každého jedince = průměr jeho `top_n` nejpodobnějších vzorků daného druhu."""
        with self._lock:
            vecs = self.vectors.get(kind)
            owners = self.owners.get(kind)
            ids = self.sample_ids.get(kind)
        if vecs is None:
            return {}
        sims = vecs @ query
        if exclude_samples:
            mask = ~np.isin(ids, list(exclude_samples))
            sims, owners = sims[mask], owners[mask]
        scores = {}
        for ind in np.unique(owners):
            s = np.sort(sims[owners == ind])[::-1][:top_n]
            scores[int(ind)] = float(s.mean())
        return scores

    def rank(self, embeddings: dict[str, np.ndarray], exclude_samples: set | None = None) -> list[dict]:
        """Seřadí jedince podle podobnosti. `embeddings` = {"face": vec, "body": vec} (stačí jeden)."""
        per_kind = {k: self.kind_scores(k, v, exclude_samples) for k, v in embeddings.items() if v is not None}
        individuals = set().union(*[set(s) for s in per_kind.values()]) if per_kind else set()
        ranking = []
        for ind in individuals:
            face = per_kind.get("face", {}).get(ind)
            body = per_kind.get("body", {}).get(ind)
            if face is not None and body is not None:
                score = settings.face_weight * face + (1 - settings.face_weight) * body
            else:
                score = face if face is not None else body
            ranking.append({"individual_id": ind, "score": score, "face": face, "body": body})
        ranking.sort(key=lambda r: r["score"], reverse=True)
        return ranking


def aggregate_frames(frame_rankings: list[list[dict]]) -> list[dict]:
    """Hlasování přes snímky videa: průměrné skóre jedince přes snímky + kolikrát vyhrál."""
    totals: dict[int, list[float]] = defaultdict(list)
    wins: dict[int, int] = defaultdict(int)
    for ranking in frame_rankings:
        if not ranking:
            continue
        wins[ranking[0]["individual_id"]] += 1
        for r in ranking:
            totals[r["individual_id"]].append(r["score"])
    n = max(1, sum(1 for r in frame_rankings if r))
    result = []
    for ind, scores in totals.items():
        # chybějící snímky se počítají jako nula, aby jedinec viděný jednou nepřebil stálého
        mean = sum(scores) / n
        result.append({"individual_id": ind, "score": mean, "wins": wins.get(ind, 0), "frames": n})
    result.sort(key=lambda r: (r["score"], r["wins"]), reverse=True)
    return result
