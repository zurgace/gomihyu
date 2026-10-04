import os as _os; REPO, TMP = _os.environ["GOMI_REPO"], _os.environ["GOMI_TMP"]  # set by tests/run_all.sh
import asyncio, os, sys, types
from contextlib import asynccontextmanager
from aiohttp import web

os.environ["PEOPLE_FILE"] = TMP + "/people_test_bot.json"; os.environ["DISCORD_BOT_TOKEN"] = "fake"
os.environ["OLLAMA_URL"] = "http://127.0.0.1:8765/api/chat"
sys.path.insert(0, REPO)
import bot, persona
from datetime import datetime
bot.REACT_ONLY_MAX_WORDS = 0; bot.CHIME_IN_THRESHOLD = 0  # these tests are about replies
NOW = datetime(2026, 10, 4, 13, 31); bot.local_now = lambda: NOW
bot.examples = []  # example chats are covered by test_fewshot.py

requests = []          # user-turn content of every prompt Ollama received
canned = iter([])      # model outputs to return, in order

async def fake_ollama(request):
    body = await request.json()
    requests.append(body)
    await asyncio.sleep(0.3)  # generation takes a while
    return web.json_response({"message": {"content": next(canned)}})

def user(uid, name, is_bot=False): return types.SimpleNamespace(id=uid, name=name, display_name=name, bot=is_bot)

ME = user(1, "Gomihyu", True)
bot.client._connection.user = ME

class Channel:
    def __init__(self, cid): self.id, self.name, self.sent = cid, f"chan{cid}", []
    @asynccontextmanager
    async def typing(self): yield
    async def send(self, text): self.sent.append(text)

def msg(channel, author, content, mentions=(), roles=(), channels=()):
    return types.SimpleNamespace(author=author, channel=channel, content=content, mentions=list(mentions),
                                 role_mentions=list(roles), channel_mentions=list(channels), attachments=[], stickers=[], guild=None)

KAZ, NORI = user(100, "kaz0"), user(200, "NoriMaki")

async def main():
    global canned
    app = web.Application(); app.router.add_post("/api/chat", fake_ollama)
    runner = web.AppRunner(app); await runner.setup(); await web.TCPSite(runner, "127.0.0.1", 8765).start()

    # 1. readable(): mention tokens become @handle / @role / #channel
    role, chan = types.SimpleNamespace(id=300, name="mods"), types.SimpleNamespace(id=400, name="general")
    m = msg(Channel(9), KAZ, "<@1> hi <@!200> ask <@&300> in <#400> <@999>", [ME, NORI], [role], [chan])
    assert bot.readable(m) == "@Gomihyu hi @NoriMaki ask @mods in #general <@999>", bot.readable(m)

    # 2. every message gets a reply; prefix stripped; @handle -> ping; payload == build_messages, with the
    #    date; @names nobody has: one retry, then those sentences go (never a mass ping)
    c1 = Channel(10)
    canned = iter(["Gomihyu: first", *["**Gomihyu:** Silence, @KAZ0. And @nobody, and @everyone."] * 2])
    await bot.on_message(msg(c1, KAZ, "morning chat"))
    await bot.on_message(msg(c1, NORI, "hey @kaz0 <@1>", [KAZ, ME]))
    assert c1.sent == ["first", "Silence, <@100>."], c1.sent
    assert requests[1]["messages"] == persona.build_messages(
        ["kaz0: morning chat", "Gomihyu: first", "NoriMaki: hey @kaz0 @Gomihyu"], True, now=NOW), requests[1]["messages"]
    assert requests[1]["messages"][1]["content"].startswith("Right now it's Sunday, October 4, 2026, 1:31 PM.\n\n")
    assert len(requests) == 3 and requests[2]["options"]["temperature"] == bot.RETRY_TEMPERATURE
    assert "directly mentioned" not in requests[0]["messages"][1]["content"]

    # 3. burst of 4 messages while generating -> first reply + ONE follow-up that sees all 4,
    #    carrying the @mention from a message that arrived mid-reply
    requests.clear(); c2 = Channel(20)
    canned = iter(["reply A", "gomihyu : reply B"])
    first = asyncio.create_task(bot.on_message(msg(c2, KAZ, "one")))
    await asyncio.sleep(0.05); await bot.on_message(msg(c2, NORI, "two"))
    await bot.on_message(msg(c2, KAZ, "three <@1>", [ME]))
    await bot.on_message(msg(c2, NORI, "four"))
    await first
    assert c2.sent == ["reply A", "reply B"], c2.sent
    assert len(requests) == 2
    follow = requests[1]["messages"][1]["content"]
    assert "kaz0: one\nGomihyu: reply A\nNoriMaki: two\nkaz0: three @Gomihyu\nNoriMaki: four" in follow, follow
    assert "directly mentioned" in follow
    assert not bot.pending_followup and not bot.reply_locks[20].locked()

    # 3b. more messages arrive mid-reply than HISTORY_LENGTH holds -> stale reply falls off the log
    c6 = Channel(60); canned = iter(["stale", "fresh"])
    first = asyncio.create_task(bot.on_message(msg(c6, KAZ, "start")))
    await asyncio.sleep(0.05)
    for i in range(bot.HISTORY_LENGTH + 2): await bot.on_message(msg(c6, NORI, f"spam {i}"))
    await first
    assert c6.sent == ["stale", "fresh"] and len(bot.history[60]) == bot.HISTORY_LENGTH
    assert list(bot.history[60])[-2:] == [f"NoriMaki: spam {bot.HISTORY_LENGTH + 1}", "Gomihyu: fresh"], list(bot.history[60])
    assert not any("stale" in l for l in list(bot.history[60]))
    requests.clear()

    # 4. two channels generate concurrently (lock is per channel, not global)
    requests.clear(); c3, c4 = Channel(30), Channel(40)
    canned = iter(["x", "y"])
    t0 = asyncio.get_running_loop().time()
    await asyncio.gather(bot.on_message(msg(c3, KAZ, "a")), bot.on_message(msg(c4, NORI, "b")))
    assert asyncio.get_running_loop().time() - t0 < 0.5 and c3.sent and c4.sent

    # 5. bots (including itself) are ignored; Ollama down -> no reply, no crash, lock released
    await bot.on_message(msg(c3, user(5, "otherbot", True), "beep"))
    assert len(requests) == 2
    bot.OLLAMA_URL = "http://127.0.0.1:1/api/chat"
    c5 = Channel(50); await bot.on_message(msg(c5, KAZ, "hello?"))
    assert c5.sent == [] and not bot.reply_locks[50].locked()

    await runner.cleanup()
    print("ALL BEHAVIOR TESTS PASSED")

asyncio.run(main())
