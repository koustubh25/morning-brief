"""
generate.py — Render selected items into output/index.html via Jinja2 template.
"""

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

log = logging.getLogger(__name__)

OUTPUT_DIR = Path("output")
OUTPUT_FILE = OUTPUT_DIR / "index.html"
BRIEF_JSON = OUTPUT_DIR / "brief.json"  # artifact for Telegram notification


def generate_html(items: list[dict]) -> None:
    OUTPUT_DIR.mkdir(exist_ok=True)

    env = Environment(
        loader=FileSystemLoader("templates"),
        autoescape=select_autoescape(["html"]),
    )
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
