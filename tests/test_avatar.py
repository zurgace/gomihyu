import os as _os; REPO, TMP = _os.environ["GOMI_REPO"], _os.environ["GOMI_TMP"]  # set by tests/run_all.sh
# Her own avatar: learned at login, known when someone posts it, and described in her prompts.
import asyncio, base64, io, itertools, json, os, sys, types, logging
from pathlib import Path
from contextlib import asynccontextmanager
from aiohttp import web
from PIL import Image, ImageDraw, ImageOps
T = Path(os.environ["CHAT_LOG_DIR"]).parent
os.environ.update(DISCORD_BOT_TOKEN="fake", OLLAMA_URL="http://127.0.0.1:8764/api/chat", PEOPLE_FILE=str(T / "people.json"))
os.environ.pop("AVATAR_DESCRIPTION", None)
sys.path.insert(0, REPO)
from gomi import bot, chime, persona, vision
import discord
logging.getLogger("aiohttp.access").setLevel(logging.WARNING)
bot.examples = []; bot.CHIME_IN_THRESHOLD = 6; bot.REACT_ONLY_MAX_WORDS = 2
assert bot.AVATAR_DESCRIPTION == "" and bot.avatar_description == "" and bot.VISION
NS = types.SimpleNamespace

# a cut-out like hers: a grey blob with two eyes on a transparent background (the real one is a hamster)
cutout = Image.new("RGBA", (96, 96), (0, 0, 0, 0)); d = ImageDraw.Draw(cutout)
d.ellipse((14, 18, 82, 90), fill=(120, 110, 105, 255)); d.ellipse((30, 40, 44, 54), fill=(10, 10, 10, 255))
d.ellipse((52, 40, 66, 54), fill=(10, 10, 10, 255)); d.line((28, 34, 46, 40), fill=(40, 30, 30, 255), width=3)
def enc(img, fmt="PNG", **kw):
    out = io.BytesIO(); img.save(out, fmt, **kw); return out.getvalue()
def on(bg):
    flat = Image.new("RGB", cutout.size, bg); flat.paste(cutout, mask=cutout.getchannel("A")); return flat
AVATAR = enc(cutout)
real = Path(_os.environ.get("GOMI_AVATAR_PNG", "/nonexistent"))  # the real avatar, if you point at it

# --- vision.py: the same picture, whatever background and size a copy got; not a different one
prints = vision.avatar_prints(AVATAR)
assert 1 < len(prints) <= 4
for copy in (AVATAR, enc(on((0, 0, 0)), "JPEG", quality=40), enc(on((49, 51, 56)).resize((512, 512)), "JPEG"),
             enc(on((255, 255, 255)).resize((48, 48))), enc(cutout.resize((256, 256)), "WEBP")):
    assert vision.same_picture(vision.fingerprint(copy), prints)
other = Image.new("RGB", (96, 96), "white"); ImageDraw.Draw(other).rectangle((10, 50, 90, 90), fill=(200, 30, 30))
for different in (enc(other), enc(Image.new("RGB", (96, 96), (49, 51, 56)))):
    assert not vision.same_picture(vision.fingerprint(different), prints)
assert vision.fingerprint(b"nope") is None and not vision.same_picture(None, prints) and not vision.same_picture(1, set())
if real.exists():                                                     # the avatar the user sent, when it's here
    rp = vision.avatar_prints(real.read_bytes()); ri = Image.open(real)
    flat = Image.new("RGB", ri.size, (0, 0, 0)); flat.paste(ri, mask=ri.getchannel("A"))
    assert vision.same_picture(vision.fingerprint(enc(flat.resize((300, 300)), "JPEG", quality=50)), rp)
    assert not vision.same_picture(vision.fingerprint(enc(ImageOps.mirror(flat))), rp)
assert vision.avatar_label("a grey hamster") == "Gomi's own avatar, a grey hamster" and vision.avatar_label("") == "Gomi's own avatar"

# --- the prompts: a line about her avatar when it's known, nothing otherwise (training data has none)
line = "Your Discord avatar, the picture next to your name, is a grumpy grey hamster. That's your face here"
assert line in persona.system_content(avatar="a grumpy grey hamster") and "avatar" not in persona.system_content()
for msgs in (persona.build_messages(["kaz0: hi"], False, avatar="a grumpy grey hamster"),
             persona.build_goodnight_messages([], "rex", avatar="a grumpy grey hamster"),
             persona.build_session_messages([], "facts", "rex", avatar="a grumpy grey hamster")):
    assert line in msgs[0]["content"]
assert "avatar" not in persona.build_messages(["kaz0: hi"], False)[0]["content"]
room = chime.room_messages(["kaz0: hi"], {"🥺": "x"}, avatar="a grumpy grey hamster")
assert "Her Discord avatar is a grumpy grey hamster: when someone posts it or talks about it, that's her." in room[0]["content"]
assert "avatar" not in chime.room_messages(["kaz0: hi"], {"🥺": "x"})[0]["content"]

# --- the bot
PICS = {"/avatar.png": AVATAR, "/copy.jpg": enc(on((49, 51, 56)).resize((200, 200)), "JPEG", quality=60),
        "/car.png": enc(other)}
calls = []
async def handler(request):
    if request.method == "GET":
        return web.Response(body=PICS[request.path], content_type="image/png")
    body = await request.json(); calls.append(body)
    last = body["messages"][-1]
    if last.get("images"):
        what = "A grey blob with dark eyes, frowning" if "profile picture" in last["content"] else "A red car"
        return web.json_response({"message": {"content": what}, "done_reason": "stop"})
    if "interest" in body.get("format", {}).get("properties", {}):
        content = json.dumps({"read": "kaz posts gomi's face", "interest": 3, "react": 9, "emoji": "😳"})
        return web.json_response({"message": {"content": content}, "done_reason": "stop"})
    return web.json_response({"message": {"content": "a reply"}, "done_reason": "stop"})
looks = lambda: [c for c in calls if c["messages"][-1].get("images")]
rooms = lambda: [c for c in calls if "interest" in c.get("format", {}).get("properties", {})]
replies = lambda: [c for c in calls if "format" not in c and not c["messages"][-1].get("images")]

reads = []
async def read_avatar():
    reads.append(1)
    return AVATAR
ME = NS(id=1, name="Gomihyu", display_name="Gomihyu", bot=True, avatar=NS(key="a1", read=read_avatar))
bot.client._connection.user = ME
KAZ = NS(id=6, name="kaz0", display_name="Kaz", bot=False)
ids = itertools.count(1000)
class Post:
    def __init__(self, ch, author, content, attachments=()):
        self.id, self.channel, self.author, self.content, self.guild = next(ids), ch, author, content, ch.guild
        self.attachments, self.stickers, self.embeds, self.reference = list(attachments), [], [], None
        self.mentions, self.role_mentions, self.channel_mentions, self.reactions = [], [], [], []
    async def add_reaction(self, emoji): self.reactions.append(emoji)
class Channel:
    def __init__(self, i): self.id, self.name, self.guild, self.sent = i, "general", NS(emojis=[]), []
    @asynccontextmanager
    async def typing(self): yield
    async def send(self, text): self.sent.append(text); return NS(id=next(ids))
async def say(ch, author, content, **kw):
    post = Post(ch, author, content, **kw); await bot.on_message(post); return post
pic = lambda path: NS(content_type="image/png", url=f"http://127.0.0.1:8764{path}")

async def main():
    app = web.Application(); app.router.add_route("*", "/{tail:.*}", handler)
    runner = web.AppRunner(app); await runner.setup(); await web.TCPSite(runner, "127.0.0.1", 8764).start()

    # at login: fingerprinted, and described once by her vision model
    await bot.learn_avatar()
    assert bot.avatar_description == "A grey blob with dark eyes, frowning" and bot.avatar_prints and len(looks()) == 1
    assert "Discord profile picture" in looks()[0]["messages"][-1]["content"]
    await bot.learn_avatar(); assert len(reads) == 1 and len(looks()) == 1   # same avatar on a reconnect: nothing again

    # someone posts it (a JPEG copy on Discord's dark grey): she knows it's her, without asking the model
    ch = Channel(1); calls.clear()
    post = await say(ch, KAZ, "", attachments=[pic("/copy.jpg")])
    assert list(bot.history[1])[-1] == "kaz0: [image: Gomi's own avatar, A grey blob with dark eyes, frowning]"
    assert not looks() and len(rooms()) == 1 and post.reactions == ["😳"]
    assert "Her Discord avatar is A grey blob with dark eyes, frowning" in rooms()[0]["messages"][0]["content"]
    calls.clear(); await say(ch, KAZ, "", attachments=[pic("/car.png")])        # a different picture: looked at
    assert list(bot.history[1])[-1] == "kaz0: [image: A red car]" and len(looks()) == 1

    # her replies know what she looks like
    calls.clear(); await say(ch, KAZ, "gomi what do you even look like")
    assert ch.sent == ["a reply"]
    assert "Your Discord avatar, the picture next to your name, is A grey blob with dark eyes, frowning." in \
        replies()[0]["messages"][0]["content"]

    # a new avatar: learned again; AVATAR_DESCRIPTION: no model call for it
    bot.AVATAR_DESCRIPTION = bot.avatar_description = "a grumpy grey hamster"
    ME.avatar = NS(key="a2", read=read_avatar); calls.clear()
    await bot.learn_avatar()
    assert bot.avatar_key == "a2" and not looks() and bot.avatar_description == "a grumpy grey hamster"
    calls.clear(); await say(ch, KAZ, "", attachments=[pic("/avatar.png")])
    assert list(bot.history[1])[-1] == "kaz0: [image: Gomi's own avatar, a grumpy grey hamster]"

    # Discord's default avatar isn't hers; a failed download changes nothing
    ME.avatar = None; await bot.learn_avatar(); assert bot.avatar_key == "a2"
    async def broken(): raise discord.HTTPException(NS(status=500, reason="boom"), "boom")
    ME.avatar = NS(key="a3", read=broken); await bot.learn_avatar()
    assert bot.avatar_key == "a2" and bot.avatar_prints
    await runner.cleanup(); print("AVATAR TESTS PASSED")
asyncio.run(main())
