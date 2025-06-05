# serial_core.py

import threading, queue, time
import serial
from data_processor import DataProcessor

class SerialCore:
    def __init__(self):
        self.q = queue.Queue()
        self._stop = threading.Event()
        self.ser = None
        self.th = None

        # zentraler DataProcessor für USB
        self.processor = DataProcessor(queue=self.q)

    def connect(self, port, baud=115200):
        try:
            self.ser = serial.Serial(port, baud, timeout=1)
        except serial.SerialException:
            return False
        self._stop.clear()
        self.th = threading.Thread(target=self._reader, daemon=True)
        self.th.start()
        return True

    def disconnect(self):
        self._stop.set()
        if self.ser and self.ser.is_open:
            self.ser.close()
        self.ser = None

    def _reader(self):
        while not self._stop.is_set() and self.ser and self.ser.is_open:
            line = self.ser.readline().decode(errors="ignore").strip()
            parts = line.split(",")
            if len(parts) != 5:
                continue
            try:
                ms  = int(float(parts[0]))
                qx, qy, qz, qw = map(float, parts[1:])
            except ValueError:
                continue
            self.processor.process(ms, qx, qy, qz, qw)

    def swing_calib(self, dur=10.0):
        """Zweiphasige Swing-Kalibrierung über USB auslösen."""
        def cb(msg):
            if msg == "swing_pca_done":
                ax = self.processor.calib.axis.tolist()
                self.q.put({"dominant_axis": ax})
            self.q.put({"status": msg})
        self.processor.calib.start_swing(dur, callback=cb)

    def confirm_baseline(self, dur=0.5):
        """Bestätigung der Stillstand-Phase auslösen (Rolloffset)."""
        def cb(msg):
            self.q.put({"status": msg})
        self.processor.calib.confirm_baseline(dur, callback=cb)

    def null_calib(self, dur=0.5):
        """
        Nullpunkt-Kalibrierung (alle Achsen) über USB auslösen.
        Vergleichbar mit confirm_baseline, aber für alle 3 Achsen.
        """
        def cb(msg):
            self.q.put({"status": msg})
        self.processor.calib.start_nullpoint(dur, callback=cb)
