import os as _os; REPO, TMP = _os.environ["GOMI_REPO"], _os.environ["GOMI_TMP"]  # set by tests/run_all.sh
# Quiet mode: she only answers people talking to her.
import asyncio, itertools, os, sys, time, types, logging
from contextlib import asynccontextmanager
from aiohttp import web
SP = TMP
os.environ.update(DISCORD_BOT_TOKEN="fake", OLLAMA_URL="http://127.0.0.1:8767/api/chat", PEOPLE_FILE=f"{SP}/people_quiet.json")
if os.path.exists(f"{SP}/people_quiet.json"): os.remove(f"{SP}/people_quiet.json")
sys.path.insert(0, REPO)
from gomi import bot, chime
from gomi.commands import quiet_request as q, unmute_request as u, FOREVER
logging.getLogger("aiohttp.access").setLevel(logging.WARNING)
bot.examples = []; bot.CHIME_IN_THRESHOLD = 6; bot.REACT_ONLY_MAX_WORDS = 2

D = 30
qc = {"gomi quiet mode": D, "@Gomihyu quiet mode": D, "gomi quiet mode for an hour": 60, "gomi quiet mode 2h": 120,
      "gomi quiet mode until i say so": FOREVER, "gomi only talk when spoken to": D, "gomi only reply when pinged": D,
      "gomi only talk when someone talks to you for the next hour": 60, "gomi go into quiet mode": D,
      "gomi quiet mode off": None, "gomi turn off quiet mode": None, "gomi what's quiet mode?": None,
      "gomi don't make me put you in quiet mode": None, "gomi i'll put you in quiet mode": None, "gomi be quiet": None,
      "gomi stfu": None, "gomi quiet": None, "gomi mute": None}
assert not (bad := {t: (q(t, D), w) for t, w in qc.items() if q(t, D) != w}), bad
uc = {"gomi unmute": True, "gomi quiet mode off": True, "gomi turn off quiet mode": True, "gomi end quiet mode": True,
      "gomi you can talk again": True, "gomi you can chime in again": True, "gomi no more quiet mode": True,
      "gomi quiet mode": False, "gomi mute": False, "gomi i'll unmute you later": False, "gomi don't unmute yet": False,
      "gomi unmute, i'll mute you again if needed": True, "gomi maybe i'll turn off quiet mode later": False}
assert not (bad := {t: (u(t), w) for t, w in uc.items() if u(t) != w}), bad

calls, replies, slow = [], itertools.count(1), {"v": 0}
async def fake(request):
    body = await request.json(); calls.append(body)
    if "interest" in body.get("format", {}).get("properties", {}):
        return web.json_response({"message": {"content": '{"read": "chat", "interest": 9, "react": 9, "emoji": "😈"}'}, "done_reason": "stop"})
    if "format" in body:
        return web.json_response({"message": {"content": '{"emoji": "😈"}'}, "done_reason": "stop"})
    await asyncio.sleep(slow["v"])
    return web.json_response({"message": {"content": f"reply {next(replies)}"}, "done_reason": "stop"})
about = lambda c: c["messages"][1]["content"].split("\n\nThe last message is from")[0].splitlines()[-1]
judged = lambda: [c for c in calls if "interest" in c.get("format", {}).get("properties", {}) and about(c) != "kaz0: lol"]
ME = types.SimpleNamespace(id=1, name="Gomihyu", display_name="Gomihyu", bot=True); bot.client._connection.user = ME
REX = types.SimpleNamespace(id=5, name="rexmode", display_name="REX MODE", bot=False)
KAZ = types.SimpleNamespace(id=6, name="kaz0", display_name="Kaz", bot=False)
ids = itertools.count(1000)
class Post:
    def __init__(self, ch, author, content, mentions=(), reference=None):
        self.id, self.channel, self.author, self.content, self.guild = next(ids), ch, author, content, None
        self.mentions, self.reference, self.reactions = list(mentions), reference, []
        self.role_mentions = self.channel_mentions = self.attachments = self.stickers = []
    async def add_reaction(self, emoji): self.reactions.append(emoji)
class Channel:
    def __init__(self, i): self.id, self.name, self.guild, self.posts = i, "general", None, []
    @asynccontextmanager
    async def typing(self): yield
    async def send(self, text):
        post = Post(self, ME, text); self.posts.append(post); return post
    def hers(self): return [p.content for p in self.posts if p.author is ME]
async def say(ch, author, content, mentions=(), reply_to=None):
    post = Post(ch, author, content, mentions, types.SimpleNamespace(resolved=reply_to) if reply_to else None)
    ch.posts.append(post); await bot.on_message(post); return post

async def main():
    app = web.Application(); app.router.add_post("/api/chat", fake)
    r = web.AppRunner(app); await r.setup(); await web.TCPSite(r, "127.0.0.1", 8767).start()
    bot.owner_ids.clear(); bot.owner_ids.add(REX.id)
    ch, other = Channel(1), Channel(2)

    # a non-owner can't: it's just a post to her
    await say(ch, KAZ, "gomi quiet mode"); assert not bot.quiet(1) and ch.hers() == ["reply 1"]

    # "gomi quiet mode": 🤫, no model call, not in her log
    calls.clear(); cmd = await say(ch, REX, "gomi quiet mode")
    assert cmd.reactions == ["🤫"] and calls == [] and bot.quiet(1) and not bot.muted(1)
    assert abs(bot.quiet_until[1] - (time.monotonic() + 30 * 60)) < 5 and "rexmode: gomi quiet mode" not in bot.history[1]

    # quiet: no chiming in (not even the interest call), no reply to sad news; the rest as usual
    calls.clear()
    await say(ch, KAZ, "elden ring dlc is peak honestly")
    await say(ch, KAZ, "my dog died last night")
    assert ch.hers() == ["reply 1"] and calls == []
    lol = await say(ch, KAZ, "lol")                                     # emoji reactions still happen
    assert lol.reactions == ["😈"]
    await say(ch, KAZ, "gomi what do you think")
    await say(ch, KAZ, "<@1> hello?", [ME])
    await say(ch, KAZ, "no way that is true", reply_to=ch.posts[1])                  # a Discord reply to her post
    assert ch.hers() == ["reply 1", "reply 2", "reply 3", "reply 4"] and judged() == [], (ch.hers(), len(judged()))
    assert "kaz0: elden ring dlc is peak honestly" in bot.history[1]   # she still follows the chat

    # posts arriving while she answers: only one aimed at her gets the follow-up
    slow["v"] = 0.3
    first = asyncio.create_task(say(ch, KAZ, "gomi pick a game"))
    await asyncio.sleep(0.1); await say(ch, KAZ, "i vote mario kart"); await first
    assert ch.hers()[-1] == "reply 5" and len(ch.hers()) == 5
    first = asyncio.create_task(say(ch, KAZ, "gomi pick another"))
    await asyncio.sleep(0.1); await say(ch, REX, "gomi answer me too"); await first
    assert ch.hers()[-2:] == ["reply 6", "reply 7"]
    slow["v"] = 0

    # other channels chime in as usual
    calls.clear(); await say(other, KAZ, "elden ring dlc is peak honestly")
    assert other.hers() == ["reply 8"] and len(judged()) == 1

    # mute and quiet mode replace each other; "unmute" / "quiet mode off" / "you can talk again" end either
    await say(ch, REX, "gomi mute"); assert bot.muted(1) and not bot.quiet(1)
    await say(ch, REX, "gomi quiet mode for an hour"); assert bot.quiet(1) and not bot.muted(1)
    assert abs(bot.quiet_until[1] - (time.monotonic() + 3600)) < 5
    cmd = await say(ch, REX, "gomi quiet mode off"); assert cmd.reactions == ["🔊"] and not bot.quiet(1)
    await say(ch, REX, "gomi quiet mode until i say so"); assert bot.quiet_until[1] == float("inf")
    await say(ch, REX, "gomi unmute"); assert not bot.quiet(1)
    await say(ch, REX, "gomi mute"); cmd = await say(ch, REX, "gomi you can talk again")
    assert cmd.reactions == ["🔊"] and not bot.muted(1)

    # back to normal: she chimes in again
    calls.clear(); n = len(ch.hers())
    await say(ch, KAZ, "elden ring dlc is peak honestly")
    assert len(judged()) == 1 and len(ch.hers()) == n + 1
    await r.cleanup(); print("QUIET TESTS PASSED")
asyncio.run(main())
