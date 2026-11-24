"""
Melee results: posting about the matches she plays in AI-Melee.

AI-Melee (github.com/zurgace/aimelee) can have Gomi play Mario or Fox against the owner. It leaves
JSON files in an outbox folder both programs know (default_outbox(): ~/.local/share/gomihyu/
melee-outbox): one per in-match taunt ({"kind": "taunt", "text": ...}), one per match (the result,
the stage, the line she said right after, her review, her lessons, her practice and her record), and
one when the game closes ({"kind": "session_end"}). bot.py watches that folder (MELEE_OUTBOX
overrides it) and has her tell the chat about the whole session in one post, in her own words, in
the channel an owner picked with "gomi post melee here" -- once the session is over, or when the
owner tells her "gg" (user, 2026-09-30: "only post once I close the game or tell gomi GG"). Until
then matches are held in the outbox; her taunts are held too, and her post may call one back.
Everything here is plain file and text handling; the prompt itself is
persona.build_session_messages.
"""

import json
import os
import time
from pathlib import Path

# A session's post draws on the taunts from its matches and from up to this long before its first one
# (a Melee match is 8 minutes at most by default), so a game quit halfway doesn't lend its lines to the next.
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
            kind = event.get("kind")
            needed = ({"text"} if kind == "taunt" else set() if kind == "session_end"
                      else {"won", "stocks", "opponent_character"})
            if not needed <= event.keys():
                raise ValueError(f"not an AI-Melee {kind or 'match'} file")
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


def session_ready(events: list[tuple[Path, dict]], now: float, idle_seconds: float,
                  gg: bool = False) -> tuple[list[tuple[Path, dict]], list[Path]]:
    """What to post about now, out of the match and session_end files waiting (oldest first):
    (the matches, the session_end files to remove with them). Everything up to the first
    session_end (the game closed); else everything, if the owner said "gg" or no match has come
    for idle_seconds (the game was force-quit, so no session_end came); else nothing yet."""
    matches = [(path, e) for path, e in events if e.get("kind", "match") == "match"]
    ends = [(path, e) for path, e in events if e.get("kind") == "session_end"]
    if ends:
        end_path, end = ends[0]
        until = float(end.get("time", 0))
        return [(path, e) for path, e in matches if float(e.get("time", 0)) <= until], [end_path]
    if not matches:
        return [], []
    newest = max(float(e.get("time", 0)) for _, e in matches)
    if gg or now - newest >= idle_seconds:
        return matches, []
    return [], []


def session_facts(matches: list[dict], player: str, taunts: list[str] = ()) -> str:
    """What happened in the session, for her prompt: every match in a line, then the last one in full.
    taunts: what she said during it, oldest first."""
    wins = sum(bool(m.get("won")) for m in matches)
    played = sorted({str(m.get("character") or "Mario") for m in matches})
    against = sorted({str(m.get("opponent_character", "someone")) for m in matches})
    facts = (f"You just finished a session of Super Smash Bros. Melee against {player}: {len(matches)} "
             f"match{'es' if len(matches) != 1 else ''}, you as {' and '.join(played)}, {player} as "
             f"{' and '.join(against)}. You won {wins} and lost {len(matches) - wins}.")
    shown = matches[-8:]
    if len(matches) > len(shown):
        facts += f" The last {len(shown)}:"
    for i, m in enumerate(shown, len(matches) - len(shown) + 1):
        stocks = m.get("stocks") if isinstance(m.get("stocks"), list) else []
        her, theirs = [_int(n) for n in (stocks + [0, 0])[:2]]
        facts += (f" Match {i}: {'won' if m.get('won') else 'lost'} {her}-{theirs} in stocks "
                  f"vs {m.get('opponent_character', 'someone')} on {m.get('stage', 'a stage')}.")
    if taunts:
        said = " / ".join(f'"{taunt}"' for taunt in taunts[-3:])
        facts += f" During the session you trash-talked (call one back if it fits, don't list them): {said}."
    facts += " The last match, in full: " + match_facts(matches[-1], player)
    return facts
