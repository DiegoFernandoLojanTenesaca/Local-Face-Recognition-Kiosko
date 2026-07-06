#!/usr/bin/env bash
# Descarga los 3 modelos ONNX del sistema a faceapp/www/models/
# (no se versionan en git por su tamaño; ~17 MB en total)
set -e
DIR="$(cd "$(dirname "$0")/.." && pwd)/faceapp/www/models"
mkdir -p "$DIR"

echo "Descargando detección (SCRFD, InsightFace buffalo_s)…"
curl -sL -o "$DIR/detection.onnx"   "https://huggingface.co/immich-app/buffalo_s/resolve/main/detection/model.onnx"
echo "Descargando reconocimiento (ArcFace/MobileFaceNet, buffalo_s)…"
curl -sL -o "$DIR/recognition.onnx" "https://huggingface.co/immich-app/buffalo_s/resolve/main/recognition/model.onnx"
echo "Descargando anti-spoofing (MiniFASNet, hairymax/Face-AntiSpoofing)…"
curl -sL -o "$DIR/anti_spoof.onnx"  "https://github.com/hairymax/Face-AntiSpoofing/raw/main/saved_models/AntiSpoofing_bin_1.5_128.onnx"

echo "Modelos listos en $DIR:"
ls -lh "$DIR"
