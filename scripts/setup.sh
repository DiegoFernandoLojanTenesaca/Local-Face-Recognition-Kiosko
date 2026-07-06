#!/usr/bin/env bash
# Prepara el proyecto tras clonar: dependencias, runtime WASM y modelos.
set -e
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT/faceapp"

echo "==> Instalando dependencias npm (Capacitor + onnxruntime-web)…"
npm install

echo "==> Copiando runtime onnxruntime-web (js + wasm) a www/ort/…"
mkdir -p www/ort
cp node_modules/onnxruntime-web/dist/ort.min.js www/ort/
cp node_modules/onnxruntime-web/dist/*.wasm     www/ort/
cp node_modules/onnxruntime-web/dist/*.mjs      www/ort/ 2>/dev/null || true

echo "==> Descargando modelos ONNX…"
bash "$ROOT/scripts/download-models.sh"

echo
echo "Listo. Para compilar el APK:"
echo "  cd faceapp"
echo "  export ANDROID_HOME=\$HOME/Android/Sdk"
echo "  npx cap sync android && (cd android && ./gradlew assembleDebug)"
echo "  # APK en faceapp/android/app/build/outputs/apk/debug/app-debug.apk"
