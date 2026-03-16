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

SOURCE_COLORS = {
    "Google Cloud Blog": "#4285F4",
    "Google Security Blog": "#EA4335",
    "Google Workspace Blog": "#FBBC04",
    "Hacker News": "#FF6600",
    "InfoQ": "#1BA89C",
    "The New Stack": "#30B566",
    "HBR": "#CC0000",
    "InnovationAus": "#8B5CF6",
}


def _hsl_to_hex(h: int, s: int, l: int) -> str:
    """Convert HSL (0-360, 0-100, 0-100) to hex."""
    s, l = s / 100, l / 100
    c = (1 - abs(2 * l - 1)) * s
    x = c * (1 - abs((h / 60) % 2 - 1))
    m = l - c / 2
    if h < 60: r, g, b = c, x, 0
    elif h < 120: r, g, b = x, c, 0
    elif h < 180: r, g, b = 0, c, x
    elif h < 240: r, g, b = 0, x, c
    elif h < 300: r, g, b = x, 0, c
    else: r, g, b = c, 0, x
    return f"#{int((r+m)*255):02x}{int((g+m)*255):02x}{int((b+m)*255):02x}"


def _get_source_color(source: str) -> str:
    if source in SOURCE_COLORS:
        return SOURCE_COLORS[source]
    h = sum(ord(c) * (i + 1) for i, c in enumerate(source)) % 360
    return _hsl_to_hex(h, 65, 55)


def _hex_to_rgba(hex_color: str, alpha: float) -> str:
    """Convert hex color to rgba() string."""
    n = int(hex_color.lstrip("#"), 16)
    return f"rgba({(n >> 16) & 255}, {(n >> 8) & 255}, {n & 255}, {alpha})"


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

    # Group items by source for template
    grouped = {}
    for item in items:
        src = item.get("source", "Unknown")
        grouped.setdefault(src, []).append(item)
    source_colors = {src: _get_source_color(src) for src in grouped}
    source_colors_header = {src: _hex_to_rgba(c, 0.35) for src, c in source_colors.items()}
    source_colors_bg = {src: _hex_to_rgba(c, 0.05) for src, c in source_colors.items()}
    source_colors_glow = {src: _hex_to_rgba(c, 0.5) for src, c in source_colors.items()}

    html = template.render(
        items=items,
        grouped=grouped,
        source_colors=source_colors,
        source_colors_header=source_colors_header,
        source_colors_bg=source_colors_bg,
        source_colors_glow=source_colors_glow,
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
