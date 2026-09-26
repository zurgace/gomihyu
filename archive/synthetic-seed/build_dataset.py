"""
Render the seed examples into SFT chat data, using the same prompt format bot.py sends.

    python3 archive/synthetic-seed/build_dataset.py   # gomihyu_seed.jsonl -> train.jsonl

Archived: this was the synthetic seed for LFM2.5-2.6B, replaced by training on real messages.

Each seed line is {"history": [[handle, text], ...], "reply": "..."}. The last history line
is the message being replied to; it counts as an @mention if it contains "@Gomihyu". Earlier
lines are chat context, and Gomihyu's own earlier messages use the speaker "Gomihyu".
An optional "facts": [...] is what that last speaker has asked her to remember (memory.py), and
an optional "nicknames": {handle: nickname} what she calls people in the log.
"""

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent.parent))  # the repo root, so persona.py imports when run from anywhere

from persona import BOT_NAME, build_messages, format_line  # noqa: E402

SEED = HERE / "gomihyu_seed.jsonl"
OUT = HERE / "train.jsonl"


def render(example: dict) -> dict:
    transcript = [format_line(speaker, text) for speaker, text in example["history"]]
    speaker, last_text = example["history"][-1]
    mentioned = f"@{BOT_NAME}".lower() in last_text.lower()
    messages = build_messages(transcript, mentioned, speaker, example.get("facts", []), example.get("nicknames"))
    messages.append({"role": "assistant", "content": example["reply"]})
    return {"messages": messages}


def main():
    lines = [line for line in SEED.read_text(encoding="utf-8").splitlines() if line.strip()]
    rows = [render(json.loads(line)) for line in lines]
    OUT.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8")
    print(f"Wrote {len(rows)} examples to {OUT}")


if __name__ == "__main__":
    main()
