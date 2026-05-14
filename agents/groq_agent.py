"""
groq_agent.py — Sends shortlisted stock data + news to Groq LLM for
                sentiment analysis and a structured trading recommendation.

Uses llama-3.3-70b-versatile (free tier on Groq).
"""

import json
import logging
import time
from datetime import datetime
from typing import Optional

import requests

logger = logging.getLogger(__name__)

GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"


def _build_prompt(symbol: str, score_data: dict, articles: list) -> str:
    news_block = ""
    if articles:
        for i, art in enumerate(articles, 1):
            news_block += (
                f"\n  [{i}] {art['published_at'][:10] if art['published_at'] else 'N/A'} "
                f"— {art['source']}\n"
                f"  Title: {art['title']}\n"
                f"  Summary: {art['description'] or art['content'] or 'No summary.'}\n"
            )
    else:
        news_block = "\n  No recent news articles found.\n"

    last_close = float(score_data.get('last_close') or 0)
    ema200     = float(score_data.get('ema200') or 0)
    atr_pct    = float(score_data.get('atr_pct') or 2.0)
    pct_above  = ((last_close / ema200) - 1) * 100 if ema200 > 0 else 0

    if pct_above > 15:
        entry_context = (
            f"ENTRY GUIDANCE: Current price ₹{last_close:.2f} is {pct_above:.1f}% ABOVE EMA200 ₹{ema200:.2f}. "
            f"This is a momentum trade — do NOT suggest waiting for the EMA level; that requires a "
            f"{pct_above:.0f}% correction and defeats the purpose. "
            f"suggested_entry_note should recommend buying near the CURRENT PRICE on a 1-3 day "
            f"intraday dip of ~{atr_pct:.1f}–{atr_pct*1.5:.1f}% (≈1 ATR), e.g. around "
            f"₹{last_close * (1 - atr_pct/100):.0f}–₹{last_close:.0f}."
        )
    elif pct_above > 5:
        entry_context = (
            f"ENTRY GUIDANCE: Price ₹{last_close:.2f} is {pct_above:.1f}% above EMA200 ₹{ema200:.2f}. "
            f"Suggest entry near current price on a minor pullback, not at the EMA level."
        )
    elif pct_above >= 0:
        entry_context = (
            f"ENTRY GUIDANCE: Price ₹{last_close:.2f} is just {pct_above:.1f}% above EMA200 ₹{ema200:.2f}. "
            f"A breakout-and-retest entry near EMA or current support is appropriate."
        )
    else:
        entry_context = (
            f"ENTRY GUIDANCE: Price ₹{last_close:.2f} is BELOW EMA200 ₹{ema200:.2f} — "
            f"confirm trend reversal before entry."
        )

    return f"""You are a professional equity analyst for Indian markets (BSE/NSE, Nifty500 universe).
This system uses a MOMENTUM strategy — stocks are selected because they are trending UP,
above their EMA200, with strong ADX and positive OBV. Analyse accordingly.

═══════════════════════════════════════
STOCK: {symbol}
Date:  {datetime.now().strftime('%Y-%m-%d')}
═══════════════════════════════════════

TECHNICAL SNAPSHOT (all data is current/live from today):
  Last Close:        ₹{last_close:.2f}
  EMA 200:           ₹{ema200:.2f}  (price is {pct_above:+.1f}% relative to EMA200)
  12-Month Momentum: {score_data.get('momentum_ret', 'N/A')}%
  RSI (14):          {score_data.get('rsi', 'N/A')}
  ADX (14):          {score_data.get('adx', 'N/A')}
  ATR % of Price:    {atr_pct:.2f}%  (≈₹{last_close * atr_pct / 100:.0f} per day)
  OBV Positive:      {score_data.get('obv_positive', 'N/A')}
  Composite Score:   {score_data.get('composite_score', 'N/A')} (0–1 scale)
  Rank in Shortlist: #{score_data.get('rank', 'N/A')}

RECENT NEWS:{news_block}

{entry_context}

═══════════════════════════════════════
Respond ONLY with a valid JSON object (no markdown, no preamble) with this exact structure:
{{
  "sentiment": "BULLISH" | "BEARISH" | "NEUTRAL",
  "sentiment_score": <float -1.0 to 1.0>,
  "confidence": <float 0.0 to 1.0>,
  "news_sentiment": "POSITIVE" | "NEGATIVE" | "NEUTRAL" | "MIXED",
  "key_positives": [<up to 3 short strings>],
  "key_risks": [<up to 3 short strings>],
  "recommendation": "BUY" | "HOLD" | "AVOID",
  "target_horizon": "short_term (1-4 weeks)" | "medium_term (1-3 months)",
  "suggested_entry_note": "<actionable entry near current price — see ENTRY GUIDANCE above>",
  "stop_loss_note": "<stop loss using ATR: e.g. stop at ₹X which is 2×ATR below entry>",
  "summary": "<2-3 sentence plain English summary mentioning current price vs EMA relationship>"
}}"""


def _call_groq(prompt: str, cfg: dict) -> Optional[str]:
    api_key = cfg["api_keys"]["groq"]
    model   = cfg["groq"]["model"]
    max_tok = cfg["groq"]["max_tokens"]
    temp    = cfg["groq"]["temperature"]

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type":  "application/json",
    }
    payload = {
        "model":       model,
        "messages":    [{"role": "user", "content": prompt}],
        "max_tokens":  max_tok,
        "temperature": temp,
    }
    try:
        r = requests.post(GROQ_API_URL, headers=headers, json=payload, timeout=30)
        r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"].strip()
    except requests.exceptions.HTTPError as e:
        if r.status_code == 429:
            logger.warning("Groq rate limit hit. Sleeping 30s.")
            time.sleep(30)
        else:
            logger.error(f"Groq HTTP error: {e} — {r.text[:200]}")
        return None
    except Exception as e:
        logger.error(f"Groq call error: {e}")
        return None


def _parse_response(raw: str, symbol: str) -> dict:
    try:
        clean = raw.strip().lstrip("```json").lstrip("```").rstrip("```").strip()
        result = json.loads(clean)
        result["symbol"]      = symbol
        result["analysed_at"] = datetime.now().isoformat()
        return result
    except json.JSONDecodeError as e:
        logger.error(f"JSON parse error for {symbol}: {e}\nRaw: {raw[:300]}")
        return {
            "symbol":               symbol,
            "sentiment":            "NEUTRAL",
            "sentiment_score":      0.0,
            "confidence":           0.0,
            "news_sentiment":       "NEUTRAL",
            "key_positives":        [],
            "key_risks":            ["Analysis failed — JSON parse error"],
            "recommendation":       "HOLD",
            "target_horizon":       "N/A",
            "suggested_entry_note": "N/A",
            "stop_loss_note":       "N/A",
            "summary":              f"AI analysis failed to parse for {symbol}.",
            "analysed_at":          datetime.now().isoformat(),
            "parse_error":          True,
        }


def run_ai_analysis(shortlist_df, news_data: dict, cfg: dict) -> list:
    analyses = []
    logger.info(f"Starting Groq AI analysis for {len(shortlist_df)} stocks")

    for _, row in shortlist_df.iterrows():
        sym      = row["symbol"]
        articles = news_data.get(sym, [])
        score    = row.to_dict()

        prompt  = _build_prompt(sym, score, articles)
        raw_out = _call_groq(prompt, cfg)

        if raw_out is None:
            logger.warning(f"No Groq response for {sym}, using fallback.")
            analyses.append({
                "symbol": sym, "sentiment": "NEUTRAL", "sentiment_score": 0.0,
                "confidence": 0.0, "recommendation": "HOLD",
                "summary": "AI analysis unavailable.", "analysed_at": datetime.now().isoformat(),
                "key_positives": [], "key_risks": [], "news_sentiment": "NEUTRAL",
                "target_horizon": "N/A", "suggested_entry_note": "N/A", "stop_loss_note": "N/A",
            })
        else:
            result = _parse_response(raw_out, sym)
            analyses.append(result)
            logger.info(f"  {sym}: {result.get('recommendation','?')} | "
                        f"sentiment={result.get('sentiment','?')} | "
                        f"confidence={result.get('confidence', 0):.2f}")

        time.sleep(2)

    order = {"BUY": 0, "HOLD": 1, "AVOID": 2}
    analyses.sort(key=lambda x: (order.get(x.get("recommendation", "HOLD"), 1),
                                  -x.get("confidence", 0)))

    logger.info(f"AI analysis complete. "
                f"BUY={sum(1 for a in analyses if a.get('recommendation')=='BUY')} | "
                f"HOLD={sum(1 for a in analyses if a.get('recommendation')=='HOLD')} | "
                f"AVOID={sum(1 for a in analyses if a.get('recommendation')=='AVOID')}")
    return analyses
