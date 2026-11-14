"""Fresh interpreters, synthetic .env files and an in-process fake HTTP transport only."""

import os
from pathlib import Path
import shutil
import subprocess
import sys

REPO, TMP = Path(os.environ["GOMI_REPO"]), Path(os.environ["GOMI_TMP"])
repo = TMP / "checker-isolation"
repo.mkdir()
# Copy the import graph's source, never saved configuration, examples, logs or models.
for name in ("persona.py", "shape.py", "emojis.py", "reactions.py", "chatlog.py", "chime.py",
             "diary.py", "meld.py", "censor.py", "finetuning/weekly.py", "finetuning/build_dataset.py",
             "tools/chat_check.py", "tools/vision_check.py"):
    dest = repo / name
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(REPO / name, dest)
(repo / "slurs.txt").write_text("syntheticforbiddenword\n")
(repo / ".env").write_text(
    "GOMI_DOTENV_SENTINEL=synthetic-loaded\n"
    "OLLAMA_URL=http://dotenv.invalid:12123/api/chat\n"
    "OLLAMA_MODEL=synthetic-dotenv-model\n"
    "OLLAMA_THINK=true\nOLLAMA_NUM_CTX=9999\nMAX_REPLY_TOKENS=999\n")

SETTINGS = {"OLLAMA_MODEL": "synthetic-inherited-model", "OLLAMA_THINK": "false",
            "OLLAMA_NUM_CTX": "4096", "MAX_REPLY_TOKENS": "123"}
ENV = {key: value for key, value in os.environ.items()
       if not key.startswith("OLLAMA_") and key not in (*SETTINGS, "GOMI_DOTENV_SENTINEL")}
ENV.update(PYTHONPATH=os.pathsep.join((str(repo / "tools"), str(repo))),
           PYTHONDONTWRITEBYTECODE="1")

COMMON = r'''
import base64, io, json, os, re, runpy, sys, urllib.request, zlib
from pathlib import Path
repo = Path.cwd()
dotenv_reads, requests = [], []
def audit(event, args):
    if event == "open" and str(args[0]) == str(repo / ".env"):
        dotenv_reads.append(str(args[0]))
sys.addaudithook(audit)
def fake_urlopen(request, timeout):
    # This replacement never opens a socket, including if the checker chooses the wrong endpoint.
    body = json.loads(request.data) if request.data else None
    requests.append((request.full_url, body))
    if request.full_url.endswith("/api/tags"):
        result = {"models": [{"name": "synthetic-model:latest", "digest": "synthetic-digest"}]}
    elif body and body["messages"][0].get("images"):
        png = base64.b64decode(body["messages"][0]["images"][0])
        pos, compressed = 8, b""
        while pos < len(png):
            size = int.from_bytes(png[pos:pos + 4], "big")
            if png[pos + 4:pos + 8] == b"IDAT":
                compressed += png[pos + 8:pos + 8 + size]
            pos += size + 12
        rgb = tuple(zlib.decompress(compressed)[1:4])
        colour = {(230, 20, 20): "red", (20, 170, 40): "green",
                  (20, 40, 230): "blue", (250, 220, 20): "yellow"}[rgb]
        result = {"message": {"content": colour}}
    else:
        result = {"model": "synthetic-model:latest", "message": {"content": "A synthetic answer."}}
    return io.BytesIO(json.dumps(result).encode())
urllib.request.urlopen = fake_urlopen
'''


def fresh(code, label, extra=None, settings=True):
    env = ENV | (SETTINGS if settings else {}) | (extra or {})
    result = subprocess.run([sys.executable, "-c", COMMON + code], cwd=repo, env=env,
                            text=True, capture_output=True, timeout=30)
    assert result.returncode == 0, f"{label}:\n{result.stdout}\n{result.stderr}"


# Each import is tested in its own process: an earlier import cannot hide dotenv's side effect.
for module in ("chat_check", "finetuning.weekly"):
    fresh(f'''
before = {{key: os.environ[key] for key in {tuple(SETTINGS)!r}}}
__import__({module!r})
assert not dotenv_reads, "import read synthetic .env"
assert "GOMI_DOTENV_SENTINEL" not in os.environ, "import loaded unrelated .env sentinel"
assert {{key: os.environ[key] for key in before}} == before
assert "vision_check" not in sys.modules
assert not requests
''', f"fresh {module} import")


for label, extra, cli, endpoint, source in (
        ("default", {}, [], "http://localhost:11434/api/chat", "default"),
        ("environment", {"OLLAMA_URL": "http://inherited.invalid:12234/api/chat"}, [],
         "http://inherited.invalid:12234/api/chat", "OLLAMA_URL"),
        ("explicit", {"OLLAMA_URL": "http://inherited.invalid:12234/api/chat"},
         ["--url", "http://explicit.invalid:12345/api/chat"],
         "http://explicit.invalid:12345/api/chat", "--url")):
    fresh(fr'''
import chat_check
report = repo / {label + '.md'!r}
assert chat_check.main(["synthetic-model", "--seeds", "17", "--no-think", "--output", str(report)]
                       + {cli!r}) == 0
assert len(requests) == 7
assert requests[0][0] == {endpoint!r}.rsplit("/api/", 1)[0] + "/api/tags"
assert all(url == {endpoint!r} for url, body in requests[1:])
assert all(body["think"] is False and body["options"]["num_ctx"] == 8192
           and body["options"]["num_predict"] == 200 for url, body in requests[1:])
records = [json.loads(block) for block in re.findall(r"```json\n(.*?)\n```", report.read_text(), re.DOTALL)]
assert records[0]["endpoint"] == {endpoint!r}
assert records[0]["endpoint_source"] == {source!r}
assert not dotenv_reads and "GOMI_DOTENV_SENTINEL" not in os.environ
assert "vision_check" not in sys.modules
''', f"fresh checker {label} endpoint", extra)


# Deferring the import preserves both the standalone CLI's .env contract and weekly's colour check.
fresh(r'''
sys.argv = [str(repo / "tools" / "vision_check.py")]
try:
    runpy.run_path(sys.argv[0], run_name="__main__")
except SystemExit as error:
    assert error.code == 0
else:
    raise AssertionError("vision CLI did not exit")
assert dotenv_reads and os.environ["GOMI_DOTENV_SENTINEL"] == "synthetic-loaded"
assert len(requests) == 4
assert all(url == "http://dotenv.invalid:12123/api/chat" and body["model"] == "synthetic-dotenv-model"
           and body["think"] is False and body["options"]["num_ctx"] == 9999 for url, body in requests)
''', "standalone vision CLI", settings=False)

fresh(r'''
from finetuning import weekly
assert not dotenv_reads and "vision_check" not in sys.modules
assert weekly.sees("synthetic-weekly-model")
assert dotenv_reads and os.environ["GOMI_DOTENV_SENTINEL"] == "synthetic-loaded"
assert len(requests) == 2
assert all(url == "http://dotenv.invalid:12123/api/chat" and body["model"] == "synthetic-weekly-model"
           and body["think"] is False and body["options"]["num_ctx"] == 9999 for url, body in requests)
''', "weekly deferred vision check", settings=False)

print("CHAT CHECK ISOLATION TESTS PASSED")
