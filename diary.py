"""
Her diary: what she takes away from a day of chat (user, 2026-09-29: "store conversations into her
memory whenever I shut down gomi for the night"). Written when the bot shuts down (Ctrl+C, or an
owner's "gomi goodnight"), and at the next start for anything a crash left unread. Each channel's
chat log (chatlog.py) since her last entry goes to the model in parts, and for each part it writes:
  - a short recap of what happened, kept in diary.json;
  - notes on people ("kaz0 started learning guitar"), kept in people.json as "learned", next to
    the notes people asked her to keep. Each comes with the exact words it's based on, and code
    drops any note whose words aren't in the log, that's about someone who didn't talk, or that has
    a slur: a small model will make things up, so what's stored has to be checkable.
The prompts, the checks and the file live here; bot.py makes the calls.
"""

import json
import os
import re
import time
from pathlib import Path

from censor import has_slur
from chatlog import local_day
from persona import BOT_NAME, BOT_NICKNAME

MAX_NOTE_LENGTH = 200
MAX_RECAP_LENGTH = 500


def chunks(entries: list[dict], max_chars: int) -> list[list[dict]]:
    """The log in parts that fit one prompt, each at most max_chars of 'handle: message' lines."""
    parts, part, size = [], [], 0
    for entry in entries:
        length = len(entry["author"]) + len(entry["text"]) + 3
        if part and size + length > max_chars:
            parts.append(part)
            part, size = [], 0
        part.append(entry)
        size += length
    return parts + [part] if part else parts


def digest_messages(channel: str, day: str, lines: list[str]) -> list[dict]:
    return [
        {"role": "system", "content": f"You keep {BOT_NICKNAME}'s diary. {BOT_NICKNAME} ({BOT_NAME} in the log) is a "
                                      "bratty, dramatic, self-proclaimed Archdemon in a small Discord server of "
                                      "friends. You read a stretch of the server's chat and write down what she'd "
                                      "want to remember. Only write what the chat actually says; never guess."},
        {"role": "user", "content": f"Chat in {channel} on {day}, one 'handle: message' per line:\n" + "\n".join(lines)
                                    + "\n\n"
                                    f"1. recap: what happened, in 1 to 3 short sentences, past tense, written as "
                                    f"{BOT_NICKNAME}'s diary (she's \"I\"): who talked about what, what got decided, "
                                    "anything funny.\n"
                                    f"2. notes: lasting things worth remembering about the people in it (not "
                                    f"{BOT_NICKNAME}): what they like or hate, what's going on in their life (a job, a "
                                    "trip, a game they're into), plans, running jokes about them. Not one-off chatter "
                                    "or passing moods. Each note is one short sentence about one person, with "
                                    "\"quote\": the exact words from the message it comes from, copied as written. "
                                    "No notes is fine.\n\n"
                                    'Answer as JSON: {"recap": "...", "notes": [{"who": "<handle>", "note": "...", '
                                    '"quote": "..."}]}'},
    ]


def digest_format(people: list[str]) -> dict:
    """JSON schema for Ollama's `format`: notes can only be about people who talked."""
    note = {"type": "object", "properties": {"who": {"type": "string", "enum": people}, "note": {"type": "string"},
                                             "quote": {"type": "string"}},
            "required": ["who", "note", "quote"]}
    return {"type": "object", "properties": {"recap": {"type": "string"}, "notes": {"type": "array", "items": note}},
            "required": ["recap", "notes"]}


def _plain(text: str) -> str:
    return " ".join(re.findall(r"[\w']+", text.casefold()))


def parse_digest(content: str, people: list[str], said: list[str]) -> tuple[str | None, list[tuple[str, str]]] | None:
    """(recap, [(who, note)]) from the model's answer, keeping only what checks out against the
    log (said: the messages' texts). None if the answer isn't the JSON asked for."""
    try:
        data = json.loads(content)
        recap, notes = data["recap"], data["notes"]
    except (ValueError, KeyError, TypeError):
        return None
    recap = " ".join(recap.split())[:MAX_RECAP_LENGTH] if isinstance(recap, str) else ""
    if not recap or has_slur(recap):
        recap = None
    handles = {person.casefold(): person for person in people}
    log_words = [_plain(text) for text in said]
    kept, seen = [], set()
    for item in notes if isinstance(notes, list) else []:
        if not isinstance(item, dict):
            continue
        who = handles.get(str(item.get("who", "")).casefold())
        note = " ".join(str(item.get("note", "")).split())
        quote = _plain(str(item.get("quote", "")))
        if (not who or not note or len(note) > MAX_NOTE_LENGTH or has_slur(note) or note.casefold() in seen
                or len(quote.split()) < 2 or not any(quote in words for words in log_words)):
            continue
        seen.add(note.casefold())
        kept.append((who, note))
    return recap, kept


class Diary:
    """diary.json: {"read_up_to": {channel_id: time}, "recaps": [{"day", "channel_id", "channel", "text"}],
    "vibe": {"notes": [...], "day": ...}} (the vibe: meld.py's note on how the server talks)."""

    def __init__(self, path: Path):
        self.path = path
        try:
            self.data = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
        except json.JSONDecodeError as e:
            raise SystemExit(f"{path} isn't valid JSON ({e}). Fix it, or delete it to start over.")
        self.data.setdefault("read_up_to", {})
        self.data.setdefault("recaps", [])
        self.data.setdefault("vibe", {"notes": [], "day": None})

    def read_up_to(self, channel_id: int) -> float:
        return float(self.data["read_up_to"].get(str(channel_id), 0))

    def mark_read(self, channel_id: int, up_to: float) -> None:
        self.data["read_up_to"][str(channel_id)] = up_to
        self._save()

    def add_recap(self, channel_id: int, channel: str, day: str, text: str) -> None:
        self.data["recaps"].append({"day": day, "channel_id": channel_id, "channel": channel, "text": text})
        self._save()

    def recaps_for(self, channel_id: int, days: int, now: float | None = None) -> list[str]:
        """This channel's recaps from the last `days` days, oldest first, as "Sep 29: ..."."""
        if days <= 0:
            return []
        now = time.time() if now is None else now
        since = local_day(now - (days - 1) * 86400)
        return [f"{time.strftime('%b', time.strptime(r['day'], '%Y-%m-%d'))} {int(r['day'][8:])}: {r['text']}"
                for r in self.data["recaps"] if r.get("channel_id") == channel_id and r.get("day", "") >= since]

    def vibe(self) -> list[str]:
        return list(self.data["vibe"].get("notes", []))

    def set_vibe(self, notes: list[str], day: str) -> None:
        self.data["vibe"] = {"notes": notes, "day": day}
        self._save()

    def _save(self) -> None:
        tmp = self.path.with_name(self.path.name + ".tmp")
        tmp.write_text(json.dumps(self.data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        os.replace(tmp, self.path)
