import os as _os; REPO, TMP = _os.environ["GOMI_REPO"], _os.environ["GOMI_TMP"]  # set by tests/run_all.sh
import asyncio, json, os, sys, types, logging
from contextlib import asynccontextmanager
from aiohttp import web
SP = TMP
os.environ.update(DISCORD_BOT_TOKEN="fake", OLLAMA_URL="http://127.0.0.1:8771/api/chat", PEOPLE_FILE=f"{SP}/people_emo.json")
sys.path.insert(0, REPO)
from gomi.reactions import reacts_instead as ri, media_only, posted_emoji
from gomi.chime import room_format as picker_format
logging.getLogger("aiohttp.access").setLevel(logging.WARNING)

# --- when a reaction replaces a reply (max 2 words) ---
for text in ["oogaga", "lol wtf", "Live", "[image]", "[sticker: wave]", ":pleasee:", "🤏", "💀💀💀", "??",
             "https://tenor.com/view/cat-crying-gif-12345", "lol :200:", "[image] lol"]:
    assert ri(text, 2), text
for text in ["it knows WTF", "say something else", "gomi lol", "gomi' brain = 🤏", "Gomihyu lol", "why tho?",
             "grandma died", "rough day", "Which sushi should I get as a beginner"]:
    assert not ri(text, 2), text
assert not ri("oogaga", 0) and ri("[image]", 0)
# --- media only (she just looks) ---
assert media_only("[image]") and media_only("[video] [image]") and media_only("[sticker: wave]")
assert media_only("https://tenor.com/view/x-123")
assert not media_only("[image] lol") and not media_only("[image] 😂") and not media_only(":pleasee:") and not media_only("lol")
# --- emoji-only posts: what "the same" would be ---
assert posted_emoji(":pleasee:") == ":pleasee:" and posted_emoji("💀💀") == "💀" and posted_emoji("🤏") == "🤏"
assert posted_emoji("👍🏽") == "👍🏽" and posted_emoji("👨‍👩‍👧 lmao") is None and posted_emoji("👨‍👩‍👧") == "👨‍👩‍👧"
assert posted_emoji("🇯🇵") == "🇯🇵" and posted_emoji("❤️") == "❤️"
assert posted_emoji("lol 💀") is None and posted_emoji("[image] 💀") is None and posted_emoji("") is None
assert picker_format({"😤": "x", "kekpoint": "y"})["properties"]["emoji"]["enum"] == ["😤", "kekpoint", "none"]

from gomi import bot, persona
bot.CHIME_IN_THRESHOLD = 0; bot.VISION = False  # these are the text-only paths; test_vision.py has the rest
from gomi.emojis import UNICODE
# the chat prompt lists in-text emojis only
assert ":kekpoint: (laughing at someone's fail)" in persona.SYSTEM_PROMPT
assert "aryanosaka" not in persona.SYSTEM_PROMPT and "goonerstare" not in persona.SYSTEM_PROMPT

class Emoji:
    def __init__(self, name, id): self.name, self.id = name, id
    def __str__(self): return f"<:{self.name}:{self.id}>"
    __repr__ = __str__
# a server that has most of the emojis, but not DoWar or goonerstare, plus one not in emojis.py
SERVER = types.SimpleNamespace(emojis=[Emoji(n, 100 + i) for i, n in enumerate(
    ["kekpoint", "200", "deadge", "pleasee", "AIEEEE", "catsad", "aryanosaka", "randomserveremoji"])])
E = {e.name: e for e in SERVER.emojis}

picker_answer, reply_text, calls = {"v": None}, {"v": None}, []
async def fake(request):
    body = await request.json(); calls.append(body)
    content = picker_answer["v"] if "format" in body else reply_text["v"]
    return web.json_response({"message": {"content": content}, "done_reason": "stop"})

ME = types.SimpleNamespace(id=1, name="Gomihyu", display_name="Gomihyu", bot=True); bot.client._connection.user = ME
KAZ = types.SimpleNamespace(id=7, name="kaz0", display_name="Kaz", bot=False)
class Channel:
    def __init__(self, cid, guild=SERVER): self.id, self.guild, self.sent = cid, guild, []
    @asynccontextmanager
    async def typing(self): yield
    async def send(self, text): self.sent.append(text)
class Att:
    def __init__(self, ct): self.content_type = ct
class Msg:
    def __init__(self, channel, content, mentions=(), attachments=(), stickers=()):
        self.id, self.author, self.channel, self.guild, self.content = id(self), KAZ, channel, channel.guild, content
        self.mentions, self.role_mentions, self.channel_mentions = list(mentions), [], []
        self.attachments, self.stickers, self.reactions = list(attachments), list(stickers), []
    async def add_reaction(self, emoji): self.reactions.append(emoji)

async def send(content, **kw):
    c = Channel(len(calls) * 10 + 1000 + len(kw)); m = Msg(c, content, **kw); calls.clear()
    await bot.on_message(m); return m, c

async def main():
    app = web.Application(); app.router.add_post("/api/chat", fake)
    r = web.AppRunner(app); await r.setup(); await web.TCPSite(r, "127.0.0.1", 8771).start()

    # readable(): custom emoji tokens, attachments and stickers
    m = Msg(Channel(1), "look <:pleasee:103> <a:dance:9>", attachments=[Att("image/png"), Att("video/mp4"), Att(None)],
            stickers=[types.SimpleNamespace(name="wave")])
    assert bot.readable(m) == "look :pleasee: :dance: [image] [video] [file] [sticker: wave]", bot.readable(m)
    assert bot.readable(Msg(Channel(1), "", attachments=[Att("image/jpeg")])) == "[image]"

    # image-only post: a "looking" reaction, no model call, no reply; goonerstare isn't on this server -> 👀
    m, c = await send("", attachments=[Att("image/png")])
    assert m.reactions == ["👀"] and c.sent == [] and calls == []
    assert list(bot.history[c.id]) == ["kaz0: [image]"]                  # in the log, as [image]
    # on a server that has goonerstare, it's one of the two
    looks = set()
    for _ in range(40):
        g = types.SimpleNamespace(emojis=[Emoji("goonerstare", 555)])
        mm = Msg(Channel(2, g), "", attachments=[Att("image/png")]); await bot.on_message(mm); looks.add(str(mm.reactions[0]))
    assert looks == {"👀", "<:goonerstare:555>"}, looks

    # short interjection: the picker chooses; options = unicode + custom emojis this server has
    picker_answer["v"] = '{"emoji": "kekpoint", "react": 9}'
    m, c = await send("oogaga")
    assert m.reactions == [E["kekpoint"]] and c.sent == [] and len(calls) == 1
    enum = calls[0]["format"]["properties"]["emoji"]["enum"]
    assert set(enum) == set(UNICODE) | {"kekpoint", "200", "deadge", "pleasee", "AIEEEE", "catsad", "aryanosaka", "none"}, enum
    assert "DoWar" not in enum and "randomserveremoji" not in enum and "same" not in enum
    assert "kaz0: oogaga" in calls[0]["messages"][1]["content"]

    # emoji-only posts can get the same emoji back
    picker_answer["v"] = '{"emoji": "same", "react": 9}'
    m, _ = await send("<:pleasee:103>"); assert m.reactions == [E["pleasee"]]
    m, _ = await send("💀"); assert m.reactions == ["💀"]
    m, _ = await send("<:randomserveremoji:107>"); assert m.reactions == [E["randomserveremoji"]]   # any emoji of this server
    m, _ = await send("<:fromanotherserver:999>")                         # can't mirror what it can't use
    assert "same" not in calls[0]["format"]["properties"]["emoji"]["enum"] and m.reactions == []
    picker_answer["v"] = '{"emoji": "same", "react": 9}'
    m, _ = await send("oogaga"); assert m.reactions == []                  # "same" with nothing posted: ignored

    # none / garbage / JSON not honored
    for answer, want in [('{"emoji": "none"}', []), ("lol idk", []), ('{"nope": 1}', []), ("[1, 2]", []), ('{"emoji": ["kekpoint"]}', []),
                         ("kekpoint", []), ('"😤"', []), ('{"emoji": "DoWar", "react": 9}', []),  # not JSON: no react score
                         ('{"emoji": "kekpoint", "react": 7}', []), ('{"emoji": "kekpoint", "react": 8}', [E["kekpoint"]])]:
        picker_answer["v"] = answer
        m, c = await send("oogaga"); assert m.reactions == want and c.sent == [], (answer, m.reactions)

    # these get a reply, not a reaction
    reply_text["v"] = "hmph"
    for text, kw in [("<@1> lol", {"mentions": [ME]}), ("gomi lol", {}), ("it knows WTF", {}), ("why?", {})]:
        m, c = await send(text, **kw)
        assert c.sent == ["hmph"] and m.reactions == [] and not any("format" in x for x in calls), text

    # sad news: a reply AND a sad cat, whatever its length and even when @mentioned; laughter isn't sad news
    for text, kw in [("grandma died", {}), ("<@1> my dog died last night", {"mentions": [ME]}),
                     ("rough week ngl", {}), ("i'm so sad", {})]:
        m, c = await send(text, **kw)
        assert c.sent == ["hmph"] and m.reactions == [E["catsad"]], (text, m.reactions)
    for text in ["im crying lmao", "crying 😂", "i died lol", "cried laughing haha"]:
        m, c = await send(text); assert E["catsad"] not in m.reactions, text
    m, c = await send("https://tenor.com/view/cat-crying-gif-123"); assert m.reactions == ["👀"] and c.sent == []
    nocat = Channel(5, types.SimpleNamespace(emojis=[])); mm = Msg(nocat, "grandma died"); await bot.on_message(mm)
    assert mm.reactions == [] and nocat.sent == ["hmph"]              # no catsad on the server: just the reply

    # custom emojis in her reply become the real thing; reaction-only / unknown ones stay text
    said = "AGAIN?? :kekpoint: and :Kekpoint: but :aryanosaka: :DoWar: :nothere: 10:30:45"
    assert bot.to_server_emojis(said, SERVER) == "AGAIN?? <:kekpoint:100> and <:kekpoint:100> but :aryanosaka: :DoWar: :nothere: 10:30:45"
    # a reply keeps one of them (shape.py): the last she can post
    reply_text["v"] = said
    m, c = await send("i failed my driving test again")
    assert c.sent == ["AGAIN?? and but :DoWar: 10:30:45"], c.sent       # DoWar isn't on this server: stays text
    reply_text["v"] = "AGAIN?? :kekpoint: third time's the charm"
    await bot.on_message(Msg(c, "i failed my driving test again"))
    assert c.sent[-1] == "AGAIN?? third time's the charm", c.sent    # her last message there had one
    c = Channel(77); await bot.on_message(Msg(c, "i failed my driving test again"))
    assert c.sent == ["AGAIN?? <:kekpoint:100> third time's the charm"], c.sent
    assert list(bot.history[c.id])[-1] == "Gomihyu: " + reply_text["v"]  # the log keeps :name:
    c2 = Channel(3, guild=None); await bot.on_message(Msg(c2, "no guild here at all")); assert c2.sent == [reply_text["v"]]

    # A reaction-only post doesn't cause a follow-up. Required answers still deliver, while an
    # unsolicited draft is invalidated by every new observation, independent of scheduling.
    started, release = asyncio.Event(), asyncio.Event()
    async def slow(request):
        body = await request.json(); calls.append(body)
        if "format" not in body:
            started.set(); await release.wait()
        return web.json_response({"message": {"content": '{"emoji": "200", "react": 9}' if "format" in body else "done"}})
    app2 = web.Application(); app2.router.add_post("/api/chat", slow)
    r2 = web.AppRunner(app2); await r2.setup(); await web.TCPSite(r2, "127.0.0.1", 8772).start()
    bot.OLLAMA_URL = "http://127.0.0.1:8772/api/chat"; calls.clear()
    c = Channel(4); first = asyncio.create_task(bot.on_message(Msg(c, "gomi tell me something good")))
    await asyncio.wait_for(started.wait(), 3)
    lol = Msg(c, "lmao"); await bot.on_message(lol); release.set(); await first
    assert c.sent == ["done"] and lol.reactions == [E["200"]] and sum("format" not in x for x in calls) == 1
    assert list(bot.history[4]) == ["kaz0: gomi tell me something good", "Gomihyu: done", "kaz0: lmao"]
    calls.clear(); started.clear(); release.clear()
    c = Channel(404); first = asyncio.create_task(bot.on_message(Msg(c, "tell me something good")))
    await asyncio.wait_for(started.wait(), 3)
    lol = Msg(c, "lmao"); await bot.on_message(lol); release.set(); await first
    assert not c.sent and lol.reactions == [E["200"]] and sum("format" not in x for x in calls) == 1
    assert list(bot.history[404]) == ["kaz0: tell me something good", "kaz0: lmao"]

    # Ollama down: no reaction, no crash
    bot.OLLAMA_URL = "http://127.0.0.1:1/api/chat"; m, c = await send("oogaga"); assert m.reactions == [] and c.sent == []
    await r.cleanup(); await r2.cleanup(); print("EMOJI TESTS PASSED")
asyncio.run(main())
