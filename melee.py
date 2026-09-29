"""
Melee results: posting about the matches she plays in AI-Melee.

AI-Melee (github.com/zurgace/aimelee) can have Gomi play Mario or Fox against the owner. It leaves
JSON files in an outbox folder both programs know (default_outbox(): ~/.local/share/gomihyu/
melee-outbox): one per in-match taunt ({"kind": "taunt", "text": ...}, posted as she wrote it) and
one per match (the result, the stage, the line she said right after, her lessons and her record).
bot.py watches that folder (MELEE_OUTBOX overrides it) and has her tell the chat about each match in
her own words, in the channel an owner picked with "gomi post melee here". Everything here is
plain file and text handling; the prompt itself is persona.build_match_messages.
"""

import json
import os
import time
from pathlib import Path

TAUNT_MAX_AGE_SECONDS = 90  # a taunt is live trash talk: late, it's dropped


def default_outbox() -> Path:
    """The folder AI-Melee leaves her lines in unless told otherwise (its gomi_brain.default_outbox)."""
    data = os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share"
    return Path(data) / "gomihyu" / "melee-outbox"


def load_channel(path: Path) -> int | None:
    """The channel an owner picked with "gomi post melee here", if any."""
    try:
        return int(json.loads(path.read_text(encoding="utf-8"))["channel_id"]) or None
    except (OSError, ValueError, KeyError, TypeError):
        return None


def save_channel(path: Path, channel_id: int | None) -> None:
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps({"channel_id": channel_id}), encoding="utf-8")
    tmp.replace(path)


def read_outbox(outbox: Path, log) -> list[tuple[Path, dict]]:
    """The taunt and match files waiting in outbox, oldest first. A file that isn't one (half-written
    by hand, wrong format) is renamed *.bad so it isn't retried forever."""
    events = []
    for path in sorted(outbox.glob("*.json")):
        try:
            event = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(event, dict):
                raise ValueError("not an AI-Melee file")
            needed = {"text"} if event.get("kind") == "taunt" else {"won", "stocks", "opponent_character"}
            if not needed <= event.keys():
                raise ValueError(f"not an AI-Melee {event.get('kind', 'match')} file")
        except (OSError, ValueError) as e:
            log.warning(f"Skipping {path.name} in the Melee outbox ({e})")
            try:
                path.rename(path.with_suffix(".bad"))
            except OSError:
                pass
            continue
        events.append((path, event))
    return events


def stale(event: dict, max_age_seconds: float, now: float | None = None) -> bool:
    """Too old to post: the bot was off while these were played."""
    return (now if now is not None else time.time()) - float(event.get("time", 0)) > max_age_seconds


def _record(wins: int, matches: int) -> str:
    return f"{wins} wins, {matches - wins} losses"


def match_facts(event: dict, player: str) -> str:
    """What happened in the match, for her prompt."""
    her, theirs = (list(event.get("stocks", [0, 0])) + [0, 0])[:2]
    opponent = event.get("opponent_character", "someone")
    stage = event.get("stage", "a stage")
    won = bool(event.get("won"))
    character = event.get("character") or "Mario"
    facts = (f"You just played a match of Super Smash Bros. Melee as {character} against {player}, who played "
             f"{opponent}, on {stage}, and you {'WON' if won else 'LOST'}: you had {her} "
             f"stock{'s' if her != 1 else ''} left, {player} had {theirs}.")
    if line := str(event.get("line") or "").strip():
        facts += f' Right after the match you said: "{line}"'
    record = event.get("record") or {}
    if record.get("matches_vs"):
        facts += (f" Your record against {player}'s {opponent}: "
                  f"{_record(record.get('wins_vs', 0), record['matches_vs'])}.")
    if record.get("matches"):
        facts += f" Overall: {_record(record.get('wins', 0), record['matches'])}."
    lessons = [str(ln).strip() for ln in event.get("lessons") or [] if str(ln).strip()][:3]
    if lessons:
        facts += " What you've learned so far: " + " / ".join(lessons)
    return facts
