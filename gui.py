"""
gui_light_arc.py – Nicla-Viewer GUI mit USB-prioritärer Verbindung, BLE-Fallback,
CSV, Live-3D+2D, Kalib-Status und Visualisierung der dominanten Schwing-Achse
"""

import tkinter as tk
import csv
import datetime
import collections
from tkinter import ttk, filedialog, messagebox
from queue import Queue, Empty
from serial.tools import list_ports

from viewer_core import ViewerCore
from serial_core import SerialCore
from pyquaternion import Quaternion
import numpy as np

import matplotlib
matplotlib.use("TkAgg")
import matplotlib.pyplot as plt
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg

try:
    from ttkthemes import ThemedTk
    RootTk, THEME = ThemedTk, {"theme": "arc"}  # helles Arc-Theme
except ImportError:
    RootTk, THEME = tk.Tk, {}

class NiclaGUI(RootTk):
    def __init__(self):
        super().__init__(**THEME)
        self.title("Nicla Bell Viewer")
        self.geometry("1040x820")
        self.configure(bg="#fafafa")

        # Back-Ends
        self.core  = ViewerCore()
        self.ser   = SerialCore()
        self.queue = Queue()

        # GUI-State: USB first on COM7
        self.mode      = tk.StringVar(value="USB")
        self.port_var  = tk.StringVar(value="COM7")
        self._csv_file = None
        self._csv_wr   = None
        self.buf_t     = collections.deque(maxlen=400)
        self.buf_rl    = collections.deque(maxlen=400)

        self._style()
        self._build_widgets()

        # Startup: try USB on COM7, else BLE
        if not self._try_usb_startup():
            self.mode.set("BLE")
            self._connect_ble()

        # Polling loop
        self.after(40, self._poll)

    def _try_usb_startup(self) -> bool:
        """
        Versucht, automatisch per USB auf self.port_var (z.B. 'COM7')
        zu verbinden. Gibt True zurück bei Erfolg, sonst False.
        """
        port = self.port_var.get()
        ok = self.ser.connect(port, baud=115200)
        if ok:
            self.lbl_status.configure(text=f"USB {port}")
            self.mode.set("USB")
            self._mode_changed()
            return True
        else:
            print(f"USB-Startup auf {port} fehlgeschlagen, wechsele zu BLE")
            return False

    def _style(self):
        s = ttk.Style(self)
        s.configure(".", font=("Segoe UI", 10), background="#fafafa")
        s.configure("TLabelframe.Label", font=("Segoe UI", 11, "bold"))
        s.configure("TButton", background="#e0e0e0")
        s.map("TButton", background=[("active", "#d0d0d0")])

    def _build_widgets(self):
        # Header
        hdr = ttk.Frame(self); hdr.pack(fill="x", padx=10, pady=6)
        ttk.Radiobutton(hdr, text="BLE", value="BLE", variable=self.mode,
                        command=self._mode_changed).pack(side="left")
        ttk.Radiobutton(hdr, text="USB", value="USB", variable=self.mode,
                        command=self._mode_changed).pack(side="left", padx=(0,4))

        self.cbx_port    = ttk.Combobox(hdr, textvariable=self.port_var,
                                        state="disabled", width=12)
        self.btn_refresh = ttk.Button(hdr, text="↻", width=3,
                                      command=self._refresh_ports, state="disabled")
        self.cbx_port.pack(side="left"); self.btn_refresh.pack(side="left", padx=(2,8))

        self.lbl_status  = ttk.Label(hdr, text="Init …")
        self.lbl_status.pack(side="left", fill="x", expand=True)

        ttk.Button(hdr, text="Reconnect", command=self._reconnect).pack(side="left", padx=6)
        self.btn_csv = ttk.Button(hdr, text="Start CSV", command=self._toggle_csv)
        self.btn_csv.pack(side="left")

        # Aktionen
        act = ttk.LabelFrame(self, text="Aktionen"); act.pack(fill="x", padx=10, pady=4)
        for txt, cmd in [("Ruhe-Kalib", self._rest),
                         ("Schwing-Kalib", self._swing),
                         ("Reset",       self._reset)]:
            ttk.Button(act, text=txt, width=14, command=cmd).pack(side="left", padx=6, pady=4)

        # 1) Info-Bereich (fixe Höhe)
        info_container = ttk.Frame(self)
        info_container.pack(fill="x", padx=10, pady=(0,4))
        self._build_info_area(info_container)

        # 2) Plot-Bereich (expand)
        plot_container = ttk.Frame(self)
        plot_container.pack(fill="both", expand=True, padx=10, pady=(4,10))
        self._build_plot_area(plot_container)

    def _build_info_area(self, parent):
        """Erstellt nur den Info-Bereich ohne Plots."""
        self.var = {}

        # System
        sysf = ttk.LabelFrame(parent, text="System"); sysf.pack(side="left", fill="y", padx=(0,10))
        for i, (lbl, key, fmt) in enumerate((
            ("Sek [s]", "secs",  "{:.4f}"),
            ("Pkt Hz",  "rate",  "{:.1f}"),
            ("Samp Hz", "srate", "{:.1f}")
        )):
            ttk.Label(sysf, text=lbl+":").grid(row=i, column=0, sticky="e", padx=4, pady=2)
            sv = tk.StringVar(value="–")
            ttk.Label(sysf, textvariable=sv, width=10).grid(row=i, column=1, sticky="w")
            self.var[key] = sv

        # Euler
        eul = ttk.LabelFrame(parent, text="Euler-Winkel"); eul.pack(side="left", fill="y", padx=(0,10))
        for i, ax in enumerate(("Roll","Pitch","Yaw")):
            ttk.Label(eul, text=ax+"°:").grid(row=i, column=0, sticky="e", padx=4, pady=2)
            sv = tk.StringVar(value="–")
            ttk.Label(eul, textvariable=sv, width=12).grid(row=i, column=1, sticky="w")
            self.var[ax.lower()] = sv

        # Quaternion
        qf = ttk.LabelFrame(parent, text="Quaternion"); qf.pack(side="left", fill="y", padx=(0,10))
        for i, k in enumerate(("qx","qy","qz","qw")):
            ttk.Label(qf, text=k+":").grid(row=i, column=0, sticky="e", padx=4, pady=2)
            sv = tk.StringVar(value="–")
            ttk.Label(qf, textvariable=sv, width=12).grid(row=i, column=1, sticky="w")
            self.var[k] = sv

        # Matrix
        mat = ttk.LabelFrame(parent, text="Rotationsmatrix R"); mat.pack(side="left", fill="y")
        for i, r in enumerate(("r0","r1","r2")):
            sv = tk.StringVar(value="– – –")
            ttk.Label(mat, textvariable=sv, width=26, anchor="w") \
                .grid(row=i, column=0, padx=4, pady=2)
            self.var[r] = sv

    def _build_plot_area(self, parent):
        """Erstellt die Matplotlib-Plots."""
        fig = plt.Figure(figsize=(9.6,6.8), facecolor="#fafafa")
        gs  = fig.add_gridspec(2,1, height_ratios=[3,1], hspace=0.25)

        # 3D
        ax3 = fig.add_subplot(gs[0], projection="3d", facecolor="#fafafa")
        ax3.set_xlim(-1,1); ax3.set_ylim(-1,1); ax3.set_zlim(-1,1)
        for axis in (ax3.xaxis, ax3.yaxis, ax3.zaxis):
            axis.set_ticks([]); axis.set_ticklabels([])

        # RGB-Achsen
        self.ax_lines = [
            ax3.plot([0,1],[0,0],[0,0],'#d62728', lw=3)[0],
            ax3.plot([0,0],[0,1],[0,0],'#2ca02c', lw=3)[0],
            ax3.plot([0,0],[0,0],[0,1],'#1f77b4', lw=3)[0],
        ]
        # dominant axis
        self.axis_line, = ax3.plot([0,0],[0,0],[0,0],
                                   linestyle="--", color="black", linewidth=2)

        # 2D Roll vs Zeit
        ax2 = fig.add_subplot(gs[1], facecolor="#fafafa")
        ax2.set_title("Roll° vs Zeit (s)", fontsize=9)
        ax2.set_xlabel("Sekunden"); ax2.set_ylabel("Roll°"); ax2.grid(alpha=0.3)
        self.line2d, = ax2.plot([], [], '#d62728')
        self.ax2 = ax2

        canvas = FigureCanvasTkAgg(fig, master=parent)
        canvas.draw()
        canvas.get_tk_widget().pack(fill="both", expand=True)
        self.canvas = canvas

    def _mode_changed(self):
        usb = (self.mode.get() == "USB")
        st  = "normal" if usb else "disabled"
        self.cbx_port.configure(state=st)
        self.btn_refresh.configure(state=st)
        if usb:
            self._refresh_ports()

    def _refresh_ports(self):
        ports = [p.device for p in list_ports.comports()]
        self.cbx_port["values"] = ports
        if ports:
            self.port_var.set(ports[0])

    def _connect_ble(self):
        self.lbl_status.configure(text="Suche Nicla (BLE)…")
        self.core.auto_connect(self.queue)

    def _connect_usb(self, port):
        ok = self.ser.connect(port, baud=115200)
        self.lbl_status.configure(text=f"USB {port}" if ok else "USB Fehler")

    def _reconnect(self):
        self.core.disconnect(); self.ser.disconnect()
        self.buf_t.clear(); self.buf_rl.clear()
        if self.mode.get() == "BLE":
            self._connect_ble()
        else:
            p = self.port_var.get()
            if p.startswith("<"):
                messagebox.showwarning("Port wählen", "Bitte Port auswählen.")
                return
            self._connect_usb(p)

    def _toggle_csv(self):
        if self._csv_file:
            self._csv_file.close(); self._csv_file = None; self._csv_wr = None
            self.btn_csv.configure(text="Start CSV"); self.lbl_status.configure(text="CSV gespeichert")
            return
        ts = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        default = f"nicla_{ts}.csv"
        path = filedialog.asksaveasfilename(defaultextension=".csv",
            initialfile=default, title="CSV speichern", filetypes=[("CSV","*.csv")])
        if not path: return
        self._csv_file = open(path, "w", newline=""); self._csv_wr = csv.writer(self._csv_file)
        self._csv_wr.writerow(["secs","roll","pitch","yaw","qx","qy","qz","qw"])
        self.btn_csv.configure(text="Stop CSV"); self.lbl_status.configure(text=f"Schreibe: {path}")

    def _rest(self):
        if self.mode.get() == "USB":
            self.ser.rest_calib()
        else:
            self.core.rest_calib()

    def _swing(self):
        if self.mode.get() == "USB":
            self.ser.swing_calib()
        else:
            self.core.swing_calib()

    def _reset(self):
        # Reset Kalibrierung
        if self.mode.get()=="BLE":
            self.core.calib.q_mount = Quaternion()
            self.core.calib.axis    = np.array([1.0,0.0,0.0])
        else:
            self.ser.calib.q_mount = Quaternion()
            self.ser.calib.axis    = np.array([1.0,0.0,0.0])
        # Reset Plot
        self.buf_t.clear(); self.buf_rl.clear()
        self.axis_line.set_data([0,0], [0,0]); self.axis_line.set_3d_properties([0,0])
        self.canvas.draw_idle()

    def _poll(self):
        try:
            while True:
                if self.mode.get()=="BLE":
                    d = self.queue.get_nowait()
                else:
                    d = self.ser.q.get_nowait()
                if "status" in d:
                    self.lbl_status.configure(text=d["status"])
                elif "dominant_axis" in d:
                    ax = d["dominant_axis"]
                    self.axis_line.set_data([0, ax[0]], [0, ax[1]])
                    self.axis_line.set_3d_properties([0, ax[2]])
                else:
                    self._update(d)
        except Empty:
            pass
        self.after(40, self._poll)

    def _update(self, d):
        for k, fmt in [("secs","{:.4f}"), ("rate","{:.1f}"), ("srate","{:.1f}"),
                       ("roll","{:+6.2f}"), ("pitch","{:+6.2f}"), ("yaw","{:+6.2f}")]:
            self.var[k].set(fmt.format(d[k]))
        for k in ("qx","qy","qz","qw"):
            self.var[k].set(f"{d[k]:+.4f}")

        R = d["R"]
        self.var["r0"].set(" ".join(f"{v:+.3f}" for v in R[0]))
        self.var["r1"].set(" ".join(f"{v:+.3f}" for v in R[1]))
        self.var["r2"].set(" ".join(f"{v:+.3f}" for v in R[2]))

        l0,l1,l2 = self.ax_lines
        l0.set_data([0,R[0,0]],[0,R[1,0]]); l0.set_3d_properties([0,R[2,0]])
        l1.set_data([0,R[0,1]],[0,R[1,1]]); l1.set_3d_properties([0,R[2,1]])
        l2.set_data([0,R[0,2]],[0,R[1,2]]); l2.set_3d_properties([0,R[2,2]])

        self.buf_t.append(d["secs"]); self.buf_rl.append(d["roll"])
        self.line2d.set_data(self.buf_t, self.buf_rl)
        if len(self.buf_t)>1:
            self.ax2.set_xlim(self.buf_t[0], self.buf_t[-1])
        lo, hi = min(self.buf_rl), max(self.buf_rl)
        self.ax2.set_ylim(lo-5, hi+5)

        self.canvas.draw_idle()

        if self._csv_wr:
            self._csv_wr.writerow([
                f"{d['secs']:.4f}",
                f"{d['roll']:.2f}",
                f"{d['pitch']:.2f}",
                f"{d['yaw']:.2f}",
                f"{d['qx']:.6f}",
                f"{d['qy']:.6f}",
                f"{d['qz']:.6f}",
                f"{d['qw']:.6f}"
            ])

if __name__=="__main__":
    NiclaGUI().mainloop()
