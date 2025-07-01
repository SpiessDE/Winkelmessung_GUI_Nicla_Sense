# Nicla Bell Viewer – Modulübersicht

Dieses Dokument gibt einen kompakten Überblick über die Architektur und die einzelnen Komponenten der Web-App.

---

## 📂 Projektstruktur

```
/home/probell/
├── winkelmessung/venv/  
└── Winkelmessung_GUI_Nicla_Sense/
    ├── app.py                  # Flask-Server und HTTP/API-Routen
    ├── serial_core.py          # USB-Serial-Backend & Kalibrierungs-Hook
    ├── data_processor.py       # Quaternion→Euler/Matrix, Ratenmessung
    ├── calibration.py          # Ruhe-, Swing- und Nullpunkt-Kalibrierung
    └── templates/index.html    # Minimalistisches Browser-Frontend mit SSE
```

---

## 🖥️ app.py

**Aufgabe:**  
Startet den Flask-Webserver, stellt Seiten und JSON-APIs bereit und liefert per **Server-Sent Events (SSE)** Live-Daten an den Browser.

**Hauptfunktionen:**
- `/` → Hauptseite mit Steuer-Buttons und Live-Anzeige  
- `/stream` → SSE-Endpoint für Echtzeit-Daten  
- `/api/swing`, `/api/confirm`, `/api/null` → Endpoints zum Auslösen der Kalibrierungs‑Phasen  

---

## 🔌 serial_core.py

**Aufgabe:**  
Liest den seriellen Port, parst eingehende Quaternion-Daten und leitet sie an den **DataProcessor** weiter. Außerdem werden Kalibrierungs‑Status‑Events in die Queue gepusht.

---

## 🔄 data_processor.py

**Aufgabe:**  
Verarbeitet rohe Quaternionen zu:
1. kalibrierten Euler-Winkeln (Roll/Pitch/Yaw)  
2. Rotationsmatrix  
3. Paket- und Sample-Rate über 2‑Sekunden‑Fenster  

liefert alle Ergebnisse als Python-Dict an die Queue.

---

## 🧰 calibration.py

**Aufgabe:**  
Implementiert zwei Modi:
1. **Swing-Kalibrierung** (Baseline‑Mittelung + PCA + Offset)  
2. **Nullpunkt-Kalibrierung** (einfacher Mittel‑Rollwinkel)

---

## 🌐 templates/index.html

**Aufgabe:**  
Einfaches HTML/JS‑Frontend zur Bedienung:
- Buttons für Kalibrierung  
- Live-Anzeige (Sekunden, Roll, Pitch, Yaw, Status)  
- **Server-Sent Events** zum Empfangen der Echtzeit-Daten

---

## 📋 Zusammenfassung

1. **SerialCore** → Echtzeit-Lesen und Weiterleitung der Sensordaten  
2. **DataProcessor** → Umrechnung zu Winkeln, Matrizen & Raten  
3. **Calibration** → Automatisierte Ruhe-, Swing- und Nullpunkt-Kalibrierung  
4. **Flask-App** (`app.py`) → HTTP-Server & SSE  
5. **Browser-Frontend** (`index.html`) → Steuerung und Live-Darstellung  

Jedes Modul ist schlank gehalten und über klar definierte Schnittstellen verbunden. Detaillierten Code findest du im Repository.
