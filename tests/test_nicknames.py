import os as _os; REPO, TMP = _os.environ["GOMI_REPO"], _os.environ["GOMI_TMP"]  # set by tests/run_all.sh
import asyncio, json, os, sys, types, logging
from pathlib import Path
from contextlib import asynccontextmanager
from aiohttp import web
SP = Path(TMP)
PEOPLE = SP / "people_nick.json"
# the user's real people.json, as it is today
PEOPLE.write_text(json.dumps({
  "111111111111111111": {"display_name": "REX MODE", "facts": ["I like coffee", "Yuzuki's nickname is Yuzu and your nickname is Gomi"]},
  "222222222222222222": {"display_name": "Yuzuki", "facts": ["I hate coffee"]}}))
os.environ.update(DISCORD_BOT_TOKEN="fake", OLLAMA_URL="http://127.0.0.1:8773/api/chat", PEOPLE_FILE=str(PEOPLE))
sys.path.insert(0, REPO)
from memory import nicknames_in as n, PeopleMemory
logging.getLogger("aiohttp.access").setLevel(logging.WARNING)

assert n("ok then gomi remember that Yuzuki's nickname is Yuzu and your nickname is Gomi") == [("Yuzuki", "Yuzu")]
assert n("gomi call me Rex") == [("me", "Rex")] and n("gomi my nickname is REX from now on") == [("me", "REX")]
assert n("gomi, call @yuzuki Yuzu please") == [("yuzuki", "Yuzu")] and n('gomi call me "Big Rex"') == [("me", "Big Rex")]
assert n("gomi call me later") == [] and n("gomi call me when you're free") == [] and n("gomi, your nickname is Gomi") == []
assert n("gomi, kaz0's nick is Kaz. also hi") == [("kaz0", "Kaz")] and n("gomi call me " + "x" * 33) == []

import bot, persona
from datetime import datetime
bot.local_now = lambda: datetime(2026, 10, 4, 23, 59)
bot.REACT_ONLY_MAX_WORDS = 0; bot.CHIME_IN_THRESHOLD = 0
assert "you go by Gomi and that's what you call yourself" in persona.SYSTEM_PROMPT
assert "never a nickname" not in persona.SYSTEM_PROMPT and "call people by their nickname" in persona.SYSTEM_PROMPT

calls, reply = [], {"v": "ok"}
async def fake(request):
    calls.append(await request.json()); return web.json_response({"message": {"content": reply["v"]}})
ME = types.SimpleNamespace(id=1, name="Gomihyu", display_name="Gomihyu", bot=True); bot.client._connection.user = ME
REX = types.SimpleNamespace(id=111111111111111111, name="rexmode", display_name="REX MODE", bot=False)
YUZU = types.SimpleNamespace(id=222222222222222222, name="yuzuki", display_name="Yuzuki", bot=False)
class Channel:
    id, guild, sent = 9, None, []
    @asynccontextmanager
    async def typing(self): yield
    async def send(self, text): self.sent.append(text)
ch = Channel()
class Msg:
    def __init__(self, author, content, mentions=()):
        self.author, self.channel, self.guild, self.content = author, ch, None, content
        self.mentions, self.role_mentions, self.channel_mentions = list(mentions), [], []
        self.attachments, self.stickers, self.reactions = [], [], []
    async def add_reaction(self, emoji): self.reactions.append(emoji)
user_turn = lambda: calls[-1]["messages"][1]["content"]
saved = lambda: json.loads(PEOPLE.read_text())

async def main():
    app = web.Application(); app.router.add_post("/api/chat", fake)
    r = web.AppRunner(app); await r.setup(); await web.TCPSite(r, "127.0.0.1", 8773).start()

    # the exact message from today's log: fact stored for REX, nickname stored for YUZUKI (found by display name)
    m = Msg(REX, "ok then gomi remember that Yuzuki's nickname is Yuzu"); await bot.on_message(m)
    assert m.reactions == ["📝"]
    s = saved()
    assert s["222222222222222222"]["nickname"] == "Yuzu" and "nickname" not in s["111111111111111111"]
    assert s["111111111111111111"]["facts"][-1] == "Yuzuki's nickname is Yuzu"

    # yesterday's combined message again: the fact is already saved (deduped), the nickname is still set
    m = Msg(REX, "gomihyu remember that Yuzuki's nickname is Yuzu and your nickname is Gomi"); await bot.on_message(m)
    assert m.reactions == ["📝"] and len(saved()["111111111111111111"]["facts"]) == 3

    m = Msg(REX, "gomi call me Rex"); await bot.on_message(m)
    assert m.reactions == ["📝"] and saved()["111111111111111111"]["nickname"] == "Rex"
    assert saved()["111111111111111111"]["facts"] == ["I like coffee", "Yuzuki's nickname is Yuzu and your nickname is Gomi",
                                                    "Yuzuki's nickname is Yuzu"]   # "call me" isn't a fact

    # Yuzuki talks: everyone in the log gets their nickname; only Yuzuki's facts
    reply["v"] = "Gomi: hey @Yuzu, and @rex too"
    await bot.on_message(Msg(YUZU, "hi gomi"))
    turn = user_turn()
    assert turn.startswith("Right now it's Sunday, October 4, 2026, 11:59 PM.\n\nNicknames, call these people by them: rexmode is Rex, yuzuki is Yuzu\n\n"
                           'Your notes on yuzuki'), turn[:200]
    assert "The newest message, from yuzuki (Yuzu):\nyuzuki: hi gomi" in turn
    assert "These messages still need your reply:\nyuzuki: hi gomi\n" in turn
    assert 'When yuzuki says I, me or my, they mean themselves; "you" means you, Gomi.' in turn
    assert "I hate coffee" in turn and "I like coffee" not in turn
    # "Gomi:" stripped; @nicknames ping, except the person she's answering (Yuzuki), who just gets the name
    assert ch.sent[-1] == "hey Yuzu, and <@111111111111111111> too", ch.sent[-1]

    # not saved: unknown person, slur, her own name, not aimed at her
    before = saved()
    for text in ["gomi, bob's nickname is Bobby", "gomi call me faggot", "gomi call you Gomi", "call me Rexy",
                 "my nickname is Rexy"]:
        m = Msg(REX, text); await bot.on_message(m); assert m.reactions == [] and saved() == before, text
    # an @mention counts as aimed at her, and "call @yuzuki" finds the handle
    m = Msg(REX, "<@1> call <@222222222222222222> Yoms", [ME, YUZU]); await bot.on_message(m)
    assert m.reactions == ["📝"] and saved()["222222222222222222"]["nickname"] == "Yoms"
    # someone new, set before they're in people.json, gets an entry with their display name
    KAZ = types.SimpleNamespace(id=7, name="kaz0", display_name="Kaz Zero", bot=False)
    await bot.on_message(Msg(KAZ, "hello there everyone"))
    m = Msg(REX, "gomi, kaz0's nickname is Kazzy"); await bot.on_message(m)
    assert saved()["7"] == {"display_name": "Kaz Zero", "facts": [], "nickname": "Kazzy"}

    # survives a restart
    assert PeopleMemory(PEOPLE, 20).nickname_for(111111111111111111) == "Rex"
    await r.cleanup(); PEOPLE.unlink(); print("NICKNAME TESTS PASSED")
asyncio.run(main())
