import os as _os; REPO, TMP = _os.environ["GOMI_REPO"], _os.environ["GOMI_TMP"]  # set by tests/run_all.sh
import asyncio, json, os, subprocess, sys, types, logging
from contextlib import asynccontextmanager
from aiohttp import web
SP = TMP
os.environ.update(DISCORD_BOT_TOKEN="fake", OLLAMA_URL="http://127.0.0.1:8776/api/chat", PEOPLE_FILE=f"{SP}/people_fewshot.json")
sys.path.insert(0, REPO)
import bot, persona
logging.getLogger("aiohttp.access").setLevel(logging.WARNING)
bot.REACT_ONLY_MAX_WORDS = 0; bot.CHIME_IN_THRESHOLD = 0
seed = [json.loads(l) for l in open(REPO + "/finetuning/gomihyu_seed.jsonl") if l.strip()]
assert len(seed) == 78 and bot.SEED_EXAMPLES is False and bot.examples == []   # the seed only trains her now

calls, answers = [], []
async def fake(request):
    body = await request.json(); calls.append(body)
    return web.json_response({"message": {"role": "assistant", "content": answers.pop(0) if answers else "smash, obviously."},
                              "done_reason": "stop"})
ME = types.SimpleNamespace(id=1, name="Gomihyu", display_name="Gomihyu", bot=True); bot.client._connection.user = ME
REX = types.SimpleNamespace(id=5, name="rexmode", display_name="REX MODE", bot=False)
class Channel:
    id, guild, sent = 12, None, []
    @asynccontextmanager
    async def typing(self): yield
    async def send(self, text): self.sent.append(text)
ch = Channel()
msg = lambda c: types.SimpleNamespace(author=REX, channel=ch, guild=None, content=c, mentions=[],
                                      role_mentions=[], channel_mentions=[], attachments=[], stickers=[])
def shown(call):
    system = call["messages"][0]["content"]
    assert system.startswith(persona.SYSTEM_PROMPT)
    chats = system[len(persona.SYSTEM_PROMPT):].strip().split("\n\n")[1:]  # after the header line
    return [chat.splitlines()[-1] for chat in chats]  # each chat ends with her reply

async def main():
    app = web.Application(); app.router.add_post("/api/chat", fake)
    r = web.AppRunner(app); await r.setup(); await web.TCPSite(r, "127.0.0.1", 8776).start()

    # nothing landed yet: no example chats, just the persona
    await bot.on_message(msg("what games should we play this saturday"))
    assert calls[0]["messages"][0]["content"] == persona.SYSTEM_PROMPT
    # her landed replies are her examples: up to 8, a fresh pick each reply, the chat log and instruction untouched
    bot.earned[:] = [{"history": [["kaz0", f"question {n}"]], "reply": f"landed line number {n}", "real": True}
                     for n in range(12)]
    calls.clear(); await bot.on_message(msg("ok but which character are you going to play then"))
    first = shown(calls[0])
    assert len(first) == 8 and all(line[len("Gomihyu: "):] in {e["reply"] for e in bot.earned} for line in first)
    assert "Some real chats from this server" in calls[0]["messages"][0]["content"]
    assert "made-up" not in calls[0]["messages"][0]["content"]
    assert calls[0]["messages"][1] == persona.build_messages(list(bot.history[12])[:-1], False, "rexmode")[1]
    await bot.on_message(msg("and which stage do you want to play on after that one"))
    assert shown(calls[1]) != first

    # SEED_EXAMPLES: the seed's made-up chats in her prompt, as before her landed replies took over
    bot.examples, bot.earned[:] = seed, []
    calls.clear(); await bot.on_message(msg("anyone want to play something later"))
    first = shown(calls[0])
    assert len(first) == 8 and all(line[len("Gomihyu: "):] in {e["reply"] for e in seed} for line in first)
    assert "made-up chats" in calls[0]["messages"][0]["content"]
    # copying an example's line counts as repeating: one retry, the retry is sent
    calls.clear(); answers[:] = [seed[3]["reply"], "nah, too easy for me."]
    await bot.on_message(msg("anyone up for ranked tonight"))
    assert len(calls) == 2 and ch.sent[-1] == "nah, too easy for me.", (len(calls), ch.sent[-1])
    assert calls[1]["options"].get("temperature") == bot.RETRY_TEMPERATURE
    await r.cleanup(); print("FEWSHOT TESTS PASSED")
asyncio.run(main())

# SEED_EXAMPLES=true loads the seed; FEW_SHOT_EXAMPLES=0 turns example chats off; a missing seed warns and carries on
env = {**os.environ}
run = lambda code, **extra: subprocess.run([sys.executable, "-c", "import bot; " + code], cwd=REPO,
                                           env={**env, **extra}, capture_output=True, text=True)
out = run("print(len(bot.examples))", SEED_EXAMPLES="true"); assert out.stdout.strip().endswith("78"), out
out = run("print(len(bot.examples))", SEED_EXAMPLES="true", FEW_SHOT_EXAMPLES="0"); assert out.stdout.strip().endswith("0"), out
out = run("from pathlib import Path; print(len(bot.load_examples(Path('nope.jsonl'))))", SEED_EXAMPLES="true")
assert out.stdout.strip().endswith("0") and "No example chats at" in out.stderr, out
# training data still comes from the seed, and never gets the example block
subprocess.run([sys.executable, REPO + "/finetuning/build_dataset.py"], check=True, capture_output=True)
rows = [json.loads(l) for l in open(REPO + "/finetuning/train.jsonl")]
assert len(rows) == 78 and all(row["messages"][0]["content"] == persona.SYSTEM_PROMPT for row in rows)
os.remove(REPO + "/finetuning/train.jsonl")
print("FEWSHOT CONFIG OK")
