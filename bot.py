"""
Gomihyu — a Discord conversationalist backed by a local LFM2.5-2.6B (via Ollama).

Behavior:
  - Always replies when @mentioned.
  - Otherwise replies to any message with probability UNPROMPTED_REPLY_CHANCE (default 1.0,
    i.e. every message), except posts that don't need words (images, emoji-only posts, "lol"):
    those get an emoji reaction as her whole response (reactions.py, emojis.py).
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
from pathlib import Path

import aiohttp
import discord
from dotenv import load_dotenv

from censor import has_slur
from emojis import CUSTOM, LOOKING, SAD_NEWS, SLUR_STANDIN, UNICODE
from memory import PeopleMemory, aimed_at_her, fact_to_remember, nicknames_in
from persona import BOT_NAME, BOT_NICKNAME, build_messages, format_line
from reactions import media_only, picker_format, picker_messages, posted_emoji, reacts_instead, sad_news

load_dotenv()

DISCORD_TOKEN = os.environ["DISCORD_BOT_TOKEN"]
OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://localhost:11434/api/chat")
MODEL_NAME = os.environ.get("OLLAMA_MODEL", "gomihyu-base")  # built with the Modelfile, see README
UNPROMPTED_REPLY_CHANCE = float(os.environ.get("UNPROMPTED_REPLY_CHANCE", "1.0"))
# Posts of at most this many words (no "?", not aimed at her) get a reaction instead of a reply.
REACT_ONLY_MAX_WORDS = int(os.environ.get("REACT_ONLY_MAX_WORDS", "2"))
HISTORY_LENGTH = int(os.environ.get("HISTORY_LENGTH", "12"))  # recent messages kept per channel for context
# A reply that copies REPEAT_WORDS words in a row from one of the bot's recent messages is
# regenerated once at RETRY_TEMPERATURE (small models love copying their own earlier lines).
REPEAT_WORDS = int(os.environ.get("REPEAT_WORDS", "5"))
RETRY_TEMPERATURE = float(os.environ.get("RETRY_TEMPERATURE", "1.0"))
# Ceiling on a reply's length; one that hits it is cut back to its last full sentence.
MAX_REPLY_TOKENS = int(os.environ.get("MAX_REPLY_TOKENS", "200"))
# Let a thinking model reason before answering. Off: for chat it only adds delay, and its thinking
# counts against MAX_REPLY_TOKENS, which can leave no room for the answer.
OLLAMA_THINK = os.environ.get("OLLAMA_THINK", "false").strip().lower() in ("1", "true", "yes", "on")
# Whether answers come with thinking: OLLAMA_THINK, or seen in a response (some models think even when
# told not to). Replies then go uncapped, since the thinking counts against MAX_REPLY_TOKENS.
model_thinks = OLLAMA_THINK
# Facts people ask her to remember; relative paths are next to this file. Survives restarts.
PEOPLE_FILE = Path(__file__).resolve().parent / os.environ.get("PEOPLE_FILE", "people.json")
MAX_FACTS_PER_PERSON = int(os.environ.get("MAX_FACTS_PER_PERSON", "20"))
REMEMBERED_EMOJI = "📝"  # reaction confirming a fact or nickname was stored

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
# lowercase Discord handle or display name -> user id, for real pings and for "Yuzuki's nickname is..."
handles = {}
# user id -> display name, for everyone seen
display_names = {}
# channel_id -> (user id, handle) of the latest message, whose remembered facts a reply gets
last_author = {}
memory = PeopleMemory(PEOPLE_FILE, MAX_FACTS_PER_PERSON)

MENTION_TOKEN = re.compile(r"<(@!?|@&|#)(\d+)>")
CUSTOM_EMOJI_TOKEN = re.compile(r"<a?:(\w+):\d+>")
CUSTOM_EMOJI_NAME = re.compile(r":(\w+):")
# Custom emojis she may post: the in-text ones, plus the stand-in she posts instead of a slur.
POSTABLE_EMOJIS = {name.lower() for name, (_, in_text) in CUSTOM.items() if in_text} | {SLUR_STANDIN.lower()}
HANDLE = re.compile(r"@([\w.]*\w)")
SENTENCE_END = re.compile(r"[.!?…](?=\s|$)")
OWN_NAME_PREFIX = re.compile(rf"^\s*[*_]*(?:{BOT_NAME}|{BOT_NICKNAME})[*_]*\s*:[*_]*\s*", re.IGNORECASE)


def readable(message: discord.Message) -> str:
    """message.content as the model sees it: <@id>/<@&id>/<#id> as @handle/@role/#channel,
    custom emojis as :name:, and attachments/stickers as [image]/[video]/[file]/[sticker: name]."""
    names = {user.id: f"@{user.name}" for user in message.mentions}
    names.update({role.id: f"@{role.name}" for role in message.role_mentions})
    names.update({channel.id: f"#{channel.name}" for channel in message.channel_mentions})
    text = MENTION_TOKEN.sub(lambda m: names.get(int(m[2]), m[0]), message.content)
    text = CUSTOM_EMOJI_TOKEN.sub(r":\1:", text)
    kinds = [(a.content_type or "").split("/")[0] for a in message.attachments]
    media = [f"[{kind if kind in ('image', 'video') else 'file'}]" for kind in kinds]
    media += [f"[sticker: {sticker.name}]" for sticker in message.stickers]
    return " ".join([text, *media]).strip()


def to_pings(text: str) -> str:
    """Turn "@handle" (or @nickname, @display name) into a real <@id> mention for anyone known."""
    def ping(m: re.Match) -> str:
        user_id = handles.get(m[1].lower()) or memory.find(m[1])
        return f"<@{user_id}>" if user_id else m[0]
    return HANDLE.sub(ping, text)


def to_server_emojis(text: str, guild: discord.Guild | None) -> str:
    """Turn ":name:" for this server's postable emojis (see emojis.py) into the real emoji."""
    server = {e.name.lower(): e for e in guild.emojis if e.name.lower() in POSTABLE_EMOJIS} if guild else {}
    return CUSTOM_EMOJI_NAME.sub(lambda m: str(server.get(m[1].lower(), m[0])), text)


def strip_thinking(text: str) -> str:
    """Drop reasoning a model wrote into the answer itself (<think>...</think>); it's never posted."""
    text = text.rsplit("</think>", 1)[-1]
    return text.split("<think>", 1)[0]  # an unclosed <think>: the answer never came


def word_runs(text: str) -> set[tuple[str, ...]]:
    words = re.findall(r"[\w']+", text.lower())
    return {tuple(words[i:i + REPEAT_WORDS]) for i in range(len(words) - REPEAT_WORDS + 1)}


def repeats_itself(channel_id: int, reply: str) -> bool:
    """Whether reply copies a run of REPEAT_WORDS words from one of the bot's messages in the log."""
    own = format_line(BOT_NAME, "")
    runs = word_runs(reply)
    return any(runs & word_runs(line[len(own):]) for line in history[channel_id] if line.startswith(own))


async def ollama_chat(payload: dict) -> dict | None:
    """One non-streaming call to Ollama's chat API: the response, or None with the reason logged."""
    global model_thinks
    start = time.monotonic()
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(OLLAMA_URL, json={"model": MODEL_NAME, "stream": False, "think": OLLAMA_THINK,
                                                      **payload},
                                    timeout=aiohttp.ClientTimeout(total=60)) as resp:
                if resp.status != 200:
                    # Ollama explains itself in the body (e.g. "model ... not found, try pulling it first").
                    log.error(f"Ollama returned HTTP {resp.status} for model {MODEL_NAME!r}: {(await resp.text())[:500]}")
                    return None
                data = await resp.json()
    except Exception:
        log.exception(f"Generation failed after {time.monotonic() - start:.1f}s (Ollama at {OLLAMA_URL})")
        return None
    if not model_thinks and data.get("message", {}).get("thinking"):
        model_thinks = True
        log.warning(f"{MODEL_NAME} thinks before answering even with OLLAMA_THINK=false, so replies take longer. "
                    f"They're no longer capped at MAX_REPLY_TOKENS ({MAX_REPLY_TOKENS}), which the thinking counts against.")
    return data


async def generate_reply(channel_id: int, triggered_by_mention: bool, temperature: float | None = None) -> str | None:
    # Only the person being replied to gets their facts in context, never everyone's.
    author_id, author_handle = last_author[channel_id]
    # Everyone in the log gets their nickname, though, so she can call them by it.
    speakers = dict.fromkeys(line.split(": ", 1)[0] for line in history[channel_id])
    nicknames = {handle: nick for handle in speakers
                 if (user_id := handles.get(handle.lower())) and (nick := memory.nickname_for(user_id))}
    options = {} if model_thinks else {"num_predict": MAX_REPLY_TOKENS}  # thinking would eat into the cap
    if temperature is not None:
        options["temperature"] = temperature  # otherwise the model's own (Modelfile) setting
    payload = {"messages": build_messages(list(history[channel_id]), triggered_by_mention,
                                          author_handle, memory.facts_for(author_id), nicknames),
               "options": options}

    start = time.monotonic()
    data = await ollama_chat(payload)
    if data and "num_predict" in options and data.get("done_reason") == "length" and data.get("message", {}).get("thinking"):
        # Thinking used up the cap before the answer was done (the first reply from a model that turns
        # out to think). Let it finish rather than go quiet or send half a sentence.
        log.warning(f"Thinking used up the {MAX_REPLY_TOKENS}-token cap before the answer was done; retrying without it")
        del options["num_predict"]
        data = await ollama_chat(payload)
    if data is None:
        return None

    # Small models often start with "Gomihyu:" anyway, copying the log format.
    reply = OWN_NAME_PREFIX.sub("", strip_thinking(data.get("message", {}).get("content", "")).strip())
    if data.get("done_reason") == "length" and (ends := list(SENTENCE_END.finditer(reply))):
        reply = reply[:ends[-1].end()]  # ran into MAX_REPLY_TOKENS: drop the half-finished sentence
    # A reply with a slur in it is thrown away whole, before it's sent or kept in the chat
    # history: she just stares instead.
    if has_slur(reply):
        log.info(f"Reply had a slur, posting :{SLUR_STANDIN}: instead (was: {reply[:200]!r})")
        reply = f":{SLUR_STANDIN}:"
    log.info(f"Generated in {time.monotonic() - start:.1f}s "
             f"(done_reason={data.get('done_reason')}, tokens={data.get('eval_count')}): {reply[:200]!r}")
    if not reply:
        log.warning(f"Model gave an empty reply, nothing will be sent. Raw response: {json.dumps(data)[:1000]}")
    return reply


async def reply_to(channel: discord.abc.Messageable, channel_id: int, mentioned: bool) -> None:
    seen = logged[channel_id]
    async with channel.typing():
        reply = await generate_reply(channel_id, triggered_by_mention=mentioned)
        if reply and repeats_itself(channel_id, reply):
            log.info(f"Reply repeats one of Gomihyu's recent messages; retrying at temperature {RETRY_TEMPERATURE}")
            # If the retry fails outright, the repetitive reply beats no reply.
            reply = await generate_reply(channel_id, triggered_by_mention=mentioned, temperature=RETRY_TEMPERATURE) or reply

    if reply:
        # Log the reply right after the messages it answered, ahead of any that arrived while it
        # was being written, so a follow-up's last log line is still the newest unanswered message.
        lines = history[channel_id]
        newer = [lines.pop() for _ in range(min(logged[channel_id] - seen, len(lines)))]
        lines.append(format_line(BOT_NAME, reply))
        lines.extend(reversed(newer))
        text = to_server_emojis(to_pings(reply), getattr(channel, "guild", None))
        await channel.send(text[:2000])  # Discord's hard message-length limit


async def choose_reaction(message: discord.Message, text: str) -> str | discord.Emoji | None:
    """The emoji for a post that gets a reaction instead of a reply, or None to leave it be."""
    server = {e.name.lower(): e for e in message.guild.emojis} if message.guild else {}

    def usable(name: str) -> bool:
        return name in UNICODE or name.lower() in server

    def as_reaction(name: str) -> str | discord.Emoji:
        return name if name in UNICODE else server[name.lower()]

    if media_only(text):  # she can't see images, so she doesn't pretend to judge them
        looks = [name for name in LOOKING if usable(name)]
        return as_reaction(random.choice(looks)) if looks else None

    options = dict(UNICODE) | {name: use for name, (use, _) in CUSTOM.items() if usable(name)}
    posted = posted_emoji(text)
    same = server.get(posted.strip(":").lower()) if posted and posted.startswith(":") else posted
    if same:
        options["same"] = "the same emoji they posted, joining in"

    recent = list(history[message.channel.id])[-5:]
    data = await ollama_chat({"messages": picker_messages(recent, options), "format": picker_format(options)})
    if data is None:
        return None
    answer = data.get("message", {}).get("content", "")
    try:
        choice = str(json.loads(answer)["emoji"])
    except (ValueError, KeyError, TypeError):
        choice = answer.strip().strip('"').strip(":")  # in case the JSON format wasn't honored
    if choice == "same" and same:
        return same
    if choice in options and choice != "same":
        return as_reaction(choice)
    log.info(f"No reaction for {message.author.name}: picker answered {choice!r}")
    return None


def find_person(who: str, message: discord.Message) -> int | None:
    """The user id behind "me" or a name/handle someone used, if the bot knows who that is."""
    if who.lower() == "me":
        return message.author.id
    if who.lower() in ("you", "yourself", BOT_NAME.lower(), BOT_NICKNAME.lower()):
        return None  # her own name is fixed
    return handles.get(who.lower()) or memory.find(who)


async def take_notes(message: discord.Message, text: str, mentioned: bool) -> None:
    """Store what a message aimed at her explicitly asks her to remember: facts and nicknames."""
    noted = False
    if fact := fact_to_remember(text, mentioned):
        memory.remember(message.author.id, message.author.display_name, fact)
        log.info(f"Remembered for {message.author.name}: {fact!r}")
        noted = True
    if aimed_at_her(text, mentioned):
        for who, nick in nicknames_in(text):
            if (user_id := find_person(who, message)) is None:
                log.warning(f"Nickname {nick!r} not saved: don't know who {who!r} is")
            elif has_slur(nick):
                log.warning(f"Nickname for {who!r} not saved: it has a slur in it")
            else:
                memory.set_nickname(user_id, display_names.get(user_id), nick)
                log.info(f"Nickname for {who} (id {user_id}) is now {nick!r}, set by {message.author.name}")
                noted = True
    if noted:
        await react(message, REMEMBERED_EMOJI)


async def react(message: discord.Message, emoji: str | discord.Emoji) -> None:
    try:
        await message.add_reaction(emoji)
        log.info(f"Reacted {emoji} to {message.author.name}")
    except discord.HTTPException as e:  # e.g. the bot lacks the Add Reactions permission
        log.warning(f"Couldn't react {emoji} to {message.author.name}: {e}")


@client.event
async def on_ready():
    log.info(f"Logged in as {client.user} (id: {client.user.id})")


@client.event
async def on_message(message: discord.Message):
    if message.author.id == client.user.id or message.author.bot:
        return

    channel_id = message.channel.id
    text = readable(message)
    history[channel_id].append(format_line(message.author.name, text))
    logged[channel_id] += 1
    for user in (message.author, *message.mentions):
        handles[user.name.lower()] = user.id
        handles[user.display_name.lower()] = user.id
        display_names[user.id] = user.display_name
    last_author[channel_id] = (message.author.id, message.author.name)

    mentioned = client.user in message.mentions

    await take_notes(message, text, mentioned)

    # Sad news gets a sad cat on top of her reply (it never counts as a post that doesn't need words).
    if sad_news(text) and message.guild:
        if cat := next((e for e in message.guild.emojis if e.name.lower() == SAD_NEWS.lower()), None):
            await react(message, cat)

    # Posts that don't need words (images, emoji-only, "lol") get a reaction as her whole response.
    # A reaction isn't a message, so it stays out of the chat history.
    if not mentioned and reacts_instead(text, REACT_ONLY_MAX_WORDS):
        if emoji := await choose_reaction(message, text):
            await react(message, emoji)
        return

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
