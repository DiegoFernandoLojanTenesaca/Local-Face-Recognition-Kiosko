#!/usr/bin/env bash
# ============================================================================
#  Local Face Recognition Kiosko — instalación en Raspberry Pi
#  Compatible con Pi 3 / 4 / 5 / Zero 2 W (Raspberry Pi OS 64-bit).
#  La Pi corre el MISMO motor que el teléfono (server/ en Python).
# ============================================================================
set -e
REPO="$(cd "$(dirname "$0")/.." && pwd)"

echo "==> Paquetes del sistema…"
sudo apt-get update
sudo apt-get install -y python3-pip python3-venv chromium-browser \
                        libatlas-base-dev libjpeg-dev curl

echo "==> Entorno Python…"
python3 -m venv "$HOME/lfrk-venv"
# shellcheck disable=SC1091
source "$HOME/lfrk-venv/bin/activate"
pip install --upgrade pip
pip install flask pillow numpy onnxruntime

echo "==> Descargando modelos ONNX (a las rutas que espera el motor)…"
MD="$HOME/face_models_s"; SP="$HOME/spoof_models"
mkdir -p "$MD" "$SP"
curl -sL -o "$MD/detection.onnx"   "https://huggingface.co/immich-app/buffalo_s/resolve/main/detection/model.onnx"
curl -sL -o "$MD/recognition.onnx" "https://huggingface.co/immich-app/buffalo_s/resolve/main/recognition/model.onnx"
curl -sL -o "$SP/as.onnx"          "https://github.com/hairymax/Face-AntiSpoofing/raw/main/saved_models/AntiSpoofing_bin_1.5_128.onnx"

echo
echo "===================================================================="
echo " Listo. Para arrancar el kiosko en la Raspberry:"
echo
echo "   source ~/lfrk-venv/bin/activate"
echo "   python $REPO/server/face_api.py       # servidor en :8090"
echo
echo " Y en la Pi (con cámara USB/CSI conectada), abre el navegador:"
echo "   chromium-browser --kiosk http://localhost:8090/kiosk"
echo
echo " (localhost = contexto seguro → la cámara funciona)"
echo "===================================================================="
