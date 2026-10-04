import os as _os; REPO, TMP = _os.environ["GOMI_REPO"], _os.environ["GOMI_TMP"]  # set by tests/run_all.sh
# She never pings the person she's answering (they're already in the conversation); others still get pinged.
import asyncio, json, os, sys, types, logging
from pathlib import Path
from contextlib import asynccontextmanager
from aiohttp import web
SP = Path(TMP)
PEOPLE = SP / "people_pings.json"
PEOPLE.write_text(json.dumps({"111111111111111111": {"display_name": "REX MODE", "facts": [], "nickname": "Rex"}}))
os.environ.update(DISCORD_BOT_TOKEN="fake", OLLAMA_URL="http://127.0.0.1:8772/api/chat", PEOPLE_FILE=str(PEOPLE))
sys.path.insert(0, REPO)
import bot, persona
logging.getLogger("aiohttp.access").setLevel(logging.WARNING)
bot.REACT_ONLY_MAX_WORDS = 0; bot.CHIME_IN_THRESHOLD = 0; bot.examples = []

reply = {"v": "ok"}
async def fake(request):
    return web.json_response({"message": {"content": reply["v"]}, "done_reason": "stop"})
ME = types.SimpleNamespace(id=1, name="Gomihyu", display_name="Gomihyu", bot=True); bot.client._connection.user = ME
REX = types.SimpleNamespace(id=111111111111111111, name="rexmode", display_name="REX MODE", bot=False)
KAZ = types.SimpleNamespace(id=100, name="kaz0", display_name="Kaz", bot=False)
class Channel:
    id, guild, sent = 9, None, []
    @asynccontextmanager
    async def typing(self): yield
    async def send(self, text): self.sent.append(text)
ch = Channel()
msg = lambda author, c, mentions=(): types.SimpleNamespace(author=author, channel=ch, guild=None, content=c, mentions=list(mentions),
                                                           role_mentions=[], channel_mentions=[], attachments=[], stickers=[])
assert "never @ the person you're answering" in persona.SYSTEM_PROMPT and "put @ in front of a name to ping someone" not in persona.SYSTEM_PROMPT

async def main():
    app = web.Application(); app.router.add_post("/api/chat", fake)
    r = web.AppRunner(app); await r.setup(); await web.TCPSite(r, "127.0.0.1", 8772).start()
    await bot.on_message(msg(KAZ, "morning"))
    cases = [  # what she writes to rexmode -> what's posted
        ("@rexmode hey. what's up, rexmode?", "hey. what's up, rexmode?"),          # leading @ at him: dropped
        ("@REX, you absolute bozo", "you absolute bozo"),                             # by nickname, any case, with a comma
        ("Are you even paying attention, @rexmode?", "Are you even paying attention, rexmode?"),
        ("Fine, @Rex. Ask @kaz0 then.", "Fine, Rex. Ask <@100> then."),              # others still get pinged
        ("@rexmode", "rexmode"),                                                     # never an empty message
        ("Go ask @nobody. Or @everyone. Fine, rexmode.", "Fine, rexmode."),          # unknown names: those sentences go, no mass ping
        (":AIEEE: @rexmode no", ":AIEEE: rexmode no"),                                # leading emoji colons left alone
    ]
    for said, posted in cases:
        reply["v"] = said
        await bot.on_message(msg(REX, "<@1> stop pinging me", [ME]))
        assert ch.sent[-1] == posted, (said, ch.sent[-1])
    # her chat log shows what she posted (no @ at him), so she doesn't learn to keep @-ing him
    assert "Gomihyu: :AIEEE: rexmode no" in bot.history[9], list(bot.history[9])
    # replying to kaz0, an @ at rexmode pings him
    reply["v"] = "go ask @rexmode"; await bot.on_message(msg(KAZ, "who's hosting tonight"))
    assert ch.sent[-1] == "go ask <@111111111111111111>", ch.sent[-1]
    await r.cleanup(); print("PING TESTS PASSED")
asyncio.run(main())
