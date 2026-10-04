import os as _os; REPO, TMP = _os.environ["GOMI_REPO"], _os.environ["GOMI_TMP"]  # set by tests/run_all.sh
import asyncio, json, os, sys, types, logging, tempfile
from pathlib import Path
from contextlib import asynccontextmanager
from aiohttp import web
SP = Path(TMP)
PEOPLE = SP / "people_memtest.json"; PEOPLE.unlink(missing_ok=True)
os.environ.update(DISCORD_BOT_TOKEN="fake", OLLAMA_URL="http://127.0.0.1:8769/api/chat", PEOPLE_FILE=str(PEOPLE))
sys.path.insert(0, REPO)
from memory import fact_to_remember as f, PeopleMemory
logging.getLogger("aiohttp.access").setLevel(logging.WARNING)

# --- trigger parsing: only explicit requests aimed at her ---
M = True  # message @mentions the bot (readable() renders that as "@Gomihyu")
cases = [
    ("@Gomihyu remember that I hate cilantro", M, "I hate cilantro"),
    ("hey @Gomihyu remember that I hate cilantro", M, "I hate cilantro"),
    ("Gomihyu, don't forget my birthday is march 3", False, "my birthday is march 3"),
    ("gomihyu dont forget that i'm allergic to cats", False, "i'm allergic to cats"),
    ("yo gomihyu pls remember I main jett", False, "I main jett"),
    ("remember that i'm vegan @Gomihyu", M, "i'm vegan"),
    ("remember that I'm vegan", M, "I'm vegan"),                      # Discord reply-with-ping: no @ in text
    ("@Gomihyu remember: @kaz0 owes me $5", M, "@kaz0 owes me $5"),
    ("@Gomihyu remember that Gomihyu owes me a melon bread", M, "Gomihyu owes me a melon bread"),
    ("remember that party last week lol", False, None),                # not aimed at her
    ("remember that I hate cilantro", False, None),
    ("@kaz0 remember that I hate cilantro", False, None),
    ("@Gomihyu remember when you tripped lol", M, None),               # question/reminiscing, not a fact
    ("@Gomihyu remember what I told you?", M, None),
    ("@Gomihyu remember that?", M, None),
    ("@Gomihyu remember that", M, None),
    ("Gomihyu is cool, remember that", False, None),
    ("@Gomihyu I remember that you lost", M, None),
    ("@Gomihyu rememberance day is soon", M, None),
    ("Gomihyus remember that x", False, None),
    # her nickname, and a few words before her name
    ("ok then gomi remember that Yuzuki's nickname is Yuzu", False, "Yuzuki's nickname is Yuzu"),
    ("gomi remember that i like tea", False, "i like tea"),
    ("lol ok so gomi, don't forget i owe kaz 5 bucks", False, "i owe kaz 5 bucks"),
    ("we should all remember that gomi is dumb", False, None),     # her name too far in
    ("yo gomi remember when you tripped", False, None),
    ("gomitron remember that x", False, None),
]
for text, mentioned, want in cases:
    got = f(text, mentioned)
    assert got == want, (text, got, want)

# --- storage: dedupe, cap drops oldest, persists, atomic, corrupt file refuses to start ---
p = SP / "people_unit.json"; p.unlink(missing_ok=True)
m = PeopleMemory(p, max_facts=3)
assert m.facts_for(7) == [] and not p.exists()
for fact in ["a", "b", "B", "c", "d"]: m.remember(7, "Kaz", fact)
assert m.facts_for(7) == ["b", "c", "d"], m.facts_for(7)        # "B" deduped, "a" dropped past cap
m.remember(7, "Kaz Renamed", "e")
data = json.loads(p.read_text())
assert data == {"7": {"display_name": "Kaz Renamed", "facts": ["c", "d", "e"]}}, data
assert PeopleMemory(p, 3).facts_for(7) == ["c", "d", "e"]            # survives a restart
assert not (SP / "people_unit.json.tmp").exists()
p.write_text('{"7": {"facts": ["x",]}}')
try: PeopleMemory(p, 3); raise AssertionError("should refuse corrupt file")
except SystemExit as e: assert "isn't valid JSON" in str(e)
assert p.read_text() == '{"7": {"facts": ["x",]}}'                  # untouched
p.unlink()

# --- in the bot ---
import bot
bot.REACT_ONLY_MAX_WORDS = 0; bot.CHIME_IN_THRESHOLD = 0  # these tests are about replies
requests = []
async def fake(request):
    requests.append(await request.json()); await asyncio.sleep(0.2)
    return web.json_response({"message": {"content": f"reply {len(requests)}"}, "done_reason": "stop"})
ME = types.SimpleNamespace(id=1, name="Gomihyu", display_name="Gomihyu", bot=True); bot.client._connection.user = ME
KAZ = types.SimpleNamespace(id=7, name="kaz0", display_name="Kaz", bot=False)
NORI = types.SimpleNamespace(id=8, name="norimaki", display_name="Nori", bot=False)
class Channel:
    def __init__(self, cid): self.id, self.sent = cid, []
    @asynccontextmanager
    async def typing(self): yield
    async def send(self, text): self.sent.append(text)
class Msg:
    def __init__(self, channel, author, content, mentions=()):
        self.author, self.channel, self.content = author, channel, content
        self.mentions, self.role_mentions, self.channel_mentions = list(mentions), [], []
        self.attachments, self.stickers, self.guild = [], [], None
        self.reactions = []
    async def add_reaction(self, emoji): self.reactions.append(emoji)
user_turn = lambda i: requests[i]["messages"][1]["content"]

async def main():
    app = web.Application(); app.router.add_post("/api/chat", fake)
    r = web.AppRunner(app); await r.setup(); await web.TCPSite(r, "127.0.0.1", 8769).start()
    c = Channel(1)

    m1 = Msg(c, KAZ, "<@1> remember that I hate cilantro", [ME]); await bot.on_message(m1)
    assert m1.reactions == ["📝"] and c.sent == ["reply 1"]
    assert json.loads(PEOPLE.read_text()) == {"7": {"display_name": "Kaz", "facts": ["I hate cilantro"]}}
    assert user_turn(0).startswith('Your notes on kaz0, things they asked you to remember, in their own words '
                                   '(bring one up only if it fits, or if they ask what you remember): "I hate cilantro"\n\nkaz0: ')
    assert "Your notes" not in requests[0]["messages"][0]["content"]     # not in the system prompt

    m2 = Msg(c, NORI, "what should we eat"); await bot.on_message(m2)   # other person: none of kaz0's facts
    assert m2.reactions == [] and "cilantro" not in user_turn(1).split("kaz0:")[0] and not user_turn(1).startswith("Your notes")

    m3 = Msg(c, KAZ, "remember that party last week lol"); await bot.on_message(m3)   # not aimed at her
    assert m3.reactions == [] and bot.memory.facts_for(7) == ["I hate cilantro"]
    assert user_turn(2).startswith("Your notes on kaz0")                        # kaz0 speaking -> their facts

    # follow-up after a burst gets the facts of whoever sent the latest message
    requests.clear(); c2 = Channel(2)
    first = asyncio.create_task(bot.on_message(Msg(c2, NORI, "one")))
    await asyncio.sleep(0.05); await bot.on_message(Msg(c2, KAZ, "two")); await first
    assert not user_turn(0).startswith("Your notes") and user_turn(1).startswith("Your notes on kaz0")

    # restart: a fresh PeopleMemory reads what was stored
    assert PeopleMemory(PEOPLE, 20).facts_for(7) == ["I hate cilantro"]
    await r.cleanup(); PEOPLE.unlink(); print("MEMORY TESTS PASSED")
asyncio.run(main())
