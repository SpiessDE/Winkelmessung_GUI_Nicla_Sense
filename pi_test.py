#!/usr/bin/env python3
import serial, time

port = serial.Serial("/dev/serial0", 115200, timeout=1)

try:
    while True:
        line = port.readline().decode("ascii", errors="replace").strip()
        if line:
            print(time.strftime("%H:%M:%S"), line)
except KeyboardInterrupt:
    pass
