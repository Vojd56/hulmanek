"""Testy celé aplikace s náhradním detektorem a jednoduchým embedderem (bez stahování modelů).

Spuštění: python -m pytest tests -q
"""
import io

import cv2
import numpy as np
import pytest
from PIL import Image

from app.detector import Animal, Box, group_animals


class FakeEmbedder:
    model_name = "fake"
    model_id = "fake"
    finetuned = False

    def embed(self, images):
        vecs = []
        for im in images:
            v = np.asarray(im.convert("RGB").resize((8, 8)), dtype=np.float32).ravel() - 127.5
            vecs.append(v / (np.linalg.norm(v) + 1e-6))
        return np.stack(vecs).astype(np.float32) if vecs else np.zeros((0, 192), np.float32)


class FakeDetector:
    """Najde „hulmana“ v levé polovině obrázku, obličej v jeho horní části."""
    available = True
    error = None
    weights = "fake"

    def animals(self, image):
        w, h = image.size
        if np.asarray(image).std() < 1:  # jednobarevný obrázek = žádné zvíře
            return group_animals(image, [], []) if False else [Animal(
                box=Box(0, 0, w, h), crops={"body": image}, boxes={"body": Box(0, 0, w, h)}, fallback=True)]
        body = Box(0, 0, w / 2, h, conf=0.9)
        face = Box(w / 8, h / 8, w * 3 / 8, h * 3 / 8, conf=0.8)
        return group_animals(image, [body], [face])


def pattern(seed: int, noise: int = 0, size=(320, 240)) -> Image.Image:
    """Jedinec = náhodná barevná mozaika; `noise` = jiná fotka téhož jedince."""
    base = np.random.default_rng(seed).integers(0, 255, (6, 8, 3)).astype(np.int16)
    if noise:
        base = base + np.random.default_rng(seed * 1000 + noise).integers(-30, 30, base.shape)
    base = np.clip(base, 0, 255).astype(np.uint8)
    return Image.fromarray(base).resize(size, Image.NEAREST)


def jpeg(im: Image.Image) -> bytes:
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=95)
    return buf.getvalue()


def mp4(path, frames):
    w, h = frames[0].size
    out = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"mp4v"), 10, (w, h))
    for f in frames:
        out.write(cv2.cvtColor(np.asarray(f), cv2.COLOR_RGB2BGR))
    out.release()
    return path.read_bytes()


@pytest.fixture()
def client(tmp_path, monkeypatch):
    from app import db
    from app.config import settings

    monkeypatch.setattr(settings, "data_dir", tmp_path / "data")
    monkeypatch.setattr(settings, "models_dir", tmp_path / "models")
    monkeypatch.setattr(settings, "unknown_threshold", 0.5)
    monkeypatch.setattr(settings, "face_weight", 0.5)
    db.reset_connection()
    from fastapi.testclient import TestClient

    from app import main
    from app.service import Service

    main.state.clear()
    main.state["service"] = Service(detector=FakeDetector(), embedder=FakeEmbedder())
    with TestClient(main.app) as c:
        yield c
    db.reset_connection()


def add(client, name):
    r = client.post("/api/individuals", json={"name": name})
    assert r.status_code == 200, r.text
    return r.json()["id"]


def test_group_animals_assigns_face_to_body():
    im = Image.new("RGB", (100, 100))
    animals = group_animals(im, [Box(0, 0, 50, 100, .9), Box(50, 0, 100, 100, .8)], [Box(60, 10, 80, 30, .7)])
    assert len(animals) == 2
    with_face = [a for a in animals if "face" in a.crops]
    assert len(with_face) == 1 and with_face[0].box.x1 == 50


def test_enroll_identify_confirm(client):
    ids = {n: add(client, n) for n in ["Bongo", "Kiki", "Zuri"]}
    for seed, (name, iid) in enumerate(ids.items(), start=1):
        files = [("files", (f"{name}{k}.jpg", jpeg(pattern(seed, noise=k)), "image/jpeg")) for k in range(1, 4)]
        r = client.post(f"/api/individuals/{iid}/media", files=files)
        assert r.status_code == 200, r.text
        assert sum(x["added"] for x in r.json()["reports"]) >= 2

    assert client.post("/api/individuals", json={"name": "bongo"}).status_code == 409
    listing = client.get("/api/individuals").json()
    assert {x["name"] for x in listing} == set(ids)
    assert all(x["face_samples"] > 0 and x["body_samples"] > 0 for x in listing)

    r = client.post("/api/identify", files={"file": ("q.jpg", jpeg(pattern(2, noise=9)), "image/jpeg")})
    assert r.status_code == 200, r.text
    res = r.json()
    animal = res["animals"][0]
    assert animal["candidates"][0]["name"] == "Kiki"
    assert animal["status"] == "match"
    assert set(animal["boxes"]) == {"face", "body"}

    before = client.get(f"/api/individuals/{ids['Kiki']}").json()["samples"]
    r = client.post(f"/api/identifications/{res['id']}/confirm",
                    json={"individual_id": ids["Kiki"], "animal_index": 0})
    assert r.status_code == 200
    after = client.get(f"/api/individuals/{ids['Kiki']}").json()["samples"]
    assert len(after) == len(before) + r.json()["added"]

    hist = client.get("/api/identifications").json()
    assert hist[0]["confirmed_name"] == "Kiki"

    ev = client.post("/api/evaluate").json()
    assert ev["samples"] > 0 and ev["top1"] >= 0.9


def test_unknown_when_nothing_matches(client):
    iid = add(client, "Bongo")
    client.post(f"/api/individuals/{iid}/media",
                files=[("files", ("a.jpg", jpeg(pattern(1, 1)), "image/jpeg"))])
    res = client.post("/api/identify", files={"file": ("q.jpg", jpeg(pattern(77)), "image/jpeg")}).json()
    assert res["animals"][0]["status"] == "unknown"


def test_video_identify_and_enroll(client, tmp_path):
    a, b = add(client, "Bongo"), add(client, "Kiki")
    vid_a = mp4(tmp_path / "a.mp4", [pattern(1, noise=k) for k in range(1, 21)])
    r = client.post(f"/api/individuals/{a}/media", files=[("files", ("a.mp4", vid_a, "video/mp4"))])
    rep = r.json()["reports"][0]
    assert rep["frames"] == 2 and rep["added"] >= 1, rep
    client.post(f"/api/individuals/{b}/media",
                files=[("files", (f"b{k}.jpg", jpeg(pattern(2, k)), "image/jpeg")) for k in range(1, 4)])

    vid_q = mp4(tmp_path / "q.mp4", [pattern(1, noise=k) for k in range(30, 50)])
    res = client.post("/api/identify", files={"file": ("q.mp4", vid_q, "video/mp4")}).json()
    assert res["media_type"] == "video"
    assert res["video"]["candidates"][0]["name"] == "Bongo"
    assert res["video"]["frames"] >= 3
    r = client.post(f"/api/identifications/{res['id']}/confirm", json={"individual_id": a})
    assert r.status_code == 200


def test_delete(client):
    iid = add(client, "Bongo")
    client.post(f"/api/individuals/{iid}/media", files=[("files", ("a.jpg", jpeg(pattern(1, 1)), "image/jpeg"))])
    sample = client.get(f"/api/individuals/{iid}").json()["samples"][0]
    assert client.delete(f"/api/samples/{sample['id']}").status_code == 200
    assert client.delete(f"/api/individuals/{iid}").status_code == 200
    assert client.get("/api/individuals").json() == []


def test_pin(client, monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "pin", "1234")
    assert client.get("/api/individuals").status_code == 401
    assert client.get("/api/individuals", headers={"x-pin": "1234"}).status_code == 200
    assert client.get("/api/status").json()["pin_ok"] is False


def test_gallery_recomputed_when_model_changes(client):
    from app import main

    iid = add(client, "Bongo")
    client.post(f"/api/individuals/{iid}/media", files=[("files", ("a.jpg", jpeg(pattern(1, 1)), "image/jpeg"))])
    service = main.state["service"]
    assert service.gallery.size() == 2

    class NewModel(FakeEmbedder):
        model_id = "fake+ft"

    service.embedder = NewModel()
    service.reload()
    assert service.gallery.size() == 0  # staré otisky se s novým modelem nemíchají
    service.ensure_embeddings(background=False)
    assert service.gallery.size() == 2


def test_switch_sample_kind_and_confirm_override(client):
    from app import main

    iid = add(client, "Bongo")
    client.post(f"/api/individuals/{iid}/media", files=[("files", ("a.jpg", jpeg(pattern(1, 1)), "image/jpeg"))])
    face = next(s for s in client.get(f"/api/individuals/{iid}").json()["samples"] if s["kind"] == "face")
    assert client.patch(f"/api/samples/{face['id']}", json={"kind": "body"}).json()["kind"] == "body"
    assert client.patch(f"/api/samples/{face['id']}", json={"kind": "tail"}).status_code == 400
    assert len(main.state["service"].gallery.vectors["body"]) == 2
    assert "face" not in main.state["service"].gallery.vectors

    res = client.post("/api/identify", files={"file": ("q.jpg", jpeg(pattern(1, 5)), "image/jpeg")}).json()
    kinds = [c["kind"] for c in res["animals"][0]["crops"]]
    r = client.post(f"/api/identifications/{res['id']}/confirm",
                    json={"individual_id": iid, "animal_index": 0, "crop_kinds": ["body"] * len(kinds)})
    assert r.status_code == 200
    stored = {s["kind"] for s in client.get(f"/api/individuals/{iid}").json()["samples"]}
    assert stored == {"body"}


def test_settings_persist(client):
    from app import main
    from app.config import settings

    client.post("/api/settings", json={"face_weight": 0.3})
    settings.face_weight = 0.9
    main.load_saved_settings()
    assert settings.face_weight == 0.3
    assert client.get("/api/status").json()["face_weight"] == 0.3


def test_big_face_without_body_counts_as_body():
    im = Image.new("RGB", (100, 100))
    animals = group_animals(im, [], [Box(5, 5, 95, 95, .6)])
    assert list(animals[0].crops) == ["body"]
    animals = group_animals(im, [Box(0, 0, 100, 100, .9)], [Box(2, 2, 98, 98, .5)])
    assert list(animals[0].crops) == ["body"]
