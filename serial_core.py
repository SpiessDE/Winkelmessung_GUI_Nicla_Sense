# serial_core.py

import threading, queue, time, serial
from data_processor import DataProcessor

class SerialCore:
    def __init__(self, port="/dev/serial0", baud=115200):
        self.port = port
        self.baud = baud
        self.ser   = None
        self._stop = threading.Event()
        self.q     = queue.Queue()
        # DataProcessor übernimmt Kalibrierung & Winkel‐Berechnung
        self.processor = DataProcessor(queue=self.q)

    def connect(self):
        """Öffnet den seriellen Port und startet den Reader‐Thread."""
        try:
            self.ser = serial.Serial(self.port, self.baud, timeout=1)
        except serial.SerialException as e:
            print("SerialCore: Port open error:", e)
            return False
        self._stop.clear()
        threading.Thread(target=self._reader, daemon=True).start()
        return True

    def disconnect(self):
        self._stop.set()
        if self.ser and self.ser.is_open:
            self.ser.close()

    def _reader(self):
        """Liest Zeilen im CSV-Format: millis,qx,qy,qz,qw"""
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
            # Verarbeite jeden Frame direkt durch DataProcessor
            self.processor.process(ms, qx, qy, qz, qw)

    # Umbau der Kalibrierungs-Hooks für Web-API
    def swing_calib(self, dur=10.0):
        self.processor.calib.start_swing(dur, callback=self._cb)

    def confirm_baseline(self, dur=0.5):
        self.processor.calib.confirm_baseline(dur, callback=self._cb)

    def null_calib(self, dur=0.5):
        self.processor.calib.start_nullpoint(dur, callback=self._cb)

    def _cb(self, msg):
        """ Callback aus Calibration → wird über WebSocket/SSE ausgesendet """
        # wir sammeln Status-Meldungen in einer Queue
        self.q.put({"status": msg})
