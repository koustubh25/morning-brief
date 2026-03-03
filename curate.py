"""
curate.py — Score candidates with Claude API against topics.yaml profile.
Returns top-scored items enriched with one_liner and relevance_note fields.
"""

import json
import logging
import time
from typing import Optional

import anthropic
import yaml

log = logging.getLogger(__name__)

MODEL = "claude-haiku-4-5-20251001"
TOP_N = 9  # target digest size (7–10)
MAX_CANDIDATES_TO_SCORE = 80  # cap to control API cost


def _load_topics() -> dict:
    with open("config/topics.yaml") as f:
        return yaml.safe_load(f)


def _build_system_prompt(topics: dict) -> str:
    primary = "\n".join(f"  - {t}" for t in topics["topics"]["primary"])
    secondary = "\n".join(f"  - {t}" for t in topics["topics"]["secondary"])
    exclude = "\n".join(f"  - {t}" for t in topics["exclude"])
    verticals = ", ".join(topics.get("verticals", []))
    return f"""You are a content curator for a senior cloud engineering leader at PwC Australia.

Reader profile: {topics['context']}
Industry verticals: {verticals}

Primary topics of interest:
{primary}

Secondary topics:
{secondary}

Exclude / low-relevance:
{exclude}

Scoring note: {topics.get('scoring_note', '')}

Your job: rate each article for relevance to this reader and produce a concise one-liner summary."""


def _build_user_prompt(item: dict) -> str:
    return f"""Rate this article for relevance to the reader profile (0–10) and write a tight one-liner.

Title: {item['title']}
Source: {item['source']}
Summary: {item.get('summary', '')[:400]}

Respond with valid JSON only — no markdown, no explanation outside the JSON:
{{"score": <0-10>, "reason": "<why relevant or not, ≤20 words>", "one_liner": "<punchy 1-sentence summary ≤25 words>"}}"""


def score_item(client: anthropic.Anthropic, system_prompt: str, item: dict) -> Optional[dict]:
    try:
        response = client.messages.create(
            model=MODEL,
            max_tokens=200,
            system=system_prompt,
            messages=[{"role": "user", "content": _build_user_prompt(item)}],
        )
        raw = response.content[0].text.strip()
        # Handle occasional markdown fences
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        result = json.loads(raw)
        return {
            **item,
            "score": float(result.get("score", 0)),
            "reason": result.get("reason", ""),
            "one_liner": result.get("one_liner", item["title"]),
        }
    except json.JSONDecodeError as e:
        log.warning("JSON parse error for '%s': %s", item["title"][:50], e)
        return None
    except anthropic.APIError as e:
        log.warning("Claude API error for '%s': %s", item["title"][:50], e)
        return None


def curate(candidates: list[dict], top_n: int = TOP_N) -> list[dict]:
    topics = _load_topics()
    system_prompt = _build_system_prompt(topics)
    client = anthropic.Anthropic()

    # Trim to cap API cost — prioritise high-weight sources
    weight_order = {"high": 0, "medium": 1, "low": 2}
    ordered = sorted(candidates, key=lambda x: weight_order.get(x.get("_weight", "medium"), 1))
    to_score = ordered[:MAX_CANDIDATES_TO_SCORE]

    log.info("Scoring %d candidates with Claude (%s)…", len(to_score), MODEL)
    scored = []
    for i, item in enumerate(to_score):
        result = score_item(client, system_prompt, item)
        if result:
            scored.append(result)
        if (i + 1) % 10 == 0:
            log.info("  …%d/%d scored", i + 1, len(to_score))
        time.sleep(0.1)  # gentle rate limit

    scored.sort(key=lambda x: x["score"], reverse=True)
    selected = [s for s in scored if s["score"] >= 5.0][:top_n]

    # Fall back if nothing passes threshold
    if not selected:
        selected = scored[:top_n]

    log.info("Selected %d items (top score: %.1f)", len(selected), selected[0]["score"] if selected else 0)
    return selected
