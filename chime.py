"""
How Gomihyu reads the room: for a post that isn't aimed at her, one short Ollama call says what's going on,
how much she'd want to say something about it, and which emoji reaction, if any, fits the moment
(user, 2026-09-29: "get gomi to be even more aware of the conversation or situation"; this replaced a
separate interest rating and a separate emoji picker that only saw the last 5 lines and a one-line
persona, and reacted 🙄 to a cat photo, a rabbit drawing and a link alike).

Posts that @mention her, reply to her or name her always get a reply, and so does sad news (bot.py);
they aren't read here. For anything else: she replies at CHIME_IN_THRESHOLD or above; a post she
doesn't answer can still get the reaction the read picked (REACT_TO_CHAT); a post that doesn't need
words (a picture, "lol") only ever gets the reaction.
"""

import json
from typing import NamedTuple

from persona import BOT_NAME, BOT_NICKNAME

MAX_READ = 150


class Reading(NamedTuple):
    read: str  # what's going on, in a few words (for the console)
    interest: int | None  # 0-10, how much she'd want to say something; None if the model didn't say
    emoji: str | None  # an option name (or "same"), None for no reaction


def room_messages(recent: list[str], options: dict[str, str], vibe: list[str] = (), speaker: str = "",
                  replying_to: str | None = None, just_used: list[str] = ()) -> list[dict]:
    system = (f"You read the room for {BOT_NICKNAME} ({BOT_NAME} in the log): a bratty, dramatic, self-proclaimed "
              "Archdemon in a small Discord server of friends. She loves games, food (melon bread above all), plans, "
              "drama and being challenged, hates being left out, and is secretly soft: cute things and kindness "
              "fluster her. Like a real friend in a group chat, she doesn't answer every message, and she only "
              "reacts when something calls for it.")
    if vibe:
        system += " How people in this server talk: " + " / ".join(vibe)
    last = f"The last message is from {speaker}" + (f", replying to {replying_to}" if replying_to else "") + "."
    listing = "\n".join(f"- {name}: {use}" for name, use in options.items())
    avoid = f" She just reacted with {', '.join(just_used)}, so not those again." if just_used else ""
    user = (f"Recent chat, one 'handle: message' per line ({BOT_NAME} is her; pictures are described in "
            "brackets):\n" + "\n".join(recent) + f"\n\n{last} About that last message:\n"
            "1. read: what's going on, in under 15 words: who it's for, and the mood.\n"
            f"2. interest: how much {BOT_NICKNAME} would want to say something about it, from 0 to 10.\n"
            "   0-2: people talking to each other about something she has nothing to add to, or the exchange is "
            "done (ok, thanks, logistics). 3-5: she could say something, but it would just be filler. 6-8: her kind "
            "of topic (games, food, plans, drama), someone bragging, someone wrong about something she has opinions "
            "on, plans being made without her, or she has a genuinely funny line to add. 9-10: a question to the "
            "whole chat, or someone answering what she just said.\n"
            "3. emoji: the reaction she'd put on it, if the moment calls for one: good news, a flex, a joke, a fail, "
            "something cute, something cursed, a sad moment. none for plain logistics and everyday chatter. Pick "
            f"what fits this moment, not just her usual attitude.{avoid} Options:\n{listing}\n- none: no reaction\n\n"
            'Answer as JSON: {"read": "...", "interest": <0-10>, "emoji": "<option>"}')
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def room_format(options: dict[str, str]) -> dict:
    """JSON schema for Ollama's `format`: a short read, a number, and one of the options or none."""
    return {"type": "object",
            "properties": {"read": {"type": "string"}, "interest": {"type": "integer", "minimum": 0, "maximum": 10},
                           "emoji": {"type": "string", "enum": [*options, "none"]}},
            "required": ["read", "interest", "emoji"]}


def parse_room(content: str, options: dict[str, str]) -> Reading | None:
    """The read from the model's answer, or None if it isn't one. Missing parts count as not said."""
    try:
        data = json.loads(content)
    except ValueError:
        data = None
    if not isinstance(data, dict):
        choice = content.strip().strip('"').strip(":")  # in case the JSON format wasn't honored
        return Reading("", None, choice) if choice in options else None
    interest = data.get("interest")
    if isinstance(interest, bool) or not isinstance(interest, (int, float)):
        interest = None
    else:
        interest = max(0, min(10, round(interest)))
    emoji = str(data.get("emoji") or "")
    read = " ".join(str(data.get("read") or "").split())[:MAX_READ]
    return Reading(read, interest, emoji if emoji in options else None)
