import os as _os; REPO, TMP = _os.environ["GOMI_REPO"], _os.environ["GOMI_TMP"]  # set by tests/run_all.sh
import asyncio, os, sys, types, logging, subprocess
from contextlib import asynccontextmanager
from aiohttp import web
SP = TMP
os.environ.update(DISCORD_BOT_TOKEN="fake", OLLAMA_URL="http://127.0.0.1:8775/api/chat", PEOPLE_FILE=f"{SP}/people_think.json")
sys.path.insert(0, REPO)
import bot
logging.getLogger("aiohttp.access").setLevel(logging.WARNING)
bot.REACT_ONLY_MAX_WORDS = 0; bot.CHIME_IN_THRESHOLD = 0

calls, mode = [], {"honors_think": True}
THOUGHT = "The user wants me to respond as Gomi. I need to: 1. Not prefix my reply..."
async def fake(request):
    body = await request.json(); calls.append(body)
    if "format" in body:                                   # emoji picker
        return web.json_response({"message": {"content": '{"emoji": "none"}'}, "done_reason": "stop"})
    thinks = body.get("think") or not mode["honors_think"]
    capped = "num_predict" in body.get("options", {})
    if thinks and capped:                                  # the log: all tokens spent thinking, no (or half an) answer
        return web.json_response({"message": {"role": "assistant", "content": mode.get("partial", ""), "thinking": THOUGHT},
                                  "done_reason": "length"})
    if mode.get("inline"):                                 # reasoning written into the answer itself
        return web.json_response({"message": {"role": "assistant", "content": mode["inline"]}, "done_reason": "stop"})
    return web.json_response({"message": {"role": "assistant", "content": "smash, obviously.",
                                          **({"thinking": THOUGHT} if thinks else {})}, "done_reason": "stop"})
ME = types.SimpleNamespace(id=1, name="Gomihyu", display_name="Gomihyu", bot=True); bot.client._connection.user = ME
REX = types.SimpleNamespace(id=5, name="rexmode", display_name="REX MODE", bot=False)
class Channel:
    id, guild, sent = 12, None, []
    @asynccontextmanager
    async def typing(self): yield
    async def send(self, text): self.sent.append(text)
ch = Channel()
msg = lambda c, mentions=(): types.SimpleNamespace(author=REX, channel=ch, guild=None, content=c, mentions=list(mentions),
                                                   role_mentions=[], channel_mentions=[], attachments=[], stickers=[])
async def main():
    app = web.Application(); app.router.add_post("/api/chat", fake)
    r = web.AppRunner(app); await r.setup(); await web.TCPSite(r, "127.0.0.1", 8775).start()

    # default: thinking off, one call, answer sent
    assert bot.OLLAMA_THINK is False
    await bot.on_message(msg("what games should we play this saturday"))
    assert ch.sent == ["smash, obviously."] and len(calls) == 1
    assert calls[0]["think"] is False and calls[0]["options"] == {"num_ctx": 8192, "num_predict": 200}

    # a model that thinks anyway: first answer is thinking-only -> one retry without the cap, answer sent
    mode["honors_think"] = False; calls.clear()
    await bot.on_message(msg("<@1> are you broken", [ME]))
    assert ch.sent[-1] == "smash, obviously." and len(calls) == 2
    assert calls[0]["options"] == {"num_ctx": 8192, "num_predict": 200} and calls[1]["options"] == {"num_ctx": 8192}
    assert bot.model_thinks is True

    # ...and from then on, one uncapped call per reply: no wasted capped attempt
    calls.clear()
    await bot.on_message(msg("ok but which character"))
    assert ch.sent[-1] == "smash, obviously." and len(calls) == 1 and calls[0]["options"] == {"num_ctx": 8192}

    # thinking that leaves half an answer at the cap is retried too, not trimmed and sent
    bot.model_thinks = False; mode["partial"] = "Smash. Obviously, because"; calls.clear()
    await bot.on_message(msg("smash or mario kart"))
    assert ch.sent[-1] == "smash, obviously." and len(calls) == 2 and calls[1]["options"] == {"num_ctx": 8192}

    # reasoning inside the content is never posted: closed, unclosed, or with only the closing tag
    mode.pop("partial"); bot.model_thinks = True
    for raw, sent in [("<think>they want a game pick</think>\n\nsmash, duh.", "smash, duh."),
                      ("they want a game pick\n</think>\nmario kart, duh.", "mario kart, duh."),
                      ("peak. <think>should I add", "peak.")]:
        mode["inline"] = raw
        await bot.on_message(msg("smash or mario kart"))
        assert ch.sent[-1] == sent, (raw, ch.sent[-1])
    n = len(ch.sent); mode["inline"] = "<think>still planning, never answers"
    await bot.on_message(msg("hello??"))
    assert len(ch.sent) == n  # nothing posted
    mode.pop("inline")
    assert bot.strip_thinking("no tags at all") == "no tags at all"

    # the emoji picker sends think=false too
    bot.REACT_ONLY_MAX_WORDS = 2; calls.clear()
    await bot.on_message(msg("oogaga"))
    assert len(calls) == 1 and "format" in calls[0] and calls[0]["think"] is False and calls[0]["options"] == {"num_ctx": 8192}

    # OLLAMA_THINK on: her replies think, uncapped (the thinking counts against the cap), and the thought is
    # logged, never posted; that's not a model thinking when told not to. Reading the room still doesn't think.
    bot.OLLAMA_THINK, bot.model_thinks, mode["honors_think"] = True, False, True
    bot.REACT_ONLY_MAX_WORDS = 0; calls.clear(); logged = []
    class Keep(logging.Handler):
        def emit(self, record): logged.append(record.getMessage())
    bot.log.addHandler(Keep())
    await bot.on_message(msg("<@1> smash or mario kart", [ME]))
    assert ch.sent[-1] == "smash, obviously." and len(calls) == 1 and bot.model_thinks is False
    assert calls[0]["think"] is True and calls[0]["options"] == {"num_ctx": 8192}
    assert any(line.startswith("She thought (16 words") and "respond as Gomi" in line for line in logged), logged
    bot.CHIME_IN_THRESHOLD = 6; calls.clear()
    await bot.on_message(msg("anyone up"))
    assert len(calls) == 1 and "format" in calls[0] and calls[0]["think"] is False
    await r.cleanup(); print("THINK TESTS PASSED")
asyncio.run(main())

# OLLAMA_THINK=true in .env turns it back on
out = subprocess.run([sys.executable, "-c", "import bot; print(bot.OLLAMA_THINK)"], cwd=REPO,
                     env={**os.environ, "OLLAMA_THINK": "true"}, capture_output=True, text=True)
assert out.stdout.strip().endswith("True"), out
out = subprocess.run([sys.executable, "-c", "import bot; print(bot.model_thinks, bot.cap(200, bot.OLLAMA_THINK), bot.cap(80))"],
                     cwd=REPO, env={**os.environ, "OLLAMA_THINK": "true"}, capture_output=True, text=True)
assert out.stdout.strip().endswith("False {} {'num_predict': 80}"), out  # replies uncapped from the first, the rest not
print("OLLAMA_THINK ENV OK")
