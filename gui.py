"""
gui.py – Nicla-Viewer GUI mit USB-prioritärer Verbindung, BLE-Fallback,
CSV, Live-3D+2D, zweiphasiger Swing-Kalibrierung (10 s PCA + Bestätigung)
und zusätzlicher Analyse des kalibrierten Roll-Winkels.
3D- und 2D-Plot stehen nun nebeneinander in einer Zeile.
"""

import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import csv, datetime, collections
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
        self.geometry("1200x1000")  # Fensterbreite vergrößert für nebeneinander stehende Plots
        self.configure(bg="#fafafa")

        # Backends
        self.core  = ViewerCore()
        self.ser   = SerialCore()
        self.queue = Queue()

        # GUI-State
        self.mode      = tk.StringVar(value="USB")
        self.port_var  = tk.StringVar(value="COM7")
        self._csv_file = None
        self._csv_wr   = None

        # Buffers für 2D-Plot
        self.buf_t  = collections.deque(maxlen=400)
        self.buf_rl = collections.deque(maxlen=400)

        # Analyse‐Modus‐State
        self.analyzing     = False
        self.analyse_t     = []
        self.analyse_roll  = []

        self._style()
        self._build_widgets()

        # Start: USB auf COM7, sonst BLE
        if not self._try_usb_startup():
            self.mode.set("BLE")
            self._connect_ble()

        # Poll-Loop
        self.after(40, self._poll)

    def _style(self):
        s = ttk.Style(self)
        s.configure(".", font=("Segoe UI",10), background="#fafafa")
        s.configure("TLabelframe.Label", font=("Segoe UI",11,"bold"))
        s.configure("TButton", background="#e0e0e0")
        s.map("TButton", background=[("active","#d0d0d0")])

    def _build_widgets(self):
        # Header mit Modus-Wahl + Port + CSV
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
        self.lbl_status  = ttk.Label(hdr, text="Init …"); self.lbl_status.pack(side="left", fill="x", expand=True)
        ttk.Button(hdr, text="Reconnect", command=self._reconnect).pack(side="left", padx=6)
        self.btn_csv = ttk.Button(hdr, text="Start CSV", command=self._toggle_csv)
        self.btn_csv.pack(side="left")

        # Aktionen-Frame
        act = ttk.LabelFrame(self, text="Aktionen"); act.pack(fill="x", padx=10, pady=4)
        ttk.Button(act, text="Schwing-Kalib", width=14, command=self._swing).pack(side="left", padx=6)
        self.btn_confirm = ttk.Button(act, text="Glocke still?", width=14, command=self._confirm_baseline)
        self.btn_confirm.pack(side="left", padx=6)
        self.btn_confirm.configure(state="disabled")
        ttk.Button(act, text="Reset", width=14, command=self._reset).pack(side="left", padx=6)

        # Info-Bereiche
        info = ttk.Frame(self); info.pack(fill="x", padx=10, pady=(0,4))
        self.var = {}
        def col(frm, title, items):
            lf = ttk.LabelFrame(frm, text=title); lf.pack(side="left", fill="y", padx=(0,10))
            for i, (lbl, key, width) in enumerate(items):
                ttk.Label(lf, text=lbl+":").grid(row=i, column=0, sticky="e", padx=4, pady=2)
                sv = tk.StringVar(value="–")
                ttk.Label(lf, textvariable=sv, width=width).grid(row=i, column=1, sticky="w")
                self.var[key] = sv

        col(info, "System",      [("Sek [s]","secs",10), ("Pkt Hz","rate",10), ("Samp Hz","srate",10)])
        col(info, "Euler-Winkel",[("Roll","roll",12), ("Pitch","pitch",12), ("Yaw","yaw",12)])
        col(info, "Quaternion",  [("qx","qx",12), ("qy","qy",12), ("qz","qz",12), ("qw","qw",12)])
        mat = ttk.LabelFrame(info, text="Rotationsmatrix R"); mat.pack(side="left", fill="y")
        for i, r in enumerate(("r0","r1","r2")):
            sv = tk.StringVar(value="– – –")
            ttk.Label(mat, textvariable=sv, width=26, anchor="w").grid(row=i, column=0, padx=4, pady=2)
            self.var[r] = sv

        # Plot-Bereich (nebenläufig, 3D links, 2D rechts)
        plot_area = ttk.Frame(self); plot_area.pack(fill="both", expand=True, padx=10, pady=(4,10))
        fig = plt.Figure(figsize=(10,5), facecolor="#fafafa")
        gs  = fig.add_gridspec(1,2, width_ratios=[1,1], wspace=0.3)

        # 3D-Plot (links)
        ax3 = fig.add_subplot(gs[0], projection="3d", facecolor="#fafafa")
        ax3.set_xlim(-1,1); ax3.set_ylim(-1,1); ax3.set_zlim(-1,1)
        for axis in (ax3.xaxis, ax3.yaxis, ax3.zaxis):
            axis.set_ticklabels([])#; axis.set_ticks([])
        ax3.view_init(elev=0, azim=90)  # Blick senkrecht auf Roll-X-Achse
        self.ax_lines = [
            ax3.plot([0,1],[0,0],[0,0],'#d62728', lw=3)[0],
            ax3.plot([0,0],[0,1],[0,0],'#2ca02c', lw=3)[0],
            ax3.plot([0,0],[0,0],[0,1],'#1f77b4', lw=3)[0],
        ]


        # 2D-Plot: Roll vs. Zeit (rechts)
        ax2 = fig.add_subplot(gs[1], facecolor="#fafafa")
        ax2.set_title("Roll° vs Zeit (s)", fontsize=10)
        ax2.set_xlabel("Sekunden"); ax2.set_ylabel("Roll°"); ax2.grid(alpha=0.3)
        self.line2d, = ax2.plot([], [], '#d62728')
        self.ax2 = ax2

        canvas = FigureCanvasTkAgg(fig, master=plot_area)
        canvas.draw(); canvas.get_tk_widget().pack(fill="both", expand=True)
        self.canvas = canvas

        # -------------- Neuer Abschnitt: Analyse --------------
        analyse_frame = ttk.LabelFrame(self, text="Analyse (Roll-Winkel)")
        analyse_frame.pack(fill="x", padx=10, pady=(0,10))

        self.btn_analyse = ttk.Button(analyse_frame, text="Starte Analyse", command=self._toggle_analysis)
        self.btn_analyse.pack(side="top", pady=(4,4))

        self.txt_analyse = tk.Text(analyse_frame, height=6, width=100, state="disabled",
                                   background="#ffffff", relief="solid", bd=1)
        self.txt_analyse.pack(side="top", padx=10, pady=(0,4))

    def _mode_changed(self):
        usb = (self.mode.get()=="USB")
        state = "normal" if usb else "disabled"
        self.cbx_port.configure(state=state)
        self.btn_refresh.configure(state=state)
        if usb: self._refresh_ports()

    def _try_usb_startup(self) -> bool:
        port = self.port_var.get()
        ok = self.ser.connect(port, baud=115200)
        if ok:
            self.lbl_status.configure(text=f"USB {port}")
            self.mode.set("USB")
            self._mode_changed()
        return ok

    def _refresh_ports(self):
        ports = [p.device for p in list_ports.comports()]
        self.cbx_port["values"] = ports
        if ports:
            self.port_var.set(ports[0])

    def _connect_ble(self):
        self.lbl_status.configure(text="Suche Nicla (BLE)…")
        self.core.auto_connect(self.queue)

    def _reconnect(self):
        self.core.disconnect(); self.ser.disconnect()
        self.buf_t.clear(); self.buf_rl.clear()
        if self.mode.get()=="BLE":
            self._connect_ble()
        else:
            p = self.port_var.get()
            if p.startswith("<"):
                messagebox.showwarning("Port wählen","Bitte Port auswählen.")
                return
            self.ser.connect(p, baud=115200)
            self.lbl_status.configure(text=f"USB {p}")

    def _toggle_csv(self):
        if self._csv_file:
            self._csv_file.close(); self._csv_file = None; self._csv_wr = None
            self.btn_csv.configure(text="Start CSV")
            self.lbl_status.configure(text="CSV gespeichert")
            return
        ts = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        path = filedialog.asksaveasfilename(defaultextension=".csv",
            initialfile=f"nicla_{ts}.csv", title="CSV speichern",
            filetypes=[("CSV","*.csv")])
        if not path: return
        self._csv_file = open(path,"w",newline="")
        self._csv_wr   = csv.writer(self._csv_file)
        self._csv_wr.writerow(["secs","roll","pitch","yaw","qx","qy","qz","qw"])
        self.btn_csv.configure(text="Stop CSV")
        self.lbl_status.configure(text=f"Schreibe: {path}")

    def _swing(self):
        if self.mode.get()=="USB":
            self.ser.swing_calib(10.0)
        else:
            self.core.swing_calib(10.0)

    def _confirm_baseline(self):
        self.btn_confirm.configure(state="disabled")
        if self.mode.get()=="USB":
            self.ser.confirm_baseline(0.5)
        else:
            self.core.confirm_baseline(0.5)

    def _reset(self):
        # Alle Kalib-Quaternions zurücksetzen
        for backend in (self.core.processor.calib, self.ser.processor.calib):
            backend.q_base = Quaternion()
            backend.q_axis = Quaternion()
            backend.set_manual_roll(0.0)
        self.buf_t.clear(); self.buf_rl.clear()

        # Falls Analyse aktiv war, beenden und zurücksetzen
        if self.analyzing:
            self._toggle_analysis(end_early=True)

    def _poll(self):
        try:
            while True:
                if self.mode.get()=="BLE":
                    d = self.queue.get_nowait()
                else:
                    d = self.ser.q.get_nowait()

                if "status" in d:
                    st = d["status"]
                    if st == "please_hold_baseline":
                        self.lbl_status.configure(text="Bitte Glocke stillhalten…")
                    elif st == "baseline_done":
                        self.lbl_status.configure(text="Baseline OK")
                    elif st == "please_swing":
                        self.lbl_status.configure(text="Bitte Glocke schwingen…")
                    elif st.endswith("s verbleiben"):
                        self.lbl_status.configure(text=st)  # Countdown („10 s verbleiben“)
                    elif st == "swing_pca_done":
                        self.lbl_status.configure(text="PCA fertig. Jetzt stillhalten!")
                        self.btn_confirm.configure(state="normal")
                    elif st == "please_hold_offset":
                        self.lbl_status.configure(text="Bitte Glocke stillhalten…")
                    elif st == "swing_done":
                        self.lbl_status.configure(text="Swing-Kalibrierung abgeschlossen")
                    else:
                        self.lbl_status.configure(text=st)

                elif "dominant_axis" in d:
                    # optional: d["dominant_axis"] anzeigen oder anderweitig nutzen
                    pass

                else:
                    self._update(d)

        except Empty:
            pass
        finally:
            self.after(40, self._poll)

    def _update(self, d):
        # System-Felder
        for k, fmt in [("secs","{:.4f}"),("rate","{:.1f}"),("srate","{:.1f}")]:
            self.var[k].set(fmt.format(d[k]))

        # Euler
        for k, fmt in [("roll","{:+6.2f}"),("pitch","{:+6.2f}"),("yaw","{:+6.2f}")]:
            self.var[k].set(fmt.format(d[k]))

        # Quaternion
        for k in ("qx","qy","qz","qw"):
            self.var[k].set(f"{d[k]:+.4f}")

        # Matrix
        R = d["R"]
        self.var["r0"].set(" ".join(f"{v:+.3f}" for v in R[0]))
        self.var["r1"].set(" ".join(f"{v:+.3f}" for v in R[1]))
        self.var["r2"].set(" ".join(f"{v:+.3f}" for v in R[2]))

        # 3D-Plot update
        for i, line in enumerate(self.ax_lines):
            line.set_data([0, R[0,i]], [0, R[1,i]])
            line.set_3d_properties([0, R[2,i]])

        # 2D-Plot update
        self.buf_t.append(d["secs"]); self.buf_rl.append(d["roll"])
        self.line2d.set_data(self.buf_t, self.buf_rl)
        if len(self.buf_t) > 1:
            self.ax2.set_xlim(self.buf_t[0], self.buf_t[-1])
        lo, hi = min(self.buf_rl), max(self.buf_rl)
        self.ax2.set_ylim(lo-5, hi+5)

        # CSV schreiben, falls aktiv
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

        # Analyse‐Daten puffern, falls aktiv
        if self.analyzing:
            self.analyse_t.append(d["secs"])
            self.analyse_roll.append(d["roll"])

        # Canvas neu zeichnen
        self.canvas.draw_idle()

    # ---------------- Analyse-Funktionen ----------------

    def _toggle_analysis(self, end_early=False):
        """
        Startet oder beendet den Analyse-Modus.
        Wenn end_early=True, wird Analyse diskret abgebrochen, ohne Auswertung.
        """
        if not self.analyzing:
            # Starte Analyse
            self.analyzing = True
            self.analyse_t.clear()
            self.analyse_roll.clear()
            self.btn_analyse.configure(text="Beende Analyse")
            self.txt_analyse.configure(state="normal")
            self.txt_analyse.delete("1.0", tk.END)
            self.txt_analyse.insert(tk.END, "Analysiere… Bitte warten.\n")
            self.txt_analyse.configure(state="disabled")
        else:
            # Beende Analyse
            self.analyzing = False
            self.btn_analyse.configure(text="Starte Analyse")
            if not end_early:
                self._compute_and_show_analysis()

    def _compute_and_show_analysis(self):
        """
        Berechnet die Kennzahlen aus analyse_t und analyse_roll und zeigt sie an.
        """
        t = np.array(self.analyse_t)
        r = np.array(self.analyse_roll)

        if len(r) < 3:
            text = "Zu wenige Daten für Analyse."
        else:
            # 1) Maximal positiver Roll-Wert
            max_pos = np.max(r)

            # 2) Maximal negativer Roll-Wert
            max_neg = np.min(r)

            # 3) Mittelwert aus Max/Min
            mid_val = 0.5 * (max_pos + max_neg)

            # 4 + 5) Schwingfrequenz & Periodendauer aus lokalen Maxima
            idx_peaks = np.where((r[1:-1] > r[:-2]) & (r[1:-1] > r[2:]))[0] + 1
            if len(idx_peaks) >= 2:
                t_peaks = t[idx_peaks]
                periods = np.diff(t_peaks)
                period_avg = np.mean(periods)
                freq = 1.0 / period_avg if period_avg > 0 else 0.0
            else:
                period_avg = 0.0
                freq = 0.0

            text = (
                f"Max. positiver Roll (°):  {max_pos:+.2f}\n"
                f"Max. negativer Roll (°):  {max_neg:+.2f}\n"
                f"Mittlerer Wert aus Max/Min (°): {mid_val:+.2f}\n\n"
                f"Mittlere Periodendauer (s): {period_avg:.3f}\n"
                f"Schwingfrequenz (Hz): {freq:.3f}\n"
            )

        # Ausgabe ins Textfeld
        self.txt_analyse.configure(state="normal")
        self.txt_analyse.delete("1.0", tk.END)
        self.txt_analyse.insert(tk.END, text)
        self.txt_analyse.configure(state="disabled")

if __name__=="__main__":
    NiclaGUI().mainloop()
