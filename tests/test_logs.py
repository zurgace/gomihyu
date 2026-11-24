import os as _os; REPO, TMP = _os.environ["GOMI_REPO"], _os.environ["GOMI_TMP"]  # set by tests/run_all.sh
import asyncio, os, sys, types, logging
from aiohttp import web
os.environ["PEOPLE_FILE"] = TMP + "/people_test_logs.json"; os.environ["DISCORD_BOT_TOKEN"] = "fake"; os.environ["OLLAMA_URL"] = "http://127.0.0.1:8766/api/chat"
sys.path.insert(0, REPO)
import aiohttp
from gomi import bot
logging.getLogger("aiohttp.access").setLevel(logging.WARNING)

mode = {"v": None}
async def fake(request):
    m = mode["v"]
    if m == "404": return web.json_response({"error": "model 'hf.co/lmstudio-community/LFM2.5-2.6B-GGUF:Q4_K_M' not found"}, status=404)
    if m == "empty": return web.json_response({"model": "x", "message": {"role": "assistant", "content": "", "thinking": "hmm..."}, "done_reason": "stop", "eval_count": 3})
    if m == "slow": await asyncio.sleep(2)
    return web.json_response({"message": {"role": "assistant", "content": "Gomihyu: Bow before me!"}, "done_reason": "stop", "eval_count": 9})

async def main():
    app = web.Application(); app.router.add_post("/api/chat", fake)
    r = web.AppRunner(app); await r.setup(); await web.TCPSite(r, "127.0.0.1", 8766).start()
    bot.history[1].append("kaz0: hi"); bot.last_author[1] = (7, "kaz0")
    for m in ["ok", "404", "empty"]:
        mode["v"] = m; print(f"--- {m}:", repr(await bot.generate_reply(1, False)))
    mode["v"] = "slow"; real = aiohttp.ClientTimeout
    aiohttp.ClientTimeout = lambda total: real(total=0.5)  # stand-in for the 60s limit
    print("--- timeout:", repr(await bot.generate_reply(1, False))); aiohttp.ClientTimeout = real
    bot.OLLAMA_URL = "http://127.0.0.1:1/api/chat"
    print("--- ollama down:", repr(await bot.generate_reply(1, False)))
    await r.cleanup()
asyncio.run(main())
