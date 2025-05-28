# calibration.py

import threading
import time
import numpy as np
from pyquaternion import Quaternion

def _quat_avg(qs: list[Quaternion]) -> Quaternion:
    """
    Mittelt eine Liste von Quaternionen über ihren outer product,
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
        # antiparallel: beliebige orthogonale Achse
        axis = np.cross([1, 0, 0], v0)
        if np.linalg.norm(axis) < 1e-6:
            axis = np.cross([0, 1, 0], v0)
        return Quaternion(axis=axis/np.linalg.norm(axis), angle=np.pi)
    axis = np.cross(v0, v1)
    return Quaternion(1 + d, *axis).normalised

class Calibration:
    """
    Handhabt Ruhe- und Schwing-Kalibrierung
    mit Status-Callbacks für GUI-Feedback.
    """

    def __init__(self):
        self.q_mount = Quaternion()
        self._collecting = False
        self._collector  = None
        self.axis        = np.array([1.0, 0.0, 0.0])    # Default

    def start_rest(self, duration: float, callback=None):
        """
        Ruhe-Kalibrierung über 'duration' Sekunden.
        callback erhält 'rest_started' und 'rest_finished'.
        """
        qs: list[Quaternion] = []
        self._collecting = True
        self._collector  = qs.append
        if callback:
            callback("rest_started")

        def _job():
            time.sleep(duration)
            self._collecting = False
            self._collector  = None
            if qs:
                q_avg = _quat_avg(qs)
                self.q_mount = q_avg.inverse
            if callback:
                callback("rest_finished")

        threading.Thread(target=_job, daemon=True).start()

    def start_swing(self, duration: float, callback=None):
        """
        Schwing-Kalibrierung über 'duration' Sekunden mit:
          • Aufforderung "Bitte Glocke anschwingen"
          • Countdown jeder Sekunde
          • Probenentnahme währenddessen
          • Achsbestimmung per PCA
          • Roll-Offset-Korrektur
        callback erhält alle Status-Texte 1:1.
        """
        qs: list[Quaternion] = []
        q0: Quaternion | None = None

        def collect(q: Quaternion):
            nonlocal q0
            if q0 is None:
                q0 = q
            qs.append(q)

        # Aufforderung zum Anschwingen
        if callback:
            callback("Bitte Glocke anschwingen")
        self._collecting = True
        self._collector  = collect

        def _job():
            # Countdown
            for remaining in range(int(duration), 0, -1):
                if callback:
                    callback(f"{remaining} s verbleiben")
                time.sleep(1)

            # Sampling beenden
            self._collecting = False
            self._collector  = None

            # Ausgabe zur Analyse
            print("---- Swing-Kalibrierung abgeschlossen ----")
            print(f"  Samples gesammelt: {len(qs)}")
            if q0 is None:
                print("  !! Kein Start-Sample erhalten !!")
            else:
                # Δ-Quaternions analysieren
                omegas: list[np.ndarray] = []
                for a, b in zip(qs, qs[1:]):
                    dq = b * a.inverse
                    v  = np.array(dq.vector)
                    ang = 2 * np.arctan2(np.linalg.norm(v), dq.w)
                    if np.linalg.norm(v) > 1e-6:
                        omegas.append(v/np.linalg.norm(v) * ang)
                # PCA
                if omegas:
                    _, _, vt = np.linalg.svd(np.vstack(omegas), full_matrices=False)
                    axis = vt[0]
                    print(f"  Dominante Achse (PCA): [{axis[0]:+.3f}, {axis[1]:+.3f}, {axis[2]:+.3f}]")
                else:
                    axis = np.array([1.0, 0.0, 0.0])
                    print("  !! Zu wenige valide Δ-Proben für PCA, verwende X-Achse.")

                # Roll-Offset bestimmen
                q_axis = _quat_between(axis, np.array([1, 0, 0]))
                roll0, _, _ = (q_axis * q0).yaw_pitch_roll
                print(f"  Gefundener Roll-Offset: {np.degrees(roll0):+.2f}°")

                # Mount-Quaternion setzen
                self.q_mount = (Quaternion(axis=[1,0,0], angle=-roll0) * q_axis).normalised
                # Achse speichern
                self.axis = axis
                qm = self.q_mount
                print(f"  Mount-Quaternion: w={qm.w:.4f}, x={qm.x:.4f}, y={qm.y:.4f}, z={qm.z:.4f}")
            print("-------------------------------------------")

            if callback:
                callback("Schwing-Kalibrierung fertig")

        threading.Thread(target=_job, daemon=True).start()

    def collect(self, q: Quaternion):
        """
        Wird von ViewerCore bei jedem neuen Roh-Quaternion aufgerufen.
        """
        if self._collecting and self._collector:
            self._collector(q)

    def apply(self, q: Quaternion) -> Quaternion:
        """
        Wendet die Kalibrier-Rotation auf ein Roh-Quaternion an.
        """
        return self.q_mount * q

    def collecting(self) -> bool:
        """
        True, solange Kalibrier-Proben gesammelt werden.
        """
        return self._collecting
