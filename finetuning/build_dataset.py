"""
Render training data in the same prompt format bot.py sends.

    python3 finetuning/build_dataset.py                  # the Satania seed only -> train.jsonl
    python3 finetuning/build_dataset.py --meld --run 2   # the seed plus the server, for training run 2

Each example is {"history": [[handle, context], ...], "reply": "..."}. Harvested examples also carry
history_meta (raw author text, addressing, ids and bot flags) and answered_requests (source ids).
Human voice samples carry source="voice" so a preceding Gomi post remains the newest message.
Only raw addressing labels a message as aimed at her; quoted names do not. Delayed requests stay
explicit prompt targets. Real examples without this provenance are skipped, leaving saved files
untouched. Handwritten seed histories are raw by definition. An optional "facts": [...] is
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
from persona import BOT_NAME, build_messages, example_targets, format_line  # noqa: E402
from reactions import names_her  # noqa: E402
from shape import tidy  # noqa: E402

SEED = HERE / "gomihyu_seed.jsonl"
OUT = HERE / "train.jsonl"


def render(example: dict) -> dict | None:
    """A faithful training turn, or None when real history has lost its target provenance."""
    targets = example_targets(example)
    if targets is None:
        return None
    meta = example.get("history_meta")
    transcript = [format_line(speaker + (" (bot)" if meta and meta[i].get("bot")
                                         and speaker != BOT_NAME and not speaker.endswith(" (bot)") else ""), text)
                  for i, (speaker, text) in enumerate(example["history"])]
    speaker, last_text = example["history"][-1]
    addressed = []
    newest = None
    if meta is None:
        mentioned = names_her(last_text)  # Handwritten examples contain author words, not display context.
    else:
        # Runtime observes participants separately from her own inserted replies. A later batch can
        # follow one of her answers, but that answer is never its newest observed source. Human voice
        # samples can answer Gomi herself, including with a Discord reply link, and keep the true tail.
        latest = len(meta) - 1
        if targets and example.get("source") != "voice":
            latest = next((i for i in range(latest, -1, -1)
                           if example["history"][i][0] != BOT_NAME), latest)
        speaker = example["history"][latest][0]
        if meta[latest].get("bot") and speaker != BOT_NAME and not speaker.endswith(" (bot)"):
            speaker += " (bot)"
        mentioned = bool(meta[latest].get("addressed")) and not meta[latest].get("bot")
        newest = transcript[latest]
        addressed = [transcript[i] for i in targets]
    messages = build_messages(transcript, mentioned, speaker, example.get("facts", []), example.get("nicknames"),
                              addressed=addressed, newest=newest)
    messages.append({"role": "assistant", "content": example["reply"]})
    return {"messages": messages}


def read_jsonl(path: Path, real: bool = False) -> list[dict]:
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines() if path.exists() else []:
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(row, dict) and real:
            row = row | {"real": True}  # Earned-file origin is authoritative, even on unmarked legacy rows.
        if isinstance(row, dict) and row.get("reply") and row.get("history") and render(row) is not None:
            rows.append(row)
    return rows


def voice_pool(chat_log: ChatLog) -> list[dict]:
    """Every message in the chat logs that can stand for the server's voice (meld.voice_examples)."""
    return [example for channel_id in sorted(chat_log.channels())
            for example in voice_examples(chat_log.read(channel_id)) if render(example) is not None]


def meld_examples(seed: list[dict], run: int, share: float | None, seed_repeat: int, chat_log: ChatLog,
                  earned: list[dict], anchor: float, runs: int = MELD_RUNS) -> tuple[list[dict], str]:
    """The run's examples and a line saying what's in them."""
    share = share if share is not None else persona_share(run, anchor, runs)
    persona = seed * seed_repeat
    server_n = round(len(persona) * (1 - share) / share)
    rng = random.Random(run)
    eligible = [example for example in earned if render(example) is not None]
    landed = eligible if len(eligible) <= server_n else rng.sample(eligible, server_n)
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
        earned = read_jsonl(ROOT / os.environ.get("EARNED_FILE", "earned_examples.jsonl"), real=True)
        anchor = float(os.environ.get("MELD_ANCHOR", "0.3"))
        runs = int(os.environ.get("MELD_RUNS", str(MELD_RUNS)))
        rows, summary = meld_examples(seed, args.run, args.persona_share, args.seed_repeat, chat_log, earned, anchor,
                                      runs)
    rendered = [turn for row in rows if (turn := render(row)) is not None]
    OUT.write_text("".join(json.dumps(turn, ensure_ascii=False) + "\n" for turn in rendered), encoding="utf-8")
    print(f"Wrote {len(rendered)} examples to {OUT} ({summary})")


if __name__ == "__main__":
    main()
