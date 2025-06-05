# calibration.py

import threading
import time
import numpy as np
from pyquaternion import Quaternion

def _quat_avg(qs: list[Quaternion]) -> Quaternion:
    """
    Mittelt eine Liste von Quaternionen über ihren Outer-Product,
    liefert die normalisierte Hauptkomponente zurück.
    """
    M = sum(np.outer(q.elements, q.elements) for q in qs) / len(qs)
    vals, vecs = np.linalg.eigh(M)
    return Quaternion(vecs[:, vals.argmax()]).normalised

def _quat_between(v0: np.ndarray, v1: np.ndarray) -> Quaternion:
    """
    Erzeugt die kürzeste Rotation, die Vektor v0 auf v1 abbildet.
    """
    v0 = v0 / np.linalg.norm(v0)
    v1 = v1 / np.linalg.norm(v1)
    d = np.dot(v0, v1)
    if d < -0.999999:
        # antiparallel: beliebige orthogonale Achse wählen
        axis = np.cross([1, 0, 0], v0)
        if np.linalg.norm(axis) < 1e-6:
            axis = np.cross([0, 1, 0], v0)
        return Quaternion(axis=axis / np.linalg.norm(axis), angle=np.pi)
    axis = np.cross(v0, v1)
    return Quaternion(1 + d, *axis).normalised

class Calibration:
    """
    Kombinierte Swing-Kalibrierung plus neue Nullpunkt-Kalibrierung (alle drei Achsen).
    - start_swing(duration, callback, base_dur=0.5, offset_dur=0.5):
        führt dreiphasig eine Swing-Kalibrierung durch (Basis, PCA, Offset).
    - confirm_baseline(duration, callback):
        dient als dritte Phase der Swing-Kalibrierung, berechnet den Roll-Offset.
    - start_nullpoint(duration, callback):
        misst für 'duration' Sekunden die aktuelle Orientierung (bereinigt um
        q_base und q_axis) und setzt einen neuen Offset-Quaternion so, dass
        alle Achsen (Roll/Pitch/Yaw) auf 0° stehen. Ohne PCA.
    """

    def __init__(self):
        # bestehende Zustände für Swing-Kalib
        self.q_base = Quaternion()       # Basis-Quaternion (Ruhelage)
        self.axis   = np.array([1.0,0.0,0.0])  # Achse aus PCA
        self.q_axis = Quaternion()       # Quaternion, die 'axis' auf X-Standard (1,0,0) bringt
        self.roll_offset_angle = 0.0     # Roll-Offset (für Swing-Baseline)
        self.q_offset = Quaternion()     # Quaternion, um den Roll-Offset zu kompensieren

        # interner Zustand
        self._collecting = False
        self._collector  = None
        self._baseline_qs = []
        self._swing_qs    = []

    def start_swing(self,
                    swing_dur: float,
                    callback: callable = None,
                    base_dur: float   = 0.5,
                    offset_dur: float = 0.5):
        """
        Dreiphasige Swing-Kalibrierung:
         1) Basis-Mittelung (still) → q_base
         2) Swing + PCA → q_axis
         3) Offset-Baseline → q_offset (nur Roll)
        callback erhält Status-Texte:
          "please_hold_baseline" →  Nutzer soll stillhalten (base_dur)
          "baseline_done"        →  Basis eingeholt
          "please_swing"         →  Nutzer soll Glocke schwingen (swing_dur)
          "{n} s verbleiben"     →  Countdown
          "swing_pca_done"       →  PCA fertig, jetzt stillhalten
          "please_hold_offset"   →  Offset-Baseline (offset_dur)
          "swing_done"           →  Swing-Kalib abgeschlossen
        """
        # --- Phase 1: Basis-Mittelung ---
        self._baseline_qs = []
        def collect_base(q):
            self._baseline_qs.append(q)

        if callback: callback("please_hold_baseline")
        self._collecting = True
        self._collector  = collect_base
        time.sleep(base_dur)
        self._collecting = False
        self._collector  = None

        if self._baseline_qs:
            q_avg       = _quat_avg(self._baseline_qs)
            self.q_base = q_avg.inverse.normalised
        if callback: callback("baseline_done")

        # --- Phase 2: Swing + PCA ---
        self._swing_qs = []
        def collect_swing(q):
            self._swing_qs.append(q)

        if callback: callback("please_swing")
        self._collecting = True
        self._collector  = collect_swing

        def _pca_job():
            # Countdown während Swing
            for rem in range(int(swing_dur), 0, -1):
                if callback:
                    callback(f"{rem} s verbleiben")
                time.sleep(1)

            self._collecting = False
            self._collector  = None

            # korrigiere Swing-Qs mit Basis
            corrected = [self.q_base * q for q in self._swing_qs]
            omegas = []
            for a, b in zip(corrected, corrected[1:]):
                dq  = b * a.inverse
                v   = np.array(dq.vector)
                ang = 2 * np.arctan2(np.linalg.norm(v), dq.w)
                if np.linalg.norm(v) > 1e-6:
                    omegas.append((v / np.linalg.norm(v)) * ang)

            if omegas:
                _, _, vt = np.linalg.svd(np.vstack(omegas), full_matrices=False)
                self.axis = vt[0]
            else:
                self.axis = np.array([1.0, 0.0, 0.0])

            self.q_axis = _quat_between(self.axis, np.array([1.0,0.0,0.0])).normalised
            if callback: callback("swing_pca_done")

        threading.Thread(target=_pca_job, daemon=True).start()

        # --- Phase 3: Offset-Baseline (Roll) ---
        def _offset_starter():
            # Warte bis PCA fertig (callback sendet "swing_pca_done")
            # und führe dann confirm_baseline durch
            self.confirm_baseline(offset_dur, callback)

        threading.Thread(target=_offset_starter, daemon=True).start()

    def confirm_baseline(self, offset_dur: float, callback=None):
        """
        Offset-Baseline für Swing-Kalibrierung (Roll-Nullpunkt).
        callback erhält:
          "please_hold_offset" →  Nutzer soll stillhalten (offset_dur)
          "swing_done"         →  Swing-Kalibrierung vollständig abgeschlossen
        """
        self._baseline_qs = []
        def collect_offset(q):
            self._baseline_qs.append(q)

        if callback: callback("please_hold_offset")
        self._collecting = True
        self._collector  = collect_offset

        def _offset_job():
            time.sleep(offset_dur)
            self._collecting = False
            self._collector  = None

            # Korrigiere jede Baseline-Quaternion: zuerst Basis → dann Achse
            corrected = [(self.q_axis * (self.q_base * q)) for q in self._baseline_qs]
            rolls = [qc.yaw_pitch_roll[2] for qc in corrected]
            roll_mean = float(np.mean(rolls)) if rolls else 0.0
            self.set_manual_roll(roll_mean)

            if callback: callback("swing_done")

        threading.Thread(target=_offset_job, daemon=True).start()

    def start_nullpoint(self, null_dur: float, callback=None):
        """
        Neue „Nullpunkt-Kalibrierung“ (alle 3 Achsen) für 'null_dur' Sekunden:
        - Misst aktuelle Quaternions (bereinigt um q_base und q_axis)
        - Mittelt sie, berechnet den Mittelwert-Q,
          und setzt q_offset = inverse(Mittelwert-Q),
          so dass in dieser Pose Roll/Pitch/Yaw = 0° sind.
        callback erhält:
          "please_hold_null" →  Nutzer soll in Null-Pose stillhalten
          "null_done"        →  Nullpunkt-Kalibrierung abgeschlossen
        """
        self._baseline_qs = []
        def collect_null(q):
            # q: Roh-Quaternion
            self._baseline_qs.append(q)

        if callback: callback("please_hold_null")
        self._collecting = True
        self._collector  = collect_null

        def _null_job():
            time.sleep(null_dur)
            self._collecting = False
            self._collector  = None

            # Korrigiere alle gesammelten Quaternions: q_corrected = (q_axis * (q_base * q_raw))
            corrected = [(self.q_axis * (self.q_base * q)) for q in self._baseline_qs]
            if corrected:
                # Mittelwert der korrigierten Quaternions
                q_avg = _quat_avg(corrected)
                # Neuer Offset‐Quaternion: invertiere diesen Mittelwert
                self.q_offset = q_avg.inverse.normalised
            else:
                self.q_offset = Quaternion()  # kein Datenpunkt → Identity

            if callback: callback("null_done")

        threading.Thread(target=_null_job, daemon=True).start()

    def collect(self, q: Quaternion):
        """
        Wird bei jedem neuen Roh-Quaternion aufgerufen, solange _collecting True ist.
        """
        if self._collecting and self._collector:
            self._collector(q)

    def apply(self, q: Quaternion) -> Quaternion:
        """
        Wendet die Kalibrierungs-Quaternions an:
           → q_base (Basis)
           → q_axis (Achsenausrichtung)
           → q_offset (Offset, Roll & jetzt auch Pitch/Yaw)
        """
        return (self.q_offset * self.q_axis * self.q_base) * q

    def set_manual_roll(self, angle_rad: float):
        """
        Setzt nur den manuellen Roll-Offset (wird in Swing confirm_baseline benutzt).
        """
        self.roll_offset_angle = angle_rad
        self.q_offset = Quaternion(axis=[1, 0, 0], angle=-angle_rad).normalised

    def collecting(self) -> bool:
        """
        True, solange eine Kalibrierungsphase (Swing oder Nullpunkt) aktiv ist.
        """
        return self._collecting
