import os as _os; REPO, TMP = _os.environ["GOMI_REPO"], _os.environ["GOMI_TMP"]  # set by tests/run_all.sh
# tools/vision_check.py against fake Ollamas: one that sees, one with the blank-image bug, a missing model, none.
import asyncio, base64, json, os, subprocess, sys, zlib, threading
from aiohttp import web
SCRIPT = REPO + "/tools/vision_check.py"
NAMES = {(230, 20, 20): "Red", (20, 170, 40): "Green.", (20, 40, 230): "blue", (250, 220, 20): "Yellow"}
def colour(b64):
    png = base64.b64decode(b64)
    assert png.startswith(b"\x89PNG") and b"IHDR" in png and b"IEND" in png
    raw = zlib.decompress(png[png.index(b"IDAT") + 4:png.index(b"IEND") - 8])
    return tuple(raw[1:4])
seen = []
def make(mode):
    async def handler(request):
        body = await request.json(); seen.append(body)
        if mode == "missing": return web.json_response({"error": "model 'gemma4:e4b' not found"}, status=404)
        rgb = colour(body["messages"][0]["images"][0])
        answer = NAMES[rgb] if mode == "sees" else ("Black" if mode == "blank" else "Purple")
        return web.json_response({"message": {"content": answer}, "done": True})
    return handler
def serve(mode, port):
    loop = asyncio.new_event_loop()
    app = web.Application(); app.router.add_post("/api/chat", make(mode))
    runner = web.AppRunner(app); loop.run_until_complete(runner.setup())
    loop.run_until_complete(web.TCPSite(runner, "127.0.0.1", port).start())
    threading.Thread(target=loop.run_forever, daemon=True).start()
def run(port):
    env = dict(os.environ, OLLAMA_URL=f"http://127.0.0.1:{port}/api/chat", OLLAMA_MODEL="gemma4:e4b")
    r = subprocess.run([sys.executable, SCRIPT], capture_output=True, text=True, env=env, timeout=60)
    return r.returncode, r.stdout
for i, mode in enumerate(["sees", "blank", "missing", "wrong"]):
    serve(mode, 8750 + i)
code, out = run(8750); print(out)
assert code == 0 and "She can see" in out and out.count("right") >= 4
b = seen[0]
assert b["model"] == "gemma4:e4b" and b["think"] is False and b["stream"] is False and b["options"]["num_ctx"] == 8192
code, out = run(8751); print(out)
assert code == 1 and "blank-image bug" in out and out.count("WRONG") == 4
code, out = run(8752); print(out)
assert code == 2 and "HTTP 404" in out and "not found" in out
code, out = run(8753); print(out)
assert code == 1 and "Only 0 of 4 right" in out
code, out = run(8799); print(out)                                    # nothing listening
assert code == 2 and "Couldn't reach Ollama" in out
print("VISION CHECK TESTS PASSED")
