"""
Whether Gomihyu chimes in on a post that isn't aimed at her, and the prompt that decides it.

Like a friend in a group chat, she doesn't answer everything. Posts that @mention her, reply to
one of her messages or name her always get a reply, and so does sad news (bot.py). Anything else
is rated 0-10 for how much she'd want to say something, by a short Ollama call constrained to a
number, and she replies only at CHIME_IN_THRESHOLD or above.
"""

import json

from persona import BOT_NAME, BOT_NICKNAME


def interest_messages(recent: list[str]) -> list[dict]:
    return [
        {"role": "system", "content": f"You decide whether {BOT_NICKNAME} would jump into a Discord group chat. "
                                      f"{BOT_NICKNAME} is a bratty, dramatic, self-proclaimed Archdemon in a small "
                                      "server of friends. She loves games, food (melon bread above all), plans, drama "
                                      "and being challenged, and hates being left out. Like a real friend in a group "
                                      "chat, she doesn't answer every message."},
        {"role": "user", "content": f"Recent chat, one 'handle: message' per line ({BOT_NAME} is her):\n"
                                    + "\n".join(recent)
                                    + f"\n\nHow much would {BOT_NICKNAME} want to say something about the last "
                                    "message, from 0 to 10?\n"
                                    "- 0-2: people talking to each other about something she has nothing to add "
                                    "to, or the exchange is done (ok, thanks, logistics).\n"
                                    "- 3-5: she could say something, but it would just be filler.\n"
                                    "- 6-8: her kind of topic (games, food, plans, drama), someone bragging, "
                                    "someone wrong about something she has opinions on, plans being made without "
                                    "her, or she has a genuinely funny line to add.\n"
                                    "- 9-10: a question to the whole chat, or someone answering what she just said.\n\n"
                                    'Answer as JSON: {"interest": <0-10>}'},
    ]


# JSON schema for Ollama's `format`, so the answer is just the number.
INTEREST_FORMAT = {"type": "object", "properties": {"interest": {"type": "integer", "minimum": 0, "maximum": 10}},
                   "required": ["interest"]}


def parse_interest(content: str) -> int | None:
    """The 0-10 rating from the model's answer, or None if it isn't one."""
    try:
        interest = json.loads(content)["interest"]
    except (ValueError, KeyError, TypeError):
        return None
    if isinstance(interest, bool) or not isinstance(interest, (int, float)):
        return None
    return max(0, min(10, round(interest)))
