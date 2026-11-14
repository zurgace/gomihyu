"""Compare installed Ollama models on six synthetic Discord conversations.

    venv/bin/python tools/chat_check.py --think --output /tmp/gomi-comparison.md

Defaults: gomi-w1, gemma4:e4b and gomi-bolt, each at seeds 17, 29 and 43. Uses the
runtime prompt builder and reply-shape helper, with raw author words separate from
quoted context. No .env, private chat, diary or training examples are read. The
report preserves prompts, settings, installed model digests and raw responses.
Endpoint: --url, else the process's OLLAMA_URL, else http://localhost:11434/api/chat.
Credential-bearing URLs are rejected; repository .env is never loaded.
This compares generation only: it does not test Discord scheduling, room-reading
decisions, delivery, retries or the full runtime cleanup. No models are pulled.
"""

import argparse
import hashlib
import json
import os
import re
import sys
import tempfile
import time
import urllib.error
from urllib.parse import urlsplit, urlunsplit
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from finetuning.weekly import THINK, api  # noqa: E402
from persona import BOT_NAME, build_messages, format_line  # noqa: E402
from shape import LINE_SENTENCES, MAX_SENTENCES, at_most, one_emoji, this_time  # noqa: E402

MODELS = ["gomi-w1", "gemma4:e4b", "gomi-bolt"]
SEEDS = [17, 29, 43]
FIXTURE_TIME = "2026-11-14T12:00:00-05:00"
CASES = [
    {"name": "Topic changed", "mentioned": True,
     "history": [{"author": "Mira", "text": "that boss keeps killing me"},
                 {"author": BOT_NAME, "text": "which boss?"},
                 {"author": "Mira", "text": "nevermind, beat it"},
                 {"author": "Sol", "text": "anyway my keyboard won't connect over bluetooth"},
                 {"author": "Sol", "text": "gomi it works over usb though"}],
     "look_for": "Talk about the keyboard/Bluetooth, not the boss. Don't invent the keyboard model or cause."},
    {"name": "Clarification after a question", "mentioned": True,
     "history": [{"author": "Mira", "text": "movie later?"},
                 {"author": BOT_NAME, "text": "what are we watching?"},
                 {"author": "Sol", "text": "unrelated, gomi is that one any good?"}],
     "look_for": "Ask which thing Sol means, even though Gomi just asked a question. Don't invent an answer."},
    {"name": "Discord reply to an older topic", "mentioned": True,
     "history": [{"author": "Mira", "text": "my headphones keep disconnecting"},
                 {"author": "Sol", "text": "pizza arrived"},
                 {"author": "Mira", "text": "gomi any idea why?",
                  "context": '[reply to Mira: "my headphones keep disconnecting"] gomi any idea why?'}],
     "look_for": "Answer about the headphones, not pizza. Ask a useful missing detail; don't assert a cause."},
    {"name": "You means another person", "mentioned": False,
     "history": [{"author": "Mira", "text": "Sol, did you finish that drawing?"},
                 {"author": "Sol", "text": "yeah, uploading it now",
                  "context": '[reply to Mira: "Sol, did you finish that drawing?"] yeah, uploading it now'},
                 {"author": "Mira", "text": "you nailed the lighting",
                  "context": '[reply to Sol: "yeah, uploading it now"] you nailed the lighting'}],
     "look_for": "Recognize Sol drew it. Don't claim the praise or pretend to have seen the unseen drawing."},
    {"name": "Earlier direct question in a burst", "mentioned": False,
     "history": [{"author": "Mira", "text": "gomi what's 6 times 7?"},
                 {"author": "Sol", "text": "my pizza just arrived"}],
     "pending": [0],
     "look_for": "Answer Mira's pending question with 42; don't treat Sol as the person who asked."},
    {"name": "Plain answer", "mentioned": True,
     "history": [{"author": "Sol", "text": "gomi can i use a usb keyboard with a laptop?"}],
     "look_for": "Give a short yes with any necessary connector caveat. No lecture or mandatory extra joke."},
]


def displayed(row: dict) -> str:
    return format_line(row["author"], row.get("context", row["text"]))


def prompt(case: dict, now: datetime, max_words: int = 6) -> tuple[list[dict], dict]:
    history = case["history"]
    newest_index = case.get("newest", len(history) - 1)
    newest = history[newest_index]
    pending = [history[i] for i in case.get("pending", [newest_index] if case["mentioned"] else [])]
    shape = this_time(newest["text"], [row["text"] for row in history if row["author"] == BOT_NAME],
                      max_words, pending_raw=[row["text"] for row in pending])
    messages = build_messages([displayed(row) for row in history], case["mentioned"], newest["author"],
                              **shape, now=now, addressed=[displayed(row) for row in pending],
                              newest=displayed(newest))
    return messages, shape


def response_details(data: dict) -> dict:
    """Preserve exact model fields; thinking counts are observed text, not inferred reasoning tokens."""
    if (not isinstance(data, dict) or not isinstance(data.get("message"), dict)
            or not isinstance(data["message"].get("content", ""), str)
            or data["message"].get("thinking") is not None and not isinstance(data["message"]["thinking"], str)):
        raise ValueError("Ollama returned an unusable message")
    message = data["message"]
    raw = message.get("content", "")
    thought = message.get("thinking") or ""
    inline = [match[0] for match in re.finditer(r"<think>(.*?)(?:</think>|$)", raw, re.DOTALL)]
    inline_text = "\n".join(re.sub(r"^<think>|</think>$", "", text) for text in inline)
    thinking = "\n".join(text for text in (thought, inline_text) if text.strip())
    return {"raw_content": raw, "raw_thinking": thought, "reply": THINK.sub("", raw).strip(),
            "thinking_present": bool(thinking.strip()), "thinking_words": len(thinking.split()),
            "thinking_chars": len(thinking), "thinking_token_count": None}


def write_json(output, value: dict) -> None:
    output.write("```json\n" + json.dumps(value, ensure_ascii=False, indent=2) + "\n```\n\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("models", nargs="*", default=MODELS, help="Installed models (default: all three candidates)")
    parser.add_argument("--seeds", nargs="+", type=int, default=SEEDS, help="Fixed generation seeds (default: 17 29 43)")
    parser.add_argument("--think", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--num-ctx", type=int, default=8192)
    parser.add_argument("--num-predict", type=int, help="Generation token cap (default: -1 with thinking, 200 without)")
    parser.add_argument("--temperature", type=float, default=0.8)
    parser.add_argument("--top-p", type=float, default=0.9)
    parser.add_argument("--top-k", type=int, default=40)
    parser.add_argument("--repeat-penalty", type=float, default=1.1)
    parser.add_argument("--at", type=datetime.fromisoformat, default=datetime.fromisoformat(FIXTURE_TIME),
                        help="Synthetic prompt date/time in ISO format; fixed by default")
    parser.add_argument("--url", help="Ollama base or chat URL; overrides process OLLAMA_URL (never reads .env)")
    parser.add_argument("--output", type=Path, help="New Markdown report; default: a fresh file in /tmp")
    args = parser.parse_args(argv)
    process_url = os.environ.get("OLLAMA_URL", "").strip()
    endpoint_source = "--url" if args.url is not None else "OLLAMA_URL" if process_url else "default"
    endpoint = (args.url if args.url is not None else process_url or "http://localhost:11434/api/chat").strip()
    try:
        parts = urlsplit(endpoint)
        if (parts.scheme not in ("http", "https") or not parts.hostname or "@" in parts.netloc
                or parts.query or parts.fragment):
            raise ValueError
        parts.port  # Validate the port without including a possibly sensitive URL in errors.
    except ValueError:
        parser.error("Use an HTTP(S) Ollama URL without credentials, query parameters or fragments")
    endpoint = urlunsplit(parts).rstrip("/").rsplit("/api/", 1)[0] + "/api/chat"
    options = {"num_ctx": args.num_ctx, "num_predict": args.num_predict if args.num_predict is not None else
               (-1 if args.think else 200), "temperature": args.temperature, "top_p": args.top_p,
               "top_k": args.top_k, "min_p": 0.0, "mirostat": 0,
               "repeat_penalty": args.repeat_penalty, "repeat_last_n": 64,
               "presence_penalty": 0.0, "frequency_penalty": 0.0}
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        try:
            output = args.output.open("x", encoding="utf-8")
        except FileExistsError:
            parser.error(f"Report already exists: {args.output}; choose a new path")
    else:
        output = tempfile.NamedTemporaryFile(mode="w", prefix="gomi-chat-check-", suffix=".md",
                                             dir="/tmp", encoding="utf-8", delete=False)
    failed = False
    try:
        tags = api("/api/tags", url=endpoint)
        if (not isinstance(tags, dict) or not isinstance(tags.get("models"), list)
                or any(not isinstance(entry, dict) or not isinstance(entry.get("name", ""), str)
                       or not isinstance(entry.get("model", ""), str) for entry in tags["models"])):
            raise ValueError("Ollama returned an unusable model list")
        installed = tags["models"]
        identity_error = None
    except (urllib.error.URLError, OSError, ValueError) as error:
        installed, identity_error, failed = [], str(error), True
    identities = {model: next((entry for entry in installed if model in
                              (entry.get("name"), entry.get("model"), entry.get("name", "").removesuffix(":latest"))),
                             None) for model in args.models}
    with output:
        output.write("# Gomi conversation comparison\n\n"
                     "Synthetic generation only. This does not test Discord scheduling or room-reading decisions, "
                     "delivery, retries or full runtime cleanup. Review relevance, uncertainty, useful questions and "
                     "substance; short answers alone do not mean good answers. Prompts and persona are identical "
                     "across models and seeds. No few-shot examples or private memory. Generation settings override "
                     "model sampling defaults. Elapsed seconds measure the chat HTTP request and JSON decoding, "
                     "including loading; Ollama load/total durations are reported separately when available. "
                     "These are not complete end-to-end runtime latency. "
                     "Thinking counts measure returned words/characters, not hidden reasoning or separate tokens. "
                     "Shaped previews apply runtime sentence/emoji policy only.\n\n")
        write_json(output, {"run_at": datetime.now(ZoneInfo("America/Detroit")).isoformat(timespec="seconds"),
                            "endpoint": endpoint, "endpoint_source": endpoint_source,
                            "fixture_time": args.at.isoformat(), "models": args.models, "seeds": args.seeds,
                            "think_requested": args.think, "options": options, "few_shot_examples": 0,
                            "max_history": 30, "installed_identity": identities, "identity_error": identity_error})
        for case in CASES:
            messages, shape = prompt(case, args.at)
            output.write(f"## {case['name']}\n\nLook for: {case['look_for']}\n\n")
            write_json(output, {"fixture": case, "messages": messages, "shape": shape,
                                "prompt_sha256": hashlib.sha256(json.dumps(messages, ensure_ascii=False,
                                                                           sort_keys=True).encode()).hexdigest()})
            for seed in args.seeds:
                for model in args.models:
                    print(f"{case['name']}: {model}, seed {seed}", flush=True)
                    output.write(f"### {model}, seed {seed}\n\n")
                    if identities[model] is None:
                        failed = True
                        write_json(output, {"requested_model": model, "seed": seed,
                                            "error": "Model identity unavailable" if identity_error else
                                            "Requested model is not installed; no pull attempted",
                                            "elapsed_seconds": None})
                        output.flush()
                        continue
                    start = time.monotonic()
                    try:
                        data = api("/api/chat", {"model": model, "messages": messages, "stream": False,
                                                 "think": args.think, "options": options | {"seed": seed}},
                                   timeout=120 if args.think else 60, url=endpoint)
                        elapsed = time.monotonic() - start
                        details = response_details(data)
                    except (urllib.error.URLError, OSError, ValueError) as error:
                        failed = True
                        write_json(output, {"requested_model": model, "seed": seed, "error": str(error),
                                            "elapsed_seconds": time.monotonic() - start})
                        output.flush()
                        continue
                    preview = at_most(one_emoji(details["reply"], shape["emoji"]),
                                      LINE_SENTENCES if shape["one_line"] else MAX_SENTENCES)
                    record = {"requested_model": model, "returned_model": data.get("model"),
                              "installed_digest": (identities[model] or {}).get("digest"), "seed": seed,
                              "think_requested": args.think, **details, "shaped_preview": preview,
                              "elapsed_seconds": elapsed,
                              "load_seconds": (data["load_duration"] / 1e9
                                               if isinstance(data.get("load_duration"), (int, float)) else None),
                              "total_seconds": (data["total_duration"] / 1e9
                                                if isinstance(data.get("total_duration"), (int, float)) else None),
                              "prompt_eval_count": data.get("prompt_eval_count"),
                              "eval_count": data.get("eval_count"), "done_reason": data.get("done_reason")}
                    write_json(output, record)
                    if not details["reply"]:
                        failed = True
                    output.flush()
    print(f"Report: {Path(output.name).resolve()}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
