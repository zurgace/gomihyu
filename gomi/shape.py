"""
The shape of her replies, decided in code (user, 2026-10-04: her replies had become one template, an
emoji before every sentence, five to seven sentences, a question at the end, whatever was said).

A small model can't follow "now and then" (it doesn't count its own messages) or count its sentences,
and it copies whatever its last few messages in the log looked like, so once a habit slips in, every
reply has it. So code decides, per reply, and tells her concretely (persona.build_messages):
  - length, one of three sizes from what she's answering (sentences_for):
      a short post that isn't a question (a jab, "slopot", "gomi hi"): one short line;
      a post aimed at her that asks for something that takes room (needs_room: "make me a build",
      "explain wavedashing", "how do I beat fox", a list, tips, steps): the whole answer, tight, up to
      ROOM_SENTENCES, with a bigger token cap (bot.py);
      anything else: 1 to 3 sentences.
    A reply that runs longer is cut after its last sentence that fits (at_most), one stopped mid-sentence
    (the token cap, Discord's 2000 characters) back to its last whole sentence or line (whole), and then
    posted; one the cap stopped before a single whole sentence is written again without it (bot.py), since
    "The answer is forty" may be half of "forty-two". Never dropped (user, 2026-11-15: an answer aimed at
    her that ran long was thrown away whole, so "ok gomi make me a build" got the typing dots and then
    nothing, three times in a row; "she's built to have really long posts to be stopped... the method to do
    so needs to be changed"). The room phrases are few on purpose, so a miss gets 1 to 3 sentences: the
    server found her wordy (user, 2026-10-22: "a verbose chud"; 10-23: "keep it below 20 words"), and a
    size left to her went the other way (persona.build_messages).
  - asking back: only if none of her last RECENT messages asked anything;
  - emojis: at most one per message (the last she can post), and none if one of her last RECENT had one.
Her replies that landed before this (meld.py) are held to the same limits (tidy) as examples and training data.
"""

import re

from .emojis import CUSTOM
from .reactions import ADDRESSED, EMOJI, MEDIA, sad_news, words

RECENT = 2  # her own latest messages that "now and then" looks back on
LINE_SENTENCES = 2  # a one-line reply: "AGAIN?? ...third time's the charm, kaz0. probably." is still one
MAX_SENTENCES = 3  # anything else ("1 to 3 sentences, never more")
ROOM_SENTENCES = 6  # asked for room ("up to 6 sentences or a short list")
SENTENCE_END = re.compile(r"[.!?…](?=\s|$)")
WHOLE = re.compile(r"[.!?…](?=\s|$)|\n")  # the end of a whole sentence, or of a line (a list's item)
ROOM = re.compile(r"\b(?:explain|lists?|tips|guides?|recipes?|rundown|breakdown|step by step|walk (?:me|us) through|"
                  r"teach (?:me|us)|how (?:do|can|should) (?:i|we)|(?:make|build) (?:me|us) an?)\b", re.I)
NAMES = {name.lower() for name in CUSTOM}  # ":200:" is an emoji, "10:30:45" isn't
IN_TEXT = {name.lower() for name, (_, in_text) in CUSTOM.items() if in_text}  # what she can post
QUESTION_WORDS = {"who", "what", "whats", "when", "where", "why", "how", "which", "is", "are", "am", "was", "were",
                  "do", "does", "did", "can", "could", "would", "will", "should", "wanna"}


def quick(text: str, max_words: int) -> bool:
    """Whether a post (as bot.readable() renders it) calls for one short line: at most max_words words
    besides her name, no question, not bad news. "you are such a slop bot", "gomi look [image: ...]"."""
    said = [word for word in words(text) if not ADDRESSED.fullmatch(word)]
    return (len(said) <= max_words and not asked(text) and not sad_news(text)
            and not (said and said[0].lower() in QUESTION_WORDS))


def needs_room(text: str) -> bool:
    """Whether a post asks for something 1 to 3 sentences can't hold: "ok gomi make me a build", "explain
    wavedashing", "how do I beat fox", "any tips?". "what build should I run" isn't caught: it gets 1 to 3."""
    return bool(ROOM.search(MEDIA.sub(" ", text)))


def asked(text: str) -> bool:
    """Whether a message has a question in it (not counting a link's or picture's)."""
    return "?" in MEDIA.sub(" ", text)


def emojis_in(text: str) -> list[re.Match]:
    """Unicode emojis and :name: ones (made-up names too: they'd post as plain text), in order."""
    return [m for m in EMOJI.finditer(text) if not m[1] or m[1].lower() in NAMES or re.search(r"[^\W\d_]", m[1])]


def one_emoji(text: str, keep: bool = True) -> str:
    """text with at most one emoji (none unless keep), each removed with the space next to it. The one kept
    is the last one she can really post: unicode, or an in-text one from emojis.py, rather than a made-up name
    that would post as text. A message that's nothing but emojis keeps that one."""
    found = emojis_in(text)
    if not found:
        return text
    real = [m for m in found if not m[1] or m[1].lower() in IN_TEXT]
    kept = (real or found)[-1]
    out, pos = "", 0
    for m in found:
        if keep and m is kept:
            continue
        out += text[pos:m.start()]
        pos = m.end()
        if not out or out[-1] == " ":
            while text[pos:pos + 1] == " ":
                pos += 1
            if pos == len(text) or (text[pos] in ".,!?" and not text.startswith("..", pos)):  # not " ...fine"
                out = out.rstrip(" ")
    return (out + text[pos:]).strip() or kept[0]


def at_most(text: str, sentences: int) -> str:
    """text cut after its `sentences`-th sentence. A bit of a few words ("Really.", "...probably.") isn't
    counted as one, and stays if it comes right after the last."""
    counted, start = 0, 0
    for end in [*SENTENCE_END.finditer(text), None]:
        stop = end.end() if end else len(text)
        if len(words(text[start:stop])) >= 3:
            if counted == sentences:
                return text[:start].rstrip()
            counted += 1
        start = stop
    return text


def whole(text: str, chars: int | None = None) -> str:
    """text cut back to its last whole sentence or line, within chars characters if given: what can still be
    posted of a reply the token cap stopped mid-sentence, or of one too long for Discord. With no whole one
    in reach, the text as it is, up to chars."""
    limit = len(text) if chars is None else chars
    ends = [m.end() for m in WHOLE.finditer(text) if m.end() <= limit]
    return text[:ends[-1]].rstrip() if ends else text[:limit]


def this_time(newest: str, mine: list[str], max_words: int, pending_raw: list[str] = ()) -> dict:
    """build_messages' say for one reply: newest is the post she's answering, mine her own latest messages
    in the chat, oldest first. pending_raw contains the author words of requests actually being
    answered; unrelated newest chatter and displayed quotes cannot shorten their answer. Only those can ask
    for room: a chime-in adds to the talk."""
    recent = mine[-RECENT:]
    room = any(needs_room(text) for text in pending_raw)
    return {"one_line": not room and len(pending_raw) <= 1 and quick(pending_raw[0] if pending_raw else newest, max_words),
            "room": room,
            "ask_back": not any(asked(line) for line in recent),
            "emoji": not any(emojis_in(line) for line in recent)}


def sentences_for(shape: dict) -> int:
    """How many sentences a reply of this shape (this_time) may have, at most."""
    return LINE_SENTENCES if shape["one_line"] else ROOM_SENTENCES if shape["room"] else MAX_SENTENCES


def tidy(reply: str, room: bool = False) -> str:
    """One of her old replies held to today's limits: one emoji, and 3 sentences, or 6 if what it answered
    asked for room (persona.asked_room)."""
    return at_most(one_emoji(reply), ROOM_SENTENCES if room else MAX_SENTENCES)
