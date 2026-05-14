"""
screener.py — Momentum + technical screener with three hedge-fund-grade enhancements:

  1. Sharpe-adjusted momentum  — ranks by return/volatility, not raw return
  2. EMA50/200 crossover info  — detects golden/death cross, predicts days to next
  3. Sector concentration cap  — enforces max N stocks per sector in the shortlist
"""

import logging
import time
from datetime import datetime
from typing import Optional

import numpy as np
import pandas as pd
import requests

logger = logging.getLogger(__name__)


# ─── Data fetchers ────────────────────────────────────────────────────────────

def _fetch_yfinance(symbol: str, period: str = "2y") -> Optional[pd.DataFrame]:
    try:
        import yfinance as yf
        df = yf.Ticker(symbol).history(period=period, auto_adjust=True)
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
        rows = [
            {
                "date":   pd.to_datetime(d),
                "open":   float(v["1. open"]),
                "high":   float(v["2. high"]),
                "low":    float(v["3. low"]),
                "close":  float(v["5. adjusted close"]),
                "volume": float(v["6. volume"]),
            }
            for d, v in data[key].items()
        ]
        return pd.DataFrame(rows).set_index("date").sort_index()
    except Exception as e:
        logger.error(f"[AV] Error fetching {symbol}: {e}")
        return None


# ─── Technical indicators (pure pandas) ──────────────────────────────────────

def _ema(series: pd.Series, period: int) -> pd.Series:
    return series.ewm(span=period, adjust=False).mean()


def _rsi(close: pd.Series, period: int = 14) -> pd.Series:
    delta = close.diff()
    gain  = delta.clip(lower=0).rolling(period).mean()
    loss  = (-delta.clip(upper=0)).rolling(period).mean()
    rs    = gain / loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


def _adx(df: pd.DataFrame, period: int = 14) -> pd.Series:
    high, low, close = df["high"], df["low"], df["close"]
    tr = pd.concat([
        high - low,
        (high - close.shift()).abs(),
        (low  - close.shift()).abs(),
    ], axis=1).max(axis=1)
    dm_p = ((high - high.shift()) > (low.shift() - low)).astype(float) \
           * (high - high.shift()).clip(lower=0)
    dm_m = ((low.shift() - low) > (high - high.shift())).astype(float) \
           * (low.shift() - low).clip(lower=0)
    atr  = tr.ewm(span=period,  adjust=False).mean()
    di_p = 100 * dm_p.ewm(span=period, adjust=False).mean() / atr
    di_m = 100 * dm_m.ewm(span=period, adjust=False).mean() / atr
    dx   = 100 * (di_p - di_m).abs() / (di_p + di_m).replace(0, np.nan)
    return dx.ewm(span=period, adjust=False).mean()


def _obv(df: pd.DataFrame) -> pd.Series:
    return (np.sign(df["close"].diff().fillna(0)) * df["volume"]).cumsum()


def _atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    high, low, close = df["high"], df["low"], df["close"]
    tr = pd.concat([
        high - low,
        (high - close.shift()).abs(),
        (low  - close.shift()).abs(),
    ], axis=1).max(axis=1)
    return tr.rolling(period).mean()


# ─── Entry / Exit / Hold calculations ───────────────────────────────────────

def _entry_exit_calc(close: pd.Series, atr: float, ema50: float, ema200: float) -> dict:
    """
    Compute technically-derived entry zone, stop loss, targets, and hold estimate.

    Methodology (from professional swing-trading practice):
      Entry zone : current price down to max(EMA50, Fib 61.8% retracement, price - 1.5×ATR)
      Stop loss  : entry_low - 2×ATR  (2×ATR stop for swing traders)
      Target 1   : entry_high + 2×risk  (2:1 reward-to-risk)
      Target 2   : entry_high + 3×risk  (3:1 reward-to-risk — partial profit target)
      Hold est.  : ADX-based (strong trend → longer hold)
    """
    last = float(close.iloc[-1])

    # Fibonacci retracement (50-day swing high → 20-day swing low)
    swing_high = float(close.rolling(50).max().iloc[-1])
    swing_low  = float(close.rolling(20).min().iloc[-1])
    fib_range  = swing_high - swing_low if swing_high > swing_low else last * 0.1
    fib_382 = round(swing_high - fib_range * 0.382, 2)
    fib_618 = round(swing_high - fib_range * 0.618, 2)

    # Entry zone
    entry_high = round(last, 2)
    entry_low  = round(max(fib_618, ema50, last - 1.5 * atr), 2)
    entry_low  = min(entry_low, entry_high)  # safety: low ≤ high

    # Stop and targets
    stop_loss = round(entry_low - 2.0 * atr, 2)
    risk      = entry_high - stop_loss
    target_1  = round(entry_high + 2.0 * risk, 2)
    target_2  = round(entry_high + 3.0 * risk, 2)

    return {
        "entry_low":  entry_low,
        "entry_high": entry_high,
        "stop_loss":  stop_loss,
        "target_1":   target_1,
        "target_2":   target_2,
        "fib_382":    fib_382,
        "fib_618":    fib_618,
    }


def _hold_days_est(adx: float, momentum_ret: float) -> int:
    """
    Estimate hold duration in trading days from ADX strength.
    ADX > 40 = very strong trend → longer hold justified.
    """
    if adx >= 40:
        base = 35
    elif adx >= 30:
        base = 25
    elif adx >= 20:
        base = 15
    else:
        base = 7
    # Scale slightly by raw momentum magnitude
    if momentum_ret > 0.40:
        base = int(base * 1.2)
    elif momentum_ret < 0.10:
        base = int(base * 0.8)
    return min(max(base, 5), 60)


# ─── Crossover helpers ────────────────────────────────────────────────────────

def _crossover_info(close: pd.Series, ema50: float, ema200: float) -> dict:
    """
    Returns crossover_state and days_to_cross using a 30-day spread regression.

    crossover_state:
      GOLDEN_CROSS  — EMA50 crossed above EMA200 within last 10 days
      DEATH_CROSS   — EMA50 crossed below EMA200 within last 10 days
      BULLISH       — EMA50 above EMA200, no recent cross
      BEARISH       — EMA50 below EMA200, no recent cross

    days_to_cross:
      Positive integer = predicted calendar days until the next cross
      None = no crossing expected within 90 days at current trajectory
    """
    ema50_s  = _ema(close, 50).iloc[-31:]
    ema200_s = _ema(close, 200).iloc[-31:]
    spread   = (ema50_s - ema200_s)

    # Recent sign change detection (within last 10 bars)
    sign_now  = np.sign(spread.iloc[-1])
    sign_past = np.sign(spread.iloc[-10])
    recent_cross = (sign_now != sign_past) and (sign_past != 0)

    if ema50 > ema200:
        state = "GOLDEN_CROSS" if recent_cross else "BULLISH"
    else:
        state = "DEATH_CROSS"  if recent_cross else "BEARISH"

    # Predict days to next crossover via OLS on 30-day spread
    days_to_cross = None
    s30 = spread.iloc[-30:].dropna()
    if len(s30) >= 10:
        x = np.arange(len(s30))
        slope, intercept = np.polyfit(x, s30.values, 1)
        if abs(slope) > 0.01:
            # Extrapolate from last point (index = len-1) to spread = 0
            projected = intercept + slope * (len(s30) - 1)
            d = -projected / slope
            d = int(round(d))
            if 1 <= d <= 90:
                days_to_cross = d

    return {"crossover_state": state, "days_to_cross": days_to_cross}


# ─── Scoring ─────────────────────────────────────────────────────────────────

def _score_stock(df: pd.DataFrame, cfg: dict) -> Optional[dict]:
    s_cfg = cfg["screening"]
    w     = s_cfg["scoring_weights"]
    t_cfg = s_cfg["technical"]
    m_cfg = s_cfg["momentum"]

    if len(df) < 260:
        return None

    close = df["close"]

    # ── EMA filters ──────────────────────────────────────────────────────────
    ema200 = _ema(close, 200).iloc[-1]
    ema50  = _ema(close, 50).iloc[-1]
    last_close = close.iloc[-1]

    if t_cfg.get("ema_above_200") and last_close < ema200:
        return None

    if t_cfg.get("require_golden_cross", False) and ema50 < ema200:
        return None

    # ── Raw 12-1 momentum ────────────────────────────────────────────────────
    lb, excl = m_cfg["lookback_days"], m_cfg["exclude_recent_days"]
    if len(close) < lb + 5:
        return None
    momentum_ret = (close.iloc[-excl] / close.iloc[-lb]) - 1

    # ── Sharpe-adjusted momentum (rank signal) ───────────────────────────────
    monthly = close.resample("ME").last().pct_change().dropna()
    if len(monthly) >= 6:
        std = monthly.std()
        sharpe_mom = (monthly.mean() / std * np.sqrt(12)) if std > 0 else 0.0
    else:
        sharpe_mom = momentum_ret  # fallback for short history

    # ── RSI ──────────────────────────────────────────────────────────────────
    rsi_val = _rsi(close).iloc[-1]
    if not (t_cfg["rsi_min"] <= rsi_val <= t_cfg["rsi_max"]):
        return None

    # ── ADX ──────────────────────────────────────────────────────────────────
    adx_val = _adx(df).iloc[-1]
    if adx_val < t_cfg["adx_min"]:
        return None

    # ── OBV trend ────────────────────────────────────────────────────────────
    obv_series  = _obv(df).iloc[-20:]
    obv_slope   = np.polyfit(range(len(obv_series)), obv_series.values, 1)[0]
    obv_positive = 1.0 if obv_slope > 0 else 0.0

    # ── ATR ──────────────────────────────────────────────────────────────────
    atr_pct = _atr(df).iloc[-1] / last_close * 100

    # ── Composite score ───────────────────────────────────────────────────────
    # Sharpe momentum normalised: Sharpe -1→0, 0→0.33, 2→1.0
    mom_score  = float(np.clip((sharpe_mom + 1.0) / 3.0, 0, 1))
    rsi_score  = 1 - abs(rsi_val - 55) / 55
    adx_score  = float(np.clip((adx_val - 20) / 40, 0, 1))
    vol_score  = obv_positive

    composite = (
        w["momentum_score"] * mom_score +
        w["rsi_score"]      * rsi_score +
        w["adx_score"]      * adx_score +
        w["volume_score"]   * vol_score
    )

    # ── EMA50/200 crossover metadata ─────────────────────────────────────────
    cross = _crossover_info(close, ema50, ema200)

    # ── Entry / exit / hold (technical) ──────────────────────────────────────
    atr_val    = _atr(df).iloc[-1]
    trade      = _entry_exit_calc(close, atr_val, ema50, ema200)
    hold_days  = _hold_days_est(adx_val, momentum_ret)

    return {
        "last_close":      round(last_close, 2),
        "ema200":          round(ema200, 2),
        "ema50":           round(ema50, 2),
        "spread_pct":      round((ema50 - ema200) / last_close * 100, 2),
        "crossover_state": cross["crossover_state"],
        "days_to_cross":   cross["days_to_cross"],
        "momentum_ret":    round(momentum_ret * 100, 2),
        "sharpe_momentum": round(float(sharpe_mom), 3),
        "rsi":             round(rsi_val, 2),
        "adx":             round(adx_val, 2),
        "atr_pct":         round(atr_pct, 2),
        "obv_positive":    bool(obv_positive),
        "composite_score": round(composite, 4),
        # ── Trade levels (technical) ─────────────────────────────────────────
        "entry_low":       trade["entry_low"],
        "entry_high":      trade["entry_high"],
        "stop_loss":       trade["stop_loss"],
        "target_1":        trade["target_1"],
        "target_2":        trade["target_2"],
        "fib_382":         trade["fib_382"],
        "fib_618":         trade["fib_618"],
        "hold_days_est":   hold_days,
    }


# ─── Main screener ────────────────────────────────────────────────────────────

def run_screener(cfg: dict,
                 symbols:  list = None,
                 fund_df:  pd.DataFrame = None,
                 regime:   dict = None) -> pd.DataFrame:
    """
    symbols  — pre-filtered list from fundamentals stage (None → config symbols)
    fund_df  — fundamentals DataFrame with 'sector' column for sector-cap logic
    regime   — market regime dict from regime.get_market_regime()
    """
    from core.config_loader import get_symbols

    source      = cfg["data_source"]
    av_key      = cfg["api_keys"].get("alpha_vantage", "")
    s_cfg       = cfg.get("screening", {})
    r_cfg       = s_cfg.get("regime_filter", {})
    sector_cap  = s_cfg.get("sector_cap", 4)

    # ── Regime-aware shortlist size ───────────────────────────────────────────
    shortlist_n = cfg["universe"]["shortlist_size"]
    if regime and not regime.get("above_ema200", True) and r_cfg.get("enabled", True):
        bear_n = r_cfg.get("bear_shortlist_size", 5)
        logger.warning(
            f"BEAR market (Nifty50 below EMA200) — shrinking shortlist "
            f"{shortlist_n} → {bear_n}"
        )
        shortlist_n = bear_n

    # ── Symbol list ───────────────────────────────────────────────────────────
    if symbols is None:
        symbols = get_symbols(cfg)

    # ── Sector map from fundamentals ──────────────────────────────────────────
    sector_map = {}
    if fund_df is not None and not fund_df.empty and "sector" in fund_df.columns:
        sector_map = dict(zip(fund_df["symbol"], fund_df["sector"].fillna("Unknown")))

    results = []
    total   = len(symbols)
    logger.info(f"Starting technical screen of {total} symbols via [{source}]")

    for i, sym in enumerate(symbols, 1):
        if source == "yfinance":
            df = _fetch_yfinance(sym)
        else:
            df = _fetch_alpha_vantage(sym, av_key)
            time.sleep(12)

        if df is None or df.empty:
            continue

        score = _score_stock(df, cfg)
        if score is None:
            logger.debug(f"  [{i}/{total}] {sym} filtered out")
            continue

        score["symbol"] = sym
        score["sector"] = sector_map.get(sym, "Unknown")
        results.append(score)
        logger.info(
            f"  {sym:<22} score={score['composite_score']:.3f}  "
            f"mom={score['momentum_ret']:+.1f}%  "
            f"sharpe={score['sharpe_momentum']:+.2f}  "
            f"RSI={score['rsi']:.1f}  ADX={score['adx']:.1f}  "
            f"[{score['crossover_state']}]"
        )

    if not results:
        logger.warning("Screener returned 0 results.")
        return pd.DataFrame()

    df_out = pd.DataFrame(results).sort_values("composite_score", ascending=False)

    # ── Sector concentration cap ──────────────────────────────────────────────
    if sector_cap and sector_cap > 0:
        sector_counts: dict = {}
        capped = []
        for _, row in df_out.iterrows():
            sec = row.get("sector", "Unknown")
            if sector_counts.get(sec, 0) < sector_cap:
                capped.append(row)
                sector_counts[sec] = sector_counts.get(sec, 0) + 1
            if len(capped) >= shortlist_n:
                break
        shortlist = pd.DataFrame(capped).reset_index(drop=True)

        # Log if cap was applied
        if len(shortlist) < len(df_out.head(shortlist_n)):
            capped_sectors = {s: c for s, c in sector_counts.items() if c >= sector_cap}
            logger.info(f"Sector cap ({sector_cap}/sector) applied. "
                        f"Capped: {capped_sectors}")
    else:
        shortlist = df_out.head(shortlist_n).reset_index(drop=True)

    shortlist["rank"]         = range(1, len(shortlist) + 1)
    shortlist["screened_at"]  = datetime.now().isoformat()

    logger.info(f"Screener complete. Shortlist: {len(shortlist)} stocks.")
    return shortlist
