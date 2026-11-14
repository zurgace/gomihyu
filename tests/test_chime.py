import os as _os; REPO, TMP = _os.environ["GOMI_REPO"], _os.environ["GOMI_TMP"]  # set by tests/run_all.sh
# She chimes in on posts not aimed at her only when the interest call rates them >= CHIME_IN_THRESHOLD.
import asyncio, json, os, sys, types, logging
from contextlib import asynccontextmanager
from aiohttp import web
SP = TMP
os.environ.update(DISCORD_BOT_TOKEN="fake", OLLAMA_URL="http://127.0.0.1:8771/api/chat", PEOPLE_FILE=f"{SP}/people_chime.json")
os.environ.pop("CHIME_IN_THRESHOLD", None)
sys.path.insert(0, REPO)
import bot, chime
logging.getLogger("aiohttp.access").setLevel(logging.WARNING)
bot.examples = []
assert bot.CHIME_IN_THRESHOLD == 6   # the default

# parse_room: the interest part (the reaction part is in test_reactions.py)
P = lambda content: (r.interest if (r := chime.parse_room(content, {"😤": "x"})) else None)
assert P('{"interest": 7}') == 7 and P('{"interest": 12}') == 10 and P('{"interest": -1}') == 0 and P('{"interest": 6.6}') == 7
assert P('{"interest": "7"}') is None and P('{"interest": true}') is None and P("{}") is None and P("nope") is None and P("[]") is None
is_room = lambda body: "interest" in body.get("format", {}).get("properties", {})

calls, judge = [], {"answer": '{"interest": 3}', "status": 200, "delay": 0}
reply_delay = {"v": 0}
async def fake(request):
    body = await request.json(); calls.append(body)
    if is_room(body):
        await asyncio.sleep(judge["delay"])
        if judge["status"] != 200: return web.json_response({"error": "boom"}, status=judge["status"])
        return web.json_response({"message": {"content": judge["answer"]}, "done_reason": "stop"})
    await asyncio.sleep(reply_delay["v"])
    return web.json_response({"message": {"content": f"reply {len(calls)}"}, "done_reason": "stop"})
judged = lambda: [c for c in calls if is_room(c)]
replied = lambda: [c for c in calls if "format" not in c]

ME = types.SimpleNamespace(id=1, name="Gomihyu", display_name="Gomihyu", bot=True); bot.client._connection.user = ME
REX = types.SimpleNamespace(id=5, name="rexmode", display_name="REX MODE", bot=False)
KAZ = types.SimpleNamespace(id=6, name="kaz0", display_name="Kaz", bot=False)
class Channel:
    def __init__(self, i): self.id, self.guild, self.sent = i, None, []
    @asynccontextmanager
    async def typing(self): yield
    async def send(self, text): self.sent.append(text)
def msg(ch, author, c, mentions=(), reference=None):
    return types.SimpleNamespace(author=author, channel=ch, guild=None, content=c, mentions=list(mentions), reference=reference,
                                 role_mentions=[], channel_mentions=[], attachments=[], stickers=[])

async def main():
    app = web.Application(); app.router.add_post("/api/chat", fake)
    r = web.AppRunner(app); await r.setup(); await web.TCPSite(r, "127.0.0.1", 8771).start()

    # not aimed at her, dull: one interest call, no reply
    ch = Channel(1); calls.clear()
    await bot.on_message(msg(ch, REX, "ok i'll grab the charger from the car"))
    assert ch.sent == [] and len(calls) == 1 and len(judged()) == 1
    c = judged()[0]
    assert c["think"] is False and c["options"] == {"num_ctx": 8192} and c["stream"] is False
    assert "a bratty, dramatic" in c["messages"][0]["content"] and "secretly soft" in c["messages"][0]["content"]
    assert "rexmode: ok i'll grab the charger from the car\n\nThe last message is from rexmode. About that last message:" in c["messages"][1]["content"]

    # interesting (and exactly at the threshold): interest call, then a normal reply
    for rating in (8, 6):
        judge["answer"] = json.dumps({"interest": rating}); calls.clear()
        await bot.on_message(msg(ch, KAZ, "elden ring dlc is mid honestly"))
        assert ch.sent[-1].startswith("reply") and len(judged()) == 1 and len(replied()) == 1, rating
    judge["answer"] = '{"interest": 5}'; n = len(ch.sent); calls.clear()
    await bot.on_message(msg(ch, KAZ, "anyway going to bed"))
    assert len(ch.sent) == n and len(judged()) == 1                    # just under: quiet

    # aimed at her: always a reply, no interest call
    judge["answer"] = '{"interest": 0}'
    last = types.SimpleNamespace(author=ME)                            # a Discord reply to one of her messages, ping off
    for m in [msg(ch, REX, "<@1> what do you think", [ME]), msg(ch, REX, "gomi what do you think"),
              msg(ch, REX, "what do you think, Gomihyu?"), msg(ch, REX, "no way that's true", reference=types.SimpleNamespace(resolved=last)),
              msg(ch, REX, "my grandma died last night")]:
        calls.clear(); n = len(ch.sent)
        await bot.on_message(m)
        assert len(ch.sent) == n + 1 and judged() == [], m.content
    # a reply to someone else's message, or her name only inside a link, isn't aimed at her
    for m in [msg(ch, REX, "no way that's true", reference=types.SimpleNamespace(resolved=types.SimpleNamespace(author=KAZ))),
              msg(ch, REX, "look at this https://example.com/gomi-cat.gif so good"),
              msg(ch, REX, "no way that's true", reference=types.SimpleNamespace(resolved=None))]:
        calls.clear(); n = len(ch.sent)
        await bot.on_message(m)
        assert len(ch.sent) == n and len(judged()) == 1, m.content

    # a broken answer or a failed call: she stays quiet
    for answer, status in [("not json", 200), ('{"interest": "high"}', 200), ('{"interest": 9}', 500)]:
        judge["answer"], judge["status"] = answer, status; calls.clear(); n = len(ch.sent)
        await bot.on_message(msg(ch, KAZ, "who's up for mario kart later"))
        assert len(ch.sent) == n and len(judged()) == 1 and replied() == [], answer
    judge["status"] = 200

    # CHIME_IN_THRESHOLD=0: answers everything, never asks
    bot.CHIME_IN_THRESHOLD = 0; calls.clear(); n = len(ch.sent)
    await bot.on_message(msg(ch, KAZ, "ok i'll grab the charger from the car"))
    assert len(ch.sent) == n + 1 and judged() == []
    bot.CHIME_IN_THRESHOLD = 6

    # While she's deciding, more posts arrive. The old reading is discarded and the latest post is read.
    ch = Channel(2); judge.update(answer='{"interest": 8}', delay=0.3); calls.clear()
    first = asyncio.create_task(bot.on_message(msg(ch, KAZ, "who's up for mario kart later")))
    await asyncio.sleep(0.1)
    me = asyncio.create_task(bot.on_message(msg(ch, REX, "me")))     # 1 word: read for a reaction only, never a reply
    await asyncio.sleep(0)
    await bot.on_message(msg(ch, REX, "i'm in, 9pm works for me"))
    await first; await me
    assert len(ch.sent) == 1 and len(judged()) == 3, (ch.sent, len(judged()))
    assert list(bot.history[2])[-2:] == ["rexmode: i'm in, 9pm works for me", f"Gomihyu: {ch.sent[0]}"], list(bot.history[2])

    # if she stays quiet, the post that arrived while she decided gets its own look: an @mention is just answered
    ch = Channel(3); judge.update(answer='{"interest": 2}', delay=0.3); calls.clear()
    first = asyncio.create_task(bot.on_message(msg(ch, KAZ, "ok i'll grab the charger from the car")))
    await asyncio.sleep(0.1)
    await bot.on_message(msg(ch, REX, "<@1> you're quiet today", [ME]))
    await first
    assert len(ch.sent) == 1 and len(judged()) == 1 and "directly mentioned" in replied()[0]["messages"][1]["content"]
    #   ...and an unaddressed one is rated again, on the newest post
    ch = Channel(4); calls.clear()
    first = asyncio.create_task(bot.on_message(msg(ch, KAZ, "ok i'll grab the charger from the car")))
    await asyncio.sleep(0.1)
    await bot.on_message(msg(ch, REX, "cool see you at 9 then"))
    await first
    assert ch.sent == [] and len(judged()) == 2
    assert judged()[1]["messages"][1]["content"].split("\n\nThe last message is from")[0].endswith("rexmode: cool see you at 9 then")

    # Posts arriving while she writes replace the stale chime-in with a freshly rated reply.
    ch = Channel(5); judge.update(answer='{"interest": 7}', delay=0); reply_delay["v"] = 0.3; calls.clear()
    first = asyncio.create_task(bot.on_message(msg(ch, KAZ, "elden ring dlc is mid honestly")))
    await asyncio.sleep(0.1)
    await bot.on_message(msg(ch, REX, "nah it's peak"))
    await bot.on_message(msg(ch, KAZ, "the final boss is so bad though"))
    await first
    assert len(ch.sent) == 1 and len(judged()) == 2 and len(replied()) == 2
    await r.cleanup(); print("CHIME TESTS PASSED")
asyncio.run(main())
