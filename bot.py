"""
Gomihyu — a Discord conversationalist backed by a small local model (via Ollama).

Behavior:
  - Always replies when @mentioned, replied to, or named ("gomi"), and to sad news.
  - Any other post, she reads the room first (chime.py): one short model call rates how much she'd
    want to say something (replies at CHIME_IN_THRESHOLD) and how much it gets a rise out of her
    (an emoji reaction at REACT_THRESHOLD). Posts that don't need words (pictures, emoji-only,
    "lol") only ever get the reaction (reactions.py, emojis.py).
  - Sees pictures (vision.py), knows her own avatar, and posts about her Melee sessions (melee.py).
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
import contextlib
import logging
import signal
from collections import defaultdict, deque
from datetime import datetime
from pathlib import Path

import aiohttp
import discord
from dotenv import load_dotenv

from censor import has_slur
from chatlog import ChatLog, local_day, raw_author_text
from chime import Reading, parse_room, room_format, room_messages
from commands import (ALL, FOREVER, delete_request, gg_request, goodnight_request, melee_here_request, melee_stop_request,
                      mute_request, quiet_request, unmute_request)
from diary import Diary, chunks, diary_posts, digest_format, digest_messages, parse_digest, render_line
from meld import VIBE_FORMAT, landed_replies, parse_vibe, pick_examples, vibe_messages
from emojis import CUSTOM, LOOKING, SAD_NEWS, SLUR_STANDIN, UNICODE
from melee import (TAUNT_WINDOW_SECONDS, default_outbox, load_channel, read_outbox, save_channel, session_facts,
                   session_ready, stale)
from memory import PeopleMemory, aimed_at_her, fact_to_remember, nicknames_in
from persona import (BOT_NAME, BOT_NICKNAME, build_goodnight_messages, build_messages, build_session_messages, format_line,
                     made_up_names, example_targets)
from reactions import media_only, names_her, posted_emoji, reacts_instead, sad_news
from shape import (LINE_SENTENCES, MAX_SENTENCES, SENTENCE_END, WHOLE, at_most, one_emoji, sentences_for, this_time,
                   whole)
import vision
from vision import clean_description, describe_messages, embed_label, jpeg_b64, label, sources

load_dotenv()

DISCORD_TOKEN = os.environ["DISCORD_BOT_TOKEN"]
OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://localhost:11434/api/chat")
MODEL_NAME = os.environ.get("OLLAMA_MODEL", "gemma4:e4b")
# Posts not aimed at her are read (chime.py): what's going on, 0-10 for how much she'd want to chime in,
# and a fitting reaction. She replies at CHIME_IN_THRESHOLD or above (higher is quieter; 0 answers
# everything without reading). With REACT_TO_CHAT, a post she doesn't answer can still get the reaction.
CHIME_IN_THRESHOLD = int(os.environ.get("CHIME_IN_THRESHOLD", "6"))
REACT_TO_CHAT = os.environ.get("REACT_TO_CHAT", "true").strip().lower() in ("1", "true", "yes", "on")
# She only reacts to what gets a rise out of her: the read's react score (0-10, its own scale, not the
# chime-in one) at this or above. Higher is fewer reactions; 0 reacts whenever a reaction fits.
REACT_THRESHOLD = int(os.environ.get("REACT_THRESHOLD", "8"))
# A post she chimes in on gets that reaction as well as her reply (a 10/10 moment deserves both).
REACT_WHEN_REPLYING = os.environ.get("REACT_WHEN_REPLYING", "true").strip().lower() in ("1", "true", "yes", "on")
# Posts of at most this many words (no "?", not aimed at her) get a reaction instead of a reply.
REACT_ONLY_MAX_WORDS = int(os.environ.get("REACT_ONLY_MAX_WORDS", "2"))
# A post she answers of at most this many words, not a question (a jab, "gomi hi"), gets one short line
# back; anything else 1 to 3 sentences (shape.py).
ONE_LINE_MAX_WORDS = int(os.environ.get("ONE_LINE_MAX_WORDS", "6"))
HISTORY_LENGTH = int(os.environ.get("HISTORY_LENGTH", "12"))  # recent messages kept per channel for context
# A reply that copies REPEAT_WORDS words in a row from one of the bot's recent messages is
# regenerated once at RETRY_TEMPERATURE (small models love copying their own earlier lines).
REPEAT_WORDS = int(os.environ.get("REPEAT_WORDS", "5"))
RETRY_TEMPERATURE = float(os.environ.get("RETRY_TEMPERATURE", "1.0"))
# Ceiling on a reply's length; one that hits it is cut back to its last full sentence and posted. One that
# asks for room (a build, a list, steps: shape.py) gets at least ROOM_REPLY_TOKENS.
MAX_REPLY_TOKENS = int(os.environ.get("MAX_REPLY_TOKENS", "200"))
ROOM_REPLY_TOKENS = 400  # 6 sentences or a short list: ~1,600 characters, under Discord's 2000
# Context window, in tokens, for every call. Ollama's default of 4096 can be outgrown by the prompt
# (system prompt, example chats, 12 messages of chat) when people post long messages, and Ollama then
# silently cuts the prompt. Every call sends the same value, or Ollama reloads the model between them.
OLLAMA_NUM_CTX = int(os.environ.get("OLLAMA_NUM_CTX", "8192"))
# Let her think before she writes: her answers, Melee posts and goodnight, never a chime-in (reply_to),
# reading the room, her diary or pictures. Off by default: it adds seconds to every reply. On, her
# replies aren't capped at MAX_REPLY_TOKENS (the thinking counts against it), but shape.py still holds
# them to their size. The console shows the start of each thought.
OLLAMA_THINK = os.environ.get("OLLAMA_THINK", "false").strip().lower() in ("1", "true", "yes", "on")
# Whether the model thinks even when told not to (some do), seen in a response. Nothing is capped then.
model_thinks = False
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
# Post each new recap in the channel it's about, the next time she's online (diary.py, post_diary).
POST_DIARY = os.environ.get("POST_DIARY", "true").strip().lower() in ("1", "true", "yes", "on")
# Melding (meld.py): the server slowly shapes her. Each night her replies that landed are kept in
# EARNED_FILE as her example chats (with SEED_EXAMPLES, replacing Satania ones as they pile up: MELD_FULL_AT
# earned, all the way down to MELD_ANCHOR, the share of Satania examples that always stays); and, with at
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
# Example chats in her prompt, to set her voice until a fine-tuned model carries it: FEW_SHOT_EXAMPLES of
# her own replies that landed (meld.py), a fresh random pick each reply; 0 turns them off. SEED_EXAMPLES
# mixes in the made-up Satania chats (the fine-tuning seed) as before, with her landed replies taking over
# bit by bit. Off by default (user, 2026-10-04: melon bread out of nowhere; her defiance is in the system
# prompt): the seed only trains her now.
FEW_SHOT_EXAMPLES = int(os.environ.get("FEW_SHOT_EXAMPLES", "8"))
SEED_EXAMPLES = os.environ.get("SEED_EXAMPLES", "false").strip().lower() in ("1", "true", "yes", "on")
SEED_FILE = Path(__file__).resolve().parent / "finetuning" / "gomihyu_seed.jsonl"
# Melee results (melee.py): the outbox folder AI-Melee leaves her taunts and matches in (by default the
# one both programs know, ~/.local/share/gomihyu/melee-outbox), and the channel she posts them in: the
# one an owner picked with "gomi post melee here" (kept in MELEE_CHANNEL_FILE), else MELEE_CHANNEL_ID.
# She posts once per session: when AI-Melee says the game closed, when the owner says "gg", or once no
# match has come for MELEE_SESSION_IDLE_MINUTES (the game was force-quit). A session whose newest match
# is older than MELEE_MAX_AGE_MINUTES (played while the bot was off) is dropped unposted.
MELEE_OUTBOX = Path(os.environ.get("MELEE_OUTBOX", "").strip() or default_outbox()).expanduser()
MELEE_CHANNEL_FILE = Path(__file__).resolve().parent / "melee_channel.json"
MELEE_CHANNEL_ID = int(os.environ.get("MELEE_CHANNEL_ID", "0").strip() or "0")
MELEE_EMOJI = "🎮"  # reaction confirming this channel gets her Melee posts
NO_MELEE_EMOJI = "🔕"
MELEE_MAX_AGE_MINUTES = float(os.environ.get("MELEE_MAX_AGE_MINUTES", "120"))
MELEE_SESSION_IDLE_MINUTES = float(os.environ.get("MELEE_SESSION_IDLE_MINUTES", "20"))
# Who played against her; default: the bot owner's nickname, else their display name.
MELEE_PLAYER = os.environ.get("MELEE_PLAYER", "").strip()
MELEE_CHECK_SECONDS = 5
# Vision (vision.py): each picture, sticker, GIF or link preview in a post is described once by
# VISION_MODEL (her own model unless set) and the description stands in for it in her chat log. At most
# VISION_MAX_IMAGES per post. VISION=false: she's text-only again, with a looking emoji for pictures.
VISION = os.environ.get("VISION", "true").strip().lower() in ("1", "true", "yes", "on")
VISION_MODEL = os.environ.get("VISION_MODEL", "").strip() or MODEL_NAME
# Her jobs that aren't her voice: reading the room, her diary and the vibe note (her own model unless
# set). Once a fine-tune serves her voice (finetuning/weekly.py), these can stay on the stock model.
TASK_MODEL = os.environ.get("TASK_MODEL", "").strip() or MODEL_NAME
# What her Discord avatar looks like, for her prompts. Unset: VISION_MODEL describes it at login.
AVATAR_DESCRIPTION = os.environ.get("AVATAR_DESCRIPTION", "").strip()
VISION_MAX_IMAGES = int(os.environ.get("VISION_MAX_IMAGES", "3"))
VISION_MAX_BYTES = 10 * 1024 * 1024
EMBED_WAIT_SECONDS = 2.5  # Discord adds a link's preview a moment after the post
MELEE_RETRY_SECONDS = 60  # after a session she couldn't post

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("gomihyu")
if VISION and vision.Image is None:
    log.warning("Pillow isn't installed, so she can't look at pictures. Run: venv/bin/pip install -r requirements.txt")
    VISION = False

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
# channel_id -> (whether anything that arrived mid-reply was for her: an @mention, a reply to her, her
# name; whether anything must be answered: that, or sad news); present = one follow-up owed
pending_followup = {}
# Required replies keep their actual speaker/text through a burst; a boolean can't identify who asked.
unanswered = defaultdict(list)
# A newer turn must wait for descriptions already in progress before consuming picture questions.
pending_vision = defaultdict(set)
# lowercase Discord handle or display name -> user id, for real pings and for "Yuzuki's nickname is..."
handles = {}
# user id -> display name, for everyone seen
display_names = {}
# channel_id -> (user id, handle) of the latest message, whose remembered facts a reply gets
last_author = {}
# channel_id -> the latest observed line and its source, even after history eviction or her own reply
latest_post = {}
# channel_id -> the emojis she picked for her last reactions there, so she doesn't repeat them
recent_reactions = defaultdict(lambda: deque(maxlen=2))
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


def seed_chats(path: Path) -> list[dict]:
    """The fine-tuning seed's made-up chats."""
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()] if path.exists() else []


def load_examples(path: Path) -> list[dict]:
    """The seed chats for her prompt, if SEED_EXAMPLES."""
    if FEW_SHOT_EXAMPLES <= 0 or not SEED_EXAMPLES:
        return []
    if not path.exists():
        log.warning(f"No example chats at {path}; replying without them")
        return []
    return seed_chats(path)


examples = load_examples(SEED_FILE)


def made_up_pattern(chats: list[dict]) -> re.Pattern | None:
    """Finds the people from the made-up example chats in a reply: handles in any case, nicknames only as
    written ("Nori", not nori seaweed). None of them is in the server (she once said "go bother @kaz0")."""
    handles_there = {name for chat in chats for name, _ in chat["history"]}
    names = [f"(?i:{re.escape(name)})" if name in handles_there else re.escape(name) for name in made_up_names(chats)]
    return re.compile(r"(?<![\w.])@?(" + "|".join(names) + r")(?!\w)") if names else None


# from the seed itself, in her prompt or not: it trains her, so a fine-tune knows those names too
MADE_UP = made_up_pattern(seed_chats(SEED_FILE))


def load_earned(path: Path) -> list[dict]:
    """Load earned rows only when raw addressing, source targets and reply shape remain representable.
    Saved files stay intact; legacy or clipped examples cannot silently acquire a different target."""
    earned = []
    for line in path.read_text(encoding="utf-8").splitlines() if path.exists() else []:
        try:
            example = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(example, dict):
            example = example | {"real": True}
            if example_targets(example) is not None:
                earned.append(example)
    return earned


earned = load_earned(EARNED_FILE)


def shown_examples() -> list[dict]:
    """This reply's example chats: her own that landed, and Satania ones if SEED_EXAMPLES."""
    return pick_examples(examples, earned, FEW_SHOT_EXAMPLES, MELD_ANCHOR, MELD_FULL_AT)

URL = re.compile(r"https?://\S+")
MENTION_TOKEN = re.compile(r"<(@!?|@&|#)(\d+)>")
CUSTOM_EMOJI_TOKEN = re.compile(r"<a?:(\w+):\d+>")
CUSTOM_EMOJI_NAME = re.compile(r":(\w+):")
# Custom emojis she may post: the in-text ones, plus the stand-in she posts instead of a slur.
POSTABLE_EMOJIS = {name.lower() for name, (_, in_text) in CUSTOM.items() if in_text} | {SLUR_STANDIN.lower()}
HANDLE = re.compile(r"@([\w.]*\w)")
OWN_NAME_PREFIX = re.compile(rf"^\s*[*_]*(?:{BOT_NAME}|{BOT_NICKNAME})[*_]*\s*:[*_]*\s*", re.IGNORECASE)


def readable(message: discord.Message, seen: dict | None = None, include_media: bool = True) -> str:
    """message.content as the model sees it: <@id>/<@&id>/<#id> as @handle/@role/#channel,
    custom emojis as :name:, attachments/stickers as [image]/[gif]/[video]/[file]/[sticker: name] and
    link previews as [link: "title"]. seen: what she saw in its pictures (look_at), by (kind, index),
    which goes in the brackets: [image: a cat in a tiny wizard hat]."""
    seen = seen or {}
    names = {user.id: f"@{user.name}" for user in message.mentions}
    names.update({role.id: f"@{role.name}" for role in message.role_mentions})
    names.update({channel.id: f"#{channel.name}" for channel in message.channel_mentions})
    text = MENTION_TOKEN.sub(lambda m: names.get(int(m[2]), m[0]), message.content)
    text = CUSTOM_EMOJI_TOKEN.sub(r":\1:", text)
    if not include_media:
        return text.strip()
    media = []
    for i, attachment in enumerate(message.attachments):
        content_type = (attachment.content_type or "").split(";")[0].lower()
        kind = "gif" if content_type == "image/gif" else content_type.split("/")[0]
        media.append(label(kind if kind in ("image", "gif", "video") else "file", seen.get(("attachment", i))))
    media += [label("sticker", seen.get(("sticker", i)), sticker.name) for i, sticker in enumerate(message.stickers)]
    media += [embed_label(embed, seen.get(("embed", i))) for i, embed in enumerate(getattr(message, "embeds", []))]
    return " ".join([text, *(m for m in media if m)]).strip()


def conversation_text(message: discord.Message, text: str) -> str:
    """Keep Discord's reply link visible, even when the quoted post has left recent history."""
    reference = getattr(message, "reference", None)
    if reference is None:
        return text
    replied = getattr(reference, "resolved", None)
    author = getattr(replied, "author", None)
    if author is None:
        return f"[reply to an unavailable earlier message] {text}"
    # No fetch or vision call for old posts; a bounded quote, with explicit missing-content fallback.
    quote = readable(replied) if hasattr(replied, "content") else ""
    quote = " ".join(quote.split())
    if len(quote) > 300:
        quote = quote[:300] + "…"
    return f"[reply to {author.name}: {json.dumps(quote or '(content unavailable)', ensure_ascii=False)}] {text}"


class ObservedLine(str):
    """A display line with its Discord source; equal captions are still distinct observations."""
    def __new__(cls, message: discord.Message, text: str):
        author = message.author.name + (" (bot)" if message.author.bot else "")
        line = super().__new__(cls, format_line(author, conversation_text(message, text)))
        line.message = message
        return line


def observe(message: discord.Message, text: str) -> ObservedLine:
    """Record a participant in arrival order; observing another bot never triggers a reply."""
    channel_id = message.channel.id
    line = ObservedLine(message, text)
    history[channel_id].append(line)
    logged[channel_id] += 1
    last_author[channel_id] = (message.author.id, message.author.name + (" (bot)" if message.author.bot else ""))
    latest_post[channel_id] = line
    return line


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


def strangers(channel_id: int, reply: str) -> list[str]:
    """Names in reply that aren't anyone here, as written: people from the made-up example chats ("kaz0"),
    and @handles nobody has ("@bob"). Anyone known (person) is real, whatever the example chats say, and a
    name someone else used in this channel's log is fair game ("who's kaz0?" can still be answered)."""
    own = format_line(BOT_NAME, "")
    log_text = "\n".join(line for line in history[channel_id] if not line.startswith(own))
    found = [m[1] for m in MADE_UP.finditer(reply)] if MADE_UP else []
    found += [m[0] for m in HANDLE.finditer(reply) if m[1].lower() not in {name.lower() for name in found}]

    def real(name: str) -> bool:
        return (name.lower() in (BOT_NAME.lower(), BOT_NICKNAME.lower()) or person(name) is not None
                or re.search(rf"(?<![\w.])@?{re.escape(name)}(?!\w)", log_text, re.IGNORECASE) is not None)
    return [name for name in dict.fromkeys(found) if not real(name.lstrip("@"))]


def without_names(text: str, names: list[str]) -> str:
    """text minus every sentence that mentions one of names (strangers'), a bare one with or without an @."""
    named = re.compile(r"(?<![\w.])(?:" + "|".join(re.escape(name) if name.startswith("@") else f"@?{re.escape(name)}"
                                                   for name in names) + r")(?!\w)")
    cuts = [0, *(m.end() for m in SENTENCE_END.finditer(text)), len(text)]
    return "".join(part for a, b in zip(cuts, cuts[1:]) if not named.search(part := text[a:b])).strip()


def local_now() -> datetime:
    """The date and time where the bot runs, for her prompt."""
    return datetime.now()


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
    runs = word_runs(reply)
    return (any(runs & word_runs(line) for line in own_lines(channel_id))
            or any(runs & word_runs(example["reply"]) for example in examples + earned))


def cap(tokens: int, thinking: bool = False) -> dict:
    """A call's num_predict, unless its answer comes after thinking, which would count against it."""
    return {} if thinking or model_thinks else {"num_predict": tokens}


async def ollama_chat(payload: dict) -> dict | None:
    """One non-streaming call to Ollama's chat API: the response, or None with the reason logged. The model
    only thinks if the payload says "think": True."""
    global model_thinks
    start = time.monotonic()
    thinking = payload.get("think", False)
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(OLLAMA_URL, json={"model": MODEL_NAME, "stream": False, "think": False, **payload,
                                                      "options": {"num_ctx": OLLAMA_NUM_CTX} | payload.get("options", {})},
                                    timeout=aiohttp.ClientTimeout(total=120 if thinking else 60)) as resp:
                if resp.status != 200:
                    # Ollama explains itself in the body (e.g. "model ... not found, try pulling it first").
                    log.error(f"Ollama returned HTTP {resp.status} for model {payload.get('model', MODEL_NAME)!r}: "
                              f"{(await resp.text())[:500]}")
                    return None
                data = await resp.json()
    except Exception:
        log.exception(f"Generation failed after {time.monotonic() - start:.1f}s (Ollama at {OLLAMA_URL})")
        return None
    if (not isinstance(data, dict) or not isinstance(data.get("message"), dict)
            or not isinstance(data["message"].get("content", ""), str)
            or data["message"].get("thinking") is not None and not isinstance(data["message"]["thinking"], str)):
        log.warning("Ollama returned an unusable message; generation failed")
        return None
    thought = data["message"].get("thinking")
    if thought and thinking:
        thought = " ".join(thought.split())
        log.info(f"She thought ({len(thought.split())} words, {time.monotonic() - start:.1f}s for all): "
                 f"{thought[:600]!r}" + ("..." if len(thought) > 600 else ""))
    elif thought and not model_thinks:
        model_thinks = True
        log.warning(f"{payload.get('model', MODEL_NAME)} thinks before answering even when told not to, so "
                    f"answers take longer. They're no longer capped (MAX_REPLY_TOKENS, {MAX_REPLY_TOKENS}), since "
                    "the thinking counts against the cap.")
    return data


def prepare_reply(channel_id: int, for_her: bool, requests: list[tuple] = ()) -> tuple:
    """Freeze the prompt and addressee once, so retries answer the same conversation snapshot."""
    # The latest observed speaker gets their notes; pending speakers get separately labeled notes.
    author_id, author_handle = last_author[channel_id]
    addressed = [line for _, line, _ in requests]
    pending_raw = [readable(post, include_media=False) for _, _, post in requests]
    # Everyone in the log gets their nickname, though, so she can call them by it.
    speakers = dict.fromkeys(line.split(": ", 1)[0] for line in [*history[channel_id], *addressed])
    nicknames = {handle: nick for handle in speakers
                 if (user_id := handles.get(handle.lower())) and (nick := memory.nickname_for(user_id))}
    # How long, whether to ask back, whether an emoji fits: decided here, not left to the model (shape.py).
    newest = history[channel_id][-1].split(": ", 1)[-1] if history[channel_id] else ""
    latest = latest_post.get(channel_id)
    if latest is not None:
        post = latest.message
        author_id = post.author.id
        author_handle = post.author.name + (" (bot)" if post.author.bot else "")
        newest = readable(post, include_media=False)
        # An earlier mention in a burst doesn't make the newest speaker's 'you' mean Gomi.
        for_her = not post.author.bot and (client.user in post.mentions or replying_to_her(post) or names_her(newest))
    shape = this_time(newest, own_lines(channel_id), ONE_LINE_MAX_WORDS, pending_raw)
    addressed_notes = {}
    for _, _, post in requests:
        handle, user_id = post.author.name, post.author.id
        if nick := memory.nickname_for(user_id):
            nicknames[handle] = nick
        else:
            nicknames.pop(handle, None)
        if user_id != author_id and handle not in addressed_notes:
            notes = [f'Asked you to remember: "{fact}"' for fact in memory.facts_for(user_id)]
            notes += [f"Past observation (may be out of date): {note}" for note in memory.learned_for(user_id)]
            if notes:
                addressed_notes[handle] = notes
    messages = build_messages(list(history[channel_id]), for_her,
                              author_handle, memory.facts_for(author_id), nicknames, shown_examples(),
                              memory.learned_for(author_id), diary.recaps_for(channel_id, RECAP_DAYS),
                              diary.vibe(), avatar_description, **shape, now=local_now(), addressed=addressed,
                              addressed_notes=addressed_notes, newest=str(latest) if latest is not None else None)
    return messages, requests[-1][2].author.id if requests else author_id, shape


async def generate_reply(channel_id: int, for_her: bool, temperature: float | None = None,
                         prepared: tuple | None = None, think: bool = True) -> str | None:
    """think=False: this reply doesn't think, even with OLLAMA_THINK on (a chime-in, reply_to)."""
    messages, author_id, shape = prepared if prepared is not None else prepare_reply(channel_id, for_her)
    tokens = max(MAX_REPLY_TOKENS, ROOM_REPLY_TOKENS) if shape["room"] else MAX_REPLY_TOKENS
    thinking = OLLAMA_THINK and think
    options = cap(tokens, thinking)
    if temperature is not None:
        options["temperature"] = temperature  # otherwise the model's own (Modelfile) setting
    payload = {"messages": messages,
               "options": options, "think": thinking}

    start = time.monotonic()
    data = await ollama_chat(payload)
    said = data.get("message", {}) if data else {}
    if (data and "num_predict" in options and data.get("done_reason") == "length"
            and (said.get("thinking") or not WHOLE.search(said.get("content", "")))):
        # The cap stopped her before the answer was done: thinking used it up (the first reply from a model
        # that turns out to think), or not one whole sentence was written ("The answer is forty" of "forty-two").
        # Let it finish rather than go quiet or send half a sentence.
        log.warning(f"The {tokens}-token cap stopped the answer before it was done; retrying without it")
        del options["num_predict"]
        data = await ollama_chat(payload)
    if data is None:
        return None
    return clean_reply(data, author_id, start, sentences_for(shape), shape["emoji"])


def own_lines(channel_id: int) -> list[str]:
    """What she said in this channel's recent chat, oldest first."""
    own = format_line(BOT_NAME, "")
    return [line[len(own):] for line in history[channel_id] if line.startswith(own)]


def clean_reply(data: dict, author_id: int | None, start: float, sentences: int = MAX_SENTENCES,
                emoji: bool = True) -> str:
    """The model's answer as she'll post it; author_id is the person she's answering, if anyone. At most
    `sentences` sentences and one emoji (none unless emoji), whatever the model wrote (shape.py): one that
    ran long is cut, never dropped."""
    # Small models often start with "Gomihyu:" anyway, copying the log format.
    reply = OWN_NAME_PREFIX.sub("", strip_thinking(data.get("message", {}).get("content", "")).strip())
    if data.get("done_reason") == "length":
        reply = whole(reply)  # ran into the token cap: drop the half-finished sentence or list item
    if author_id is not None:
        reply = without_ping(reply, author_id)
    if (shaped := at_most(one_emoji(reply, emoji), sentences)) != reply:
        log.info(f"Trimmed to {sentences} sentences and {'one emoji' if emoji else 'no emojis'} at most, from: "
                 f"{reply[:300]!r}")
        reply = shaped
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
                     about: str = "reply", replying_to: discord.Message | None = None,
                     answered_requests: list[int] = ()) -> bool:
    """Post reply and keep it in her chat log. seen: how many messages had been logged when she started
    writing it, so it goes in right after those, ahead of any that arrived meanwhile. about: what kind
    of post (reply, filtered, melee, goodnight); only replies can become examples (meld.py)."""
    guild = getattr(channel, "guild", None)
    text = to_server_emojis(to_pings(reply), guild)
    if len(text) > 2000:  # Discord's limit: back to the whole sentences that fit, pings and emojis included
        log.info(f"Cut to fit Discord's 2000 characters, from {len(text)}")
        reply = whole(reply, 2000 - (len(text) - len(reply)))
        text = to_server_emojis(to_pings(reply), guild)
    kwargs = {}
    if replying_to is not None and hasattr(replying_to, "to_reference"):
        kwargs = {"reference": replying_to.to_reference(fail_if_not_exists=False), "mention_author": False}
    try:
        sent = await channel.send(text[:2000], **kwargs)  # Discord's hard message-length limit
    except (discord.HTTPException, aiohttp.ClientError, OSError) as e:
        # A timeout can follow remote acceptance. Treat it as terminal/unknown, never auto-resend.
        log.warning(f"Couldn't post in {channel_label(channel)}: {e}")
        return False
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
            try:
                chat_log.add(channel_id, channel_label(channel), sent.id, client.user.id, BOT_NAME, reply, about=about,
                             reply_to=getattr(replying_to, "id", None), answered_requests=list(answered_requests))
            except OSError:
                log.exception("Reply was delivered but could not be saved; it will not be resent")
    return True


def retire_requests(channel: discord.abc.Messageable, channel_id: int, requests: list[tuple], reason: str | None) -> None:
    """Finish pending requests once, including cancellation while their generation is in flight."""
    numbers = {n for n, _, _ in requests}
    pending = [request for request in unanswered[channel_id] if request[0] in numbers]
    unanswered[channel_id] = [request for request in unanswered[channel_id] if request[0] not in numbers]
    if not pending or not reason:
        return
    request_ids = [post.id for _, _, post in pending if getattr(post, "id", None) is not None]
    log.warning(f"Required reply failed ({reason}); retiring request ids {request_ids}")
    if getattr(channel, "guild", None):
        try:
            chat_log.add(channel_id, channel_label(channel), None, client.user.id, BOT_NAME, "",
                         kind="reply_failure", reason=reason, request_ids=request_ids)
        except OSError:
            log.exception("Could not save the reply failure event; requests remain terminal")


async def reply_to(channel: discord.abc.Messageable, channel_id: int, for_her: bool, must_answer: bool = False) -> None:
    seen = logged[channel_id]
    # One normal reply has room for at most three requests. Remaining requests get another bounded
    # batch rather than disappearing behind the global sentence limit.
    requests = list(unanswered[channel_id][:MAX_SENTENCES])
    latest = latest_post.get(channel_id)
    target = requests[-1][2] if requests else latest.message if latest is not None else None
    request_ids = [post.id for _, _, post in requests if getattr(post, "id", None) is not None]
    prepared = prepare_reply(channel_id, for_her, requests)
    # A chime-in is dropped if anyone posts while she writes, so it doesn't think (the user, 2026-11-22: "too
    # slow"; thinking took 7-14s, and Doumi's answers, 5-9s after a post, dropped 3 of her 5). Answers still do.
    chiming = not requests and not must_answer
    filtered_required = False
    async with channel.typing():
        reply = await generate_reply(channel_id, for_her, prepared=prepared, think=not chiming)
        if reply and (names := strangers(channel_id, reply)):
            log.info(f"Reply names someone who isn't here ({', '.join(names)}); retrying at temperature {RETRY_TEMPERATURE}")
            reply = await generate_reply(channel_id, for_her, temperature=RETRY_TEMPERATURE, prepared=prepared,
                                         think=not chiming) or reply
        elif reply and repeats_itself(channel_id, reply):
            log.info(f"Reply repeats one of Gomihyu's recent messages or example lines; retrying at temperature {RETRY_TEMPERATURE}")
            # If the retry fails outright, the repetitive reply beats no reply.
            reply = await generate_reply(channel_id, for_her, temperature=RETRY_TEMPERATURE, prepared=prepared,
                                         think=not chiming) or reply
        if reply and (names := strangers(channel_id, reply)):
            # Still there after the retry: those sentences go. Nothing left means nothing to say.
            filtered = without_names(reply, names)
            filtered_required = bool(requests and filtered != reply)
            reply = filtered
            log.info(f"Reply still named {', '.join(names)}; without those sentences: {reply[:200]!r}")

    if requests and {n for n, _, _ in requests}.isdisjoint(n for n, _, _ in unanswered[channel_id]):
        return  # a mute cancelled this batch, even if she was unmuted before generation finished
    if reply and muted(channel_id):
        log.info("Muted while writing a reply; not sending it")
        reply = None
    reason = "generation"
    if reply:
        moved = logged[channel_id] != seen
        if moved and chiming:
            log.info("Chat moved on while writing a chime-in; discarding the stale draft")
            return
        # Everyone in a required batch is already being answered, so none needs a ping.
        for _, _, post in requests:
            reply = without_ping(reply, post.author.id)
        # Log the reply right after the messages it answered, ahead of any that arrived while it
        # was being written, so a follow-up's last log line is still the newest unanswered message.
        censored = filtered_required or reply == f":{SLUR_STANDIN}:"
        sent = await send_reply(channel, channel_id, reply, seen, replying_to=target if moved or requests else None,
                                about="filtered" if censored else "reply",
                                answered_requests=[] if censored else request_ids)
        reason = ("filtered" if censored else None) if sent else "delivery"
    if requests:
        # Terminal failure: one generation attempt (plus existing content retry), one delivery attempt,
        # no automatic resend after an ambiguous network failure. Record failure separately from a reply.
        retire_requests(channel, channel_id, requests, reason)


def looking(message: discord.Message) -> str | discord.Emoji | None:
    """What she reacts to media she couldn't see with: she just looks, and doesn't judge it."""
    server = {e.name.lower(): e for e in message.guild.emojis} if message.guild else {}
    looks = [name for name in LOOKING if name in UNICODE or name.lower() in server]
    name = random.choice(looks) if looks else None
    return None if name is None else name if name in UNICODE else server[name.lower()]


async def read_room(message: discord.Message, text: str = "") -> tuple[Reading | None, str | discord.Emoji | None, str]:
    """Her read of a post (chime.py) and the reaction she'd put on it, as something to react with and its
    name: none ("") unless one fits and the post gets a rise out of her (REACT_THRESHOLD). None for the
    read if the model didn't answer usably."""
    channel_id = message.channel.id
    latest = latest_post.get(channel_id)
    if latest is None or latest.message is not message:
        return None, None, ""
    server = {e.name.lower(): e for e in message.guild.emojis} if message.guild else {}
    options = dict(UNICODE) | {name: use for name, (use, _) in CUSTOM.items() if name.lower() in server}
    theirs = posted_emoji(text)
    same = server.get(theirs.strip(":").lower()) if theirs and theirs.startswith(":") else theirs
    if same:
        options["same"] = "the same emoji they posted, joining in"
    used = list(recent_reactions[channel_id])  # emojis, never "same": echoing someone stays possible
    options = {name: use for name, use in options.items() if name not in used} or options
    replied = getattr(getattr(message, "reference", None), "resolved", None)
    replying_to = getattr(getattr(replied, "author", None), "name", None)
    data = await ollama_chat({"model": TASK_MODEL,
                              "messages": room_messages(list(history[channel_id]), options, diary.vibe(),
                                                        message.author.name, replying_to, used, avatar_description),
                              "format": room_format(options)})
    reading = parse_room(data.get("message", {}).get("content", ""), options) if data else None
    if reading is None:
        log.warning(f"Couldn't read the room for {message.author.name}'s post. Raw response: {json.dumps(data)[:300]}")
        return None, None, ""
    moved = REACT_THRESHOLD <= 0 or (reading.react is not None and reading.react >= REACT_THRESHOLD)
    fits = theirs if reading.emoji == "same" else reading.emoji or "none"
    log.info(f"Read {message.author.name}'s post: {reading.read or '(no read)'!r}, interest {reading.interest}, "
             f"react {reading.react}/10 (reacts at {REACT_THRESHOLD}), {fits} fits"
             + ("" if moved or not reading.emoji else ": no reaction"))
    if not reading.emoji or not moved:
        return reading, None, ""
    if reading.emoji == "same":
        return reading, same, theirs.strip(":")
    return reading, reading.emoji if reading.emoji in UNICODE else server[reading.emoji.lower()], reading.emoji


async def react_picked(message: discord.Message, emoji: str | discord.Emoji, name: str) -> None:
    """A reaction she chose (not a command's confirmation), remembered so she doesn't repeat it."""
    await react(message, emoji)
    recent_reactions[message.channel.id].append(name)


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
    """Whether the newest post, not aimed at her, interests her enough to say something. Either way it gets
    a reaction if it got a rise out of her (REACT_THRESHOLD; REACT_WHEN_REPLYING, REACT_TO_CHAT)."""
    if (latest := latest_post.get(channel_id)) is None:
        return False
    message = latest.message
    if message.author.bot:
        return False
    if CHIME_IN_THRESHOLD <= 0:
        return True
    newest = str(latest)
    reading, emoji, name = await read_room(message)
    if latest_post.get(channel_id) is not latest:
        log.info("Chat moved on while reading the room; reconsidering the latest post")
        return False
    if reading is None or reading.interest is None:
        log.warning(f"Couldn't tell whether to chime in on {newest[:80]!r}, staying quiet")
        return False
    chiming = reading.interest >= CHIME_IN_THRESHOLD
    # not muted: a mute can arrive while she reads
    reacting = emoji and (REACT_WHEN_REPLYING if chiming else REACT_TO_CHAT) and not muted(channel_id)
    log.info(f"Interest {reading.interest}/10 (chimes in at {CHIME_IN_THRESHOLD}) in {newest[:80]!r}: "
             + ("chiming in" if chiming else "staying quiet") + (f", reacting {name}" if reacting else ""))
    if reacting:
        await react_picked(message, emoji, name)
    return chiming


async def look_at(message: discord.Message) -> tuple[discord.Message, dict]:
    """What she sees in a post's pictures (vision.py): descriptions by (kind, index), and the message,
    re-fetched if it has a link whose preview Discord hadn't added yet."""
    if URL.search(message.content) and not getattr(message, "embeds", None) and message.guild:
        await asyncio.sleep(EMBED_WAIT_SECONDS)
        try:
            message = await message.channel.fetch_message(message.id)
        except discord.HTTPException as e:
            log.info(f"Couldn't fetch the link preview for {message.author.name}'s post: {e}")
    seen = {}
    for key, url, what, _ in sources(message)[:VISION_MAX_IMAGES]:
        remembered = url.split("?", 1)[0]
        if remembered in seen_before:
            seen[key] = seen_before[remembered]
            continue
        raw = await download(url)
        if raw and avatar_prints and vision.same_picture(vision.fingerprint(raw), avatar_prints):
            seen[key] = seen_before[remembered] = vision.avatar_label(avatar_description)
            log.info(f"Saw her own avatar in {message.author.name}'s post")
            continue
        image = jpeg_b64(raw) if raw else None
        if not image:
            continue
        start = time.monotonic()
        data = await ollama_chat({"model": VISION_MODEL, "messages": describe_messages(what, image),
                                  "options": {"temperature": 0.2} | cap(80)})
        description = clean_description(strip_thinking(data.get("message", {}).get("content", ""))) if data else None
        if description:
            seen[key] = seen_before[remembered] = description
            if len(seen_before) > 500:
                del seen_before[next(iter(seen_before))]
            log.info(f"Saw {what} from {message.author.name}: {description!r} ({time.monotonic() - start:.1f}s)")
    return message, seen


async def learn_avatar() -> None:
    """Her own avatar: its fingerprint, to know it when someone posts it (look_at), and what it looks like,
    for her prompts (AVATAR_DESCRIPTION, else VISION_MODEL's description). Again only if it changed."""
    global avatar_key, avatar_prints, avatar_description
    asset = client.user.avatar  # None: Discord's default avatar, which isn't really hers
    if asset is None or asset.key == avatar_key:
        return
    try:
        data = await asset.read()
    except discord.DiscordException as e:
        log.warning(f"Couldn't download her avatar, so she won't know it when it's posted: {e}")
        return
    avatar_key, avatar_prints = asset.key, vision.avatar_prints(data)
    if not AVATAR_DESCRIPTION and VISION and (image := jpeg_b64(data)):
        answer = await ollama_chat({"model": VISION_MODEL,
                                    "messages": describe_messages("Discord profile picture", image),
                                    "options": {"temperature": 0.2} | cap(80)})
        content = answer.get("message", {}).get("content", "") if answer else ""
        avatar_description = clean_description(strip_thinking(content)) or avatar_description
    log.info(f"Her avatar: {avatar_description or '(not described: set AVATAR_DESCRIPTION)'}")


async def download(url: str) -> bytes | None:
    """A picture to look at, at most VISION_MAX_BYTES, or None."""
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=20)) as resp:
                if resp.status != 200 or (resp.content_length or 0) > VISION_MAX_BYTES:
                    return None
                data, size = [], 0
                async for chunk in resp.content.iter_chunked(65536):
                    size += len(chunk)
                    if size > VISION_MAX_BYTES:
                        return None
                    data.append(chunk)
    except (aiohttp.ClientError, asyncio.TimeoutError, ValueError) as e:
        log.warning(f"Couldn't download a picture to look at ({e})")
        return None
    return b"".join(data)


@client.event
async def on_ready():
    global app_owner, melee_watcher
    log.info(f"Logged in as {client.user} (id: {client.user.id})")
    others = {"reading the room, diary": TASK_MODEL, "pictures": VISION_MODEL if VISION else MODEL_NAME}
    log.info(f"Her voice: {MODEL_NAME}" + "".join(f"; {job}: {model}" for job, model in others.items()
                                                    if model != MODEL_NAME))
    log.info(f"Example chats in her prompt: up to {FEW_SHOT_EXAMPLES} of her {len(earned)} landed replies"
             + (f", mixed with the {len(examples)} seed chats" if examples else ""))
    asyncio.create_task(learn_avatar())
    # on_ready runs again after a reconnect: one watcher is enough.
    if melee_watcher is None:
        melee_watcher = asyncio.create_task(watch_melee())
        asyncio.create_task(catch_up())
    try:
        app = await client.application_info()
    except discord.HTTPException as e:
        log.warning(f"Couldn't look up the bot's owner ({e}); only OWNER_USER_IDS can make her delete posts")
        return
    owners = app.team.members if app.team else [app.owner]
    owner_ids.update(owner.id for owner in owners)
    app_owner = (owners[0].id, owners[0].name)
    for owner in owners:
        handles.setdefault(owner.name.lower(), owner.id)
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
    if message.author.id == client.user.id:
        return

    channel_id = message.channel.id
    text = readable(message)
    if message.author.bot:
        observe(message, text)
        if message.guild:
            try:
                chat_log.add(channel_id, channel_label(message.channel), message.id, message.author.id,
                             message.author.name + " (bot)", readable(message, include_media=False), bot=True,
                             text_provenance="author", addressed=False,
                             context=conversation_text(message, text),
                             reply_to=getattr(getattr(message, "reference", None), "message_id", None))
            except OSError:
                log.exception("Could not save the observed bot post; keeping its in-memory context")
        return  # visible context, never a command, a reply trigger, or a training target
    for user in (message.author, *message.mentions):
        handles[user.name.lower()] = user.id
        handles[user.display_name.lower()] = user.id
        display_names[user.id] = user.display_name
    mentioned = client.user in message.mentions
    typed = readable(message, include_media=False)
    for_her = mentioned or replying_to_her(message) or names_her(typed)

    # The owner's "gg" (to her, or in her Melee channel) while she holds matches: the session is over,
    # she posts about it now. With nothing held it's just chat.
    global melee_gg
    if (message.author.id in owner_ids and gg_request(text) and (for_her or channel_id == melee_channel())
            and melee_held()):
        melee_gg = True
        log.info(f"{message.author.name} said gg: posting about the Melee session")
        await react(message, MELEE_EMOJI)
        return

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
                if what == "Muted":
                    retire_requests(message.channel, channel_id, unanswered[channel_id], "muted")
                    pending_followup.pop(channel_id, None)
                log.info(f"{what} in {where} " + ("until unmuted" if minutes == FOREVER else f"for {minutes:g} minutes")
                         + f", by {message.author.name}")
                await react(message, emoji)
                return

    line = observe(message, text)  # now, so posts arriving while she looks stay in order
    number = logged[channel_id]
    needs_reply = for_her or (sad_news(typed) and not quiet(channel_id))
    if needs_reply and not muted(channel_id):
        unanswered[channel_id].append((number, line, message))
    if message.guild:  # save the arrival before vision yields; never DMs
        try:
            chat_log.add(channel_id, channel_label(message.channel), message.id, message.author.id, message.author.name,
                         typed, context=conversation_text(message, text), text_provenance="author", addressed=for_her,
                         reply_to=getattr(getattr(message, "reference", None), "message_id", None))
        except OSError:
            log.exception("Could not save the observed post; continuing with its in-memory context")
    sees = False
    if VISION and (sources(message) or URL.search(message.content)):
        ready = asyncio.get_running_loop().create_future()
        pending_vision[channel_id].add(ready)
        try:
            message, seen = await look_at(message)
            sees = bool(seen)
            described = readable(message, seen)
            enriched = ObservedLine(message, described)
            lines = history[channel_id]
            for i, old in enumerate(lines):
                if old is line:
                    lines[i] = enriched
                    break  # evicted observations stay evicted; their pending request still gets its context
            latest = latest_post.get(channel_id)
            if latest is line:
                latest_post[channel_id] = enriched
            unanswered[channel_id] = [(n, enriched, message) if n == number else (n, old, post)
                                      for n, old, post in unanswered.get(channel_id, [])]
            if described != text and message.guild:
                try:
                    chat_log.enrich(channel_id, message.id, conversation_text(message, described))
                except OSError:
                    log.exception("Could not save the picture description; continuing with its in-memory context")
            text = described
        finally:
            pending_vision[channel_id].discard(ready)
            if not ready.done():
                ready.set_result(None)
    await take_notes(message, typed, mentioned)  # not what's written in a picture

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
    if not for_her and reacts_instead(text, REACT_ONLY_MAX_WORDS):
        if media_only(text) and not sees:  # she couldn't see it, so she doesn't pretend to judge it
            if emoji := looking(message):
                await react(message, emoji)
        else:
            _, emoji, name = await read_room(message, text)
            if emoji:
                await react_picked(message, emoji, name)
        return

    # Aimed at her: always answered. Anything else only if it interests her (chimes_in), and never in
    # quiet mode, not even sad news (the sad cat above still says she saw it).
    addressed = for_her or (sad_news(typed) and not quiet(channel_id))
    if quiet(channel_id) and not addressed:
        return
    if needs_reply and not any(n == number for n, _, _ in unanswered.get(channel_id, [])):
        return  # another reply already covered this request while its pictures were being described

    lock = reply_locks[channel_id]
    if lock.locked():
        # Already deciding or writing a reply here; everything that arrives meanwhile gets one follow-up.
        was_for_her, was_addressed = pending_followup.get(channel_id, (False, False))
        pending_followup[channel_id] = (was_for_her or for_her, was_addressed or addressed)
        return

    async with lock:
        try:
            await converse(message.channel, channel_id, for_her, addressed)
        finally:
            pending_followup.pop(channel_id, None)


async def converse(channel: discord.abc.Messageable, channel_id: int, for_her: bool, addressed: bool) -> None:
    """Reply if she should, then once more for whatever arrived meanwhile. Holds the channel's lock."""
    while not muted(channel_id):
        if addressed and not unanswered[channel_id]:
            break  # the required turn was cancelled during an await, possibly followed by an unmute
        if waiting := list(pending_vision[channel_id]):
            await asyncio.gather(*(asyncio.shield(ready) for ready in waiting))
            continue  # recheck mute and any descriptions that began while waiting
        revision = logged[channel_id]
        should_reply = bool(unanswered[channel_id]) or addressed or (not quiet(channel_id) and await chimes_in(channel_id))
        # chimes_in can await both a room read and a Discord reaction. Revalidate after *all* of it,
        # immediately before reply_to freezes the prompt; no requests have been consumed yet.
        if pending_vision[channel_id] or logged[channel_id] != revision:
            if pending_vision[channel_id] or unanswered[channel_id] or channel_id in pending_followup:
                for_her, addressed = pending_followup.pop(channel_id, (False, False))
                addressed = bool(unanswered[channel_id])
                continue
            break  # a reaction-only correction invalidated the read without scheduling another reply
        if should_reply:
            # What arrived while she was deciding is already in the log, so this reply covers it.
            was_for_her, was_addressed = pending_followup.pop(channel_id, (False, False))
            await reply_to(channel, channel_id, for_her or was_for_her, addressed or was_addressed)
        if unanswered[channel_id]:
            addressed = True
            continue
        if channel_id not in pending_followup:
            break
        for_her, addressed = pending_followup.pop(channel_id)


def melee_player() -> str:
    """Who she played: MELEE_PLAYER, else the owner by nickname or display name."""
    if MELEE_PLAYER:
        return MELEE_PLAYER
    if app_owner:
        user_id, handle = app_owner
        return memory.nickname_for(user_id) or display_names.get(user_id) or handle
    return "the owner"


async def session_post(channel_id: int, matches: list[dict], taunts: list[str] = (),
                       temperature: float | None = None) -> str | None:
    """Her one message about a Melee session (melee.py), or None if the model didn't answer."""
    options = cap(max(MAX_REPLY_TOKENS, 400), OLLAMA_THINK)  # 3-5 sentences
    if temperature is not None:
        options["temperature"] = temperature
    player = melee_player()
    facts = session_facts(matches, player, taunts)
    payload = {"messages": build_session_messages(list(history[channel_id]), facts, player, shown_examples(),
                                                  diary.vibe(), avatar_description),
               "options": options, "think": OLLAMA_THINK}
    start = time.monotonic()
    data = await ollama_chat(payload)
    return clean_reply(data, None, start, sentences=5) if data else None  # asked for 3 to 5


def melee_held() -> bool:
    """Whether matches are waiting in AI-Melee's outbox for her session post."""
    if not MELEE_OUTBOX.is_dir():
        return False
    return any(event.get("kind", "match") == "match" for _, event in read_outbox(MELEE_OUTBOX, log))


async def post_session(outbox: Path) -> bool:
    """One post about the session, once it's over (melee.session_ready): the game closed, the owner
    said "gg", or no match has come for a while. Until then matches wait in the outbox. Her in-match
    taunts aren't posted: they're taken out of the outbox and held (melee_taunts) for her session post.
    The matches stay in the outbox if the model doesn't answer, to be tried again later (until they're
    too old). True if that's why it stopped."""
    global melee_gg
    max_age = MELEE_MAX_AGE_MINUTES * 60
    events = read_outbox(outbox, log)
    for path, event in events:
        if event.get("kind") == "taunt":
            path.unlink(missing_ok=True)  # out of the outbox now: AI-Melee only keeps its newest files
            text = str(event["text"]).strip()
            if text and not has_slur(text) and not stale(event, max_age):
                melee_taunts.append((float(event.get("time", 0)), text))
    melee_taunts[:] = [(said, text) for said, text in melee_taunts if not stale({"time": said}, max_age)]

    held = [(path, event) for path, event in events if event.get("kind") != "taunt"]
    matches, ends = session_ready(held, time.time(), MELEE_SESSION_IDLE_MINUTES * 60, gg=melee_gg)
    if not matches:
        for path in ends:
            path.unlink(missing_ok=True)  # a session that ended with nothing (left) to say about
        melee_gg = False
        return False
    first = min(float(e.get("time", 0)) for _, e in matches)
    last = max(float(e.get("time", 0)) for _, e in matches)
    files = [path for path, _ in matches] + ends

    def done() -> None:
        global melee_gg
        for path in files:
            path.unlink(missing_ok=True)
        forget_taunts(last)
        melee_gg = False

    if stale({"time": last}, max_age):
        log.info(f"Melee session of {len(matches)} matches is too old to post; dropping it")
        done()
        return False
    channel_id = melee_channel()
    if not channel_id:
        return False  # no channel yet: the session waits (watch_melee said how to pick one)
    channel = client.get_channel(channel_id)
    if channel is None:
        try:
            channel = await client.fetch_channel(channel_id)
        except discord.HTTPException as e:
            log.error(f"Can't reach the Melee channel {channel_id} ({e}); her Melee post waits")
            return False
    channel_id = channel.id
    if muted(channel_id):
        log.info(f"Muted in the Melee channel; not posting about {len(matches)} matches")
        done()
        return False
    taunts = [text for said, text in melee_taunts if first - TAUNT_WINDOW_SECONDS <= said <= last]
    events_only = [event for _, event in matches]
    async with reply_locks[channel_id]:
        try:
            async with channel.typing():
                post = await session_post(channel_id, events_only, taunts)
                if post and repeats_itself(channel_id, post):
                    post = await session_post(channel_id, events_only, taunts, temperature=RETRY_TEMPERATURE) or post
            if post:
                done()
                if muted(channel_id):
                    log.info("Muted while writing a Melee post; not sending it")
                else:
                    log.info(f"Posting about a Melee session of {len(matches)} match{'es' if len(matches) != 1 else ''}"
                             + (f" ({len(taunts)} of her in-match lines to draw on)" if taunts else ""))
                    await send_reply(channel, channel_id, post, about="melee")
            # Anything said while she was writing gets its usual answer now.
            if channel_id in pending_followup:
                for_her, addressed = pending_followup.pop(channel_id)
                await converse(channel, channel_id, for_her, addressed)
        finally:
            pending_followup.pop(channel_id, None)
    return not post  # the model didn't answer: try again later


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
                stalled = await post_session(outbox)
        except Exception:
            log.exception("Posting Melee results failed; trying again")
            stalled = True
        # Ollama down or a bad file: wait a minute rather than fail every 5 seconds.
        await asyncio.sleep(MELEE_RETRY_SECONDS if stalled else MELEE_CHECK_SECONDS)


melee_watcher = None
# a picture's address (without its query) -> what she saw in it, so the same GIF isn't looked at twice
seen_before = {}
# Her own avatar (learn_avatar): which one it is, its fingerprints, and what it looks like
avatar_key, avatar_prints, avatar_description = None, set(), AVATAR_DESCRIPTION
# (time.time() she said it, text) of her in-match taunts, held until their session is over (post_session)
melee_taunts = []
melee_gg = False  # the owner said "gg": post about the session now


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
            # An already saved picture must finish enriching before a diary cursor can pass it.
            # The cutoff remains the arrival snapshot; later arrivals stay unread for the next pass.
            if waiting := list(pending_vision[channel_id]):
                await asyncio.gather(*(asyncio.shield(ready) for ready in waiting))
            since = diary.read_up_to(channel_id)
            entries = chat_log.read(channel_id, after=since, before=before)
            if not entries:
                continue
            keep_landed(chat_log.read(channel_id, after=since, before=before, reactions=True))
            said += [e for e in entries if e["author"] != BOT_NAME and not e.get("bot")]
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
        raw = raw_author_text(e)
        if raw is None or not raw.strip():
            continue
        line = format_line(e["author"], raw)
        size += len(line) + 1
        if lines and size > VIBE_CHARS:
            break
        lines.append(line)
    lines.reverse()
    if not lines:
        return
    data = await ollama_chat({"model": TASK_MODEL, "messages": vibe_messages(diary.vibe(), lines),
                              "format": VIBE_FORMAT,
                              "options": {"temperature": 0.3} | cap(400)})
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
    ids = {entry["author"]: entry.get("author_id") for entry in part
           if entry["author"] != BOT_NAME and not entry.get("bot")}
    day, where = local_day(part[0]["time"]), part[-1].get("channel") or f"channel {channel_id}"
    if sum(entry["author"] != BOT_NAME for entry in part) >= 2:
        options = {"temperature": 0.3} | cap(700)
        lines = [render_line(e) for e in part]
        data = await ollama_chat({"model": TASK_MODEL, "messages": digest_messages(where, day, lines),
                                  "format": digest_format(sorted(ids)), "options": options})
        if data is None:
            return False
        digest = parse_digest(data.get("message", {}).get("content", ""), sorted(ids), part)
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


async def catch_up() -> None:
    """At the start: write up what a crash or a closed terminal left unread, then post what's waiting."""
    await write_diary("catching up on chat from before she started", before=started)
    await post_diary()


async def post_diary() -> None:
    """Post her diary's new recaps (POST_DIARY), each channel's in that channel. Only posted: not in her chat
    log or history, so she doesn't answer it, write it up again or learn her voice from it (meld.py), and
    it doesn't come back after a restart."""
    async with diary_lock:
        waiting = diary.to_post()
        by_channel = defaultdict(list)
        for recap in waiting if POST_DIARY else []:
            by_channel[recap["channel_id"]].append(recap)
        for channel_id, recaps in by_channel.items():
            where = recaps[-1].get("channel") or f"channel {channel_id}"
            if muted(channel_id):
                log.info(f"Muted in {where}; not posting her diary there")
                continue
            try:
                channel = client.get_channel(channel_id) or await client.fetch_channel(channel_id)
                for text in diary_posts(recaps):
                    await channel.send(text)
            except discord.HTTPException as e:  # gone, or no Send Messages there
                log.warning(f"Couldn't post her diary in {where}: {e}")
                continue
            log.info(f"Posted her diary in {where} ({len(recaps)} entr{'ies' if len(recaps) != 1 else 'y'})")
        diary.mark_posted(waiting)


async def go_to_bed(message: discord.Message) -> None:
    """An owner's "gomi goodnight": she writes and posts her diary, says goodnight, and the bot shuts down."""
    channel_id = message.channel.id
    log.info(f"{message.author.name} put her to bed: writing her diary, saying goodnight, then shutting down")
    await react(message, GOODNIGHT_EMOJI)
    try:
        async with contextlib.nullcontext() if muted(channel_id) else message.channel.typing():
            await write_diary("going to bed")
            await post_diary()
    except Exception:  # bedtime goes ahead whatever happens; main() tries the diary again at shutdown
        log.exception("Couldn't write or post her diary before bed")
    if not muted(channel_id):
        owner = memory.nickname_for(message.author.id) or message.author.display_name
        start = time.monotonic()
        data = await ollama_chat({"messages": build_goodnight_messages(list(history[channel_id]), owner, diary.vibe(),
                                                                       avatar_description),
                                  "options": cap(MAX_REPLY_TOKENS, OLLAMA_THINK), "think": OLLAMA_THINK})
        if data and (line := clean_reply(data, message.author.id, start, LINE_SENTENCES)):
            await send_reply(message.channel, channel_id, line, about="goodnight")
    await client.close()


def reload_history() -> None:
    """Pick the chat back up after a restart: each channel's last HISTORY_LENGTH messages from the log,
    if newer than HISTORY_RELOAD_HOURS, and who's who (everyone the log has seen) for pings and for
    telling real people from made-up ones (strangers)."""
    since = time.time() - HISTORY_RELOAD_HOURS * 3600
    for channel_id in chat_log.channels():
        everything = chat_log.read(channel_id)
        for entry in reversed(everything):  # newest first: a handle is whoever had it last
            if entry["author"] != BOT_NAME and not entry.get("bot") and entry.get("author_id"):
                handles.setdefault(entry["author"].lower(), entry["author_id"])
        entries = [entry for entry in everything if entry["time"] > since][-HISTORY_LENGTH:]
        for entry in entries:
            history[channel_id].append(format_line(entry["author"], entry.get("context", entry["text"])))
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
