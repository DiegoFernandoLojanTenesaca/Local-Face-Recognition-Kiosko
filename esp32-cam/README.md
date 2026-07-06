# ESP32-CAM como cámara de reconocimiento (~$8)

El **ESP32-CAM** es el hardware más barato para meter visión en un microcontrolador.
No hace el reconocimiento él mismo (no le da la RAM para modelos grandes): actúa como
**cámara inteligente** que captura una foto y se la manda por WiFi al **servidor**
(el teléfono, una Raspberry Pi o una PC corriendo `server/face_api.py`). El servidor
reconoce y responde; el ESP enciende un LED o **activa un relé** (por ejemplo, abrir una puerta).

```
 ESP32-CAM ──foto (WiFi/HTTP)──► servidor (motor de IA) ──► "Juan, entrada"
     ▲                                                          │
     └──────────── activa relé / LED ◄─────── marcado ──────────┘
```

## Por qué así (y no todo en el ESP32)

| Enfoque | Precisión | Complejidad |
|---|---|---|
| **ESP32-CAM = cámara → servidor** *(este)* | **Alta** (el mismo motor del teléfono) | Baja — solo capturar y enviar |
| ESP32 standalone con `esp-who` | Básica (pocas caras, controlado) | Alta — otro proyecto aparte |

Para estudiantes: este enfoque cuesta ~$8 (ESP32-CAM) y **reutiliza el servidor que ya
tienes** — incluso un teléfono viejo o una Raspberry pueden ser el "cerebro".

## Hardware

- **ESP32-CAM** (AI-Thinker, con cámara OV2640)
- Para programarlo: un **ESP32-CAM-MB** (base USB) o un adaptador **FTDI** (USB-serie)
- Opcional: un **relé** o LED en el pin `PIN_OK` (por defecto GPIO 12) para abrir puerta / avisar

## Cargar el firmware

1. En **Arduino IDE**: instala el soporte de placas ESP32 (Boards Manager → `esp32` de Espressif).
2. Placa: **AI Thinker ESP32-CAM**. Partición: *Huge APP*.
3. Abre [`esp32cam_kiosko.ino`](esp32cam_kiosko.ino) y edita arriba:
   ```cpp
   const char* SSID   = "TU_WIFI";
   const char* PASS   = "TU_CLAVE";
   const char* SERVER = "http://192.168.1.50:8090/esp_mark";  // IP del servidor
   ```
   > La IP es la del equipo que corre `server/face_api.py` (teléfono/Pi/PC), en la misma red WiFi.
4. Conecta, pon el ESP32-CAM en modo carga (GPIO0 a GND en placas FTDI), sube, y quita GPIO0-GND.
5. Abre el **Monitor Serie** (115200) para ver las respuestas (`✓ MARCADO: Juan`).

## Enrolar las caras

El ESP32 solo **marca**. Para **enrolar** personas usa el panel del servidor
(`http://<IP-servidor>:8090/admin`) desde un navegador — igual que en el teléfono.

## Endpoint que usa

`POST /esp_mark` — recibe el JPEG crudo en el cuerpo (`Content-Type: image/jpeg`) y
responde `{"name": "...", "marked": true, "tipo": "entrada", "time": "08:15"}`.
