"""
ARCHIVED until training on a rented GPU is set up; runs from here as is.

Step 1 of 3: pull training replies out of your Discord data export.

    python3 archive/discord-pipeline/extract.py ~/Downloads/package/Messages   # -> archive/discord-pipeline/data/replies.jsonl

Only public server channels are read. DMs, group DMs and private threads are skipped without
opening their messages. Messages sent within BURST_GAP seconds of each other in one channel
become one reply, a line each, since she answers with a single message. Links, @mentions, bot
commands, spoiler bars and custom emojis she can't post are stripped. A reply is dropped if it
has a slur, an email address or a phone number, or ends up outside --min-words..--max-words.

archive/discord-pipeline/data/ is gitignored: none of this leaves your machine.
"""

import argparse
import json
import re
import sys
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent.parent))  # the repo root, for censor.py and emojis.py

from censor import has_slur  # noqa: E402
from emojis import CUSTOM  # noqa: E402

OUT = HERE / "data" / "replies.jsonl"
# Channel types whose messages anyone in the server could read. Everything else is private.
PUBLIC_CHANNELS = {"GUILD_TEXT", "GUILD_VOICE", "GUILD_NEWS", "GUILD_ANNOUNCEMENT", "PUBLIC_THREAD",
                   "NEWS_THREAD", "ANNOUNCEMENT_THREAD"}
BURST_GAP = 90  # seconds between messages that still count as one reply

URL = re.compile(r"https?://\S+|discord\.gg/\S+")
MENTION = re.compile(r"<(?:@!?|@&|#)\d+>|@everyone|@here")
CUSTOM_EMOJI = re.compile(r"<a?:(\w+):\d+>")
SPOILER = re.compile(r"\|\|(.+?)\|\|", re.DOTALL)
COMMAND = re.compile(r"^![a-z]", re.IGNORECASE)  # !play, !skip: talking to a music bot, not people
EMAIL = re.compile(r"\b[\w.+-]+@[\w-]+\.[a-z]{2,}\b", re.IGNORECASE)
PHONE = re.compile(r"(?<!\d)(?:\+?1[ .-]?)?\(?\d{3}\)?[ .-]?\d{3}[ .-]?\d{4}(?!\d)")
# The custom emojis she can write in a message (see emojis.py), by lowercase name.
POSTABLE = {name.lower(): name for name, (_, in_text) in CUSTOM.items() if in_text}


def clean(text: str) -> str:
    """One message as she could have sent it, or "" if nothing's left."""
    text = CUSTOM_EMOJI.sub(lambda m: f":{POSTABLE[m[1].lower()]}:" if m[1].lower() in POSTABLE else "", text)
    text = URL.sub("", MENTION.sub("", SPOILER.sub(r"\1", text)))
    lines = (re.sub(r"[ \t]+", " ", line).strip() for line in text.splitlines())
    return "\n".join(line for line in lines if line)


def bursts(messages: list[dict]) -> list[tuple[str, list[str]]]:
    """(time of first message, cleaned messages) for each run sent close together."""
    runs, last = [], None
    for m in sorted(messages, key=lambda m: m["Timestamp"]):
        sent = datetime.fromisoformat(m["Timestamp"])
        if last is None or (sent - last).total_seconds() > BURST_GAP:
            runs.append((m["Timestamp"], []))
        last = sent
        text = (m.get("Contents") or "").strip()
        if text and not COMMAND.match(text) and (text := clean(text)):
            runs[-1][1].append(text)
    return [(when, texts) for when, texts in runs if texts]


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("export", type=Path, help="the Messages folder of your Discord data export")
    parser.add_argument("--min-words", type=int, default=3)
    parser.add_argument("--max-words", type=int, default=120, help="her replies are capped around 150 words")
    parser.add_argument("--since", type=int, help="only messages from this year on, e.g. 2024")
    args = parser.parse_args()

    skipped, dropped, seen, kept, read = {}, {}, set(), [], 0
    for channel_file in sorted(args.export.glob("c*/channel.json")):
        channel = json.loads(channel_file.read_text(encoding="utf-8"))
        if channel.get("type") not in PUBLIC_CHANNELS:
            skipped[channel.get("type")] = skipped.get(channel.get("type"), 0) + 1
            continue
        messages = json.loads((channel_file.parent / "messages.json").read_text(encoding="utf-8"))
        messages = [m for m in messages if not args.since or int(m["Timestamp"][:4]) >= args.since]
        read += len(messages)
        for when, texts in bursts(messages):
            reply = "\n".join(texts)
            words = len(reply.split())
            reason = ("slur" if has_slur(reply) else
                      "email/phone number" if EMAIL.search(reply) or PHONE.search(reply) else
                      "too short" if words < args.min_words else
                      "too long" if words > args.max_words else
                      "duplicate" if reply.casefold() in seen else None)
            if reason:
                dropped[reason] = dropped.get(reason, 0) + 1
                continue
            seen.add(reply.casefold())
            kept.append({"reply": reply, "time": when, "channel": channel["id"]})

    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in kept), encoding="utf-8")
    print(f"Skipped channels (not public server channels, messages never read): {skipped or 'none'}")
    print(f"Read {read} server messages; dropped replies: {dropped or 'none'}")
    print(f"Wrote {len(kept)} replies to {OUT}")


if __name__ == "__main__":
    main()
