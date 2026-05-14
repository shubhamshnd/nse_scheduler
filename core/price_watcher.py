"""
price_watcher.py — Intraday price monitor for NSE stocks in entry zones.

Polls current prices using yfinance during NSE market hours and sends Telegram
alerts when a BUY-rated stock's price enters the entry zone computed by the
screener/Groq pipeline.

Only runs Mon–Fri, 09:15–15:30 IST. Deduplicates alerts within the same
process lifetime so the same stock doesn't spam on every interval tick.
"""

import json
import logging
from datetime import datetime, time as dtime
from pathlib import Path

logger = logging.getLogger(__name__)

DATA_DIR     = Path(__file__).parent.parent / "data"
MARKET_OPEN  = dtime(9, 15)
MARKET_CLOSE = dtime(15, 30)

# Symbols already alerted this process session — resets on restart (intentional:
# avoids spam across multiple intraday interval ticks).
_alerted_this_session: set = set()


def _ist_now():
    try:
        from zoneinfo import ZoneInfo
        return datetime.now(tz=ZoneInfo("Asia/Kolkata"))
    except ImportError:
        import pytz
        return datetime.now(tz=pytz.timezone("Asia/Kolkata"))


def _is_market_hours() -> bool:
    now = _ist_now()
    return now.weekday() < 5 and MARKET_OPEN <= now.time() <= MARKET_CLOSE


def _fetch_prices_bulk(symbols: list) -> dict:
    """
    Fetches last prices for a list of NSE symbols using yfinance fast_info.
    Falls back to 1-minute bar download if fast_info fails for a symbol.
    Returns {symbol: price} for successfully fetched symbols only.
    """
    import yfinance as yf

    prices = {}
    if not symbols:
        return prices

    try:
        tickers = yf.Tickers(" ".join(symbols))
        for sym in symbols:
            try:
                fi    = tickers.tickers[sym].fast_info
                price = fi.last_price
                if price and float(price) > 0:
                    prices[sym] = float(price)
            except Exception:
                pass
    except Exception as e:
        logger.warning(f"Bulk Tickers() fetch failed: {e}. Falling back to individual fetch.")

    # For symbols still missing, try 1d/1m download as fallback
    missing = [s for s in symbols if s not in prices]
    if missing:
        try:
            import yfinance as yf
            df = yf.download(
                " ".join(missing),
                period="1d",
                interval="1m",
                group_by="ticker",
                auto_adjust=True,
                progress=False,
                threads=True,
            )
            for sym in missing:
                try:
                    if len(missing) == 1:
                        last = df["Close"].dropna().iloc[-1]
                    else:
                        last = df[sym]["Close"].dropna().iloc[-1]
                    if last > 0:
                        prices[sym] = float(last)
                except Exception:
                    pass
        except Exception as e:
            logger.debug(f"Fallback download failed: {e}")

    return prices


def reset_session_alerts():
    """Call this at the start of each trading day to re-enable all alerts."""
    global _alerted_this_session
    _alerted_this_session = set()
    logger.info("Price watcher session alerts reset (new trading day).")


def check_entry_zones(cfg: dict) -> int:
    """
    Main entry point — called periodically during market hours.

    Loads the latest AI analyses, fetches current prices for all BUY-rated
    stocks, and fires a Telegram alert for any stock whose price has entered
    its computed entry zone.

    Returns the number of alerts triggered this call.
    """
    if not _is_market_hours():
        logger.debug("Price watcher: outside market hours, skipping.")
        return 0

    if not cfg.get("price_watcher", {}).get("enabled", False):
        logger.debug("Price watcher disabled in config.")
        return 0

    analyses_path = DATA_DIR / "analyses.json"
    if not analyses_path.exists():
        logger.debug("No analyses.json found — run AI analysis first.")
        return 0

    with open(analyses_path, encoding="utf-8") as f:
        analyses = json.load(f)

    # Only watch BUY-rated stocks with valid entry zones
    watchlist = [
        a for a in analyses
        if a.get("recommendation") == "BUY"
        and a.get("entry_low") is not None
        and a.get("entry_high") is not None
        and float(a.get("entry_low", 0)) > 0
        and float(a.get("entry_high", 0)) > 0
    ]

    if not watchlist:
        logger.info("Price watcher: no BUY-rated stocks with entry zones to watch.")
        return 0

    symbols = [a["symbol"] for a in watchlist]
    logger.info(f"Price watcher: checking {len(symbols)} BUY-rated stocks…")

    prices = _fetch_prices_bulk(symbols)
    if not prices:
        logger.warning("Price watcher: could not fetch any current prices.")
        return 0

    alert_data  = []
    for a in watchlist:
        sym        = a["symbol"]
        price      = prices.get(sym)
        entry_low  = float(a["entry_low"])
        entry_high = float(a["entry_high"])

        if not price:
            continue

        in_zone = entry_low <= price <= entry_high

        if in_zone and sym not in _alerted_this_session:
            _alerted_this_session.add(sym)
            alert_data.append({
                "symbol":         sym,
                "price":          price,
                "entry_low":      entry_low,
                "entry_high":     entry_high,
                "stop_loss":      a.get("stop_loss"),
                "target_1":       a.get("target_1"),
                "target_2":       a.get("target_2"),
                "hold_days_est":  a.get("hold_days_est"),
                "risk_reward":    a.get("risk_reward"),
                "confidence":     a.get("confidence", 0),
                "sentiment":      a.get("sentiment", ""),
                "position_size_note": a.get("position_size_note", ""),
                "summary":        a.get("summary", ""),
            })
            logger.info(
                f"  ENTRY ALERT: {sym} ₹{price:.2f} in zone ₹{entry_low:.2f}–₹{entry_high:.2f}"
            )
        else:
            logger.debug(
                f"  {sym} ₹{price:.2f} | zone ₹{entry_low:.2f}–₹{entry_high:.2f} "
                f"{'(in zone, already alerted)' if in_zone else '(outside zone)'}"
            )

    if alert_data:
        try:
            from agents.telegram_notifier import send_price_alert
            send_price_alert(alert_data, cfg)
        except Exception as e:
            logger.error(f"Price alert Telegram send failed: {e}")

    logger.info(
        f"Price watcher done: {len(prices)} prices fetched, "
        f"{len(alert_data)} new alert(s) sent."
    )
    return len(alert_data)
