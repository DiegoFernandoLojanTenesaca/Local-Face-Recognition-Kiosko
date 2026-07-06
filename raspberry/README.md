# Kiosko en Raspberry Pi

La Raspberry corre **el mismo motor que el teléfono** (el servidor Python de `server/`).
No hay que portar nada: es Linux ARM, `onnxruntime` corre nativo.

## Compatibilidad

| Modelo | ¿Funciona? | Nota |
|---|---|---|
| **Pi 4 / 5** | ✅ Fluido | Recomendado |
| **Pi 3 / Zero 2 W** | ✅ Sí | Más lento pero usable (kiosko de 1 persona) |
| Pi 2 / Pi 1 / Zero (v1) | ⚠️ | 32-bit y poca CPU; no recomendado |

Requisito: **Raspberry Pi OS de 64-bit** (para el `onnxruntime` de aarch64) y una
**cámara** (USB webcam o módulo CSI habilitado).

## Instalación

```bash
git clone https://github.com/DiegoFernandoLojanTenesaca/Local-Face-Recognition-Kiosko.git
cd Local-Face-Recognition-Kiosko
bash raspberry/install.sh
```

## Arrancar

```bash
source ~/lfrk-venv/bin/activate
python server/face_api.py                       # servidor en :8090
# en otra terminal / al iniciar el escritorio:
chromium-browser --kiosk http://localhost:8090/kiosk
```

Abre `http://localhost:8090/admin` para enrolar personas y ver reportes.

## Arranque automático (opcional)

**1) Servicio del servidor** — crea `/etc/systemd/system/lfrk.service`:

```ini
[Unit]
Description=Local Face Recognition Kiosko
After=network.target

[Service]
User=pi
ExecStart=/home/pi/lfrk-venv/bin/python /home/pi/Local-Face-Recognition-Kiosko/server/face_api.py
Restart=always

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl enable --now lfrk
```

**2) Chromium en kiosko al iniciar el escritorio** — en
`~/.config/lxsession/LXDE-pi/autostart` agrega:

```
@chromium-browser --kiosk --noerrdialogs --disable-infobars http://localhost:8090/kiosk
```

Con eso la Pi arranca sola como kiosko de asistencia.

## ¿Y el ESP32-CAM?

Si además tienes un **ESP32-CAM**, puede actuar como cámara remota que le manda la
foto a esta Raspberry (o al teléfono) para reconocer. Ver [`../esp32-cam/`](../esp32-cam/).
