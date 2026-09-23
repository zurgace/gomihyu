"""
When Gomihyu answers a post with an emoji reaction instead of words, and the emoji-picking prompt.

Posts that don't need words get a reaction as her whole response: images, stickers, emoji-only
posts and short interjections ("oogaga", "lol wtf"). Not if they're aimed at her or serious.
Texts here are as bot.readable() renders them: custom emojis as :name:, media as [image] etc.
"""

import re

ADDRESSED = re.compile(r"\bgomi(?:hyu)?\b", re.IGNORECASE)
# Bad news gets words, never just an emoji.
SERIOUS = re.compile(r"\b(?:died|passed away|funeral|hospital|sad|depressed|crying|cried|rough|breakup|"
                     r"broke up|lost my|grieving)\b", re.IGNORECASE)
# Media she can't see; a bare link (usually a Tenor GIF) counts too.
MEDIA = re.compile(r"\[(?:image|video|file|sticker)[^\]]*\]|https?://\S+")
_PIC = r"[\u2190-\u21FF\u2600-\u27BF\u2B00-\u2BFF\U0001F000-\U0001FAFF]"
# One emoji: a :custom: name, a flag, or a pictograph with its skin-tone/ZWJ/variation parts.
EMOJI = re.compile(rf":(\w+):|[\U0001F1E6-\U0001F1FF]{{2}}|{_PIC}[\uFE0F\U0001F3FB-\U0001F3FF]*"
                   rf"(?:\u200D{_PIC}[\uFE0F\U0001F3FB-\U0001F3FF]*)*")
WORD = re.compile(r"\w+")


def _words(text: str) -> list[str]:
    return WORD.findall(EMOJI.sub(" ", MEDIA.sub(" ", text)))


def reacts_instead(text: str, max_words: int) -> bool:
    """Whether a reaction says enough: no words at all, or a few without a question."""
    said = MEDIA.sub(" ", text)  # what they typed, not a link's text ("cat-crying-gif")
    if ADDRESSED.search(said) or SERIOUS.search(said):
        return False
    words = _words(text)
    return not words or (len(words) <= max_words and "?" not in text)


def media_only(text: str) -> bool:
    """An image/video/file/sticker/link with nothing else: she can't see it, so she just looks."""
    return bool(MEDIA.search(text)) and not _words(text) and not EMOJI.search(text)


def posted_emoji(text: str) -> str | None:
    """The first emoji of an emoji-only post (":name:" for custom ones), for reacting the same."""
    if _words(text) or MEDIA.search(text):
        return None
    first = EMOJI.search(text)
    return first[0] if first else None


def picker_messages(recent: list[str], options: dict[str, str]) -> list[dict]:
    listing = "\n".join(f"- {name}: {use}" for name, use in options.items())
    return [
        {"role": "system", "content": "You choose the one emoji reaction that Gomihyu, a bratty, dramatic "
                                      "self-proclaimed demon in a small Discord server, would put on a message. "
                                      "Match the message's mood; pick none if nothing fits."},
        {"role": "user", "content": "Recent chat, one 'handle: message' per line:\n" + "\n".join(recent)
                                    + f"\n\nReact to the last message. Options:\n{listing}\n- none: nothing fits\n\n"
                                    'Answer as JSON: {"emoji": "<option>"}'},
    ]


def picker_format(options: dict[str, str]) -> dict:
    """JSON schema for Ollama's `format`, so the answer can only be one of the options or none."""
    return {"type": "object", "properties": {"emoji": {"type": "string", "enum": [*options, "none"]}},
            "required": ["emoji"]}
