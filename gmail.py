"""
gmail.py — Fetch Medium article links from Gmail via IMAP (App Password).

Connects to Gmail, finds yesterday's forwarded Medium Daily Digest emails,
parses the plain-text body to extract article URLs and titles, and returns
them as candidate items for the morning brief pipeline.

Email format (forwarded Medium Daily Digest, plain text):
  Each article block looks like:
    [image: Author]
    <profile_url>
    Author
    <profile_url>
    [image: Article Title Here]
    <article_url>
    Article Title Here
    Short description…
    <article_url>
    [image: Member-only content]
    X min read
"""

import email
import imaplib
import logging
import os
import re
from datetime import datetime, timezone, timedelta
from email.header import decode_header

log = logging.getLogger(__name__)

IMAP_SERVER = "imap.gmail.com"
IMAP_PORT = 993
FREEDIUM_BASE = "https://freedium-mirror.cfd"

# Article URL: medium.com/@author/slug-hexhash (has a path beyond the @author)
ARTICLE_URL_RE = re.compile(
    r'https?://medium\.com/@[\w._-]+/[\w-]+-[0-9a-f]{8,}',
    re.IGNORECASE,
)

# [image: Some Title Text Here]
IMAGE_TAG_RE = re.compile(r'^\[image:\s*(.+)\]\s*$')


def _clean_url(url: str) -> str:
    """Strip query params, fragments, and trailing punctuation."""
    return url.split("?")[0].split("#")[0].rstrip(".,;:!)")


def _to_freedium(url: str) -> str:
    return f"{FREEDIUM_BASE}/{url}"


def _decode_mime_header(raw: str) -> str:
    parts = decode_header(raw)
    decoded = []
    for part, charset in parts:
        if isinstance(part, bytes):
            decoded.append(part.decode(charset or "utf-8", errors="replace"))
        else:
            decoded.append(part)
    return " ".join(decoded)


def _parse_articles_from_text(text: str) -> list[dict]:
    """
    Parse the plain-text body of a Medium Daily Digest email.

    Returns list of {url, title, description} dicts.
    """
    lines = text.splitlines()
    articles = []  # list of {url, title, description}
    seen_urls = set()

    i = 0
    while i < len(lines):
        line = lines[i].strip()

        # Look for an article URL in angle brackets: <https://medium.com/@author/slug-hash...>
        if line.startswith("<") and line.endswith(">"):
            inner = line[1:-1]
            clean = _clean_url(inner)
            m = ARTICLE_URL_RE.match(clean)
            if m and clean not in seen_urls:
                # Found an article URL — look backwards for [image: Title]
                title = ""
                for back in range(1, 4):
                    if i - back >= 0:
                        prev = lines[i - back].strip()
                        img_match = IMAGE_TAG_RE.match(prev)
                        if img_match:
                            title = img_match.group(1).strip()
                            # Medium truncates long titles with "…" — grab the
                            # full title from the next plain-text line after the URL
                            break

                # Look forward for description: after the title line and URL,
                # the next non-URL, non-image, non-empty line is the description,
                # then another line is a secondary description
                description = ""
                for fwd in range(1, 5):
                    if i + fwd < len(lines):
                        nxt = lines[i + fwd].strip()
                        if nxt and not nxt.startswith("<") and not nxt.startswith("[image:"):
                            # This is the full title line (untruncated)
                            if not title:
                                title = nxt
                            else:
                                # Check if this looks like the full title repeated
                                # (Medium shows title, then description on next line)
                                title_norm = title.rstrip("…").lower()
                                if nxt.lower().startswith(title_norm[:30]):
                                    # This is the full version of the truncated title
                                    title = nxt
                                else:
                                    description = nxt
                                    break
                            # Keep looking for description
                            continue

                seen_urls.add(clean)
                articles.append({
                    "url": clean,
                    "title": title,
                    "description": description,
                })
        i += 1

    return articles


def _get_plain_text(msg) -> str:
    """Extract plain text body from an email message."""
    if msg.is_multipart():
        for part in msg.walk():
            if part.get_content_type() == "text/plain":
                payload = part.get_payload(decode=True)
                if payload:
                    charset = part.get_content_charset() or "utf-8"
                    return payload.decode(charset, errors="replace")
    else:
        if msg.get_content_type() == "text/plain":
            payload = msg.get_payload(decode=True)
            if payload:
                charset = msg.get_content_charset() or "utf-8"
                return payload.decode(charset, errors="replace")
    return ""


def fetch_medium_from_gmail(gmail_address: str = None, app_password: str = None) -> list[dict]:
    """
    Fetch yesterday's Medium Daily Digest articles from Gmail via IMAP.

    Returns list of candidate dicts compatible with the fetch pipeline:
    {title, url, source, summary, published_at, _weight}
    """
    gmail_address = gmail_address or os.environ.get("GMAIL_ADDRESS", "")
    app_password = app_password or os.environ.get("GMAIL_APP_PASSWORD", "")

    if not gmail_address or not app_password:
        log.warning("Gmail credentials not configured (GMAIL_ADDRESS / GMAIL_APP_PASSWORD). Skipping Medium fetch.")
        return []

    # Search window: yesterday through today (Medium digest arrives in the morning,
    # and the brief may run at any point during the day)
    yesterday = datetime.now(timezone.utc) - timedelta(days=1)
    tomorrow = datetime.now(timezone.utc) + timedelta(days=1)
    since_date = yesterday.strftime("%d-%b-%Y")
    before_date = tomorrow.strftime("%d-%b-%Y")

    log.info("Connecting to Gmail IMAP for Medium emails (since %s)…", since_date)

    try:
        mail = imaplib.IMAP4_SSL(IMAP_SERVER, IMAP_PORT)
        mail.login(gmail_address, app_password)
    except Exception as e:
        log.error("Gmail IMAP login failed: %s", e)
        return []

    try:
        mail.select("INBOX", readonly=True)

        # Search for emails forwarded from the configured sender.
        # Gmail auto-forwarding preserves the original From header (e.g. noreply@medium.com)
        # and puts the forwarder in X-Forwarded-For, which IMAP can't search.
        # So we search by both FROM (manual forwards) and FROM medium (auto-forwards).
        forward_from = os.environ.get("GMAIL_FORWARD_FROM", "kosta250@gmail.com")
        ids = set()

        for criteria in [
            f'(FROM "{forward_from}" SINCE {since_date} BEFORE {before_date})',
            f'(FROM "noreply@medium.com" SINCE {since_date} BEFORE {before_date})',
        ]:
            status, message_ids = mail.search(None, criteria)
            if status == "OK" and message_ids[0]:
                ids.update(message_ids[0].split())

        if not ids:
            log.info("No emails from %s found for %s", forward_from, since_date)
            return []

        ids = sorted(ids)
        log.info("Found %d email(s) from %s on %s", len(ids), forward_from, since_date)

        all_articles = []

        for msg_id in ids:
            status, msg_data = mail.fetch(msg_id, "(RFC822)")
            if status != "OK":
                continue

            msg = email.message_from_bytes(msg_data[0][1])
            text = _get_plain_text(msg)

            if "medium.com" not in text.lower():
                # Not a Medium email — skip
                log.debug("Skipping non-Medium email: %s", _decode_mime_header(msg.get("Subject", "")))
                continue

            articles = _parse_articles_from_text(text)
            log.info("  Email '%s': %d article(s)", _decode_mime_header(msg.get("Subject", ""))[:60], len(articles))
            all_articles.extend(articles)

        log.info("Total: %d Medium article(s) extracted", len(all_articles))

        # Convert to fetch pipeline format
        items = []
        for article in all_articles:
            items.append({
                "title": article["title"],
                "url": _to_freedium(article["url"]),
                "source": "Medium (Gmail)",
                "summary": article["description"],
                "published_at": yesterday.isoformat(),
                "_weight": "high",
            })

        return items

    except Exception as e:
        log.error("Failed to fetch Medium emails: %s", e)
        return []
    finally:
        try:
            mail.close()
            mail.logout()
        except Exception:
            pass


if __name__ == "__main__":
    """Quick test: run directly to see what articles are found."""
    from dotenv import load_dotenv
    load_dotenv()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)-7s %(name)s — %(message)s")
    items = fetch_medium_from_gmail()
    for i, item in enumerate(items, 1):
        print(f"  {i}. {item['title']}")
        print(f"     {item['url']}")
        print(f"     {item['summary']}")
        print()
    print(f"Total: {len(items)} article(s)")
