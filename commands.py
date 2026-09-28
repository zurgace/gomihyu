"""
Commands from the bot's owner(s), handled in code so her persona can't argue with them: deleting
her own posts. bot.py only acts on them from an owner, in a message aimed at her.

    "gomi delete that" / "@Gomihyu delete it" / "gomi del"   -> her newest post (or, in a Discord
                                                                reply to one of her posts, that one)
    "gomi delete your last 3 messages"                        -> her 3 newest posts
    "gomi delete all your messages" / "gomi delete those"     -> all of hers among the channel's
                                                                recent messages
"""

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
# "don't delete that", and "i'll delete that" (they're doing it, not asking her)
NOT_A_REQUEST = re.compile(rf"\b(?:(?:don[’']?t|do\s+not|never)\s+(?:\w+\s+)?"
                           rf"|(?:i|i[’']?ll|ill|i[’']?m|im|i[’']?d|we|we[’']?ll|we[’']?re|let\s+me)\s+(?:\w+\s+){{0,2}}){VERB}\b",
                           re.IGNORECASE)


def delete_request(text: str) -> int | None:
    """How many of her newest posts the message asks her to delete (ALL for all of them), or None."""
    if NOT_A_REQUEST.search(text) or not (m := REQUEST.search(text)):
        return None
    if m["all"]:
        return ALL
    if m["n"]:
        count = int(NUMBERS.get(m["n"].lower(), m["n"]))
        return count if count > 0 else None
    if m["noun"] and m["noun"].lower() in PLURALS:  # "delete your messages": all of them
        return ALL
    return 1
