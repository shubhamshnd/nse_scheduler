"""
news_fetcher.py — Fetches news for shortlisted stocks from NewsData.io.

Free plan limits: 200 credits/day, 10 articles per credit.
We batch carefully and respect the configured max_credits_per_run.
"""

import logging
import time
from typing import Optional

import requests

logger = logging.getLogger(__name__)

NEWSDATA_BASE = "https://newsdata.io/api/1/news"


def _clean_symbol(symbol: str) -> str:
    """Strip exchange suffix: RELIANCE.NS → RELIANCE"""
    return symbol.split(".")[0]


def _fetch_news_for_query(query: str, api_key: str, language: str = "en",
                          page_token: Optional[str] = None) -> dict:
    params = {
        "apikey":   api_key,
        "q":        query,
        "language": language,
        "category": "business,top",
        "country":  "in",
    }
    if page_token:
        params["page"] = page_token
    try:
        r = requests.get(NEWSDATA_BASE, params=params, timeout=15)
        r.raise_for_status()
        return r.json()
    except requests.exceptions.HTTPError as e:
        if r.status_code == 429:
            logger.warning("NewsData.io rate limit hit. Sleeping 60s.")
            time.sleep(60)
        else:
            logger.error(f"HTTP error for query '{query}': {e}")
        return {}
    except Exception as e:
        logger.error(f"News fetch error for query '{query}': {e}")
        return {}


def fetch_news_for_shortlist(shortlist_df, cfg: dict) -> dict:
    """
    Fetches news articles for each stock in the shortlist.
    Returns dict: { symbol: [article, ...] }
    Respects max_credits_per_run from config.
    """
    news_cfg    = cfg["news"]
    api_key     = cfg["api_keys"]["newsdata_io"]
    language    = news_cfg.get("language", "en")
    max_credits = news_cfg.get("max_credits_per_run", 30)
    target_per_sym = news_cfg.get("articles_per_symbol", 5)

    symbols = shortlist_df["symbol"].tolist()
    credits_used = 0
    results = {}

    logger.info(f"Fetching news for {len(symbols)} symbols (budget: {max_credits} credits)")

    for sym in symbols:
        if credits_used >= max_credits:
            logger.warning(f"Credit budget exhausted at {credits_used}. Stopping news fetch.")
            break

        clean_name = _clean_symbol(sym)
        query = f"{clean_name} stock India"

        logger.debug(f"Fetching news: {query} (credit {credits_used + 1}/{max_credits})")
        data = _fetch_news_for_query(query, api_key, language)
        credits_used += 1

        if data.get("status") != "success":
            logger.warning(f"Bad response for {sym}: {data.get('message', 'unknown error')}")
            results[sym] = []
            time.sleep(1)
            continue

        articles = data.get("results", [])[:target_per_sym]
        cleaned = []
        for art in articles:
            cleaned.append({
                "title":        art.get("title", ""),
                "description":  art.get("description", ""),
                "content":      art.get("content", "")[:500] if art.get("content") else "",
                "source":       art.get("source_id", ""),
                "published_at": art.get("pubDate", ""),
                "link":         art.get("link", ""),
            })
        results[sym] = cleaned
        logger.info(f"  {sym}: {len(cleaned)} articles fetched")
        time.sleep(1.5)

    logger.info(f"News fetch complete. Credits used: {credits_used}. "
                f"Stocks covered: {len([s for s, a in results.items() if a])}")
    return results
