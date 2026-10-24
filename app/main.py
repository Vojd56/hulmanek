"""Webový server: API + mobilní rozhraní. Spuštění: python -m app.main"""
import hmac
import json
import logging
import shutil
import socket
import threading
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool

from . import db, media
from .config import ROOT, settings
from .device import device_description
from .embedder import finetuned_path

log = logging.getLogger("hulmani")
STATIC = ROOT / "static"
MAX_UPLOAD = 300 * 1024 * 1024
state = {}
_service_lock = threading.Lock()


def get_service():
    if "service" not in state:
        with _service_lock:  # modely se načítají jen jednou, i když se ptá víc požadavků naráz
            if "service" not in state:
                from .service import Service

                state["service"] = Service()
    return state["service"]


def _load_service():
    try:
        get_service()
    except Exception:  # noqa: BLE001  zkusí se znovu při prvním rozpoznání
        log.exception("Načtení modelů selhalo")


def settings_file() -> Path:
    return settings.data_dir / "settings.json"


def load_saved_settings():
    """Práh a váha obličeje nastavené v aplikaci přežijí restart."""
    try:
        saved = json.loads(settings_file().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return
    settings.unknown_threshold = float(saved.get("threshold", settings.unknown_threshold))
    settings.face_weight = float(saved.get("face_weight", settings.face_weight))


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings.media_dir.mkdir(parents=True, exist_ok=True)
    load_saved_settings()
    db.connect()
    # modely se načítají na pozadí, galerie a historie se mezitím zobrazí hned
    threading.Thread(target=_load_service, daemon=True).start()
    yield


app = FastAPI(title="Hulmánek", lifespan=lifespan)


def pin_ok(request: Request) -> bool:
    # obrázky (<img>) neumí poslat hlavičku, proto se PIN bere i z cookie
    return not settings.pin or settings.pin in (request.headers.get("x-pin"), request.cookies.get("pin"))


def check_pin(request: Request):
    if not pin_ok(request):
        raise HTTPException(401, "Špatný nebo chybějící PIN.")


@app.middleware("http")
async def require_proxy(request: Request, call_next):
    if settings.proxy_key and not hmac.compare_digest(request.headers.get("x-proxy-key", ""), settings.proxy_key):
        return JSONResponse({"detail": "Aplikace je dostupná jen přes svou hlavní adresu."}, status_code=403)
    return await call_next(request)


@app.middleware("http")
async def protect_media(request: Request, call_next):
    if request.url.path.startswith("/media/") and not pin_ok(request):
        return JSONResponse({"detail": "Špatný nebo chybějící PIN."}, status_code=401)
    response = await call_next(request)
    if request.url.path.startswith("/media/") and response.status_code == 200:
        # soubory mají jedinečná jména a nemění se, prohlížeč je nemusí znovu stahovat
        response.headers["Cache-Control"] = "private, max-age=31536000, immutable"
    return response


api = Depends(check_pin)


async def read_upload(file: UploadFile) -> bytes:
    data = await file.read()
    if len(data) > MAX_UPLOAD:
        raise HTTPException(413, "Soubor je příliš velký (max 300 MB).")
    if not data:
        raise HTTPException(400, "Prázdný soubor.")
    return data


# ---------- jedinci ----------
class IndividualIn(BaseModel):
    name: str
    sex: str | None = None
    birth_year: int | None = None
    notes: str | None = None


def individual_dict(row) -> dict:
    d = dict(row)
    if d.get("cover_path"):
        d["cover_url"] = media.thumb_url(media.media_url(d.pop("cover_path")))
    return d


@app.get("/api/individuals", dependencies=[api])
def list_individuals():
    rows = db.query("""
        SELECT i.*, COUNT(s.id) AS samples,
               SUM(s.kind = 'face') AS face_samples, SUM(s.kind = 'body') AS body_samples,
               (SELECT crop_path FROM samples c WHERE c.individual_id = i.id
                ORDER BY c.kind = 'face' DESC, c.id LIMIT 1) AS cover_path
        FROM individuals i LEFT JOIN samples s ON s.individual_id = i.id
        GROUP BY i.id ORDER BY i.name COLLATE NOCASE""")
    return [individual_dict(r) for r in rows]


@app.post("/api/individuals", dependencies=[api])
def create_individual(body: IndividualIn):
    name = body.name.strip()
    if not name:
        raise HTTPException(400, "Jméno nesmí být prázdné.")
    if db.query("SELECT 1 FROM individuals WHERE name = ? COLLATE NOCASE", (name,)):
        raise HTTPException(409, f"Hulman se jménem {name} už existuje.")
    with db.tx() as conn:
        cur = conn.execute("INSERT INTO individuals (name, sex, birth_year, notes, created_at) VALUES (?,?,?,?,?)",
                           (name, body.sex, body.birth_year, body.notes, db.now()))
    return {"id": cur.lastrowid, "name": name}


@app.get("/api/individuals/{iid}", dependencies=[api])
def get_individual(iid: int):
    rows = db.query("SELECT * FROM individuals WHERE id = ?", (iid,))
    if not rows:
        raise HTTPException(404, "Hulman nenalezen.")
    samples = db.query("SELECT id, kind, crop_path, origin, created_at FROM samples WHERE individual_id = ? "
                       "ORDER BY id DESC", (iid,))
    return {**dict(rows[0]), "samples": [
        {"id": s["id"], "kind": s["kind"], "origin": s["origin"], "url": media.thumb_url(media.media_url(s["crop_path"]))}
        for s in samples]}


@app.put("/api/individuals/{iid}", dependencies=[api])
def update_individual(iid: int, body: IndividualIn):
    with db.tx() as conn:
        conn.execute("UPDATE individuals SET name=?, sex=?, birth_year=?, notes=? WHERE id=?",
                     (body.name.strip(), body.sex, body.birth_year, body.notes, iid))
    return {"ok": True}


@app.delete("/api/individuals/{iid}", dependencies=[api])
def delete_individual(iid: int):
    with db.tx() as conn:
        conn.execute("DELETE FROM samples WHERE individual_id = ?", (iid,))
        conn.execute("DELETE FROM individuals WHERE id = ?", (iid,))
    shutil.rmtree(media.media_path(f"samples/{iid}"), ignore_errors=True)
    get_service().reload()
    return {"ok": True}


@app.post("/api/individuals/{iid}/media", dependencies=[api])
async def enroll_media(iid: int, files: list[UploadFile] = File(...)):
    if not db.query("SELECT 1 FROM individuals WHERE id = ?", (iid,)):
        raise HTTPException(404, "Hulman nenalezen.")
    service = get_service()
    reports = []
    for f in files:
        data = await read_upload(f)
        try:
            reports.append(await run_in_threadpool(service.enroll, iid, data, f.filename, f.content_type))
        except Exception as exc:  # noqa: BLE001
            reports.append({"file": f.filename, "error": str(exc)})
    return {"reports": reports}


class SampleIn(BaseModel):
    kind: str


@app.patch("/api/samples/{sid}", dependencies=[api])
def update_sample(sid: int, body: SampleIn):
    """Přepnutí výřezu mezi obličejem a tělem (otisk zůstává, mění se jen skupina pro porovnání)."""
    if body.kind not in ("face", "body"):
        raise HTTPException(400, "Druh musí být face nebo body.")
    with db.tx() as conn:
        if conn.execute("UPDATE samples SET kind = ? WHERE id = ?", (body.kind, sid)).rowcount == 0:
            raise HTTPException(404, "Výřez nenalezen.")
    get_service().reload()
    return {"ok": True, "kind": body.kind}


@app.delete("/api/samples/{sid}", dependencies=[api])
def delete_sample(sid: int):
    rows = db.query("SELECT crop_path FROM samples WHERE id = ?", (sid,))
    with db.tx() as conn:
        conn.execute("DELETE FROM samples WHERE id = ?", (sid,))
    if rows:
        media.media_path(rows[0]["crop_path"]).unlink(missing_ok=True)
    get_service().reload()
    return {"ok": True}


# ---------- rozpoznání ----------
@app.post("/api/identify", dependencies=[api])
async def identify(file: UploadFile = File(...)):
    data = await read_upload(file)
    service = get_service()
    try:
        if media.is_video(file.filename, file.content_type):
            result = await run_in_threadpool(service.identify_video, data, file.filename)
        else:
            result = await run_in_threadpool(service.identify_image, data, file.filename)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return web_result(result)


def web_result(result: dict) -> dict:
    """Pro zobrazení stačí náhledy (rámečky se kreslí v souřadnicích originálu, takže sedí dál)."""
    result = {**result, "media_url": media.thumb_url(result.get("media_url"), "m")}
    result["animals"] = [{**a, "crops": [{**c, "url": media.thumb_url(c["url"])} for c in a["crops"]]}
                         for a in result.get("animals", [])]
    return result


class ConfirmIn(BaseModel):
    individual_id: int
    animal_index: int | None = None
    learn: bool = True
    crop_kinds: list[str] | None = None  # přepsání druhu výřezů ("face"/"body"), ve stejném pořadí


@app.post("/api/identifications/{ident_id}/confirm", dependencies=[api])
async def confirm(ident_id: int, body: ConfirmIn):
    try:
        added = await run_in_threadpool(get_service().confirm, ident_id, body.individual_id,
                                        body.animal_index, body.learn, body.crop_kinds)
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from exc
    return {"added": added}


@app.get("/api/identifications", dependencies=[api])
def history(limit: int = 30):
    rows = db.query("""SELECT d.id, d.media_type, d.result_json, d.created_at, i.name AS confirmed_name
                       FROM identifications d LEFT JOIN individuals i ON i.id = d.confirmed_individual_id
                       ORDER BY d.id DESC LIMIT ?""", (limit,))
    out = []
    for r in rows:
        res = json.loads(r["result_json"])
        cands = (res.get("video") or {}).get("candidates") or \
            (res["animals"][0]["candidates"] if res.get("animals") else [])
        out.append({"id": r["id"], "media_type": r["media_type"], "created_at": r["created_at"],
                    "media_url": media.thumb_url(res.get("media_url")), "top": cands[0] if cands else None,
                    "confirmed_name": r["confirmed_name"]})
    return out


# ---------- stav a vyhodnocení ----------
@app.get("/api/status")
async def status(request: Request):
    pin_ok = not settings.pin or request.headers.get("x-pin") == settings.pin
    info = {"pin_required": bool(settings.pin), "pin_ok": pin_ok}
    if not pin_ok:
        return info
    s = await run_in_threadpool(get_service)  # po probuzení počká, než se načtou modely
    return {**info,
            "device": device_description(),
            "embedder": s.embedder.model_name, "finetuned": s.embedder.finetuned,
            "detector": s.detector.available, "detector_error": s.detector.error,
            "detector_weights": getattr(s.detector, "weights", None),
            "gallery_size": s.gallery.size(), "threshold": settings.unknown_threshold,
            "face_weight": settings.face_weight,
            "rebuild": s.rebuild_state,
            "individuals": db.query("SELECT COUNT(*) AS n FROM individuals")[0]["n"]}


@app.post("/api/evaluate", dependencies=[api])
async def evaluate():
    return await run_in_threadpool(get_service().evaluate)


class SettingsIn(BaseModel):
    threshold: float | None = None
    face_weight: float | None = None


@app.post("/api/settings", dependencies=[api])
def update_settings(body: SettingsIn):
    if body.threshold is not None:
        settings.unknown_threshold = max(0.0, min(1.0, body.threshold))
    if body.face_weight is not None:
        settings.face_weight = max(0.0, min(1.0, body.face_weight))
    settings_file().write_text(json.dumps({"threshold": settings.unknown_threshold,
                                           "face_weight": settings.face_weight}), encoding="utf-8")
    return {"threshold": settings.unknown_threshold, "face_weight": settings.face_weight}


@app.post("/api/reload-model", dependencies=[api])
async def reload_model():
    """Po doladění modelu (scripts/finetune.py) načte nový model a přepočítá galerii."""
    from .embedder import Embedder

    service = get_service()
    service.embedder = await run_in_threadpool(Embedder)
    service.ensure_embeddings(background=True)
    return {"model": service.embedder.model_id,
            "finetuned_file": str(finetuned_path(service.embedder.model_name))}


# ---------- soubory ----------
@app.get("/media/_t/{size}/{rel:path}")
def thumbnail(size: str, rel: str):
    path = media.thumb_path(size, rel)
    if path is None:
        raise HTTPException(404, "Náhled nenalezen.")
    return FileResponse(path, media_type="image/jpeg")


app.mount("/media", StaticFiles(directory=str(settings.media_dir), check_dir=False), name="media")


@app.get("/")
def index():
    return FileResponse(STATIC / "index.html", headers={"Cache-Control": "no-cache"})


app.mount("/", StaticFiles(directory=str(STATIC)), name="static")


def lan_addresses() -> list[str]:
    addrs = set()
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("10.255.255.255", 1))
        addrs.add(s.getsockname()[0])
        s.close()
    except OSError:
        pass
    return sorted(addrs)


def main():
    import argparse

    import uvicorn

    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--https", action="store_true", help="použít certifikát z certs/ (viz README)")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO)
    scheme = "https" if args.https else "http"
    print("\n  Hulmánek běží (neoficiální studentský projekt). Otevřete v telefonu (stejná Wi-Fi):")
    for a in lan_addresses():
        print(f"    {scheme}://{a}:{args.port}")
    print(f"  Na tomto počítači: {scheme}://localhost:{args.port}\n")
    ssl = {}
    if args.https:
        certs = ROOT / "certs"
        ssl = {"ssl_certfile": str(certs / "cert.pem"), "ssl_keyfile": str(certs / "key.pem")}
    uvicorn.run(app, host=args.host, port=args.port, **ssl)


if __name__ == "__main__":
    main()
