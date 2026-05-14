"""
regime.py — Market regime detection using the Nifty50 index (^NSEI).

Determines whether the broad market is in a BULL or BEAR trend by comparing
the Nifty50 close to its EMA200.  Regime is saved to data/regime.json so
the dashboard can display it without re-fetching.
"""

import json
import logging
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

DATA_DIR = Path(__file__).parent.parent / "data"


def get_market_regime() -> dict:
    """
    Fetch Nifty50 index, compute EMA50/EMA200, classify regime.

    Returns a dict with keys:
      regime          — STRONG_BULL | BULL | BEAR | STRONG_BEAR | UNKNOWN
      above_ema200    — bool
      nifty50_close   — float
      nifty50_ema200  — float
      nifty50_ema50   — float
      drawdown_pct    — float (from 52-week high, negative)
      pct_above_ema200— float
      checked_at      — ISO timestamp
    """
    try:
        import yfinance as yf
        raw = yf.Ticker("^NSEI").history(period="2y", auto_adjust=True)
        if raw.empty:
            return _unknown("No data for ^NSEI")

        close = raw["Close"].rename("close")
        close.index = pd.to_datetime(close.index).tz_localize(None)

        ema200 = close.ewm(span=200, adjust=False).mean().iloc[-1]
        ema50  = close.ewm(span=50,  adjust=False).mean().iloc[-1]
        last   = float(close.iloc[-1])

        high_52w    = float(close.rolling(252).max().iloc[-1])
        drawdown    = (last - high_52w) / high_52w * 100
        pct_vs_ema  = (last - ema200) / ema200 * 100

        if last > ema200:
            regime = "STRONG_BULL" if drawdown > -5 else "BULL"
        else:
            regime = "STRONG_BEAR" if drawdown < -15 else "BEAR"

        result = {
            "regime":           regime,
            "above_ema200":     last > ema200,
            "nifty50_close":    round(last, 2),
            "nifty50_ema200":   round(float(ema200), 2),
            "nifty50_ema50":    round(float(ema50), 2),
            "drawdown_pct":     round(drawdown, 2),
            "pct_above_ema200": round(float(pct_vs_ema), 2),
            "checked_at":       datetime.now().isoformat(),
        }

        DATA_DIR.mkdir(exist_ok=True)
        with open(DATA_DIR / "regime.json", "w", encoding="utf-8") as f:
            json.dump(result, f, indent=2)

        logger.info(
            f"Market regime: {regime} | Nifty50 ₹{last:.0f} | "
            f"EMA200 ₹{ema200:.0f} ({pct_vs_ema:+.1f}%) | "
            f"Drawdown {drawdown:.1f}%"
        )
        return result

    except Exception as e:
        logger.error(f"Regime detection failed: {e}")
        return _unknown(str(e))


def _unknown(reason: str) -> dict:
    return {
        "regime":       "UNKNOWN",
        "above_ema200": True,   # default: don't restrict the scan
        "drawdown_pct": 0.0,
        "error":        reason,
        "checked_at":   datetime.now().isoformat(),
    }
