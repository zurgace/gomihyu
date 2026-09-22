"""
Gomihyu — a Discord conversationalist backed by a local LFM2.5-2.6B (via Ollama).

Behavior:
  - Always replies when @mentioned.
  - Otherwise replies unprompted to any message with probability UNPROMPTED_REPLY_CHANCE.
  - No cooldown — designed for a small, low-traffic server (see README).

Setup is in README.md. Persona lives in persona.py so it's easy to swap out
(e.g. for the fine-tuned LoRA later) without touching the bot logic.
"""

import os
import random
import logging
from collections import defaultdict, deque

import aiohttp
import discord
from dotenv import load_dotenv

from persona import SYSTEM_PROMPT

load_dotenv()

DISCORD_TOKEN = os.environ["DISCORD_BOT_TOKEN"]
OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://localhost:11434/api/chat")
MODEL_NAME = os.environ.get("OLLAMA_MODEL", "hf.co/lmstudio-community/LFM2.5-2.6B-GGUF:Q4_K_M")
UNPROMPTED_REPLY_CHANCE = float(os.environ.get("UNPROMPTED_REPLY_CHANCE", "0.5"))
HISTORY_LENGTH = int(os.environ.get("HISTORY_LENGTH", "12"))  # recent messages kept per channel for context

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("gomihyu")

intents = discord.Intents.default()
intents.message_content = True  # required — must also be enabled in the Dev Portal, see README
client = discord.Client(intents=intents)

# channel_id -> deque of "display_name: content" strings, most recent last
history = defaultdict(lambda: deque(maxlen=HISTORY_LENGTH))


async def generate_reply(channel_id: int, triggered_by_mention: bool) -> str | None:
    transcript = "\n".join(history[channel_id])
    instruction = (
        "Above is the recent chat log in a Discord server. "
        "Write your next message as Gomihyu, replying naturally to the most recent line. "
        "Keep it short, like a real Discord message (usually 1-2 sentences). "
        "Do not prefix your reply with your own name."
    )
    if triggered_by_mention:
        instruction += " You were just directly mentioned/addressed — respond to that directly, in character."

    payload = {
        "model": MODEL_NAME,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": f"{transcript}\n\n{instruction}"},
        ],
        "stream": False,
    }

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(OLLAMA_URL, json=payload, timeout=aiohttp.ClientTimeout(total=60)) as resp:
                resp.raise_for_status()
                data = await resp.json()
                return data["message"]["content"].strip()
    except Exception:
        log.exception("Generation failed")
        return None


@client.event
async def on_ready():
    log.info(f"Logged in as {client.user} (id: {client.user.id})")


@client.event
async def on_message(message: discord.Message):
    if message.author.id == client.user.id or message.author.bot:
        return

    history[message.channel.id].append(f"{message.author.display_name}: {message.content}")

    mentioned = client.user in message.mentions
    should_respond = mentioned or (random.random() < UNPROMPTED_REPLY_CHANCE)

    if not should_respond:
        return

    async with message.channel.typing():
        reply = await generate_reply(message.channel.id, triggered_by_mention=mentioned)

    if reply:
        history[message.channel.id].append(f"Gomihyu: {reply}")
        await message.channel.send(reply[:2000])  # Discord's hard message-length limit


if __name__ == "__main__":
    client.run(DISCORD_TOKEN)
