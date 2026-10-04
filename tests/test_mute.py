import os as _os; REPO, TMP = _os.environ["GOMI_REPO"], _os.environ["GOMI_TMP"]  # set by tests/run_all.sh
# The owner can mute her per channel: code, not the model, keeps her quiet.
import asyncio, itertools, math, os, sys, time, types, logging
from contextlib import asynccontextmanager
from aiohttp import web
SP = TMP
os.environ.update(DISCORD_BOT_TOKEN="fake", OLLAMA_URL="http://127.0.0.1:8769/api/chat", PEOPLE_FILE=f"{SP}/people_mute.json",
                  MUTE_MINUTES="45")
if os.path.exists(f"{SP}/people_mute.json"): os.remove(f"{SP}/people_mute.json")
sys.path.insert(0, REPO)
import discord, bot
from commands import mute_request as m, unmute_request as u, FOREVER
logging.getLogger("aiohttp.access").setLevel(logging.WARNING)
bot.REACT_ONLY_MAX_WORDS = 2; bot.CHIME_IN_THRESHOLD = 0; bot.examples = []
assert bot.MUTE_MINUTES == 45

D = 30
cases = {
    "gomi mute": D, "@Gomihyu mute": D, "gomi mute pls": D, "gomi mute yourself": D, "gomi, mute.": D,
    "gomi mute for 10 minutes": 10, "gomi mute 10m": 10, "gomi mute for 2 hours": 120, "gomi mute 1h": 60,
    "gomi mute for an hour": 60, "gomi mute for half an hour": 30, "gomi mute for a day": 1440, "gomi mute for two hours": 120,
    "gomi mute for 1.5 hours": 90, "gomi MUTE FOR 5 MINS": 5, "gomi mute 45 min": 45, "gomi mute for 3 days": 4320,
    "gomi mute until i say so": FOREVER, "gomi mute till i unmute you": FOREVER, "gomi mute forever": FOREVER,
    "gomi mute indefinitely": FOREVER, "gomi mute for good": FOREVER, "in 5 minutes... gomi mute": D,
    "gomi unmute": None, "gomi don't mute": None, "gomi don't make me mute you": None, "gomi i'll mute you": None,
    "gomi im gonna mute you": None, "gomi is muted lol": None, "gomi mute for 0 minutes": None, "gomi stfu": None,
    "gomi shut up": None, "gomi mute and i mean it": D, "gomi mute, you're a menace": D, "gomi mute im heading out": D,
}
assert not (bad := {t: (m(t, D), want) for t, want in cases.items() if m(t, D) != want}), bad
ucases = {"gomi unmute": True, "@Gomihyu unmute": True, "gomi unmute pls": True, "gomi mute": False,
          "gomi i'll unmute you later": False, "gomi don't unmute yet": False, "gomi unmute, i'll mute you again if needed": True}
assert not (bad := {t: (u(t), want) for t, want in ucases.items() if u(t) != want}), bad

calls, replies, slow = [], itertools.count(1), {"v": 0}
async def fake(request):
    body = await request.json(); calls.append(body)
    if "format" in body:  # emoji picker
        return web.json_response({"message": {"content": '{"emoji": "👍"}'}, "done_reason": "stop"})
    await asyncio.sleep(slow["v"])
    return web.json_response({"message": {"content": f"reply {next(replies)}"}, "done_reason": "stop"})
ME = types.SimpleNamespace(id=1, name="Gomihyu", display_name="Gomihyu", bot=True); bot.client._connection.user = ME
REX = types.SimpleNamespace(id=5, name="rexmode", display_name="REX MODE", bot=False)
KAZ = types.SimpleNamespace(id=6, name="kaz0", display_name="Kaz", bot=False)
ids = itertools.count(1000)
class Post:
    def __init__(self, ch, author, content, mentions=()):
        self.id, self.channel, self.author, self.content, self.guild = next(ids), ch, author, content, None
        self.mentions, self.reference, self.reactions = list(mentions), None, []
        self.role_mentions = self.channel_mentions = self.attachments = self.stickers = []
    async def delete(self): self.channel.posts.remove(self)
    async def add_reaction(self, emoji): self.reactions.append(emoji)
class Channel:
    def __init__(self, i, name): self.id, self.name, self.guild, self.posts = i, name, None, []
    @asynccontextmanager
    async def typing(self): yield
    async def send(self, text):
        post = Post(self, ME, text); self.posts.append(post); return post
    async def history(self, limit):
        for post in reversed(self.posts[-limit:]): yield post
    def hers(self): return [p.content for p in self.posts if p.author is ME]
async def say(ch, author, content, mentions=()):
    post = Post(ch, author, content, mentions); ch.posts.append(post); await bot.on_message(post); return post

async def main():
    app = web.Application(); app.router.add_post("/api/chat", fake)
    r = web.AppRunner(app); await r.setup(); await web.TCPSite(r, "127.0.0.1", 8769).start()
    bot.owner_ids.clear(); bot.owner_ids.add(REX.id)
    ch, other = Channel(1, "general"), Channel(2, "memes")

    await say(ch, KAZ, "morning everyone, how are we"); assert ch.hers() == ["reply 1"]

    # "gomi mute": 🔇, default MUTE_MINUTES, no model call, the command isn't in her log
    calls.clear()
    cmd = await say(ch, REX, "gomi mute")
    assert cmd.reactions == ["🔇"] and calls == [] and bot.muted(1)
    assert abs(bot.muted_until[1] - (time.monotonic() + 45 * 60)) < 5
    assert "rexmode: gomi mute" not in bot.history[1]

    # muted: she follows the chat but says nothing, reacts to nothing, and 🤐s anyone talking to her
    calls.clear()
    p1 = await say(ch, KAZ, "elden ring dlc is peak honestly")
    p2 = await say(ch, KAZ, "lol")                                     # would get an emoji reaction
    p3 = await say(ch, KAZ, "gomi what do you think")
    p4 = await say(ch, KAZ, "<@1> hello??", [ME])
    p5 = await say(ch, KAZ, "my dog died last night")
    p6 = await say(ch, KAZ, "gomi remember that I like tea")           # memory still works
    p7 = await say(ch, KAZ, "gomi unmute")                             # not an owner: just a post to her
    assert ch.hers() == ["reply 1"] and calls == []
    assert p1.reactions == p2.reactions == p5.reactions == [] and p3.reactions == p4.reactions == p7.reactions == ["🤐"]
    assert p6.reactions == ["📝", "🤐"] and bot.memory.facts_for(KAZ.id) == ["I like tea"]
    assert "kaz0: elden ring dlc is peak honestly" in bot.history[1] and "kaz0: gomi what do you think" in bot.history[1]

    # other channels aren't muted
    await say(other, KAZ, "anyone up for smash"); assert other.hers() == ["reply 2"]

    # owner commands still work while muted; "i'll mute you" is just chat (once she can talk)
    cmd = await say(ch, REX, "gomi delete that"); assert cmd.reactions == ["🗑️"] and ch.hers() == []
    cmd = await say(ch, REX, "gomi unmute")
    assert cmd.reactions == ["🔊"] and not bot.muted(1) and "rexmode: gomi unmute" not in bot.history[1] and "kaz0: gomi unmute" in bot.history[1]
    await say(ch, REX, "gomi i'll mute you if you keep going")
    assert ch.hers() == ["reply 3"] and bot.history[1][-1] == "Gomihyu: reply 3"
    assert "kaz0: elden ring dlc is peak honestly" in bot.history[1]     # what she missed is still in her log

    # a time: "for 10 minutes"; when it runs out she talks again
    await say(ch, REX, "gomi mute for 10 minutes")
    assert abs(bot.muted_until[1] - (time.monotonic() + 600)) < 5
    await say(ch, KAZ, "hello?"); assert ch.hers() == ["reply 3"]
    bot.muted_until[1] = time.monotonic() - 1                            # ...ten minutes later
    await say(ch, KAZ, "hello??"); assert ch.hers() == ["reply 3", "reply 4"]

    # "until i say so": no end
    await say(ch, REX, "gomi mute until i say so"); assert bot.muted_until[1] == math.inf and bot.muted(1)
    await say(ch, REX, "gomi unmute")

    # muted while she's writing: the reply isn't sent or logged, and no follow-up comes
    slow["v"] = 0.3; calls.clear()
    first = asyncio.create_task(say(ch, KAZ, "what should we play tonight"))
    await asyncio.sleep(0.1)
    await say(ch, KAZ, "something co-op maybe")                        # would be owed a follow-up
    await say(ch, REX, "@Gomihyu mute", [ME])
    await first
    assert ch.hers() == ["reply 3", "reply 4"] and len(calls) == 1
    assert not any(line.startswith("Gomihyu: reply 5") for line in bot.history[1]) and 1 not in bot.pending_followup
    await r.cleanup(); print("MUTE TESTS PASSED")
asyncio.run(main())
