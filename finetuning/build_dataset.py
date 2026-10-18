"""
Render training data in the same prompt format bot.py sends.

    python3 finetuning/build_dataset.py                  # the Satania seed only -> train.jsonl
    python3 finetuning/build_dataset.py --meld --run 2   # the seed plus the server, for training run 2

Each example is {"history": [[handle, text], ...], "reply": "..."}. The last history line is the
message being replied to; it counts as an @mention if it contains "@Gomihyu". Earlier lines are chat
context, and Gomihyu's own earlier messages use the speaker "Gomihyu". An optional "facts": [...] is
what that last speaker has asked her to remember (memory.py), and an optional "nicknames":
{handle: nickname} what she calls people in the log.

With --meld (meld.py: the server slowly shapes her; the members agreed to their chat being used),
the data mixes:
  - the seed, repeated --seed-repeat times: the Satania persona, the anchor;
  - her replies that landed (EARNED_FILE, earned_examples.jsonl), all of them first;
  - people's own messages from the chat logs (CHAT_LOG_DIR, chatlogs/): the server's voice, a fixed
    random pick per run.
The seed's share goes from 70% at run 1 down in even steps to MELD_ANCHOR (30%) at run MELD_RUNS (11),
and stays there (meld.persona_share: 70%, 66%, 62%, ...); --persona-share overrides it. Paths,
MELD_ANCHOR and MELD_RUNS come from .env like the bot's. finetuning/weekly.py runs this once a week.
train.jsonl holds real chat: it's gitignored, never commit it.
"""

import argparse
import json
import os
import random
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))  # so persona.py imports when run from anywhere

from dotenv import load_dotenv  # noqa: E402

from chatlog import ChatLog  # noqa: E402
from meld import MELD_RUNS, persona_share, voice_examples  # noqa: E402
from persona import build_messages, format_line  # noqa: E402
from reactions import names_her  # noqa: E402
from shape import tidy  # noqa: E402

SEED = HERE / "gomihyu_seed.jsonl"
OUT = HERE / "train.jsonl"


def render(example: dict) -> dict:
    transcript = [format_line(speaker, text) for speaker, text in example["history"]]
    speaker, last_text = example["history"][-1]
    mentioned = names_her(last_text)  # aimed at her, as bot.py sees it (minus Discord replies: not in the data)
    messages = build_messages(transcript, mentioned, speaker, example.get("facts", []), example.get("nicknames"))
    messages.append({"role": "assistant", "content": example["reply"]})
    return {"messages": messages}


def read_jsonl(path: Path) -> list[dict]:
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines() if path.exists() else []:
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(row, dict) and row.get("reply") and row.get("history"):
            rows.append(row)
    return rows


def voice_pool(chat_log: ChatLog) -> list[dict]:
    """Every message in the chat logs that can stand for the server's voice (meld.voice_examples)."""
    return [example for channel_id in sorted(chat_log.channels())
            for example in voice_examples(chat_log.read(channel_id))]


def meld_examples(seed: list[dict], run: int, share: float | None, seed_repeat: int, chat_log: ChatLog,
                  earned: list[dict], anchor: float, runs: int = MELD_RUNS) -> tuple[list[dict], str]:
    """The run's examples and a line saying what's in them."""
    share = share if share is not None else persona_share(run, anchor, runs)
    persona = seed * seed_repeat
    server_n = round(len(persona) * (1 - share) / share)
    rng = random.Random(run)
    landed = earned if len(earned) <= server_n else rng.sample(earned, server_n)
    landed = [example | {"reply": tidy(example["reply"])} for example in landed]  # today's limits (shape.py)
    pool = voice_pool(chat_log)
    voice = rng.sample(pool, min(len(pool), server_n - len(landed)))
    rows = persona + landed + voice
    rng.shuffle(rows)
    actual = len(persona) / len(rows) if rows else 1
    summary = (f"Run {run}: {len(seed)} seed x {seed_repeat} = {len(persona)} persona examples, {len(landed)} of her "
               f"{len(earned)} landed replies, {len(voice)} of {len(pool)} server messages: {len(rows)} examples, "
               f"{actual:.0%} persona (aimed for {share:.0%})")
    return rows, summary


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--meld", action="store_true", help="mix in the server (chat logs, her landed replies)")
    parser.add_argument("--run", type=int, default=1, help="which training run this is (sets the persona share)")
    parser.add_argument("--persona-share", type=float, help="share of seed examples, instead of the schedule")
    parser.add_argument("--seed-repeat", type=int, default=3, help="times the seed goes in (default 3)")
    args = parser.parse_args()

    seed = read_jsonl(SEED)
    if not args.meld:
        rows, summary = seed, f"{len(seed)} seed examples"
    else:
        load_dotenv(ROOT / ".env")
        chat_log = ChatLog(ROOT / os.environ.get("CHAT_LOG_DIR", "chatlogs"))
        earned = read_jsonl(ROOT / os.environ.get("EARNED_FILE", "earned_examples.jsonl"))
        anchor = float(os.environ.get("MELD_ANCHOR", "0.3"))
        runs = int(os.environ.get("MELD_RUNS", str(MELD_RUNS)))
        rows, summary = meld_examples(seed, args.run, args.persona_share, args.seed_repeat, chat_log, earned, anchor,
                                      runs)
    OUT.write_text("".join(json.dumps(render(row), ensure_ascii=False) + "\n" for row in rows), encoding="utf-8")
    print(f"Wrote {len(rows)} examples to {OUT} ({summary})")


if __name__ == "__main__":
    main()
