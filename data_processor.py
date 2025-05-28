# data_processor.py
import time
import numpy as np
from pyquaternion import Quaternion
from calibration import Calibration

class DataProcessor:
    def __init__(self, queue):
        self.queue = queue
        self.calib = Calibration()
        self._rate_cnt   = 0
        self._rate_t0    = time.time()
        self.rate_hz     = 0.0
        self._srate_cnt  = 0
        self._srate_t0   = time.time()
        self.srate_hz    = 0.0

    def process(self, ms: int, qx: float, qy: float, qz: float, qw: float):
        secs = ms / 1000.0
        now = time.time()

        # Paket-Rate (2 s-Fenster)
        self._rate_cnt += 1
        if now - self._rate_t0 >= 2.0:
            self.rate_hz  = self._rate_cnt / (now - self._rate_t0)
            self._rate_t0 = now
            self._rate_cnt = 0

        # Sample-Rate (2 s-Fenster)
        self._srate_cnt += 1
        if now - self._srate_t0 >= 2.0:
            self.srate_hz   = self._srate_cnt / (now - self._srate_t0)
            self._srate_t0  = now
            self._srate_cnt = 0

        # RAW-Quaternion
        q_raw = Quaternion(w=qw, x=qx, y=qy, z=qz)
        R_raw = q_raw.rotation_matrix

        # Kalibriertes Quaternion
        self.calib.collect(q_raw)
        q_cal = self.calib.apply(q_raw)
        yaw, pitch, roll = q_cal.yaw_pitch_roll
        R_cal = q_cal.rotation_matrix

        # Dict in die Queue
        if self.queue:
            self.queue.put({
                "secs":    secs,
                "rate":    self.rate_hz,
                "srate":   self.srate_hz,
                # RAW
                "raw_qx":  q_raw.x, "raw_qy": q_raw.y,
                "raw_qz":  q_raw.z, "raw_qw": q_raw.w,
                "raw_R":   R_raw,
                # Kalibriert
                "qx":      q_cal.x, "qy":     q_cal.y,
                "qz":      q_cal.z, "qw":     q_cal.w,
                "roll":    np.degrees(roll),
                "pitch":   np.degrees(pitch),
                "yaw":     np.degrees(yaw),
                "R":       R_cal
            })
