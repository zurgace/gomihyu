"""Synthetic harvest/render regressions; no logs, models, or external services."""
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, os.environ["GOMI_REPO"])
sys.path.insert(0, str(Path(os.environ["GOMI_REPO"]) / "finetuning"))

from chatlog import ChatLog, raw_author_text
from meld import landed_replies, voice_examples
from build_dataset import meld_examples, read_jsonl, render, voice_pool
from persona import SYSTEM_PROMPT, example_targets, format_examples, system_content
from meld import pick_examples


def post(i, author, text, **extra):
    return {"id": i, "time": 1000 + i, "author": author, "text": text,
            "text_provenance": "author", **extra}


def approved(entries):
    reply = entries[-1]
    return entries + [post(reply["id"] + 1, "Sol", "😂", kind="reaction", to=reply["id"])]


# Quoted addressing remains visible context without becoming the raw author's intent.
entries = approved([
    post(1, "Mira", "what about this", addressed=False,
         context='[reply to Sol: "Gomi chose chess"] what about this'),
    post(2, "Gomihyu", "Try the other one.", answered_requests=[]),
])
example, = landed_replies(entries)
assert example["history_meta"][0]["text"] == "what about this"
assert example["history_meta"][0]["addressed"] is False
prompt = render(example)["messages"][1]["content"]
assert '[reply to Sol: "Gomi chose chess"] what about this' in prompt
assert '"you" means you, Gomi.' not in prompt and "directly mentioned/addressed" not in prompt
entries[0].update(text="yes please", addressed=True, context='[reply to Gomihyu: "Want advice?"] yes please')
assert "directly mentioned/addressed" in render(landed_replies(entries)[0])["messages"][1]["content"]
assert 'These messages still need your reply' not in prompt  # Empty answered_requests is unsolicited.

# A delayed answer addresses Mira's arithmetic, with Sol's pizza remaining recent context.
entries = approved([
    post(1, "Mira", "gomi what's two plus two?", addressed=True),
    post(2, "Sol", "my pizza arrived", addressed=False),
    post(3, "Gomihyu", "Four, Mira.", reply_to=1, answered_requests=[1]),
])
example, = landed_replies(entries)
assert example["answered_requests"] == [1]
prompt = render(example)["messages"][1]["content"]
assert "messages still need your reply:\nMira: gomi what's two plus two?" in prompt
assert "The newest message, from Sol:\nSol: my pizza arrived" in prompt
assert "You are replying to the newest message" not in prompt
fewshot = format_examples([example])
assert "[Answering these messages: Mira: gomi what's two plus two?]" in fewshot
assert fewshot.endswith("Gomihyu: Four, Mira.")
assert example_targets(example) == [0]
# A mixed batch includes its newest selected source as well as older ones in the instruction.
batched = approved([
    post(1, "Mira", "gomi what's two plus two?", addressed=True),
    post(2, "Sol", "gomi what's five plus five?", addressed=True),
    post(3, "Gomihyu", "Four for Mira. Ten for Sol.", answered_requests=[1, 2]),
])
batch_prompt = render(landed_replies(batched)[0])["messages"][1]["content"]
assert ("These messages still need your reply:\nMira: gomi what's two plus two?\n"
        "Sol: gomi what's five plus five?\n") in batch_prompt
newest_only = {**landed_replies(batched)[0], "answered_requests": [2]}
assert "These messages still need your reply:\nSol: gomi what's five plus five?\n" in render(newest_only)["messages"][1]["content"]
# After a previous batch's answer, the next harvested turn retains its actual observed source.
later_batch = approved([
    post(1, "Mira", "gomi what's two plus two?", addressed=True),
    post(2, "Sol", "gomi what's five plus five?", addressed=True),
    post(3, "Gomihyu", "Four for Mira.", answered_requests=[1]),
    post(4, "Gomihyu", "Ten for Sol.", answered_requests=[2]),
])
later, = landed_replies(later_batch)
later_prompt = render(later)["messages"][1]["content"]
later_instruction = later_prompt.split('Above is the recent chat log', 1)[1]
assert "The newest message, from Sol:\nSol: gomi what's five plus five?\n" in later_instruction
assert "These messages still need your reply:\nSol: gomi what's five plus five?\n" in later_instruction
assert '\nGomihyu:' not in later_instruction
# Human voice examples can answer Gomi herself. No required targets means the actual tail remains
# the source; selecting pending requests must not change this established training meaning.
voice, = voice_examples([
    post(1, "Mira", "we could play something tonight"),
    post(2, "Gomihyu", "Which game do you want?", bot=True),
    post(3, "Sol", "I want to play chess"),
])
voice_prompt = render(voice)["messages"][1]["content"]
assert "You are replying to the newest message, from Gomihyu:\nGomihyu: Which game do you want?\n" in voice_prompt
# An explicit Discord reply does not turn a human voice sample into one of Gomi's queued batches.
for target in (1, 2):
    linked_voice, = voice_examples([
        post(1, "Mira", "we could play something tonight"),
        post(2, "Gomihyu", "Which game do you want?", bot=True),
        post(3, "Sol", "I want to play chess", reply_to=target),
    ])
    linked_prompt = render(linked_voice)["messages"][1]["content"]
    assert "The newest message, from Gomihyu:\nGomihyu: Which game do you want?\n" in linked_prompt
    assert linked_voice["answered_requests"] == [target]
omitted = {**example, "history": example["history"] + [["Sol", "more chatter"], ["Sol", "and more"]],
           "history_meta": example["history_meta"]
                           + [{"id": 8, "text": "more chatter", "addressed": False, "bot": False},
                              {"id": 9, "text": "and more", "addressed": False, "bot": False}]}
assert render(omitted) is not None  # Full dataset context retains the exact answer source.
assert format_examples([omitted]) == ""  # The three-line few-shot preview would lose it.
assert pick_examples([], [omitted, example], 8, .3, 200) == [example]
entries[2].pop("answered_requests")  # Earlier runtime versions saved a Discord link only.
assert landed_replies(entries)[0]["answered_requests"] == [1]
entries = approved([post(1, "Mira", "gomi what's two plus two?", addressed=True)]
                   + [post(i, "Sol", f"new unrelated message {i}", addressed=False) for i in range(2, 9)]
                   + [post(9, "Gomihyu", "Four, Mira.", reply_to=1, answered_requests=[1])])
assert not landed_replies(entries)  # Bounded context lost its actual source: skip, don't retarget.

# The feedback window counts people, even with several other-bot posts interposed.
entries = approved([post(1, "Mira", "gomi what do you think?"),
                    post(2, "Gomihyu", "A long irrelevant answer.", answered_requests=[1])])
entries[2:2] = [post(i, "Doumi", "bot background message", bot=True) for i in range(3, 6)]
entries.append(post(6, "Sol", "you are talking too much"))
assert not landed_replies(entries)
entries[-1]["text"] = "lmao"
entries = [e for e in entries if e.get("kind") != "reaction"]
assert landed_replies(entries)[0]["signal"] == "laugh"

# Generated and quoted context never supplies human laughter, complaints, or voice targets.
for raw, context, accepted in [("", "[image: a laughing cat saying lmao]", False),
                               ("look at this", "[reply to Sol: lmao] look at this", False),
                               ("lmao", "[image: a sign saying shut up] lmao", True)]:
    entries = [post(1, "Mira", "what do you think?"),
               post(2, "Gomihyu", "Try this other approach.", answered_requests=[]),
               post(3, "Sol", raw, context=context)]
    assert bool(landed_replies(entries)) is accepted
entries = [post(1, "Mira", "what do you think?"),
           post(2, "Sol", "", context="[image: I love this game so much]")]
assert not voice_examples(entries)
entries[-1].update(text="I like this", context="[image: generated extra words] I like this")
voice, = voice_examples(entries)
assert voice["reply"] == "I like this"
for text in ("[image: lmao]", '[reply to Mira: "haha"]', "> copied words here"):
    legacy = {"text": text}
    assert raw_author_text(legacy) is None
    entries[-1] = post(2, "Sol", text)
    entries[-1].pop("text_provenance")
    assert not voice_examples(entries)
    assert not landed_replies([post(1, "Mira", "what do you think?"),
               post(2, "Gomihyu", "Try the other approach.", answered_requests=[]),
                               {**entries[-1], "id": 3}])
assert raw_author_text({"text": "clean legacy human words"}) == "clean legacy human words"
assert raw_author_text({"text": "lmao", "text_provenance": "generated"}) is None

# Saved earned examples lacking raw addressing/answer provenance are left untouched and skipped.
legacy = {"history": [["Mira", "gomi what is that?"]], "reply": "An old answer.", "real": True}
assert render(legacy) is None
assert format_examples([legacy]) == "" and pick_examples([], [legacy], 8, .3, 200) == []
assert system_content([legacy]) == SYSTEM_PROMPT
unlinked = approved([post(1, "Mira", "gomi what's two plus two?"),
                     post(2, "Sol", "my pizza arrived"), post(3, "Gomihyu", "Four, Mira.")])
assert not landed_replies(unlinked)
# A filtered required answer can still be delivered, but must never become a successful
# unsolicited example just because the remaining words received a positive reaction.
filtered = approved([
    post(1, "Mira", "gomi what's two plus two?", addressed=True),
    post(2, "Sol", "my pizza arrived", addressed=False),
    post(3, "Gomihyu", "Try another approach.", about="filtered", reply_to=1, answered_requests=[]),
])
assert not landed_replies(filtered)
seed = {"history": [["Mira", "gomi what is that?"]], "reply": "A handwritten answer."}
rows, _ = meld_examples([seed], 1, .5, 1, ChatLog(Path(os.environ["GOMI_TMP"]) / "none"), [legacy], .3)
assert rows == [seed] and legacy["reply"] == "An old answer."
assert "directly mentioned/addressed" in render(seed)["messages"][1]["content"]
malformed = {**example, "answered_requests": [999]}
assert render(malformed) is None
long_answer = {**example, "reply": " ".join(f"The {n} answer is here." for n in
                                           "first second third fourth fifth sixth seventh".split())}
assert render(long_answer) is None
# A build she was asked for keeps its room: held to 6 sentences rather than 3, and trained under the prompt
# that gave it; the same length for an ordinary question still can't be represented.
five = " ".join(f"Step {n} of the build." for n in "one two three four five".split())
built, = landed_replies(approved([post(1, "Mira", "gomi make me a build", addressed=True),
                                  post(2, "Gomihyu", five, reply_to=1, answered_requests=[1])]))
assert "up to 6 sentences or a short list" in render(built)["messages"][1]["content"]
assert render({**example, "reply": five}) is None
assert "up to 6 sentences" not in render(example)["messages"][1]["content"]
rows, _ = meld_examples([seed], 1, .5, 1, ChatLog(Path(os.environ["GOMI_TMP"]) / "none"), [built], .3)
assert five in [row["reply"] for row in rows]  # not cut to 3 on its way into training
folder = Path(os.environ["GOMI_TMP"]) / "long_voice"
cl = ChatLog(folder)
cl.add(1, "#synthetic", 1, 1, "Mira", "What happened?", when=1001, text_provenance="author")
cl.add(1, "#synthetic", 2, 2, "Sol", long_answer["reply"], when=1002, text_provenance="author")
assert voice_examples(cl.read(1)) and not voice_pool(cl)
saved = Path(os.environ["GOMI_TMP"]) / "legacy.jsonl"
saved.write_text(json.dumps(legacy) + "\n" + json.dumps(long_answer) + "\n")
assert read_jsonl(saved) == []  # Counts used by weekly.py match the examples the builder can render.
unmarked = {key: value for key, value in legacy.items() if key != "real"}
saved.write_text(json.dumps(unmarked) + "\n" + json.dumps(seed) + "\n")
assert len(read_jsonl(saved)) == 2  # Explicit handwritten origin remains supported.
assert read_jsonl(saved, real=True) == []  # Earned-file origin cannot impersonate handwritten seed data.
print("PROVENANCE TESTS PASSED")
