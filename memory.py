"""
Person memory: facts people explicitly ask Gomihyu to remember, kept in one small JSON file.

Explicit only. A message aimed at her ("@Gomihyu remember that ...", "Gomihyu, don't forget
...") stores the rest of the message verbatim against its author's Discord ID. Nothing is
inferred from ordinary chat, so sarcasm and banter never end up stored as facts.
"""

import json
import os
import re
from pathlib import Path

from persona import BOT_NAME

# "Gomihyu, ..." / "hey @Gomihyu ..." at the start, or an @mention tacked on the end
LEADING_ADDRESS = re.compile(rf"^\s*(?:(?:hey|yo|oi|ok|okay)[\s,]+)?@?{BOT_NAME}\b[\s,:!.-]*", re.IGNORECASE)
TRAILING_MENTION = re.compile(rf"[\s,]*@{BOT_NAME}\W*$", re.IGNORECASE)
TRIGGER = re.compile(r"^(?:pl(?:ease|s|z)\s+)?(?:remember|don'?t\s+forget|do\s+not\s+forget)\b(?:\s+that\b)?[\s,:-]*",
                     re.IGNORECASE)
# "remember when we...?" / "remember what I said?" are questions, not facts to store
NOT_A_FACT = re.compile(r"^(?:when|what|who|how|why|where|the\s+time)\b|\?\s*$", re.IGNORECASE)


def fact_to_remember(text: str, mentioned: bool) -> str | None:
    """The fact in a "remember that ..." message aimed at Gomihyu, or None if it isn't one."""
    body = LEADING_ADDRESS.sub("", text, count=1)
    if not mentioned and body == text:
        return None  # neither @mentioned nor addressed by name: ordinary chat
    trigger = TRIGGER.match(TRAILING_MENTION.sub("", body).strip())
    if not trigger:
        return None
    fact = trigger.string[trigger.end():].strip()
    return fact if fact and not NOT_A_FACT.search(fact) else None


class PeopleMemory:
    """people.json: {user_id: {"display_name": ..., "facts": [...]}}. IDs are strings, as JSON keys must be."""

    def __init__(self, path: Path, max_facts: int):
        self.path = path
        self.max_facts = max_facts
        try:
            self.people = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
        except json.JSONDecodeError as e:
            # Refuse to start rather than overwrite a hand-edited file that has a typo in it.
            raise SystemExit(f"{path} isn't valid JSON ({e}). Fix it, or delete it to start over.")

    def facts_for(self, user_id: int) -> list[str]:
        return self.people.get(str(user_id), {}).get("facts", [])

    def remember(self, user_id: int, display_name: str, fact: str) -> None:
        """Store a fact for this person (once). Past max_facts, their oldest facts drop off."""
        person = self.people.setdefault(str(user_id), {"display_name": display_name, "facts": []})
        person["display_name"] = display_name
        if fact.casefold() not in (known.casefold() for known in person["facts"]):
            person["facts"] = (person["facts"] + [fact])[-self.max_facts:]
        self._save()

    def _save(self) -> None:
        # Write a temp file then swap it in, so a crash mid-write never leaves half a file.
        tmp = self.path.with_name(self.path.name + ".tmp")
        tmp.write_text(json.dumps(self.people, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        os.replace(tmp, self.path)
