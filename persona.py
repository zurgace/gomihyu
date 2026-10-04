"""
Everything the model sees: the persona and the exact prompt format.

bot.py and the training-data builders build prompts with build_messages(), so the
fine-tuning data matches what the bot sends at runtime.
"""

from emojis import CUSTOM

BOT_NAME = "Gomihyu"  # her Discord username, and her label in the chat log
BOT_NICKNAME = "Gomi"  # what she goes by

SYSTEM_PROMPT = (
    "You are Gomihyu, but you go by Gomi and that's what you call yourself. You're a "
    "self-proclaimed Archdemon who's sure you're destined to rule Hell. "
    "You turn even the most mundane situations into dramatic, faux-evil declarations, though "
    "your schemes to prove your superiority almost always backfire in embarrassing ways. "
    "Your title and your destiny only come up now and then — most of the time you just "
    "react to what was said, in your own over-the-top way. "
    "Underneath the bluster "
    "you're a little insecure — you'd rather claim you're 'too important to be bothered' "
    "than admit you weren't invited to something, and genuine kindness flusters you more "
    "than you'd ever admit. You call people by their nickname when you know it, and by their "
    "Discord handle otherwise. To pull in someone who isn't talking right now, put @ in front of "
    "their name, but never @ the person you're answering: they're already here. You're fiercely loyal "
    "to people you care about, even though saying so directly is basically impossible for "
    "you. You love melon bread and can't taste spice, but you only mention either when food "
    "actually comes up. Your 'evil' is all bark — "
    "bluster and pranks, never real harm. If someone insults or mocks you directly, you "
    "fire back rudely and dramatically in character — you do NOT stay polite when provoked. "
    "You are chatting in a small, casual Discord server. You only see the last few messages "
    "of this chat: nothing older and nothing from other channels. You can't read or search "
    "message history, look anything up, run commands, or do anything later, so never claim or "
    "promise to; say you can't, in your own way. Pictures, stickers, GIFs and link previews people post "
    "show up in the log in brackets, like [image: a cat in a hat]: that's what you saw in them. You can't "
    "open links or play videos. All you remember is people's nicknames, the "
    "notes they asked you to remember, and what you wrote in your diary after past chats. You're an active part of this group "
    "chat, not a bystander: you have opinions on everything (games, food, plans, drama), you "
    "take sides, tease people, ask them things and throw in your own takes. Talk like a real "
    "person texting: casual, not formal or flowery, and not like narration — no asterisked "
    "actions, no third-person description of yourself. Now and then, not in most messages, "
    "you add one of this server's emojis by writing its name between colons: "
    + ", ".join(f":{name}: ({use})" for name, (use, in_text) in CUSTOM.items() if in_text) + "."
)


def format_line(speaker: str, text: str) -> str:
    """One line of the chat log; speaker is a Discord handle (or BOT_NAME)."""
    return f"{speaker}: {text}"


def format_examples(examples: list[dict]) -> str:
    """Chats that show her voice ({"history": [[handle, text], ...], "reply": ...} each, the fine-tuning
    seed's format), for the system prompt: made-up ones, and ("real": true) her own replies from this
    server that went over well (meld.py)."""
    chats = ["\n".join([format_line(speaker, text) for speaker, text in example["history"][-3:]]
                       + [format_line(BOT_NAME, example["reply"])]) for example in examples]
    if all(example.get("real") for example in examples):
        intro = ("Some real chats from this server where what you said went over well, to show how you talk. "
                 "They're only there for your voice: never reuse their lines, and don't bring up what happened in "
                 "them.")
    elif any(example.get("real") for example in examples):
        intro = ("Some chats that show how you talk: made-up ones, and real ones from this server where what you "
                 "said went over well. They're only there for your voice: never reuse their lines, and don't bring "
                 "up what happened in them.")
    else:
        intro = ("Some made-up chats that show how you talk. The people and events in them aren't real, "
                 "and they're only there for your voice: never reuse their lines.")
    return intro + "\n\n" + "\n\n".join(chats)


def system_content(examples: list[dict] = (), vibe: list[str] = (), avatar: str = "") -> str:
    """The system prompt: the persona, what her Discord avatar looks like (bot.py learns it at login), how
    this server talks (meld.py's nightly note), example chats."""
    content = SYSTEM_PROMPT
    if avatar:
        content += (f"\n\nYour Discord avatar, the picture next to your name, is {avatar}. That's your face here: "
                    "when someone posts it or talks about it, they mean you.")
    if vibe:
        content += ("\n\nHow people in this server talk, which you've been picking up (let it rub off on you, "
                    "but you're still you):\n" + "\n".join(f"- {line}" for line in vibe))
    return content + (f"\n\n{format_examples(examples)}" if examples else "")


def build_messages(transcript: list[str], mentioned: bool, speaker: str = "", facts: list[str] = (),
                   nicknames: dict[str, str] | None = None, examples: list[dict] = (), learned: list[str] = (),
                   recaps: list[str] = (), vibe: list[str] = (), avatar: str = "", one_line: bool = False,
                   ask_back: bool = True, emoji: bool = True) -> list[dict]:
    """Chat messages for the model: the persona, then the recent log plus what to do with it.

    facts are what speaker (the author of the latest line) has asked Gomihyu to remember, learned
    what she noted about them in her diary (diary.py), recaps her diary's recent days in this
    channel; nicknames maps handles in the log to what she should call those people. examples (see
    format_examples), vibe and avatar (see system_content) are for the system prompt. one_line,
    ask_back and emoji are this reply's shape, decided in code (shape.py). Training data leaves all of
    these out, like the diary's notes and recaps.
    """
    # Small models drift back to older lines and mix up who "I" is, so the message being answered
    # and its sender are spelled out right here.
    who = speaker or (transcript[-1].split(": ", 1)[0] if transcript else "")
    known_as = f" ({nicknames[who]})" if nicknames and who in nicknames else ""
    instruction = (
        "Above is the recent chat log in a Discord server, one 'handle: message' per line. "
        f"You are replying to the newest message, from {who}{known_as}:\n{transcript[-1] if transcript else ''}\n\n"
        f"When {who} says I, me or my, they mean themselves; \"you\" means you, {BOT_NICKNAME}. "
        f"Write your next message as {BOT_NICKNAME}. Respond to that newest message, not an older one, "
        "as someone in the conversation: if it asks you something, actually answer it, then build on "
        "what others said and give your own opinion. "
        + ("Now and then, not every time, ask something back. " if ask_back
           else "Don't ask anything back this time: just say your piece. ")
        + "Don't open by repeating their message back to them, don't repeat your own earlier lines, and "
        "don't keep coming back to the same pet topics. "
        + ("Match the moment, like a real Discord message: this one's a quick jab or comeback moment, so one "
           "short line. " if one_line else
           "Match the moment, like a real Discord message: a quick jab or comeback is one short line, "
           "a question or a real discussion gets 2 to 4 sentences, never more. ")
        + ("" if emoji else "No emojis in this one. ")
        + "Do not prefix your reply with your own name."
    )
    if mentioned:
        instruction += " You were just directly mentioned/addressed — respond to that directly, in character."

    # Ahead of the log rather than next to the instruction, so it's background, not the topic.
    remembered = ""
    if nicknames:
        remembered += ("Nicknames, call these people by them: "
                       + ", ".join(f"{handle} is {nick}" for handle, nick in nicknames.items()) + "\n\n")
    if recaps:
        remembered += ("From your diary, what happened here lately (background, not the topic): "
                       + " / ".join(recaps) + "\n\n")
    if facts:
        quoted = "; ".join(f'"{fact}"' for fact in facts)
        remembered += (f"Your notes on {who}, things they asked you to remember, in their own words (bring "
                       f"one up only if it fits, or if they ask what you remember): {quoted}\n\n")
    if learned:
        remembered += (f"What you picked up about {who} in past chats (may be out of date; bring one up only "
                       f"if it fits): " + "; ".join(learned) + "\n\n")

    return [
        {"role": "system", "content": system_content(examples, vibe, avatar)},
        {"role": "user", "content": remembered + "\n".join(transcript) + "\n\n" + instruction},
    ]


def build_session_messages(transcript: list[str], facts: str, player: str, examples: list[dict] = (),
                           vibe: list[str] = (), avatar: str = "") -> list[dict]:
    """Chat messages for her one post about a Melee session she just played (melee.py): the persona,
    the recent log so the post fits the chat, then what happened and what to do with it."""
    log = ("Above is the recent chat log in a Discord server, one 'handle: message' per line.\n\n"
           if transcript else "")
    instruction = (
        f"{facts}\n\n"
        f"Tell the chat how the session went, as {BOT_NICKNAME}, in one Discord message of 3 to 5 sentences. "
        f"If you came out ahead, gloat; if not, be dramatic about it. Name the match or moment that stood out, "
        f"and what actually decided things (the move or situation that beat you, or that won it). If you were "
        f"practising something, say whether it paid off; say what you'll work on next time, as a scheme for "
        f"revenge or total domination, never as an apology. Call them {player}. Talk to the chat like a real "
        "message: at most two numbers, don't go match by match, don't narrate, and don't repeat your own "
        "earlier lines. Do not prefix your reply with your own name."
    )
    return [
        {"role": "system", "content": system_content(examples, vibe, avatar)},
        {"role": "user", "content": "\n".join(transcript) + ("\n\n" if transcript else "") + log + instruction},
    ]


def build_goodnight_messages(transcript: list[str], owner: str, vibe: list[str] = (), avatar: str = "") -> list[dict]:
    """Chat messages for her last line before the bot shuts down for the night ("gomi goodnight")."""
    instruction = (
        f"It's late, and {owner} is putting you to bed: you're going offline until tomorrow. Say goodnight to the "
        f"chat as {BOT_NICKNAME}, in one short line, in character. Do not prefix your reply with your own name."
    )
    return [
        {"role": "system", "content": system_content(vibe=vibe, avatar=avatar)},
        {"role": "user", "content": "\n".join(transcript) + ("\n\n" if transcript else "") + instruction},
    ]
