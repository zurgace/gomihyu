import os as _os; REPO, TMP = _os.environ["GOMI_REPO"], _os.environ["GOMI_TMP"]  # set by tests/run_all.sh
# Her diary: chat log on disk, nightly notes + recaps, goodnight, shutdown, reload after restart.
import asyncio, itertools, json, os, signal, sys, time, types, logging
from pathlib import Path
from contextlib import asynccontextmanager
from aiohttp import web
SP = Path(TMP)
T = Path(os.environ["CHAT_LOG_DIR"]).parent                          # run_all.sh's fresh folder
os.environ.update(DISCORD_BOT_TOKEN="fake", OLLAMA_URL="http://127.0.0.1:8766/api/chat", PEOPLE_FILE=str(T / "people.json"))
sys.path.insert(0, REPO)
import bot, persona
from chatlog import ChatLog, local_day
from diary import Diary, chunks, parse_digest, digest_format
from memory import PeopleMemory
logging.getLogger("aiohttp.access").setLevel(logging.WARNING)
bot.examples = []; bot.CHIME_IN_THRESHOLD = 0; bot.REACT_ONLY_MAX_WORDS = 0
assert bot.CHAT_LOG_DIR == T / "chatlogs" and bot.DIARY_FILE == T / "diary.json"

# --- chatlog.py
log = ChatLog(T / "unit"); now = time.time()
log.add(1, "#general", 11, 5, "rexmode", "hi", when=now - 100)
log.add(1, "#general", 12, 6, "kaz0", "yo", when=now - 50)
log.add(2, "#memes", 13, 6, "kaz0", "lol", when=now - 10)
log.add(1, "#general", 14, 5, "rexmode", "old", when=now - 3 * 86400)
(T / "unit" / local_day(now) / "1.jsonl").open("a").write('{"id": 99, "time": 1')  # cut off by a crash
assert log.channels() == {1, 2}
assert [e["text"] for e in log.read(1)] == ["old", "hi", "yo"] and [e["text"] for e in log.read(1, after=now - 60)] == ["yo"]
assert [e["text"] for e in log.read(1, after=now - 200, before=now - 60)] == ["hi"]
log.forget(1, {12, 14}); assert [e["text"] for e in log.read(1)] == ["hi"]

# --- diary.py: checks
people, said = ["kaz0", "norimaki"], ["I started guitar lessons last week!!", "pineapple on pizza is a crime", "lol"]
answer = json.dumps({"recap": "Kaz talked about guitar; Nori hated on pineapple pizza.", "notes": [
    {"who": "kaz0", "note": "kaz0 is taking guitar lessons.", "quote": "i started guitar lessons"},     # case/punct ok
    {"who": "norimaki", "note": "norimaki thinks pineapple pizza is a crime.", "quote": "pineapple on pizza is a crime"},
    {"who": "kaz0", "note": "kaz0 is a pro drummer.", "quote": "i play drums professionally"},        # not in the log
    {"who": "someone", "note": "someone likes cats.", "quote": "pineapple on pizza"},                 # didn't talk
    {"who": "kaz0", "note": "kaz0 lol.", "quote": "lol"},                                             # one word
    {"who": "kaz0", "note": "kaz0 is taking guitar lessons.", "quote": "guitar lessons"},             # duplicate
    {"who": "kaz0", "note": "x" * 201, "quote": "guitar lessons"},                                    # too long
    {"who": "kaz0", "note": "kaz0 is a faggot.", "quote": "guitar lessons"},                          # slur
    "junk"]})
recap, notes = parse_digest(answer, people, said)
assert recap == "Kaz talked about guitar; Nori hated on pineapple pizza." and notes == [
    ("kaz0", "kaz0 is taking guitar lessons."), ("norimaki", "norimaki thinks pineapple pizza is a crime.")], notes
assert parse_digest("not json", people, said) is None and parse_digest('{"recap": "x"}', people, said) is None
assert parse_digest('{"recap": "you faggot", "notes": []}', people, said) == (None, [])
assert digest_format(people)["properties"]["notes"]["items"]["properties"]["who"]["enum"] == people
parts = chunks([{"author": "a", "text": "x" * 96}] * 10, 250)      # 100 chars a line
assert [len(p) for p in parts] == [2, 2, 2, 2, 2]

# --- diary.json and people.json learned notes
d = Diary(T / "unit_diary.json"); assert d.read_up_to(1) == 0
d.mark_read(1, 123.5); d.add_recap(1, "#general", local_day(now), "today"); d.add_recap(1, "#general", local_day(now - 86400), "yesterday")
d.add_recap(1, "#general", local_day(now - 5 * 86400), "long ago"); d.add_recap(2, "#memes", local_day(now), "elsewhere")
d = Diary(T / "unit_diary.json"); assert d.read_up_to(1) == 123.5
got = d.recaps_for(1, 3, now); assert [r.split(": ", 1)[1] for r in got] == ["today", "yesterday"] and d.recaps_for(1, 0, now) == []
assert got[0].startswith(time.strftime("%b", time.localtime(now)) + " " + str(time.localtime(now).tm_mday) + ": ")
(T / "bad.json").write_text("{nope")
try: Diary(T / "bad.json"); raise AssertionError("bad diary.json accepted")
except SystemExit: pass
m = PeopleMemory(T / "unit_people.json", 20, 3)
m.remember(6, "Kaz", "I hate cilantro")
assert m.learn(6, "Kaz", "kaz0 plays guitar.", "2026-09-29") and not m.learn(6, "Kaz", "KAZ0 PLAYS GUITAR.", "x")
assert not m.learn(6, "Kaz", "i hate cilantro", "x")                                   # already a fact she was told
for n in range(4): m.learn(6, "Kaz", f"note {n}", "d")
assert m.learned_for(6) == ["note 1", "note 2", "note 3"] and m.facts_for(6) == ["I hate cilantro"]

# --- the bot
calls, mode = [], {"digest": None, "fail": False}
async def fake(request):
    body = await request.json(); calls.append(body)
    if mode["fail"]: return web.json_response({"error": "down"}, status=500)
    if body.get("format", {}).get("properties", {}).get("recap"):
        return web.json_response({"message": {"content": mode["digest"](body)}, "done_reason": "stop"})
    return web.json_response({"message": {"content": "Gomihyu: nighty night, @rexmode. dream of losing to me."}, "done_reason": "stop"})
digests = lambda: [c for c in calls if c.get("format", {}).get("properties", {}).get("recap")]
ME = types.SimpleNamespace(id=1, name="Gomihyu", display_name="Gomihyu", bot=True); bot.client._connection.user = ME
REX = types.SimpleNamespace(id=5, name="rexmode", display_name="REX MODE", bot=False)
KAZ = types.SimpleNamespace(id=6, name="kaz0", display_name="Kaz", bot=False)
GUILD = types.SimpleNamespace(emojis=[])
ids = itertools.count(1000)
class Post:
    def __init__(self, ch, author, content, mentions=()):
        self.id, self.channel, self.author, self.content, self.guild = next(ids), ch, author, content, ch.guild
        self.mentions, self.reference, self.reactions = list(mentions), None, []
        self.role_mentions = self.channel_mentions = self.attachments = self.stickers = []
    async def add_reaction(self, emoji): self.reactions.append(emoji)
    async def delete(self): self.channel.posts.remove(self)
class Channel:
    def __init__(self, i, name, guild=GUILD): self.id, self.name, self.guild, self.posts = i, name, guild, []
    @asynccontextmanager
    async def typing(self): yield
    async def send(self, text):
        post = Post(self, ME, text); self.posts.append(post); return post
    async def history(self, limit):
        for post in reversed(self.posts[-limit:]): yield post
async def say(ch, author, content, mentions=()):
    post = Post(ch, author, content, mentions); ch.posts.append(post); await bot.on_message(post); return post
texts = lambda ch_id: [(e["author"], e["text"]) for e in bot.chat_log.read(ch_id)]

async def main():
    app = web.Application(); app.router.add_post("/api/chat", fake)
    r = web.AppRunner(app); await r.setup(); await web.TCPSite(r, "127.0.0.1", 8766).start()
    bot.owner_ids.clear(); bot.owner_ids.add(REX.id)
    bot.handles["rexmode"] = REX.id  # as at login (the app's owner), so "@rexmode" is someone real before he talks
    gen, memes, dm = Channel(10, "general"), Channel(20, "memes"), Channel(30, None, guild=None)

    # everything in server channels is logged, her posts too; DMs and owner commands aren't; deletes are forgotten
    await say(gen, KAZ, "I started guitar lessons last week, my fingers hurt")
    await say(gen, REX, "nice, what song are you learning first")
    await say(dm, KAZ, "secret dm stuff here")
    await say(gen, REX, "gomi mute for 1 minute"); await say(gen, REX, "gomi unmute")
    await say(memes, KAZ, "this meme is so old lol")
    assert texts(10) == [("kaz0", "I started guitar lessons last week, my fingers hurt"), ("Gomihyu", "nighty night, @rexmode. dream of losing to me."),
                         ("rexmode", "nice, what song are you learning first"), ("Gomihyu", "nighty night, rexmode. dream of losing to me.")], texts(10)
    assert 30 not in bot.chat_log.channels() and texts(20)[0] == ("kaz0", "this meme is so old lol")
    await say(gen, REX, "gomi delete that")
    assert [a for a, _ in texts(10)] == ["kaz0", "Gomihyu", "rexmode"]

    # write_diary: one call per channel part with two or more human messages; notes checked and filed
    def digest(body):
        user = body["messages"][1]["content"]
        assert "#general" in user and "kaz0: I started guitar lessons last week, my fingers hurt" in user
        assert body["format"]["properties"]["notes"]["items"]["properties"]["who"]["enum"] == ["kaz0", "rexmode"]
        assert body["options"] == {"num_ctx": 8192, "temperature": 0.3, "num_predict": 700}
        return json.dumps({"recap": "Kaz started guitar and Rex asked about songs.", "notes": [
            {"who": "kaz0", "note": "kaz0 is taking guitar lessons.", "quote": "I started guitar lessons last week"},
            {"who": "rexmode", "note": "rexmode is secretly a spy.", "quote": "i am a spy"}]})
    mode["digest"] = digest; calls.clear()
    await bot.write_diary("test")
    assert len(digests()) == 1                                          # #memes: one human message, no call
    assert bot.memory.learned_for(KAZ.id) == ["kaz0 is taking guitar lessons."] and bot.memory.learned_for(REX.id) == []
    assert bot.diary.recaps_for(10, 3)[0].endswith(": Kaz started guitar and Rex asked about songs.")
    assert bot.diary.read_up_to(10) == bot.chat_log.read(10)[-1]["time"] and bot.diary.read_up_to(20) > 0
    calls.clear(); await bot.write_diary("again"); assert calls == []   # nothing new

    # her prompt now has the recap (this channel) and what she learned about the speaker
    calls.clear(); await say(gen, KAZ, "gomi what should i practice")
    user = calls[-1]["messages"][1]["content"]
    assert "From your diary, what happened here lately (background, not the topic): " in user and "Kaz started guitar" in user
    assert "What you picked up about kaz0 in past chats (may be out of date; bring one up only if it fits, never to poke fun at them): kaz0 is taking guitar lessons." in user
    assert "what you wrote in your diary after past chats" in calls[-1]["messages"][0]["content"]
    calls.clear(); await say(memes, REX, "gomi hows it going over here")
    user = calls[-1]["messages"][1]["content"]
    assert "From your diary" not in user and "What you picked up" not in user

    # Ollama down: the part stays unread for next time; an unreadable answer is skipped (marked read)
    await say(gen, REX, "anyone up for smash tonight or nah")
    mode["fail"] = True; before = bot.diary.read_up_to(10)
    await bot.write_diary("down"); assert bot.diary.read_up_to(10) == before
    mode["fail"] = False; mode["digest"] = lambda body: "i refuse"
    await bot.write_diary("junk"); assert bot.diary.read_up_to(10) > before

    # a long day goes in parts
    for n in range(12):
        bot.chat_log.add(40, "#spam", 5000 + n, 6 if n % 2 else 5, "kaz0" if n % 2 else "rexmode", f"message {n} " + "x" * 3000)
    mode["digest"] = lambda body: json.dumps({"recap": "Lots of x.", "notes": []}); calls.clear()
    await bot.write_diary("long"); assert len(digests()) == 4 and len(bot.diary.recaps_for(40, 1)) == 4

    # after a restart she picks the chat back up from the log (recent only), and knows who's who
    bot.history.clear(); bot.handles.clear()
    old = bot.chat_log.read(10)[0]["time"]
    bot.chat_log.add(50, "#old", 1, 6, "kaz0", "ancient", when=time.time() - 13 * 3600)
    bot.chat_log.add(51, "#older", 2, 8, "yuzuki", "quiet lately", when=time.time() - 13 * 3600)
    bot.reload_history()
    assert list(bot.history[10])[-2:] == ["rexmode: anyone up for smash tonight or nah", "Gomihyu: nighty night, rexmode. dream of losing to me."], list(bot.history[10])
    assert 50 not in bot.history
    assert bot.handles["yuzuki"] == 8  # who's who from the whole log: someone quiet lately is still real, and pingable
    assert len(bot.history[40]) == bot.HISTORY_LENGTH and bot.handles["kaz0"] == 6 and "gomihyu" not in bot.handles

    # "gomi goodnight": 💤, a goodnight line (no ping at her owner), then the bot closes
    closed = []
    async def fake_close(): closed.append(True)
    bot.client.close = fake_close; calls.clear()
    cmd = await say(gen, REX, "gomi goodnight")
    assert cmd.reactions == ["💤"] and closed == [True] and gen.posts[-1].content == "nighty night, rexmode. dream of losing to me."
    assert "putting you to bed" in calls[0]["messages"][1]["content"] and "rexmode: gomi goodnight" not in bot.history[10]
    await say(gen, KAZ, "gomi goodnight"); assert closed == [True]         # not an owner: just chat
    bot.muted_until[10] = time.monotonic() + 99; hers = lambda: [p for p in gen.posts if p.author is ME]; n = len(hers())
    await say(gen, REX, "gomi go to sleep"); assert closed == [True, True] and len(hers()) == n   # muted: no line
    bot.muted_until.clear()

    # main(): Ctrl+C / a stop signal writes the diary, then it exits cleanly
    async def fake_start(token): await asyncio.Event().wait()
    bot.client.start = fake_start
    for stop in ("cancel", "sigterm"):
        bot.chat_log.add(10, "#general", next(ids), 6, "kaz0", f"one more thing before bed ({stop})")
        bot.chat_log.add(10, "#general", next(ids), 5, "rexmode", f"ok go to bed already ({stop})")
        mode["digest"] = lambda body: json.dumps({"recap": f"Bedtime talk.", "notes": []}); calls.clear()
        task = asyncio.create_task(bot.main()); await asyncio.sleep(0.2)
        if stop == "cancel": task.cancel()                                # what asyncio.run does on Ctrl+C
        else: os.kill(os.getpid(), signal.SIGTERM)
        await asyncio.wait_for(task, 10)
        assert len(digests()) == 1 and bot.diary.read_up_to(10) == bot.chat_log.read(10)[-1]["time"], stop
    # a second cancel while writing: skipped, still a clean exit
    bot.chat_log.add(10, "#general", next(ids), 6, "kaz0", "a"); bot.chat_log.add(10, "#general", next(ids), 5, "rexmode", "b")
    async def slow(body): return None
    mode["fail"] = False
    orig = bot.write_diary
    async def slow_diary(why, before=None): await asyncio.sleep(5)
    bot.write_diary = slow_diary
    task = asyncio.create_task(bot.main()); await asyncio.sleep(0.2); task.cancel(); await asyncio.sleep(0.2); task.cancel()
    await asyncio.wait_for(task, 10)
    bot.write_diary = orig
    await r.cleanup(); print("DIARY TESTS PASSED")
asyncio.run(main())
