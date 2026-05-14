"""
app.py — Flask web server for the Nifty Pipeline dashboard.
Runs on Raspberry Pi, accessible on LAN.

Routes:
  GET  /                  → dashboard (last scan results)
  GET  /earnings          → earnings dashboard
  GET  /config            → config editor UI
  POST /config            → save config
  POST /run/<task>        → manually trigger a task or full pipeline
  GET  /api/status        → JSON status of last run + scheduler
  GET  /api/analyses      → JSON analyses
  GET  /api/shortlist     → JSON shortlist
  GET  /api/earnings      → JSON earnings
  GET  /logs              → last 200 log lines
"""

import json
import logging
import os
import threading
from datetime import datetime
from pathlib import Path

import yaml
from flask import Flask, jsonify, redirect, render_template, request, url_for

BASE_DIR  = Path(__file__).parent
DATA_DIR  = BASE_DIR / "data"
LOG_FILE  = BASE_DIR / "logs" / "pipeline.log"
CFG_PATH  = BASE_DIR / "config.yaml"

app    = Flask(__name__, template_folder=str(BASE_DIR / "templates"),
               static_folder=str(BASE_DIR / "static"))

logger = logging.getLogger(__name__)
_run_lock = threading.Lock()   # prevent concurrent pipeline runs


# ─── Helpers ─────────────────────────────────────────────────────────────────

def _load_json(name: str):
    p = DATA_DIR / f"{name}.json"
    if p.exists():
        with open(p) as f:
            return json.load(f)
    return None


def _load_cfg() -> dict:
    from core.config_loader import load_config
    return load_config(CFG_PATH)


def _run_in_bg(tasks: list[str]):
    """Run pipeline tasks in background thread so web request returns immediately."""
    def _run():
        if not _run_lock.acquire(blocking=False):
            logger.warning("Pipeline already running, skipping.")
            return
        try:
            cfg = _load_cfg()
            from core.pipeline import run_tasks
            run_tasks(tasks, cfg)
        finally:
            _run_lock.release()
    t = threading.Thread(target=_run, daemon=True)
    t.start()


# ─── Pages ───────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    cfg       = _load_cfg()
    analyses  = _load_json("analyses") or []
    shortlist = _load_json("shortlist") or []
    last_run  = _load_json("last_run")
    from core.scheduler import get_scheduler, list_jobs
    sched = get_scheduler()
    jobs  = list_jobs(sched) if sched else []
    is_running = _run_lock.locked()
    return render_template("index.html",
                           analyses=analyses,
                           shortlist=shortlist,
                           last_run=last_run,
                           jobs=jobs,
                           is_running=is_running,
                           cfg=cfg)


@app.route("/earnings")
def earnings_page():
    earnings = _load_json("earnings") or []
    last_run = _load_json("last_run")
    return render_template("earnings.html", earnings=earnings, last_run=last_run)


@app.route("/config", methods=["GET"])
def config_page():
    cfg = _load_cfg()
    return render_template("config.html", cfg=cfg)


@app.route("/config/save", methods=["POST"])
def config_save():
    """Accepts a full config dict as JSON, saves it, reloads the scheduler."""
    data = request.get_json(silent=True)
    if not data:
        return jsonify({"ok": False, "error": "No JSON body received"}), 400
    try:
        from core.config_loader import save_config
        save_config(data, CFG_PATH)
        from core.scheduler import reload_schedule
        reload_schedule(data, str(CFG_PATH))
        logger.info("Config updated via form UI.")
        return jsonify({"ok": True, "message": "Configuration saved. Scheduler reloaded."})
    except Exception as e:
        logger.exception(f"Config save error: {e}")
        return jsonify({"ok": False, "error": str(e)}), 400


@app.route("/config/yaml", methods=["GET", "POST"])
def config_yaml():
    """Raw YAML editor — for advanced edits (symbol lists, custom fields)."""
    msg = None
    if request.method == "POST":
        raw = request.form.get("config_yaml", "")
        try:
            new_cfg = yaml.safe_load(raw)
            from core.config_loader import save_config
            save_config(new_cfg, CFG_PATH)
            from core.scheduler import reload_schedule
            reload_schedule(new_cfg, str(CFG_PATH))
            msg = ("success", "Configuration saved and scheduler reloaded.")
            logger.info("Config updated via raw YAML editor.")
        except yaml.YAMLError as e:
            msg = ("error", f"YAML parse error: {e}")
        except Exception as e:
            msg = ("error", f"Save error: {e}")
    with open(CFG_PATH) as f:
        raw_yaml = f.read()
    return render_template("config_yaml.html", raw_yaml=raw_yaml, msg=msg)


@app.route("/logs")
def logs_page():
    lines = []
    if LOG_FILE.exists():
        with open(LOG_FILE) as f:
            lines = f.readlines()[-300:]
    return render_template("logs.html", lines=lines)


# ─── Manual Triggers ─────────────────────────────────────────────────────────

@app.route("/run/<task>", methods=["POST"])
def run_task(task: str):
    allowed = {
        "full":         ["fundamentals", "screen", "news", "ai_analysis",
                         "earnings_dashboard", "telegram_report"],
        "fundamentals": ["fundamentals"],
        "screen":       ["screen"],
        "news":         ["news"],
        "ai":           ["ai_analysis"],
        "earnings":     ["earnings_dashboard"],
        "telegram":     ["telegram_report"],
        "scan_only":    ["screen", "news", "ai_analysis"],
        "full_scan":    ["fundamentals", "screen", "news", "ai_analysis"],
    }
    tasks = allowed.get(task)
    if not tasks:
        return jsonify({"error": f"Unknown task '{task}'"}), 400

    if _run_lock.locked():
        return jsonify({"error": "A pipeline run is already in progress."}), 409

    _run_in_bg(tasks)
    return jsonify({"ok": True, "message": f"Started: {tasks}", "task": task})


# ─── JSON APIs ───────────────────────────────────────────────────────────────

@app.route("/api/status")
def api_status():
    from core.scheduler import get_scheduler, list_jobs
    sched = get_scheduler()
    jobs  = list_jobs(sched) if sched else []
    last  = _load_json("last_run")
    return jsonify({
        "is_running":  _run_lock.locked(),
        "last_run":    last,
        "jobs":        jobs,
        "server_time": datetime.now().isoformat(),
    })


@app.route("/api/analyses")
def api_analyses():
    return jsonify(_load_json("analyses") or [])


@app.route("/api/shortlist")
def api_shortlist():
    return jsonify(_load_json("shortlist") or [])


@app.route("/api/earnings")
def api_earnings():
    return jsonify(_load_json("earnings") or [])


# ─── Entry Point ─────────────────────────────────────────────────────────────

def create_app():
    cfg = _load_cfg()
    app.secret_key = cfg["web"].get("secret_key", "nifty_pipeline_secret")
    DATA_DIR.mkdir(exist_ok=True)

    from core.scheduler import init_scheduler
    init_scheduler(cfg, str(CFG_PATH))

    return app


if __name__ == "__main__":
    application = create_app()
    cfg = _load_cfg()
    application.run(
        host  = cfg["web"].get("host",  "0.0.0.0"),
        port  = cfg["web"].get("port",  5000),
        debug = cfg["web"].get("debug", False),
    )
