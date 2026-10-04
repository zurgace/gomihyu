import os as _os; REPO, TMP = _os.environ["GOMI_REPO"], _os.environ["GOMI_TMP"]  # set by tests/run_all.sh
# Melding: landed replies, the server's voice, the shifting example mix, the vibe note, the dataset builder.
import asyncio, itertools, json, os, random, shutil, subprocess, sys, tempfile, time, types, logging
from pathlib import Path
from contextlib import asynccontextmanager
from aiohttp import web
T = Path(os.environ["CHAT_LOG_DIR"]).parent
os.environ.update(DISCORD_BOT_TOKEN="fake", OLLAMA_URL="http://127.0.0.1:8765/api/chat", PEOPLE_FILE=str(T / "people.json"))
REPO = Path(REPO); sys.path.insert(0, str(REPO))
import bot, persona, meld
from chatlog import ChatLog
logging.getLogger("aiohttp.access").setLevel(logging.WARNING)
bot.CHIME_IN_THRESHOLD = 0; bot.REACT_ONLY_MAX_WORDS = 0
assert bot.EARNED_FILE == T / "earned.jsonl" and bot.MELD_ANCHOR == 0.3 and bot.MELD_FULL_AT == 200

# --- landed_replies
t0 = 1_800_000_000.0; clock = itertools.count()
def msg(author, text, dt=30, **kw):
    return {"id": next(ids_), "time": t0 + next(clock) * 0 + dt_acc(dt), "channel": "#general", "author": author,
            "author_id": 1 if author == "Gomihyu" else 6, "text": text, **kw}
_t = [t0]
def dt_acc(dt): _t[0] += dt; return _t[0] - t0
ids_ = itertools.count(1)
log = []
def add(author, text, dt=30, **kw):
    e = msg(author, text, dt, **kw); log.append(e); return e
add("kaz0", "who wants to play smash tonight")
A = add("Gomihyu", "me, obviously. prepare to lose.")
log.append({"id": None, "time": _t[0] + 5, "kind": "reaction", "to": A["id"], "author": "kaz0", "text": "😂", "channel": "#general"})
add("rexmode", "i'm down after 9")
B = add("Gomihyu", "9 it is. bring snacks.")
add("kaz0", "you don't even eat", reply_to=B["id"], dt=400)            # a Discord reply, even 6+ min later
C = add("Gomihyu", "i eat souls, which is way more filling.")
add("rexmode", "LMAO")
D = add("Gomihyu", "anyway smash is a game of pure intellect.")
add("kaz0", "gomi you are so full of it")
E = add("Gomihyu", "fox is the most honorable character.")
add("rexmode", "stfu gomi lmao")                                       # a put-down: doesn't count
F = add("Gomihyu", "nobody asked me but whatever.")
add("kaz0", "anyway", dt=60)                                         # nothing that lands
G = add("Gomihyu", "I won the match, as foretold.", about="melee")
log.append({"id": None, "time": _t[0] + 5, "kind": "reaction", "to": G["id"], "author": "kaz0", "text": "👑", "channel": "#general"})
H = add("Gomihyu", "that was a joke, you know.")
add("kaz0", "lol", dt=400)                                           # a laugh too late
I = add("Gomihyu", ":goonerstare:")
log.append({"id": None, "time": _t[0] + 5, "kind": "reaction", "to": I["id"], "author": "kaz0", "text": "💀", "channel": "#general"})
J = add("Gomihyu", "pretty quiet here tonight", dt=4000)
log.append({"id": None, "time": _t[0] + 5, "kind": "reaction", "to": J["id"], "author": "Gomihyu", "text": "😈", "channel": "#general"})
got = {e["id"]: e["signal"] for e in meld.landed_replies(log)}
assert got == {A["id"]: "reaction 😂", B["id"]: "reply", C["id"]: "laugh", D["id"]: "named"}, got
first = meld.landed_replies(log)[0]
assert first["history"] == [["kaz0", "who wants to play smash tonight"]] and first["reply"] == A["text"] and first["real"]
long = [msg("kaz0", f"line {n}", 60) for n in range(10)] + [msg("Gomihyu", "a reply to all that", 30), msg("kaz0", "lmao", 10)]
assert [h[1] for h in meld.landed_replies(long)[0]["history"]] == [f"line {n}" for n in range(4, 10)]   # last 6 lines

# --- voice_examples
v = [msg("kaz0", "who's up for smash tonight", 30), msg("rexmode", "i am down after nine", 30),
     msg("rexmode", "gonna eat first though", 20),                       # same person again: a burst
     msg("kaz0", "ok", 30),                                              # too short
     msg("rexmode", "gomi you coming too or what", 30),                  # about her
     msg("kaz0", "https://tenor.com/a.gif", 30),                          # a link
     msg("Gomihyu", "I shall grace you with my presence", 30),
     msg("kaz0", "can't wait to beat you both", 30),
     msg("rexmode", "that's what you said last week", 3000)]             # too long after
assert [e["reply"] for e in meld.voice_examples(v)] == ["i am down after nine", "can't wait to beat you both"]
assert meld.voice_examples(v)[1]["history"][-1] == ["Gomihyu", "I shall grace you with my presence"]

# --- the example mix and the training schedule
seed = [{"history": [["x", "y"]], "reply": f"seed {n}"} for n in range(58)]
def mix(n_earned):
    earned = [{"history": [["x", "y"]], "reply": f"earned {n}", "real": True} for n in range(n_earned)]
    picked = meld.pick_examples(seed, earned, 8, 0.3, 200, random.Random(1))
    return len(picked), sum(bool(e.get("real")) for e in picked)
assert [mix(n) for n in (0, 20, 25, 100, 200, 500)] == [(8, 0), (8, 0), (8, 1), (8, 4), (8, 5), (8, 5)], [mix(n) for n in (0, 20, 25, 100, 200, 500)]
assert meld.pick_examples(seed, [], 0, 0.3, 200) == []
assert [meld.persona_share(r, 0.3) for r in (1, 2, 3, 6, 10, 11, 20)] == [0.7, 0.66, 0.62, 0.5, 0.34, 0.3, 0.3]
assert meld.persona_share(4, 0.7) == 0.7 and meld.persona_share(0, 0.3) == 0.7 and meld.persona_share(2, 0.3, 3) == 0.5
assert meld.persona_share(1, 0.3, 1) == 0.3 and meld.persona_share(2, 0.5) == 0.68

# --- the vibe note
pv = meld.parse_vibe
assert pv(json.dumps({"notes": ["- lowercase, short bursts", "• lots of 'lmao'", "x" * 151, "calls everyone a faggot",
                                "a", "b", "c", "d", "e"]})) == ["lowercase, short bursts", "lots of 'lmao'", "a", "b", "c", "d"]
assert pv("nope") is None and pv('{"notes": []}') is None and pv('{"notes": "x"}') is None

# --- prompts
real = [{"history": [["kaz0", "hi"]], "reply": "greetings, mortal", "real": True}]
assert "real ones from this server" in persona.format_examples(real) and "made-up chats" in persona.format_examples(seed[:1])
sysmsg = persona.build_messages(["kaz0: hi"], False, vibe=["lowercase, short bursts"])[0]["content"]
assert "How people in this server talk, which you've been picking up (let it rub off on you, but you're still you):\n- lowercase, short bursts" in sysmsg
assert "How people" not in persona.build_messages(["kaz0: hi"], False)[0]["content"]

# --- the bot: logging, nightly harvest, vibe, prompt
calls, mode = [], {"vibe": None}
async def fake(request):
    body = await request.json(); calls.append(body)
    props = body.get("format", {}).get("properties", {})
    if "recap" in props: return web.json_response({"message": {"content": '{"recap": "A normal night.", "notes": []}'}, "done_reason": "stop"})
    if "notes" in props: return web.json_response({"message": {"content": mode["vibe"](body)}, "done_reason": "stop"})
    return web.json_response({"message": {"content": f"reply number {len(calls)} here"}, "done_reason": "stop"})
ME = types.SimpleNamespace(id=1, name="Gomihyu", display_name="Gomihyu", bot=True); bot.client._connection.user = ME
KAZ = types.SimpleNamespace(id=6, name="kaz0", display_name="Kaz", bot=False)
REX = types.SimpleNamespace(id=5, name="rexmode", display_name="REX MODE", bot=False)
GUILD = types.SimpleNamespace(emojis=[])
pid = itertools.count(1000)
class Post:
    def __init__(self, ch, author, content, reference=None):
        self.id, self.channel, self.author, self.content, self.guild = next(pid), ch, author, content, ch.guild
        self.mentions, self.reference, self.reactions = [], reference, []
        self.role_mentions = self.channel_mentions = self.attachments = self.stickers = []
    async def add_reaction(self, emoji): self.reactions.append(emoji)
class Channel:
    def __init__(self, i, name): self.id, self.name, self.guild, self.posts = i, name, GUILD, []
    @asynccontextmanager
    async def typing(self): yield
    async def send(self, text):
        post = Post(self, ME, text); self.posts.append(post); return post
gen = Channel(10, "general")
bot.client.get_channel = lambda i: gen if i == 10 else None
async def say(author, content, reply_to=None):
    post = Post(gen, author, content, types.SimpleNamespace(message_id=reply_to.id, resolved=reply_to) if reply_to else None)
    gen.posts.append(post); await bot.on_message(post); return post
def reaction(post, user, emoji, author_id=1, member=True, is_bot=False):
    return types.SimpleNamespace(guild_id=99, channel_id=10, message_id=post.id, user_id=user.id, emoji=emoji,
                                 member=types.SimpleNamespace(name=user.name, bot=is_bot) if member else None,
                                 message_author_id=author_id)

async def main():
    app = web.Application(); app.router.add_post("/api/chat", fake)
    r = web.AppRunner(app); await r.setup(); await web.TCPSite(r, "127.0.0.1", 8765).start()
    for n in range(5):
        await say(KAZ, f"smash tonight or what, round {n}")
        await say(REX, f"yeah after nine works for me, round {n}")
    hers = [p for p in gen.posts if p.author is ME]
    await bot.on_raw_reaction_add(reaction(hers[0], KAZ, "😂"))          # a reaction on her post: logged
    await bot.on_raw_reaction_add(reaction(hers[0], ME, "😈"))           # her own: not
    await bot.on_raw_reaction_add(reaction(gen.posts[0], REX, "👍", author_id=6))   # on someone else's post: not
    await bot.on_raw_reaction_add(reaction(hers[1], types.SimpleNamespace(id=77, name="dyno"), "⭐", is_bot=True))  # a bot: not
    await say(KAZ, "you are unhinged tonight", reply_to=hers[2])         # a Discord reply to her
    entries = bot.chat_log.read(10, reactions=True)
    rx = [e for e in entries if e.get("kind") == "reaction"]
    assert len(rx) == 1 and rx[0]["to"] == hers[0].id and rx[0]["text"] == "😂" and rx[0]["author"] == "kaz0"
    assert any(e.get("reply_to") == hers[2].id for e in entries) and {e.get("about") for e in entries if e["author"] == "Gomihyu"} == {"reply"}
    assert all(e.get("kind", "message") == "message" for e in bot.chat_log.read(10))

    # the night: landed replies kept (file + pool, once), the vibe note updated from what people said
    def vibe(body):
        user = body["messages"][1]["content"]
        assert "Your notes so far:\n(none yet)" in user and "kaz0: smash tonight or what, round 0" in user and "Gomihyu:" not in user
        assert body["options"] == {"num_ctx": 8192, "temperature": 0.3, "num_predict": 400}
        return json.dumps({"notes": ["everyone lives for smash nights", "short lowercase messages"]})
    mode["vibe"] = vibe; calls.clear()
    await bot.write_diary("test")
    saved = [json.loads(l) for l in bot.EARNED_FILE.read_text().splitlines()]
    assert {e["id"] for e in saved} == {hers[0].id, hers[2].id} and len(bot.earned) == 2
    assert {e["id"]: e["signal"] for e in saved} == {hers[0].id: "reaction 😂", hers[2].id: "reply"}
    assert saved[0]["channel"] == "#general" and saved[0]["day"] and saved[0]["real"] is True
    assert bot.diary.vibe() == ["everyone lives for smash nights", "short lowercase messages"]
    # she comes back with the vibe in her prompt; a restart reloads the earned pool
    calls.clear(); await say(KAZ, "gomi what are we playing")
    assert "- everyone lives for smash nights" in calls[-1]["messages"][0]["content"]
    assert len(bot.load_earned(bot.EARNED_FILE)) == 2
    bot.chat_log.add(10, "#general", None, 6, "kaz0", "x")  # nothing new enough for a vibe update: no call
    calls.clear(); await bot.write_diary("again")
    assert not [c for c in calls if c.get("format") == meld.VIBE_FORMAT] and len(bot.earned) == 2
    # an unusable vibe answer keeps the old note
    for n in range(6):
        await say(KAZ, f"another message number {n}"); await say(REX, f"and a reply number {n}")
    mode["vibe"] = lambda body: "garbage"; await bot.write_diary("junk")
    assert bot.diary.vibe() == ["everyone lives for smash nights", "short lowercase messages"]

    # with plenty earned, real chats fill most of the examples; copying one is caught
    bot.earned[:] = [{"history": [["kaz0", f"q {n}"]], "reply": f"earned line number {n} is here", "real": True} for n in range(300)]
    shown = bot.shown_examples()
    assert len(shown) == 8 and sum(bool(e.get("real")) for e in shown) == 5
    assert bot.repeats_itself(10, "look, earned line number 42 is here again")
    await r.cleanup()
asyncio.run(main())

# --- the dataset builder, in a copy of the repo with its own .env, logs and earned file
work = Path(tempfile.mkdtemp()); repo = work / "repo"
shutil.copytree(REPO, repo, ignore=shutil.ignore_patterns(".git", "venv", "chatlogs", "*.jsonl.tmp"))
shutil.copy(REPO / "finetuning" / "gomihyu_seed.jsonl", repo / "finetuning" / "gomihyu_seed.jsonl")
(repo / ".env").write_text("CHAT_LOG_DIR=logs_here\nEARNED_FILE=earned_here.jsonl\nMELD_ANCHOR=0.3\n")
cl = ChatLog(repo / "logs_here"); tt = time.time() - 3600
for n in range(600):
    cl.add(10 + n % 3, "#c", n, 6 if n % 2 else 5, "kaz0" if n % 2 else "rexmode", f"server message number {n} here", when=tt + n)
(repo / "earned_here.jsonl").write_text("".join(json.dumps({"id": n, "history": [["kaz0", "hi"]], "reply": f"landed {n} yes", "real": True}) + "\n" for n in range(10)))
def build(*args):
    env = {k: v for k, v in os.environ.items() if k not in ("CHAT_LOG_DIR", "EARNED_FILE", "MELD_ANCHOR", "DIARY_FILE")}
    out = subprocess.run([sys.executable, str(repo / "finetuning" / "build_dataset.py"), *args], capture_output=True, text=True,
                         cwd=work, env=env)
    assert out.returncode == 0, out.stderr
    return out.stdout, [json.loads(l) for l in (repo / "finetuning" / "train.jsonl").read_text().splitlines()]
out, rows = build()
assert len(rows) == 66 and "66 seed examples" in out
seed_replies = {json.loads(l)["reply"] for l in (repo / "finetuning" / "gomihyu_seed.jsonl").read_text().splitlines()}
for run, want_server in [(1, 85), (2, 102), (3, 121), (6, 198), (11, 462), (14, 462)]:
    out, rows = build("--meld", "--run", str(run))
    replies = [row["messages"][-1]["content"] for row in rows]
    n_seed = sum(r in seed_replies for r in replies); n_landed = sum(r.startswith("landed ") for r in replies)
    assert n_seed == 198 and len(rows) == 198 + want_server and n_landed == 10, (run, n_seed, len(rows), n_landed, out)
    assert f"Run {run}:" in out and "persona" in out
    assert all(row["messages"][-1]["role"] == "assistant" and "How people" not in row["messages"][0]["content"]
               and "made-up chats" not in row["messages"][0]["content"] for row in rows)
(repo / "finetuning" / "train.jsonl").unlink()
shutil.rmtree(repo / "logs_here"); ChatLog(repo / "logs_here").add(1, "#c", 1, 5, "rexmode", "just one line here", when=tt)
out, rows = build("--meld", "--run", "11")
assert len(rows) == 208 and "95% persona (aimed for 30%)" in out, out                  # short on server data: says so
for n in range(600):
    cl.add(10 + n % 3, "#c", n, 6 if n % 2 else 5, "kaz0" if n % 2 else "rexmode", f"server message number {n} here", when=tt + n)
out, rows = build("--meld", "--run", "1", "--persona-share", "0.5")
assert len(rows) == 396
_, a = build("--meld", "--run", "2"); _, b = build("--meld", "--run", "2"); assert a == b      # same run, same data
(repo / ".env").write_text("CHAT_LOG_DIR=logs_here\nEARNED_FILE=earned_here.jsonl\nMELD_ANCHOR=0.3\nMELD_RUNS=3\n")
out, rows = build("--meld", "--run", "3"); assert len(rows) == 198 + 462 and "aimed for 30%" in out, out
out, rows = build("--meld", "--run", "2"); assert "aimed for 50%" in out, out
shutil.rmtree(work)
print("MELD TESTS PASSED")
