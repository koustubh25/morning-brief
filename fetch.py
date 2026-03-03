"""
fetch.py — Pull candidate articles from RSS feeds, Hacker News, and Google News.
Returns a deduplicated list of {title, url, source, summary, published_at} dicts.
"""

import logging
import time
from datetime import datetime, timezone
from typing import Optional

import feedparser
import requests
import yaml

log = logging.getLogger(__name__)

HN_TOP_STORIES = "https://hacker-news.firebaseio.com/v0/topstories.json"
HN_ITEM = "https://hacker-news.firebaseio.com/v0/item/{id}.json"
GOOGLE_NEWS_RSS = "https://news.google.com/rss/search?q={query}&hl=en-AU&gl=AU&ceid=AU:en"

HEADERS = {"User-Agent": "morning-brief/1.0 (daily digest; contact via github)"}


def _load_sources() -> dict:
    with open("config/sources.yaml") as f:
        return yaml.safe_load(f)


def _parse_date(entry) -> str:
    """Best-effort ISO date string from a feedparser entry."""
    if hasattr(entry, "published_parsed") and entry.published_parsed:
        return datetime(*entry.published_parsed[:6], tzinfo=timezone.utc).isoformat()
    return datetime.now(timezone.utc).isoformat()


def _summary(entry) -> str:
    """Extract a clean summary string from a feedparser entry."""
    raw = ""
    if hasattr(entry, "summary"):
        raw = entry.summary
    elif hasattr(entry, "description"):
        raw = entry.description
    # Strip HTML tags simply — avoid heavy deps
    import re
    clean = re.sub(r"<[^>]+>", " ", raw)
    clean = re.sub(r"\s+", " ", clean).strip()
    return clean[:500]


def fetch_rss(sources: list) -> list[dict]:
    items = []
    for src in sources:
        try:
            feed = feedparser.parse(src["url"])
            for entry in feed.entries[:20]:
                url = entry.get("link", "")
                if not url:
                    continue
                items.append({
                    "title": entry.get("title", "").strip(),
                    "url": url,
                    "source": src["name"],
                    "summary": _summary(entry),
                    "published_at": _parse_date(entry),
                    "_weight": src.get("weight", "medium"),
                })
            log.info("RSS %s: %d entries", src["name"], len(feed.entries))
        except Exception as e:
            log.warning("RSS fetch failed for %s: %s", src["name"], e)
    return items


def fetch_hacker_news(config: dict) -> list[dict]:
    if not config.get("enabled", True):
        return []
    try:
        resp = requests.get(HN_TOP_STORIES, headers=HEADERS, timeout=10)
        resp.raise_for_status()
        story_ids = resp.json()[: config.get("max_items", 30) * 5]  # over-fetch, filter below
    except Exception as e:
        log.warning("HN top stories fetch failed: %s", e)
        return []

    items = []
    min_score = config.get("min_score", 100)
    max_items = config.get("max_items", 30)

    for story_id in story_ids:
        if len(items) >= max_items:
            break
        try:
            r = requests.get(HN_ITEM.format(id=story_id), headers=HEADERS, timeout=8)
            r.raise_for_status()
            story = r.json()
        except Exception:
            continue

        if not story or story.get("type") != "story":
            continue
        score = story.get("score", 0)
        if score < min_score:
            continue
        url = story.get("url", "")
        if not url:
            # text post — use HN thread itself
            url = f"https://news.ycombinator.com/item?id={story_id}"
        items.append({
            "title": story.get("title", "").strip(),
            "url": url,
            "source": "Hacker News",
            "summary": story.get("text", "")[:500] if story.get("text") else f"HN score: {score}",
            "published_at": datetime.fromtimestamp(story.get("time", 0), tz=timezone.utc).isoformat(),
            "_weight": "medium",
        })
        time.sleep(0.05)  # gentle rate limit

    log.info("Hacker News: %d items above score %d", len(items), min_score)
    return items


def fetch_google_news(config: dict) -> list[dict]:
    queries = config.get("queries", [])
    items = []
    for query in queries:
        url = GOOGLE_NEWS_RSS.format(query=requests.utils.quote(query))
        try:
            feed = feedparser.parse(url)
            for entry in feed.entries[:10]:
                link = entry.get("link", "")
                if not link:
                    continue
                items.append({
                    "title": entry.get("title", "").strip(),
                    "url": link,
                    "source": f"Google News: {query}",
                    "summary": _summary(entry),
                    "published_at": _parse_date(entry),
                    "_weight": "medium",
                })
            log.info("Google News '%s': %d entries", query, len(feed.entries))
        except Exception as e:
            log.warning("Google News fetch failed for '%s': %s", query, e)
    return items


def deduplicate(items: list[dict]) -> list[dict]:
    seen_urls = set()
    seen_titles: list[str] = []
    unique = []
    for item in items:
        url = item["url"].rstrip("/").lower().split("?")[0]
        if url in seen_urls:
            continue
        # Rough title dedup (same headline from multiple sources)
        title_norm = item["title"].lower()[:60]
        if any(title_norm == t for t in seen_titles):
            continue
        seen_urls.add(url)
        seen_titles.append(title_norm)
        unique.append(item)
    return unique


def fetch_all() -> list[dict]:
    sources = _load_sources()
    candidates: list[dict] = []
    candidates += fetch_rss(sources.get("rss", []))
    candidates += fetch_hacker_news(sources.get("hacker_news", {}))
    candidates += fetch_google_news(sources.get("google_news", {}))
    candidates = deduplicate(candidates)
    log.info("Total candidates after dedup: %d", len(candidates))
    return candidates
