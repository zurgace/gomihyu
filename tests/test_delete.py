import os as _os; REPO, TMP = _os.environ["GOMI_REPO"], _os.environ["GOMI_TMP"]  # set by tests/run_all.sh
# The owner can make her delete her posts: code, not the model, handles it.
import asyncio, itertools, os, sys, types, logging
from contextlib import asynccontextmanager
from aiohttp import web
SP = TMP
os.environ.update(DISCORD_BOT_TOKEN="fake", OLLAMA_URL="http://127.0.0.1:8770/api/chat", PEOPLE_FILE=f"{SP}/people_delete.json",
                  OWNER_USER_IDS="111, 222")
sys.path.insert(0, REPO)
import discord, bot
logging.getLogger("aiohttp.access").setLevel(logging.WARNING)
bot.REACT_ONLY_MAX_WORDS = 0; bot.CHIME_IN_THRESHOLD = 0; bot.examples = []
assert bot.OWNER_USER_IDS == {111, 222} and bot.owner_ids == {111, 222}

from commands import delete_request as d, ALL
cases = {
    "gomi delete that": 1, "@Gomihyu delete it": 1, "gomi del": 1, "gomi delete pls": 1, "delete this": 1,
    "gomi delete that message": 1, "gomi delete your last message": 1, "gomi delete ur last msg": 1,
    "gomi delete your last 3 messages": 3, "gomi delete your last three posts": 3, "gomi DELETE YOUR LAST 2 MSGS": 2,
    "gomi delete all your messages": ALL, "gomi delete all of your posts": ALL, "gomi delete those": ALL,
    "gomi delete everything": ALL, "gomi delete your messages": ALL, "gomi delete them": ALL, "gomi delete all": ALL,
    "gomi unsend that": 1, "gomi erase that": 1, "gomi can you delete that": 1, "gomi could you delete that pls": 1,
    "gomi i want you to delete that": 1, "gomi you should delete that": 1, "idk gomi, delete that": 1,
    "gomi don't delete that": None, "gomi dont delete that": None, "gomi do not delete it": None, "gomi don’t delete that": None,
    "gomi should i delete my account": None, "gomi how do you delete a server": None, "gomi i deleted it already": None,
    "gomi delete the chat history lol": None, "gomi delete your last 0 messages": None, "gomi what does delete do": None,
    "gomi delete my message": None, "gomi i'll delete that later": None, "gomi im gonna delete it": None,
    "gomi i will delete that": None, "gomi let me delete that": None, "gomi we should delete that": None,
}
assert not (bad := {t: (d(t), want) for t, want in cases.items() if d(t) != want}), bad

calls, replies = [], itertools.count(1)
async def fake(request):
    calls.append(await request.json()); return web.json_response({"message": {"content": f"reply {next(replies)}"}, "done_reason": "stop"})
ME = types.SimpleNamespace(id=1, name="Gomihyu", display_name="Gomihyu", bot=True); bot.client._connection.user = ME
REX = types.SimpleNamespace(id=5, name="rexmode", display_name="REX MODE", bot=False)
KAZ = types.SimpleNamespace(id=6, name="kaz0", display_name="Kaz", bot=False)
ids = itertools.count(1000)
resp = lambda status: types.SimpleNamespace(status=status, reason="nope")

class Post:
    def __init__(self, ch, author, content, mentions=(), reference=None):
        self.id, self.channel, self.author, self.content, self.guild = next(ids), ch, author, content, None
        self.mentions, self.reference, self.reactions = list(mentions), reference, []
        self.role_mentions = self.channel_mentions = self.attachments = self.stickers = []
        self.fail = None
    async def delete(self):
        if self.fail: raise self.fail
        if self not in self.channel.posts: raise discord.NotFound(resp(404), "Unknown Message")
        self.channel.posts.remove(self)
    async def add_reaction(self, emoji): self.reactions.append(emoji)
class Channel:
    def __init__(self, i): self.id, self.guild, self.posts, self.history_fails = i, None, [], False
    @asynccontextmanager
    async def typing(self): yield
    async def send(self, text):
        post = Post(self, ME, text); self.posts.append(post); return post
    async def history(self, limit):
        if self.history_fails: raise discord.Forbidden(resp(403), "Missing Access")
        for post in reversed(self.posts[-limit:]): yield post
    def hers(self): return [p.content for p in self.posts if p.author is ME]

async def say(ch, author, content, mentions=(), reply_to=None):
    post = Post(ch, author, content, mentions, types.SimpleNamespace(resolved=reply_to) if reply_to else None)
    ch.posts.append(post); await bot.on_message(post); return post

async def main():
    app = web.Application(); app.router.add_post("/api/chat", fake)
    r = web.AppRunner(app); await r.setup(); await web.TCPSite(r, "127.0.0.1", 8770).start()

    # the application's owner is looked up at login (a person, or a team's members); a failed lookup is survivable
    async def info_owner(): return types.SimpleNamespace(team=None, owner=REX)
    bot.client.application_info = info_owner; await bot.on_ready()
    assert bot.owner_ids == {111, 222, 5}
    async def info_team(): return types.SimpleNamespace(team=types.SimpleNamespace(members=[types.SimpleNamespace(id=7, name="a"), types.SimpleNamespace(id=8, name="b")]), owner=None)
    bot.client.application_info = info_team; await bot.on_ready()
    assert {7, 8} <= bot.owner_ids
    async def info_fails(): raise discord.HTTPException(resp(500), "down")
    bot.client.application_info = info_fails; await bot.on_ready()
    bot.owner_ids.clear(); bot.owner_ids.add(REX.id)

    ch = Channel(1)
    for who, text in [(KAZ, "morning all"), (REX, "what's up"), (KAZ, "nm, you?")]:
        await say(ch, who, text)
    assert ch.hers() == ["reply 1", "reply 2", "reply 3"] and len(bot.posted) == 3

    # "gomi delete that": her newest post goes; 🗑️ on the command; no model call; the command and the post leave her log
    calls.clear()
    cmd = await say(ch, REX, "gomi delete that")
    assert ch.hers() == ["reply 1", "reply 2"] and cmd.reactions == ["🗑️"] and calls == []
    log = list(bot.history[1])
    assert "Gomihyu: reply 3" not in log and not any("delete" in line for line in log) and "Gomihyu: reply 2" in log, log

    # a Discord reply to one of her posts saying just "delete": that post, not her newest
    first = next(p for p in ch.posts if p.content == "reply 1")
    cmd = await say(ch, REX, "delete", reply_to=first)
    assert ch.hers() == ["reply 2"] and cmd.reactions == ["🗑️"] and "Gomihyu: reply 1" not in bot.history[1]

    # "last N" skips other people's posts; an @mention works like her name
    for text in ["one", "two", "three"]:
        await say(ch, KAZ, text)
    assert ch.hers() == ["reply 2", "reply 4", "reply 5", "reply 6"]
    await say(ch, REX, "<@1> delete your last 2 messages", [ME])
    assert ch.hers() == ["reply 2", "reply 4"]
    await say(ch, REX, "gomi delete all your messages")
    assert ch.hers() == [] and not any(line.startswith("Gomihyu:") for line in bot.history[1])
    cmd = await say(ch, REX, "gomi delete that")
    assert cmd.reactions == ["🤷"]                                     # nothing left of hers

    # not a command: someone else asking, not aimed at her, or "don't": a normal chat message
    await say(ch, KAZ, "hi")                                           # she posts "reply 7"
    for who, text in [(KAZ, "gomi delete that"), (REX, "delete that"), (REX, "gomi don't delete that"),
                      (REX, "gomi i'll delete that later")]:
        calls.clear(); n = len(ch.hers())
        await say(ch, who, text)
        assert len(ch.hers()) == n + 1 and len(calls) == 1, text      # replied, deleted nothing
        assert f"{who.name}: {text}" in bot.history[1]

    # a post that's already gone counts as deleted; one Discord won't delete is skipped; so is a failed lookup
    ch2 = Channel(2); await say(ch2, KAZ, "yo"); await say(ch2, KAZ, "yo2")
    old, new = [p for p in ch2.posts if p.author is ME]
    new.fail = discord.NotFound(resp(404), "Unknown Message")         # someone else removed it already
    cmd = await say(ch2, REX, "gomi delete your last message")
    assert cmd.reactions == ["🗑️"]
    ch2.posts.remove(new)                                               # (really gone, so the channel no longer lists it)
    old.fail = discord.Forbidden(resp(403), "Missing Permissions")
    cmd = await say(ch2, REX, "gomi delete everything")
    assert cmd.reactions == ["🤷"] and old in ch2.posts
    ch2.history_fails = True
    cmd = await say(ch2, REX, "gomi delete that")
    assert cmd.reactions == ["🤷"]
    await r.cleanup(); print("DELETE TESTS PASSED")
asyncio.run(main())
