"""
Person memory: facts people explicitly ask Gomihyu to remember, kept in one small JSON file.

Explicit only. A message aimed at her ("@Gomihyu remember that ...", "ok gomi, don't forget
...") stores the rest of the message verbatim against its author's Discord ID. Nothing is
inferred from ordinary chat, so sarcasm and banter never end up stored as facts.

Nicknames are stored against the person they belong to, not whoever said them, so she can
use them whenever that person is around: "call me Rex", "my nickname is Rex",
"Yuzuki's nickname is Yuzu", "call @yuzuki Yuzu".
"""

import json
import os
import re
from pathlib import Path

from persona import BOT_NAME, BOT_NICKNAME

# Her name within the first few words ("gomi, ...", "ok then gomi ...", "hey @Gomihyu ..."),
# or an @mention tacked on the end
LEADING_ADDRESS = re.compile(rf"^\W*(?:\w+\W+){{0,3}}?@?(?:{BOT_NAME}|{BOT_NICKNAME})\b[\s,:!.-]*", re.IGNORECASE)
TRAILING_MENTION = re.compile(rf"[\s,]*@{BOT_NAME}\W*$", re.IGNORECASE)
TRIGGER = re.compile(r"^(?:pl(?:ease|s|z)\s+)?(?:remember|don'?t\s+forget|do\s+not\s+forget)\b(?:\s+that\b)?[\s,:-]*",
                     re.IGNORECASE)
# "remember when we...?" / "remember what I said?" are questions, not facts to store
NOT_A_FACT = re.compile(r"^(?:when|what|who|how|why|where|the\s+time)\b|\?\s*$", re.IGNORECASE)

# A nickname runs to the end of its clause: "Yuzuki's nickname is Yuzu and ..." -> "Yuzu".
_NICK = r"(?P<nick>[^,.;!?\n]+?)(?=\s+(?:and|from now on|please|pls|plz)\b|[,.;!?\n]|$)"
NICKNAME_STATEMENTS = [
    re.compile(rf"\bcall\s+(?P<who>me|@?[\w.]+)\s+{_NICK}", re.IGNORECASE),                   # call me Rex
    re.compile(rf"\b(?P<who>my)\s+nick(?:name)?\s+is\s+{_NICK}", re.IGNORECASE),               # my nickname is Rex
    re.compile(rf"(?<![\w@.])(?P<who>@?[\w.]+?)['’]s\s+nick(?:name)?\s+is\s+{_NICK}", re.IGNORECASE),  # Yuzu's...
]
# "call me later", "call me when you're free" aren't nicknames
NOT_A_NICKNAME = re.compile(r"^(?:later|back|when|if|by|out|tomorrow|tonight|now|soon|sometime|maybe|anytime|"
                            r"a|an|the)\b", re.IGNORECASE)
MAX_NICKNAME_LENGTH = 32


def aimed_at_her(text: str, mentioned: bool) -> bool:
    return mentioned or bool(LEADING_ADDRESS.match(text))


def nicknames_in(text: str) -> list[tuple[str, str]]:
    """(who, nickname) pairs a message states; who is "me" or a name/handle as written."""
    found = []
    for pattern in NICKNAME_STATEMENTS:
        for m in pattern.finditer(text):
            nick = m["nick"].strip().strip("\"'“”")
            if nick and len(nick) <= MAX_NICKNAME_LENGTH and not NOT_A_NICKNAME.match(nick):
                found.append(("me" if m["who"].lower() in ("me", "my") else m["who"].lstrip("@"), nick))
    return found


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
    """people.json: {user_id: {"display_name": ..., "facts": [...], "nickname"?: ...}}.
    IDs are strings, as JSON keys must be."""

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

    def nickname_for(self, user_id: int) -> str | None:
        return self.people.get(str(user_id), {}).get("nickname")

    def find(self, name: str) -> int | None:
        """The user whose display name or nickname this is, any capitalization."""
        name = name.casefold()
        for user_id, person in self.people.items():
            if name in (person.get("display_name", "").casefold(), person.get("nickname", "").casefold()):
                return int(user_id)
        return None

    def remember(self, user_id: int, display_name: str, fact: str) -> None:
        """Store a fact for this person (once). Past max_facts, their oldest facts drop off."""
        person = self._person(user_id, display_name)
        if fact.casefold() not in (known.casefold() for known in person["facts"]):
            person["facts"] = (person["facts"] + [fact])[-self.max_facts:]
        self._save()

    def set_nickname(self, user_id: int, display_name: str | None, nickname: str) -> None:
        self._person(user_id, display_name)["nickname"] = nickname
        self._save()

    def _person(self, user_id: int, display_name: str | None) -> dict:
        person = self.people.setdefault(str(user_id), {"display_name": display_name or str(user_id), "facts": []})
        if display_name:
            person["display_name"] = display_name
        return person

    def _save(self) -> None:
        # Write a temp file then swap it in, so a crash mid-write never leaves half a file.
        tmp = self.path.with_name(self.path.name + ".tmp")
        tmp.write_text(json.dumps(self.people, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        os.replace(tmp, self.path)
