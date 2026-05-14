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


# ─── Prompt Builder ───────────────────────────────────────────────────────────

def _build_prompt(symbol: str, score_data: dict, articles: list[dict]) -> str:
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

    prompt = f"""You are a professional equity analyst for Indian markets (BSE/NSE, Nifty500 universe).

Analyse the following stock and provide a structured investment opinion.

═══════════════════════════════════════
STOCK: {symbol}
Date:  {datetime.now().strftime('%Y-%m-%d')}
═══════════════════════════════════════

TECHNICAL SNAPSHOT:
  Last Close:        ₹{score_data.get('last_close', 'N/A')}
  EMA 200:           ₹{score_data.get('ema200', 'N/A')}
  12-Month Momentum: {score_data.get('momentum_ret', 'N/A')}%
  RSI (14):          {score_data.get('rsi', 'N/A')}
  ADX (14):          {score_data.get('adx', 'N/A')}
  ATR % of Price:    {score_data.get('atr_pct', 'N/A')}%
  OBV Positive:      {score_data.get('obv_positive', 'N/A')}
  Composite Score:   {score_data.get('composite_score', 'N/A')} (0–1 scale)
  Rank in Shortlist: #{score_data.get('rank', 'N/A')}

RECENT NEWS:{news_block}

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
  "suggested_entry_note": "<one concise sentence on entry strategy>",
  "stop_loss_note": "<one concise sentence referencing ATR>",
  "summary": "<2-3 sentence plain English summary>"
}}"""
    return prompt


# ─── Groq Call ────────────────────────────────────────────────────────────────

def _call_groq(prompt: str, cfg: dict) -> Optional[str]:
    api_key   = cfg["api_keys"]["groq"]
    model     = cfg["groq"]["model"]
    max_tok   = cfg["groq"]["max_tokens"]
    temp      = cfg["groq"]["temperature"]

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": max_tok,
        "temperature": temp,
    }
    try:
        r = requests.post(GROQ_API_URL, headers=headers, json=payload, timeout=30)
        r.raise_for_status()
        data = r.json()
        return data["choices"][0]["message"]["content"].strip()
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
        # Strip any accidental markdown fences
        clean = raw.strip().lstrip("```json").lstrip("```").rstrip("```").strip()
        result = json.loads(clean)
        result["symbol"] = symbol
        result["analysed_at"] = datetime.now().isoformat()
        return result
    except json.JSONDecodeError as e:
        logger.error(f"JSON parse error for {symbol}: {e}\nRaw: {raw[:300]}")
        return {
            "symbol": symbol,
            "sentiment": "NEUTRAL",
            "sentiment_score": 0.0,
            "confidence": 0.0,
            "news_sentiment": "NEUTRAL",
            "key_positives": [],
            "key_risks": ["Analysis failed — JSON parse error"],
            "recommendation": "HOLD",
            "target_horizon": "N/A",
            "suggested_entry_note": "N/A",
            "stop_loss_note": "N/A",
            "summary": f"AI analysis failed to parse for {symbol}.",
            "analysed_at": datetime.now().isoformat(),
            "parse_error": True,
        }


# ─── Main Entry ──────────────────────────────────────────────────────────────

def run_ai_analysis(shortlist_df, news_data: dict, cfg: dict) -> list[dict]:
    """
    For each stock in shortlist, builds prompt with scores + news,
    calls Groq, parses structured JSON response.
    Returns list of analysis dicts.
    """
    threshold = cfg["news"].get("sentiment_confidence_threshold", 0.55)
    analyses  = []

    logger.info(f"Starting Groq AI analysis for {len(shortlist_df)} stocks")

    for _, row in shortlist_df.iterrows():
        sym      = row["symbol"]
        articles = news_data.get(sym, [])
        score    = row.to_dict()

        logger.debug(f"Analysing {sym} with {len(articles)} articles")
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

        time.sleep(2)  # stay within Groq free tier rate limits

    # Sort: BUY first, then HOLD, then AVOID; within each by confidence desc
    order = {"BUY": 0, "HOLD": 1, "AVOID": 2}
    analyses.sort(key=lambda x: (order.get(x.get("recommendation", "HOLD"), 1),
                                 -x.get("confidence", 0)))

    logger.info(f"AI analysis complete. "
                f"BUY={sum(1 for a in analyses if a.get('recommendation')=='BUY')} | "
                f"HOLD={sum(1 for a in analyses if a.get('recommendation')=='HOLD')} | "
                f"AVOID={sum(1 for a in analyses if a.get('recommendation')=='AVOID')}")
    return analyses
