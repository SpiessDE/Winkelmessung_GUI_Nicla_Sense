# Schwing-Kalibrierung – Physikalische Hintergründe und Code-Umsetzung

Diese Dokumentation erklärt detailliert die **Schwing-Kalibrierung** (Swing Calibration) des Nicla Sense ME auf der Glocke. Sie beschreibt zum einen die physikalischen und mathematischen Grundlagen und zum anderen deren konkrete Umsetzung im Python‑Code.
Mathematische Hintergründe zu Quaternionen: https://ekunzeweb.de/PAPERS/Mathematische%20Grundlagen%20der%20Quaternionen.pdf
---

## 1. Ziel der Schwing-Kalibrierung

Bei der Messung des Läutewinkels einer Glocke mit einem IMU-Board stimmt die Ausrichtung des Sensors oft nicht exakt mit der physischen Drehachse der Glocke überein. Die **Schwing-Kalibrierung** richtet das Mess-Koordinatensystem so aus, dass:

- die dominante Schwingbewegung (links/rechts) entlang der X‑Achse (Roll) erfolgt  
- alle Rotationskomponenten um andere Achsen minimiert werden  

Dadurch wird die Messung des Läutewinkels präziser und die nachfolgenden Berechnungen (Euler‑Winkel, Rotationsmatrix, 2D‑Plot) konsistent.

---

## 2. Physikalischer Hintergrund

1. **Quaternionen**  
   - Ein Quaternion `q = [w, x, y, z]` repräsentiert eine 3D‑Rotation.  
   - Der Sensor liefert fortlaufend Quaternion‑Messungen `q_i`.

2. **Relativer Drehvektor (Angular Velocity Approximation)**  
   - Die Änderung zwischen zwei Quaternionen  
     ```text
     Δq = q_{i+1} · q_i^{-1}
     ```  
     beschreibt eine kleine Rotationsbe‐ wegung.  
   - Wir schreiben Δq als `(w, v)` mit v = [x, y, z].  
   - Der zugehörige Rotationswinkel θ berechnet sich zu  
     ```text
     θ = 2 · arctan2(‖v‖, w)
     ```  
   - Der Rotationsvektor (Proportional zur Winkelgeschwindigkeit) ist  
     ```text
     ω = (v / ‖v‖) · θ
     ```

3. **Hauptkomponentenanalyse (PCA)**  
   - Beim Anschwingen erzeugt die dominante Modus der Glocke (links‑rechts) die stärksten ω-Vektoren.  
   - Mittels Singulärwertzerlegung (SVD) auf der Matrix dieser ω-Vektoren wird die **erste Hauptkomponente** (erster Singulärvektor) als dominante Schwing-Achse bestimmt.

---

## 3. Umsetzung im Code (calibration.py)

Die Schwing‑Kalibrierung erfolgt in drei Phasen:

### 3.1 Phase 1: Basis‑Mittelung (Stillstand)

- **Ziel:** Erfassung der Grundorientierung `q_base`, solange die Glocke ruhigsteht.  
- **Vorgehen im Code:**
  ```python
  # Sammlung ruhender Quaternions
  qs_base = []
  def collect_base(q): qs_base.append(q)
  callback("please_hold_baseline")
  self._collecting = True; self._collector = collect_base
  time.sleep(base_dur)   # z.B. 0.5 s
  self._collecting = False; self._collector = None

  # Mittelwert-Quaternion bestimmen
  if qs_base:
      q_avg = _quat_avg(qs_base)
      self.q_base = q_avg.inverse.normalised
  callback("baseline_done")
  ```

### 3.2 Phase 2: Swing + PCA

- **Ziel:** Ermittlung der dominanten Schwingachse.  
- **Vorgehen im Code:**
  ```python
  qs_swing = []
  def collect_swing(q): qs_swing.append(q)
  callback("please_swing")
  self._collecting = True; self._collector = collect_swing

  # in Hintergrundthread: Countdown + Sammeln
  for rem in range(int(swing_dur),0,-1):
      callback(f"{rem} s verbleiben")
      time.sleep(1)
  self._collecting = False; self._collector = None

  # Alle Samples auf Basis-Orientierung korrigieren
  corrected = [self.q_base * q for q in qs_swing]

  # Δ-Quaternions und Rotationsvektoren berechnen
  omegas = []
  for a, b in zip(corrected, corrected[1:]):
      dq = b * a.inverse
      v  = np.array(dq.vector)
      theta = 2 * np.arctan2(np.linalg.norm(v), dq.w)
      if np.linalg.norm(v) > 1e-6:
          omegas.append((v/np.linalg.norm(v)) * theta)

  # PCA per SVD → dominante Achse
  if omegas:
      _, _, vt = np.linalg.svd(np.vstack(omegas), full_matrices=False)
      self.axis = vt[0]
  else:
      self.axis = np.array([1.0, 0.0, 0.0])

  # Quaternion, die Achse auf X‑Achse abbildet
  self.q_axis = _quat_between(self.axis, np.array([1,0,0])).normalised
  callback("swing_pca_done")
  ```

### 3.3 Phase 3: Offset‑Baseline (Roll‑Nullpunkt)

- **Ziel:** Bestimmung des tatsächlichen Roll‑Nullpunkts in ruhiger Stellung.  
- **Vorgehen im Code:**
  ```python
  qs_off = []
  def collect_offset(q): qs_off.append(q)
  callback("please_hold_offset")
  self._collecting = True; self._collector = collect_offset

  # nach offset_dur (z.B. 0.5 s)
  time.sleep(offset_dur)
  self._collecting = False; self._collector = None

  # korrigierte Quaternions anwenden
  corr = [(self.q_axis * (self.q_base * q)) for q in qs_off]
  rolls = [qc.yaw_pitch_roll[2] for qc in corr]
  mean_roll = float(np.mean(rolls)) if rolls else 0.0

  # manuellen Roll-Offset setzen
  self.set_manual_roll(mean_roll)
  callback("swing_done")
  ```

---

## 4. GUI-Interaktion

1. **Schwing-Kalib**  
   - Startet automatisch alle drei Phasen.  
   - GUI-Statusmeldungen:  
     - `please_hold_baseline` → Sammeln der Ruhedaten  
     - `baseline_done` → Start der Swing-Daten  
     - `please_swing` → Glocke anschwingen (Countdown)  
     - `swing_pca_done` → PCA abgeschlossen  
     - `please_hold_offset` → Sammeln der Offset-Daten  
     - `swing_done` → Kalibrierung fertig  

2. **Messwert-Anpassung**  
   - Künftige rohen Quaternionen `q_raw` werden angewendet durch  
     ```
     q_cal = q_offset * q_axis * q_base * q_raw
     ```  
   - Die X‑Komponente (Roll) von `q_cal` liefert den kalibrierten Läutewinkel.

---

**Parameter**  
- `base_dur` (Stille-Mittelung): Standard 0.5 s  
- `swing_dur` (PCA-Phase): typ. 10 s  
- `offset_dur` (Offset-Mittelung): Standard 0.5 s  

Jede Phase lässt sich flexibel anpassen, um auf verschieden schwere Glocken und Befestigungen zu reagieren.  
