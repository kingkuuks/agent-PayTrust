"""
Agent 1 — The Listener
Monitors Twitter/X for payment pain points, trending complaints, viral formats.
(Reddit support can be added later when API keys are available.)
"""

import json
import logging
from pathlib import Path
from datetime import datetime

logger = logging.getLogger(__name__)

DATA_DIR = Path(__file__).parent.parent / "data"
SEEN_POSTS_PATH = DATA_DIR / "seen_posts.json"


def _load_seen_posts() -> set:
    if SEEN_POSTS_PATH.exists():
        return set(json.loads(SEEN_POSTS_PATH.read_text()))
    return set()


def _save_seen_posts(seen: set):
    SEEN_POSTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    SEEN_POSTS_PATH.write_text(json.dumps(list(seen)))


def run_listener() -> list[dict]:
    """Scrape Twitter, score, deduplicate, return top 10 signals."""
    from tools.twitter_scraper import scrape_twitter

    logger.info("=== Listener Agent starting ===")
    seen = _load_seen_posts()

    # Scrape Twitter
    logger.info("Scraping Twitter...")
    try:
        twitter_results = scrape_twitter()
    except Exception as e:
        logger.error("Twitter scraping failed: %s", e)
        twitter_results = []

    # Filter out already-seen posts
    new_results = []
    for item in twitter_results:
        post_id = item.get("tweet_id", "")
        if post_id and post_id not in seen:
            new_results.append(item)
            seen.add(post_id)

    logger.info("New results after dedup: %d (from %d total)", len(new_results), len(twitter_results))

    # Score and sort
    new_results.sort(key=lambda x: x.get("relevance_score", 0), reverse=True)
    top_signals = new_results[:10]

    # Save trend data
    today = datetime.now().strftime("%Y-%m-%d")
    trend_dir = DATA_DIR / "trends" / today
    trend_dir.mkdir(parents=True, exist_ok=True)

    twitter_path = trend_dir / "twitter_raw.json"
    with open(twitter_path, "w") as f:
        json.dump(twitter_results, f, indent=2, default=str)
    logger.info("Raw twitter data saved: %s", twitter_path)

    # Save seen posts
    _save_seen_posts(seen)

    # Format for the strategist
    signals = []
    for item in top_signals:
        signals.append({
            "source": "twitter",
            "text": item.get("text", ""),
            "user": item.get("user", "unknown"),
            "engagement": (
                item.get("favorite_count", 0)
                + item.get("retweet_count", 0) * 2
                + item.get("reply_count", 0)
            ),
            "relevance_score": item.get("relevance_score", 0),
            "keyword": item.get("keyword", ""),
        })

    logger.info("=== Listener Agent done: %d signals ===", len(signals))
    return signals


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    signals = run_listener()
    print(f"\nTop signals ({len(signals)}):")
    for s in signals:
        print(f"  [{s['relevance_score']:.1f}] @{s['user']}: {s['text'][:80]}...")
