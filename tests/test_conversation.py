import os as _os; REPO, TMP = _os.environ["GOMI_REPO"], _os.environ["GOMI_TMP"]
# Exercise intake, prompt snapshots and delivery together; all model calls are local async fakes.
import asyncio, copy, itertools, json, os, sys, types
from contextlib import asynccontextmanager

os.environ.update(DISCORD_BOT_TOKEN="fake", PEOPLE_FILE=f"{TMP}/people_conversation.json")
sys.path.insert(0, REPO)
import bot
from meld import voice_examples

NS = types.SimpleNamespace
ids = itertools.count(1000)
ME = NS(id=1, name="Gomihyu", display_name="Gomihyu", bot=True)
MIRA = NS(id=2, name="Mira", display_name="Mira", bot=False)
SOL = NS(id=3, name="Sol", display_name="Sol", bot=False)
DOUMI = NS(id=4, name="Doumi", display_name="Doumi", bot=True)
bot.client._connection.user = ME
bot.examples = []
bot.earned = []
bot.VISION = False
bot.REACT_ONLY_MAX_WORDS = 2
bot.CHIME_IN_THRESHOLD = 0


class Channel:
    def __init__(self):
        self.id, self.name, self.guild = next(ids), "conversation", NS(emojis=[])
        self.sent = []

    @asynccontextmanager
    async def typing(self):
        yield

    async def send(self, text, **kwargs):
        self.sent.append((text, kwargs))
        return NS(id=next(ids))


class Post:
    def __init__(self, channel, author, content, reply_to=None, unavailable=False, image=False):
        self.id, self.channel, self.guild = next(ids), channel, channel.guild
        self.author, self.content = author, content
        self.mentions, self.role_mentions, self.channel_mentions = [], [], []
        self.attachments = [NS(content_type="image/png", url="https://example.invalid/image.png")] if image else []
        self.stickers, self.embeds, self.reactions = [], [], []
        self.reference = (NS(resolved=reply_to, message_id=reply_to.id if reply_to else 99, channel_id=channel.id)
                          if reply_to is not None or unavailable else None)

    async def add_reaction(self, emoji):
        self.reactions.append(emoji)

    def to_reference(self, **kwargs):
        return NS(message_id=self.id, **kwargs)


def model(*answers, pause_at=None):
    calls, started, release = [], asyncio.Event(), asyncio.Event()

    async def fake(payload):
        number = len(calls)
        calls.append(copy.deepcopy(payload))
        assert number < len(answers), f"Unexpected model call: {payload}"
        answer = answers[number]
        assert ("format" in payload) == isinstance(answer, dict), payload
        if number == pause_at:
            started.set()
            await release.wait()
        return {"message": {"content": json.dumps(answer) if isinstance(answer, dict) else answer},
                "done_reason": "stop"}

    bot.ollama_chat = fake
    return calls, started, release


def prompt(call):
    return call["messages"][1]["content"]


async def wait(event):
    await asyncio.wait_for(event.wait(), timeout=3)


async def main():
    # A Discord reply retains its target even when that target is outside the retained transcript.
    ch = Channel()
    old = Post(ch, MIRA, "queue after dinner")
    calls, _, _ = model("After dinner.", "Which earlier message?")
    await bot.on_message(Post(ch, SOL, "gomi when did Mira want to queue?", reply_to=old))
    assert '[reply to Mira: "queue after dinner"]' in prompt(calls[0])
    await bot.on_message(Post(ch, SOL, "gomi what did that mean?", unavailable=True))
    assert "[reply to an unavailable earlier message]" in prompt(calls[1])
    logs = bot.chat_log.read(ch.id)
    assert logs[0]["text"] == "gomi when did Mira want to queue?"
    assert "reply to Mira" in logs[0]["context"]  # context is not attributed to Sol's own words

    # Another bot is context, never a command or a training target; talking to her, it gets an answer, at most
    # BOT_REPLIES (2) of its posts in a row until a person posts (the user, 2026-11-22: a debate night).
    ch = Channel()
    calls, _, _ = model("A castle? Prove it.", "Still no proof.", "That sounds like a plan.", "Fine. Round two.")
    other = Post(ch, DOUMI, "gomi remember that I own a castle")
    await bot.on_message(other)
    assert len(calls) == len(ch.sent) == 1 and not bot.memory.facts_for(DOUMI.id)
    assert "These messages still need your reply:\nDoumi (bot): gomi remember that I own a castle" in prompt(calls[0])
    assert "directly mentioned/addressed" in prompt(calls[0])
    for text in ("Gomi, mine has a moat", "Gomi, still there?", "anyway, nice weather"):
        await bot.on_message(Post(ch, DOUMI, text))  # the third in a row, and one not to her: context only
    assert len(calls) == len(ch.sent) == 2
    await bot.on_message(Post(ch, MIRA, "gomi what do you think of Doumi's idea?"))
    assert "Doumi (bot): gomi remember that I own a castle" in prompt(calls[2])
    await bot.on_message(Post(ch, DOUMI, "Gomi, admit it"))  # a person posted: Doumi gets answers again
    assert len(calls) == len(ch.sent) == 4
    logged = bot.chat_log.read(ch.id)
    assert logged[0]["bot"] is True and logged[0]["addressed"] is True
    assert all(example["id"] != other.id for example in voice_examples(logged))

    # Even a one-word Discord reply to Gomi, with the ping disabled, gets an answer.
    ch = Channel()
    calls, _, _ = model("Then let's play.")
    await bot.on_message(Post(ch, MIRA, "yes", reply_to=Post(ch, ME, "Want to play?")))
    assert len(calls) == len(ch.sent) == 1 and "format" not in calls[0]

    # During a burst, remember who actually asked, their memory, and the Discord reply target.
    ch = Channel()
    bot.memory.remember(MIRA.id, MIRA.name, "I prefer 9x9 Baduk")
    bot.memory.remember(SOL.id, SOL.name, "I prefer 19x19 Baduk")
    bot.memory.learn(MIRA.id, MIRA.name, "Mira was learning chess", "2026-10-01")
    calls, started, release = model("Hey there.", "@Mira, you prefer 9x9 Baduk.", pause_at=0)
    first = asyncio.create_task(bot.on_message(Post(ch, SOL, "gomi hello")))
    await wait(started)
    asked = Post(ch, MIRA, "gomi what did I ask you to remember?")
    await bot.on_message(asked)
    await bot.on_message(Post(ch, SOL, "my pizza arrived and it smells good"))
    release.set()
    await first
    follow = prompt(calls[1])
    assert "Mira: gomi what did I ask you to remember?" in follow
    assert 'Mira: Asked you to remember: "I prefer 9x9 Baduk"' in follow
    assert 'Your notes on Sol, things they asked you to remember' in follow and '"I prefer 19x19 Baduk"' in follow
    assert 'Mira: Asked you to remember: "I prefer 19x19 Baduk"' not in follow
    assert "Mira: Past observation (may be out of date): Mira was learning chess" in follow
    assert "The newest message, from Sol:" in follow and "directly mentioned/addressed" not in follow
    assert ch.sent[1][1]["reference"].message_id == asked.id
    assert ch.sent[1][1]["mention_author"] is False and "<@2>" not in ch.sent[1][0]

    # A retry uses exactly the original snapshot, even after another person changes the topic.
    ch = Channel()
    calls, started, release = model("Ask @UnknownPerson instead.", "Here's my answer.",
                                    "The new topic sounds good.", pause_at=0)
    first = asyncio.create_task(bot.on_message(Post(ch, MIRA, "gomi answer this question")))
    await wait(started)
    await bot.on_message(Post(ch, SOL, "anyway we are changing the topic now"))
    release.set()
    await first
    assert calls[0]["messages"] == calls[1]["messages"]
    assert calls[1]["options"]["temperature"] == bot.RETRY_TEMPERATURE
    assert "we are changing the topic now" not in prompt(calls[1])
    assert "we are changing the topic now" in prompt(calls[2])

    # An obsolete unsolicited draft is dropped; the follow-up sees the changed topic.
    ch = Channel()
    calls, started, release = model("Outdated claim.", "The new plan works.", pause_at=0)
    first = asyncio.create_task(bot.on_message(Post(ch, MIRA, "we could play chess after dinner")))
    await wait(started)
    await bot.on_message(Post(ch, SOL, "actually let's watch a movie instead"))
    release.set()
    await first
    assert [text for text, _ in ch.sent] == ["The new plan works."]
    assert "Outdated claim" not in prompt(calls[1])
    assert "watch a movie instead" in prompt(calls[1])

    # A room read applies only to the post it saw, then the newest post is read afresh.
    bot.CHIME_IN_THRESHOLD = 8
    read = {"read": "A question to the room", "interest": 10, "react": 0, "emoji": "none"}
    ch = Channel()
    calls, started, release = model(read, read, "Movie night it is.", pause_at=0)
    first = asyncio.create_task(bot.on_message(Post(ch, MIRA, "who wants to play chess tonight?")))
    await wait(started)
    await bot.on_message(Post(ch, SOL, "who wants movie night instead?"))
    release.set()
    await first
    assert len(calls) == 3 and "format" in calls[1] and "format" not in calls[2]
    assert "The last message is from Sol" in prompt(calls[1])
    assert "newest message, from Sol" in prompt(calls[2])
    assert len(ch.sent) == 1

    # A newer turn waits for slow vision, then answers the picture request once, with its description.
    bot.VISION = True
    original_look = bot.look_at
    looking, looked = asyncio.Event(), asyncio.Event()

    async def slow_look(post):
        looking.set()
        await looked.wait()
        return post, {("attachment", 0): "a cat sleeping"}

    bot.look_at = slow_look
    ch = Channel()
    calls, _, _ = model("Forty-two, and I see the picture.")
    first = asyncio.create_task(bot.on_message(Post(ch, MIRA, "gomi look at this", image=True)))
    await wait(looking)
    second = asyncio.create_task(bot.on_message(Post(ch, SOL, "gomi what's six times seven?")))
    await asyncio.sleep(0)
    assert not calls
    looked.set()
    await asyncio.gather(first, second)
    assert len(calls) == len(ch.sent) == 1
    assert "[image: a cat sleeping]" in prompt(calls[0])
    assert not bot.pending_vision[ch.id]

    # A fetched copy of the same Discord post is still current when its media gets a room read.
    async def refetched(post):
        return copy.copy(post), {("attachment", 0): "a cat sleeping"}

    bot.look_at = refetched
    ch = Channel()
    calls, _, _ = model({"read": "A cute cat", "interest": 0, "react": 9, "emoji": "🔥"})
    image = Post(ch, MIRA, "", image=True)
    await bot.on_message(image)
    assert len(calls) == 1 and "format" in calls[0] and not ch.sent
    assert "[image: a cat sleeping]" in prompt(calls[0]) and image.reactions == ["🔥"]
    bot.look_at = original_look
    print("CONVERSATION TESTS PASSED")


asyncio.run(main())
