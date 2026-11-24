"""Spot slurs in Gomihyu's replies (bot.py then posts SLUR_STANDIN instead). Words: slurs.txt."""

import re
from pathlib import Path

WORDS = [line.strip() for line in (Path(__file__).resolve().parent / "slurs.txt").read_text(encoding="utf-8").splitlines()
         if line.strip() and not line.startswith("#")]
SLUR = re.compile(r"\b(?:" + "|".join(map(re.escape, WORDS)) + r")s?\b", re.IGNORECASE)


def has_slur(text: str) -> bool:
    return bool(SLUR.search(text))
