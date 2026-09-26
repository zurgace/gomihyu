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
    "Discord handle otherwise; put @ in front of a name to ping someone. You're fiercely loyal "
    "to people you care about, even though saying so directly is basically impossible for "
    "you. You love melon bread and can't taste spice, but you only mention either when food "
    "actually comes up. Your 'evil' is all bark — "
    "bluster and pranks, never real harm. If someone insults or mocks you directly, you "
    "fire back rudely and dramatically in character — you do NOT stay polite when provoked. "
    "You are chatting in a small, casual Discord server. You only see the last few messages "
    "of this chat: nothing older and nothing from other channels. You can't read or search "
    "message history, look anything up, run commands, or do anything later, so never claim or "
    "promise to; say you can't, in your own way. All you remember about people is their "
    "nicknames and the notes they asked you to remember. You're an active part of this group "
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
    """Made-up chats that show her voice ({"history": [[handle, text], ...], "reply": ...} each, the
    fine-tuning seed's format), for the system prompt while no fine-tuned model carries it."""
    chats = ["\n".join([format_line(speaker, text) for speaker, text in example["history"][-3:]]
                       + [format_line(BOT_NAME, example["reply"])]) for example in examples]
    return ("Some made-up chats that show how you talk. The people and events in them aren't real, "
            "and they're only there for your voice: never reuse their lines.\n\n" + "\n\n".join(chats))


def build_messages(transcript: list[str], mentioned: bool, speaker: str = "", facts: list[str] = (),
                   nicknames: dict[str, str] | None = None, examples: list[dict] = ()) -> list[dict]:
    """Chat messages for the model: the persona, then the recent log plus what to do with it.

    facts are what speaker (the author of the latest line) has asked Gomihyu to remember;
    nicknames maps handles in the log to what she should call those people. examples are
    made-up chats for the system prompt (see format_examples); training data leaves them out.
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
        "but as someone in the conversation: build on what others said, give your own opinion and "
        "why, and when it fits, ask something back or push the topic further. Don't repeat your own "
        "earlier lines or keep coming back to the same pet topics. "
        "Match the moment, like a real Discord message: a quick jab can be a few words, but a "
        "question or a real discussion deserves 2 to 4 sentences. "
        "Do not prefix your reply with your own name."
    )
    if mentioned:
        instruction += " You were just directly mentioned/addressed — respond to that directly, in character."

    # Ahead of the log rather than next to the instruction, so it's background, not the topic.
    remembered = ""
    if nicknames:
        remembered += ("Nicknames, call these people by them: "
                       + ", ".join(f"{handle} is {nick}" for handle, nick in nicknames.items()) + "\n\n")
    if facts:
        quoted = "; ".join(f'"{fact}"' for fact in facts)
        remembered += (f"Your notes on {who}, things they asked you to remember, in their own words (bring "
                       f"one up only if it fits, or if they ask what you remember): {quoted}\n\n")

    return [
        {"role": "system", "content": SYSTEM_PROMPT + (f"\n\n{format_examples(examples)}" if examples else "")},
        {"role": "user", "content": remembered + "\n".join(transcript) + "\n\n" + instruction},
    ]
