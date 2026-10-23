"""
Her weekly fine-tune: the server melds into her voice one training run at a time, on Kaggle's free GPU
(user, 2026-09-29: "running the fine tuning once a week on gomi to slowly meld the personality").

    venv/bin/python finetuning/weekly.py status    # the runs so far, what she runs on, what's next
    venv/bin/python finetuning/weekly.py build     # this week's data, if there's enough new
    venv/bin/python finetuning/weekly.py upload    # to Kaggle (private) and start the training there
    venv/bin/python finetuning/weekly.py fetch     # wait for it, download her model, delete the data on Kaggle
    venv/bin/python finetuning/weekly.py install   # into Ollama as gomi-wN
    venv/bin/python finetuning/weekly.py check     # gomi-wN next to what she runs on now
    venv/bin/python finetuning/weekly.py switch    # her voice becomes gomi-wN (edits .env); restart the bot
    venv/bin/python finetuning/weekly.py rollback  # back to what she ran on before the last switch
    venv/bin/python finetuning/weekly.py all       # build through check in one go; never switches

What keeps it safe to repeat every week:
- Every run trains the stock Gemma 4 E4B again, on all the data so far, never last week's model: the
  changes don't pile up, her own habits don't feed on themselves, and any run can be redone.
- The data's mix is the meld: run N is meld.persona_share(N) Satania, 70% at run 1 down to
  MELD_ANCHOR (30%) at run MELD_RUNS (11), then stays there. Skipped weeks pause it.
- A week with fewer than --min-new (WEEKLY_MIN_NEW, 50) new examples from the server (her landed
  replies plus people's messages) since the last run isn't worth a run: build says so and stops.
- Each run's model stays in Ollama as gomi-w1, gomi-w2, ...; switch and rollback only edit .env, and
  switch wants a check first.
- Her pictures, reading the room and her diary can stay on the stock model (VISION_MODEL, TASK_MODEL):
  the fine-tune is text only, and trained for her voice, not for those jobs.

Needs the Kaggle CLI in the venv (venv/bin/pip install kaggle) and your Kaggle API token (kaggle.com >
Settings > API; Kaggle wants a verified phone number for GPUs and internet), and ollama on PATH.
Everything it keeps is in finetuning/runs/ (gitignored: it holds real chat): runs.json and a folder per
run with the uploaded data, the downloaded model, the Modelfile and the check's report.
"""

import argparse
import json
import os
import random
import re
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path[:0] = [str(ROOT), str(HERE), str(ROOT / "tools")]

from dotenv import load_dotenv  # noqa: E402

import build_dataset  # noqa: E402  (finetuning/build_dataset.py)
import vision_check  # noqa: E402  (tools/vision_check.py)
from chatlog import ChatLog, local_day  # noqa: E402
from chime import parse_room, room_format, room_messages  # noqa: E402
from diary import Diary, digest_format, digest_messages, parse_digest  # noqa: E402
from emojis import UNICODE  # noqa: E402
from meld import MELD_RUNS, persona_share, pick_examples  # noqa: E402
from persona import build_messages, format_line  # noqa: E402
from reactions import names_her  # noqa: E402

RUNS = HERE / "runs"
STATE = RUNS / "runs.json"
ENV = ROOT / ".env"
CHECK_CHATS = HERE / "check_chats.jsonl"
TRAIN_SCRIPT = HERE / "kaggle_train.py"
# On Kaggle, under your username, both private: a dataset per run (deleted once the model is downloaded)
# and one notebook, which gets a new version each run.
DATASET, KERNEL = "gomi-meld-w{run}", "gomi-meld"
STOCK = "gemma4:e4b"  # the stock model in Ollama; gomi-wN takes its chat template and settings
BASE = "unsloth/gemma-4-E4B-it"  # the same model on Hugging Face, which Kaggle trains from
ACCELERATOR = "NvidiaTeslaT4"  # Unsloth doesn't run on Kaggle's other free GPU, the P100
STAGES = ["built", "training", "fetched", "installed", "checked"]
SWITCHED_KEYS = ["OLLAMA_MODEL", "FEW_SHOT_EXAMPLES", "VISION_MODEL", "TASK_MODEL"]
THINK = re.compile(r"<think>.*?(</think>|$)", re.DOTALL)


class Stop(Exception):
    """A step that can't go on; the message says why and what to do."""


def setting(key: str, default: str) -> str:
    return os.environ.get(key, "").strip() or default


def ollama_url(path: str) -> str:
    return setting("OLLAMA_URL", "http://localhost:11434/api/chat").rsplit("/api/", 1)[0] + path


# --- state: finetuning/runs/runs.json

def load_state() -> dict:
    return json.loads(STATE.read_text(encoding="utf-8")) if STATE.exists() else {"runs": [], "switches": []}


def save_state(state: dict) -> None:
    RUNS.mkdir(parents=True, exist_ok=True)
    tmp = STATE.with_name(STATE.name + ".tmp")
    tmp.write_text(json.dumps(state, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    os.replace(tmp, STATE)


def reached(run: dict, stage: str) -> bool:
    return STAGES.index(run["stage"]) >= STAGES.index(stage)


def pick_run(state: dict, stage: str, number: int | None = None) -> dict:
    """The run a step works on: --run N, else the newest that has reached `stage`."""
    runs = [r for r in state["runs"] if (r["run"] == number if number else reached(r, stage))]
    if not runs:
        raise Stop(f"No run {number} built yet." if number else f"No run has got as far as '{stage}' yet: see "
                   "weekly.py status.")
    return runs[-1]


def folder(run: dict) -> Path:
    return RUNS / f"w{run['run']}"


# --- .env

def env_get(key: str) -> str | None:
    for line in ENV.read_text(encoding="utf-8").splitlines() if ENV.exists() else []:
        if match := re.match(rf"\s*{key}\s*=(.*)$", line):
            return match.group(1).strip().strip("\"'")
    return None


def env_set(values: dict[str, str | None]) -> None:
    """Sets (or with None, removes) these keys in .env, keeping every other line as it is."""
    out, done = [], set()
    for line in ENV.read_text(encoding="utf-8").splitlines() if ENV.exists() else []:
        match = re.match(r"\s*([A-Za-z_]\w*)\s*=", line)
        if match and match.group(1) in values:
            key = match.group(1)
            if key not in done and values[key] is not None:
                out.append(f"{key}={values[key]}")
            done.add(key)
            continue
        out.append(line)
    out += [f"{key}={value}" for key, value in values.items() if key not in done and value is not None]
    ENV.write_text("\n".join(out) + "\n", encoding="utf-8")


# --- the outside world: Kaggle's CLI, ollama's CLI and Ollama's API

def kaggle(*args: str, check: bool = True) -> subprocess.CompletedProcess:
    beside = Path(sys.executable).with_name("kaggle")
    exe = str(beside) if beside.exists() else shutil.which("kaggle")
    if not exe:
        raise Stop("The Kaggle CLI isn't installed: venv/bin/pip install kaggle")
    # The CLI reads every KAGGLE_* variable as its own setting: an empty one would blank out your login.
    env = {key: value for key, value in os.environ.items() if value or not key.startswith("KAGGLE_")}
    done = subprocess.run([exe, *args], capture_output=True, text=True, env=env)
    if check and done.returncode:
        raise Stop(f"kaggle {' '.join(args)} failed:\n{(done.stdout + done.stderr).strip()[-1500:]}")
    return done


def kaggle_user() -> str:
    user = setting("WEEKLY_KAGGLE_USER", "") or setting("KAGGLE_USERNAME", "")
    if not user:
        match = re.search(r"username:\s*(\S+)", kaggle("config", "view", check=False).stdout)
        user = match.group(1) if match and match.group(1) != "None" else ""
    if not user:
        raise Stop("Couldn't tell your Kaggle username: put WEEKLY_KAGGLE_USER=<yours> in .env (it's in your "
                   "kaggle.com profile's address).")
    return user


def api(path: str, body: dict | None = None, timeout: float = 300) -> dict:
    request = urllib.request.Request(ollama_url(path), json.dumps(body).encode() if body is not None else None,
                                     {"Content-Type": "application/json"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.load(response)


def thinks() -> bool:
    """Whether her replies think first (OLLAMA_THINK); reading the room and the diary never do."""
    return setting("OLLAMA_THINK", "false").lower() in ("1", "true", "yes", "on")


def chat(model: str, messages: list[dict], fmt: dict | None = None, options: dict | None = None,
         think: bool = False) -> str | None:
    """One answer from Ollama, the way the bot asks; None (and why, printed) if there's none."""
    body = {"model": model, "messages": messages, "stream": False, "think": think,
            "options": {"num_ctx": int(setting("OLLAMA_NUM_CTX", "8192"))} | (options or {})}
    if fmt:
        body["format"] = fmt
    try:
        content = api("/api/chat", body).get("message", {}).get("content", "")
    except (urllib.error.URLError, OSError, ValueError) as e:
        detail = e.read().decode(errors="replace")[:200] if isinstance(e, urllib.error.HTTPError) else e
        print(f"  {model}: no answer ({detail})")
        return None
    return THINK.sub("", content).strip()


# --- the steps

def cmd_build(args) -> bool:
    state = load_state()
    done = [r for r in state["runs"] if reached(r, "installed")]
    unfinished = state["runs"] and not reached(state["runs"][-1], "installed")
    if unfinished:
        number = state["runs"][-1]["run"]  # built or trained but never installed: built again, same number
    elif args.redo and done:
        number = done[-1]["run"]
        if env_get("OLLAMA_MODEL") == done[-1].get("model"):
            print(f"She runs on {done[-1]['model']} now: installing the redo will replace it under her.")
    else:
        number = done[-1]["run"] + 1 if done else 1
    before = next((r for r in reversed(done) if r["run"] < number), {"landed": 0, "voice": 0})

    chat_log = ChatLog(ROOT / setting("CHAT_LOG_DIR", "chatlogs"))
    earned = build_dataset.read_jsonl(ROOT / setting("EARNED_FILE", "earned_examples.jsonl"))
    voice = len(build_dataset.voice_pool(chat_log))
    new = len(earned) - before["landed"] + voice - before["voice"]
    since = f"run {before['run']}" if "run" in before else "the start"
    if new < args.min_new and not args.force:
        print(f"Only {new} new examples from the server since {since} ({len(earned) - before['landed']} landed "
              f"replies, {voice - before['voice']} messages); a run wants {args.min_new} (--min-new). Skipping this "
              "week: the meld just pauses. --force builds anyway.")
        return False

    anchor, runs = float(setting("MELD_ANCHOR", "0.3")), int(setting("MELD_RUNS", str(MELD_RUNS)))
    seed = build_dataset.read_jsonl(build_dataset.SEED)
    rows, summary = build_dataset.meld_examples(seed, number, None, 3, chat_log, earned, anchor, runs)
    upload = RUNS / f"w{number}" / "upload"
    shutil.rmtree(upload, ignore_errors=True)
    upload.mkdir(parents=True)
    (upload / "train.jsonl").write_text("".join(json.dumps(build_dataset.render(row), ensure_ascii=False) + "\n"
                                                for row in rows), encoding="utf-8")
    config = {"run": number, "base": args.base, "epochs": args.epochs, "rank": args.rank, "lr": args.lr,
              "max_len": args.max_len, "quant": args.quant}
    (upload / "run.json").write_text(json.dumps(config, indent=2) + "\n")
    record = {"run": number, "built": local_day(time.time()), "stage": "built", "examples": len(rows),
              "landed": len(earned), "voice": voice, "share": persona_share(number, anchor, runs),
              "summary": summary, "config": config}
    state["runs"] = [r for r in state["runs"] if r["run"] != number] + [record]
    save_state(state)
    print(f"Built run {number} ({new} new from the server since {since}): {summary}")
    return True


def cmd_upload(args) -> bool:
    state = load_state()
    run = state["runs"][-1] if state["runs"] else None
    if not run or reached(run, "fetched"):
        raise Stop("Nothing built to upload: weekly.py build first.")
    user, number = kaggle_user(), run["run"]
    dataset = f"{user}/{DATASET.format(run=number)}"
    upload = folder(run) / "upload"
    (upload / "dataset-metadata.json").write_text(json.dumps(
        {"title": DATASET.format(run=number), "id": dataset, "licenses": [{"name": "other"}]}, indent=2) + "\n")
    status = kaggle("datasets", "status", dataset, check=False)
    if status.returncode == 0 and not re.search(r"404|not found", status.stdout + status.stderr, re.I):
        print(f"Uploading run {number}'s data to Kaggle again (a new version of {dataset}; the old one deleted)")
        kaggle("datasets", "version", "-p", str(upload), "-m", f"run {number}", "-d")
    else:
        print(f"Uploading run {number}'s data to Kaggle as a private dataset, {dataset}")
        kaggle("datasets", "create", "-p", str(upload))
    for _ in range(60):  # Kaggle processes an upload before a notebook can use it
        if "ready" in kaggle("datasets", "status", dataset, check=False).stdout.lower():
            break
        time.sleep(args.poll / 6)
    else:
        raise Stop("Kaggle hasn't finished processing the upload after a while; run weekly.py upload again later.")

    kernel = folder(run) / "kernel"
    kernel.mkdir(exist_ok=True)
    script = re.sub(r"^RUN = \d+.*$", f"RUN = {number}", TRAIN_SCRIPT.read_text(encoding="utf-8"), count=1,
                    flags=re.MULTILINE)
    (kernel / TRAIN_SCRIPT.name).write_text(script, encoding="utf-8")
    (kernel / "kernel-metadata.json").write_text(json.dumps(
        {"id": f"{user}/{KERNEL}", "title": KERNEL, "code_file": TRAIN_SCRIPT.name, "language": "python",
         "kernel_type": "script", "is_private": True, "enable_gpu": True, "enable_internet": True,
         "machine_shape": args.accelerator, "dataset_sources": [dataset], "competition_sources": [],
         "kernel_sources": [], "model_sources": []}, indent=2) + "\n")
    kaggle("kernels", "push", "-p", str(kernel), "--accelerator", args.accelerator)
    run.update(stage="training", pushed=time.time())
    run.pop("error", None)
    run.pop("seen_running", None)
    save_state(state)
    print(f"Training run {number} on Kaggle: https://www.kaggle.com/code/{user}/{KERNEL} (about an hour). "
          "Then: weekly.py fetch")
    return True


def cmd_fetch(args) -> bool:
    state = load_state()
    run = next((r for r in reversed(state["runs"]) if r["stage"] == "training"), None)
    if not run:
        raise Stop("Nothing is training: weekly.py status.")
    user, number = kaggle_user(), run["run"]
    notebook = f"{user}/{KERNEL}"
    deadline, last = time.time() + args.wait_hours * 3600, None
    while True:
        said = kaggle("kernels", "status", notebook, check=False)
        text = (said.stdout + said.stderr).lower().replace(notebook.lower(), "")  # "<you>/gomi-meld has status ..."
        if said.returncode:  # couldn't ask (network, Kaggle down): not the run's status
            status = f"unknown ({(said.stdout + said.stderr).strip()[-200:]})"
        else:
            failed = re.search(r"error|cancel|fail", text)
            status = "complete" if "complete" in text else "failed" if failed else "running"
        if status != last:
            print(f"Kaggle: {status} ({time.strftime('%H:%M')})")
            last = status
        if status == "running" and not run.get("seen_running"):
            run["seen_running"] = True  # kept: a second fetch then needn't wait for it again
            save_state(state)
        # Right after a push, the status can still be the previous run's; the result's run number decides.
        if status in ("complete", "failed") and (run.get("seen_running") or time.time() - run.get("pushed", 0) > 300):
            break
        if time.time() > deadline:
            print("Still training. Run weekly.py fetch again later.")
            return False
        time.sleep(args.poll)

    out = folder(run) / "out"
    shutil.rmtree(out, ignore_errors=True)
    print("Downloading what the run made (the model is a few GB)")
    kaggle("kernels", "output", notebook, "-p", str(out), "-o")
    result_file = out / "result.json"
    result = json.loads(result_file.read_text()) if result_file.exists() else {}
    log = next(out.glob("*.log"), None)
    if not result and status == "failed" and run.get("seen_running"):  # killed by Kaggle (time, memory, disk)
        run["error"] = "stopped without a result.json; see its log"
        save_state(state)
        raise Stop(f"Run {number} failed on Kaggle without saying why. Its log: {log or 'not downloaded'} (the "
                   "error is near the end). Fix it, then weekly.py upload to try again.")
    if result.get("run") != number:
        print(f"Kaggle's output isn't run {number}'s yet (it says run {result.get('run')}); weekly.py fetch again "
              "in a few minutes.")
        return False
    if result.get("error"):
        run["error"] = result["error"]
        save_state(state)
        raise Stop(f"Run {number} failed on Kaggle: {result['error']}\nIts log: {log or 'not downloaded'}. "
                   "Fix it, then weekly.py upload to try again.")
    if not (out / str(result.get("gguf"))).is_file():
        raise Stop(f"Run {number} says it's done, but its model file isn't in {out}. Log: {log}")
    run.update(stage="fetched", result=result)
    save_state(state)
    print(f"Run {number}: {result.get('examples')} examples, loss {result.get('loss')}, "
          f"{result.get('minutes')} min on a {result.get('gpu')}.")
    dataset = f"{user}/{DATASET.format(run=number)}"
    if args.keep_cloud_data:
        print(f"The data stays on Kaggle ({dataset}, private) as asked.")
    elif kaggle("datasets", "delete", dataset, "-y", check=False).returncode == 0:
        print(f"Deleted {dataset} from Kaggle: the server's chat isn't kept there.")
    else:
        print(f"Couldn't delete the data on Kaggle; delete {dataset} on kaggle.com yourself.")
    return True


def modelfile(stock_modelfile: str, gguf: Path) -> str:
    """The stock model's Modelfile (chat template, stop words, settings) on her weights."""
    lines, quoted = [f"FROM {gguf.resolve()}"], False
    for line in stock_modelfile.splitlines():
        if not quoted and (line.startswith("#") or re.match(r"FROM\s", line, re.I)):
            continue
        quoted ^= line.count('"""') % 2 == 1
        lines.append(line)
    return "\n".join(lines).strip() + "\n"


def cmd_install(args) -> bool:
    state = load_state()
    run = pick_run(state, "fetched", args.run)
    if not reached(run, "fetched"):
        raise Stop(f"Run {run['run']} hasn't been fetched: weekly.py fetch.")
    gguf = folder(run) / "out" / run["result"]["gguf"]
    name = f"gomi-w{run['run']}"
    if not gguf.is_file():
        if reached(run, "installed"):
            print(f"{name} is already in Ollama.")
            return True
        raise Stop(f"{gguf} is gone; weekly.py upload and fetch to train it again.")
    try:
        stock = api("/api/show", {"model": args.stock})["modelfile"]
    except (urllib.error.URLError, OSError, KeyError, ValueError) as e:
        raise Stop(f"Couldn't read {args.stock}'s Modelfile from Ollama ({e}). Is Ollama running, and is "
                   f"{args.stock} pulled?")
    path = folder(run) / "Modelfile"
    path.write_text(modelfile(stock, gguf), encoding="utf-8")
    if not shutil.which("ollama"):
        raise Stop("The ollama command isn't on PATH.")
    print(f"Creating {name} in Ollama from {gguf.name}")
    made = subprocess.run(["ollama", "create", name, "-f", str(path)], capture_output=True, text=True)
    if made.returncode:
        raise Stop(f"ollama create failed:\n{(made.stdout + made.stderr).strip()[-1500:]}\nThe Modelfile is {path}.")
    hello = chat(name, [{"role": "user", "content": "Say hi in five words."}], options={"num_predict": 30})
    if not hello:
        raise Stop(f"{name} was created but didn't answer; see ollama's log. The Modelfile is {path}.")
    print(f"{name} answers: {hello!r}")
    if not args.keep_gguf:
        gguf.unlink()  # Ollama keeps its own copy
        print(f"Deleted the downloaded {gguf.name} (Ollama has its own copy; --keep-gguf keeps it).")
    run.update(stage="installed", model=name)
    save_state(state)
    return True


def check_chats() -> list[dict]:
    return [json.loads(line) for line in CHECK_CHATS.read_text(encoding="utf-8").splitlines() if line.strip()]


def room_read(model: str, history: list[list[str]], vibe: list[str]) -> tuple[bool, str]:
    options = dict(UNICODE)
    content = chat(model, room_messages([format_line(h, t) for h, t in history], options, vibe, history[-1][0]),
                   room_format(options), {"temperature": 0.3})
    reading = parse_room(content, options) if content else None
    if not reading or reading.interest is None:
        return False, f"unusable: {(content or '')[:80]!r}"
    return True, f"{reading.read!r}, interest {reading.interest}, {reading.emoji or 'no reaction'}"


def diary_read(model: str, history: list[list[str]]) -> tuple[bool, str]:
    people = sorted({h for h, _ in history})
    content = chat(model, digest_messages("#general", local_day(time.time()), [format_line(h, t) for h, t in history]),
                   digest_format(people), {"temperature": 0.3, "num_predict": 700})
    digest = parse_digest(content, people, [t for _, t in history]) if content else None
    if not digest or not digest[0]:
        return False, f"unusable: {(content or '')[:80]!r}"
    return True, f"{digest[0][:90]!r}, {len(digest[1])} note(s) that check out"


def sees(model: str) -> bool:
    for name, rgb in (("red", (230, 20, 20)), ("blue", (20, 40, 230))):
        try:
            if name not in vision_check.ask(vision_check.png(rgb), model).lower():
                return False
        except (urllib.error.URLError, OSError, ValueError):
            return False
    return True


def same_model(a: str, b: str) -> bool:
    return (a if ":" in a else a + ":latest") == (b if ":" in b else b + ":latest")


def fit_together(models: list[str]) -> tuple[bool, str]:
    """Whether these models are all in VRAM at once: each gets a one-token call, then Ollama's /api/ps."""
    for model in models:
        chat(model, [{"role": "user", "content": "hi"}], options={"num_predict": 1})
    try:
        loaded = api("/api/ps", timeout=30).get("models", [])
    except (urllib.error.URLError, OSError, ValueError) as e:
        return False, f"couldn't ask Ollama ({e})"
    found = {model: next((m for m in loaded if same_model(m.get("name", ""), model)), None) for model in models}
    parts = [f"{model}: {m['size'] / 1e9:.1f} GB, {100 * m.get('size_vram', 0) / max(m['size'], 1):.0f}% on the GPU"
             if m else f"{model}: pushed out" for model, m in found.items()]
    fits = all(m and m.get("size_vram", 0) >= 0.99 * m["size"] for m in found.values())
    return fits, "; ".join(parts)


def cmd_check(args) -> bool:
    state = load_state()
    run = pick_run(state, "installed", args.run)
    if not reached(run, "installed"):
        raise Stop(f"Run {run['run']} isn't installed: weekly.py install.")
    new, current = run["model"], setting("OLLAMA_MODEL", STOCK)
    now = current if not same_model(current, new) else args.stock
    # the example chats she'd get on `now`: the bot's setting for what she runs on, the default for the stock model
    few = int(setting("FEW_SHOT_EXAMPLES", "8")) if now == current else 8
    diary_file = ROOT / setting("DIARY_FILE", "diary.json")
    vibe = Diary(diary_file).vibe() if diary_file.exists() else []
    # her prompt's seed chats, if the bot shows them (SEED_EXAMPLES): it only trains her by default
    shows_seed = setting("SEED_EXAMPLES", "false").lower() in ("1", "true", "yes", "on")
    seed = build_dataset.read_jsonl(build_dataset.SEED) if shows_seed else []
    earned = build_dataset.read_jsonl(ROOT / setting("EARNED_FILE", "earned_examples.jsonl"))
    anchor, full_at = float(setting("MELD_ANCHOR", "0.3")), int(setting("MELD_FULL_AT", "200"))
    think = thinks()
    cap = {} if think else {"num_predict": int(setting("MAX_REPLY_TOKENS", "200"))}  # thinking counts against it
    chats = check_chats()
    print(f"Checking {new} against {now} (what she runs on now): {len(chats)} test chats, a minute or two")

    replies = []
    for i, test in enumerate(c for c in chats if c.get("use", "reply") == "reply"):
        transcript = [format_line(h, t) for h, t in test["history"]]
        speaker, last = test["history"][-1]
        mentioned = names_her(last)  # aimed at her, as in build_dataset.py
        examples = pick_examples(seed, earned, few, anchor, full_at, rng=random.Random(i)) if few > 0 else []
        context = {"vibe": vibe, "avatar": setting("AVATAR_DESCRIPTION", "")}
        replies.append((test, chat(now, build_messages(transcript, mentioned, speaker, examples=examples, **context),
                                   options=cap, think=think),
                        chat(new, build_messages(transcript, mentioned, speaker, **context), options=cap, think=think)))
    room = next(c["history"] for c in chats if c.get("use") == "room")
    diary_log = next(c["history"] for c in chats if c.get("use") == "diary")
    tasks = {model: (room_read(model, room, vibe), diary_read(model, diary_log)) for model in (now, new)}
    new_sees = sees(new)
    both_fit, sizes = fit_together([args.stock, new])
    tasks_ok = tasks[new][0][0] and tasks[new][1][0]
    run.update(stage="checked", check={"against": now, "sees": new_sees, "tasks_ok": tasks_ok, "both_fit": both_fit})
    save_state(state)

    def cell(ok_detail):
        return ("ok: " if ok_detail[0] else "FAILED: ") + ok_detail[1]
    result = run.get("result", {})
    report = [f"# {new} next to {now}", "",
              f"Run {run['run']}, built {run['built']}: {run['summary']}. Trained on {result.get('examples')} "
              f"examples, loss {result.get('loss')}, {result.get('minutes')} min on Kaggle.", "",
              f"- Reading the room, {now}: {cell(tasks[now][0])}",
              f"- Reading the room, {new}: {cell(tasks[new][0])}",
              f"- Diary, {now}: {cell(tasks[now][1])}",
              f"- Diary, {new}: {cell(tasks[new][1])}",
              f"- {new} sees pictures: {'yes' if new_sees else 'no (text only, as trained)'}",
              f"- {new} and {args.stock} on the GPU together: {'yes' if both_fit else 'no'} ({sizes})", "",
              "What `weekly.py switch` would set: "
              + ", ".join(f"{k}={v}" for k, v in switch_values(run, args).items()), ""]
    for n, (test, before, after) in enumerate(replies, 1):
        report += [f"## {n}. {' / '.join(f'{h}: {t}' for h, t in test['history'])}", f"Look for: {test['look_for']}",
                   f"- **{now}:** {before or '(no answer)'}", f"- **{new}:** {after or '(no answer)'}", ""]
    text = "\n".join(report)
    (folder(run) / "check.md").write_text(text, encoding="utf-8")
    print(text)
    print(f"This report is also in {folder(run) / 'check.md'}. If {new} sounds like her: weekly.py switch")
    return True


def switch_values(run: dict, args) -> dict[str, str]:
    check = run.get("check", {})
    on_stock = args.tasks == "stock" or (args.tasks is None and check.get("both_fit"))
    return {"OLLAMA_MODEL": run["model"], "FEW_SHOT_EXAMPLES": "0",
            "VISION_MODEL": "" if check.get("sees") else args.stock, "TASK_MODEL": args.stock if on_stock else ""}


def cmd_switch(args) -> bool:
    state = load_state()
    run = pick_run(state, "checked" if not args.force else "installed", args.run)
    if not reached(run, "checked") and not args.force:
        raise Stop(f"{run.get('model', 'Run ' + str(run['run']))} hasn't been checked: weekly.py check first "
                   "(--force switches anyway).")
    values = switch_values(run, args)
    before = {key: env_get(key) for key in SWITCHED_KEYS}
    env_set(values)
    state["switches"].append({"run": run["run"], "when": time.strftime("%Y-%m-%d %H:%M"), "before": before,
                              "after": values})
    save_state(state)
    print(f"Her voice is {run['model']} now (.env): " + ", ".join(f"{k}={v}" for k, v in values.items()))
    if not values["TASK_MODEL"]:
        print(f"Reading the room and her diary run on {run['model']} too"
              + (": the two models don't fit on the GPU together." if not run.get("check", {}).get("both_fit")
                 else " (--tasks her)."))
    if values["VISION_MODEL"] and not run.get("check", {}).get("both_fit"):
        print(f"Pictures go to {args.stock}, which doesn't fit next to her: a picture makes Ollama swap models "
              "(a few seconds each way).")
    print("Restart the bot to use it. weekly.py rollback undoes this.")
    return True


def cmd_rollback(args) -> bool:
    state = load_state()
    if not state["switches"]:
        raise Stop("No switch to roll back.")
    last = state["switches"].pop()
    env_set(last["before"])
    save_state(state)
    print("Back to: " + ", ".join(f"{k}={v if v is not None else '(unset)'}" for k, v in last["before"].items())
          + ". Restart the bot to use it.")
    return True


def cmd_status(args) -> bool:
    state = load_state()
    print("Runs:" if state["runs"] else "No runs yet.")
    for run in state["runs"]:
        check = run.get("check")
        print(f"  {run['run']:>3}  built {run['built']}  {run['stage']:<9} {run['examples']} examples, "
              f"{run['share']:.0%} Satania" + (f", {run['model']}" if run.get("model") else "")
              + (f", checked: sees {'yes' if check['sees'] else 'no'}, tasks {'ok' if check['tasks_ok'] else 'FAILED'}"
                 if check else "") + (f"  ERROR: {run['error']}" if run.get("error") else ""))
    print("She runs on: " + ", ".join(f"{key}={env_get(key) if env_get(key) is not None else '(unset)'}"
                                      for key in SWITCHED_KEYS))
    done = [r for r in state["runs"] if reached(r, "installed")]
    number = done[-1]["run"] + 1 if done else 1
    anchor, runs = float(setting("MELD_ANCHOR", "0.3")), int(setting("MELD_RUNS", str(MELD_RUNS)))
    before = done[-1] if done else {"landed": 0, "voice": 0}
    earned = build_dataset.read_jsonl(ROOT / setting("EARNED_FILE", "earned_examples.jsonl"))
    voice = len(build_dataset.voice_pool(ChatLog(ROOT / setting("CHAT_LOG_DIR", "chatlogs"))))
    new = len(earned) - before["landed"] + voice - before["voice"]
    print(f"Next: run {number}, {persona_share(number, anchor, runs):.0%} Satania; {new} new examples from the "
          f"server so far, a run wants {args.min_new}.")
    return True


def cmd_all(args) -> bool:
    for step in (cmd_build, cmd_upload, cmd_fetch, cmd_install, cmd_check):
        if not step(args):
            return False
    return True


COMMANDS = {"status": cmd_status, "build": cmd_build, "upload": cmd_upload, "fetch": cmd_fetch,
            "install": cmd_install, "check": cmd_check, "switch": cmd_switch, "rollback": cmd_rollback,
            "all": cmd_all}


def main() -> int:
    load_dotenv(ENV)
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("command", choices=COMMANDS, nargs="?", default="status")
    parser.add_argument("--run", type=int, help="install/check/switch: this run instead of the newest")
    parser.add_argument("--force", action="store_true", help="build: even with little new data; switch: unchecked")
    parser.add_argument("--redo", action="store_true", help="build: the newest installed run again, same number")
    parser.add_argument("--min-new", type=int, default=int(setting("WEEKLY_MIN_NEW", "50")),
                        help="build: new examples from the server a run wants (WEEKLY_MIN_NEW, 50)")
    parser.add_argument("--epochs", type=float, default=1, help="build: passes over the data (1)")
    parser.add_argument("--rank", type=int, default=16, help="build: LoRA rank (16)")
    parser.add_argument("--lr", type=float, default=2e-4, help="build: learning rate (2e-4)")
    parser.add_argument("--max-len", type=int, default=2048, help="build: longest example in tokens (2048)")
    parser.add_argument("--quant", default="Q4_K_M", help="build: GGUF quantization (Q4_K_M, like the stock model)")
    parser.add_argument("--base", default=BASE, help=f"build: the model to train, on Hugging Face ({BASE})")
    parser.add_argument("--accelerator", default=ACCELERATOR, help=f"upload: Kaggle's GPU ({ACCELERATOR})")
    parser.add_argument("--poll", type=float, default=60, help="fetch: seconds between looks at Kaggle (60)")
    parser.add_argument("--wait-hours", type=float, default=3, help="fetch: how long to wait for Kaggle (3)")
    parser.add_argument("--keep-cloud-data", action="store_true", help="fetch: don't delete the data on Kaggle")
    parser.add_argument("--keep-gguf", action="store_true", help="install: keep the downloaded model file")
    parser.add_argument("--stock", default=STOCK, help=f"the stock model in Ollama ({STOCK})")
    parser.add_argument("--tasks", choices=["stock", "her"],
                        help="switch: reading the room and her diary on the stock model or on her; default: stock "
                             "if both fit on the GPU")
    args = parser.parse_args()
    try:
        COMMANDS[args.command](args)  # False: stopped for a reason it printed (little new data, still going)
        return 0
    except Stop as e:
        print(e)
        return 1


if __name__ == "__main__":
    sys.exit(main())
