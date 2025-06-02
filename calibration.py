import threading
import time
import numpy as np
from pyquaternion import Quaternion

def _quat_avg(qs: list[Quaternion]) -> Quaternion:
    M = sum(np.outer(q.elements, q.elements) for q in qs) / len(qs)
    vals, vecs = np.linalg.eigh(M)
    return Quaternion(vecs[:, vals.argmax()]).normalised

def _quat_between(v0: np.ndarray, v1: np.ndarray) -> Quaternion:
    v0 = v0 / np.linalg.norm(v0)
    v1 = v1 / np.linalg.norm(v1)
    d = np.dot(v0, v1)
    if d < -0.999999:
        axis = np.cross([1, 0, 0], v0)
        if np.linalg.norm(axis) < 1e-6:
            axis = np.cross([0, 1, 0], v0)
        return Quaternion(axis=axis/np.linalg.norm(axis), angle=np.pi)
    axis = np.cross(v0, v1)
    return Quaternion(1 + d, *axis).normalised

class Calibration:
    """
    Kombinierte Ruhe- + Swing-Kalibrierung.
    start_swing(duration, callback) führt:
      1) Basis-Mittelung (still) → q_base
      2) Swing-PCA → q_axis
      3) Offset-Baseline → q_offset
    """

    def __init__(self):
        self.q_base = Quaternion()
        self.axis   = np.array([1.0, 0.0, 0.0])
        self.q_axis = Quaternion()
        self.roll_offset_angle = 0.0
        self.q_offset          = Quaternion()

        self._collecting    = False
        self._collector     = None
        self._baseline_qs   = []
        self._swing_qs      = []

    def start_swing(self,
                    swing_dur: float,
                    callback: callable = None,
                    base_dur: float = 0.5,
                    offset_dur: float = 0.5):
        # — Phase 1: Basis-Mittelung —
        self._baseline_qs = []

        def collect_base(q):
            self._baseline_qs.append(q)

        if callback:
            callback("please_hold_baseline")
        self._collecting = True
        self._collector = collect_base
        time.sleep(base_dur)
        self._collecting = False
        self._collector = None

        if self._baseline_qs:
            q_avg = _quat_avg(self._baseline_qs)
            self.q_base = q_avg.inverse.normalised
        if callback:
            callback("baseline_done")

        # — Phase 2: Swing + PCA —
        self._swing_qs = []

        def collect_swing(q):
            self._swing_qs.append(q)

        if callback:
            callback("please_swing")
        self._collecting = True
        self._collector = collect_swing

        def _pca_job():
            for rem in range(int(swing_dur), 0, -1):
                if callback:
                    callback(f"{rem} s verbleiben")
                time.sleep(1)
            self._collecting = False
            self._collector = None

            corrected = [self.q_base * q for q in self._swing_qs]
            omegas = []
            for a, b in zip(corrected, corrected[1:]):
                dq = b * a.inverse
                v = np.array(dq.vector)
                ang = 2 * np.arctan2(np.linalg.norm(v), dq.w)
                if np.linalg.norm(v) > 1e-6:
                    omegas.append((v / np.linalg.norm(v)) * ang)
            if omegas:
                _, _, vt = np.linalg.svd(np.vstack(omegas), full_matrices=False)
                self.axis = vt[0]
            else:
                self.axis = np.array([1.0, 0.0, 0.0])

            self.q_axis = _quat_between(self.axis, np.array([1.0, 0.0, 0.0])).normalised
            if callback:
                callback("swing_pca_done")

        threading.Thread(target=_pca_job, daemon=True).start()

        # Hinweis: Phase 3 wird NUN NICHT mehr automatisch aufgerufen.
        # Stattdessen wartet man in der GUI auf den „Glocke still?“-Button, der dann confirm_baseline() auslöst.

    def confirm_baseline(self, offset_dur: float, callback=None):
        """
        Phase 3: nach PCA, offset_dur Sekunden Stillstand → Roll-Nullpunkt
        und schließlich callback("swing_done").
        """
        self._baseline_qs = []
        def collect_offset(q): self._baseline_qs.append(q)

        if callback: callback("please_hold_offset")
        self._collecting = True
        self._collector  = collect_offset

        def _offset_job():
            time.sleep(offset_dur)
            self._collecting = False
            self._collector  = None

            corr = [(self.q_axis * (self.q_base * q)) for q in self._baseline_qs]
            rolls = [qc.yaw_pitch_roll[2] for qc in corr]
            roll_mean = float(np.mean(rolls)) if rolls else 0.0
            self.set_manual_roll(roll_mean)

            if callback: callback("swing_done")

        threading.Thread(target=_offset_job, daemon=True).start()

    def collect(self, q: Quaternion):
        if self._collecting and self._collector:
            self._collector(q)

    def apply(self, q: Quaternion) -> Quaternion:
        return (self.q_offset * self.q_axis * self.q_base) * q

    def set_manual_roll(self, angle_rad: float):
        self.roll_offset_angle = angle_rad
        self.q_offset          = Quaternion(axis=[1,0,0], angle=-angle_rad).normalised

    def collecting(self) -> bool:
        return self._collecting
