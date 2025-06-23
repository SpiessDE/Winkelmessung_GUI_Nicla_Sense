# app.py

from flask import Flask, render_template, Response, request, jsonify
from serial_core import SerialCore
import threading, json, time

app = Flask(__name__, template_folder="templates", static_folder="static")

# SerialCore-Instanz global
#sc = SerialCore(port="/dev/ttyACM0", baud=115200)
sc = SerialCore(port="COM7", baud=115200)
sc.connect()

# Wird von SerialCore.q gefüllt: Winkel-Dicts und Status-Meldungen.
# Wir liefern sie per Server‐Sent Events an die Clients.
def event_stream():
    while True:
        data = sc.q.get()  # blockiert, bis etwas ansteht
        yield f"data: {json.dumps(data)}\n\n"

@app.route("/")
def index():
    """Hauptseite mit WebSocket/SSE-Client."""
    return render_template("index.html")

@app.route("/api/swing", methods=["POST"])
def api_swing():
    dur = float(request.json.get("duration", 10.0))
    sc.swing_calib(dur)
    return jsonify({"result":"swing started", "duration":dur})

@app.route("/api/confirm", methods=["POST"])
def api_confirm():
    dur = float(request.json.get("duration", 0.5))
    sc.confirm_baseline(dur)
    return jsonify({"result":"confirm baseline", "duration":dur})

@app.route("/api/null", methods=["POST"])
def api_null():
    dur = float(request.json.get("duration", 0.5))
    sc.null_calib(dur)
    return jsonify({"result":"nullpoint calib", "duration":dur})

@app.route("/stream")
def stream():
    """Server-Sent Events Endpoint."""
    return Response(event_stream(), mimetype="text/event-stream")

if __name__ == "__main__":
    # Flask nur auf 0.0.0.0, damit vom LAN erreichbar
    app.run(host="0.0.0.0", port=5000, threaded=True)
