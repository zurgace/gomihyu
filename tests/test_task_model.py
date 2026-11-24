import os as _os; REPO, TMP = _os.environ["GOMI_REPO"], _os.environ["GOMI_TMP"]  # set by tests/run_all.sh
# TASK_MODEL: reading the room, her diary and the vibe note go to it; her replies stay on OLLAMA_MODEL.
import asyncio, itertools, json, os, sys, time, types, logging
from pathlib import Path
from contextlib import asynccontextmanager
from aiohttp import web
T = Path(os.environ["CHAT_LOG_DIR"]).parent
os.environ.update(DISCORD_BOT_TOKEN="fake", OLLAMA_URL="http://127.0.0.1:8762/api/chat", PEOPLE_FILE=str(T / "people.json"),
                  OLLAMA_MODEL="gomi-w1", TASK_MODEL="gemma4:e4b", VISION_MODEL="gemma4:e4b")
sys.path.insert(0, REPO)
from gomi import bot
logging.getLogger("aiohttp.access").setLevel(logging.WARNING)
assert bot.MODEL_NAME == "gomi-w1" and bot.TASK_MODEL == "gemma4:e4b" and bot.VISION_MODEL == "gemma4:e4b"
bot.examples = []; bot.CHIME_IN_THRESHOLD = 6
NS = types.SimpleNamespace
calls, interest = [], {"n": 8}


async def handler(request):
    body = await request.json(); calls.append(body)
    props = body.get("format", {}).get("properties", {})
    if "interest" in props:
        content = json.dumps({"read": "kaz0 on games", "interest": interest["n"], "emoji": "none"})
    elif "recap" in props:
        content = json.dumps({"recap": "we talked games.", "notes": []})
    elif "notes" in props:
        content = json.dumps({"notes": ["lowercase bursts"]})
    else:
        content = "a reply"
    return web.json_response({"message": {"content": content}, "done_reason": "stop"})

ME = NS(id=1, name="Gomihyu", display_name="Gomihyu", bot=True); bot.client._connection.user = ME
KAZ = NS(id=6, name="kaz0", display_name="Kaz", bot=False)
ids = itertools.count(1000)
class Post:
    def __init__(self, ch, author, content):
        self.id, self.channel, self.author, self.content, self.guild = next(ids), ch, author, content, ch.guild
        self.attachments, self.stickers, self.embeds, self.reference = [], [], [], None
        self.mentions, self.role_mentions, self.channel_mentions, self.reactions = [], [], [], []
    async def add_reaction(self, emoji): self.reactions.append(emoji)
class Channel:
    def __init__(self, i): self.id, self.name, self.guild, self.sent = i, "general", NS(emojis=[]), []
    @asynccontextmanager
    async def typing(self): yield
    async def send(self, text): self.sent.append(text); return NS(id=next(ids))


async def main():
    app = web.Application(); app.router.add_route("*", "/{tail:.*}", handler)
    runner = web.AppRunner(app); await runner.setup(); await web.TCPSite(runner, "127.0.0.1", 8762).start()
    ch = Channel(1)
    await bot.on_message(Post(ch, KAZ, "anyone playing the new patch tonight or what"))
    for _ in range(50):
        if ch.sent:
            break
        await asyncio.sleep(0.05)
    rooms = [c for c in calls if "interest" in c.get("format", {}).get("properties", {})]
    replies = [c for c in calls if "format" not in c]
    assert ch.sent == ["a reply"] and len(rooms) == 1 and len(replies) == 1, calls
    assert rooms[0]["model"] == "gemma4:e4b" and replies[0]["model"] == "gomi-w1"
    calls.clear()
    now = time.time()
    part = [{"author": "kaz0", "author_id": 6, "text": "i love this game so much", "time": now, "channel": "#general"},
            {"author": "rexmode", "author_id": 5, "text": "same honestly its great", "time": now + 1, "channel": "#general"}]
    assert await bot.diary_entry(1, part)
    await bot.update_vibe([dict(e, kind="message") for e in part] * 6)
    assert [c["model"] for c in calls] == ["gemma4:e4b", "gemma4:e4b"], [c["model"] for c in calls]
    await runner.cleanup()
    print("TASK MODEL TESTS PASSED")

asyncio.run(main())
