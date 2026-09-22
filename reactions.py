"""
Which emoji Gomihyu reacts with: a keyword heuristic, no model call.

Only a small curated set of plain unicode emoji, all in character (dramatic, prideful,
bratty). Serious or sad messages get no reaction at all: none of these fit, and a 💢 on
bad news is worse than silence.
"""

import random
import re

# emoji -> words/phrases that call for it (whole words, case-insensitive)
KEYWORDS = {
    "😤": ["bet", "1v1", "beat", "fight", "challenge", "vs", "versus", "win", "won", "lose", "lost",
          "rematch", "try me", "prove it", "high score"],
    "🔥": ["fire", "lit", "hype", "insane", "goated", "lets go", "let's go", "pog", "spicy", "hot", "pepper"],
    "👑": ["queen", "king", "crown", "best", "goat", "boss", "congrats", "proud", "respect", "genius",
          "legend", "promotion"],
    "💢": ["stupid", "dumb", "lame", "idiot", "shut up", "stfu", "trash", "cringe", "loser", "annoying", "hate"],
    "🙄": ["whatever", "boring", "meh", "idc", "homework", "work", "school", "monday", "chores", "ok", "k", "sure"],
    "😈": ["evil", "prank", "scheme", "plan", "chaos", "devil", "demon", "hell", "muahaha", "trouble",
          "revenge", "plot"],
    "💅": ["tea", "drama", "gossip", "outfit", "slay", "cute", "pretty", "hair", "nails", "fit check", "ate",
          "iconic"],
}
# Picked from at random when no keyword matches: the ones that suit almost any message.
FALLBACK = ["😈", "💅", "🙄", "👑"]
# Any of these and she doesn't react.
SERIOUS = ["died", "passed away", "funeral", "hospital", "sad", "depressed", "crying", "cried", "rough",
           "breakup", "broke up", "lost my", "grieving"]


def _words(phrases: list[str]) -> re.Pattern:
    return re.compile(r"\b(?:" + "|".join(map(re.escape, phrases)) + r")\b", re.IGNORECASE)


PATTERNS = {emoji: _words(phrases) for emoji, phrases in KEYWORDS.items()}
SERIOUS_PATTERN = _words(SERIOUS)


def pick_reaction(text: str) -> str | None:
    """An in-character emoji for this message, or None if it's one she shouldn't react to."""
    if SERIOUS_PATTERN.search(text):
        return None
    matches = [emoji for emoji, pattern in PATTERNS.items() if pattern.search(text)]
    return random.choice(matches or FALLBACK)
