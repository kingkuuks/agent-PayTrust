"""
Twitter/X scraper using twikit (no official API key needed).
Searches for fintech/payment keywords and scores results.
"""

import os
import json
import logging
import asyncio
from pathlib import Path
from datetime import datetime, timezone
from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger(__name__)

COOKIES_PATH = Path(__file__).parent.parent / "cookies.json"


def _load_keywords() -> list[str]:
    kw_path = Path(__file__).parent.parent / "config" / "keywords.json"
    with open(kw_path) as f:
        return json.load(f)["keywords"]


async def _login_and_save():
    from twikit import Client

    client = Client("en-US")
    username = os.getenv("TWITTER_USERNAME")
    email = os.getenv("TWITTER_EMAIL", "")
    password = os.getenv("TWITTER_PASSWORD")

    if not username or not password:
        raise ValueError("TWITTER_USERNAME and TWITTER_PASSWORD must be set in .env")

    logger.info("Logging in to Twitter as %s...", username)
    await client.login(auth_info_1=username, auth_info_2=email, password=password)
    client.save_cookies(str(COOKIES_PATH))
    logger.info("Cookies saved to %s", COOKIES_PATH)
    return client


async def _get_client():
    from twikit import Client

    client = Client("en-US")
    if COOKIES_PATH.exists():
        client.load_cookies(str(COOKIES_PATH))
        logger.info("Loaded existing cookies")
    else:
        client = await _login_and_save()
    return client


async def _search_keyword(client, keyword: str, max_results: int = 20) -> list[dict]:
    results = []
    try:
        tweets = await client.search_tweet(keyword, product="Latest", count=max_results)
        for tweet in tweets:
            created = tweet.created_at_datetime if hasattr(tweet, "created_at_datetime") else None
            age_hours = None
            if created:
                age_hours = (datetime.now(timezone.utc) - created).total_seconds() / 3600

            results.append({
                "tweet_id": tweet.id,
                "text": tweet.text,
                "user": tweet.user.screen_name if tweet.user else "unknown",
                "favorite_count": getattr(tweet, "favorite_count", 0) or 0,
                "retweet_count": getattr(tweet, "retweet_count", 0) or 0,
                "reply_count": getattr(tweet, "reply_count", 0) or 0,
                "keyword": keyword,
                "age_hours": age_hours,
            })
    except Exception as e:
        logger.warning("Search failed for keyword '%s': %s", keyword, e)
    return results


def _score_tweet(tweet: dict) -> float:
    engagement = (
        tweet.get("favorite_count", 0) * 1.0
        + tweet.get("retweet_count", 0) * 2.0
        + tweet.get("reply_count", 0) * 1.5
    )
    recency_bonus = 0
    if tweet.get("age_hours") is not None and tweet["age_hours"] < 24:
        recency_bonus = 2.0
    elif tweet.get("age_hours") is not None and tweet["age_hours"] < 48:
        recency_bonus = 1.0

    keyword_weight = 1.0
    text_lower = tweet.get("text", "").lower()
    high_value = ["scam", "fraud", "fake", "momo", "lost money", "trust"]
    for term in high_value:
        if term in text_lower:
            keyword_weight += 0.5

    return engagement * keyword_weight + recency_bonus


async def _scrape_all() -> list[dict]:
    client = await _get_client()
    keywords = _load_keywords()
    all_tweets = []

    for kw in keywords:
        logger.info("Searching Twitter for: %s", kw)
        tweets = await _search_keyword(client, kw)
        all_tweets.extend(tweets)
        await asyncio.sleep(2)

    # Deduplicate by tweet_id
    seen = set()
    unique = []
    for t in all_tweets:
        if t["tweet_id"] not in seen:
            seen.add(t["tweet_id"])
            t["relevance_score"] = _score_tweet(t)
            unique.append(t)

    unique.sort(key=lambda x: x["relevance_score"], reverse=True)
    logger.info("Found %d unique tweets from %d keywords", len(unique), len(keywords))
    return unique


def scrape_twitter() -> list[dict]:
    """Synchronous entry point: scrape Twitter for payment-related content."""
    return asyncio.run(_scrape_all())


def login():
    """One-time login to save cookies."""
    asyncio.run(_login_and_save())
    print("Login successful. Cookies saved.")


if __name__ == "__main__":
    import sys

    logging.basicConfig(level=logging.INFO)
    if "--login" in sys.argv:
        login()
    else:
        results = scrape_twitter()
        print(f"\nFound {len(results)} tweets. Top 5:")
        for t in results[:5]:
            print(f"  [{t['relevance_score']:.1f}] @{t['user']}: {t['text'][:80]}...")
