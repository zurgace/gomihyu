import os as _os; REPO, TMP = _os.environ["GOMI_REPO"], _os.environ["GOMI_TMP"]  # set by tests/run_all.sh
import asyncio, os, sys, types, logging
from contextlib import asynccontextmanager
from aiohttp import web
os.environ["PEOPLE_FILE"] = TMP + "/people_test_repeat.json"; os.environ["DISCORD_BOT_TOKEN"] = "fake"; os.environ["OLLAMA_URL"] = "http://127.0.0.1:8767/api/chat"
sys.path.insert(0, REPO)
import bot
bot.REACT_ONLY_MAX_WORDS = 0; bot.CHIME_IN_THRESHOLD = 0  # these tests are about replies
logging.getLogger("aiohttp.access").setLevel(logging.WARNING)

R2 = "I am the Archdemon of this realm, and you dare call me such? I shall crush your tiny ego like a fly. But I cannot help noticing you're the only one who dares to speak to me — perhaps I am not as feared as I claim."
R4 = "I am the Archdemon of this realm, and you dare call me such? I shall crush your tiny ego like a fly before you can even process this insult."
R6 = "Your words are as weak as your spirit. I am the Archdemon of this realm, and you are merely a speck in my domain."
outputs, requests = [], []
async def fake(request):
    body = await request.json(); requests.append(body)
    out = outputs.pop(0)
    if out is None: return web.json_response({"error": "boom"}, status=500)
    return web.json_response({"message": {"content": out}, "done_reason": "stop"})

ME = types.SimpleNamespace(id=1, name="Gomihyu", display_name="Gomihyu", bot=True); bot.client._connection.user = ME
REX = types.SimpleNamespace(id=7, name="rexmode", display_name="rexmode", bot=False)
class Channel:
    id, sent = 5, []
    @asynccontextmanager
    async def typing(self): yield
    async def send(self, text): self.sent.append(text)
ch = Channel()
def msg(content, mentions=()):
    return types.SimpleNamespace(author=REX, channel=ch, content=content, mentions=list(mentions), role_mentions=[], channel_mentions=[], attachments=[], stickers=[], guild=None)

async def main():
    app = web.Application(); app.router.add_post("/api/chat", fake)
    r = web.AppRunner(app); await r.setup(); await web.TCPSite(r, "127.0.0.1", 8767).start()

    outputs[:] = [R2]                                   # first reply: nothing to repeat yet
    await bot.on_message(msg("<@1> retard", [ME]))
    assert ch.sent == [R2] and len(requests) == 1 and requests[0]["options"] == {"num_ctx": 8192, "num_predict": 200}

    outputs[:] = [R4, "Chill?! I was PERFECTLY chill. You're the one yelling, rexmode."]
    await bot.on_message(msg("chill"))                  # copies R2 -> one retry at temperature 1.0
    assert len(requests) == 3 and requests[2]["options"] == {"num_ctx": 8192, "num_predict": 200, "temperature": 1.0}, requests[2].get("options")
    assert ch.sent[-1].startswith("Chill?!")

    outputs[:] = [R6, "Fine. Melon bread is superior to you. That's new."]
    await bot.on_message(msg("say something else"))     # shares "i am the archdemon of" with R2 -> retry
    assert len(requests) == 5 and ch.sent[-1].startswith("Fine.")

    outputs[:] = ["That's what an ordinary mortal would say, obviously.", ]
    await bot.on_message(msg("ok"))                     # fresh wording -> no retry
    assert len(requests) == 6 and requests[5]["options"] == {"num_ctx": 8192, "num_predict": 200}

    outputs[:] = [R4, None]                             # retry fails -> still sends the first draft
    await bot.on_message(msg("again"))
    assert len(requests) == 8 and ch.sent[-1] == R4

    # the prompt the model saw for "chill" carries the new instruction
    assert "don't repeat your own earlier lines" in requests[1]["messages"][1]["content"]
    assert "only come up now and then" in requests[1]["messages"][0]["content"]
    await r.cleanup(); print("REPEAT GUARD TESTS PASSED")
asyncio.run(main())
