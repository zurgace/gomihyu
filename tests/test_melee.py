import os as _os; REPO, TMP = _os.environ["GOMI_REPO"], _os.environ["GOMI_TMP"]  # set by tests/run_all.sh
# She only talks once a Melee session is over (post_session): taunts are held and handed to her one post.
import asyncio, itertools, json, os, sys, time, types, logging, shutil
from pathlib import Path
from contextlib import asynccontextmanager
from aiohttp import web
SP = Path(TMP)
OUT = SP / "outbox"; shutil.rmtree(OUT, ignore_errors=True); OUT.mkdir()
os.environ.update(DISCORD_BOT_TOKEN="fake", OLLAMA_URL="http://127.0.0.1:8768/api/chat", PEOPLE_FILE=str(SP / "people_melee.json"),
                  MELEE_OUTBOX=str(OUT), MELEE_PLAYER="Rex")
sys.path.insert(0, REPO)
import bot, melee
logging.getLogger("aiohttp.access").setLevel(logging.WARNING)
bot.examples = []
bot.MELEE_CHANNEL_FILE = SP / "melee_channel_test.json"; bot.MELEE_CHANNEL_FILE.unlink(missing_ok=True)

# the prompt facts: the last 3 taunts, quoted
facts = melee.match_facts({"won": True, "stocks": [2, 0], "opponent_character": "Falco", "stage": "Battlefield"}, "Rex",
                          ["one", "two", "three", "four"])
assert 'During the match you trash-talked (call one back if it fits, don\'t list them): "two" / "three" / "four".' in facts
assert "trash-talked" not in melee.match_facts({"won": False, "stocks": [0, 1], "opponent_character": "Fox"}, "Rex")

calls, answer = [], {"v": "ok", "fail": False}
async def fake(request):
    calls.append(await request.json())
    if answer["fail"]: return web.json_response({"error": "down"}, status=500)
    return web.json_response({"message": {"content": answer["v"]}, "done_reason": "stop"})
ME = types.SimpleNamespace(id=1, name="Gomihyu", display_name="Gomihyu", bot=True); bot.client._connection.user = ME
class Channel:
    def __init__(self, i): self.id, self.name, self.guild, self.sent = i, "melee", None, []
    @asynccontextmanager
    async def typing(self): yield
    async def send(self, text):
        self.sent.append(text); return types.SimpleNamespace(id=len(self.sent))
ch = Channel(77)
bot.client.get_channel = lambda i: ch if i == 77 else None
counter = itertools.count()
def drop(event, age=0):
    event = {**event, "time": time.time() - age}
    (OUT / f"{time.time():.6f}-{next(counter):03d}.json").write_text(json.dumps(event))
taunt = lambda text, age=0: drop({"kind": "taunt", "text": text}, age)
match = lambda age=0, **kw: drop({"won": True, "stocks": [2, 0], "opponent_character": "Falco", "stage": "Battlefield", **kw}, age)
end = lambda age=0: drop({"kind": "session_end"}, age)                  # AI-Melee: the game closed
post = lambda: bot.post_session(OUT)
files = lambda: sorted(p.name for p in OUT.glob("*.json"))
facts_of = lambda call: call["messages"][1]["content"]

async def main():
    app = web.Application(); app.router.add_post("/api/chat", fake)
    r = web.AppRunner(app); await r.setup(); await web.TCPSite(r, "127.0.0.1", 8768).start()
    melee.save_channel(bot.MELEE_CHANNEL_FILE, 77)
    assert bot.MELEE_MAX_AGE_MINUTES == 120 and bot.MELEE_SESSION_IDLE_MINUTES == 20

    # during the session: taunts leave the outbox, nothing is posted, no model call
    taunt("get wrecked", age=200); taunt("is that all?", age=120); taunt("n-word placeholder"); taunt("  ")
    taunt("ancient line", age=130 * 60)                                 # older than MELEE_MAX_AGE_MINUTES
    bot.has_slur_orig = bot.has_slur
    bot.has_slur = lambda text: "n-word" in text or bot.has_slur_orig(text)
    await post()
    assert ch.sent == [] and calls == [] and files() == []
    assert [t for _, t in bot.melee_taunts] == ["get wrecked", "is that all?"], bot.melee_taunts

    # a match ends, but the session doesn't: it waits, however often she checks
    taunt("bow before me", age=30); match(line="HA!", age=20)
    await post(); await post()
    assert ch.sent == [] and calls == [] and len(files()) == 1

    # the game closes: one post about the session, drawing on her taunts; its files and taunts are gone after
    end(age=5)
    answer["v"] = "Gomihyu: I told you. Battlefield bows to me."
    await post()
    assert ch.sent == ["I told you. Battlefield bows to me."] and len(calls) == 1 and files() == []
    f = facts_of(calls[0])
    assert 'During the session you trash-talked (call one back if it fits, don\'t list them): "get wrecked" / ' \
           '"is that all?" / "bow before me"' in f and 'Right after the match you said: "HA!"' in f, f
    assert "1 match, you as Mario" in f and "You won 1 and lost 0" in f
    assert bot.melee_taunts == [] and bot.history[77][-1] == "Gomihyu: I told you. Battlefield bows to me."

    # several matches, then the owner's "gg": one post for all of them, no "trash-talked" line without taunts
    calls.clear(); answer["v"] = "Two out of three. Obviously."
    match(age=300); match(won=False, stocks=[0, 1], age=200); match(age=100)
    await post(); assert calls == []
    bot.melee_gg = True; await post()
    f = facts_of(calls[0])
    assert ch.sent[-1] == "Two out of three. Obviously." and len(calls) == 1 and files() == [] and not bot.melee_gg
    assert "3 matches" in f and "You won 2 and lost 1" in f and "Match 2: lost 0-1" in f and "trash-talked" not in f

    # no match for MELEE_SESSION_IDLE_MINUTES (a force-quit, no session_end): posted anyway
    calls.clear(); answer["v"] = "The coward left."
    match(age=21 * 60); await post()
    assert ch.sent[-1] == "The coward left." and files() == []

    # taunts from long before the session (an old quit game) aren't its lines
    calls.clear(); answer["v"] = "Another win."
    taunt("from a quit game", age=20 * 60); taunt("this session", age=60); match(age=30); end()
    await post()
    assert '"this session"' in facts_of(calls[0]) and "quit game" not in facts_of(calls[0]) and bot.melee_taunts == []

    # matches after a session_end wait for the next session
    calls.clear(); answer["v"] = "Session one: mine."
    match(age=60); end(age=50); match(age=10)
    await post()
    assert ch.sent[-1] == "Session one: mine." and len(files()) == 1 and "1 match," in facts_of(calls[0])
    bot.melee_gg = True; answer["v"] = "Session two: also mine."; await post()
    assert ch.sent[-1] == "Session two: also mine." and files() == []

    # the model is down: the session and its taunts wait for the next check
    calls.clear(); taunt("round two, loser", age=40); match(age=20); end()
    answer["fail"] = True; assert await post() is True
    assert len(files()) == 2 and len(bot.melee_taunts) == 1 and ch.sent[-1] == "Session two: also mine."
    answer["fail"] = False; answer["v"] = "Round two: mine."; calls.clear()
    assert await post() is False
    assert ch.sent[-1] == "Round two: mine." and '"round two, loser"' in facts_of(calls[-1]) and files() == []

    # quiet mode doesn't stop her session posts; a mute drops the session and its taunts
    bot.quiet_until[77] = time.monotonic() + 600
    answer["v"] = "Quiet mode can't hide THIS win."; match(age=10); end(); await post()
    assert ch.sent[-1] == "Quiet mode can't hide THIS win."
    bot.quiet_until.clear(); bot.muted_until[77] = time.monotonic() + 600; n = len(ch.sent); calls.clear()
    taunt("muted taunt", age=10); match(age=5); end(); await post()
    assert len(ch.sent) == n and calls == [] and files() == [] and bot.melee_taunts == []
    bot.muted_until.clear()

    # no channel picked: taunts are still taken in, the session waits in the outbox
    melee.save_channel(bot.MELEE_CHANNEL_FILE, None); calls.clear()
    taunt("anyone there?", age=5); match(age=3); end(); await post()
    assert calls == [] and len(files()) == 2 and [t for _, t in bot.melee_taunts] == ["anyone there?"]
    melee.save_channel(bot.MELEE_CHANNEL_FILE, 77); answer["v"] = "Finally, an audience."
    await post()
    assert ch.sent[-1] == "Finally, an audience." and '"anyone there?"' in facts_of(calls[0]) and files() == []

    # a session too old to post (its last match over MELEE_MAX_AGE_MINUTES ago) is dropped, with its taunts
    taunt("old taunt", age=121 * 60 - 5); match(age=121 * 60); end(age=121 * 60 - 1); n = len(ch.sent); calls.clear()
    await post()
    assert len(ch.sent) == n and calls == [] and files() == [] and bot.melee_taunts == []
    await r.cleanup(); print("MELEE TESTS PASSED")
asyncio.run(main())
