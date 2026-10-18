"""
How Gomihyu reads the room: for a post that isn't aimed at her, one short Ollama call says what's going on,
how much she'd want to say something about it, how much it gets a reaction out of her, and which emoji
reaction fits the moment
(user, 2026-09-29: "get gomi to be even more aware of the conversation or situation"; this replaced a
separate interest rating and a separate emoji picker that only saw the last 5 lines and a one-line
persona, and reacted 🙄 to a cat photo, a rabbit drawing and a link alike).

Posts that @mention her, reply to her or name her always get a reply, and so does sad news (bot.py);
they aren't read here. For anything else: she replies at CHIME_IN_THRESHOLD or above; a post she
doesn't answer (REACT_TO_CHAT), or one that doesn't need words (a picture, "lol"), gets the reaction the
read picked only if its react score is REACT_THRESHOLD or above (user, 2026-09-30: she reacted to every
single post; "react only if the item interests her ... have the scale be slightly different to the post
scale"). The react scale is its own: a reaction is for a moment, not a conversation, so a question to
the room or plans score high for talking but low for reacting, and a great joke the other way round.
"""

import json
from typing import NamedTuple

from persona import BOT_NAME, BOT_NICKNAME

MAX_READ = 150


class Reading(NamedTuple):
    read: str  # what's going on, in a few words (for the console)
    interest: int | None  # 0-10, how much she'd want to say something; None if the model didn't say
    react: int | None  # 0-10, how much it gets a reaction out of her; None if the model didn't say
    emoji: str | None  # an option name (or "same") that would fit, None if nothing does


def room_messages(recent: list[str], options: dict[str, str], vibe: list[str] = (), speaker: str = "",
                  replying_to: str | None = None, just_used: list[str] = (), avatar: str = "") -> list[dict]:
    system = (f"You read the room for {BOT_NICKNAME} ({BOT_NAME} in the log): a bratty, dramatic, self-proclaimed "
              "Archdemon in a small Discord server of friends. She loves games, food (melon bread above all), plans, "
              "drama and being challenged, hates being left out, and is secretly soft: cute things and kindness "
              "fluster her. Like a real friend in a group chat, she doesn't answer every message: most aren't for "
              "her or about her, since friends mostly talk to each other (\"you\" in a message is whoever it's said "
              "to). She only reacts when something really gets to her: most messages get no reaction at all.")
    if avatar:
        system += f" Her Discord avatar is {avatar}: when someone posts it or talks about it, that's her."
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
            "done (ok, thanks, logistics). 3-5: she could say something, but it would just be filler. 6-7: something "
            "she finds interesting, but it's just background chatter — she notices it but doesn't need to interrupt. "
            "8-9: something that genuinely demands a response — a direct joke at her expense, a challenge she can't "
            "ignore, someone wrong about something she's specifically passionate about, or she has a genuinely funny "
            "one-liner ready. Not just 'interesting to her.' 10: a question to the whole chat, or someone answering "
            "what she just said.\n"
            "3. react: how much it gets a reaction out of her, from 0 to 10. A different question from interest: a "
            "reaction is for a moment, not a conversation.\n"
            "   0-2: everyday chatter, logistics, questions, plans, anything that's just information. 3-5: fine, even "
            "nice, but nothing she'd make a point of. 6-7: she notices: a decent joke, a small win, something mildly "
            "cute or annoying. 8-10: it really gets a rise out of her: something actually funny, a big win or a flex, "
            "something cute enough to get past her act, something cursed, a painful fail, a sad moment.\n"
            "4. emoji: the reaction that fits this moment best: good news, a flex, a joke, a fail, something cute, "
            "something cursed, a sad moment. none if nothing fits. Pick what fits this moment, not just her usual "
            f"attitude.{avoid} Options:\n{listing}\n- none: no reaction\n\n"
            'Answer as JSON: {"read": "...", "interest": <0-10>, "react": <0-10>, "emoji": "<option>"}')
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def room_format(options: dict[str, str]) -> dict:
    """JSON schema for Ollama's `format`: a short read, two numbers, and one of the options or none."""
    score = {"type": "integer", "minimum": 0, "maximum": 10}
    return {"type": "object",
            "properties": {"read": {"type": "string"}, "interest": score, "react": score,
                           "emoji": {"type": "string", "enum": [*options, "none"]}},
            "required": ["read", "interest", "react", "emoji"]}


def parse_room(content: str, options: dict[str, str]) -> Reading | None:
    """The read from the model's answer, or None if it isn't one. Missing parts count as not said."""
    try:
        data = json.loads(content)
    except ValueError:
        data = None
    if not isinstance(data, dict):
        choice = content.strip().strip('"').strip(":")  # in case the JSON format wasn't honored
        return Reading("", None, None, choice) if choice in options else None
    emoji = str(data.get("emoji") or "")
    read = " ".join(str(data.get("read") or "").split())[:MAX_READ]
    return Reading(read, _score(data.get("interest")), _score(data.get("react")), emoji if emoji in options else None)


def _score(value) -> int | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return max(0, min(10, round(value)))
