"""
earnings.py — Fetches upcoming earnings, historical beat/miss rate,
              and recent earnings surprises for the shortlisted universe.

Uses yfinance for free data (production: swap to AV EARNINGS endpoint).
"""

import logging
from datetime import datetime, timedelta
from typing import Optional

import pandas as pd

logger = logging.getLogger(__name__)


def _safe_get(ticker_obj, attr: str):
    try:
        val = getattr(ticker_obj, attr)
        if isinstance(val, pd.DataFrame) and val.empty:
            return None
        return val
    except Exception:
        return None


def get_earnings_data(symbols: list[str]) -> list[dict]:
    """
    For each symbol, return a dict with:
      - upcoming earnings date (if within 30 days)
      - last 8 quarters of EPS actuals vs estimates
      - beat rate
      - average surprise %
    """
    try:
        import yfinance as yf
    except ImportError:
        logger.error("yfinance not installed.")
        return []

    results = []
    now = datetime.now()
    thirty_days = now + timedelta(days=30)

    for sym in symbols:
        logger.debug(f"Fetching earnings data: {sym}")
        try:
            ticker = yf.Ticker(sym)

            # ── Earnings history ─────────────────────────────
            hist = _safe_get(ticker, "earnings_history")
            quarterly = []
            beat_count = 0

            if hist is not None and isinstance(hist, pd.DataFrame) and not hist.empty:
                hist = hist.sort_index(ascending=False).head(8)
                for idx, row in hist.iterrows():
                    eps_est   = row.get("epsEstimate",  None)
                    eps_act   = row.get("epsActual",    None)
                    surprise  = row.get("surprisePercent", None)
                    beat      = None
                    if eps_est is not None and eps_act is not None:
                        beat = eps_act > eps_est
                        if beat:
                            beat_count += 1
                    quarterly.append({
                        "quarter":      str(idx)[:10],
                        "eps_estimate": round(float(eps_est), 2) if eps_est is not None else None,
                        "eps_actual":   round(float(eps_act), 2) if eps_act is not None else None,
                        "surprise_pct": round(float(surprise), 2) if surprise is not None else None,
                        "beat":         beat,
                    })

            beat_rate = round(beat_count / len(quarterly) * 100, 1) if quarterly else None
            avg_surprise = None
            surprises = [q["surprise_pct"] for q in quarterly if q["surprise_pct"] is not None]
            if surprises:
                avg_surprise = round(sum(surprises) / len(surprises), 2)

            # ── Next earnings date ───────────────────────────
            cal = _safe_get(ticker, "calendar")
            next_earnings = None
            earnings_flag = False
            if cal is not None:
                # yfinance calendar can be a dict or DataFrame depending on version
                if isinstance(cal, dict):
                    ed = cal.get("Earnings Date")
                    if ed:
                        try:
                            # could be a list
                            ed_val = ed[0] if isinstance(ed, list) else ed
                            next_earnings = pd.Timestamp(ed_val).strftime("%Y-%m-%d")
                            if now <= pd.Timestamp(ed_val).to_pydatetime() <= thirty_days:
                                earnings_flag = True
                        except Exception:
                            pass
                elif isinstance(cal, pd.DataFrame):
                    if "Earnings Date" in cal.columns:
                        try:
                            ed_val = cal["Earnings Date"].iloc[0]
                            next_earnings = pd.Timestamp(ed_val).strftime("%Y-%m-%d")
                            if now <= pd.Timestamp(ed_val).to_pydatetime() <= thirty_days:
                                earnings_flag = True
                        except Exception:
                            pass

            results.append({
                "symbol":           sym,
                "next_earnings":    next_earnings,
                "earnings_soon":    earnings_flag,   # within 30 days
                "beat_rate_pct":    beat_rate,
                "avg_surprise_pct": avg_surprise,
                "quarters":         quarterly,
                "fetched_at":       datetime.now().isoformat(),
            })

        except Exception as e:
            logger.error(f"Earnings fetch failed for {sym}: {e}")
            results.append({
                "symbol": sym, "next_earnings": None, "earnings_soon": False,
                "beat_rate_pct": None, "avg_surprise_pct": None,
                "quarters": [], "fetched_at": datetime.now().isoformat(),
            })

    # sort: earnings_soon first, then by beat_rate desc
    results.sort(key=lambda x: (not x["earnings_soon"], -(x["beat_rate_pct"] or 0)))
    logger.info(f"Earnings data fetched for {len(results)} stocks. "
                f"Earnings soon: {sum(1 for r in results if r['earnings_soon'])}")
    return results
