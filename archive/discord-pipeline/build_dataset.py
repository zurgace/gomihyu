"""
ARCHIVED until training on a rented GPU is set up; runs from here as is.

Step 3 of 3: render examples into chat-format training data, using the prompt format bot.py sends.

    python3 archive/discord-pipeline/build_dataset.py                      # data/examples.jsonl -> data/train.jsonl
    python3 archive/discord-pipeline/build_dataset.py archive/discord-pipeline/data/examples.jsonl finetuning/gomihyu_seed.jsonl

Each input line is {"history": [[handle, text], ...], "reply": "..."}, optionally with "facts"
and "nicknames": the format backtranslate.py writes and finetuning/gomihyu_seed.jsonl uses. The last
history line is the message being answered; it counts as an @mention if it contains
"@Gomihyu". Every prompt is built by persona.build_messages(), like at runtime.
"""

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent.parent))  # the repo root, for the gomi package

from gomi.persona import BOT_NAME, build_messages, format_line  # noqa: E402

EXAMPLES = HERE / "data" / "examples.jsonl"
OUT = HERE / "data" / "train.jsonl"


def render(example: dict) -> dict:
    transcript = [format_line(speaker, text) for speaker, text in example["history"]]
    speaker, last_text = example["history"][-1]
    mentioned = f"@{BOT_NAME}".lower() in last_text.lower()
    messages = build_messages(transcript, mentioned, speaker, example.get("facts", []), example.get("nicknames"))
    messages.append({"role": "assistant", "content": example["reply"]})
    return {"messages": messages}


def main():
    sources = [Path(arg) for arg in sys.argv[1:]] or [EXAMPLES]
    rows = []
    for source in sources:
        lines = [line for line in source.read_text(encoding="utf-8").splitlines() if line.strip()]
        rows += [render(json.loads(line)) for line in lines]
        print(f"{len(lines)} examples from {source}")
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8")
    print(f"Wrote {len(rows)} examples to {OUT}")


if __name__ == "__main__":
    main()
