"""
curate.py — Score candidates using the `claude` CLI against topics.yaml profile.
Returns top-scored items enriched with one_liner and relevance_note fields.

Uses batched claude -p calls (10 articles per call) so the Claude Code
subscription handles all inference — no separate Anthropic API key needed.
"""

import json
import logging
import os
import subprocess
from typing import Optional

import yaml

# Load .env if present (local dev)
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

log = logging.getLogger(__name__)

TOP_N = 9           # target digest size (7–10)
BATCH_SIZE = 10     # articles per claude call
MAX_CANDIDATES_TO_SCORE = 80


def _load_topics() -> dict:
    with open("config/topics.yaml") as f:
        return yaml.safe_load(f)


def _build_system_prompt(topics: dict) -> str:
    primary = "\n".join(f"  - {t}" for t in topics["topics"]["primary"])
    secondary = "\n".join(f"  - {t}" for t in topics["topics"]["secondary"])
    exclude = "\n".join(f"  - {t}" for t in topics["exclude"])
    verticals = ", ".join(topics.get("verticals", []))
    return (
        f"You are a content curator for a senior technology leader at PwC Australia.\n\n"
        f"Reader profile: {topics['context']}\n"
        f"Industry verticals: {verticals}\n\n"
        f"Primary topics of interest:\n{primary}\n\n"
        f"Secondary topics:\n{secondary}\n\n"
        f"Exclude / low-relevance:\n{exclude}\n\n"
        f"Scoring note: {topics.get('scoring_note', '')}\n\n"
        f"Your job: rate each article for relevance to this reader and produce a concise one-liner summary."
    )


def _build_batch_prompt(batch: list[dict]) -> str:
    articles = "\n\n".join(
        f"Article {i + 1}:\nTitle: {item['title']}\nSource: {item['source']}\n"
        f"Summary: {item.get('summary', '')[:400]}"
        for i, item in enumerate(batch)
    )
    return (
        f"Rate each article for relevance to the reader profile (0–10) and write a one-liner.\n\n"
        f"{articles}\n\n"
        f"Respond with ONLY a JSON array — no markdown, no explanation:\n"
        f'[{{"article": 1, "score": <0-10>, "reason": "<why, ≤20 words>", "one_liner": "<≤25 words>"}}, ...]'
    )


def _call_claude(system_prompt: str, user_prompt: str) -> Optional[str]:
    """Invoke claude CLI and return the text response, or None on failure."""
    env = {k: v for k, v in os.environ.items() if k != "CLAUDECODE"}
    cmd = [
        "claude", "--print",
        "--output-format", "json",
        "--no-session-persistence",
        "--tools", "",
        "--model", "claude-haiku-4-5-20251001",
        "--system-prompt", system_prompt,
        user_prompt,
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=120, env=env)
        if result.returncode != 0:
            log.warning("claude CLI error: %s", result.stderr[:200])
            return None
        data = json.loads(result.stdout)
        if data.get("type") == "result" and data.get("subtype") == "success":
            return data["result"]
        log.warning("claude unexpected response: subtype=%s", data.get("subtype"))
        return None
    except FileNotFoundError:
        log.error("claude CLI not found — ensure Claude Code is installed and `claude` is in PATH.")
        return None
    except subprocess.TimeoutExpired:
        log.warning("claude CLI timed out on batch.")
        return None
    except json.JSONDecodeError as e:
        log.warning("Failed to parse claude CLI JSON response: %s", e)
        return None


def _parse_batch_response(raw: str, batch: list[dict]) -> list[Optional[dict]]:
    # Strip markdown fences if present
    if "```" in raw:
        parts = raw.split("```")
        for part in parts:
            part = part.strip()
            if part.startswith("json"):
                part = part[4:].strip()
            if part.startswith("["):
                raw = part
                break

    try:
        results = json.loads(raw)
    except json.JSONDecodeError as e:
        log.warning("JSON parse error in batch response: %s", e)
        return [None] * len(batch)

    enriched = []
    for entry in results:
        idx = entry.get("article", 0) - 1
        if idx < 0 or idx >= len(batch):
            continue
        item = batch[idx]
        enriched.append({
            **item,
            "score": float(entry.get("score", 0)),
            "reason": entry.get("reason", ""),
            "one_liner": entry.get("one_liner", item["title"]),
        })
    return enriched


def curate(candidates: list[dict], top_n: int = TOP_N) -> list[dict]:
    topics = _load_topics()
    system_prompt = _build_system_prompt(topics)

    # Prioritise high-weight sources, cap total to control cost
    weight_order = {"high": 0, "medium": 1, "low": 2}
    ordered = sorted(candidates, key=lambda x: weight_order.get(x.get("_weight", "medium"), 1))
    to_score = ordered[:MAX_CANDIDATES_TO_SCORE]

    batches = [to_score[i:i + BATCH_SIZE] for i in range(0, len(to_score), BATCH_SIZE)]
    log.info("Scoring %d candidates in %d batches via claude CLI…", len(to_score), len(batches))

    scored = []
    for i, batch in enumerate(batches):
        log.info("  Batch %d/%d (%d articles)…", i + 1, len(batches), len(batch))
        raw = _call_claude(system_prompt, _build_batch_prompt(batch))
        if raw:
            enriched = _parse_batch_response(raw, batch)
            scored.extend([e for e in enriched if e is not None])

    scored.sort(key=lambda x: x["score"], reverse=True)
    selected = [s for s in scored if s["score"] >= 5.0][:top_n]

    if not selected:
        selected = scored[:top_n]

    log.info("Selected %d items (top score: %.1f)", len(selected), selected[0]["score"] if selected else 0)
    return selected
