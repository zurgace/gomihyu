"""
Her chat log on disk: every message in the server channels she's in (her own posts too), one JSON
line each, in <folder>/<YYYY-MM-DD>/<channel_id>.jsonl by local date, plus the reactions people put
on her posts ({"kind": "reaction", "to": message id}), which meld.py counts as a reply landing. DMs
and owner commands are never logged. It's kept (user, 2026-09-29) and gitignored: the raw material for her diary
(diary.py), her recent chat after a restart, and training data for melding her persona with the server
(meld.py; the members agreed to their chat being used).

Human observations are saved before asynchronous vision. A later context event enriches that same
message by id; readers keep its original arrival time and never treat the event as another post.
"""

import json
import math
import re
import time
from pathlib import Path

DAY = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_CONTEXT_TEXT = re.compile(r"\[(?:image|gif|video|file|sticker|link|reply\s+to|generated)\b|^\s*>", re.I | re.M)


def raw_author_text(entry: dict) -> str | None:
    """Author words, or None when an old record may contain generated/quoted context.

    New records explicitly attest that text is raw. Clean legacy text remains usable, but we
    cannot recover author words reliably by stripping old media descriptions or reply quotes.
    context is display-only and is never a fallback for text.
    """
    text = entry.get("text")
    if not isinstance(text, str):
        return None
    provenance = entry.get("text_provenance")
    if provenance == "author":
        return text
    if provenance is not None or _CONTEXT_TEXT.search(text):
        return None
    return text


def local_day(when: float) -> str:
    return time.strftime("%Y-%m-%d", time.localtime(when))


class ChatLog:
    def __init__(self, folder: Path):
        self.folder = folder

    def add(self, channel_id: int, channel: str, message_id: int | None, author_id: int, author: str, text: str,
            when: float | None = None, **extra) -> None:
        """One line: a message, or with kind="reaction" a reaction (text: the emoji, to: the message id).
        extra: reply_to (the message a Discord reply answers), context (text with a bounded reply quote),
        bot (another bot, context only), about (what kind of post of hers). text stays the author's own
        words, so quoted context cannot become feedback or a training target."""
        when = time.time() if when is None else when
        entry = {"id": message_id, "time": when, "channel": channel, "author_id": author_id, "author": author,
                 "text": text} | {key: value for key, value in extra.items() if value is not None}
        self._append(channel_id, entry)

    def enrich(self, channel_id: int, message_id: int, context: str, when: float | None = None) -> None:
        """Append display context by source identity without rewriting or reordering its raw observation."""
        self._append(channel_id, {"kind": "context", "id": message_id,
                                  "time": time.time() if when is None else when, "context": context})

    def _append(self, channel_id: int, entry: dict) -> None:
        path = self.folder / local_day(entry["time"]) / f"{channel_id}.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    def _days(self) -> list[Path]:
        return sorted(p for p in self.folder.glob("*") if p.is_dir() and DAY.match(p.name)) if self.folder.is_dir() else []

    def channels(self) -> set[int]:
        return {int(f.stem) for day in self._days() for f in day.glob("*.jsonl") if f.stem.isdigit()}

    def read(self, channel_id: int, after: float = 0.0, before: float = math.inf, reactions: bool = False) -> list[dict]:
        """Enriched observations with after < arrival time <= before, oldest first.

        Context completions may happen after before (or across midnight); they only update an existing
        observation's display text. Reactions are optional; context events never become messages.
        """
        first_day = local_day(after - 86400) if after > 86400 else ""  # a day early, in case the clock moved
        entries, contexts = [], {}
        for day in self._days():
            if day.name < first_day or not (path := day / f"{channel_id}.jsonl").exists():
                continue
            for line in path.read_text(encoding="utf-8").splitlines():
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue  # a line cut off by a crash
                if not isinstance(entry, dict):
                    continue
                if entry.get("kind") == "context":
                    if entry.get("id") is not None and isinstance(entry.get("context"), str):
                        contexts[entry["id"]] = entry["context"]
                elif (after < float(entry.get("time", 0)) <= before
                      and (reactions or entry.get("kind", "message") == "message")):
                    entries.append(entry)
        for entry in entries:
            if entry.get("kind", "message") == "message" and entry.get("id") in contexts:
                entry["context"] = contexts[entry["id"]]
        return sorted(entries, key=lambda entry: entry["time"])

    def forget(self, channel_id: int, message_ids: set[int], days: int = 30) -> None:
        """Take deleted posts out of the log (her newest `days` days of it)."""
        for day in reversed(self._days()[-days:]):
            path = day / f"{channel_id}.jsonl"
            if not path.exists():
                continue
            lines = path.read_text(encoding="utf-8").splitlines()
            kept = []
            for line in lines:
                try:
                    message_id = json.loads(line).get("id")
                except (json.JSONDecodeError, AttributeError):
                    message_id = None
                if message_id not in message_ids:
                    kept.append(line)
            if len(kept) == len(lines):
                continue
            tmp = path.with_name(path.name + ".tmp")
            tmp.write_text("".join(line + "\n" for line in kept), encoding="utf-8")
            tmp.replace(path)
