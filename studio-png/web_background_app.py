from __future__ import annotations

import json
import socket
import subprocess
import threading
import time
import webbrowser
from pathlib import Path
from typing import Any

from flask import Flask, jsonify, render_template, request

from batch_remove_background import process_batch


APP_DIR = Path(__file__).resolve().parent
SETTINGS_PATH = APP_DIR / "tool_settings.json"

DEFAULT_SETTINGS: dict[str, Any] = {
    "models": ["birefnet-portrait", "u2net_human_seg", "bria-rmbg", "u2net"],
    "presets": {
        "normal": {
            "label": "Foto Normal",
            "canvas_width": 3600,
            "canvas_height": 4500,
            "subject_height": 4500,
            "bottom_margin": 0,
            "safe_width": True,
        },
        "cuadro": {
            "label": "Foto Cuadro",
            "canvas_width": 3600,
            "canvas_height": 4500,
            "subject_height": 4500,
            "bottom_margin": 0,
            "safe_width": True,
        },
    },
}


def deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def load_settings() -> dict[str, Any]:
    if SETTINGS_PATH.exists():
        with SETTINGS_PATH.open("r", encoding="utf-8") as file:
            data = json.load(file)
        return deep_merge(DEFAULT_SETTINGS, data)
    save_settings(DEFAULT_SETTINGS)
    return json.loads(json.dumps(DEFAULT_SETTINGS))


def save_settings(settings: dict[str, Any]) -> None:
    with SETTINGS_PATH.open("w", encoding="utf-8") as file:
        json.dump(settings, file, indent=2, ensure_ascii=False)


settings = load_settings()

app = Flask(__name__, template_folder=str(APP_DIR / "templates"), static_folder=str(APP_DIR / "static"))

job_state: dict[str, Any] = {
    "running": False,
    "done": False,
    "error": "",
    "logs": [],
    "started_at": None,
}
job_lock = threading.Lock()


def append_log(message: str) -> None:
    with job_lock:
        job_state["logs"].append(message)


def reset_job_state() -> None:
    with job_lock:
        job_state["running"] = True
        job_state["done"] = False
        job_state["error"] = ""
        job_state["logs"] = []
        job_state["started_at"] = time.time()


def finish_job(error: str = "") -> None:
    with job_lock:
        job_state["running"] = False
        job_state["done"] = not error
        job_state["error"] = error


@app.get("/")
def index():
    return render_template("index.html", settings=settings)


@app.get("/status")
def status():
    with job_lock:
        return jsonify(job_state)


@app.post("/save-preset")
def save_preset():
    payload = request.get_json(force=True)
    preset_name = payload.get("preset_name")
    if preset_name not in settings["presets"]:
        return jsonify({"ok": False, "error": "Preset no valido."}), 400

    settings["presets"][preset_name].update(
        {
            "canvas_width": int(payload["canvas_width"]),
            "canvas_height": int(payload["canvas_height"]),
            "subject_height": int(payload["subject_height"]),
            "bottom_margin": int(payload["bottom_margin"]),
            "safe_width": bool(payload["safe_width"]),
        }
    )
    save_settings(settings)
    return jsonify({"ok": True, "settings": settings})


def run_job(payload: dict[str, Any]) -> None:
    try:
        process_batch(
            input_root=payload["input_dir"],
            output_root=payload["output_dir"],
            model=payload["model"],
            limit=payload["limit"],
            overwrite=payload["overwrite"],
            alpha_matting=payload["alpha_matting"],
            autocrop=payload["autocrop"],
            output_mode=payload["output_mode"],
            canvas_width=payload["canvas_width"],
            canvas_height=payload["canvas_height"],
            subject_height=payload["subject_height"],
            bottom_margin=payload["bottom_margin"],
            safe_width=payload["safe_width"],
            progress_callback=append_log,
        )
        finish_job()
    except Exception as exc:
        append_log(f"ERROR: {exc}")
        finish_job(error=str(exc))


@app.post("/start")
def start():
    with job_lock:
        if job_state["running"]:
            return jsonify({"ok": False, "error": "Ya hay un proceso en marcha."}), 409

    payload = request.get_json(force=True)
    input_dir = Path(payload["input_dir"]).expanduser()
    output_dir = Path(payload["output_dir"]).expanduser()

    if not input_dir.exists() or not input_dir.is_dir():
        return jsonify({"ok": False, "error": "La carpeta de origen no es valida."}), 400
    if not output_dir.parent.exists():
        return jsonify({"ok": False, "error": "La carpeta padre del destino no existe."}), 400

    reset_job_state()

    worker = threading.Thread(
        target=run_job,
        kwargs={
            "payload": {
                "input_dir": str(input_dir),
                "output_dir": str(output_dir),
                "model": payload["model"],
                "limit": payload["limit"],
                "overwrite": payload["overwrite"],
                "alpha_matting": payload["alpha_matting"],
                "autocrop": payload["autocrop"],
                "output_mode": payload["output_mode"],
                "canvas_width": payload["canvas_width"],
                "canvas_height": payload["canvas_height"],
                "subject_height": payload["subject_height"],
                "bottom_margin": payload["bottom_margin"],
                "safe_width": payload["safe_width"],
            }
        },
        daemon=True,
    )
    worker.start()
    return jsonify({"ok": True})


@app.post("/open-output")
def open_output():
    payload = request.get_json(force=True)
    path = Path(payload["output_dir"]).expanduser()
    path.mkdir(parents=True, exist_ok=True)
    subprocess.Popen(["explorer", str(path.resolve())])
    return jsonify({"ok": True})


def find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def open_in_edge(url: str) -> None:
    edge_candidates = [
        Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"),
        Path(r"C:\Program Files\Microsoft\Edge\Application\msedge.exe"),
    ]
    for candidate in edge_candidates:
        if candidate.exists():
            subprocess.Popen([str(candidate), url])
            return
    webbrowser.open(url)


def main() -> None:
    port = find_free_port()
    url = f"http://127.0.0.1:{port}"
    threading.Timer(1.0, lambda: open_in_edge(url)).start()
    app.run(host="127.0.0.1", port=port, debug=False, use_reloader=False)


if __name__ == "__main__":
    main()
