import os as _os; REPO, TMP = _os.environ["GOMI_REPO"], _os.environ["GOMI_TMP"]  # set by tests/run_all.sh
# Regression tests for the 2026-09-29 review fixes.
import asyncio, json, os, sys, time, types, logging, shutil
from pathlib import Path
from contextlib import asynccontextmanager
from aiohttp import web
import discord
T = Path(os.environ["CHAT_LOG_DIR"]).parent
OUT = T / "outbox"; OUT.mkdir()
os.environ.update(DISCORD_BOT_TOKEN="fake", OLLAMA_URL="http://127.0.0.1:8764/api/chat", PEOPLE_FILE=str(T / "people.json"),
                  MELEE_OUTBOX=str(OUT), MELEE_PLAYER="Rex")
sys.path.insert(0, REPO)
import bot, melee
from diary import parse_digest
logging.getLogger("aiohttp.access").setLevel(logging.WARNING)
bot.examples = []; bot.CHIME_IN_THRESHOLD = 0; bot.REACT_ONLY_MAX_WORDS = 0
bot.MELEE_CHANNEL_FILE = T / "melee_channel.json"

# --- match_facts: the event exactly as AI-Melee's gomi_brain.post writes it
event = {"version": 1, "kind": "match", "time": time.time(), "character": "Fox", "opponent_character": "Falco",
         "stage": "Battlefield", "won": False, "stocks": [0, 2], "percent": [120, 40], "line": "This isn't over!",
         "lessons": ["shield less", "recover high"], "review": "I got edgeguarded twice.",
         "notes": ["lost 2 stocks offstage.", "won 35% of openings", "took 90% from shine combos", "4th"],
         "goal": "Recover high and mix it up", "drill": "recovery",
         "drill_result": {"drill": "recovery", "goal": "Recover high", "unit": "offstage deaths", "before": 3, "after": 2,
                          "verdict": "better", "text": "..."},
         "best_plan": None, "worst_plan": None, "record": {"matches": 10, "wins": 4, "matches_vs": 6, "wins_vs": 2}}
f = melee.match_facts(event, "Rex")
for part in ['as Fox against Rex, who played Falco, on Battlefield, and you LOST: you had 0 stocks left, Rex had 2.',
             'Right after the match you said: "This isn\'t over!"', "Your own review of the match: I got edgeguarded twice.",
             "What the match log says: lost 2 stocks offstage / won 35% of openings / took 90% from shine combos.",
             'This match you were practising "Recover high": offstage deaths went 3 -> 2 (better).',
             'Next match you will work on: "Recover high and mix it up"', "Your record against Rex's Falco: 2 wins, 4 losses.",
             "Overall: 4 wins, 6 losses.", "What you've learned so far: shield less / recover high"]:
    assert part in f, (part, f)
# no drill this match (AI-Melee writes None), and odd types don't crash it or print junk
f = melee.match_facts(event | {"drill_result": None}, "Rex"); assert "practising" not in f
odd = event | {"stocks": 3, "notes": "one long string", "lessons": "also a string", "drill_result": "x", "record": [1, 2]}
f = melee.match_facts(odd, "Rex")
assert "you had 0 stocks left, Rex had 0." in f and "match log" not in f and "learned" not in f and "record" not in f.lower()
f = melee.match_facts(event | {"drill_result": {"goal": "Tech more"}, "record": {"matches": "7", "wins": True, "matches_vs": 2}}, "Rex")
assert 'practising "Tech more".' in f and "None" not in f and "Your record against Rex's Falco: 0 wins, 2 losses." in f
assert "Overall" not in f   # "7" as text: no junk line

# --- read_outbox: a match whose time isn't a number is set aside, not retried forever
(OUT / "a.json").write_text(json.dumps(event | {"time": "yesterday"}))
(OUT / "b.json").write_text(json.dumps(event))
got = melee.read_outbox(OUT, logging.getLogger("t"))
assert [p.name for p, _ in got] == ["b.json"] and (OUT / "a.bad").exists()
for p in OUT.iterdir(): p.unlink()

# --- the diary's quote check: whole words only
said = ["I started guitar lessons last week"]
answer = lambda quote: json.dumps({"recap": "x", "notes": [{"who": "kaz0", "note": "kaz0 plays guitar.", "quote": quote}]})
assert parse_digest(answer("guitar lessons"), ["kaz0"], said)[1] == [("kaz0", "kaz0 plays guitar.")]
assert parse_digest(answer("tar lessons"), ["kaz0"], said)[1] == []                 # part of a word
assert parse_digest(answer("started guitar lessons last week"), ["kaz0"], said)[1] != []
assert parse_digest(answer("i started guitar lessons last week"), ["kaz0"], said)[1] != []

# --- the bot
mode = {"down": False}
async def fake(request):
    if mode["down"]: return web.json_response({"error": "down"}, status=500)
    return web.json_response({"message": {"content": "a post from her"}, "done_reason": "stop"})
ME = types.SimpleNamespace(id=1, name="Gomihyu", display_name="Gomihyu", bot=True); bot.client._connection.user = ME
KAZ = types.SimpleNamespace(id=6, name="kaz0", display_name="Kaz", bot=False)
GUILD = types.SimpleNamespace(emojis=[])
class Channel:
    def __init__(self, i): self.id, self.name, self.guild, self.sent, self.fail = i, "general", GUILD, [], False
    @asynccontextmanager
    async def typing(self): yield
    async def send(self, text):
        if self.fail: raise discord.Forbidden(types.SimpleNamespace(status=403, reason="Forbidden"), "Missing Permissions")
        self.sent.append(text); return types.SimpleNamespace(id=500 + len(self.sent))
ch = Channel(10)
bot.client.get_channel = lambda i: ch if i == 10 else None
def msg(content):
    return types.SimpleNamespace(id=int(time.time() * 1e6) % 10**9, author=KAZ, channel=ch, guild=GUILD, content=content, mentions=[],
                                 role_mentions=[], channel_mentions=[], attachments=[], stickers=[], reference=None)

async def main():
    app = web.Application(); app.router.add_post("/api/chat", fake)
    r = web.AppRunner(app); await r.setup(); await web.TCPSite(r, "127.0.0.1", 8764).start()

    # a post Discord refuses: not in her chat history, her posts or the chat log; the bot carries on
    ch.fail = True
    await bot.on_message(msg("gomi you there or what"))
    assert ch.sent == [] and not any(l.startswith("Gomihyu:") for l in bot.history[10]) and not bot.posted
    assert [e["author"] for e in bot.chat_log.read(10)] == ["kaz0"]
    ch.fail = False
    await bot.on_message(msg("gomi hello again then"))
    assert ch.sent == ["a post from her"] and bot.history[10][-1] == "Gomihyu: a post from her"

    # Melee: the model down -> post_session says it stalled (watch_melee then waits a minute)
    melee.save_channel(bot.MELEE_CHANNEL_FILE, 10)
    (OUT / "m.json").write_text(json.dumps(event | {"time": time.time() - 1}))
    (OUT / "n.json").write_text(json.dumps({"kind": "session_end", "time": time.time()}))   # the game closed
    mode["down"] = True
    assert await bot.post_session(OUT) is True and (OUT / "m.json").exists() and (OUT / "n.json").exists()
    mode["down"] = False
    assert await bot.post_session(OUT) is False and not (OUT / "m.json").exists() and not (OUT / "n.json").exists()
    assert ch.sent[-1] == "a post from her"
    waits = []
    async def fake_sleep(seconds):
        waits.append(seconds); raise asyncio.CancelledError
    orig_sleep, orig_post = bot.asyncio.sleep, bot.post_session
    bot.asyncio.sleep = fake_sleep
    for stalled in (True, False):
        async def fake_post(outbox, stalled=stalled): return stalled
        bot.post_session = fake_post
        try: await bot.watch_melee()
        except asyncio.CancelledError: pass
    bot.asyncio.sleep, bot.post_session = orig_sleep, orig_post
    assert waits == [bot.MELEE_RETRY_SECONDS, bot.MELEE_CHECK_SECONDS]

    # shutdown stops the Melee watcher before the diary
    async def forever(): await asyncio.Event().wait()
    bot.melee_watcher = asyncio.create_task(forever())
    async def fake_start(token): await asyncio.Event().wait()
    bot.client.start = fake_start
    task = asyncio.create_task(bot.main()); await asyncio.sleep(0.2); task.cancel(); await asyncio.wait_for(task, 10)
    await asyncio.sleep(0); assert bot.melee_watcher.cancelled()
    await r.cleanup(); print("FIX TESTS PASSED")
asyncio.run(main())
