# Obraz pro Hugging Face Spaces (Docker, jen procesor). Na PC v zoo se nepoužívá.
FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends libgl1 libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*
RUN useradd -m -u 1000 user
USER user
ENV HOME=/home/user PATH=/home/user/.local/bin:$PATH PYTHONUNBUFFERED=1 \
    HULMANY_DEVICE=cpu HULMANY_EMBEDDER=B-224 HULMANY_DETECTOR_WEIGHTS=yolov8s-worldv2.pt \
    YOLO_CONFIG_DIR=/home/user/.config/Ultralytics
WORKDIR /home/user/app

COPY --chown=user requirements.txt .
RUN pip install --no-cache-dir --user torch torchvision --index-url https://download.pytorch.org/whl/cpu \
    && pip install --no-cache-dir --user -r requirements.txt

COPY --chown=user . .
# modely se stáhnou už při sestavení, aby start po probuzení netrval dlouho
RUN python deploy/warmup.py

EXPOSE 7860
CMD ["python", "-m", "app.main", "--port", "7860"]
