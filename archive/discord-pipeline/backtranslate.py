"""
ARCHIVED until training on a rented GPU is set up; runs from here as is.

Step 2 of 3: write the other side of each conversation.

    python3 archive/discord-pipeline/backtranslate.py --limit 50   # try a small batch first, then read the output
    python3 archive/discord-pipeline/backtranslate.py              # data/replies.jsonl -> data/examples.jsonl

Your export only has your messages, not what they were answering. For each one, a model (via
Ollama: OLLAMA_URL and OLLAMA_MODEL from .env, or --model) writes 1-3 friend messages that
plausibly came just before it. The friends get made-up handles. Some examples get an
"@Gomihyu" ping, so training also covers the prompt she gets when she's mentioned.

A reply whose context comes back unusable twice (bad JSON, a slur, or copying the reply) is
logged in data/rejected.jsonl instead. Replies are taken in a fixed shuffled order, so a bigger
--limit extends a smaller one. Safe to stop (Ctrl+C) and rerun: finished replies are skipped.
"""

import argparse
import json
import os
import random
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent.parent))  # the repo root, for the gomi package

from dotenv import load_dotenv  # noqa: E402

from gomi.censor import has_slur  # noqa: E402
from gomi.persona import BOT_NAME  # noqa: E402

load_dotenv(HERE.parent / ".env")
OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://localhost:11434/api/chat")
MODEL = os.environ.get("OLLAMA_MODEL", "gemma4:e4b")

REPLIES = HERE / "data" / "replies.jsonl"
OUT = HERE / "data" / "examples.jsonl"
REJECTED = HERE / "data" / "rejected.jsonl"
FRIENDS = ["kaz0", "norimaki", "mintchoco", "sleepyfox", "jake.b"]  # made-up handles
MENTION_SHARE = 0.25  # share of examples where the last friend message pings her
COPY_WORDS = 5  # a context message sharing this many words in a row with the reply copied it

SYSTEM = (
    "You rebuild Discord group chats. You're shown a message someone sent in a casual Discord "
    "server among friends. Write the 1 to 3 messages their friends sent just before it, which it "
    "replies to or follows on from. Casual Discord texting: short, lowercase is fine, slang is "
    "fine. Just the message text: no names in front, no @mentions, and don't repeat the "
    "message's own words. If it starts a new topic by itself, write what the friends were "
    "talking about right before."
)
FORMAT = {"type": "object", "required": ["messages"],
          "properties": {"messages": {"type": "array", "items": {"type": "string"}, "minItems": 1, "maxItems": 3}}}


def words(text: str) -> list[str]:
    return re.findall(r"[\w']+", text.lower())


def copies(context: str, reply: str) -> bool:
    runs = lambda w: {tuple(w[i:i + COPY_WORDS]) for i in range(len(w) - COPY_WORDS + 1)}
    return bool(runs(words(context)) & runs(words(reply)))


def ask(model: str, reply: str) -> list[str]:
    body = {"model": model, "stream": False, "think": False, "format": FORMAT,
            "options": {"temperature": 0.9, "num_predict": 200},
            "messages": [{"role": "system", "content": SYSTEM}, {"role": "user", "content": f"The message:\n{reply}"}]}
    request = urllib.request.Request(OLLAMA_URL, json.dumps(body).encode(), {"Content-Type": "application/json"})
    with urllib.request.urlopen(request, timeout=120) as resp:
        content = json.load(resp).get("message", {}).get("content", "")
    try:
        messages = json.loads(content).get("messages", [])
    except (json.JSONDecodeError, AttributeError):
        return []
    return [text.strip()[:300] for text in messages if isinstance(text, str) and text.strip()]


def problem(context: list[str], reply: str) -> str | None:
    return ("no usable answer" if not context else
            "slur in context" if any(has_slur(text) for text in context) else
            "copied the reply" if any(copies(text, reply) for text in context) else None)


def read_replies(path: Path) -> set[str]:
    if not path.exists():
        return set()
    return {json.loads(line)["reply"] for line in path.read_text(encoding="utf-8").splitlines() if line.strip()}


def example(reply: str, context: list[str]) -> dict:
    rnd = random.Random(reply)  # the same reply always gets the same friends
    friends = rnd.sample(FRIENDS, 2)
    history = [[friends[0] if i == 0 else rnd.choice(friends), text] for i, text in enumerate(context)]
    if rnd.random() < MENTION_SHARE:
        history[-1][1] = f"@{BOT_NAME} {history[-1][1]}"
    return {"history": history, "reply": reply}


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--limit", type=int, default=3000, help="how many replies to use (default 3000)")
    parser.add_argument("--model", default=MODEL, help=f"Ollama model that writes the context (default {MODEL})")
    args = parser.parse_args()

    replies = [json.loads(line)["reply"] for line in REPLIES.read_text(encoding="utf-8").splitlines() if line.strip()]
    random.Random(0).shuffle(replies)
    done, skip = read_replies(OUT), read_replies(REJECTED)
    todo = [reply for reply in replies[:args.limit] if reply not in done and reply not in skip]
    print(f"{len(done)} examples already written, {len(skip)} rejected before, {len(todo)} to go, using {args.model}")

    rejected, start = {}, time.monotonic()
    with OUT.open("a", encoding="utf-8") as out, REJECTED.open("a", encoding="utf-8") as bad:
        for n, reply in enumerate(todo, 1):
            for _ in range(2):  # a second try usually fixes a bad answer
                try:
                    context = ask(args.model, reply)
                except urllib.error.HTTPError as e:
                    sys.exit(f"Ollama returned HTTP {e.code}: {e.read().decode()[:300]}")
                except (urllib.error.URLError, TimeoutError) as e:
                    sys.exit(f"Couldn't reach Ollama at {OLLAMA_URL} ({e}). Is it running? Rerun to continue.")
                if not (reason := problem(context, reply)):
                    break
            if reason:
                rejected[reason] = rejected.get(reason, 0) + 1
                bad.write(json.dumps({"reply": reply, "reason": reason}, ensure_ascii=False) + "\n")
                bad.flush()
            else:
                out.write(json.dumps(example(reply, context), ensure_ascii=False) + "\n")
                out.flush()
            if n % 25 == 0 or n == len(todo):
                per = (time.monotonic() - start) / n
                print(f"{n}/{len(todo)} ({per:.1f}s each, ~{per * (len(todo) - n) / 60:.0f} min left)", flush=True)
    print(f"Done. Skipped: {rejected or 'none'}. Examples are in {OUT}")


if __name__ == "__main__":
    main()
