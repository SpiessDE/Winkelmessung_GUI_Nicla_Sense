// Quaternion_UART.ino
// Nicla Sense ME → Raspberry Pi Zero 2 W per UART (115 200 Bd)
// Sendet Quaternionen als CSV‑Zeile:  millis,qx,qy,qz,qw   bei 50 Hz
//
// Verbindungen
// ───────────────────────────────────────────────────────────────
//   Nicla VIN      ↔ Pi 5 V (Pin 4)          (gemeinsames Netzteil)
//   Nicla GND      ↔ Pi GND (Pin 6)
//   Nicla D0 (RX)  ↔ Pi GPIO14 TX (Pin 8)
//   Nicla D1 (TX)  ↔ Pi GPIO15 RX (Pin 10)
//
// Bibliotheken:  Nicla_System • Arduino_BHY2 (Board‑Manager „Nicla“)
//
// Erstellt 2025‑06‑25 – nur UART, kein BLE.

#include "Nicla_System.h"
#include "Arduino_BHY2.h"

// ───────────────────────────────────────────────────────────────
// Konfiguration
// ───────────────────────────────────────────────────────────────
constexpr uint32_t BAUDRATE         = 115200;  // UART‑Geschwindigkeit
constexpr uint32_t SAMPLE_PERIOD_MS = 20;      // 50 Hz  (1 000 ms / 50)
constexpr uint32_t LED_BLINK_MS     = 100;     // Herzschlag‑LED

// Bosch Sensor‑Hub ➜ Rotation‑Vector (Quaternion)
SensorQuaternion rotationVec(SENSOR_ID_RV);

// ───────────────────────────────────────────────────────────────
void setup()
{
  // USB‑Serial (für Debug über den PC, optional)
  Serial.begin(BAUDRATE);
  while (!Serial);
  Serial.println("Nicla Sense ME – Quaternion UART mode");

  // Hardware‑UART1 für den Raspberry Pi
  Serial1.begin(BAUDRATE);

  // Nicla‑Init & LED
  nicla::begin();
  nicla::leds.begin();
  nicla::leds.setColor(0, 255, 0);   // dauergrün

  // Bosch BHY2‑Sensor‑Hub initialisieren (Standalone‑Modus)
  BHY2.begin(NICLA_STANDALONE);
  rotationVec.begin(50, 0);          // 50 Hz Output, keine Latenz
}

// ───────────────────────────────────────────────────────────────
void loop()
{
  static uint32_t lastSend  = 0;
  static uint32_t lastBlink = 0;
  static bool     ledOn     = false;

  // Herzschlag‑LED blinken lassen
  if (millis() - lastBlink >= LED_BLINK_MS) {
    lastBlink = millis();
    ledOn     = !ledOn;
    nicla::leds.setColor(0, ledOn ? 255 : 0, 0);  // grün an/aus
  }

  // Sensor‑Hub Update (holt FIFO‑Daten)
  BHY2.update();

  // Neue Quaternion verfügbar?
  if (!rotationVec.dataAvailable()) return;
  rotationVec.clearDataAvailFlag();

  uint32_t now = millis();
  if (now - lastSend < SAMPLE_PERIOD_MS) return; // 50 Hz‑Limit
  lastSend = now;

  // Werte lesen
  float qx = rotationVec.x();
  float qy = rotationVec.y();
  float qz = rotationVec.z();
  float qw = rotationVec.w();

  // ▶ Ausgabe über USB‑Serial (nur Debug, kann entfallen)
  Serial.print(now);  Serial.print(',');
  Serial.print(qx, 6); Serial.print(',');
  Serial.print(qy, 6); Serial.print(',');
  Serial.print(qz, 6); Serial.print(',');
  Serial.println(qw, 6);

  // ▶ Ausgabe über UART1 an den Pi
  Serial1.print(now);  Serial1.print(',');
  Serial1.print(qx, 6); Serial1.print(',');
  Serial1.print(qy, 6); Serial1.print(',');
  Serial1.print(qz, 6); Serial1.print(',');
  Serial1.println(qw, 6);
}
