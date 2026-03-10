"""
seen.py — Persistent cross-day URL deduplication.

Maintains output/seen.json: a rolling 7-day list of published URLs.
Used by fetch.py (filter) and generate.py (save).
"""

import json
from datetime import datetime, timezone, timedelta
from pathlib import Path

SEEN_PATH = Path("output/seen.json")
RETENTION_DAYS = 7


def _today() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def _cutoff() -> str:
    return (datetime.now(timezone.utc) - timedelta(days=RETENTION_DAYS)).date().isoformat()


def load_seen_urls() -> set[str]:
    """Return the set of URLs published in the last RETENTION_DAYS days."""
    if not SEEN_PATH.exists():
        return set()
    with open(SEEN_PATH) as f:
        entries = json.load(f)
    cut = _cutoff()
    return {e["url"] for e in entries if e["date"] >= cut}


def save_seen_urls(new_urls: list[str]) -> None:
    """Append new_urls to seen.json, pruning entries older than RETENTION_DAYS."""
    existing: list[dict] = []
    if SEEN_PATH.exists():
        with open(SEEN_PATH) as f:
            existing = json.load(f)

    cut = _cutoff()
    existing = [e for e in existing if e["date"] >= cut]

    known = {e["url"] for e in existing}
    today = _today()
    for url in new_urls:
        if url not in known:
            existing.append({"url": url, "date": today})
            known.add(url)

    SEEN_PATH.parent.mkdir(exist_ok=True)
    with open(SEEN_PATH, "w") as f:
        json.dump(existing, f, indent=2)
