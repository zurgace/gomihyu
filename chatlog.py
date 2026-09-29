"""
Her chat log on disk: every message in the server channels she's in (her own posts too), one JSON
line each, in <folder>/<YYYY-MM-DD>/<channel_id>.jsonl by local date, plus the reactions people put
on her posts ({"kind": "reaction", "to": message id}), which meld.py counts as a reply landing. DMs
and owner commands are never logged. It's kept (user, 2026-09-29) and gitignored: the raw material for her diary
(diary.py), her recent chat after a restart, and training data for melding her persona with the server
(meld.py; the members agreed to their chat being used).
"""

import json
import math
import re
import time
from pathlib import Path

DAY = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def local_day(when: float) -> str:
    return time.strftime("%Y-%m-%d", time.localtime(when))


class ChatLog:
    def __init__(self, folder: Path):
        self.folder = folder

    def add(self, channel_id: int, channel: str, message_id: int | None, author_id: int, author: str, text: str,
            when: float | None = None, **extra) -> None:
        """One line: a message, or with kind="reaction" a reaction (text: the emoji, to: the message id).
        extra: reply_to (the message a Discord reply answers), about (what kind of post of hers)."""
        when = time.time() if when is None else when
        path = self.folder / local_day(when) / f"{channel_id}.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        entry = {"id": message_id, "time": when, "channel": channel, "author_id": author_id, "author": author,
                 "text": text} | {key: value for key, value in extra.items() if value is not None}
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    def _days(self) -> list[Path]:
        return sorted(p for p in self.folder.glob("*") if p.is_dir() and DAY.match(p.name)) if self.folder.is_dir() else []

    def channels(self) -> set[int]:
        return {int(f.stem) for day in self._days() for f in day.glob("*.jsonl") if f.stem.isdigit()}

    def read(self, channel_id: int, after: float = 0.0, before: float = math.inf, reactions: bool = False) -> list[dict]:
        """The channel's messages with after < time <= before, oldest first (and reactions too, if asked)."""
        first_day = local_day(after - 86400) if after > 86400 else ""  # a day early, in case the clock moved
        entries = []
        for day in self._days():
            if day.name < first_day or not (path := day / f"{channel_id}.jsonl").exists():
                continue
            for line in path.read_text(encoding="utf-8").splitlines():
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue  # a line cut off by a crash
                if (isinstance(entry, dict) and after < float(entry.get("time", 0)) <= before
                        and (reactions or entry.get("kind", "message") == "message")):
                    entries.append(entry)
        return sorted(entries, key=lambda entry: entry["time"])

    def forget(self, channel_id: int, message_ids: set[int], days: int = 30) -> None:
        """Take deleted posts out of the log (her newest `days` days of it)."""
        left = set(message_ids)
        for day in reversed(self._days()[-days:]):
            path = day / f"{channel_id}.jsonl"
            if not left or not path.exists():
                continue
            lines = path.read_text(encoding="utf-8").splitlines()
            kept = []
            for line in lines:
                try:
                    message_id = json.loads(line).get("id")
                except (json.JSONDecodeError, AttributeError):
                    message_id = None
                if message_id in left:
                    left.discard(message_id)
                else:
                    kept.append(line)
            if len(kept) == len(lines):
                continue
            tmp = path.with_name(path.name + ".tmp")
            tmp.write_text("".join(line + "\n" for line in kept), encoding="utf-8")
            tmp.replace(path)
