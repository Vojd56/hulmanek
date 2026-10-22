"""Běh na Modal.com (GPU T4, uspává se, když se nepoužívá). Nasazení: python deploy/modal_deploy.py

Galerie (databáze a fotky) leží na trvalém disku Modal Volume "hulmanek-data".
PIN je v Modal Secret "hulmanek" (HULMANY_PIN).
"""
from pathlib import Path

import modal

ROOT = Path(__file__).resolve().parent.parent
WORKDIR = "/root/hulmanek"
GPU = "T4"  # None = jen procesor (levnější, pomalejší, menší model)

env = {"HULMANY_DATA_DIR": "/data", "HULMANY_MODELS_DIR": "/data/models", "PYTHONUNBUFFERED": "1"}
if GPU:
    env |= {"HULMANY_EMBEDDER": "L-384", "HULMANY_DETECTOR_WEIGHTS": "yolov8x-worldv2.pt"}
else:
    env |= {"HULMANY_DEVICE": "cpu", "HULMANY_EMBEDDER": "B-224", "HULMANY_DETECTOR_WEIGHTS": "yolov8s-worldv2.pt"}

image = (
    modal.Image.debian_slim(python_version="3.12")
    .apt_install("libgl1", "libglib2.0-0")
    .pip_install("torch", "torchvision", index_url="https://download.pytorch.org/whl/cu124")
    .pip_install_from_requirements(str(ROOT / "requirements.txt"))
    .env(env)
    .workdir(WORKDIR)
    .add_local_dir(ROOT / "app", f"{WORKDIR}/app", copy=True, ignore=["__pycache__"])
    .add_local_file(ROOT / "deploy" / "warmup.py", f"{WORKDIR}/deploy/warmup.py", copy=True)
    # modely se stáhnou už do obrazu, aby probuzení netrvalo déle než nutné
    .run_commands(f"cd {WORKDIR} && HULMANY_DEVICE=cpu python deploy/warmup.py")
    .add_local_dir(ROOT / "static", f"{WORKDIR}/static")
)

volume = modal.Volume.from_name("hulmanek-data", create_if_missing=True)
app = modal.App("hulmanek")


@app.function(image=image, gpu=GPU, volumes={"/data": volume}, secrets=[modal.Secret.from_name("hulmanek")],
              scaledown_window=300, timeout=600, max_containers=1)
@modal.concurrent(max_inputs=8)
@modal.asgi_app()
def web():
    import sys

    sys.path.insert(0, WORKDIR)
    from app.main import app as fastapi_app

    return fastapi_app
