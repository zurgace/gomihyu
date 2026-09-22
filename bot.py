"""
Gomihyu — a Discord conversationalist backed by a local LFM2.5-2.6B (via Ollama).

Behavior:
  - Always replies when @mentioned.
  - Otherwise replies to any message with probability UNPROMPTED_REPLY_CHANCE (default 1.0,
    i.e. every message).
  - One reply at a time per channel. Messages that arrive while a reply is being written get
    a single follow-up reply to the latest chat, not one reply each.
  - No cooldown — designed for a small, slow server (see README).

Setup is in README.md. Persona and prompt format live in persona.py, shared with the
fine-tuning data builder, so they're easy to swap out without touching the bot logic.
"""

import os
import re
import json
import time
import random
import asyncio
import logging
from collections import defaultdict, deque

import aiohttp
import discord
from dotenv import load_dotenv

from persona import BOT_NAME, build_messages, format_line

load_dotenv()

DISCORD_TOKEN = os.environ["DISCORD_BOT_TOKEN"]
OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://localhost:11434/api/chat")
MODEL_NAME = os.environ.get("OLLAMA_MODEL", "hf.co/lmstudio-community/LFM2.5-2.6B-GGUF:Q4_K_M")
UNPROMPTED_REPLY_CHANCE = float(os.environ.get("UNPROMPTED_REPLY_CHANCE", "1.0"))
HISTORY_LENGTH = int(os.environ.get("HISTORY_LENGTH", "12"))  # recent messages kept per channel for context

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("gomihyu")

intents = discord.Intents.default()
intents.message_content = True  # required — must also be enabled in the Dev Portal, see README
# The bot pings people on purpose (see to_pings), but never @everyone/@here or roles.
client = discord.Client(intents=intents, allowed_mentions=discord.AllowedMentions(everyone=False, roles=False, users=True))

# channel_id -> deque of "handle: content" lines, most recent last
history = defaultdict(lambda: deque(maxlen=HISTORY_LENGTH))
# channel_id -> messages logged so far, so a reply can be slotted in ahead of ones it never saw
logged = defaultdict(int)
# channel_id -> held while a reply is being generated and sent
reply_locks = defaultdict(asyncio.Lock)
# channel_id -> whether anything that arrived mid-reply @mentioned the bot; present = one follow-up owed
pending_followup = {}
# lowercase Discord handle -> user id, so "@handle" in a reply can become a real ping
handles = {}

MENTION_TOKEN = re.compile(r"<(@!?|@&|#)(\d+)>")
HANDLE = re.compile(r"@([\w.]*\w)")
OWN_NAME_PREFIX = re.compile(rf"^\s*[*_]*{re.escape(BOT_NAME)}[*_]*\s*:[*_]*\s*", re.IGNORECASE)


def readable(message: discord.Message) -> str:
    """message.content with raw <@id>/<@&id>/<#id> tokens swapped for @handle, @role, #channel."""
    names = {user.id: f"@{user.name}" for user in message.mentions}
    names.update({role.id: f"@{role.name}" for role in message.role_mentions})
    names.update({channel.id: f"#{channel.name}" for channel in message.channel_mentions})
    return MENTION_TOKEN.sub(lambda m: names.get(int(m[2]), m[0]), message.content)


def to_pings(text: str) -> str:
    """Turn "@handle" into a real <@id> mention for anyone the bot has seen."""
    def ping(m: re.Match) -> str:
        user_id = handles.get(m[1].lower())
        return f"<@{user_id}>" if user_id else m[0]
    return HANDLE.sub(ping, text)


async def generate_reply(channel_id: int, triggered_by_mention: bool) -> str | None:
    payload = {
        "model": MODEL_NAME,
        "messages": build_messages(list(history[channel_id]), triggered_by_mention),
        "stream": False,
    }

    start = time.monotonic()
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(OLLAMA_URL, json=payload, timeout=aiohttp.ClientTimeout(total=60)) as resp:
                if resp.status != 200:
                    # Ollama explains itself in the body (e.g. "model ... not found, try pulling it first").
                    log.error(f"Ollama returned HTTP {resp.status} for model {MODEL_NAME!r}: {(await resp.text())[:500]}")
                    return None
                data = await resp.json()
    except Exception:
        log.exception(f"Generation failed after {time.monotonic() - start:.1f}s (Ollama at {OLLAMA_URL})")
        return None

    # Small models often start with "Gomihyu:" anyway, copying the log format.
    reply = OWN_NAME_PREFIX.sub("", data.get("message", {}).get("content", "").strip())
    log.info(f"Generated in {time.monotonic() - start:.1f}s "
             f"(done_reason={data.get('done_reason')}, tokens={data.get('eval_count')}): {reply[:200]!r}")
    if not reply:
        log.warning(f"Model gave an empty reply, nothing will be sent. Raw response: {json.dumps(data)[:1000]}")
    return reply


async def reply_to(channel: discord.abc.Messageable, channel_id: int, mentioned: bool) -> None:
    seen = logged[channel_id]
    async with channel.typing():
        reply = await generate_reply(channel_id, triggered_by_mention=mentioned)

    if reply:
        # Log the reply right after the messages it answered, ahead of any that arrived while it
        # was being written, so a follow-up's last log line is still the newest unanswered message.
        lines = history[channel_id]
        newer = [lines.pop() for _ in range(min(logged[channel_id] - seen, len(lines)))]
        lines.append(format_line(BOT_NAME, reply))
        lines.extend(reversed(newer))
        await channel.send(to_pings(reply)[:2000])  # Discord's hard message-length limit


@client.event
async def on_ready():
    log.info(f"Logged in as {client.user} (id: {client.user.id})")


@client.event
async def on_message(message: discord.Message):
    if message.author.id == client.user.id or message.author.bot:
        return

    channel_id = message.channel.id
    history[channel_id].append(format_line(message.author.name, readable(message)))
    logged[channel_id] += 1
    for user in (message.author, *message.mentions):
        handles[user.name.lower()] = user.id

    mentioned = client.user in message.mentions
    should_respond = mentioned or (random.random() < UNPROMPTED_REPLY_CHANCE)

    if not should_respond:
        return

    lock = reply_locks[channel_id]
    if lock.locked():
        # Already writing a reply here; answer everything that arrives meanwhile in one follow-up.
        pending_followup[channel_id] = pending_followup.get(channel_id, False) or mentioned
        return

    async with lock:
        try:
            await reply_to(message.channel, channel_id, mentioned)
            while channel_id in pending_followup:
                await reply_to(message.channel, channel_id, pending_followup.pop(channel_id))
        finally:
            pending_followup.pop(channel_id, None)


if __name__ == "__main__":
    client.run(DISCORD_TOKEN)
