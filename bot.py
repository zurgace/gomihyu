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
from chime import INTEREST_FORMAT, interest_messages, parse_interest
from commands import ALL, delete_request
from emojis import CUSTOM, LOOKING, SAD_NEWS, SLUR_STANDIN, UNICODE
from memory import PeopleMemory, aimed_at_her, fact_to_remember, nicknames_in
from persona import BOT_NAME, BOT_NICKNAME, build_messages, format_line
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
REMEMBERED_EMOJI = "📝"  # reaction confirming a fact or nickname was stored
# Who can make her delete her posts ("gomi delete that", commands.py): the bot application's owner,
# looked up at login, plus these Discord user ids (comma-separated).
OWNER_USER_IDS = {int(user_id) for user_id in re.findall(r"\d+", os.environ.get("OWNER_USER_IDS", ""))}
# "Delete all your messages" means her posts among this many of the channel's newest messages.
DELETE_SCAN = int(os.environ.get("DELETE_SCAN", "200"))
DELETED_EMOJI = "🗑️"  # reaction confirming her posts were deleted
NOTHING_TO_DELETE_EMOJI = "🤷"
# Made-up example chats (the fine-tuning seed) shown in her prompt to set her voice, until a
# fine-tuned model carries it. A fresh random pick each reply; 0 turns them off.
EXAMPLES_FILE = Path(__file__).resolve().parent / os.environ.get("EXAMPLES_FILE", "finetuning/gomihyu_seed.jsonl")
FEW_SHOT_EXAMPLES = int(os.environ.get("FEW_SHOT_EXAMPLES", "8"))

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
# message id -> (channel_id, her chat-log line) for her recent posts, so a deleted post leaves her log too
posted = {}
memory = PeopleMemory(PEOPLE_FILE, MAX_FACTS_PER_PERSON)


def load_examples(path: Path) -> list[dict]:
    if FEW_SHOT_EXAMPLES <= 0:
        return []
    if not path.exists():
        log.warning(f"No example chats at {path}; replying without them")
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


examples = load_examples(EXAMPLES_FILE)

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
            or any(runs & word_runs(example["reply"]) for example in examples))


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
    shown = random.sample(examples, min(FEW_SHOT_EXAMPLES, len(examples)))
    payload = {"messages": build_messages(list(history[channel_id]), triggered_by_mention,
                                          author_handle, memory.facts_for(author_id), nicknames, shown),
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


async def reply_to(channel: discord.abc.Messageable, channel_id: int, mentioned: bool) -> None:
    seen = logged[channel_id]
    async with channel.typing():
        reply = await generate_reply(channel_id, triggered_by_mention=mentioned)
        if reply and repeats_itself(channel_id, reply):
            log.info(f"Reply repeats one of Gomihyu's recent messages or example lines; retrying at temperature {RETRY_TEMPERATURE}")
            # If the retry fails outright, the repetitive reply beats no reply.
            reply = await generate_reply(channel_id, triggered_by_mention=mentioned, temperature=RETRY_TEMPERATURE) or reply

    if reply:
        # Log the reply right after the messages it answered, ahead of any that arrived while it
        # was being written, so a follow-up's last log line is still the newest unanswered message.
        lines = history[channel_id]
        newer = [lines.pop() for _ in range(min(logged[channel_id] - seen, len(lines)))]
        line = format_line(BOT_NAME, reply)
        lines.append(line)
        lines.extend(reversed(newer))
        text = to_server_emojis(to_pings(reply), getattr(channel, "guild", None))
        if sent := await channel.send(text[:2000]):  # Discord's hard message-length limit
            posted[sent.id] = (channel_id, line)
            if len(posted) > 1000:
                del posted[next(iter(posted))]


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
    deleted = 0
    for post in targets:
        try:
            await post.delete()
        except discord.NotFound:
            pass  # already gone
        except discord.HTTPException as e:
            log.warning(f"Couldn't delete her post {post.id}: {e}")
            continue
        deleted += 1
        if entry := posted.pop(post.id, None):
            channel_id, line = entry
            try:
                history[channel_id].remove(line)
            except ValueError:
                pass  # already scrolled out of her log
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
    log.info(f"Logged in as {client.user} (id: {client.user.id})")
    try:
        app = await client.application_info()
    except discord.HTTPException as e:
        log.warning(f"Couldn't look up the bot's owner ({e}); only OWNER_USER_IDS can make her delete posts")
        return
    owners = app.team.members if app.team else [app.owner]
    owner_ids.update(owner.id for owner in owners)
    log.info(f"Owner commands (deleting her posts) accepted from: {', '.join(owner.name for owner in owners)}"
             + (f", and user ids {', '.join(map(str, sorted(OWNER_USER_IDS)))}" if OWNER_USER_IDS else ""))


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

    # An owner telling her to delete her posts overrides the persona: done in code, never shown to
    # the model or kept in her chat log.
    if (message.author.id in owner_ids and (count := delete_request(text))
            and (mentioned or replying_to_her(message) or names_her(text))):
        await delete_posts(message, count)
        return

    history[channel_id].append(format_line(message.author.name, text))
    logged[channel_id] += 1
    last_author[channel_id] = (message.author.id, message.author.name)

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

    # Aimed at her: always answered. Anything else only if it interests her (chimes_in).
    addressed = mentioned or replying_to_her(message) or names_her(text) or sad_news(text)

    lock = reply_locks[channel_id]
    if lock.locked():
        # Already deciding or writing a reply here; everything that arrives meanwhile gets one follow-up.
        was_mentioned, was_addressed = pending_followup.get(channel_id, (False, False))
        pending_followup[channel_id] = (was_mentioned or mentioned, was_addressed or addressed)
        return

    async with lock:
        try:
            while True:
                if addressed or await chimes_in(channel_id):
                    # What arrived while she was deciding is already in the log, so this reply covers it.
                    was_mentioned, _ = pending_followup.pop(channel_id, (False, False))
                    await reply_to(message.channel, channel_id, mentioned or was_mentioned)
                if channel_id not in pending_followup:
                    break
                mentioned, addressed = pending_followup.pop(channel_id)
        finally:
            pending_followup.pop(channel_id, None)


if __name__ == "__main__":
    client.run(DISCORD_TOKEN)
