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
    url = TELEGRAM_API.format(token=token)
    chunks = [text[i:i+4000] for i in range(0, len(text), 4000)]
    ok = True
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


def _emoji(rec: str) -> str:
    return {"BUY": "🟢", "HOLD": "🟡", "AVOID": "🔴"}.get(rec, "⚪")


def send_scan_report(analyses: list, shortlist_df, cfg: dict):
    if not cfg.get("telegram", {}).get("enabled"):
        return
    token   = cfg["api_keys"]["telegram_bot"]
    chat_id = str(cfg["api_keys"]["telegram_chat"])
    max_n   = cfg["telegram"].get("max_stocks_in_message", 10)

    import pandas as pd
    if not isinstance(shortlist_df, pd.DataFrame):
        shortlist_df = pd.DataFrame(shortlist_df)

    lines = [
        "<b>🔍 Nifty500 Scan Report</b>",
        f"<i>{datetime.now().strftime('%d %b %Y, %H:%M IST')}</i>",
        f"Screened: {len(shortlist_df)} stocks | AI analysed: {len(analyses)}",
        "─────────────────────────",
    ]

    for a in analyses[:max_n]:
        sym      = a.get("symbol", "?")
        rec      = a.get("recommendation", "HOLD")
        sentiment = a.get("sentiment", "NEUTRAL")
        conf     = a.get("confidence", 0)
        summary  = a.get("summary", "")[:150]

        row = shortlist_df[shortlist_df["symbol"] == sym]
        close_str = f"₹{row['last_close'].values[0]:.2f}" if not row.empty else ""
        mom_str   = f"{row['momentum_ret'].values[0]:+.1f}%" if not row.empty else ""

        lines.append(
            f"{_emoji(rec)} <b>{sym}</b> {close_str} ({mom_str})\n"
            f"   <b>{rec}</b> | Sentiment: {sentiment} | Conf: {conf:.0%}\n"
            f"   <i>{summary}</i>"
        )

    if len(analyses) > max_n:
        lines.append(f"\n…and {len(analyses) - max_n} more. View dashboard for full report.")

    _send(token, chat_id, "\n".join(lines))
    logger.info("Telegram scan report sent.")


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
        br  = f"{e['beat_rate_pct']:.0f}%" if e["beat_rate_pct"] is not None else "N/A"
        avg = f"{e['avg_surprise_pct']:+.1f}%" if e["avg_surprise_pct"] is not None else "N/A"
        lines.append(
            f"📌 <b>{e['symbol']}</b> — {e['next_earnings']}\n"
            f"   Beat rate: {br} | Avg surprise: {avg}"
        )

    _send(token, chat_id, "\n".join(lines))
    logger.info(f"Telegram earnings alert sent for {len(soon)} stocks.")


def send_simple_message(text: str, cfg: dict):
    if not cfg.get("telegram", {}).get("enabled"):
        return
    token   = cfg["api_keys"]["telegram_bot"]
    chat_id = str(cfg["api_keys"]["telegram_chat"])
    _send(token, chat_id, text)
