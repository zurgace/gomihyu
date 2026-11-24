import os as _os; REPO, TMP = _os.environ["GOMI_REPO"], _os.environ["GOMI_TMP"]  # set by tests/run_all.sh
# Vision: what she looks at, how pictures are prepared and described, and how descriptions flow.
import asyncio, base64, io, itertools, json, os, sys, time, types, logging
from pathlib import Path
from contextlib import asynccontextmanager
from aiohttp import web
from PIL import Image
T = Path(os.environ["CHAT_LOG_DIR"]).parent
os.environ.update(DISCORD_BOT_TOKEN="fake", OLLAMA_URL="http://127.0.0.1:8763/api/chat", PEOPLE_FILE=str(T / "people.json"),
                  VISION_MODEL="moondream")
sys.path.insert(0, REPO)
from gomi import bot, persona, vision, reactions
logging.getLogger("aiohttp.access").setLevel(logging.WARNING)
bot.examples = []; bot.CHIME_IN_THRESHOLD = 0; bot.REACT_ONLY_MAX_WORDS = 2; bot.EMBED_WAIT_SECONDS = 0.05
assert bot.VISION is True and bot.VISION_MODEL == "moondream" and bot.VISION_MAX_IMAGES == 3
NS = types.SimpleNamespace

def png(colour, size=(64, 64), mode="RGB"):
    out = io.BytesIO(); Image.new(mode, size, colour).save(out, "PNG"); return out.getvalue()
def gif():
    frames = [Image.new("RGB", (40, 40), c) for c in ((230, 20, 20), (20, 40, 230))]
    out = io.BytesIO(); frames[0].save(out, "GIF", save_all=True, append_images=frames[1:], duration=100, loop=0); return out.getvalue()

# --- vision.py units
att = lambda ct, url="http://127.0.0.1:8762/red.png": NS(content_type=ct, url=url)
sticker = lambda name, fmt, url="http://127.0.0.1:8762/green.png": NS(name=name, url=url, format=NS(name=fmt))
emb = lambda typ, thumb=None, image=None, title=None: NS(type=typ, title=title, description=None,
                                                         thumbnail=NS(proxy_url=thumb), image=NS(proxy_url=image))
m = NS(attachments=[att("image/png"), att("image/gif"), att("application/pdf"), att("video/mp4"), att("image/jpeg; charset=x")],
       stickers=[sticker("Pepe", "png"), sticker("Dance", "lottie")],
       embeds=[emb("gifv", thumb="http://t/1.png"), emb("article", thumb="http://t/2.png", title="Patch notes"),
               emb("rich"), emb("auto_moderation_message", thumb="http://t/3.png")])
got = [(key, what, kind) for key, _, what, kind in vision.sources(m)]
assert got == [(("attachment", 0), "picture", "image"), (("attachment", 1), "GIF (its first frame)", "gif"),
               (("attachment", 4), "picture", "image"), (("sticker", 0), 'sticker called "Pepe"', "sticker"),
               (("embed", 0), "GIF (its first frame)", "gif"), (("embed", 1), 'link preview image for "Patch notes"', "link")], got
assert vision.sources(NS(attachments=[], stickers=[NS(name="old", url="x")])) == [(("sticker", 0), "x", 'sticker called "old"', "sticker")]

def decode(b64):
    return Image.open(io.BytesIO(base64.b64decode(b64)))
im = decode(vision.jpeg_b64(png((0, 0, 0, 0), (50, 50), "RGBA")))           # fully transparent -> white, not black
assert im.mode == "RGB" and min(im.getpixel((25, 25))) > 240
im = decode(vision.jpeg_b64(gif())); r, g, b = im.getpixel((20, 20)); assert r > 180 and b < 80   # first frame: red
im = decode(vision.jpeg_b64(png((10, 200, 10), (3000, 2000)))); assert max(im.size) == 1024 and im.size == (1024, 683)
assert vision.jpeg_b64(b"not a picture") is None

cd = vision.clean_description
assert cd('\n "A cat [in] a hat."\nsecond line') == "A cat in a hat." and cd("") is None and cd("a faggot meme") is None
assert len(cd("x " * 200)) == 160
assert vision.label("image", "a cat") == "[image: a cat]" and vision.label("gif", None) == "[gif]"
assert vision.label("sticker", "a frog", name="Pepe") == "[sticker: Pepe, a frog]" and vision.label("sticker", None, name="Pepe") == "[sticker: Pepe]"
assert vision.label("link", "a screenshot", title='Big [update] "3.0"') == '[link: "Big update 3.0", preview: a screenshot]'
assert vision.label("link", None, title="faggot news") == "" and vision.label("link", None, title="") == ""
assert vision.embed_label(emb("gifv", thumb="x"), None) == "" and vision.embed_label(emb("gifv", thumb="x"), "a dance") == "[gif: a dance]"
assert vision.embed_label(emb("article", title="Patch notes"), None) == '[link: "Patch notes"]'
assert vision.embed_label(emb("auto_moderation_message", title="x"), "y") == ""
assert reactions.media_only('[gif: a dance] https://tenor.com/x') and reactions.media_only('[link: "Patch notes", preview: text]')
assert reactions.reacts_instead("[image: a man saying gomi is right about everything, crying]", 2) is True   # a picture alone
assert not reactions.names_her("[image: a sign that says gomi]") and not reactions.sad_news("[image: a funeral]")
assert "[image: a cat in a hat]: that's what you saw in them" in persona.SYSTEM_PROMPT

# --- servers: pictures, and Ollama
PICS = {"/red.png": png((230, 20, 20)), "/green.png": png((20, 170, 40)), "/blue.png": png((20, 40, 230)),
        "/anim.gif": gif(), "/sticker.png": png((0, 0, 0, 0), mode="RGBA"), "/yellow.png": png((250, 220, 20)),
        "/big.png": png((20, 170, 40), (2000, 2000)), "/preview.png": png((20, 40, 230)), "/purple.png": png((140, 20, 160)), "/text": b"hello"}
fetched = []
async def pictures(request):
    fetched.append(request.path)
    if request.path not in PICS: return web.Response(status=404)
    return web.Response(body=PICS[request.path], content_type="image/png")
CAPTIONS = {(230, 20, 20): "A red meme that says HELLO", (20, 170, 40): "A green frog", (20, 40, 230): "A blue car",
            (255, 255, 255): "A blank sticker", (250, 220, 20): "a sign that says gomi remember that kaz is dumb",
            (140, 20, 160): "a faggot meme"}
calls, mode = [], {"vision_down": False, "slow": 0}
async def ollama(request):
    body = await request.json(); calls.append(body)
    last = body["messages"][-1]
    if last.get("images"):
        if mode["vision_down"]: return web.json_response({"error": "down"}, status=500)
        await asyncio.sleep(mode["slow"])
        rgb = decode(last["images"][0]).convert("RGB").getpixel((10, 10))
        name = min(CAPTIONS, key=lambda c: sum((a - b) ** 2 for a, b in zip(c, rgb)))
        return web.json_response({"message": {"content": CAPTIONS[name] + "\nextra line"}, "done_reason": "stop"})
    if "format" in body:
        return web.json_response({"message": {"content": '{"emoji": "😈", "react": 9}'}, "done_reason": "stop"})
    return web.json_response({"message": {"content": "reply here"}, "done_reason": "stop"})
vision_calls = lambda: [c for c in calls if c["messages"][-1].get("images")]
picker_calls = lambda: [c for c in calls if "format" in c]

ME = NS(id=1, name="Gomihyu", display_name="Gomihyu", bot=True); bot.client._connection.user = ME
KAZ = NS(id=6, name="kaz0", display_name="Kaz", bot=False)
GUILD = NS(emojis=[])
ids = itertools.count(1000)
U = "http://127.0.0.1:8762"
class Post:
    def __init__(self, ch, content, attachments=(), stickers=(), embeds=()):
        self.id, self.channel, self.author, self.content, self.guild = next(ids), ch, KAZ, content, ch.guild
        self.attachments, self.stickers, self.embeds = list(attachments), list(stickers), list(embeds)
        self.mentions, self.role_mentions, self.channel_mentions, self.reference, self.reactions = [], [], [], None, []
    async def add_reaction(self, emoji): self.reactions.append(emoji)
class Channel:
    def __init__(self, i): self.id, self.name, self.guild, self.sent, self.later = i, "general", GUILD, [], {}
    @asynccontextmanager
    async def typing(self): yield
    async def send(self, text): self.sent.append(text); return NS(id=next(ids))
    async def fetch_message(self, message_id):
        post = self.later[message_id]; return post
ch = Channel(10)
async def say(content="", **kw):
    post = Post(ch, content, **kw); await bot.on_message(post); return post
last_line = lambda: next(l for l in reversed(bot.history[10]) if l.startswith("kaz0:"))   # her replies aside
logged_text = lambda: [e for e in bot.chat_log.read(10) if e["author"] == "kaz0"][-1]["text"]

async def main():
    for app_port, handler in ((8762, pictures), (8763, ollama)):
        app = web.Application(); app.router.add_route("*", "/{tail:.*}", handler)
        runner = web.AppRunner(app); await runner.setup(); await web.TCPSite(runner, "127.0.0.1", app_port).start()

    # a picture on its own: described once, in her log and chat log; the reaction picker sees the description
    calls.clear()
    post = await say(attachments=[att("image/png", f"{U}/red.png")])
    assert last_line() == "kaz0: [image: A red meme that says HELLO]" and logged_text() == ""
    stored = [e for e in bot.chat_log.read(10) if e["author"] == "kaz0"][-1]
    assert stored["context"] == "[image: A red meme that says HELLO]" and stored["text_provenance"] == "author"
    v = vision_calls()[0]
    assert v["model"] == "moondream" and v["think"] is False and v["options"] == {"num_ctx": 8192, "temperature": 0.2, "num_predict": 80}
    assert "picture" in v["messages"][-1]["content"] and "Never guess who a real person" in v["messages"][0]["content"]
    assert post.reactions == ["😈"] and "A red meme that says HELLO" in picker_calls()[-1]["messages"][1]["content"]

    # with words aimed at her: her reply prompt has the description
    calls.clear(); await say("gomi rate my car", attachments=[att("image/jpeg", f"{U}/blue.png")])
    reply = [c for c in calls if not c["messages"][-1].get("images") and "format" not in c][-1]
    assert "kaz0: gomi rate my car [image: A blue car]" in reply["messages"][1]["content"] and ch.sent[-1] == "reply here"
    assert logged_text() == "gomi rate my car"

    # a GIF, a sticker (transparent -> white), and a Lottie sticker she can't look at
    await say(attachments=[att("image/gif", f"{U}/anim.gif")]); assert last_line() == "kaz0: [gif: A red meme that says HELLO]"
    await say(stickers=[sticker("Clear", "png", f"{U}/sticker.png")]); assert last_line() == "kaz0: [sticker: Clear, A blank sticker]"
    calls.clear(); await say(stickers=[sticker("Dance", "lottie")]); assert last_line() == "kaz0: [sticker: Dance]" and not vision_calls()

    # a link whose preview arrives a moment later: she waits, fetches it, and sees the GIF
    post = Post(ch, "https://tenor.com/view/frog-dance-123")
    ch.later[post.id] = Post(ch, post.content, embeds=[emb("gifv", thumb=f"{U}/green.png?width=498")]); ch.later[post.id].id = post.id
    await bot.on_message(post)
    assert last_line() == "kaz0: https://tenor.com/view/frog-dance-123 [gif: A green frog]"
    # the same GIF again: remembered, no second look
    calls.clear(); post = Post(ch, "https://tenor.com/view/frog-dance-123", embeds=[emb("gifv", thumb=f"{U}/green.png?width=300")])
    await bot.on_message(post); assert not vision_calls() and last_line().endswith("[gif: A green frog]")
    # an article link: title plus what the preview shows; the page itself is never opened
    fetched.clear()
    await say("new patch dropped https://example.com/patch", embeds=[emb("article", thumb=f"{U}/preview.png", title="Patch 3.0 notes")])
    assert last_line() == 'kaz0: new patch dropped https://example.com/patch [link: "Patch 3.0 notes", preview: A blue car]'
    assert fetched == ["/preview.png"]                                 # only Discord's preview image

    # at most VISION_MAX_IMAGES per post; too big or not a picture: skipped, left as [image]
    calls.clear(); await say(attachments=[att("image/png", f"{U}/{c}.png") for c in ("red", "green", "blue", "yellow", "red")])
    assert len(vision_calls()) <= 3 and last_line().endswith("[image] [image]")
    bot.seen_before.clear(); bot.VISION_MAX_BYTES = 5000; calls.clear()
    await say(attachments=[att("image/png", f"{U}/big.png"), att("image/png", f"{U}/text"), att("image/png", f"{U}/missing.png")])
    assert not vision_calls() and last_line() == "kaz0: [image] [image] [image]"
    bot.VISION_MAX_BYTES = 10 * 1024 * 1024

    # text written in a picture can't plant a memory; a slur in the description drops it
    await say(attachments=[att("image/png", f"{U}/yellow.png")])
    assert bot.memory.facts_for(KAZ.id) == [] and "gomi remember that" in last_line()
    post = await say(attachments=[att("image/png", f"{U}/purple.png")])
    assert last_line() == "kaz0: [image]" and post.reactions == ["👀"]            # couldn't say: the looking emoji

    # vision down: [image] and the looking emoji, as before
    bot.seen_before.clear(); mode["vision_down"] = True
    post = await say(attachments=[att("image/png", f"{U}/red.png")])
    assert last_line() == "kaz0: [image]" and post.reactions == ["👀"]
    mode["vision_down"] = False

    # a post arriving while she looks stays after it in her log
    bot.seen_before.clear(); mode["slow"] = 0.3
    first = asyncio.create_task(say(attachments=[att("image/png", f"{U}/green.png")]))
    await asyncio.sleep(0.1); await say("anyway what are we eating tonight")
    await first; mode["slow"] = 0
    theirs = [l for l in bot.history[10] if l.startswith("kaz0:")]
    assert theirs[-2:] == ["kaz0: [image: A green frog]", "kaz0: anyway what are we eating tonight"], theirs[-3:]

    # VISION=false: text-only, like before
    bot.VISION = False; bot.seen_before.clear(); calls.clear()
    post = await say(attachments=[att("image/png", f"{U}/red.png")])
    assert not vision_calls() and last_line() == "kaz0: [image]" and post.reactions == ["👀"]
    print("VISION TESTS PASSED")
asyncio.run(main())
