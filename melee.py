"""
Melee results: posting about the matches she plays in AI-Melee.

AI-Melee (github.com/zurgace/aimelee) can have Gomi play Mario or Fox against the owner. It leaves
JSON files in an outbox folder both programs know (default_outbox(): ~/.local/share/gomihyu/
melee-outbox): one per in-match taunt ({"kind": "taunt", "text": ...}) and one per match (the result,
the stage, the line she said right after, her lessons and her record). bot.py watches that folder
(MELEE_OUTBOX overrides it) and has her tell the chat about each match in her own words, once it's
over, in the channel an owner picked with "gomi post melee here". Her taunts aren't posted while she
plays (user, 2026-09-29: she "yaps a bit too often during gameplay"); they're held and given to her
post about the match, which may call one back. Everything here is
plain file and text handling; the prompt itself is persona.build_match_messages.
"""

import json
import os
import time
from pathlib import Path

# A match's post draws on the taunts from up to this long before it ended (a Melee match is 8
# minutes at most by default), so a match that was quit halfway doesn't lend its lines to the next.
TAUNT_WINDOW_SECONDS = 15 * 60


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
            if not isinstance(event.get("time", 0), (int, float)) or isinstance(event.get("time"), bool):
                raise ValueError("its time isn't a number")
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


def _record(wins, matches) -> str:
    return f"{_int(wins)} wins, {_int(matches) - _int(wins)} losses"


def _int(value) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) else 0


def _dict(value) -> dict:
    return value if isinstance(value, dict) else {}


def _lines(value) -> list[str]:
    """A list of strings from the file, stripped; anything that isn't a list counts as none."""
    return [str(item).strip() for item in value if str(item).strip()] if isinstance(value, list) else []


def match_facts(event: dict, player: str, taunts: list[str] = ()) -> str:
    """What happened in the match, for her prompt. taunts: what she said during it, oldest first."""
    stocks = event.get("stocks") if isinstance(event.get("stocks"), list) else []
    her, theirs = [_int(n) for n in (stocks + [0, 0])[:2]]
    opponent = event.get("opponent_character", "someone")
    stage = event.get("stage", "a stage")
    won = bool(event.get("won"))
    character = event.get("character") or "Mario"
    facts = (f"You just played a match of Super Smash Bros. Melee as {character} against {player}, who played "
             f"{opponent}, on {stage}, and you {'WON' if won else 'LOST'}: you had {her} "
             f"stock{'s' if her != 1 else ''} left, {player} had {theirs}.")
    if taunts:
        said = " / ".join(f'"{taunt}"' for taunt in taunts[-3:])
        facts += f" During the match you trash-talked (call one back if it fits, don't list them): {said}."
    if line := str(event.get("line") or "").strip():
        facts += f' Right after the match you said: "{line}"'
    if review := str(event.get("review") or "").strip():
        facts += f" Your own review of the match: {review}"
    notes = _lines(event.get("notes"))[:3]
    if notes:
        facts += " What the match log says: " + " / ".join(n.rstrip(".") for n in notes) + "."
    result = _dict(event.get("drill_result"))
    if result.get("goal"):
        facts += f' This match you were practising "{result["goal"]}"'
        if result.get("before") is not None and result.get("after") is not None:
            facts += (f': {result.get("unit", "your number")} went {result["before"]} -> {result["after"]} '
                      f'({result.get("verdict", "no change")})')
        facts += "."
    if goal := str(event.get("goal") or "").strip():
        facts += f' Next match you will work on: "{goal}"'
    record = _dict(event.get("record"))
    if _int(record.get("matches_vs")):
        facts += (f" Your record against {player}'s {opponent}: "
                  f"{_record(record.get('wins_vs', 0), record['matches_vs'])}.")
    if _int(record.get("matches")):
        facts += f" Overall: {_record(record.get('wins', 0), record['matches'])}."
    lessons = _lines(event.get("lessons"))[:3]
    if lessons:
        facts += " What you've learned so far: " + " / ".join(lessons)
    return facts
