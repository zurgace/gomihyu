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
assert len(bot.examples) == 58 == len(seed)

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

    # 8 example chats in the system prompt, the chat log and instruction untouched
    await bot.on_message(msg("what games should we play this saturday"))
    first = shown(calls[0])
    assert len(first) == 8 and all(line[len("Gomihyu: "):] in {e["reply"] for e in seed} for line in first)
    assert "made-up chats" in calls[0]["messages"][0]["content"]
    plain = persona.build_messages(list(bot.history[12])[:-1], False, "rexmode")
    assert calls[0]["messages"][1] == plain[1]
    # a fresh pick for the next reply
    await bot.on_message(msg("ok but which character though"))
    assert shown(calls[1]) != first

    # copying an example's line counts as repeating: one retry, the retry is sent
    calls.clear(); answers[:] = [seed[3]["reply"], "nah, too easy for me."]
    await bot.on_message(msg("anyone up for ranked tonight"))
    assert len(calls) == 2 and ch.sent[-1] == "nah, too easy for me.", (len(calls), ch.sent[-1])
    assert calls[1]["options"].get("temperature") == bot.RETRY_TEMPERATURE
    await r.cleanup(); print("FEWSHOT TESTS PASSED")
asyncio.run(main())

# FEW_SHOT_EXAMPLES=0 turns them off; a missing file warns and carries on
env = {**os.environ}
out = subprocess.run([sys.executable, "-c", "import bot; print(len(bot.examples))"], cwd=REPO,
                     env={**env, "FEW_SHOT_EXAMPLES": "0"}, capture_output=True, text=True)
assert out.stdout.strip().endswith("0"), out
out = subprocess.run([sys.executable, "-c", "import bot; print(len(bot.examples))"], cwd=REPO,
                     env={**env, "EXAMPLES_FILE": "nope.jsonl"}, capture_output=True, text=True)
assert out.stdout.strip().endswith("0") and "No example chats at" in out.stderr, out
# training data never gets the example block
subprocess.run([sys.executable, REPO + "/finetuning/build_dataset.py"], check=True, capture_output=True)
rows = [json.loads(l) for l in open(REPO + "/finetuning/train.jsonl")]
assert len(rows) == 58 and all(row["messages"][0]["content"] == persona.SYSTEM_PROMPT for row in rows)
os.remove(REPO + "/finetuning/train.jsonl")
print("FEWSHOT CONFIG OK")
