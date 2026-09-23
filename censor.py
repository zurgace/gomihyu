"""Swap slurs in Gomihyu's messages for "filtered". The word list lives in slurs.txt."""

import re
from pathlib import Path

WORDS = [line.strip() for line in (Path(__file__).resolve().parent / "slurs.txt").read_text(encoding="utf-8").splitlines()
         if line.strip() and not line.startswith("#")]
SLUR = re.compile(r"\b(?:" + "|".join(map(re.escape, WORDS)) + r")s?\b", re.IGNORECASE)


def censor(text: str) -> str:
    return SLUR.sub("filtered", text)
