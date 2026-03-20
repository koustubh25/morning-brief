"""
podcast.py — Generate a two-host audio podcast from curated articles.

1. Takes curated items (excluding Medium/Gmail-sourced articles)
2. Sends to Gemini to generate a conversational script
3. Renders script to audio via Google Cloud TTS Journey voices
4. Concatenates into a single MP3
"""

import io
import logging
import os
import re
from pathlib import Path

from google import genai
from google.cloud import texttospeech
from pydub import AudioSegment

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

log = logging.getLogger(__name__)

OUTPUT_DIR = Path("output")
OUTPUT_FILE = OUTPUT_DIR / "podcast.mp3"

GEMINI_MODEL = "gemini-2.5-flash"

# Two distinct Journey voices — one per host
VOICE_A = "en-US-Journey-D"  # Host A (male, tech generalist)
VOICE_B = "en-US-Journey-F"  # Host B (female, cloud/AI specialist)

PAUSE_BETWEEN_TURNS_MS = 300

SCRIPT_PROMPT = """\
You are writing a podcast script for a daily tech news briefing called "Morning Brief".
There are two hosts:
- Host A: A curious tech generalist who asks good questions and connects dots across topics.
- Host B: A sharp cloud infrastructure and AI specialist who brings deep technical insight.

The tone is casual but informed — like two colleagues catching up over coffee about the day's most interesting tech news.

Structure:
1. Quick intro (hosts greet each other, set the scene for today's stories)
2. Walk through the articles — group them thematically where it makes sense. Each article should get meaningful airtime (not just a one-liner mention). Hosts should react, ask questions, add context, and debate implications.
3. Wrap up with a "what to watch" segment highlighting the most consequential trends from today's stories.

Target length: ~8,000-10,000 characters (this produces roughly 8-10 minutes of audio).

Format rules (CRITICAL — follow exactly):
- Every line must start with either "A:" or "B:" followed by the host's dialogue.
- No stage directions, sound effects, or parenthetical actions.
- No blank lines between turns.
- Alternate speakers naturally — not strictly every line, but keep it conversational.

Here are today's curated articles:

{articles}

Write the script now.
"""


def _filter_articles(items: list[dict]) -> list[dict]:
    """Exclude Medium and Gmail-sourced articles."""
    excluded_sources = {"Medium", "Gmail", "Medium (Gmail)"}
    return [
        item for item in items
        if item.get("source") not in excluded_sources
        and "medium.com" not in (item.get("url") or "")
    ]


def _format_articles_for_prompt(items: list[dict]) -> str:
    lines = []
    for i, item in enumerate(items, 1):
        parts = [f"{i}. {item['title']}"]
        if item.get("one_liner"):
            parts.append(f"   Summary: {item['one_liner']}")
        if item.get("source"):
            parts.append(f"   Source: {item['source']}")
        if item.get("score"):
            parts.append(f"   Relevance: {item['score']}/10")
        if item.get("reason"):
            parts.append(f"   Why: {item['reason']}")
        lines.append("\n".join(parts))
    return "\n\n".join(lines)


def _generate_script(items: list[dict]) -> str:
    """Use Gemini to generate a two-host podcast script."""
    client = genai.Client(api_key=os.environ.get("GEMINI_API_KEY"))
    articles_text = _format_articles_for_prompt(items)
    prompt = SCRIPT_PROMPT.format(articles=articles_text)

    response = client.models.generate_content(
        model=GEMINI_MODEL,
        contents=prompt,
    )
    script = response.text.strip()
    log.info("Generated script: %d chars", len(script))
    return script


def _parse_script(script: str) -> list[tuple[str, str]]:
    """Parse script into list of (speaker, text) tuples."""
    lines = []
    for line in script.splitlines():
        line = line.strip()
        match = re.match(r"^([AB]):\s*(.+)$", line)
        if match:
            lines.append((match.group(1), match.group(2)))
    return lines


def _synthesize_speech(text: str, voice_name: str, tts_client: texttospeech.TextToSpeechClient) -> bytes:
    """Synthesize a single line of speech, returning MP3 bytes."""
    synthesis_input = texttospeech.SynthesisInput(text=text)
    voice = texttospeech.VoiceSelectionParams(
        language_code="en-US",
        name=voice_name,
    )
    audio_config = texttospeech.AudioConfig(
        audio_encoding=texttospeech.AudioEncoding.MP3,
        speaking_rate=1.05,
    )
    response = tts_client.synthesize_speech(
        input=synthesis_input,
        voice=voice,
        audio_config=audio_config,
    )
    return response.audio_content


def _render_audio(parsed_lines: list[tuple[str, str]]) -> None:
    """Render parsed script lines to a single MP3 file."""
    tts_client = texttospeech.TextToSpeechClient()
    voice_map = {"A": VOICE_A, "B": VOICE_B}

    combined = AudioSegment.empty()
    pause = AudioSegment.silent(duration=PAUSE_BETWEEN_TURNS_MS)

    for i, (speaker, text) in enumerate(parsed_lines):
        voice_name = voice_map[speaker]
        log.info("TTS [%d/%d] %s: %.60s…", i + 1, len(parsed_lines), speaker, text)
        mp3_bytes = _synthesize_speech(text, voice_name, tts_client)
        segment = AudioSegment.from_mp3(io.BytesIO(mp3_bytes))
        if len(combined) > 0:
            combined += pause
        combined += segment

    OUTPUT_DIR.mkdir(exist_ok=True)
    combined.export(str(OUTPUT_FILE), format="mp3", bitrate="128k")
    duration_sec = len(combined) / 1000
    log.info("Wrote %s (%.1f min, %.1f MB)",
             OUTPUT_FILE, duration_sec / 60,
             OUTPUT_FILE.stat().st_size / (1024 * 1024))


def generate_podcast(items: list[dict]) -> bool:
    """Generate podcast from curated items. Returns True on success."""
    podcast_items = _filter_articles(items)
    if not podcast_items:
        log.warning("No articles for podcast (all filtered out). Skipping.")
        return False

    log.info("Generating podcast script for %d articles…", len(podcast_items))
    script = _generate_script(podcast_items)

    parsed = _parse_script(script)
    if len(parsed) < 5:
        log.error("Script parsing yielded only %d lines — something went wrong.", len(parsed))
        return False

    log.info("Rendering %d dialogue lines to audio…", len(parsed))
    _render_audio(parsed)
    return True
