"""
Can her model actually see images? Sends a few solid-colour pictures to Ollama and asks for the colour.

    venv/bin/python tools/vision_check.py

Uses OLLAMA_URL and OLLAMA_MODEL from .env, like the bot. Some Ollama versions hand gemma4:e4b a blank
image (github.com/ollama/ollama/issues/18560, reported on 0.33.3 and 0.34.2): the model then says every
picture is black, or that it sees no image, instead of naming the colour. Run this before building
anything on her vision. The first answer can take a while: Ollama loads the vision part on first use.
"""

import base64
import json
import os
import struct
import sys
import urllib.error
import urllib.request
import zlib
from pathlib import Path

try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parent.parent / ".env")
except ImportError:  # run without the venv: the defaults below
    pass

URL = os.environ.get("OLLAMA_URL", "http://localhost:11434/api/chat")
MODEL = os.environ.get("OLLAMA_MODEL", "gemma4:e4b")
NUM_CTX = int(os.environ.get("OLLAMA_NUM_CTX", "8192"))  # the bot's, so Ollama doesn't reload the model
COLOURS = {"red": (230, 20, 20), "green": (20, 170, 40), "blue": (20, 40, 230), "yellow": (250, 220, 20)}


def png(rgb: tuple[int, int, int], size: int = 96) -> bytes:
    """A solid-colour PNG, built by hand so this needs nothing installed."""
    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)
    row = b"\x00" + bytes(rgb) * size
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(row * size)) + chunk(b"IEND", b""))


def ask(image: bytes, model: str = MODEL) -> str:
    body = {"model": model, "stream": False, "think": False, "options": {"num_ctx": NUM_CTX, "temperature": 0},
            "messages": [{"role": "user", "content": "What colour fills this whole picture? Answer with one word.",
                          "images": [base64.b64encode(image).decode()]}]}
    request = urllib.request.Request(URL, json.dumps(body).encode(), {"Content-Type": "application/json"})
    with urllib.request.urlopen(request, timeout=180) as response:
        return json.load(response).get("message", {}).get("content", "").strip()


def main() -> int:
    print(f"Asking {MODEL} at {URL} what colour {len(COLOURS)} plain pictures are...")
    right, answers = 0, []
    for name, rgb in COLOURS.items():
        try:
            answer = ask(png(rgb))
        except urllib.error.HTTPError as e:
            print(f"Ollama said HTTP {e.code}: {e.read().decode(errors='replace')[:300]}")
            return 2
        except (urllib.error.URLError, OSError) as e:
            print(f"Couldn't reach Ollama at {URL} ({e}). Is it running?")
            return 2
        ok = name in answer.lower()
        right += ok
        answers.append(answer.lower())
        print(f"  {name:>6}: {answer[:80]!r}  {'right' if ok else 'WRONG'}")
    if right == len(COLOURS):
        print("She can see: every colour was right. Vision works with this model and Ollama version.")
        return 0
    if all("black" in a or "no image" in a or "not see" in a or "can't see" in a or "cannot see" in a for a in answers):
        print("The images aren't reaching the model: the blank-image bug (ollama/ollama#18560). Vision won't work "
              "with this Ollama version; check `ollama -v` and try a newer one.")
    else:
        print(f"Only {right} of {len(COLOURS)} right: something's off, so don't rely on her vision yet.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
