"""
telegram_notifier.py — Sends formatted reports to Telegram.
Uses Bot API (sendMessage with HTML parse mode).
"""

import logging
from datetime import datetime

import requests

logger = logging.getLogger(__name__)

TELEGRAM_API = "https://api.telegram.org/bot{token}/sendMessage"


def _send(token: str, chat_id: str, text: str, parse_mode: str = "HTML") -> bool:
    url    = TELEGRAM_API.format(token=token)
    chunks = [text[i:i+4000] for i in range(0, len(text), 4000)]
    ok     = True
    for chunk in chunks:
        try:
            r = requests.post(url, json={
                "chat_id":                  chat_id,
                "text":                     chunk,
                "parse_mode":               parse_mode,
                "disable_web_page_preview": True,
            }, timeout=15)
            r.raise_for_status()
        except Exception as e:
            logger.error(f"Telegram send error: {e}")
            ok = False
    return ok


def _rec_emoji(rec: str) -> str:
    return {"BUY": "🟢", "HOLD": "🟡", "AVOID": "🔴"}.get(rec, "⚪")


def _regime_emoji(regime: str) -> str:
    return {
        "STRONG_BULL": "🚀", "BULL": "📈",
        "BEAR": "📉",        "STRONG_BEAR": "⚠️",
    }.get(regime, "🔄")


def _cross_emoji(state: str) -> str:
    return {
        "GOLDEN_CROSS":        "✨",
        "GOLDEN_CROSS_FORMING":"🟡",
        "DEATH_CROSS":         "💀",
        "DEATH_CROSS_FORMING": "⚠️",
    }.get(state, "⚪")


# ─── Scan report ─────────────────────────────────────────────────────────────

def send_scan_report(analyses: list, shortlist_df, cfg: dict, regime: dict = None):
    if not cfg.get("telegram", {}).get("enabled"):
        return
    token   = cfg["api_keys"]["telegram_bot"]
    chat_id = str(cfg["api_keys"]["telegram_chat"])
    max_n   = cfg["telegram"].get("max_stocks_in_message", 10)

    import pandas as pd
    if not isinstance(shortlist_df, pd.DataFrame):
        shortlist_df = pd.DataFrame(shortlist_df)

    # ── Header with regime ────────────────────────────────────────────────────
    lines = ["<b>🔍 Nifty500 Scan Report</b>",
             f"<i>{datetime.now().strftime('%d %b %Y, %H:%M IST')}</i>"]

    if regime and regime.get("regime", "UNKNOWN") != "UNKNOWN":
        r = regime["regime"]
        close  = regime.get("nifty50_close", 0)
        pct    = regime.get("pct_above_ema200", 0)
        dd     = regime.get("drawdown_pct", 0)
        lines.append(
            f"{_regime_emoji(r)} Market: <b>{r}</b> | "
            f"Nifty50 ₹{close:,.0f} ({pct:+.1f}% vs EMA200) | "
            f"DD {dd:.1f}%"
        )

    lines += [
        f"Screened: {len(shortlist_df)} stocks | AI analysed: {len(analyses)}",
        "─────────────────────────",
    ]

    for a in analyses[:max_n]:
        sym       = a.get("symbol", "?")
        rec       = a.get("recommendation", "HOLD")
        sentiment = a.get("sentiment", "NEUTRAL")
        conf      = a.get("confidence", 0)
        summary   = a.get("summary", "")[:150]

        row       = shortlist_df[shortlist_df["symbol"] == sym]
        close_str = f"₹{row['last_close'].values[0]:.2f}"  if not row.empty else ""
        mom_str   = f"{row['momentum_ret'].values[0]:+.1f}%" if not row.empty else ""
        cross     = row["crossover_state"].values[0]         if not row.empty and "crossover_state" in row.columns else ""

        cross_tag = f" {_cross_emoji(cross)}{cross}" if cross else ""

        lines.append(
            f"{_rec_emoji(rec)} <b>{sym.split('.')[0]}</b> {close_str} ({mom_str}){cross_tag}\n"
            f"   <b>{rec}</b> | Sentiment: {sentiment} | Conf: {conf:.0%}\n"
            f"   <i>{summary}</i>"
        )

    if len(analyses) > max_n:
        lines.append(f"\n…and {len(analyses) - max_n} more. View dashboard for full report.")

    _send(token, chat_id, "\n".join(lines))
    logger.info("Telegram scan report sent.")


# ─── Earnings alert ───────────────────────────────────────────────────────────

def send_earnings_alert(earnings_data: list, cfg: dict):
    if not cfg.get("telegram", {}).get("send_earnings_alerts"):
        return
    token   = cfg["api_keys"]["telegram_bot"]
    chat_id = str(cfg["api_keys"]["telegram_chat"])

    soon = [e for e in earnings_data if e.get("earnings_soon")]
    if not soon:
        return

    lines = [
        "<b>📅 Earnings Alerts (Next 30 Days)</b>",
        f"<i>{datetime.now().strftime('%d %b %Y')}</i>",
        "─────────────────────────",
    ]
    for e in soon:
        br  = f"{e['beat_rate_pct']:.0f}%"   if e.get("beat_rate_pct")   is not None else "N/A"
        avg = f"{e['avg_surprise_pct']:+.1f}%" if e.get("avg_surprise_pct") is not None else "N/A"
        lines.append(
            f"📌 <b>{e['symbol']}</b> — {e['next_earnings']}\n"
            f"   Beat rate: {br} | Avg surprise: {avg}"
        )

    _send(token, chat_id, "\n".join(lines))
    logger.info(f"Telegram earnings alert sent for {len(soon)} stocks.")


# ─── Crossover alert ──────────────────────────────────────────────────────────

def send_crossover_alert(alerts: list, cfg: dict):
    """
    Sends a Telegram message for EMA50/200 crossover events.

    alert_type values:
      GOLDEN_CROSS          — EMA50 just crossed above EMA200 (strong buy signal)
      GOLDEN_CROSS_FORMING  — spread closing, predicted in N days
      DEATH_CROSS           — EMA50 just crossed below EMA200 (exit signal)
      DEATH_CROSS_FORMING   — spread widening negatively, predicted in N days
    """
    if not cfg.get("telegram", {}).get("enabled"):
        return
    token   = cfg["api_keys"]["telegram_bot"]
    chat_id = str(cfg["api_keys"]["telegram_chat"])

    lines = [
        "<b>⚡ EMA Crossover Alerts</b>",
        f"<i>{datetime.now().strftime('%d %b %Y, %H:%M IST')}</i>",
        "─────────────────────────",
    ]

    for a in alerts:
        sym        = a.get("symbol", "?").split(".")[0]
        atype      = a.get("alert_type", "")
        days       = a.get("days_to_cross")
        ema50      = a.get("ema50", 0)
        ema200     = a.get("ema200", 0)
        spread_pct = a.get("spread_pct", 0)
        close      = a.get("last_close", 0)
        sharpe     = a.get("sharpe_momentum", 0)

        emoji = _cross_emoji(atype)

        if atype == "GOLDEN_CROSS":
            desc = "🎯 <b>Golden Cross formed!</b> EMA50 crossed above EMA200."
        elif atype == "GOLDEN_CROSS_FORMING":
            desc = f"📐 Golden Cross forming — predicted in <b>~{days} days</b>"
        elif atype == "DEATH_CROSS":
            desc = "☠️ <b>Death Cross formed!</b> EMA50 crossed below EMA200."
        elif atype == "DEATH_CROSS_FORMING":
            desc = f"📉 Death Cross forming — predicted in <b>~{days} days</b>"
        else:
            desc = atype

        lines.append(
            f"{emoji} <b>{sym}</b> ₹{close:.2f} | Sharpe {sharpe:+.2f}\n"
            f"   {desc}\n"
            f"   EMA50 ₹{ema50:.0f} | EMA200 ₹{ema200:.0f} | Spread {spread_pct:+.1f}%"
        )

    _send(token, chat_id, "\n".join(lines))
    logger.info(f"Telegram crossover alert sent ({len(alerts)} events).")


# ─── Generic message ──────────────────────────────────────────────────────────

def send_simple_message(text: str, cfg: dict):
    if not cfg.get("telegram", {}).get("enabled"):
        return
    token   = cfg["api_keys"]["telegram_bot"]
    chat_id = str(cfg["api_keys"]["telegram_chat"])
    _send(token, chat_id, text)
