import os as _os; REPO, TMP = _os.environ["GOMI_REPO"], _os.environ["GOMI_TMP"]  # set by tests/run_all.sh
import asyncio, os, sys, types, logging
from contextlib import asynccontextmanager
from aiohttp import web
SP = TMP
os.environ.update(DISCORD_BOT_TOKEN="fake", OLLAMA_URL="http://127.0.0.1:8774/api/chat", PEOPLE_FILE=f"{SP}/people_len.json",
                  MAX_REPLY_TOKENS="120", OLLAMA_NUM_CTX="6144")
sys.path.insert(0, REPO)
import bot, persona
logging.getLogger("aiohttp.access").setLevel(logging.WARNING)
bot.REACT_ONLY_MAX_WORDS = 0; bot.CHIME_IN_THRESHOLD = 0

# the prompt no longer asks for one-liners, and asks her to take part
s, m = persona.SYSTEM_PROMPT, persona.build_messages(["kaz0: pineapple pizza is good", "nori: no it isn't"], False)[1]["content"]
assert "at most 2 sentences" not in m and "often just a few words" not in m and "only context" not in m
assert "a question or a real discussion gets 2 to 4 sentences, never more" in m and "give your own opinion" in m
assert "actually answer it" in m and "Now and then, not every time, ask something back" in m
assert "You are replying to the newest message, from nori:\nnori: no it isn't" in m
assert "You're an active part of this group chat, not a bystander" in s and "casual and quick" not in s

out = {"v": None}
async def fake(request):
    body = await request.json(); out["req"] = body
    content, reason = out["v"]
    return web.json_response({"message": {"content": content}, "done_reason": reason})
ME = types.SimpleNamespace(id=1, name="Gomihyu", display_name="Gomihyu", bot=True); bot.client._connection.user = ME
KAZ = types.SimpleNamespace(id=7, name="kaz0", display_name="Kaz", bot=False)
class Channel:
    id, guild, sent = 11, None, []
    @asynccontextmanager
    async def typing(self): yield
    async def send(self, text): self.sent.append(text)
ch = Channel()
msg = lambda c: types.SimpleNamespace(author=KAZ, channel=ch, guild=None, content=c, mentions=[], role_mentions=[],
                                      channel_mentions=[], attachments=[], stickers=[])
async def main():
    app = web.Application(); app.router.add_post("/api/chat", fake)
    r = web.AppRunner(app); await r.setup(); await web.TCPSite(r, "127.0.0.1", 8774).start()
    cases = [
        (("Smash, obviously. I have a rematch to win! Also Overcooked is fun because you all pani", "length"),
         "Smash, obviously. I have a rematch to win!"),                          # cut back to the last full sentence
        (("wait, is that true? I thought it was the other way arou", "length"), "wait, is that true?"),
        (("no sentence end at all just rambling on and on", "length"), "no sentence end at all just rambling on and on"),
        (("Short and done. Not cut", "stop"), "Short and done. Not cut"),            # finished normally: untouched
        (("v1.2 is out... ok that's wild. more soon", "length"), "v1.2 is out... ok that's wild."),
    ]
    for (content, reason), want in cases:
        out["v"] = (content, reason); await bot.on_message(msg("what game should we play saturday"))
        assert ch.sent[-1] == want, (ch.sent[-1], want)
    assert out["req"]["options"] == {"num_ctx": 6144, "num_predict": 120}  # both from .env
    await r.cleanup(); print("LENGTH TESTS PASSED")
asyncio.run(main())
