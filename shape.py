"""
The shape of her replies, decided in code (user, 2026-10-04: her replies had become one template, an
emoji before every sentence, five to seven sentences, a question at the end, whatever was said).

A small model can't follow "now and then" (it doesn't count its own messages) or count its sentences,
and it copies whatever its last few messages in the log looked like, so once a habit slips in, every
reply has it. So code decides, per reply, and tells her concretely (persona.build_messages):
  - length: a short post that isn't a question (a jab, "slopot", "gomi hi") gets one short line, anything
    else 1 to 3 sentences. A reply that runs longer is cut after its 2nd or 3rd sentence (at_most).
  - asking back: only if none of her last RECENT messages asked anything;
  - emojis: at most one per message (the last she can post), and none if one of her last RECENT had one.
Her replies that landed before this (meld.py) are held to the same limits (tidy) as examples and training data.
"""

import re

from emojis import CUSTOM
from reactions import ADDRESSED, EMOJI, MEDIA, sad_news, words

RECENT = 2  # her own latest messages that "now and then" looks back on
LINE_SENTENCES = 2  # a one-line reply: "AGAIN?? ...third time's the charm, kaz0. probably." is still one
MAX_SENTENCES = 3  # anything else ("1 to 3 sentences, never more")
SENTENCE_END = re.compile(r"[.!?…](?=\s|$)")
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


def this_time(newest: str, mine: list[str], max_words: int) -> dict:
    """build_messages' say for one reply: newest is the post she's answering, mine her own latest messages
    in the chat, oldest first."""
    recent = mine[-RECENT:]
    return {"one_line": quick(newest, max_words),
            "ask_back": not any(asked(line) for line in recent),
            "emoji": not any(emojis_in(line) for line in recent)}


def tidy(reply: str) -> str:
    """One of her old replies held to today's limits: 3 sentences, one emoji."""
    return at_most(one_emoji(reply), MAX_SENTENCES)
