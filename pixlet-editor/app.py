"""
Pixlet Config Editor — standalone Flask app

A small, separate web UI for launching Pixlet's real config editor
(pixlet serve) against any installed Starlark app, without needing to
SSH in and run the shell script manually. Runs on its own port,
completely separate from the main LEDMatrix web interface.

Only one editing session can be active at a time (pixlet serve always
uses port 8080), matching the same constraint the shell-script version
had. Starting a session stops the ledmatrix display service (to avoid
it reading config.json mid-write); stopping a session restarts it.
"""
import json
import os
import subprocess
import time
from pathlib import Path
from typing import Optional

from flask import Flask, jsonify, redirect, render_template_string, request, url_for

app = Flask(__name__)

STARLARK_APPS_DIR = Path.home() / "LEDMatrix" / "starlark-apps"
PIXLET_BINARY = "/usr/local/bin/pixlet"
PIXLET_SERVE_PORT = 8080

# Tracks the currently-running `pixlet serve` session, if any. This is
# simple in-memory state — fine for a single-user, local-network tool
# like this one, but means state is lost if this Flask process itself
# restarts while a session is active (see /cleanup for recovering from
# that: it force-restarts the display service regardless of what this
# process thinks is running).
_current_session: dict = {"process": None, "app_id": None, "started_at": None}


def _list_installed_apps():
    """Every installed Starlark app that actually has a .star file."""
    if not STARLARK_APPS_DIR.is_dir():
        return []
    apps = []
    for entry in sorted(STARLARK_APPS_DIR.iterdir()):
        if not entry.is_dir():
            continue
        star_files = list(entry.glob("*.star"))
        if star_files:
            apps.append({"id": entry.name, "star_file": star_files[0].name})
    return apps


def _find_app(app_id: str) -> Optional[dict]:
    for a in _list_installed_apps():
        if a["id"] == app_id:
            return a
    return None


def _session_is_alive() -> bool:
    proc = _current_session.get("process")
    return proc is not None and proc.poll() is None


PAGE_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <title>Pixlet Config Editor</title>
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <style>
        body { font-family: -apple-system, sans-serif; max-width: 700px; margin: 40px auto; padding: 0 20px; background: #15151d; color: #e8e8ec; }
        h1 { font-size: 1.4em; }
        .app-list { list-style: none; padding: 0; }
        .app-row { display: flex; justify-content: space-between; align-items: center; padding: 12px 16px; margin-bottom: 8px; background: #1f1f2c; border-radius: 8px; }
        .app-id { font-weight: 600; }
        button { background: #007fff; color: white; border: none; padding: 8px 16px; border-radius: 6px; cursor: pointer; font-size: 0.9em; }
        button:hover { background: #0066cc; }
        button.stop { background: #cc3333; }
        button.stop:hover { background: #a82929; }
        button:disabled { background: #444; cursor: not-allowed; }
        .session-banner { background: #2a4a2a; border: 1px solid #3a6a3a; border-radius: 8px; padding: 16px; margin-bottom: 20px; }
        .session-banner a { color: #7fff7f; }
        .empty { color: #888; padding: 20px; text-align: center; }
        .flash { background: #3a3a1f; border: 1px solid #6a6a3a; border-radius: 8px; padding: 12px 16px; margin-bottom: 16px; }
    </style>
</head>
<body>
    <h1>Pixlet Config Editor</h1>

    {% if flash %}
    <div class="flash">{{ flash }}</div>
    {% endif %}

    {% if session_active %}
    <div class="session-banner">
        <strong>Editing: {{ session_app_id }}</strong><br>
        Visit <a href="http://{{ request_host }}:8080/" target="_blank">http://{{ request_host }}:8080/</a> to make changes — they save automatically.<br><br>
        <form method="post" action="{{ url_for('stop_session') }}">
            <button type="submit" class="stop">Stop Editing &amp; Restart Display</button>
        </form>
    </div>
    {% endif %}

    {% if apps %}
    <ul class="app-list">
        {% for app in apps %}
        <li class="app-row">
            <span class="app-id">{{ app.id }}</span>
            <form method="post" action="{{ url_for('start_session', app_id=app.id) }}">
                <button type="submit" {% if session_active %}disabled{% endif %}>Edit Config</button>
            </form>
        </li>
        {% endfor %}
    </ul>
    {% else %}
    <div class="empty">No Starlark apps installed.</div>
    {% endif %}

    {% if not session_active %}
    <p style="margin-top: 30px;">
        <form method="post" action="{{ url_for('cleanup') }}" onsubmit="return confirm('Force-restart the display service? Only needed if a previous session got stuck.');">
            <button type="submit" class="stop">Force Cleanup / Restart Display</button>
        </form>
    </p>
    {% endif %}
</body>
</html>
"""


@app.route("/")
def index():
    return render_template_string(
        PAGE_TEMPLATE,
        apps=_list_installed_apps(),
        session_active=_session_is_alive(),
        session_app_id=_current_session.get("app_id"),
        request_host=request.host.split(":")[0],
        flash=request.args.get("flash"),
    )


@app.route("/start/<app_id>", methods=["POST"])
def start_session(app_id):
    if _session_is_alive():
        return redirect(url_for("index", flash="A session is already active — stop it first."))

    app_info = _find_app(app_id)
    if not app_info:
        return redirect(url_for("index", flash=f"No such app: {app_id}"))

    app_dir = STARLARK_APPS_DIR / app_id
    config_file = app_dir / "config.json"

    # Back up the existing config before pixlet starts writing to it live.
    if config_file.exists():
        backup = app_dir / "config.json.backup"
        backup.write_text(config_file.read_text())
    else:
        config_file.write_text("{}")

    # Stop the display service so it never reads config.json mid-write.
    subprocess.run(["sudo", "systemctl", "stop", "ledmatrix"], check=False)

    proc = subprocess.Popen(
        [
            PIXLET_BINARY, "serve", app_info["star_file"],
            "--host", "0.0.0.0",
            "--port", str(PIXLET_SERVE_PORT),
            "--no-browser",
            "--saveconfig", str(config_file),
        ],
        cwd=str(app_dir),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    _current_session["process"] = proc
    _current_session["app_id"] = app_id
    _current_session["started_at"] = time.time()

    return redirect(url_for("index"))


@app.route("/stop", methods=["POST"])
def stop_session():
    proc = _current_session.get("process")
    if proc is not None and proc.poll() is None:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()

    _current_session["process"] = None
    _current_session["app_id"] = None
    _current_session["started_at"] = None

    subprocess.run(["sudo", "systemctl", "restart", "ledmatrix"], check=False)

    return redirect(url_for("index", flash="Session stopped, display restarted."))


@app.route("/cleanup", methods=["POST"])
def cleanup():
    """Safety valve for when this Flask process itself restarted while a
    session was active — in-memory tracking is lost in that case, so this
    just force-restarts the display service regardless of tracked state."""
    proc = _current_session.get("process")
    if proc is not None and proc.poll() is None:
        proc.terminate()
    _current_session["process"] = None
    _current_session["app_id"] = None
    _current_session["started_at"] = None

    subprocess.run(["sudo", "systemctl", "restart", "ledmatrix"], check=False)
    return redirect(url_for("index", flash="Cleanup done, display restarted."))


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5050, debug=False)
