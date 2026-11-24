import os as _os; REPO, TMP = _os.environ["GOMI_REPO"], _os.environ["GOMI_TMP"]  # set by tests/run_all.sh
# Reading the room: one call per post not aimed at her gives a read, an interest and a fitting reaction.
import asyncio, io, itertools, json, os, sys, time, types, logging
from pathlib import Path
from contextlib import asynccontextmanager
from aiohttp import web
from PIL import Image
T = Path(os.environ["CHAT_LOG_DIR"]).parent
os.environ.update(DISCORD_BOT_TOKEN="fake", OLLAMA_URL="http://127.0.0.1:8761/api/chat", PEOPLE_FILE=str(T / "people.json"))
sys.path.insert(0, REPO)
from gomi import bot, chime
from gomi.emojis import UNICODE
logging.getLogger("aiohttp.access").setLevel(logging.WARNING)
bot.examples = []; bot.CHIME_IN_THRESHOLD = 6; bot.REACT_ONLY_MAX_WORDS = 2
assert bot.REACT_TO_CHAT is True and bot.REACT_THRESHOLD == 8 and {"🥺", "😳", "💀"} <= set(UNICODE)
NS = types.SimpleNamespace

# --- parsing and the prompt
opts = {"🥺": "cute", "🙄": "eye-roll", "kekpoint": "fail"}
R = chime.parse_room
assert R('{"read": "  rex  shows his cat ", "interest": 3, "react": 9, "emoji": "🥺"}', opts) == ("rex shows his cat", 3, 9, "🥺")
assert R('{"interest": 3, "react": 14}', opts).react == 10 and R('{"react": "high"}', opts).react is None
assert R('{"react": 7.6, "emoji": "🥺"}', opts)[2:] == (8, "🥺") and R('{"react": true}', opts).react is None
assert R('{"read": "x", "interest": 3, "emoji": "none"}', opts).emoji is None
assert R('{"read": "x", "interest": 3, "emoji": "👑"}', opts).emoji is None          # not an option now
assert R('{"emoji": "kekpoint"}', opts) == ("", None, None, "kekpoint") and R("kekpoint", opts) == ("", None, None, "kekpoint")
assert R("nope", opts) is None and R("[1]", opts) is None and R('{"interest": "high"}', opts) == ("", None, None, None)
assert len(R(json.dumps({"read": "y" * 500}), opts).read) == 150
f = chime.room_format(opts)
assert f["properties"]["emoji"]["enum"] == ["🥺", "🙄", "kekpoint", "none"] and f["required"] == ["read", "interest", "react", "emoji"]
assert f["properties"]["react"] == {"type": "integer", "minimum": 0, "maximum": 10} == f["properties"]["interest"]
m = chime.room_messages(["kaz0: look at my cat [image: a fluffy cat]"], opts, ["lowercase bursts", "lots of lmao"],
                        "kaz0", "rexmode", ["🙄"])
assert "secretly soft: cute things and kindness fluster her" in m[0]["content"]
assert "How people in this server talk: lowercase bursts / lots of lmao" in m[0]["content"]
u = m[1]["content"]
assert "kaz0: look at my cat [image: a fluffy cat]\n\nThe last message is from kaz0, replying to rexmode." in u
assert "She just reacted with 🙄, so not those again." in u and "- 🥺: cute" in u and "- none: no reaction" in u
assert "not just her usual attitude" in u
assert "3. react: how much it gets a reaction out of her, from 0 to 10. A different question from interest" in u
assert "0-2: everyday chatter, logistics, questions, plans" in u and "8-10: it really gets a rise out of her" in u
assert u.index("2. interest") < u.index("3. react") < u.index("4. emoji") and '"react": <0-10>' in u
assert "most messages get no reaction at all" in m[0]["content"]

# --- the bot
PIC = io.BytesIO(); Image.new("RGB", (40, 40), (200, 200, 200)).save(PIC, "PNG")
calls, room = [], {"answer": None}
async def handler(request):
    if request.method == "GET":
        return web.Response(body=PIC.getvalue(), content_type="image/png")
    body = await request.json(); calls.append(body)
    last = body["messages"][-1]
    if last.get("images"):
        return web.json_response({"message": {"content": "A fluffy grey cat looking up"}, "done_reason": "stop"})
    if "interest" in body.get("format", {}).get("properties", {}):
        enum = body["format"]["properties"]["emoji"]["enum"]
        return web.json_response({"message": {"content": room["answer"](enum, last["content"])}, "done_reason": "stop"})
    return web.json_response({"message": {"content": "a reply"}, "done_reason": "stop"})
rooms = lambda: [c for c in calls if "interest" in c.get("format", {}).get("properties", {})]
replies = lambda: [c for c in calls if "format" not in c and not c["messages"][-1].get("images")]
ME = NS(id=1, name="Gomihyu", display_name="Gomihyu", bot=True); bot.client._connection.user = ME
KAZ = NS(id=6, name="kaz0", display_name="Kaz", bot=False); REX = NS(id=5, name="rexmode", display_name="REX", bot=False)
ids = itertools.count(1000)
class Post:
    def __init__(self, ch, author, content, attachments=(), reference=None):
        self.id, self.channel, self.author, self.content, self.guild = next(ids), ch, author, content, ch.guild
        self.attachments, self.stickers, self.embeds, self.reference = list(attachments), [], [], reference
        self.mentions, self.role_mentions, self.channel_mentions, self.reactions = [], [], [], []
    async def add_reaction(self, emoji): self.reactions.append(emoji)
class Channel:
    def __init__(self, i): self.id, self.name, self.guild, self.sent = i, "general", NS(emojis=[]), []
    @asynccontextmanager
    async def typing(self): yield
    async def send(self, text): self.sent.append(text); return NS(id=next(ids))
async def say(ch, author, content, **kw):
    post = Post(ch, author, content, **kw); await bot.on_message(post); return post
answer = lambda read, interest, emoji, react=9: lambda enum, content: json.dumps({"read": read, "interest": interest,
                                                                                    "react": react, "emoji": emoji})

async def main():
    app = web.Application(); app.router.add_route("*", "/{tail:.*}", handler)
    runner = web.AppRunner(app); await runner.setup(); await web.TCPSite(runner, "127.0.0.1", 8761).start()
    ch = Channel(1)

    # a cat picture on its own: she sees it and reacts to what's in it, from the one read
    room["answer"] = answer("rex shows off his cat", 2, "🥺"); calls.clear()
    post = await say(ch, REX, "", attachments=[NS(content_type="image/png", url="http://127.0.0.1:8761/cat.png")])
    assert post.reactions == ["🥺"] and len(rooms()) == 1 and not replies()
    assert "rexmode: [image: A fluffy grey cat looking up]" in rooms()[0]["messages"][1]["content"]

    # no 🙄🙄🙄: her last two picks are taken out of the options
    room["answer"] = lambda enum, content: json.dumps({"read": "x", "interest": 1, "react": 8,
                                                       "emoji": "🙄" if "🙄" in enum else enum[0]})
    got = []
    for text in ("lol", "lmao ok", "bruh"):
        calls.clear(); post = await say(ch, KAZ, text); got.append(post.reactions[0])
        enum = rooms()[0]["format"]["properties"]["emoji"]["enum"]
        assert all(e not in enum for e in got[-3:-1]), (got, enum)
    assert got[0] == "🙄" and got[1] != "🙄" and got[2] not in got[:2], got
    assert "She just reacted with" in rooms()[0]["messages"][1]["content"]

    # a post she doesn't answer can still get a reaction; one she answers gets the reply, not a reaction
    bot.recent_reactions.clear()                                        # (the loop above used 🔥 last)
    room["answer"] = answer("kaz got the job", 3, "🔥"); calls.clear()
    post = await say(ch, KAZ, "just got the job offer from nintendo")
    assert post.reactions == ["🔥"] and not replies() and ch.sent == []
    room["answer"] = answer("a question for everyone", 9, "👀", react=3); calls.clear()
    post = await say(ch, KAZ, "what should we play this weekend")
    assert post.reactions == [] and ch.sent == ["a reply"] and len(rooms()) == 1
    room["answer"] = answer("chatter", 2, "none"); calls.clear()
    post = await say(ch, REX, "ok i'll grab the charger then"); assert post.reactions == [] and ch.sent == ["a reply"]
    bot.REACT_TO_CHAT = False; room["answer"] = answer("kaz flexes", 3, "🔥"); calls.clear()
    post = await say(ch, KAZ, "just hit diamond rank finally"); assert post.reactions == [] and not replies()
    bot.REACT_TO_CHAT = True

    # the read knows who a Discord reply is to, and the server's vibe
    bot.diary.set_vibe(["everyone types in lowercase"], "2026-09-29")
    room["answer"] = answer("x", 1, "none"); calls.clear()
    target = Post(ch, REX, "nobody asked")
    await say(ch, KAZ, "you did though, twice", reference=NS(resolved=target, message_id=target.id))
    u = rooms()[0]
    assert "The last message is from kaz0, replying to rexmode." in u["messages"][1]["content"]
    assert "How people in this server talk: everyone types in lowercase" in u["messages"][0]["content"]

    # echoing an emoji-only post keeps working, even several times in a row
    room["answer"] = answer("x", 0, "same")
    for _ in range(3):
        post = await say(ch, KAZ, "💀"); assert post.reactions == ["💀"], post.reactions

    # an answer she can't use: no reaction, no reply
    room["answer"] = lambda enum, content: "garbage"; calls.clear()
    post = await say(ch, KAZ, "anyway what is everyone eating"); assert post.reactions == [] and not replies()
    post = await say(ch, KAZ, "lol"); assert post.reactions == []

    # quiet mode: no read for chat, but posts that only need a reaction still get one
    bot.quiet_until[1] = time.monotonic() + 600; bot.recent_reactions.clear(); room["answer"] = answer("x", 9, "🔥"); calls.clear()
    post = await say(ch, KAZ, "big news everyone, i passed my exam"); assert not rooms() and post.reactions == []
    post = await say(ch, KAZ, "lets gooo"); assert post.reactions == ["🔥"] and len(rooms()) == 1
    bot.quiet_until.clear()

    # she only reacts to what gets a rise out of her: react >= REACT_THRESHOLD (8), whatever the interest
    bot.recent_reactions.clear(); ch3 = Channel(3)
    room["answer"] = answer("a meh cat pic", 1, "🥺", react=6); calls.clear()
    post = await say(ch3, REX, "", attachments=[NS(content_type="image/png", url="http://127.0.0.1:8761/cat.png")])
    assert post.reactions == [] and len(rooms()) == 1 and not replies()      # a picture below 8: nothing at all
    room["answer"] = answer("rex's cat in a tiny hat", 1, "🥺", react=8); calls.clear()
    post = await say(ch3, REX, "", attachments=[NS(content_type="image/png", url="http://127.0.0.1:8761/hat.png")])
    assert post.reactions == ["🥺"]
    for react, want in [(7, []), (10, ["💀"])]:                              # chat she doesn't answer
        room["answer"] = answer("kaz roasting rex", 4, "💀", react=react); calls.clear()
        post = await say(ch3, KAZ, f"rex really said that with his whole chest {react}")
        assert post.reactions == want and not replies(), (react, post.reactions)
    room["answer"] = answer("x", 2, "💀", react=None); calls.clear()        # no score said: no reaction
    post = await say(ch3, KAZ, "lmaooo"); assert post.reactions == []
    room["answer"] = lambda enum, content: "💀"; calls.clear()               # not JSON, just an emoji: no score either
    post = await say(ch3, KAZ, "ok"); assert post.reactions == []
    room["answer"] = answer("x", 0, "same", react=5)                          # echoing too
    post = await say(ch3, KAZ, "🔥"); assert post.reactions == []
    room["answer"] = answer("x", 0, "none", react=10)                         # moved, but nothing fits
    post = await say(ch3, KAZ, "wow"); assert post.reactions == []
    # one she chimes in on: the reply AND the reaction, if it got a rise out of her (REACT_WHEN_REPLYING)
    assert bot.REACT_WHEN_REPLYING is True
    room["answer"] = answer("rex calls her AI dumb, she's insulted", 9, "💢", react=10); calls.clear()
    post = await say(ch3, REX, "been feeding it my old vods but the ai is still kinda dumb")
    assert post.reactions == ["💢"] and ch3.sent == ["a reply"] and len(rooms()) == 1
    room["answer"] = answer("big question", 9, "👀", react=7); calls.clear()
    post = await say(ch3, KAZ, "wait who's hosting friday then")
    assert post.reactions == [] and ch3.sent == ["a reply"] * 2
    bot.REACT_WHEN_REPLYING = False
    room["answer"] = answer("huge flex", 9, "🔥", react=10); calls.clear()
    post = await say(ch3, KAZ, "i just went 10-0 in ranked")
    assert post.reactions == [] and ch3.sent == ["a reply"] * 3
    bot.REACT_WHEN_REPLYING = True
    def mute_while_reading(enum, content):                               # muted while she reads: nothing
        bot.muted_until[3] = time.monotonic() + 600
        return answer("huge flex", 9, "🔥", react=10)(enum, content)
    room["answer"] = mute_while_reading
    post = await say(ch3, KAZ, "no seriously 10-0")
    assert post.reactions == [] and ch3.sent == ["a reply"] * 3
    bot.muted_until.clear()
    room["answer"] = answer("x", 4, "🔥", react=10)
    post = await say(ch3, KAZ, "no seriously 10-0 again"); assert post.reactions == ["🔥"]  # not chiming in: reacts
    bot.muted_until[3] = time.monotonic() + 600
    post = await say(ch3, KAZ, "no seriously 10-0 thrice"); assert post.reactions == []   # muted: no read at all
    bot.muted_until.clear(); bot.recent_reactions.clear()
    bot.REACT_THRESHOLD = 0; bot.recent_reactions.clear()                     # 0: whenever one fits
    room["answer"] = answer("x", 2, "🙄", react=1); calls.clear()
    post = await say(ch3, KAZ, "ok whatever"); assert post.reactions == ["🙄"]
    room["answer"] = answer("x", 2, "none", react=1)
    post = await say(ch3, KAZ, "sure"); assert post.reactions == []
    bot.REACT_THRESHOLD = 8
    await runner.cleanup(); print("REACTION TESTS PASSED")
asyncio.run(main())
