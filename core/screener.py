"""
screener.py — Fetches OHLCV data, computes momentum + technical scores,
              returns a ranked shortlist of Nifty500 stocks.

Supports both yfinance (testing) and Alpha Vantage (production).
"""

import logging
import time
from datetime import datetime, timedelta
from typing import Optional

import numpy as np
import pandas as pd
import requests

logger = logging.getLogger(__name__)


# ─── yfinance helpers ────────────────────────────────────────────────────────

def _fetch_yfinance(symbol: str, period: str = "2y") -> Optional[pd.DataFrame]:
    try:
        import yfinance as yf
        ticker = yf.Ticker(symbol)
        df = ticker.history(period=period, auto_adjust=True)
        if df.empty:
            logger.warning(f"[yfinance] No data for {symbol}")
            return None
        df.index = pd.to_datetime(df.index).tz_localize(None)
        df = df.rename(columns={"Open": "open", "High": "high", "Low": "low",
                                  "Close": "close", "Volume": "volume"})
        return df[["open", "high", "low", "close", "volume"]]
    except Exception as e:
        logger.error(f"[yfinance] Error fetching {symbol}: {e}")
        return None


# ─── Alpha Vantage helpers ────────────────────────────────────────────────────

def _fetch_alpha_vantage(symbol: str, api_key: str) -> Optional[pd.DataFrame]:
    url = (
        f"https://www.alphavantage.co/query"
        f"?function=TIME_SERIES_DAILY_ADJUSTED&symbol={symbol}"
        f"&outputsize=full&apikey={api_key}"
    )
    try:
        r = requests.get(url, timeout=15)
        data = r.json()
        key = "Time Series (Daily)"
        if key not in data:
            logger.warning(f"[AV] No data for {symbol}: {data.get('Note', data.get('Information', ''))}")
            return None
        rows = []
        for date_str, vals in data[key].items():
            rows.append({
                "date": pd.to_datetime(date_str),
                "open":   float(vals["1. open"]),
                "high":   float(vals["2. high"]),
                "low":    float(vals["3. low"]),
                "close":  float(vals["5. adjusted close"]),
                "volume": float(vals["6. volume"]),
            })
        df = pd.DataFrame(rows).set_index("date").sort_index()
        return df
    except Exception as e:
        logger.error(f"[AV] Error fetching {symbol}: {e}")
        return None


# ─── Technical Indicators (pure pandas — no TA-Lib dependency) ───────────────

def _ema(series: pd.Series, period: int) -> pd.Series:
    return series.ewm(span=period, adjust=False).mean()


def _rsi(close: pd.Series, period: int = 14) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0).rolling(period).mean()
    loss = (-delta.clip(upper=0)).rolling(period).mean()
    rs = gain / loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


def _adx(df: pd.DataFrame, period: int = 14) -> pd.Series:
    high, low, close = df["high"], df["low"], df["close"]
    tr = pd.concat([
        high - low,
        (high - close.shift()).abs(),
        (low - close.shift()).abs()
    ], axis=1).max(axis=1)
    dm_plus  = ((high - high.shift()) > (low.shift() - low)).astype(float) * (high - high.shift()).clip(lower=0)
    dm_minus = ((low.shift() - low) > (high - high.shift())).astype(float) * (low.shift() - low).clip(lower=0)
    atr   = tr.ewm(span=period, adjust=False).mean()
    di_p  = 100 * dm_plus.ewm(span=period, adjust=False).mean()  / atr
    di_m  = 100 * dm_minus.ewm(span=period, adjust=False).mean() / atr
    dx    = (100 * (di_p - di_m).abs() / (di_p + di_m).replace(0, np.nan))
    return dx.ewm(span=period, adjust=False).mean()


def _obv(df: pd.DataFrame) -> pd.Series:
    direction = np.sign(df["close"].diff().fillna(0))
    return (direction * df["volume"]).cumsum()


def _atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    high, low, close = df["high"], df["low"], df["close"]
    tr = pd.concat([
        high - low,
        (high - close.shift()).abs(),
        (low - close.shift()).abs()
    ], axis=1).max(axis=1)
    return tr.rolling(period).mean()


# ─── Scoring ─────────────────────────────────────────────────────────────────

def _score_stock(df: pd.DataFrame, cfg: dict) -> Optional[dict]:
    s_cfg = cfg["screening"]
    w = s_cfg["scoring_weights"]
    t_cfg = s_cfg["technical"]
    m_cfg = s_cfg["momentum"]

    if len(df) < 260:
        return None

    close = df["close"]

    lb   = m_cfg["lookback_days"]
    excl = m_cfg["exclude_recent_days"]
    if len(close) < lb + 5:
        return None
    momentum_ret = (close.iloc[-excl] / close.iloc[-lb]) - 1

    ema200 = _ema(close, 200).iloc[-1]
    last_close = close.iloc[-1]
    if t_cfg.get("ema_above_200") and last_close < ema200:
        return None

    rsi_val = _rsi(close).iloc[-1]
    if not (t_cfg["rsi_min"] <= rsi_val <= t_cfg["rsi_max"]):
        return None

    adx_val = _adx(df).iloc[-1]
    if adx_val < t_cfg["adx_min"]:
        return None

    obv_series = _obv(df).iloc[-20:]
    obv_slope = np.polyfit(range(len(obv_series)), obv_series.values, 1)[0]
    obv_positive = 1.0 if obv_slope > 0 else 0.0

    atr_val = _atr(df).iloc[-1]
    atr_pct = atr_val / last_close * 100

    mom_score  = np.clip((momentum_ret + 0.30) / 0.90, 0, 1)
    rsi_score  = 1 - abs(rsi_val - 55) / 55
    adx_score  = np.clip((adx_val - 20) / 40, 0, 1)
    vol_score  = obv_positive

    composite = (
        w["momentum_score"] * mom_score +
        w["rsi_score"]      * rsi_score +
        w["adx_score"]      * adx_score +
        w["volume_score"]   * vol_score
    )

    return {
        "last_close":      round(last_close, 2),
        "ema200":          round(ema200, 2),
        "momentum_ret":    round(momentum_ret * 100, 2),
        "rsi":             round(rsi_val, 2),
        "adx":             round(adx_val, 2),
        "atr_pct":         round(atr_pct, 2),
        "obv_positive":    bool(obv_positive),
        "composite_score": round(composite, 4),
    }


# ─── Main Screener ───────────────────────────────────────────────────────────

def run_screener(cfg: dict, symbols: list = None) -> pd.DataFrame:
    """
    symbols — pre-filtered list (e.g. from fundamentals stage).
              If None, falls back to the symbol list in config.yaml.
    """
    from core.config_loader import get_symbols

    source      = cfg["data_source"]
    av_key      = cfg["api_keys"].get("alpha_vantage", "")
    shortlist_n = cfg["universe"]["shortlist_size"]

    if symbols is None:
        symbols = get_symbols(cfg)

    results = []
    total = len(symbols)
    logger.info(f"Starting technical screen of {total} symbols via [{source}]")

    for i, sym in enumerate(symbols, 1):
        logger.debug(f"[{i}/{total}] Processing {sym}")

        if source == "yfinance":
            df = _fetch_yfinance(sym)
        else:
            df = _fetch_alpha_vantage(sym, av_key)
            time.sleep(12)  # AV free tier: 5 calls/min

        if df is None or df.empty:
            continue

        score = _score_stock(df, cfg)
        if score is None:
            logger.debug(f"  {sym} filtered out (technical criteria)")
            continue

        score["symbol"] = sym
        results.append(score)
        logger.info(f"  {sym}  score={score['composite_score']:.3f}  "
                    f"mom={score['momentum_ret']:+.1f}%  RSI={score['rsi']:.1f}  ADX={score['adx']:.1f}")

    if not results:
        logger.warning("Screener returned 0 results.")
        return pd.DataFrame()

    df_out = pd.DataFrame(results).sort_values("composite_score", ascending=False)
    df_out = df_out.reset_index(drop=True)
    shortlist = df_out.head(shortlist_n).copy()
    shortlist["rank"] = range(1, len(shortlist) + 1)
    shortlist["screened_at"] = datetime.now().isoformat()

    logger.info(f"Screener complete. Shortlist: {len(shortlist)} stocks.")
    return shortlist
