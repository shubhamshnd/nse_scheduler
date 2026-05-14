"""
pipeline.py — Orchestrates all pipeline tasks.
Can be triggered by the scheduler or manually via web UI.

Tasks:
  screen          → screener.py
  news            → news_fetcher.py
  ai_analysis     → groq_agent.py
  earnings_dashboard → earnings.py
  telegram_report → telegram_notifier.py
"""

import json
import logging
import os
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)

DATA_DIR = Path(__file__).parent.parent / "data"
DATA_DIR.mkdir(exist_ok=True)


def _save(name: str, data) -> Path:
    """Persist result to data/ as JSON."""
    path = DATA_DIR / f"{name}.json"
    with open(path, "w") as f:
        if hasattr(data, "to_dict"):
            json.dump(data.to_dict(orient="records"), f, indent=2, default=str)
        else:
            json.dump(data, f, indent=2, default=str)
    return path


def _load(name: str):
    path = DATA_DIR / f"{name}.json"
    if path.exists():
        with open(path) as f:
            return json.load(f)
    return None


def run_tasks(task_list: list[str], cfg: dict) -> dict:
    """
    Execute a list of task names in order.
    Returns a status dict per task.
    """
    from core.screener      import run_screener
    from core.news_fetcher  import fetch_news_for_shortlist
    from core.earnings      import get_earnings_data
    from agents.groq_agent  import run_ai_analysis
    from agents.telegram_notifier import (
        send_scan_report, send_earnings_alert, send_simple_message
    )
    import pandas as pd

    status   = {}
    shortlist_df = None
    news_data    = None
    analyses     = None
    earnings     = None

    # ── Load cached data if a task depends on a prior task not in this run ──
    def get_shortlist():
        nonlocal shortlist_df
        if shortlist_df is None:
            cached = _load("shortlist")
            if cached:
                shortlist_df = pd.DataFrame(cached)
                logger.info("Loaded cached shortlist from disk.")
        return shortlist_df

    def get_news():
        nonlocal news_data
        if news_data is None:
            cached = _load("news_data")
            if cached:
                news_data = cached
                logger.info("Loaded cached news data from disk.")
        return news_data

    def get_analyses():
        nonlocal analyses
        if analyses is None:
            cached = _load("analyses")
            if cached:
                analyses = cached
                logger.info("Loaded cached AI analyses from disk.")
        return analyses

    start_ts = datetime.now().isoformat()
    logger.info(f"Pipeline run started: tasks={task_list}")

    for task in task_list:
        task_start = datetime.now()
        try:
            # ──────────────────────────────────────────────
            if task == "screen":
                logger.info("▶ Task: screen")
                shortlist_df = run_screener(cfg)
                if shortlist_df is not None and not shortlist_df.empty:
                    _save("shortlist", shortlist_df)
                    status[task] = {"ok": True, "count": len(shortlist_df)}
                else:
                    status[task] = {"ok": False, "error": "Screener returned empty results"}

            # ──────────────────────────────────────────────
            elif task == "news":
                logger.info("▶ Task: news")
                sl = get_shortlist()
                if sl is None or sl.empty:
                    status[task] = {"ok": False, "error": "No shortlist available"}
                    continue
                news_data = fetch_news_for_shortlist(sl, cfg)
                _save("news_data", news_data)
                covered = sum(1 for v in news_data.values() if v)
                status[task] = {"ok": True, "stocks_covered": covered}

            # ──────────────────────────────────────────────
            elif task == "ai_analysis":
                logger.info("▶ Task: ai_analysis")
                sl = get_shortlist()
                nd = get_news()
                if sl is None or sl.empty:
                    status[task] = {"ok": False, "error": "No shortlist available"}
                    continue
                if nd is None:
                    nd = {}
                analyses = run_ai_analysis(sl, nd, cfg)
                _save("analyses", analyses)
                status[task] = {
                    "ok": True,
                    "buy":  sum(1 for a in analyses if a.get("recommendation") == "BUY"),
                    "hold": sum(1 for a in analyses if a.get("recommendation") == "HOLD"),
                    "avoid":sum(1 for a in analyses if a.get("recommendation") == "AVOID"),
                }

            # ──────────────────────────────────────────────
            elif task == "earnings_dashboard":
                logger.info("▶ Task: earnings_dashboard")
                sl = get_shortlist()
                if sl is not None and not sl.empty:
                    symbols = sl["symbol"].tolist()
                else:
                    from core.config_loader import get_symbols
                    symbols = get_symbols(cfg)[:20]  # fallback to first 20
                earnings = get_earnings_data(symbols)
                _save("earnings", earnings)
                soon = sum(1 for e in earnings if e.get("earnings_soon"))
                status[task] = {"ok": True, "total": len(earnings), "earnings_soon": soon}

            # ──────────────────────────────────────────────
            elif task == "telegram_report":
                logger.info("▶ Task: telegram_report")
                sl = get_shortlist()
                an = get_analyses()
                if not cfg.get("telegram", {}).get("enabled"):
                    status[task] = {"ok": True, "note": "Telegram disabled in config"}
                    continue
                if an and sl is not None and not sl.empty:
                    send_scan_report(an, sl, cfg)
                if earnings:
                    send_earnings_alert(earnings, cfg)
                status[task] = {"ok": True}

            else:
                logger.warning(f"Unknown task: {task}")
                status[task] = {"ok": False, "error": f"Unknown task '{task}'"}

        except Exception as e:
            logger.exception(f"Task '{task}' failed: {e}")
            status[task] = {"ok": False, "error": str(e)}

        elapsed = (datetime.now() - task_start).total_seconds()
        status[task]["elapsed_s"] = round(elapsed, 1)
        logger.info(f"  Task '{task}' done in {elapsed:.1f}s → {status[task]}")

    # Save run log
    run_log = {
        "started_at": start_ts,
        "finished_at": datetime.now().isoformat(),
        "tasks": task_list,
        "status": status,
    }
    _save("last_run", run_log)
    logger.info(f"Pipeline run complete: {status}")
    return status
