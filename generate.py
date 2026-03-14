"""
generate.py — Render selected items into output/index.html via Jinja2 template.
"""

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from seen import save_seen_urls

log = logging.getLogger(__name__)

OUTPUT_DIR = Path("output")
OUTPUT_FILE = OUTPUT_DIR / "index.html"
BRIEF_JSON = OUTPUT_DIR / "brief.json"  # artifact for Telegram notification
ARCHIVE_DIR = Path("archive")


def _ordinal_date(iso_str: str) -> str:
    """Convert ISO date string to e.g. '12th March, 2026'."""
    try:
        dt = datetime.fromisoformat(iso_str)
    except (ValueError, TypeError):
        return iso_str
    day = dt.day
    suffix = "th" if 11 <= day <= 13 else {1: "st", 2: "nd", 3: "rd"}.get(day % 10, "th")
    return f"{day}{suffix} {dt.strftime('%B, %Y')}"


def generate_html(items: list[dict]) -> None:
    OUTPUT_DIR.mkdir(exist_ok=True)

    # Sort newest-first
    items = sorted(items, key=lambda x: x.get("published_at") or "", reverse=True)

    env = Environment(
        loader=FileSystemLoader("templates"),
        autoescape=select_autoescape(["html"]),
    )
    env.filters["ordinal_date"] = _ordinal_date
    template = env.get_template("digest.html.jinja")

    now = datetime.now(timezone.utc)
    date_display = now.strftime("%a %-d %b %Y")  # e.g. "Mon 3 Mar 2026"
    generated_at = now.strftime("%H:%M UTC")

    html = template.render(
        items=items,
        date_display=date_display,
        generated_at=generated_at,
    )
    OUTPUT_FILE.write_text(html, encoding="utf-8")
    log.info("Wrote %s (%d bytes)", OUTPUT_FILE, len(html))

    # Write JSON artifact used by GitHub Actions to build Telegram message
    brief = {
        "date": date_display,
        "top_items": [
            {"title": item["title"], "url": item["url"], "one_liner": item.get("one_liner", "")}
            for item in items[:3]
        ],
    }
    BRIEF_JSON.write_text(json.dumps(brief, indent=2, ensure_ascii=False), encoding="utf-8")
    log.info("Wrote %s", BRIEF_JSON)

    # Write markdown archive
    generate_markdown(items, now)

    # Persist published URLs so they're excluded from tomorrow's run
    save_seen_urls([item["url"] for item in items])


def generate_markdown(items: list[dict], now: datetime | None = None) -> Path:
    if now is None:
        now = datetime.now(timezone.utc)

    ARCHIVE_DIR.mkdir(exist_ok=True)
    date_str = now.strftime("%Y-%m-%d")
    date_display = now.strftime("%a %-d %b %Y")
    generated_at = now.strftime("%H:%M UTC")

    lines = [
        f"# Morning Brief — {date_display}",
        "",
        f"*Generated at {generated_at}*",
        "",
    ]
    for i, item in enumerate(items, 1):
        score = item.get("score", "")
        source = item.get("source", "")
        one_liner = item.get("one_liner", "")
        reason = item.get("reason", "")

        meta_parts = []
        if score:
            meta_parts.append(f"**Score:** {score}")
        if source:
            meta_parts.append(f"**Source:** {source}")
        meta_line = " | ".join(meta_parts)

        lines.append(f"## {i}. [{item['title']}]({item['url']})")
        lines.append("")
        if meta_line:
            lines.append(meta_line)
            lines.append("")
        if one_liner:
            lines.append(f"> {one_liner}")
            lines.append("")
        if reason:
            lines.append(f"Reason: {reason}")
            lines.append("")
        lines.append("---")
        lines.append("")

    archive_file = ARCHIVE_DIR / f"{date_str}.md"
    archive_file.write_text("\n".join(lines), encoding="utf-8")
    log.info("Wrote %s", archive_file)
    return archive_file
