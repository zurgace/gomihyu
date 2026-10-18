import os as _os; REPO, TMP = _os.environ["GOMI_REPO"], _os.environ["GOMI_TMP"]  # set by tests/run_all.sh
import json, os, shutil, subprocess, sys, tempfile, threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

REPO = Path(REPO)
work = Path(tempfile.mkdtemp())
shutil.copytree(REPO, work / "repo", ignore=shutil.ignore_patterns(".git", "venv", "data"))
FT = work / "repo" / "archive" / "discord-pipeline"
PY = __import__('sys').executable

def run(*args, env=None):
    return subprocess.run([PY, *map(str, args)], capture_output=True, text=True, env={**os.environ, **(env or {})})

# ---------- step 1: extract ----------
export = work / "Messages"
def channel(cid, type_, msgs, raw=None):
    d = export / f"c{cid}"; d.mkdir(parents=True)
    (d / "channel.json").write_text(json.dumps({"id": str(cid), "type": type_}))
    (d / "messages.json").write_text(raw if raw is not None else json.dumps(
        [{"ID": i, "Timestamp": t, "Contents": c, "Attachments": ""} for i, (t, c) in enumerate(msgs)]))
# private channels hold broken JSON: reading them at all would crash the run
channel(1, "DM", [], raw="NOT JSON")
channel(2, "GROUP_DM", [], raw="NOT JSON")
channel(3, "PRIVATE_THREAD", [], raw="NOT JSON")
channel(4, "GUILD_TEXT", [
    ("2026-01-01 10:00:00", "wonder whats the best way to practice teching"),
    ("2026-01-01 10:00:30", "cuz imo thats why melee is reaction slop"),       # same burst (30s)
    ("2026-01-01 10:05:00", "<@123456789012345678> check this https://x.com/a <:joy_frog:486326828450054164> lmao so true"),
    ("2026-01-01 10:10:00", "!play never gonna give you up"),                    # bot command, dropped
    ("2026-01-01 10:20:00", "that was ||totally a spoiler|| for real <:kekpoint:1>"),
    ("2026-01-01 10:30:00", "lol"),                                              # too short
    ("2026-01-01 10:40:00", "call me at 555-123-4567 later ok"),                # phone number
    ("2026-01-01 10:50:00", "email me at someone@example.com please thanks"),     # email
    ("2026-01-01 11:00:00", "wonder whats the best way to practice teching\ncuz imo thats why melee is reaction slop"),  # duplicate
    ("2025-06-01 09:00:00", "an older message from last year here"),
    ("2026-01-01 11:10:00", "https://tenor.com/view/cat-gif"),                   # link only -> empty
    ("2026-01-01 11:20:00", ">starts business\n>stress levels skyrocket"),
])
channel(5, "PUBLIC_THREAD", [("2026-02-02 12:00:00", "thread message counts as public too")])
slur = next(l.strip() for l in (REPO / "slurs.txt").read_text().splitlines() if l.strip() and not l.startswith("#"))
channel(6, "GUILD_VOICE", [("2026-02-02 12:00:00", f"this one has {slur} in it though")])

r = run(FT / "extract.py", export)
assert r.returncode == 0, r.stderr
print(r.stdout)
rows = [json.loads(l) for l in (FT / "data" / "replies.jsonl").read_text().splitlines()]
got = [row["reply"] for row in rows]
assert got == ["an older message from last year here",
               "wonder whats the best way to practice teching\ncuz imo thats why melee is reaction slop",
               "check this lmao so true",
               "that was totally a spoiler for real :kekpoint:",
               ">starts business\n>stress levels skyrocket",
               "thread message counts as public too"], got
assert "'DM': 1" in r.stdout and "'GROUP_DM': 1" in r.stdout and "'PRIVATE_THREAD': 1" in r.stdout
assert "'slur': 1" in r.stdout and "'email/phone number': 2" in r.stdout and "'duplicate': 1" in r.stdout
r = run(FT / "extract.py", export, "--since", "2026")
assert "an older message" not in (FT / "data" / "replies.jsonl").read_text()
run(FT / "extract.py", export)
print("EXTRACT OK")

# ---------- step 2: backtranslate, against a fake Ollama ----------
calls = []
ANSWERS = {  # reply text -> what the fake model says
    "check this lmao so true": '{"messages": ["bro look at this tweet"]}',
    "that was totally a spoiler for real :kekpoint:": "not json at all",
    "an older message from last year here": json.dumps({"messages": [f"you {slur}"]}),
    ">starts business\n>stress levels skyrocket": '{"messages": ["starts business stress levels skyrocket lol"]}',
}
class Fake(BaseHTTPRequestHandler):
    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        calls.append(body)
        reply = body["messages"][1]["content"].split("\n", 1)[1]
        content = ANSWERS.get(reply, '{"messages": ["what do you guys think", "yeah tell us"]}')
        out = json.dumps({"message": {"role": "assistant", "content": content}, "done": True}).encode()
        self.send_response(200); self.send_header("Content-Type", "application/json"); self.end_headers(); self.wfile.write(out)
    def log_message(self, *a): pass
server = HTTPServer(("127.0.0.1", 8791), Fake); threading.Thread(target=server.serve_forever, daemon=True).start()
env = {"OLLAMA_URL": "http://127.0.0.1:8791/api/chat", "OLLAMA_MODEL": "gemma4:e4b"}

r = run(FT / "backtranslate.py", "--limit", "3", env=env)
assert r.returncode == 0, r.stderr
first = (FT / "data" / "examples.jsonl").read_text().splitlines()
assert all(c["think"] is False and c["format"]["properties"]["messages"]["maxItems"] == 3 for c in calls)
assert all(c["model"] == "gemma4:e4b" for c in calls)
n_calls = len(calls)
r = run(FT / "backtranslate.py", "--limit", "3", env=env)        # resume: nothing new to do
assert "2 examples already written, 1 rejected before, 0 to go" in r.stdout and len(calls) == n_calls, r.stdout
rej = [json.loads(l) for l in (FT / "data" / "rejected.jsonl").read_text().splitlines()]
assert [x["reason"] for x in rej] == ["copied the reply"]
assert sum(c["messages"][1]["content"].endswith(rej[0]["reply"]) for c in calls) == 2  # asked twice before giving up
r = run(FT / "backtranslate.py", env=env)                          # bigger limit extends the smaller one
print(r.stdout)
ex = [json.loads(l) for l in (FT / "data" / "examples.jsonl").read_text().splitlines()]
assert (FT / "data" / "examples.jsonl").read_text().splitlines()[:len(first)] == first
by_reply = {e["reply"]: e for e in ex}
assert "that was totally a spoiler for real :kekpoint:" not in by_reply            # bad JSON
assert "an older message from last year here" not in by_reply                     # slur in context
assert ">starts business\n>stress levels skyrocket" not in by_reply                # copied the reply
assert "'no usable answer': 1" in r.stdout and "'slur in context': 1" in r.stdout and "copied" not in r.stdout
e = by_reply["check this lmao so true"]
assert e["history"][-1][1].endswith("bro look at this tweet") and e["history"][0][0] in ["kaz0", "norimaki", "mintchoco", "sleepyfox", "jake.b"]
two = by_reply["thread message counts as public too"]["history"]
assert len(two) == 2 and all(h in ["kaz0", "norimaki", "mintchoco", "sleepyfox", "jake.b"] for h, _ in two)
# same reply -> same friends and same ping decision, every run
assert run(FT / "backtranslate.py", env=env).returncode == 0
import importlib.util
spec = importlib.util.spec_from_file_location("bt", FT / "backtranslate.py"); bt = importlib.util.module_from_spec(spec)
sys.path.insert(0, str(work / "repo")); spec.loader.exec_module(bt)
assert bt.example("x y z", ["a"]) == bt.example("x y z", ["a"])
pinged = sum(bt.example(f"reply {i}", ["hey"])["history"][-1][1].startswith("@Gomihyu ") for i in range(400))
assert 60 < pinged < 140, pinged
server.shutdown()
r = run(FT / "backtranslate.py", "--limit", "10", env={"OLLAMA_URL": "http://127.0.0.1:1/api/chat"})
(FT / "data" / "examples.jsonl").write_text(""); (FT / "data" / "rejected.jsonl").write_text("")  # force work
r = run(FT / "backtranslate.py", "--limit", "1", env={"OLLAMA_URL": "http://127.0.0.1:1/api/chat"})
assert r.returncode != 0 and "Couldn't reach Ollama" in r.stderr, (r.stdout, r.stderr)
print("BACKTRANSLATE OK")

# ---------- step 3: build ----------
(FT / "data" / "examples.jsonl").write_text("\n".join(json.dumps(x, ensure_ascii=False) for x in ex) + "\n")
r = run(FT / "build_dataset.py")
assert r.returncode == 0, r.stderr
train = [json.loads(l) for l in (FT / "data" / "train.jsonl").read_text().splitlines()]
assert len(train) == len(ex)
for row, x in zip(train, ex):
    roles = [m["role"] for m in row["messages"]]
    assert roles == ["system", "user", "assistant"] and row["messages"][2]["content"] == x["reply"]
    assert ("directly mentioned" in row["messages"][1]["content"]) == x["history"][-1][1].startswith("@Gomihyu")
r = run(FT / "build_dataset.py", FT / "data" / "examples.jsonl", work / "repo" / "finetuning" / "gomihyu_seed.jsonl")
assert f"Wrote {len(ex) + 108} examples" in r.stdout, r.stdout
print("BUILD OK")
shutil.rmtree(work)
