"""
fundamentals.py — Quality filter over the full Nifty 500 universe.

Runs BEFORE the technical screener to eliminate:
  - Micro-caps below market-cap threshold
  - Highly leveraged companies (D/E > limit, except banking/NBFC/Insurance)
  - Companies with negative operating cash flow
  - Companies with consistently shrinking revenue
  - Low ROE companies

Uses yfinance ticker.info (no extra API key required).
Results are cached for `cache_hours` so repeated pipeline runs reuse data.
"""

import json
import logging
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

import pandas as pd

logger = logging.getLogger(__name__)

DATA_DIR = Path(__file__).parent.parent / "data"

# Sectors where high D/E is structurally normal — skip D/E filter
_SKIP_DE_SECTORS = {
    "financial services", "banks", "insurance", "nbfc",
    "diversified financials",
}

# ── Cache helpers ─────────────────────────────────────────────────────────────

def _cache_path() -> Path:
    return DATA_DIR / "fundamentals_cache.json"


def _load_cache(cache_hours: int) -> Optional[list]:
    p = _cache_path()
    if not p.exists():
        return None
    try:
        with open(p, encoding="utf-8") as f:
            cache = json.load(f)
        ts = datetime.fromisoformat(cache.get("timestamp", "2000-01-01"))
        if datetime.now() - ts < timedelta(hours=cache_hours):
            logger.info(f"Fundamentals: using cached data ({ts.strftime('%H:%M %d-%b')}), "
                        f"{len(cache['data'])} stocks.")
            return cache["data"]
    except Exception as e:
        logger.warning(f"Could not read fundamentals cache: {e}")
    return None


def _save_cache(data: list):
    DATA_DIR.mkdir(exist_ok=True)
    p = _cache_path()
    with open(p, "w", encoding="utf-8") as f:
        json.dump({"timestamp": datetime.now().isoformat(), "data": data}, f, indent=2)


# ── Fundamental fetch & filter ────────────────────────────────────────────────

_INR_PER_CR = 1e7   # 1 Crore = 10,000,000


def _fetch_info(symbol: str) -> Optional[dict]:
    """Fetch yfinance .info for one symbol; return None on failure."""
    try:
        import yfinance as yf
        info = yf.Ticker(symbol).info
        if not info or info.get("regularMarketPrice") is None:
            return None
        return info
    except Exception as e:
        logger.debug(f"  [fund] {symbol}: info fetch failed — {e}")
        return None


def _apply_filters(symbol: str, info: dict, f_cfg: dict) -> tuple:
    """
    Returns (passes: bool, reason: str).
    reason is empty string on pass, short description on fail.
    """
    min_mcap_cr = f_cfg.get("min_market_cap_cr", 500)
    max_de      = f_cfg.get("max_debt_to_equity", 200)   # yfinance unit (%)
    min_rev_g   = f_cfg.get("min_revenue_growth", -0.15)  # -15% YoY allowed
    min_roe     = f_cfg.get("min_roe", 0.05)              # 5% ROE minimum
    req_pos_cf  = f_cfg.get("require_positive_cashflow", False)

    sector = (info.get("sector") or "").lower()
    is_fin = any(s in sector for s in _SKIP_DE_SECTORS)

    # ── Market cap ───────────────────────────────────────────────────────────
    mcap = info.get("marketCap") or 0
    if mcap < min_mcap_cr * _INR_PER_CR:
        return False, f"mcap {mcap/_INR_PER_CR:.0f}Cr < {min_mcap_cr}Cr"

    # ── Debt / Equity (skip for financials) ──────────────────────────────────
    if not is_fin:
        de = info.get("debtToEquity")
        if de is not None and de > max_de:
            return False, f"D/E {de:.0f}% > {max_de}%"

    # ── Revenue growth ───────────────────────────────────────────────────────
    rev_g = info.get("revenueGrowth")
    if rev_g is not None and rev_g < min_rev_g:
        return False, f"RevGrowth {rev_g:.1%}"

    # ── Return on equity ─────────────────────────────────────────────────────
    roe = info.get("returnOnEquity")
    if roe is not None and roe < min_roe:
        return False, f"ROE {roe:.1%} < {min_roe:.0%}"

    # ── Operating cash flow ──────────────────────────────────────────────────
    if req_pos_cf:
        op_cf = info.get("operatingCashflow")
        if op_cf is not None and op_cf < 0:
            return False, f"Neg OCF {op_cf/1e7:.0f}Cr"

    return True, ""


def _process_symbol(args: tuple) -> dict:
    """Worker: fetch info and apply filters. Returns result dict."""
    symbol, f_cfg = args
    info = _fetch_info(symbol)
    if info is None:
        return {"symbol": symbol, "ok": False, "reason": "no_data",
                "mcap_cr": None, "de": None, "roe": None, "sector": None}

    passes, reason = _apply_filters(symbol, info, f_cfg)
    mcap = info.get("marketCap") or 0
    return {
        "symbol":   symbol,
        "ok":       passes,
        "reason":   reason,
        "mcap_cr":  round(mcap / _INR_PER_CR, 1),
        "de":       info.get("debtToEquity"),
        "roe":      round(info.get("returnOnEquity") or 0, 4),
        "rev_growth": info.get("revenueGrowth"),
        "sector":   info.get("sector", ""),
        "industry": info.get("industry", ""),
        "name":     info.get("shortName", symbol),
        "fetched_at": datetime.now().isoformat(),
    }


# ── Main entry ────────────────────────────────────────────────────────────────

def screen_fundamentals(cfg: dict) -> pd.DataFrame:
    """
    Filters the full Nifty500 universe by fundamental quality criteria.

    Returns a DataFrame of symbols that pass — this becomes the input
    universe for the technical screener.
    """
    from core.config_loader import get_symbols
    from core.nifty500_symbols import NIFTY500_SYMBOLS

    f_cfg       = cfg.get("fundamentals", {})
    cache_hours = f_cfg.get("cache_hours", 24)
    max_workers = f_cfg.get("max_workers", 4)

    # Use preset Nifty500 list if configured, else config symbols
    if cfg.get("use_preset_nifty500", True):
        symbols = NIFTY500_SYMBOLS
    else:
        symbols = get_symbols(cfg)

    # ── Try cache first ───────────────────────────────────────────────────────
    cached = _load_cache(cache_hours)
    if cached is not None:
        passed = [r for r in cached if r["ok"]]
        logger.info(f"Fundamentals (cached): {len(passed)}/{len(cached)} pass filters.")
        return pd.DataFrame(passed)

    # ── Fresh fetch ───────────────────────────────────────────────────────────
    logger.info(f"Fetching fundamental data for {len(symbols)} symbols "
                f"(workers={max_workers}) — this may take a few minutes…")

    results = []
    args = [(sym, f_cfg) for sym in symbols]

    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {pool.submit(_process_symbol, a): a[0] for a in args}
        done = 0
        for future in as_completed(futures):
            res = future.result()
            results.append(res)
            done += 1
            if res["ok"]:
                logger.info(f"  ✓ [{done}/{len(symbols)}] {res['symbol']:<20} "
                            f"mcap={res['mcap_cr']:.0f}Cr  "
                            f"D/E={res['de'] or 0:.0f}%  ROE={res['roe']:.1%}  "
                            f"sector={res['sector']}")
            else:
                logger.debug(f"  ✗ [{done}/{len(symbols)}] {res['symbol']:<20} → {res['reason']}")

    _save_cache(results)

    passed = [r for r in results if r["ok"]]
    logger.info(f"Fundamentals complete: {len(passed)}/{len(results)} pass quality filters.")
    return pd.DataFrame(passed) if passed else pd.DataFrame()
