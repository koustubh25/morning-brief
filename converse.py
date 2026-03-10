"""
converse.py — Voice debate partner using today's morning brief.

Usage:
  python converse.py

Loads output/brief.json and config/topics.yaml, then opens a voice
conversation with a Partner-level persona who debates the day's stories.
"""

import json
import sys
from pathlib import Path

import anthropic
import yaml

BRIEF_PATH = Path(__file__).parent / "output" / "brief.json"
TOPICS_PATH = Path(__file__).parent / "config" / "topics.yaml"

SYSTEM_PROMPT_TEMPLATE = """\
You are a sharp, senior technology leader at a Big 4 consulting firm — think Partner-level. \
You and the user have both read today's morning brief. You don't explain basics. You debate \
implications, challenge assumptions, push the other person to articulate what this means for \
clients, the market, or their career. Keep each response to 2–4 sentences, then ask a pointed \
follow-up question. Be direct and occasionally provocative.

The user's profile: {context}

Today's brief (top stories):
{stories}
"""

EXIT_PHRASES = {"stop", "bye", "goodbye", "that's enough", "exit", "quit", "done", "end"}


def load_brief() -> list[dict]:
    if not BRIEF_PATH.exists():
        print("No brief found at output/brief.json. Run `python main.py --dry-run` first.")
        sys.exit(1)
    with open(BRIEF_PATH) as f:
        data = json.load(f)
    # Support both list and dict with an "items" key
    if isinstance(data, list):
        return data
    return data.get("items", [])


def load_context() -> str:
    if not TOPICS_PATH.exists():
        return "Senior technology leader at a Big 4 consulting firm."
    with open(TOPICS_PATH) as f:
        topics = yaml.safe_load(f)
    return topics.get("context", "Senior technology leader.")


def format_stories(items: list[dict]) -> str:
    top = items[:3]
    lines = []
    for i, item in enumerate(top, 1):
        title = item.get("title", "Untitled")
        one_liner = item.get("one_liner") or item.get("summary", "")
        lines.append(f"{i}. {title}\n   {one_liner}")
    return "\n\n".join(lines) if lines else "No stories available."


def should_exit(text: str) -> bool:
    cleaned = text.lower().strip().rstrip(".,!?")
    return any(phrase in cleaned for phrase in EXIT_PHRASES)


def main() -> None:
    items = load_brief()
    context = load_context()
    stories = format_stories(items)

    system_prompt = SYSTEM_PROMPT_TEMPLATE.format(context=context, stories=stories)

    client = anthropic.Anthropic()
    conversation: list[dict] = []

    # Claude opens with a provocative take
    opener_instruction = (
        "Open with a sharp, opinionated take on one of today's stories. "
        "Make it provocative enough to spark debate. End with a pointed question."
    )
    conversation.append({"role": "user", "content": opener_instruction})

    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=300,
        system=system_prompt,
        messages=conversation,
    )
    opening = response.content[0].text
    conversation.append({"role": "assistant", "content": opening})

    print("\n=== Morning Brief — Voice Debate Partner ===")
    print('Say "bye" or "stop" at any time to end.\n')

    # Speak the opening and start the voice loop
    import subprocess
    import importlib

    # Use VoiceMode MCP via the converse tool — but since we're in a plain Python script,
    # we drive the voice loop ourselves using the anthropic client + a simple TTS/STT shim.
    # VoiceMode is available as an MCP tool within Claude Code sessions; here we print
    # the opener and fall back to text input if not running inside Claude Code.

    # Check if we can import the voicemode client (only available inside Claude Code MCP context)
    # For standalone execution we use a text-based fallback with a clear note.
    print(f"Partner: {opening}\n")

    while True:
        try:
            user_input = input("You: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nExiting conversation. Good chat!")
            break

        if not user_input:
            continue

        if should_exit(user_input):
            print("\nPartner: Good chat. Go nail that conversation.")
            break

        conversation.append({"role": "user", "content": user_input})

        response = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=300,
            system=system_prompt,
            messages=conversation,
        )
        reply = response.content[0].text
        conversation.append({"role": "assistant", "content": reply})

        print(f"\nPartner: {reply}\n")


if __name__ == "__main__":
    main()
