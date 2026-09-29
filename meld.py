"""
Melding: her Satania persona slowly shaped by the server (user, 2026-09-29: "I'd like for gomi's
personality to get influenced by the discord server"; the members agreed to their chat being used).

Two sources, both read from the chat log (chatlog.py):
  - her replies that landed: someone reacted to it, answered it with a Discord reply, laughed right
    after, or answered her by name. Decided here in code, not by the model. They're kept
    ("earned" examples) and, each night, join the example chats in her prompt, replacing Satania ones
    bit by bit, but never below the anchor share (MELD_ANCHOR).
  - the server's voice: people's own messages, as examples of how this server talks. Summed up
    nightly in a short vibe note for her prompt (vibe_messages / parse_vibe), and used as training
    examples by finetuning/build_dataset.py --meld, whose share grows run by run (persona_share).
Everything here is plain logic and prompts; bot.py and the dataset builder call it.
"""

import json
import math
import random
import re

from censor import has_slur
from persona import BOT_NAME, BOT_NICKNAME
from reactions import LAUGHING, MEDIA, names_her

LANDED_WITHIN_SECONDS = 180  # a laugh or an answer this soon after her reply counts
CONTEXT_LINES = 6  # chat before an example's reply, at most
CONTEXT_SECONDS = 30 * 60  # and no older than this before it
# "stfu gomi" right after: that one didn't land, whatever else happened
PUT_DOWN = re.compile(r"\b(?:stfu|shut\s+up|nobody\s+asked|cringe|go\s+away|be\s+quiet|so\s+annoying)\b", re.IGNORECASE)
# Persona share of a training run's data: FIRST_SHARE for run 1, down in even steps to the anchor at run
# MELD_RUNS, which stays from then on. With weekly runs (finetuning/weekly.py), 11 runs is about 2.5 months.
FIRST_SHARE = 0.7
MELD_RUNS = 11
MAX_VIBE_LINES = 6
MAX_VIBE_LINE_LENGTH = 150


def _history(entries: list[dict], i: int) -> list[list[str]]:
    """Up to CONTEXT_LINES messages before entries[i], none older than CONTEXT_SECONDS."""
    start = entries[i]["time"] - CONTEXT_SECONDS
    return [[e["author"], e["text"]] for e in entries[max(0, i - CONTEXT_LINES):i] if e["time"] >= start]


def landed_replies(entries: list[dict]) -> list[dict]:
    """Her chat replies in a channel's log (reactions included) that landed, as example chats:
    {"id", "day", "history": [[handle, text], ...], "reply", "signal", "real": True}."""
    messages = [e for e in entries if e.get("kind", "message") == "message"]
    reacted = {e.get("to"): e["text"] for e in entries if e.get("kind") == "reaction" and e.get("author") != BOT_NAME}
    found = []
    for i, post in enumerate(messages):
        if post["author"] != BOT_NAME or post.get("about", "reply") != "reply":
            continue
        reply = post["text"].strip()
        history = _history(messages, i)
        if (len(reply.split()) < 2 or has_slur(reply) or re.fullmatch(r":\w+:", reply)
                or not any(author != BOT_NAME for author, _ in history)):
            continue
        after = []  # what people said next, up to her next post
        for e in messages[i + 1:]:
            if e["author"] == BOT_NAME or e["time"] - post["time"] > LANDED_WITHIN_SECONDS or len(after) == 3:
                break
            after.append(e)
        if any(PUT_DOWN.search(e["text"]) for e in after):
            continue
        signal = None
        if post.get("id") in reacted:
            signal = f"reaction {reacted[post['id']]}"
        elif post.get("id") and any(e.get("reply_to") == post["id"] and e["author"] != BOT_NAME
                                    for e in messages[i + 1:]):
            signal = "reply"
        elif after and LAUGHING.search(after[0]["text"]):
            signal = "laugh"
        elif any(names_her(e["text"]) for e in after):
            signal = "named"
        if signal:
            found.append({"id": post.get("id"), "time": post["time"], "history": history, "reply": reply,
                          "signal": signal, "real": True})
    return found


def voice_examples(entries: list[dict]) -> list[dict]:
    """People's own messages in a channel's log as examples of the server's voice: answers to someone
    else, at least 3 words, not about her, no slur, not just a link or media."""
    entries = [e for e in entries if e.get("kind", "message") == "message"]
    found = []
    for i, message in enumerate(entries):
        if i == 0 or message["author"] == BOT_NAME:
            continue
        previous, text = entries[i - 1], message["text"].strip()
        words = re.findall(r"\w+", MEDIA.sub(" ", text))
        if (previous["author"] == message["author"] or message["time"] - previous["time"] > 600
                or len(words) < 3 or names_her(text) or has_slur(text) or text.startswith("!")):
            continue
        found.append({"id": message.get("id"), "history": _history(entries, i), "reply": text})
    return found


def pick_examples(seed: list[dict], earned: list[dict], n: int, anchor: float, full_at: int,
                  rng=random) -> list[dict]:
    """n example chats for her prompt: Satania ones and her landed replies, the latter's share growing
    with how many she's earned (full_at earned: down to the anchor), shuffled."""
    if n <= 0:
        return []
    persona_share = max(anchor, 1 - len(earned) / full_at) if full_at > 0 else anchor
    n_earned = min(len(earned), n - math.ceil(n * persona_share))
    picked = rng.sample(seed, min(len(seed), n - n_earned)) + rng.sample(earned, max(0, n_earned))
    rng.shuffle(picked)
    return picked


def persona_share(run: int, anchor: float, runs: int = MELD_RUNS) -> float:
    """A training run's share of Satania examples: FIRST_SHARE at run 1, down to the anchor by run `runs`,
    never below it."""
    if anchor >= FIRST_SHARE or runs <= 1 or run >= runs:
        return anchor
    return round(FIRST_SHARE - (FIRST_SHARE - anchor) * (max(run, 1) - 1) / (runs - 1), 4)


def vibe_messages(current: list[str], lines: list[str]) -> list[dict]:
    notes = "\n".join(f"- {line}" for line in current) or "(none yet)"
    return [
        {"role": "system", "content": f"You keep notes on how a small Discord server of friends talks, for "
                                      f"{BOT_NICKNAME} ({BOT_NAME} in the log), a bot in it who's slowly picking up "
                                      "their ways so she fits in. Only write what the chat shows; never guess."},
        {"role": "user", "content": f"Your notes so far:\n{notes}\n\nNew chat since then, one 'handle: message' per "
                                    "line:\n" + "\n".join(lines) + "\n\n"
                                    "Update the notes on how people here talk and joke: tone, humor, slang and "
                                    "abbreviations, running jokes, what they're into, what gets a laugh. Keep what's "
                                    "still true, add what's new, drop what no longer fits. About the group, not one "
                                    f"person's news. At most {MAX_VIBE_LINES} short lines.\n\n"
                                    'Answer as JSON: {"notes": ["...", "..."]}'},
    ]


VIBE_FORMAT = {"type": "object", "properties": {"notes": {"type": "array", "items": {"type": "string"},
                                                          "maxItems": MAX_VIBE_LINES}},
               "required": ["notes"]}


def parse_vibe(content: str) -> list[str] | None:
    """The updated vibe note's lines (no slurs, not too long), or None if the answer isn't usable."""
    try:
        notes = json.loads(content)["notes"]
    except (ValueError, KeyError, TypeError):
        return None
    if not isinstance(notes, list):
        return None
    lines = [" ".join(str(line).split()).lstrip("-• ") for line in notes]
    lines = [line for line in lines if line and len(line) <= MAX_VIBE_LINE_LENGTH and not has_slur(line)]
    return lines[:MAX_VIBE_LINES] or None
