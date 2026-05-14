"""
pipeline.py — Orchestrates all pipeline tasks.

Task order (recommended):
  1. fundamentals        — quality-filter all ~250 Nifty500 symbols (cached 24h)
  2. screen              — momentum + technical score on fundamentally-sound stocks
  3. news                — fetch news only for the top shortlist (saves NewsData credits)
  4. ai_analysis         — Groq LLM analysis combining technicals + news
  5. earnings_dashboard  — upcoming earnings, beat rates
  6. telegram_report     — push results to Telegram
"""

import json
import logging
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)

DATA_DIR = Path(__file__).parent.parent / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)


def _save(name: str, data) -> Path:
    path = DATA_DIR / f"{name}.json"
    with open(path, "w", encoding="utf-8") as f:
        if hasattr(data, "to_dict"):
            json.dump(data.to_dict(orient="records"), f, indent=2, default=str)
        else:
            json.dump(data, f, indent=2, default=str)
    return path


def _load(name: str):
    path = DATA_DIR / f"{name}.json"
    if path.exists():
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    return None


def run_tasks(task_list: list, cfg: dict) -> dict:
    from core.fundamentals        import screen_fundamentals
    from core.screener            import run_screener
    from core.news_fetcher        import fetch_news_for_shortlist
    from core.earnings            import get_earnings_data
    from agents.groq_agent        import run_ai_analysis
    from agents.telegram_notifier import send_scan_report, send_earnings_alert
    import pandas as pd

    status         = {}
    fund_df        = None    # fundamentally-filtered universe
    shortlist_df   = None    # technically-ranked shortlist
    news_data      = None
    analyses       = None
    earnings       = None

    # ── Lazy loaders from disk cache ──────────────────────────────────────────
    def get_fund_df():
        nonlocal fund_df
        if fund_df is None:
            cached = _load("fundamentals")
            if cached:
                fund_df = pd.DataFrame(cached)
                logger.info(f"Loaded cached fundamentals ({len(fund_df)} stocks).")
        return fund_df

    def get_shortlist():
        nonlocal shortlist_df
        if shortlist_df is None:
            cached = _load("shortlist")
            if cached:
                shortlist_df = pd.DataFrame(cached)
                logger.info(f"Loaded cached shortlist ({len(shortlist_df)} stocks).")
        return shortlist_df

    def get_news():
        nonlocal news_data
        if news_data is None:
            cached = _load("news_data")
            if cached:
                news_data = cached
                logger.info("Loaded cached news data.")
        return news_data

    def get_analyses():
        nonlocal analyses
        if analyses is None:
            cached = _load("analyses")
            if cached:
                analyses = cached
                logger.info(f"Loaded cached AI analyses ({len(analyses)} stocks).")
        return analyses

    start_ts = datetime.now().isoformat()
    logger.info(f"Pipeline run started | tasks={task_list}")

    for task in task_list:
        task_start = datetime.now()
        try:

            # ── 1. Fundamentals ───────────────────────────────────────────────
            if task == "fundamentals":
                logger.info("━━ Task: fundamentals (quality filter)")
                fund_df = screen_fundamentals(cfg)
                if fund_df is not None and not fund_df.empty:
                    _save("fundamentals", fund_df)
                    status[task] = {"ok": True, "passed": len(fund_df)}
                else:
                    status[task] = {"ok": False, "error": "No stocks passed fundamental filters"}

            # ── 2. Technical screen ───────────────────────────────────────────
            elif task == "screen":
                logger.info("━━ Task: screen (momentum + technical)")
                # Use fundamentally-filtered symbols if available, else config symbols
                fd = get_fund_df()
                if fd is not None and not fd.empty:
                    fund_symbols = fd["symbol"].tolist()
                    logger.info(f"  Input: {len(fund_symbols)} fundamentally-filtered symbols")
                else:
                    fund_symbols = None
                    logger.info("  No fundamentals data — using config symbol list")
                shortlist_df = run_screener(cfg, symbols=fund_symbols)
                if shortlist_df is not None and not shortlist_df.empty:
                    _save("shortlist", shortlist_df)
                    status[task] = {"ok": True, "count": len(shortlist_df)}
                else:
                    status[task] = {"ok": False, "error": "Screener returned empty results"}

            # ── 3. News (only for the shortlisted stocks) ─────────────────────
            elif task == "news":
                logger.info("━━ Task: news (shortlist only)")
                sl = get_shortlist()
                if sl is None or sl.empty:
                    status[task] = {"ok": False, "error": "No shortlist — run screen first"}
                    continue
                news_data = fetch_news_for_shortlist(sl, cfg)
                _save("news_data", news_data)
                covered = sum(1 for v in news_data.values() if v)
                status[task] = {"ok": True, "stocks_covered": covered,
                                "total": len(sl)}

            # ── 4. AI analysis ────────────────────────────────────────────────
            elif task == "ai_analysis":
                logger.info("━━ Task: ai_analysis")
                sl = get_shortlist()
                nd = get_news()
                if sl is None or sl.empty:
                    status[task] = {"ok": False, "error": "No shortlist available"}
                    continue
                analyses = run_ai_analysis(sl, nd or {}, cfg)
                _save("analyses", analyses)
                status[task] = {
                    "ok":    True,
                    "buy":   sum(1 for a in analyses if a.get("recommendation") == "BUY"),
                    "hold":  sum(1 for a in analyses if a.get("recommendation") == "HOLD"),
                    "avoid": sum(1 for a in analyses if a.get("recommendation") == "AVOID"),
                }

            # ── 5. Earnings dashboard ─────────────────────────────────────────
            elif task == "earnings_dashboard":
                logger.info("━━ Task: earnings_dashboard")
                sl = get_shortlist()
                if sl is not None and not sl.empty:
                    symbols = sl["symbol"].tolist()
                else:
                    from core.config_loader import get_symbols
                    symbols = get_symbols(cfg)[:20]
                earnings = get_earnings_data(symbols)
                _save("earnings", earnings)
                soon = sum(1 for e in earnings if e.get("earnings_soon"))
                status[task] = {"ok": True, "total": len(earnings), "earnings_soon": soon}

            # ── 6. Telegram report ────────────────────────────────────────────
            elif task == "telegram_report":
                logger.info("━━ Task: telegram_report")
                if not cfg.get("telegram", {}).get("enabled"):
                    status[task] = {"ok": True, "note": "Telegram disabled"}
                    continue
                sl = get_shortlist()
                an = get_analyses()
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
        ok_str = "✓" if status[task].get("ok") else "✗"
        detail = {k: v for k, v in status[task].items() if k not in ("ok", "elapsed_s")}
        logger.info(f"  {ok_str} '{task}' done in {elapsed:.1f}s  {detail}")

    run_log = {
        "started_at":  start_ts,
        "finished_at": datetime.now().isoformat(),
        "tasks":       task_list,
        "status":      status,
    }
    _save("last_run", run_log)
    logger.info(f"Pipeline complete | {' | '.join(f'{t}:{'OK' if s.get('ok') else 'FAIL'}' for t,s in status.items())}")
    return status
