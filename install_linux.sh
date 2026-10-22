#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
python3 -m venv .venv
. .venv/bin/activate
pip install --upgrade pip
if command -v nvidia-smi >/dev/null; then
  pip install torch torchvision --index-url https://download.pytorch.org/whl/cu126
fi
pip install -r requirements.txt
python -c "import torch; print('GPU:', torch.cuda.is_available())"
echo "Hotovo. Spuštění: ./start_linux.sh"
