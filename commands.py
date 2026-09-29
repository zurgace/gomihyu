"""
Commands from the bot's owner(s), handled in code so her persona can't argue with them: deleting
her own posts, muting her, and where she posts about Melee. bot.py only acts on them from an owner,
in a message aimed at her.

    "gomi delete that" / "@Gomihyu delete it" / "gomi del"   -> her newest post (or, in a Discord
                                                                reply to one of her posts, that one)
    "gomi delete your last 3 messages"                        -> her 3 newest posts
    "gomi delete all your messages" / "gomi delete those"     -> all of hers among the channel's
                                                                recent messages
    "gomi mute" / "gomi mute for 2 hours"                     -> silent in this channel for a while
    "gomi mute until i say so" / "gomi mute forever"          -> silent until unmuted
    "gomi unmute"                                             -> talking again
    "gomi post melee here" / "gomi melee results here"        -> this channel gets her Melee posts
    "gomi stop posting melee"                                 -> no channel gets them
"""

import math
import re

ALL = -1  # delete_request() for "all of them"
NUMBERS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10}
VERB = r"(?:delete|del|erase|unsend)"
REQUEST = re.compile(
    rf"\b{VERB}\s+(?:"
    r"(?P<all>all(?:\s+of)?(?:\s+(?:your|ur|those|them|these|that))?|everything|those|them|these)"
    r"|(?:(?:that|this|the|your|ur)\s+)?(?:(?:last|latest|previous|recent)\s+)?"
    rf"(?:(?P<n>\d+|{'|'.join(NUMBERS)})\s+)?(?P<noun>messages?|msgs?|posts?|repl(?:y|ies)|texts?)"
    r"|(?P<one>that|this|it)"
    r")\b"
    # or the verb alone at the end: "gomi delete", "del pls"
    rf"|\b{VERB}(?:\s+(?:pls|plz|please))?[\s.!]*$",
    re.IGNORECASE)
PLURALS = {"messages", "msgs", "posts", "replies", "texts"}


def not_a_request(verb: str) -> re.Pattern:
    """"don't delete that" / "don't make me mute you", and "i'll delete that" (they're doing it, not
    asking her)."""
    return re.compile(rf"\b(?:(?:don[’']?t|do\s+not|never)\s+(?:\w+\s+){{0,2}}"
                      rf"|(?:i|i[’']?ll|ill|i[’']?m|im|i[’']?d|we|we[’']?ll|we[’']?re|let\s+me)\s+(?:\w+\s+){{0,2}}){verb}\b",
                      re.IGNORECASE)


NOT_A_DELETE = not_a_request(VERB)


def delete_request(text: str) -> int | None:
    """How many of her newest posts the message asks her to delete (ALL for all of them), or None."""
    if NOT_A_DELETE.search(text) or not (m := REQUEST.search(text)):
        return None
    if m["all"]:
        return ALL
    if m["n"]:
        count = int(NUMBERS.get(m["n"].lower(), m["n"]))
        return count if count > 0 else None
    if m["noun"] and m["noun"].lower() in PLURALS:  # "delete your messages": all of them
        return ALL
    return 1


FOREVER = math.inf  # mute_request() for "until unmuted"
MUTE = re.compile(r"\bmute\b", re.IGNORECASE)  # not "unmute": no word boundary inside it
UNMUTE = re.compile(r"\bunmute\b", re.IGNORECASE)
NOT_A_MUTE = not_a_request(r"(?:un)?mute")
UNITS = {"m": 1, "min": 1, "mins": 1, "minute": 1, "minutes": 1,
         "h": 60, "hr": 60, "hrs": 60, "hour": 60, "hours": 60, "d": 1440, "day": 1440, "days": 1440}
_ANY_UNIT = "|".join(sorted(UNITS, key=len, reverse=True))
_WORD_UNIT = "|".join(sorted((u for u in UNITS if len(u) > 1), key=len, reverse=True))
# "10m" / "2 hours" / "1.5h", "an hour" / "two days" (a spelled-out number needs a spelled-out unit,
# so "and" isn't "a" + "d"), and "half an hour"
DURATION = re.compile(rf"\b(?:(?P<num>\d+(?:\.\d+)?)\s*(?P<unit>{_ANY_UNIT})"
                      rf"|(?P<word>an?|{'|'.join(NUMBERS)})\s+(?P<word_unit>{_WORD_UNIT})"
                      r"|(?P<half>half\s+an?\s+hour))\b", re.IGNORECASE)
UNTIL_UNMUTED = re.compile(r"\b(?:until|till|til|forever|indefinitely|for\s+good)\b", re.IGNORECASE)


def mute_request(text: str, default_minutes: float) -> float | None:
    """For how many minutes the message asks her to go quiet (FOREVER: until unmuted), or None.
    With no duration given, default_minutes."""
    # only the words leading up to it count: "mute till i unmute you" is still a request
    if not (m := MUTE.search(text)) or NOT_A_MUTE.search(text[:m.end()]):
        return None
    after = text[m.end():]  # "mute for 2 hours", not a number from earlier in the message
    if d := DURATION.search(after):
        if d["half"]:
            return 30
        if d["num"]:
            minutes = float(d["num"]) * UNITS[d["unit"].lower()]
        else:
            minutes = NUMBERS.get(d["word"].lower(), 1) * UNITS[d["word_unit"].lower()]
        return minutes if minutes > 0 else None
    if UNTIL_UNMUTED.search(after):
        return FOREVER
    return default_minutes


def unmute_request(text: str) -> bool:
    """Whether the message tells her she can talk again."""
    return bool(m := UNMUTE.search(text)) and not NOT_A_MUTE.search(text[:m.end()])


MELEE = r"(?:melee|smash|ssbm)"
MELEE_HERE = re.compile(rf"\b(?:(?:post|put|send|do)\s+(?:(?:the|your|ur)\s+)?)?{MELEE}"
                        r"(?:\s+(?:results?|matches|games|stuff|posts?))?\s+(?:in\s+)?here\b", re.IGNORECASE)
MELEE_STOP = re.compile(rf"\b(?:stop|quit|no\s+more)\s+(?:posting\s+)?(?:(?:the|your|ur)\s+)?{MELEE}\b",
                        re.IGNORECASE)
NOT_A_MELEE = not_a_request(r"(?:post|put|send|do|stop|quit)")


def melee_here_request(text: str) -> bool:
    """Whether the message asks her to post about Melee matches in this channel (not a question)."""
    return (bool(m := MELEE_HERE.search(text)) and "?" not in text
            and not NOT_A_MELEE.search(text[:m.end()]))


def melee_stop_request(text: str) -> bool:
    """Whether the message asks her to stop posting about Melee matches."""
    return bool(m := MELEE_STOP.search(text)) and "?" not in text and not NOT_A_MELEE.search(text[:m.end()])
