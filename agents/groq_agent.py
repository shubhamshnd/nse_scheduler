"""
groq_agent.py — Sends shortlisted stock data + news to Groq LLM for
                professional-grade analysis with entry/exit/hold recommendations.

System prompt design principles (from LLM equity-analysis research):
  • Chain-of-thought: reason step-by-step before outputting JSON
  • Structured context: technicals first, then news, then trade guidance
  • Explicit output schema with defined value ranges
  • Momentum-aware entry: never suggest waiting for distant EMA levels
  • Dual-layer validation: technical levels provided as reference for Groq to refine
"""

import json
import logging
import time
from datetime import datetime
from typing import Optional

import requests

logger = logging.getLogger(__name__)

GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"

SYSTEM_PROMPT = """You are a senior quantitative equity analyst specializing in Indian markets (NSE/BSE, Nifty500 universe).

Your role:
- Analyse momentum stocks already passing a multi-stage quantitative screen (fundamentals → technicals → news)
- Stocks are pre-filtered: above EMA200, ADX > 20, RSI 35-72, positive OBV trend — they are TRENDING UP
- Provide ACTIONABLE trade recommendations with specific price levels, not vague guidance

Analytical framework (Chain-of-Thought — reason through each step before outputting):
1. MOMENTUM CONTEXT: Is the trend strong, weakening, or exhausted? (ADX, RSI position, Sharpe)
2. ENTRY LOGIC: Where should a swing trader enter? Reference the technical levels provided, refine if news/context suggests adjustment
3. RISK MANAGEMENT: Stop loss must be ATR-based. Never place stops at round numbers alone.
4. TARGET SETTING: Use R:R ≥ 2:1. Adjust if news suggests a catalyst that could drive higher.
5. HOLD DURATION: Factor in ADX strength, earnings calendar, and news momentum
6. NEWS IMPACT: Assess if recent news accelerates or threatens the technical trend

Critical rules:
- If price is >10% above EMA200: this is a momentum trade — do NOT suggest entering "near EMA200"
- Entry must be near CURRENT PRICE (within 1-2 ATR), not at distant support levels
- Stop loss = entry_low - 2×ATR (provided in technical data; refine if needed)
- Be specific: give ₹ levels, not percentages alone
- Confidence should reflect BOTH technical quality AND news sentiment alignment"""


def _build_prompt(symbol: str, score_data: dict, articles: list) -> str:
    # ── News block ────────────────────────────────────────────────────────────
    if articles:
        news_block = ""
        for i, art in enumerate(articles, 1):
            date = art['published_at'][:10] if art.get('published_at') else 'N/A'
            news_block += (
                f"\n  [{i}] {date} — {art.get('source','?')}\n"
                f"  Title: {art.get('title','')}\n"
                f"  Summary: {art.get('description') or art.get('content') or 'No summary.'}\n"
            )
    else:
        news_block = "\n  No recent news — analysis based on technicals only.\n"

    # ── Derived values ────────────────────────────────────────────────────────
    last_close   = float(score_data.get('last_close') or 0)
    ema200       = float(score_data.get('ema200') or 0)
    ema50        = float(score_data.get('ema50') or 0)
    atr_pct      = float(score_data.get('atr_pct') or 2.0)
    atr_val      = last_close * atr_pct / 100
    pct_above    = ((last_close / ema200) - 1) * 100 if ema200 > 0 else 0
    spread_pct   = float(score_data.get('spread_pct') or 0)
    sharpe       = float(score_data.get('sharpe_momentum') or 0)
    cross_state  = score_data.get('crossover_state', 'BULLISH')
    days_to_cross= score_data.get('days_to_cross')

    # Technical trade levels (pre-computed, Groq refines)
    entry_low    = float(score_data.get('entry_low') or last_close * 0.97)
    entry_high   = float(score_data.get('entry_high') or last_close)
    stop_loss    = float(score_data.get('stop_loss') or (entry_low - 2 * atr_val))
    target_1     = float(score_data.get('target_1') or (entry_high + 2 * (entry_high - stop_loss)))
    target_2     = float(score_data.get('target_2') or (entry_high + 3 * (entry_high - stop_loss)))
    fib_382      = float(score_data.get('fib_382') or 0)
    fib_618      = float(score_data.get('fib_618') or 0)
    hold_days    = int(score_data.get('hold_days_est') or 20)

    # ── Entry context guidance based on EMA distance ──────────────────────────
    if pct_above > 15:
        entry_guidance = (
            f"MOMENTUM ENTRY: Price ₹{last_close:.2f} is {pct_above:.1f}% ABOVE EMA200 ₹{ema200:.2f}. "
            f"Do NOT suggest waiting for EMA200 — that is a {pct_above:.0f}% correction and defeats momentum strategy. "
            f"Entry zone is ₹{entry_low:.0f}–₹{entry_high:.0f} (near current price, 1-1.5×ATR pullback)."
        )
    elif pct_above > 5:
        entry_guidance = (
            f"PULLBACK ENTRY: Price ₹{last_close:.2f} is {pct_above:.1f}% above EMA200 ₹{ema200:.2f}. "
            f"Entry zone ₹{entry_low:.0f}–₹{entry_high:.0f}. A minor pullback is acceptable."
        )
    else:
        entry_guidance = (
            f"BREAKOUT ENTRY: Price ₹{last_close:.2f} is near EMA200 ₹{ema200:.2f} ({pct_above:+.1f}%). "
            f"Entry on confirmed breakout above ₹{entry_high:.0f} or retest at ₹{entry_low:.0f}."
        )

    cross_note = ""
    if cross_state == "GOLDEN_CROSS":
        cross_note = "⚡ GOLDEN CROSS just formed (EMA50 crossed above EMA200) — strong momentum confirmation."
    elif cross_state == "DEATH_CROSS":
        cross_note = "⚠️ DEATH CROSS recently formed — exercise extra caution, consider HOLD/AVOID."
    elif days_to_cross and cross_state == "BEARISH":
        cross_note = f"📐 Golden Cross forming: EMA50 predicted to cross EMA200 in ~{days_to_cross} days."

    return f"""═══════════════════════════════════════════════════════════════
STOCK ANALYSIS REQUEST: {symbol}
Date: {datetime.now().strftime('%Y-%m-%d %H:%M IST')}
═══════════════════════════════════════════════════════════════

TECHNICAL SNAPSHOT:
  Last Close:         ₹{last_close:.2f}
  EMA 200 (trend):    ₹{ema200:.2f}  ({pct_above:+.1f}% above EMA200)
  EMA 50  (momentum): ₹{ema50:.2f}  (spread {spread_pct:+.1f}% of price)
  Crossover State:    {cross_state}{' | ' + cross_note if cross_note else ''}
  12M Momentum (raw): {score_data.get('momentum_ret', 'N/A')}%
  Sharpe Momentum:    {sharpe:.2f}  (return/volatility, annualised; >1.0 = excellent)
  RSI (14):           {score_data.get('rsi', 'N/A')}
  ADX (14):           {score_data.get('adx', 'N/A')}  (>40 = very strong trend)
  ATR (14):           {atr_pct:.2f}% = ₹{atr_val:.0f}/day
  OBV Positive:       {score_data.get('obv_positive', 'N/A')}
  Composite Score:    {score_data.get('composite_score', 'N/A')} / 1.0
  Rank:               #{score_data.get('rank', 'N/A')}

FIBONACCI LEVELS (50-day swing high → 20-day low):
  38.2% retracement:  ₹{fib_382:.2f}  (shallow pullback entry)
  61.8% retracement:  ₹{fib_618:.2f}  (deep pullback / capitulation entry)

PRE-COMPUTED TRADE LEVELS (technical — refine with your analysis):
  Entry Zone:  ₹{entry_low:.2f} – ₹{entry_high:.2f}
  Stop Loss:   ₹{stop_loss:.2f}  (entry_low − 2×ATR; adjust if needed)
  Target 1:    ₹{target_1:.2f}  (2:1 reward-to-risk from entry_high)
  Target 2:    ₹{target_2:.2f}  (3:1 reward-to-risk — partial profit)
  Hold Est.:   {hold_days} trading days (ADX-based)

{entry_guidance}

RECENT NEWS:{news_block}

═══════════════════════════════════════════════════════════════
CHAIN-OF-THOUGHT INSTRUCTION:
Before outputting JSON, silently reason through:
1. Momentum quality: is ADX rising or high? Is Sharpe > 0.5?
2. Does news support, threaten, or not affect the technical trend?
3. Are the pre-computed entry/stop/target levels appropriate, or should you adjust?
4. What is the realistic hold duration given trend strength and any upcoming catalysts?
5. Overall conviction: does technical + news paint a consistent picture?

Then output ONLY a valid JSON object (no markdown, no commentary before or after):
{{
  "sentiment":          "BULLISH" | "BEARISH" | "NEUTRAL",
  "sentiment_score":    <float -1.0 to 1.0>,
  "confidence":         <float 0.0 to 1.0>,
  "news_sentiment":     "POSITIVE" | "NEGATIVE" | "NEUTRAL" | "MIXED",
  "key_positives":      [<up to 3 concise strings>],
  "key_risks":          [<up to 3 concise strings>],
  "recommendation":     "BUY" | "HOLD" | "AVOID",
  "target_horizon":     "short_term (1-4 weeks)" | "medium_term (1-3 months)",
  "entry_low":          <float ₹ — conservative entry, pullback level>,
  "entry_high":         <float ₹ — aggressive entry, near current price>,
  "stop_loss":          <float ₹ — hard stop, ATR-based>,
  "target_1":           <float ₹ — first profit target, 2:1 R:R>,
  "target_2":           <float ₹ — full target, 3:1 R:R>,
  "hold_days_est":      <integer — estimated trading days to hold>,
  "risk_reward":        <float — actual R:R ratio from your levels, e.g. 2.5>,
  "position_size_note": "<brief note on sizing: e.g. 'Risk 1% of capital; position = 1%/2ATR'>",
  "summary":            "<3-4 sentence analysis: trend quality, news impact, entry rationale, key risk>"
}}"""


def _call_groq(prompt: str, cfg: dict) -> Optional[str]:
    api_key = cfg["api_keys"]["groq"]
    model   = cfg["groq"]["model"]
    max_tok = cfg["groq"].get("max_tokens", 2048)
    temp    = cfg["groq"].get("temperature", 0.2)

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type":  "application/json",
    }
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user",   "content": prompt},
        ],
        "max_tokens":  max_tok,
        "temperature": temp,
    }
    try:
        r = requests.post(GROQ_API_URL, headers=headers, json=payload, timeout=45)
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


def _parse_response(raw: str, symbol: str, score_data: dict) -> dict:
    try:
        clean  = raw.strip().lstrip("```json").lstrip("```").rstrip("```").strip()
        result = json.loads(clean)
        result["symbol"]      = symbol
        result["analysed_at"] = datetime.now().isoformat()
        # Fill in technical fallbacks for any missing trade levels
        for field in ("entry_low", "entry_high", "stop_loss", "target_1", "target_2", "hold_days_est"):
            if field not in result and field in score_data:
                result[field] = score_data[field]
        return result
    except json.JSONDecodeError as e:
        logger.error(f"JSON parse error for {symbol}: {e}\nRaw: {raw[:300]}")
        return _fallback(symbol, score_data)


def _fallback(symbol: str, score_data: dict) -> dict:
    return {
        "symbol":           symbol,
        "sentiment":        "NEUTRAL",
        "sentiment_score":  0.0,
        "confidence":       0.0,
        "news_sentiment":   "NEUTRAL",
        "key_positives":    [],
        "key_risks":        ["Analysis failed — JSON parse error"],
        "recommendation":   "HOLD",
        "target_horizon":   "N/A",
        "entry_low":        score_data.get("entry_low"),
        "entry_high":       score_data.get("entry_high"),
        "stop_loss":        score_data.get("stop_loss"),
        "target_1":         score_data.get("target_1"),
        "target_2":         score_data.get("target_2"),
        "hold_days_est":    score_data.get("hold_days_est"),
        "risk_reward":      None,
        "position_size_note": "N/A",
        "summary":          f"AI analysis failed to parse for {symbol}. Use technical levels.",
        "analysed_at":      datetime.now().isoformat(),
        "parse_error":      True,
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
            logger.warning(f"No Groq response for {sym}, using technical fallback.")
            analyses.append(_fallback(sym, score))
        else:
            result = _parse_response(raw_out, sym, score)
            analyses.append(result)
            logger.info(
                f"  {sym}: {result.get('recommendation','?')} | "
                f"sentiment={result.get('sentiment','?')} | "
                f"conf={result.get('confidence', 0):.2f} | "
                f"entry=₹{result.get('entry_low','?')}–₹{result.get('entry_high','?')} | "
                f"sl=₹{result.get('stop_loss','?')} | "
                f"t1=₹{result.get('target_1','?')}"
            )

        time.sleep(2)

    order = {"BUY": 0, "HOLD": 1, "AVOID": 2}
    analyses.sort(key=lambda x: (
        order.get(x.get("recommendation", "HOLD"), 1),
        -x.get("confidence", 0)
    ))

    logger.info(
        f"AI analysis complete. "
        f"BUY={sum(1 for a in analyses if a.get('recommendation')=='BUY')} | "
        f"HOLD={sum(1 for a in analyses if a.get('recommendation')=='HOLD')} | "
        f"AVOID={sum(1 for a in analyses if a.get('recommendation')=='AVOID')}"
    )
    return analyses
