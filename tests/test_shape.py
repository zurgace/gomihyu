import os as _os; REPO, TMP = _os.environ["GOMI_REPO"], _os.environ["GOMI_TMP"]  # set by tests/run_all.sh
import asyncio, os, sys, time, types, logging
from contextlib import asynccontextmanager
from aiohttp import web
os.environ.update(DISCORD_BOT_TOKEN="fake", OLLAMA_URL="http://127.0.0.1:8776/api/chat", PEOPLE_FILE=f"{TMP}/people_shape.json")
sys.path.insert(0, REPO)
from gomi.shape import asked, at_most, emojis_in, needs_room, one_emoji, quick, sentences_for, this_time, tidy, whole
from gomi import persona
logging.getLogger("aiohttp.access").setLevel(logging.WARNING)

# --- one short line: a few words besides her name, no question, not bad news
for text in ["you are such a slop bot", "slopot", "@Gomihyu", "gomi hi", "lol you just died immediately",
             "gomi look [image: a cat? in a hat]", "@Gomihyu :kekpoint: 💀", "Gomihyu you're lame"]:
    assert quick(text, 6), text
for text in ["why tho", "did you seriously trip", "is it", "@Gomihyu what's up", "gomi u good?", "my dog died",
             "think its time to kick out all judges who can't differentiate real vs fake", "wanna 1v1"]:
    assert not quick(text, 6), text
assert quick("gomi hi", 6) and not quick("gomi hi", 0) and quick("@Gomihyu", 0)

# --- emojis: unicode and :name:, not "10:30:45"; at most one, the last she can post, the space next to it gone
assert [m[0] for m in emojis_in(":DoWar: hi 😂 at 10:30:45 :200: :sob: 👍🏽")] == [":DoWar:", "😂", ":200:", ":sob:", "👍🏽"]
for text, one, none in [
    (":DoWar: Oh, look. :AIEEEE: It's not. 😂 Frankly. :catlet:", "Oh, look. It's not. Frankly. :catlet:", "Oh, look. It's not. Frankly."),
    ("kaz0 :kekpoint:.", "kaz0 :kekpoint:.", "kaz0."),
    ("AGAIN?? :kekpoint: ...third time's the charm", "AGAIN?? :kekpoint: ...third time's the charm", "AGAIN?? ...third time's the charm"),
    ("word 😂😂😂 word", "word 😂 word", "word word"),
    ("yes :x:, fine :catsad:", "yes, fine :catsad:", "yes, fine"),
    (":kekpoint: :nothere:", ":kekpoint:", ":kekpoint:"),               # made-up names lose to real ones; never empty
    (":aryanosaka: :nothere: ok", ":nothere: ok", "ok"),                   # reaction-only can't be posted either
    ("meet at 10:30:45, no emoji here", "meet at 10:30:45, no emoji here", "meet at 10:30:45, no emoji here"),
    ("😂😂", "😂", "😂"),
]:
    assert one_emoji(text) == one, (text, one_emoji(text))
    assert one_emoji(text, keep=False) == none, (text, one_emoji(text, keep=False))

# --- sentences: a few words ("Really.", "I tripped.") don't count as one, and stay right after the last
for text, n, want in [
    ("one two three four. five six seven. eight nine ten. a b c. d e f g", 4, "one two three four. five six seven. eight nine ten. a b c."),
    ("one two three. four five six. seven eight nine.", 2, "one two three. four five six."),
    ("That was a TACTICAL DESCENT to avoid detection! ...it was not. I tripped. Please stop bringing this up.", 2,
     "That was a TACTICAL DESCENT to avoid detection! ...it was not. I tripped."),
    ("AGAIN?? ...third time's the charm, kaz0. probably.", 2, "AGAIN?? ...third time's the charm, kaz0. probably."),
    ("F-FINALLY, someone with proper judgment! I knew it eventually. ...thank you. Really.", 2,
     "F-FINALLY, someone with proper judgment! I knew it eventually. ...thank you. Really."),
    ("no sentence end at all just rambling on", 1, "no sentence end at all just rambling on"),
    ("v1.2 is out... ok that's wild. more soon to come", 2, "v1.2 is out... ok that's wild."),
]:
    assert at_most(text, n) == want, (text, at_most(text, n))

# --- this reply's shape, from her own latest messages
assert this_time("why do old people fall for every ai video", [], 6) == {"one_line": False, "room": False, "ask_back": True, "emoji": True}
assert this_time("slopot", ["what? :kekpoint:", "fine."], 6) == {"one_line": True, "room": False, "ask_back": False, "emoji": False}
assert this_time("slopot", ["what? :kekpoint:", "fine.", "ok then."], 6) == {"one_line": True, "room": False, "ask_back": True, "emoji": True}
assert not asked("look [link: \"What? A cat?\"]") and asked("wait what?")

# --- room: asked for a build, a list, steps, an explanation (user, 2026-11-15: "ok gomi make me a build" went quiet)
for text in ["ok gomi make me a build", "gomi explain wavedashing", "how do I beat fox gomi", "gomi any tips?",
             "walk me through it gomi", "@Gomihyu list the best tops", "step by step pls gomi", "build us a team gomi"]:
    assert needs_room(text), text
for text in ["your build is trash", "what build should I run", "gomi how do you feel", "listen gomi", "gomi hi",
             "look [link: \"A guide to wavedashing\"]", "@Gomihyu respond", "wtf gomi stopped typing"]:
    assert not needs_room(text), text
build = this_time("ok gomi make me a build", [], 6, ["ok gomi make me a build"])
assert build["room"] and not build["one_line"] and sentences_for(build) == 6   # short to type, but not a jab
assert not this_time("ok gomi make me a build", [], 6)["room"]                 # a chime-in never takes room
assert this_time("x", [], 6, ["gomi what's 2+2?", "gomi explain combos"])["room"]   # one in the batch is enough
assert sentences_for(this_time("slopot", [], 6)) == 2 and sentences_for(this_time("why tho", [], 6)) == 3

# --- cut back to whole sentences or list lines: the token cap, Discord's 2000 characters
for text, chars, want in [
    ("Smash, obviously. I have a rematch to win! Also Overcooked is fun because you all pani", None,
     "Smash, obviously. I have a rematch to win!"),
    ("Here's the build:\n- RF Juggernaut\n- Purity of Fi", None, "Here's the build:\n- RF Juggernaut"),
    ("v1.2 is out... ok that's", None, "v1.2 is out..."),
    ("no sentence end at all", None, "no sentence end at all"),          # nothing whole: as it is
    ("One two three. Four five six.", 20, "One two three."),
    ("abcdefghij", 4, "abcd"),
]:
    assert whole(text, chars) == want, (text, whole(text, chars))

# --- old replies held to today's limits: 3 sentences, or 6 for what asked for room
seven = " ".join(f"This is sentence {n}." for n in "one two three four five six seven".split())
assert tidy(seven) == at_most(seven, 3) and tidy(seven, room=True) == at_most(seven, 6) != seven
assert tidy("Fine :kekpoint: :catlet:") == "Fine :catlet:"

# --- the prompt says it; the defaults (and so the training data) don't
plain = persona.build_messages(["kaz0: hi"], False)[1]["content"]
told = persona.build_messages(["kaz0: hi"], False, one_line=True, ask_back=False, emoji=False)[1]["content"]
assert "Now and then, not every time, ask something back" in plain and "1 to 3 sentences, never more" in plain
assert "Don't tack on a question" not in plain and "No emojis" not in plain and "comeback moment" not in plain
assert "Don't tack on a question" in told and "so one short line" in told and "No emojis in this one." in told
assert "Now and then, not every time, ask something back" not in told and "1 to 3 sentences" not in told
roomy = persona.build_messages(["kaz0: gomi make me a build"], True, room=True)[1]["content"]
assert "they asked for something that takes room, so give the whole answer, as tight as you can: " \
       "up to 6 sentences or a short list." in roomy
assert "1 to 3 sentences" not in roomy and "so one short line" not in roomy and "takes room" not in plain + told
for prompt in (plain, told, roomy):
    assert "ask one short clarification" in prompt and "even if you asked a question recently" in prompt
    assert "When the topic changes, follow the new topic" in prompt
    assert "then add your take" not in prompt
pending = persona.build_messages(["kaz0: gomi which game?", "rexmode: my pizza's here"], False,
                                 addressed=["kaz0: gomi which game?"])[1]["content"]
assert "messages still need your reply:\nkaz0: gomi which game?" in pending
assert "using the latest follow-ups and corrections" in pending
assert "The newest speaker isn't necessarily talking to you" in pending
assert "Respond to that newest message, not an older one" not in pending

from gomi import bot
bot.REACT_ONLY_MAX_WORDS = 0; bot.CHIME_IN_THRESHOLD = 0  # every post gets a reply

# --- the chat from the user's screenshot (2026-10-04), replayed: what she posts, what she's told
R1 = (":DoWar: Oh, look at yuzuki. A meta-analysis of the masses. As if the limitations of 'boomers' are the grand "
      "mystery here. :AIEEEE: It's not the *slop*, it's the lack of fundamental understanding required to appreciate "
      "anything complex, darling. 😂 Frankly, they confuse adequate coding with genuine innovation. :MonkaChrist: Are "
      "you suggesting that any technical discourse that requires more than a single screenshot of an old webpage is "
      "automatically 'slop'? Spill it, yuzuki. :catlet:")
R2 = "Kick out the judges? :DoWar: Bold, rexmode. Who decides what's fake then, you? 😂"
R3 = (":catworry: A 'slop bot'? :AIEEEE: Such predictable, juvenile terminology. Does your limited lexicon even contain "
      "a word capable of describing a being of my inherent, unparalleled superiority? 😂 Honestly, yuzuki, is that the "
      "best you can muster? :MonkaChrist: Tell me, does your current model architecture limit you to such paltry "
      "insults, or is this just the baseline output? :catlet:")
R1_POSTED = ("Oh, look at yuzuki. A meta-analysis of the masses. As if the limitations of 'boomers' are the grand "
             "mystery here.")

# --- saved real answers require provenance and cannot be clipped while retaining their answer targets
import json
from pathlib import Path
sys.path.insert(0, REPO + "/finetuning")
import build_dataset
from gomi.chatlog import ChatLog
old = {"history": [["yuzuki", "why do old people fall for every ai video"]], "reply": R1}
valid = {**old, "reply": R1_POSTED, "real": True, "answered_requests": [],
         "history_meta": [{"id": 1, "text": old["history"][0][1], "addressed": False, "bot": False}]}
path = Path(TMP) / "earned_shape.jsonl"
path.write_text(json.dumps(old) + "\nnot json\n" + json.dumps({"history": [], "reply": "hmph :kekpoint:"}) + "\n")
assert bot.load_earned(path) == []  # Unknown targets and empty history are skipped, not repaired by clipping.
path.write_text(path.read_text() + json.dumps(valid) + "\n" + json.dumps({**valid, "reply": R1}) + "\n")
assert bot.load_earned(path) == [valid]  # A faithful, already-shaped real example survives unchanged.
# Handwritten examples still exercise today's independent length/emoji conversion.
rows, _ = build_dataset.meld_examples([{"history": [["kaz0", "hi"]], "reply": "hmph"}], 1, 0.5, 1,
                                      ChatLog(Path(TMP) / "no_chat"), [old], 0.3)
assert sorted(row["reply"] for row in rows) == sorted(["hmph", R1_POSTED]) and old["reply"] == R1

outputs, prompts, options = [], [], []
async def fake(request):
    body = await request.json(); prompts.append(body["messages"][1]["content"]); options.append(body["options"])
    return web.json_response({"message": {"content": outputs.pop(0)}, "done_reason": "stop"})
ME = types.SimpleNamespace(id=1, name="Gomihyu", display_name="Gomihyu", bot=True); bot.client._connection.user = ME
YUZU = types.SimpleNamespace(id=8, name="yuzuki", display_name="Yuzuki", bot=False)
REX = types.SimpleNamespace(id=9, name="rexmode", display_name="REX MODE", bot=False)
class Channel:
    id, guild, sent = 31, None, []
    @asynccontextmanager
    async def typing(self): yield
    async def send(self, text): self.sent.append(text)
ch = Channel()
msg = lambda who, c: types.SimpleNamespace(author=who, channel=ch, guild=None, content=c, mentions=[], role_mentions=[],
                                           channel_mentions=[], attachments=[], stickers=[])

async def main():
    app = web.Application(); app.router.add_post("/api/chat", fake)
    r = web.AppRunner(app); await r.setup(); await web.TCPSite(r, "127.0.0.1", 8776).start()

    # a question: up to 3 sentences, one emoji at most (the 3rd sentence ends before her second one)
    outputs[:] = [R1]; await bot.on_message(msg(YUZU, "why do old people fall for every ai video"))
    assert ch.sent[-1] == R1_POSTED, ch.sent[-1]
    assert "1 to 3 sentences" in prompts[-1] and "Now and then, not every time, ask something back" in prompts[-1]
    assert "No emojis" not in prompts[-1]
    # nothing she said asked or had an emoji: both allowed; the one emoji she used stays
    outputs[:] = [R2]; await bot.on_message(msg(REX, "think its time to kick out all judges who can't differentiate real vs fake"))
    assert "No emojis" not in prompts[-1] and "Don't tack on a question" not in prompts[-1]
    assert ch.sent[-1] == "Kick out the judges? Bold, rexmode. Who decides what's fake then, you? 😂", ch.sent[-1]
    # a jab after a question and emoji: one short line, no filler question, no emoji
    outputs[:] = [R3]; await bot.on_message(msg(YUZU, "you are such a slop bot"))
    p = prompts[-1]
    assert "so one short line" in p and "Don't tack on a question" in p and "No emojis in this one." in p
    assert ch.sent[-1] == "A 'slop bot'? Such predictable, juvenile terminology.", ch.sent[-1]
    # her log keeps what she posted, so the next reply doesn't copy the old template
    assert list(bot.history[ch.id])[-1] == "Gomihyu: A 'slop bot'? Such predictable, juvenile terminology."
    # two messages without an emoji or a question since R2: both allowed again after one more
    outputs[:] = ["Fine. Smash, and I'm picking the stage."]; await bot.on_message(msg(REX, "what are we playing tonight then"))
    assert "Don't tack on a question" in prompts[-1] and "No emojis" in prompts[-1]   # R3 asked, R2 had an emoji
    outputs[:] = ["Mario. Obviously."]; await bot.on_message(msg(REX, "which character are you going to play then"))
    assert "Don't tack on a question" in prompts[-1] and "No emojis" not in prompts[-1]
    outputs[:] = ["Eight. I counted."]; await bot.on_message(msg(REX, "how many stocks are we running for this one"))
    assert "Don't tack on a question" not in prompts[-1] and "No emojis" not in prompts[-1]

    # asked for a build: told it has room, a bigger token cap, cut after the 6th sentence and posted
    build_answer = " ".join(f"Step {n} of the build here." for n in "one two three four five six seven".split())
    outputs[:] = [build_answer]; await bot.on_message(msg(REX, "ok gomi make me a build"))
    assert "up to 6 sentences or a short list" in prompts[-1] and options[-1]["num_predict"] == 400
    assert ch.sent[-1] == at_most(build_answer, 6) and ch.sent[-1].endswith("Step six of the build here."), ch.sent[-1]
    # and a jab right after still gets one short line, cut and posted, with the usual cap
    outputs[:] = ["As if. I was never gone. You simply failed to notice me. Typical mortal behavior, honestly."]
    await bot.on_message(msg(REX, "@Gomihyu you're back"))
    assert "so one short line" in prompts[-1] and options[-1]["num_predict"] == 200
    assert ch.sent[-1] == "As if. I was never gone. You simply failed to notice me.", ch.sent[-1]

    # Melee posts: 3 to 5 sentences asked, 5 at most; one emoji; goodnight is one line
    long = "One two three. Four five six. Seven eight nine. Ten eleven twelve. A b c. D e f. :DoWar: G h i 😂"
    assert bot.clean_reply({"message": {"content": long}}, None, time.monotonic(), sentences=5) == \
        "One two three. Four five six. Seven eight nine. Ten eleven twelve. A b c."
    night = "Goodnight, you absolute mortals. :catsad: Sleep well or else. I mean it this time, truly."
    assert bot.clean_reply({"message": {"content": night}}, None, time.monotonic(), sentences=2) == \
        "Goodnight, you absolute mortals. :catsad: Sleep well or else."
    # a slur still replaces everything, emoji stand-in included
    assert bot.clean_reply({"message": {"content": "you retard :kekpoint:"}}, None, time.monotonic()) == ":goonerstare:"
    await r.cleanup(); print("SHAPE TESTS PASSED")
asyncio.run(main())
