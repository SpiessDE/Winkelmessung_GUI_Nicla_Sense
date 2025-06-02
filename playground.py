import serial

ser = serial.Serial("COM7", 115200, timeout=1)
while True:
    line = ser.readline().decode("utf-8", errors="ignore").strip()
    if not line:
        continue
    print("RAW:", line)
