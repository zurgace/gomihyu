"""
What she sees in pictures (user, 2026-09-29, after tools/vision_check.py showed Gemma 4 E4B sees images on
their Ollama): each picture in a post gets one short description, once, from a vision call, and it
stands in for the picture from then on: "[image]" becomes "[image: a cat in a tiny wizard hat]" in her
chat log, so her replies, her read of the room (reactions, chiming in), diary and training data all
know what was posted, with no more calls.

She looks at attached images and GIFs (the first frame), stickers (not Lottie ones, which aren't
pictures) and link previews: the card Discord shows under a link (title, description, thumbnail),
fetched from Discord's proxy. She never opens the linked page itself; that stays out of scope.

Her own avatar (user, 2026-10-01: "have gomi recognize her own avatar and have her associate with it"):
a posted picture that's the same as her Discord avatar, even resized or recompressed (fingerprint,
same_picture), isn't described by the model but labelled as hers (avatar_label), so she knows it's her.
Her avatar is a cut-out with a transparent background, which a saved copy fills with anything (white,
black, Discord's theme colour), so it's fingerprinted on each of those (avatar_prints).

This file picks what to look at, prepares the image, and holds the prompt and the labels; bot.py
downloads and calls the model.
"""

import base64
import io
import re

try:
    from PIL import Image
except ImportError:  # requirements not reinstalled since vision came in: bot.py turns vision off and says so
    Image = None

from censor import has_slur
from persona import BOT_NICKNAME

MAX_SIDE = 1024  # pixels; the vision tower works on a fixed token budget, so bigger only costs bandwidth
MAX_DESCRIPTION = 160
IMAGE_TYPES = ("image/png", "image/jpeg", "image/webp", "image/gif")
PREVIEW_TYPES = ("image", "gifv", "video", "article", "link", "rich")
# Of the 64 bits of a fingerprint: a repost of a picture, resized or recompressed, differs in a few; a
# different picture, even a similar one, in a lot more.
SAME_PICTURE_BITS = 12
WHITE = (255, 255, 255)
# What a copy of a see-through picture ends up on: white, black, Discord's dark and light themes
BACKGROUNDS = (WHITE, (0, 0, 0), (49, 51, 56), (242, 243, 245))


def sources(message) -> list[tuple[tuple[str, int], str, str, str]]:
    """What in a message she can look at: ((kind, index), url, what it is for the prompt, label kind)."""
    found = []
    for i, attachment in enumerate(message.attachments):
        content_type = (attachment.content_type or "").split(";")[0].lower()
        if content_type in IMAGE_TYPES:
            gif = content_type == "image/gif"
            found.append((("attachment", i), attachment.url, "GIF (its first frame)" if gif else "picture",
                          "gif" if gif else "image"))
    for i, sticker in enumerate(message.stickers):
        if getattr(getattr(sticker, "format", None), "name", "") != "lottie":
            found.append((("sticker", i), sticker.url, f'sticker called "{sticker.name}"', "sticker"))
    for i, embed in enumerate(getattr(message, "embeds", [])):
        picture = getattr(embed.thumbnail, "proxy_url", None) or getattr(embed.image, "proxy_url", None)
        if embed.type in PREVIEW_TYPES and picture:
            title = f' for "{embed.title}"' if embed.title else ""
            what = {"gifv": "GIF (its first frame)", "image": "picture"}.get(embed.type, f"link preview image{title}")
            found.append((("embed", i), picture, what, {"gifv": "gif", "image": "image"}.get(embed.type, "link")))
    return found


def _flat(data: bytes, background: tuple[int, int, int] = WHITE):
    """The picture's first frame as RGB, transparency on the background (white); None if it isn't one
    Pillow can read."""
    if Image is None:
        return None
    try:
        with Image.open(io.BytesIO(data)) as image:
            image.seek(0)
            frame = image.convert("RGBA")
    except Exception:  # not a picture Pillow can read, or a decompression bomb
        return None
    flat = Image.new("RGB", frame.size, background)
    flat.paste(frame, mask=frame.getchannel("A"))
    return flat


def jpeg_b64(data: bytes) -> str | None:
    """The picture as base64 JPEG for Ollama: first frame, transparency on white, at most MAX_SIDE."""
    if (flat := _flat(data)) is None:
        return None
    flat.thumbnail((MAX_SIDE, MAX_SIDE))
    out = io.BytesIO()
    flat.save(out, "JPEG", quality=85)
    return base64.b64encode(out.getvalue()).decode()


def fingerprint(data: bytes, background: tuple[int, int, int] = WHITE) -> int | None:
    """A 64-bit difference hash: the picture shrunk to 9x8 in grey, one bit per pair of neighbouring pixels
    (is the left one brighter). Resizing or recompressing a picture barely changes it."""
    if (flat := _flat(data, background)) is None:
        return None
    pixels = flat.convert("L").resize((9, 8), Image.Resampling.LANCZOS).tobytes()
    bits = 0
    for row in range(8):
        for col in range(8):
            bits = bits << 1 | (pixels[row * 9 + col] > pixels[row * 9 + col + 1])
    return bits


def avatar_prints(data: bytes) -> set[int]:
    """Her avatar's fingerprints, on each background a copy of it might have."""
    return {bits for background in BACKGROUNDS if (bits := fingerprint(data, background)) is not None}


def same_picture(bits: int | None, known: set[int]) -> bool:
    """Whether a picture's fingerprint is (nearly) one of these."""
    return bits is not None and any(bin(bits ^ other).count("1") <= SAME_PICTURE_BITS for other in known)


def avatar_label(description: str | None) -> str:
    """What her own avatar, posted by someone, reads as in her chat log (inside the [image: ...] label)."""
    return f"{BOT_NICKNAME}'s own avatar" + (f", {description}" if description else "")


def describe_messages(what: str, image: str) -> list[dict]:
    return [
        {"role": "system", "content": "You describe what people post in a small Discord server of friends, for "
                                      "Gomi, a bot there, so she knows what they shared. Plain and short. Never "
                                      "guess who a real person in a photo is."},
        {"role": "user", "content": f"Describe this {what} in one short line, under 20 words: what's in it, and any "
                                    "text written on it. If it's a meme or a reaction image, say so. Just the "
                                    "description.",
         "images": [image]},
    ]


def clean_description(text: str) -> str | None:
    """One line, no brackets (they'd end the label), no slur (then no description at all)."""
    line = next((ln for ln in text.splitlines() if ln.strip()), "")
    line = re.sub(r"[\[\]]", "", " ".join(line.split())).strip(" \"'")
    if not line or has_slur(line):
        return None
    return line[:MAX_DESCRIPTION]


def label(kind: str, description: str | None, name: str = "", title: str = "") -> str:
    """How a piece of media reads in her chat log, described or not."""
    if kind == "sticker":
        return f"[sticker: {name}, {description}]" if description else f"[sticker: {name}]"
    if kind == "link":
        title = re.sub(r"[\[\]\"]", "", " ".join(title.split()))[:100]  # a link's title comes from the site
        title = f'"{title}"' if title and not has_slur(title) else ""
        parts = [p for p in (title, f"preview: {description}" if description else "") if p]
        return f"[link: {', '.join(parts)}]" if parts else ""
    return f"[{kind}: {description}]" if description else f"[{kind}]"


def embed_label(embed, description: str | None) -> str:
    """A link preview in her chat log: a GIF or picture link as the picture, anything else as its title
    and what its preview shows. Nothing for embeds that aren't link previews."""
    if embed.type not in PREVIEW_TYPES:
        return ""
    kind = {"gifv": "gif", "image": "image"}.get(embed.type, "link")
    if kind != "link":
        return label(kind, description) if description else ""
    return label("link", description, title=embed.title or "")
