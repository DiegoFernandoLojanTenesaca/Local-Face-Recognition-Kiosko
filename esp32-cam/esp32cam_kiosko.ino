// ============================================================================
//  Local Face Recognition Kiosko — firmware ESP32-CAM (AI-Thinker)
//  El ESP32-CAM es el "ojo": captura una foto y la envía por WiFi al servidor
//  (teléfono / Raspberry / PC que corre server/face_api.py). El servidor hace
//  el reconocimiento y responde; el ESP enciende un LED / activa un relé.
//
//  Placa: "AI Thinker ESP32-CAM" · Arduino-ESP32 core.
// ============================================================================
#include "esp_camera.h"
#include <WiFi.h>
#include <HTTPClient.h>

// ---------- CONFIGURA ESTO ----------
const char* SSID     = "TU_WIFI";
const char* PASS     = "TU_CLAVE";
const char* SERVER   = "http://192.168.1.50:8090/esp_mark";  // IP del servidor (teléfono/Pi/PC)
const int   PERIODO  = 4000;   // ms entre capturas (o usa un botón)
const int   PIN_OK   = 12;     // pin que se activa al reconocer (relé / LED verde)
// ------------------------------------

// Pines de cámara del módulo AI-Thinker
#define PWDN_GPIO_NUM 32
#define RESET_GPIO_NUM -1
#define XCLK_GPIO_NUM 0
#define SIOD_GPIO_NUM 26
#define SIOC_GPIO_NUM 27
#define Y9_GPIO_NUM 35
#define Y8_GPIO_NUM 34
#define Y7_GPIO_NUM 39
#define Y6_GPIO_NUM 36
#define Y5_GPIO_NUM 21
#define Y4_GPIO_NUM 19
#define Y3_GPIO_NUM 18
#define Y2_GPIO_NUM 5
#define VSYNC_GPIO_NUM 25
#define HREF_GPIO_NUM 23
#define PCLK_GPIO_NUM 22

void setup() {
  Serial.begin(115200);
  pinMode(PIN_OK, OUTPUT); digitalWrite(PIN_OK, LOW);

  camera_config_t c = {};
  c.ledc_channel = LEDC_CHANNEL_0; c.ledc_timer = LEDC_TIMER_0;
  c.pin_d0=Y2_GPIO_NUM; c.pin_d1=Y3_GPIO_NUM; c.pin_d2=Y4_GPIO_NUM; c.pin_d3=Y5_GPIO_NUM;
  c.pin_d4=Y6_GPIO_NUM; c.pin_d5=Y7_GPIO_NUM; c.pin_d6=Y8_GPIO_NUM; c.pin_d7=Y9_GPIO_NUM;
  c.pin_xclk=XCLK_GPIO_NUM; c.pin_pclk=PCLK_GPIO_NUM; c.pin_vsync=VSYNC_GPIO_NUM;
  c.pin_href=HREF_GPIO_NUM; c.pin_sccb_sda=SIOD_GPIO_NUM; c.pin_sccb_scl=SIOC_GPIO_NUM;
  c.pin_pwdn=PWDN_GPIO_NUM; c.pin_reset=RESET_GPIO_NUM;
  c.xclk_freq_hz=20000000; c.pixel_format=PIXFORMAT_JPEG;
  // VGA (640x480) es suficiente para el detector y no satura la red
  c.frame_size=FRAMESIZE_VGA; c.jpeg_quality=12; c.fb_count=1;

  if (esp_camera_init(&c) != ESP_OK) { Serial.println("Error init camara"); return; }

  WiFi.begin(SSID, PASS);
  Serial.print("Conectando WiFi");
  while (WiFi.status() != WL_CONNECTED) { delay(400); Serial.print("."); }
  Serial.println("\nWiFi OK: " + WiFi.localIP().toString());
}

void loop() {
  camera_fb_t* fb = esp_camera_fb_get();          // captura JPEG
  if (!fb) { Serial.println("captura fallo"); delay(500); return; }

  HTTPClient http;
  http.begin(SERVER);
  http.addHeader("Content-Type", "image/jpeg");
  int code = http.POST(fb->buf, fb->len);         // envía el JPEG crudo
  String resp = code > 0 ? http.getString() : String("(sin conexion)");
  http.end();
  esp_camera_fb_return(fb);

  Serial.printf("HTTP %d -> %s\n", code, resp.c_str());

  // Respuesta tipo: {"name":"Juan","marked":true,"tipo":"entrada","time":"08:15"}
  if (resp.indexOf("\"marked\":true") >= 0) {
    int i = resp.indexOf("\"name\":\"");
    String nombre = i >= 0 ? resp.substring(i + 8, resp.indexOf("\"", i + 8)) : "?";
    Serial.println("  ✓ MARCADO: " + nombre);
    digitalWrite(PIN_OK, HIGH); delay(1200); digitalWrite(PIN_OK, LOW);   // pulso relé/LED
  }
  delay(PERIODO);
}
