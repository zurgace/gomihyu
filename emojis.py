"""
The emojis Gomihyu uses, and when. Edit freely.

The model never sees the pictures, only the names and the "when" notes, so the notes are what
make her pick the right one. Custom emojis are looked up in the server by name when used; if
one gets renamed or deleted, she simply can't use it until this file matches again.
"""

# Custom server emoji name -> (when to use it, whether she may write it in her messages).
# in_text=False keeps it reaction-only: reaction picks are forced to be one of these names, so
# the name can't leak into what she writes, and her chat prompt only lists in_text ones.
CUSTOM = {
    "kekpoint": ("laughing at someone's fail", True),
    "200": ("something genuinely funny", True),
    "deadge": ("dead chat, someone died in a game, or 'I'm dead'", True),
    "MonkaChrist": ("something cursed or unholy", True),
    "DoWar": ("ready to fight: bets, 1v1s, challenges", True),
    "AIEEE": ("shock or horror", True),
    "AAAaa": ("panic or chaos", True),
    "pleasee": ("begging, or someone begging her", True),
    "extremetired": ("done with this, exhausted", True),
    "Boomer": ("someone says something old or out of touch", True),
    "catworry": ("uh oh, nervous", True),
    "catworry2": ("uh oh, nervous", True),
    "catdespair": ("dramatic 'all is lost'", True),
    "catsad": ("sad or disappointed", True),
    "catlet": ("something small or endearingly pathetic", True),
    "aryanosaka": ("dumbfounded blank stare", False),
    "goonerstare": ("'excuse me??' stare", False),
}

# Plain unicode emojis she can react with (she can type any unicode emoji herself).
UNICODE = {
    "😤": "challenged, competitive",
    "🔥": "hype or impressive",
    "👑": "praise, or anything about her greatness",
    "💢": "annoyed or insulted",
    "🙄": "unimpressed, eye-roll",
    "😈": "scheming or mischief",
    "💅": "smug, unbothered",
    "👀": "noticed something interesting or suspicious",
}

# What she reacts with to posts she can't see (images, videos, stickers): she just looks.
LOOKING = ["👀", "goonerstare"]

# Posted instead of any reply of hers that contains a slur (see censor.py / slurs.txt).
SLUR_STANDIN = "goonerstare"

# Her reaction to sad news ("my dog died"), on top of a reply.
SAD_NEWS = "catsad"
