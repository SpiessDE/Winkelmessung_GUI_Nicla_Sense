# viewer_core.py
import asyncio
import struct
import threading
from bleak import BleakClient, BleakScanner

from data_processor import DataProcessor

CHAR_UUID = "19b10001-0000-537e-4f6c-d104768a1214"

def _new_loop():
    loop = asyncio.new_event_loop()
    threading.Thread(target=loop.run_forever, daemon=True).start()
    return loop

class ViewerCore:
    def __init__(self):
        self.loop   = _new_loop()
        self.client = None
        self.is_connected = False

        # zentraler DataProcessor für BLE
        self.processor = DataProcessor(queue=None)
        self.queue     = None

    def auto_connect(self, queue, name_prefix="Nicla"):
        self.queue            = queue
        self.processor.queue  = queue

        async def _job():
            devs = await BleakScanner.discover(timeout=3.0)
            trg  = next((d for d in devs if d.name and d.name.startswith(name_prefix)), None)
            if not trg:
                queue.put({"status": "Kein Nicla gefunden"})
                return

            queue.put({"status": f"Verbinde: {trg.name}"})
            async with BleakClient(trg) as cl:
                self.client        = cl
                self.is_connected  = True
                queue.put({"status": f"Verbunden: {trg.name}"})
                await cl.start_notify(CHAR_UUID, self._notify)
                while self.is_connected:
                    await asyncio.sleep(0.2)

        asyncio.run_coroutine_threadsafe(_job(), self.loop)

    def disconnect(self):
        self.is_connected = False
        if self.client:
            asyncio.run_coroutine_threadsafe(self.client.disconnect(), self.loop)
            self.client = None

    def rest_calib(self, dur=0.5):
        def cb(msg):
            if self.queue:
                self.queue.put({"status": msg})
        self.processor.calib.start_rest(dur, callback=cb)

    def swing_calib(self, dur=10.0):
        def cb(msg):
            if self.queue:
                self.queue.put({"status": msg})
            if msg == "Schwing-Kalibrierung fertig":
                # dominante Achse ebenfalls senden
                ax = self.processor.calib.axis.tolist()
                self.queue.put({"dominant_axis": ax})
        self.processor.calib.start_swing(dur, callback=cb)

    def _notify(self, handle, data: bytes):
        # Unpack <Iffff> = millis + 4×float
        ms, qx, qy, qz, qw = struct.unpack("<Iffff", data)
        self.processor.process(ms, qx, qy, qz, qw)
