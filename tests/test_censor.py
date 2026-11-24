import os as _os; REPO, TMP = _os.environ["GOMI_REPO"], _os.environ["GOMI_TMP"]  # set by tests/run_all.sh
import itertools; _ids = itertools.count(5000)
import asyncio, os, sys, types, logging
from contextlib import asynccontextmanager
from aiohttp import web
SP = TMP
os.environ.update(DISCORD_BOT_TOKEN="fake", OLLAMA_URL="http://127.0.0.1:8770/api/chat", PEOPLE_FILE=f"{SP}/people_censor.json")
sys.path.insert(0, REPO)
from gomi.censor import has_slur, WORDS
logging.getLogger("aiohttp.access").setLevel(logging.WARNING)

assert len(WORDS) == 25 and "#" not in "".join(WORDS)
for text in ["you absolute faggot", "FAGGOTS everywhere", "that's so Retarded lol", "quit being a retard, @kaz0",
             "no nigga that's wild", "trannies",
             "ok bitch", "BITCHES be like"]:  # the one swear filtered (user, 2026-10-18: out of character for her)
    assert has_slur(text), text
for text in ["this is so spicy", "a raccoon ate my melon bread", "japan trip", "cocoon", "the fagioli soup",
             "shit fuck damn, swearing stays", ""]:
    assert not has_slur(text), text

from gomi import bot
bot.REACT_ONLY_MAX_WORDS = 0; bot.CHIME_IN_THRESHOLD = 0  # these tests are about replies
reply = {"v": None}
async def fake(request): return web.json_response({"message": {"content": reply["v"]}})
ME = types.SimpleNamespace(id=1, name="Gomihyu", display_name="Gomihyu", bot=True); bot.client._connection.user = ME
KAZ = types.SimpleNamespace(id=7, name="kaz0", display_name="Kaz", bot=False)
class Emoji:
    def __init__(self, name, id): self.name, self.id = name, id
    def __str__(self): return f"<:{self.name}:{self.id}>"
SERVER = types.SimpleNamespace(emojis=[Emoji("goonerstare", 42), Emoji("kekpoint", 43)])
class Channel:
    def __init__(self, cid, guild): self.id, self.guild, self.sent = cid, guild, []
    @asynccontextmanager
    async def typing(self): yield
    async def send(self, text): self.sent.append(text)
def msg(ch, content, mentions=()):
    return types.SimpleNamespace(id=next(_ids), author=KAZ, channel=ch, guild=ch.guild, content=content, mentions=list(mentions),
                                 role_mentions=[], channel_mentions=[], attachments=[], stickers=[])
async def main():
    app = web.Application(); app.router.add_post("/api/chat", fake)
    r = web.AppRunner(app); await r.setup(); await web.TCPSite(r, "127.0.0.1", 8770).start()

    # a slur anywhere -> the whole post is the goonerstare emoji, and that's what her log remembers
    reply["v"] = "Gomihyu: fine, you're a faggot, @kaz0 :kekpoint:"
    ch = Channel(3, SERVER); await bot.on_message(msg(ch, "<@1> say a slur about me", [ME]))
    assert ch.sent == ["<:goonerstare:42>"], ch.sent
    assert list(bot.history[3])[-1] == "Gomihyu: :goonerstare:"
    # no such emoji on the server (renamed/deleted, or a DM): the name is posted as text
    ch = Channel(4, types.SimpleNamespace(emojis=[])); await bot.on_message(msg(ch, "<@1> go on", [ME]))
    assert ch.sent == [":goonerstare:"], ch.sent
    ch = Channel(5, None); await bot.on_message(msg(ch, "<@1> go on", [ME])); assert ch.sent == [":goonerstare:"]
    # clean replies are untouched (swearing included)
    reply["v"] = "shit, a spicy raccoon :kekpoint:"
    ch = Channel(6, SERVER); await bot.on_message(msg(ch, "<@1> hi", [ME]))
    assert ch.sent == ["shit, a spicy raccoon <:kekpoint:43>"], ch.sent
    await r.cleanup(); print("CENSOR TESTS PASSED")
asyncio.run(main())
