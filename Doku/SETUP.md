# Raspberry Pi Zero 2W– Komplett‑Setup für Raspberry Pi

> Ziel ✱ Pi bootet selbstständig, liest Quaternionen von der Nicla über UART, stellt die Web‑GUI unter `http://192.168.4.1:5000` im eigenen WLAN‑Hotspot **WinkelPi** bereit.
## 1  Raspberry Pi OS (Legacy Bullseye 64‑bit) Lite flashen
Überarbeiten, falls eigenes Image erstellt wird! Bei komplettem Neuaufsetzen:
1. **Raspberry Pi Imager** öffnen → *Raspberry Pi OS Lite (Legacy, 64‑bit)* wählen.
2. `Ctrl + Shift + X` ▸ Advanced Options:
   - Hostname `probellpi`
   - User `probell` + Passwort
   - SSH **enable**
3. SD flashen ▸ einstecken ▸ Pi booten (Monitor+Tastatur dran).

---
## 2  Grundsystem aktualisieren

```bash
sudo apt update && sudo apt full-upgrade -y
sudo apt install git python3-pip python3-venv hostapd dnsmasq -y
```
---
## 4  UART freischalten

```bash
sudo raspi-config   # Interface Options ▸ Serial
# ⇒ Login‑Shell: No • UART-Hardware: Yes
```

`/boot/config.txt` ergänzen:

```ini
enable_uart=1
dtoverlay=pi3-disable-bt   # schnelles ttyAMA0
```

Reboot ▸ `ls -l /dev/serial0` ➜ `s… → ttyAMA0`.

---
## 5  Repo klonen & venv

```bash
cd ~
git clone https://github.com/SpiessDD/Winkelmessung_GUI_Nicla_Sense.git
cd Winkelmessung_GUI_Nicla_Sense
python3 -m venv venv
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
```
---
## 6  Systemd‑Autostart

```bash
sudo tee /etc/systemd/system/winkel.service <<'EOF'
[Unit]
Description=Winkelmessung GUI Nicla Sense
After=network-online.target

[Service]
Type=simple
User=pi
WorkingDirectory=/home/pi/Winkelmessung_GUI_Nicla_Sense
ExecStart=/home/pi/Winkelmessung_GUI_Nicla_Sense/venv/bin/python \
         -m uvicorn app:app --host 0.0.0.0 --port 5000
Restart=on-failure
RestartSec=3

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable --now winkel.service
```

`sudo ss -tulpn | grep 5000` ⇒ `LISTEN 0.0.0.0:5000`.

---
## 7  Hotspot (AP) konfigurieren

### 7.1  `/etc/dhcpcd.conf`

```text
interface wlan0
    static ip_address=192.168.4.1/24
    nohook wpa_supplicant
```

`sudo service dhcpcd restart`

### 7.2  `/etc/dnsmasq.conf`

```text
interface=wlan0
dhcp-range=192.168.4.10,192.168.4.50,255.255.255.0,24h
domain-needed
bogus-priv
```

`sudo systemctl restart dnsmasq && sudo systemctl enable dnsmasq`

### 7.3  `/etc/hostapd/hostapd.conf`

```text
country_code=DE
interface=wlan0
ssid=WinkelPi
hw_mode=g
channel=6
ieee80211d=1
ieee80211n=1
wmm_enabled=1
wpa=2
wpa_passphrase=Glocke1234
rsn_pairwise=CCMP
```

`sudo sh -c 'echo DAEMON_CONF="/etc/hostapd/hostapd.conf" > /etc/default/hostapd'` `sudo systemctl restart hostapd && sudo systemctl enable hostapd`

---
## 8  Test‑Checkliste

1. `python pi_test.py` ▸ Quaternion‑Zeilen erscheinen.
2. `sudo ss -tulpn | grep 5000` ▸ Port offen.
3. Laptop ↔ SSID **WinkelPi** / Passwort `Glocke1234`.
4. Browser → `http://192.168.4.1:5000` ▸ Web‑GUI sichtbar.
5. Service‑Logs: `journalctl -u winkel.service -f`.

---
