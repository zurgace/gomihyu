"""
Gomihyu — a Discord conversationalist backed by a small local model (via Ollama).

Behavior:
  - Always replies when @mentioned, replied to, or named ("gomi"), and to sad news.
  - Posts that don't need words (images, emoji-only posts, "lol") get an emoji reaction as her
    whole response instead (reactions.py, emojis.py).
  - Any other post, she chimes in only if it interests her: a short model call rates it 0-10,
    and she replies at CHIME_IN_THRESHOLD or above (chime.py).
  - One reply at a time per channel. Messages that arrive while a reply is being written get
    a single follow-up reply to the latest chat, not one reply each.
  - No cooldown — designed for a small, slow server (see README).
  - Logs the server's chat to disk (chatlog.py) and, at shutdown (Ctrl+C or an owner's "gomi
    goodnight"), writes her diary from it: recaps and checked notes on people (diary.py).

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
import signal
from collections import defaultdict, deque
from pathlib import Path

import aiohttp
import discord
from dotenv import load_dotenv

from censor import has_slur
from chatlog import ChatLog, local_day
from chime import INTEREST_FORMAT, interest_messages, parse_interest
from commands import (ALL, FOREVER, delete_request, goodnight_request, melee_here_request, melee_stop_request, mute_request,
                      quiet_request,
                      unmute_request)
from diary import Diary, chunks, digest_format, digest_messages, parse_digest
from meld import VIBE_FORMAT, landed_replies, parse_vibe, pick_examples, vibe_messages
from emojis import CUSTOM, LOOKING, SAD_NEWS, SLUR_STANDIN, UNICODE
from melee import (TAUNT_WINDOW_SECONDS, default_outbox, load_channel, match_facts, read_outbox, save_channel,
                   stale)
from memory import PeopleMemory, aimed_at_her, fact_to_remember, nicknames_in
from persona import BOT_NAME, BOT_NICKNAME, build_goodnight_messages, build_match_messages, build_messages, format_line
from reactions import media_only, names_her, picker_format, picker_messages, posted_emoji, reacts_instead, sad_news

load_dotenv()

DISCORD_TOKEN = os.environ["DISCORD_BOT_TOKEN"]
OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://localhost:11434/api/chat")
MODEL_NAME = os.environ.get("OLLAMA_MODEL", "gemma4:e4b")
# Posts not aimed at her are rated 0-10 for how much she'd want to chime in (chime.py); she replies
# at this or above. Higher is quieter; 0 answers everything without asking.
CHIME_IN_THRESHOLD = int(os.environ.get("CHIME_IN_THRESHOLD", "6"))
# Posts of at most this many words (no "?", not aimed at her) get a reaction instead of a reply.
REACT_ONLY_MAX_WORDS = int(os.environ.get("REACT_ONLY_MAX_WORDS", "2"))
HISTORY_LENGTH = int(os.environ.get("HISTORY_LENGTH", "12"))  # recent messages kept per channel for context
# A reply that copies REPEAT_WORDS words in a row from one of the bot's recent messages is
# regenerated once at RETRY_TEMPERATURE (small models love copying their own earlier lines).
REPEAT_WORDS = int(os.environ.get("REPEAT_WORDS", "5"))
RETRY_TEMPERATURE = float(os.environ.get("RETRY_TEMPERATURE", "1.0"))
# Ceiling on a reply's length; one that hits it is cut back to its last full sentence.
MAX_REPLY_TOKENS = int(os.environ.get("MAX_REPLY_TOKENS", "200"))
# Context window, in tokens, for every call. Ollama's default of 4096 can be outgrown by the prompt
# (system prompt, example chats, 12 messages of chat) when people post long messages, and Ollama then
# silently cuts the prompt. Every call sends the same value, or Ollama reloads the model between them.
OLLAMA_NUM_CTX = int(os.environ.get("OLLAMA_NUM_CTX", "8192"))
# Let a thinking model reason before answering. Off: for chat it only adds delay, and its thinking
# counts against MAX_REPLY_TOKENS, which can leave no room for the answer.
OLLAMA_THINK = os.environ.get("OLLAMA_THINK", "false").strip().lower() in ("1", "true", "yes", "on")
# Whether answers come with thinking: OLLAMA_THINK, or seen in a response (some models think even when
# told not to). Replies then go uncapped, since the thinking counts against MAX_REPLY_TOKENS.
model_thinks = OLLAMA_THINK
# Facts people ask her to remember; relative paths are next to this file. Survives restarts.
PEOPLE_FILE = Path(__file__).resolve().parent / os.environ.get("PEOPLE_FILE", "people.json")
MAX_FACTS_PER_PERSON = int(os.environ.get("MAX_FACTS_PER_PERSON", "20"))
# Her diary (diary.py): when the bot shuts down she reads the day's chat log (every message in the
# server's channels, kept in CHAT_LOG_DIR; never DMs) and writes a recap per channel (DIARY_FILE)
# and notes on people (people.json, at most MAX_LEARNED_PER_PERSON each, oldest dropping off). Her
# prompt gets the last RECAP_DAYS days of recaps, and after a restart she picks the chat back up
# from the log if it's newer than HISTORY_RELOAD_HOURS.
CHAT_LOG_DIR = Path(__file__).resolve().parent / os.environ.get("CHAT_LOG_DIR", "chatlogs")
DIARY_FILE = Path(__file__).resolve().parent / os.environ.get("DIARY_FILE", "diary.json")
MAX_LEARNED_PER_PERSON = int(os.environ.get("MAX_LEARNED_PER_PERSON", "10"))
RECAP_DAYS = int(os.environ.get("RECAP_DAYS", "3"))
HISTORY_RELOAD_HOURS = float(os.environ.get("HISTORY_RELOAD_HOURS", "12"))
DIARY_PART_CHARS = 12000  # chat per diary call: ~3k tokens, well inside OLLAMA_NUM_CTX with the answer
# Melding (meld.py): the server slowly shapes her. Each night her replies that landed are kept in
# EARNED_FILE and join her example chats, replacing Satania ones as they pile up (MELD_FULL_AT earned:
# all the way down to MELD_ANCHOR, the share of Satania examples that always stays); and, with at
# least VIBE_MIN_MESSAGES new messages, her note on how the server talks is updated.
EARNED_FILE = Path(__file__).resolve().parent / os.environ.get("EARNED_FILE", "earned_examples.jsonl")
MELD_ANCHOR = float(os.environ.get("MELD_ANCHOR", "0.3"))
MELD_FULL_AT = int(os.environ.get("MELD_FULL_AT", "200"))
VIBE_MIN_MESSAGES = int(os.environ.get("VIBE_MIN_MESSAGES", "10"))
VIBE_CHARS = 8000  # newest chat the vibe note is updated from
GOODNIGHT_EMOJI = "💤"
REMEMBERED_EMOJI = "📝"  # reaction confirming a fact or nickname was stored
# Who can make her delete her posts ("gomi delete that", commands.py): the bot application's owner,
# looked up at login, plus these Discord user ids (comma-separated).
OWNER_USER_IDS = {int(user_id) for user_id in re.findall(r"\d+", os.environ.get("OWNER_USER_IDS", ""))}
# "Delete all your messages" means her posts among this many of the channel's newest messages.
DELETE_SCAN = int(os.environ.get("DELETE_SCAN", "200"))
DELETED_EMOJI = "🗑️"  # reaction confirming her posts were deleted
NOTHING_TO_DELETE_EMOJI = "🤷"
# How long an owner's "gomi mute" (silent) or "gomi quiet mode" (only answers people talking to her)
# lasts in that channel when they don't say, in minutes.
MUTE_MINUTES = float(os.environ.get("MUTE_MINUTES", "30"))
MUTED_EMOJI = "🔇"  # reaction confirming she's muted
QUIET_EMOJI = "🤫"  # reaction confirming quiet mode
UNMUTED_EMOJI = "🔊"
HUSHED_EMOJI = "🤐"  # on posts aimed at her while she's muted, so people know she isn't broken
# Made-up example chats (the fine-tuning seed) shown in her prompt to set her voice, until a
# fine-tuned model carries it. A fresh random pick each reply; 0 turns them off.
EXAMPLES_FILE = Path(__file__).resolve().parent / os.environ.get("EXAMPLES_FILE", "finetuning/gomihyu_seed.jsonl")
FEW_SHOT_EXAMPLES = int(os.environ.get("FEW_SHOT_EXAMPLES", "8"))
# Melee results (melee.py): the outbox folder AI-Melee leaves her taunts and matches in (by default the
# one both programs know, ~/.local/share/gomihyu/melee-outbox), and the channel she posts them in: the
# one an owner picked with "gomi post melee here" (kept in MELEE_CHANNEL_FILE), else MELEE_CHANNEL_ID.
# Matches older than MELEE_MAX_AGE_MINUTES (played while the bot was off) are dropped unposted.
MELEE_OUTBOX = Path(os.environ.get("MELEE_OUTBOX", "").strip() or default_outbox()).expanduser()
MELEE_CHANNEL_FILE = Path(__file__).resolve().parent / "melee_channel.json"
MELEE_CHANNEL_ID = int(os.environ.get("MELEE_CHANNEL_ID", "0").strip() or "0")
MELEE_EMOJI = "🎮"  # reaction confirming this channel gets her Melee posts
NO_MELEE_EMOJI = "🔕"
MELEE_MAX_AGE_MINUTES = float(os.environ.get("MELEE_MAX_AGE_MINUTES", "30"))
# Who played against her; default: the bot owner's nickname, else their display name.
MELEE_PLAYER = os.environ.get("MELEE_PLAYER", "").strip()
MELEE_CHECK_SECONDS = 5
MELEE_RETRY_SECONDS = 60  # after a match she couldn't post

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
# channel_id -> (whether anything that arrived mid-reply @mentioned her, whether anything was aimed at
# her so it must be answered); present = one follow-up owed
pending_followup = {}
# lowercase Discord handle or display name -> user id, for real pings and for "Yuzuki's nickname is..."
handles = {}
# user id -> display name, for everyone seen
display_names = {}
# channel_id -> (user id, handle) of the latest message, whose remembered facts a reply gets
last_author = {}
# user ids allowed to give owner commands: OWNER_USER_IDS, plus the application's owner(s) at login
owner_ids = set(OWNER_USER_IDS)
# (user id, handle) of the application's owner, looked up at login: who she plays Melee against
app_owner = None
# message id -> (channel_id, her chat-log line) for her recent posts, so a deleted post leaves her log too
posted = {}
# channel_id -> time.monotonic() when her mute there ends (FOREVER: until unmuted). Not kept across restarts.
muted_until = {}
# channel_id -> when her quiet mode there ends (only answers people talking to her). Same rules.
quiet_until = {}
memory = PeopleMemory(PEOPLE_FILE, MAX_FACTS_PER_PERSON, MAX_LEARNED_PER_PERSON)
chat_log = ChatLog(CHAT_LOG_DIR)
diary = Diary(DIARY_FILE)
# held while she writes her diary, so a shutdown waits for a catch-up that's still going
diary_lock = asyncio.Lock()
started = time.time()


def load_examples(path: Path) -> list[dict]:
    if FEW_SHOT_EXAMPLES <= 0:
        return []
    if not path.exists():
        log.warning(f"No example chats at {path}; replying without them")
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


examples = load_examples(EXAMPLES_FILE)


def load_earned(path: Path) -> list[dict]:
    """Her replies that landed (meld.py), kept one JSON per line; unreadable lines are skipped."""
    earned = []
    for line in path.read_text(encoding="utf-8").splitlines() if path.exists() else []:
        try:
            example = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(example, dict) and example.get("reply") and isinstance(example.get("history"), list):
            earned.append(example)
    return earned


earned = load_earned(EARNED_FILE)


def shown_examples() -> list[dict]:
    """This reply's example chats: Satania ones and, more and more, her own that landed."""
    return pick_examples(examples, earned, FEW_SHOT_EXAMPLES, MELD_ANCHOR, MELD_FULL_AT)

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


def muted(channel_id: int) -> bool:
    return muted_until.get(channel_id, 0) > time.monotonic()


def quiet(channel_id: int) -> bool:
    return quiet_until.get(channel_id, 0) > time.monotonic()


def person(name: str) -> int | None:
    """The user id behind a handle, display name or nickname, if known."""
    return handles.get(name.lower()) or memory.find(name)


def to_pings(text: str) -> str:
    """Turn "@handle" (or @nickname, @display name) into a real <@id> mention for anyone known."""
    def ping(m: re.Match) -> str:
        user_id = person(m[1])
        return f"<@{user_id}>" if user_id else m[0]
    return HANDLE.sub(ping, text)


def without_ping(text: str, user_id: int) -> str:
    """text with no @ on user_id's name: they're the one she's answering, already in the conversation,
    and pinging them on every reply is just noise. A leading "@name" goes; any other loses its @."""
    if (m := HANDLE.match(text)) and person(m[1]) == user_id:
        text = text[m.end():].lstrip(" ,:") or m[1]
    return HANDLE.sub(lambda m: m[1] if person(m[1]) == user_id else m[0], text)


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
    """Whether reply copies a run of REPEAT_WORDS words from one of the bot's messages in the log,
    or from an example chat's reply."""
    own = format_line(BOT_NAME, "")
    runs = word_runs(reply)
    return (any(runs & word_runs(line[len(own):]) for line in history[channel_id] if line.startswith(own))
            or any(runs & word_runs(example["reply"]) for example in examples + earned))


async def ollama_chat(payload: dict) -> dict | None:
    """One non-streaming call to Ollama's chat API: the response, or None with the reason logged."""
    global model_thinks
    start = time.monotonic()
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(OLLAMA_URL, json={"model": MODEL_NAME, "stream": False, "think": OLLAMA_THINK,
                                                      **payload,
                                                      "options": {"num_ctx": OLLAMA_NUM_CTX} | payload.get("options", {})},
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
                                          author_handle, memory.facts_for(author_id), nicknames, shown_examples(),
                                          memory.learned_for(author_id), diary.recaps_for(channel_id, RECAP_DAYS),
                                          diary.vibe()),
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
    return clean_reply(data, author_id, start)


def clean_reply(data: dict, author_id: int | None, start: float) -> str:
    """The model's answer as she'll post it; author_id is the person she's answering, if anyone."""
    # Small models often start with "Gomihyu:" anyway, copying the log format.
    reply = OWN_NAME_PREFIX.sub("", strip_thinking(data.get("message", {}).get("content", "")).strip())
    if data.get("done_reason") == "length" and (ends := list(SENTENCE_END.finditer(reply))):
        reply = reply[:ends[-1].end()]  # ran into MAX_REPLY_TOKENS: drop the half-finished sentence
    if author_id is not None:
        reply = without_ping(reply, author_id)
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


async def send_reply(channel: discord.abc.Messageable, channel_id: int, reply: str, seen: int | None = None,
                     about: str = "reply") -> None:
    """Post reply and keep it in her chat log. seen: how many messages had been logged when she started
    writing it, so it goes in right after those, ahead of any that arrived meanwhile. about: what kind
    of post (reply, melee, goodnight); only replies can become examples (meld.py)."""
    text = to_server_emojis(to_pings(reply), getattr(channel, "guild", None))
    try:
        sent = await channel.send(text[:2000])  # Discord's hard message-length limit
    except discord.HTTPException as e:  # e.g. no Send Messages permission there: she never said it
        log.warning(f"Couldn't post in {channel_label(channel)}: {e}")
        return
    lines = history[channel_id]
    newer = [lines.pop() for _ in range(min(logged[channel_id] - seen, len(lines)))] if seen is not None else []
    line = format_line(BOT_NAME, reply)
    lines.append(line)
    lines.extend(reversed(newer))
    if sent:
        posted[sent.id] = (channel_id, line)
        if len(posted) > 1000:
            del posted[next(iter(posted))]
        if getattr(channel, "guild", None):
            chat_log.add(channel_id, channel_label(channel), sent.id, client.user.id, BOT_NAME, reply, about=about)


async def reply_to(channel: discord.abc.Messageable, channel_id: int, mentioned: bool) -> None:
    seen = logged[channel_id]
    async with channel.typing():
        reply = await generate_reply(channel_id, triggered_by_mention=mentioned)
        if reply and repeats_itself(channel_id, reply):
            log.info(f"Reply repeats one of Gomihyu's recent messages or example lines; retrying at temperature {RETRY_TEMPERATURE}")
            # If the retry fails outright, the repetitive reply beats no reply.
            reply = await generate_reply(channel_id, triggered_by_mention=mentioned, temperature=RETRY_TEMPERATURE) or reply

    if reply and muted(channel_id):
        log.info("Muted while writing a reply; not sending it")
        return
    if reply:
        # Log the reply right after the messages it answered, ahead of any that arrived while it
        # was being written, so a follow-up's last log line is still the newest unanswered message.
        await send_reply(channel, channel_id, reply, seen)


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
    theirs = posted_emoji(text)
    same = server.get(theirs.strip(":").lower()) if theirs and theirs.startswith(":") else theirs
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


async def delete_posts(message: discord.Message, count: int) -> None:
    """An owner's "gomi delete that": delete the post this message replies to, or her newest `count`
    posts in the channel (ALL: every one among the last DELETE_SCAN messages). She doesn't answer,
    and the deleted posts leave her chat log, so she can't bring them back up."""
    try:
        if count == 1 and replying_to_her(message):
            targets = [message.reference.resolved]
        else:
            targets = [post async for post in message.channel.history(limit=DELETE_SCAN)
                       if post.author.id == client.user.id]
            targets = targets if count == ALL else targets[:count]
    except discord.HTTPException as e:  # e.g. the bot lacks Read Message History here
        log.warning(f"Couldn't look up her posts to delete: {e}")
        targets = []
    deleted, gone = 0, set()
    for post in targets:
        try:
            await post.delete()
        except discord.NotFound:
            pass  # already gone
        except discord.HTTPException as e:
            log.warning(f"Couldn't delete her post {post.id}: {e}")
            continue
        deleted += 1
        gone.add(post.id)
        if entry := posted.pop(post.id, None):
            channel_id, line = entry
            try:
                history[channel_id].remove(line)
            except ValueError:
                pass  # already scrolled out of her log
    if gone:
        chat_log.forget(message.channel.id, gone)
    log.info(f"Deleted {deleted} of her posts, as {message.author.name} asked")
    await react(message, DELETED_EMOJI if deleted else NOTHING_TO_DELETE_EMOJI)


async def react(message: discord.Message, emoji: str | discord.Emoji) -> None:
    try:
        await message.add_reaction(emoji)
        log.info(f"Reacted {emoji} to {message.author.name}")
    except discord.HTTPException as e:  # e.g. the bot lacks the Add Reactions permission
        log.warning(f"Couldn't react {emoji} to {message.author.name}: {e}")


def replying_to_her(message: discord.Message) -> bool:
    """A Discord reply to one of her messages, even with the ping turned off."""
    replied = getattr(getattr(message, "reference", None), "resolved", None)
    return getattr(getattr(replied, "author", None), "id", None) == client.user.id


async def chimes_in(channel_id: int) -> bool:
    """Whether the newest post, not aimed at her, interests her enough to say something."""
    if CHIME_IN_THRESHOLD <= 0:
        return True
    recent = list(history[channel_id])
    data = await ollama_chat({"messages": interest_messages(recent), "format": INTEREST_FORMAT})
    interest = parse_interest(data.get("message", {}).get("content", "")) if data else None
    newest = recent[-1] if recent else ""
    if interest is None:
        log.warning(f"Couldn't tell whether to chime in, staying quiet. Raw response: {json.dumps(data)[:300]}")
        return False
    log.info(f"Interest {interest}/10 (chimes in at {CHIME_IN_THRESHOLD}) in {newest[:80]!r}"
             + ("" if interest >= CHIME_IN_THRESHOLD else ": staying quiet"))
    return interest >= CHIME_IN_THRESHOLD


@client.event
async def on_ready():
    global app_owner, melee_watcher
    log.info(f"Logged in as {client.user} (id: {client.user.id})")
    # on_ready runs again after a reconnect: one watcher is enough.
    if melee_watcher is None:
        melee_watcher = asyncio.create_task(watch_melee())
        # A crash or a closed terminal skips the diary; catch up on what it left.
        asyncio.create_task(write_diary("catching up on chat from before she started", before=started))
    try:
        app = await client.application_info()
    except discord.HTTPException as e:
        log.warning(f"Couldn't look up the bot's owner ({e}); only OWNER_USER_IDS can make her delete posts")
        return
    owners = app.team.members if app.team else [app.owner]
    owner_ids.update(owner.id for owner in owners)
    app_owner = (owners[0].id, owners[0].name)
    log.info(f"Owner commands (deleting her posts) accepted from: {', '.join(owner.name for owner in owners)}"
             + (f", and user ids {', '.join(map(str, sorted(OWNER_USER_IDS)))}" if OWNER_USER_IDS else ""))


@client.event
async def on_raw_reaction_add(payload: discord.RawReactionActionEvent):
    """A reaction on one of her posts, in a server: logged, since it means the post landed (meld.py)."""
    if not payload.guild_id or payload.user_id == client.user.id or (payload.member and payload.member.bot):
        return
    if getattr(payload, "message_author_id", None) != client.user.id and payload.message_id not in posted:
        return
    channel = client.get_channel(payload.channel_id)
    who = payload.member.name if payload.member else str(payload.user_id)
    chat_log.add(payload.channel_id, channel_label(channel) if channel else f"channel {payload.channel_id}", None,
                 payload.user_id, who, str(payload.emoji), kind="reaction", to=payload.message_id)


@client.event
async def on_message(message: discord.Message):
    if message.author.id == client.user.id or message.author.bot:
        return

    channel_id = message.channel.id
    text = readable(message)
    for user in (message.author, *message.mentions):
        handles[user.name.lower()] = user.id
        handles[user.display_name.lower()] = user.id
        display_names[user.id] = user.display_name
    mentioned = client.user in message.mentions
    for_her = mentioned or replying_to_her(message) or names_her(text)

    # An owner telling her to delete her posts or be quiet overrides the persona: done in code,
    # never shown to the model or kept in her chat log.
    if message.author.id in owner_ids and for_her:
        if goodnight_request(text):
            await go_to_bed(message)
            return
        where = f"#{message.channel.name}" if getattr(message.channel, "name", None) else f"channel {channel_id}"
        if count := delete_request(text):
            await delete_posts(message, count)
            return
        if unmute_request(text):
            muted_until.pop(channel_id, None)
            quiet_until.pop(channel_id, None)
            log.info(f"Unmuted in {where} by {message.author.name}")
            await react(message, UNMUTED_EMOJI)
            return
        if melee_here_request(text):
            save_channel(MELEE_CHANNEL_FILE, channel_id)
            log.info(f"Melee posts go to {where} now, set by {message.author.name}")
            await react(message, MELEE_EMOJI)
            return
        if melee_stop_request(text):
            save_channel(MELEE_CHANNEL_FILE, None)
            log.info(f"No more Melee posts, by {message.author.name}")
            await react(message, NO_MELEE_EMOJI)
            return
        # The newest of a mute and quiet mode wins.
        for request, until, other, what, emoji in [(mute_request, muted_until, quiet_until, "Muted", MUTED_EMOJI),
                                                   (quiet_request, quiet_until, muted_until, "Quiet mode", QUIET_EMOJI)]:
            if (minutes := request(text, MUTE_MINUTES)) is not None:
                until[channel_id] = time.monotonic() + minutes * 60
                other.pop(channel_id, None)
                log.info(f"{what} in {where} " + ("until unmuted" if minutes == FOREVER else f"for {minutes:g} minutes")
                         + f", by {message.author.name}")
                await react(message, emoji)
                return

    history[channel_id].append(format_line(message.author.name, text))
    logged[channel_id] += 1
    last_author[channel_id] = (message.author.id, message.author.name)
    if message.guild:  # never DMs
        chat_log.add(channel_id, channel_label(message.channel), message.id, message.author.id, message.author.name, text,
                     reply_to=getattr(getattr(message, "reference", None), "message_id", None))

    await take_notes(message, text, mentioned)

    # Muted here: she keeps following the chat but says nothing and reacts to nothing, except a 🤐
    # for anyone talking to her.
    if muted(channel_id):
        if for_her:
            await react(message, HUSHED_EMOJI)
        return

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

    # Aimed at her: always answered. Anything else only if it interests her (chimes_in), and never in
    # quiet mode, not even sad news (the sad cat above still says she saw it).
    addressed = for_her or (sad_news(text) and not quiet(channel_id))
    if quiet(channel_id) and not addressed:
        return

    lock = reply_locks[channel_id]
    if lock.locked():
        # Already deciding or writing a reply here; everything that arrives meanwhile gets one follow-up.
        was_mentioned, was_addressed = pending_followup.get(channel_id, (False, False))
        pending_followup[channel_id] = (was_mentioned or mentioned, was_addressed or addressed)
        return

    async with lock:
        try:
            await converse(message.channel, channel_id, mentioned, addressed)
        finally:
            pending_followup.pop(channel_id, None)


async def converse(channel: discord.abc.Messageable, channel_id: int, mentioned: bool, addressed: bool) -> None:
    """Reply if she should, then once more for whatever arrived meanwhile. Holds the channel's lock."""
    while not muted(channel_id):
        if addressed or (not quiet(channel_id) and await chimes_in(channel_id)):
            # What arrived while she was deciding is already in the log, so this reply covers it.
            was_mentioned, _ = pending_followup.pop(channel_id, (False, False))
            await reply_to(channel, channel_id, mentioned or was_mentioned)
        if channel_id not in pending_followup:
            break
        mentioned, addressed = pending_followup.pop(channel_id)


def melee_player() -> str:
    """Who she played: MELEE_PLAYER, else the owner by nickname or display name."""
    if MELEE_PLAYER:
        return MELEE_PLAYER
    if app_owner:
        user_id, handle = app_owner
        return memory.nickname_for(user_id) or display_names.get(user_id) or handle
    return "the owner"


async def match_post(channel_id: int, event: dict, taunts: list[str] = (), temperature: float | None = None) -> str | None:
    """Her message about a Melee match (melee.py), or None if the model didn't answer."""
    options = {} if model_thinks else {"num_predict": max(MAX_REPLY_TOKENS, 300)}  # 2-4 sentences
    if temperature is not None:
        options["temperature"] = temperature
    player = melee_player()
    facts = match_facts(event, player, taunts)
    payload = {"messages": build_match_messages(list(history[channel_id]), facts, player, shown_examples(),
                                                diary.vibe()),
               "options": options}
    start = time.monotonic()
    data = await ollama_chat(payload)
    return clean_reply(data, None, start) if data else None


async def post_matches(outbox: Path) -> bool:
    """Post about every match waiting in AI-Melee's outbox, oldest first. She only talks once a match
    is over: her in-match taunts aren't posted, they're taken out of the outbox and held (melee_taunts)
    for her post about their match. A match stays in the outbox if the model doesn't answer, to be tried
    again later (until it's too old). True if that's why it stopped."""
    max_age = MELEE_MAX_AGE_MINUTES * 60
    events = read_outbox(outbox, log)
    for path, event in events:
        if event.get("kind") == "taunt":
            path.unlink(missing_ok=True)  # out of the outbox now: AI-Melee only keeps its newest 20 files
            text = str(event["text"]).strip()
            if text and not has_slur(text) and not stale(event, max_age):
                melee_taunts.append((float(event.get("time", 0)), text))
    # Taunts from a match that never finished
    melee_taunts[:] = [(said, text) for said, text in melee_taunts if not stale({"time": said}, max_age)]

    channel_id = melee_channel()
    for path, event in events:
        if event.get("kind") == "taunt":
            continue
        ended = float(event.get("time", 0))
        taunts = [text for said, text in melee_taunts if ended - TAUNT_WINDOW_SECONDS <= said <= ended]
        if stale(event, max_age):
            log.info(f"Melee match {path.name} is too old to post; dropping it")
            path.unlink(missing_ok=True)
            forget_taunts(ended)
            continue
        if not channel_id:
            return False  # no channel yet: matches wait (watch_melee said how to pick one)
        channel = client.get_channel(channel_id)
        if channel is None:
            try:
                channel = await client.fetch_channel(channel_id)
            except discord.HTTPException as e:
                log.error(f"Can't reach the Melee channel {channel_id} ({e}); her Melee posts wait")
                return False
        channel_id = channel.id
        if muted(channel_id):
            log.info(f"Muted in the Melee channel; not posting {path.name}")
            path.unlink(missing_ok=True)
            forget_taunts(ended)
            continue
        async with reply_locks[channel_id]:
            try:
                async with channel.typing():
                    post = await match_post(channel_id, event, taunts)
                    if post and repeats_itself(channel_id, post):
                        post = await match_post(channel_id, event, taunts, temperature=RETRY_TEMPERATURE) or post
                if post:
                    path.unlink(missing_ok=True)
                    forget_taunts(ended)
                    if muted(channel_id):
                        log.info("Muted while writing a Melee post; not sending it")
                    else:
                        log.info(f"Posting about Melee match {path.name}"
                                 + (f" ({len(taunts)} of her in-match lines to draw on)" if taunts else ""))
                        await send_reply(channel, channel_id, post, about="melee")
                # Anything said while she was writing gets its usual answer now.
                if channel_id in pending_followup:
                    mentioned, addressed = pending_followup.pop(channel_id)
                    await converse(channel, channel_id, mentioned, addressed)
            finally:
                pending_followup.pop(channel_id, None)
        if not post:
            return True  # the model didn't answer: try again later
    return False


def forget_taunts(ended: float) -> None:
    """Drop the held taunts from a match that ended at `ended` (and any older ones)."""
    melee_taunts[:] = [(said, text) for said, text in melee_taunts if said > ended]


def melee_channel() -> int | None:
    """Where her Melee posts go: the channel an owner picked (or none, after "stop posting melee"),
    else MELEE_CHANNEL_ID."""
    if MELEE_CHANNEL_FILE.exists():
        return load_channel(MELEE_CHANNEL_FILE)
    return MELEE_CHANNEL_ID or None


async def watch_melee() -> None:
    outbox = MELEE_OUTBOX
    if channel_id := melee_channel():
        channel = client.get_channel(channel_id)
        where = f"#{channel.name}" if getattr(channel, "name", None) else f"channel {channel_id}"
        log.info(f"Melee results: posting from {outbox} in {where}")
    else:
        log.info(f"Melee results: watching {outbox}, but no channel yet. Say 'gomi post melee here' in the "
                 "channel you want (as the bot's owner)")
    while True:
        stalled = False
        try:
            if outbox.is_dir():
                stalled = await post_matches(outbox)
        except Exception:
            log.exception("Posting Melee results failed; trying again")
            stalled = True
        # Ollama down or a bad file: wait a minute rather than fail every 5 seconds.
        await asyncio.sleep(MELEE_RETRY_SECONDS if stalled else MELEE_CHECK_SECONDS)


melee_watcher = None
# (time.time() she said it, text) of her in-match taunts, held until their match is over (post_matches)
melee_taunts = []


def channel_label(channel) -> str:
    return f"#{channel.name}" if getattr(channel, "name", None) else f"channel {channel.id}"


async def write_diary(why: str, before: float | None = None) -> None:
    """Read each channel's chat log since her last diary entry (up to `before`) and write it up:
    a recap per part and checked notes on people (diary.py). A part stays unread if the model doesn't
    answer, for the next time; an answer that isn't the JSON asked for is skipped with a warning."""
    async with diary_lock:
        before = time.time() if before is None else before
        said = []  # what people said, for the vibe note
        for channel_id in sorted(chat_log.channels()):
            since = diary.read_up_to(channel_id)
            entries = chat_log.read(channel_id, after=since, before=before)
            if not entries:
                continue
            keep_landed(chat_log.read(channel_id, after=since, before=before, reactions=True))
            said += [e for e in entries if e["author"] != BOT_NAME]
            parts = chunks(entries, DIARY_PART_CHARS)
            where = entries[-1].get("channel") or f"channel {channel_id}"
            log.info(f"Writing her diary ({why}): {where}, {len(entries)} messages"
                     + (f" in {len(parts)} parts" if len(parts) > 1 else ""))
            for part in parts:
                if not await diary_entry(channel_id, part):
                    log.warning("Couldn't write her diary (is Ollama running?); she'll catch up next time")
                    return
        if len(said) >= VIBE_MIN_MESSAGES:
            await update_vibe(sorted(said, key=lambda e: e["time"]))


def keep_landed(entries: list[dict]) -> None:
    """Keep her replies in this stretch of log that landed (meld.py) as examples, once each."""
    known = {example.get("id") for example in earned}
    new = [example | {"day": local_day(example["time"]), "channel": entries[0].get("channel")}
           for example in landed_replies(entries) if example["id"] not in known]
    if not new:
        return
    with EARNED_FILE.open("a", encoding="utf-8") as f:
        f.writelines(json.dumps(example, ensure_ascii=False) + "\n" for example in new)
    earned.extend(new)
    log.info(f"{len(new)} of her replies landed and join her examples ({len(earned)} earned so far): "
             + " | ".join(f"{e['reply'][:60]!r} ({e['signal']})" for e in new))


async def update_vibe(said: list[dict]) -> None:
    """Update her note on how the server talks from what people said since the last one (meld.py)."""
    lines, size = [], 0
    for e in reversed(said):  # the newest VIBE_CHARS of it: that's what's new
        line = format_line(e["author"], e["text"])
        size += len(line) + 1
        if lines and size > VIBE_CHARS:
            break
        lines.append(line)
    lines.reverse()
    data = await ollama_chat({"messages": vibe_messages(diary.vibe(), lines), "format": VIBE_FORMAT,
                              "options": {"temperature": 0.3} | ({} if model_thinks else {"num_predict": 400})})
    if data is None:
        log.warning("Couldn't update her note on how the server talks; next time")
        return
    notes = parse_vibe(data.get("message", {}).get("content", ""))
    if notes is None:
        log.warning(f"Her note on how the server talks came back unusable; kept the old one. Raw: {json.dumps(data)[:300]}")
        return
    diary.set_vibe(notes, local_day(said[-1]["time"]))
    log.info("How the server talks, as she sees it now: " + " | ".join(notes))


async def diary_entry(channel_id: int, part: list[dict]) -> bool:
    """One diary call for part of a channel's log; False if the model didn't answer."""
    ids = {entry["author"]: entry.get("author_id") for entry in part if entry["author"] != BOT_NAME}
    day, where = local_day(part[0]["time"]), part[-1].get("channel") or f"channel {channel_id}"
    if sum(entry["author"] != BOT_NAME for entry in part) >= 2:
        options = {"temperature": 0.3} | ({} if model_thinks else {"num_predict": 700})
        data = await ollama_chat({"messages": digest_messages(where, day, [format_line(e["author"], e["text"])
                                                                         for e in part]),
                                  "format": digest_format(sorted(ids)), "options": options})
        if data is None:
            return False
        digest = parse_digest(data.get("message", {}).get("content", ""), sorted(ids), [e["text"] for e in part])
        if digest is None:
            log.warning(f"Her diary for {where} came back unreadable; skipping that part. "
                        f"Raw: {json.dumps(data)[:300]}")
        else:
            recap, notes = digest
            if recap:
                diary.add_recap(channel_id, where, day, recap)
            new = [f"{who}: {note}" for who, note in notes
                   if ids.get(who) and memory.learn(ids[who], display_names.get(ids[who]), note, day)]
            log.info(f"Diary for {where}, {day}: {recap or '(no recap)'}"
                     + (f" | Noted: {'; '.join(new)}" if new else ""))
    diary.mark_read(channel_id, part[-1]["time"])
    return True


async def go_to_bed(message: discord.Message) -> None:
    """An owner's "gomi goodnight": she says goodnight, and the bot shuts down (main() then writes her
    diary)."""
    channel_id = message.channel.id
    log.info(f"{message.author.name} put her to bed: saying goodnight, then writing her diary and shutting down")
    await react(message, GOODNIGHT_EMOJI)
    if not muted(channel_id):
        owner = memory.nickname_for(message.author.id) or message.author.display_name
        start = time.monotonic()
        data = await ollama_chat({"messages": build_goodnight_messages(list(history[channel_id]), owner, diary.vibe()),
                                  "options": {} if model_thinks else {"num_predict": MAX_REPLY_TOKENS}})
        if data and (line := clean_reply(data, message.author.id, start)):
            await send_reply(message.channel, channel_id, line, about="goodnight")
    await client.close()


def reload_history() -> None:
    """Pick the chat back up after a restart: each channel's last HISTORY_LENGTH messages from the log,
    if newer than HISTORY_RELOAD_HOURS, and who's who for pings."""
    since = time.time() - HISTORY_RELOAD_HOURS * 3600
    for channel_id in chat_log.channels():
        entries = chat_log.read(channel_id, after=since)[-HISTORY_LENGTH:]
        for entry in entries:
            history[channel_id].append(format_line(entry["author"], entry["text"]))
            if entry["author"] != BOT_NAME and entry.get("author_id"):
                handles.setdefault(entry["author"].lower(), entry["author_id"])
        if entries:
            log.info(f"Picked up {len(entries)} messages of chat in {entries[-1].get('channel') or channel_id}")


async def main() -> None:
    reload_history()
    # Ctrl+C (asyncio cancels this task), a stop (SIGTERM) or a closed terminal (SIGHUP): write her diary
    # first. A second Ctrl+C skips it; the next start catches up.
    task = asyncio.current_task()
    for sig in (signal.SIGTERM, signal.SIGHUP):
        try:
            asyncio.get_running_loop().add_signal_handler(sig, task.cancel)
        except (NotImplementedError, AttributeError, ValueError):
            pass  # not on this platform
    try:
        async with client:
            await client.start(DISCORD_TOKEN)
    except asyncio.CancelledError:
        if hasattr(task, "uncancel"):  # Python 3.11+: this cancel is handled, so later awaits run normally
            task.uncancel()
    finally:
        if melee_watcher:
            melee_watcher.cancel()  # Discord's gone: nothing to post to
        log.info("Shutting down: writing her diary first (Ctrl+C again to skip it)")
        try:
            await write_diary("shutting down")
            log.info("Diary written. Goodnight.")
        except asyncio.CancelledError:
            log.info("Skipped her diary; she'll catch up at the next start")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
