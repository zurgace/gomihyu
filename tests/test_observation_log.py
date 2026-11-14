"""Arrival-time persistence and diary boundaries with synthetic observations and async fakes only."""
import asyncio
from datetime import datetime
import json
import os
from pathlib import Path
import sys
import time

REPO, TMP = Path(os.environ["GOMI_REPO"]), Path(os.environ["GOMI_TMP"])
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "finetuning"))
from chatlog import ChatLog, local_day, raw_author_text
from meld import landed_replies
from build_dataset import render


# Two identical captions retain their own descriptions, including completion across a day boundary.
arrival = datetime(2026, 1, 2, 23, 59, 50).timestamp()
log = ChatLog(TMP / "arrival")
for i, author, text, extra in [
    (1, "Mira", "look at this", {"context": "look at this [image]"}),
    (2, "Doumi (bot)", "Background context.", {"bot": True}),
    (3, "Mira", "look at this", {"context": "look at this [image]"}),
    (4, "Sol", "what should I try next?", {}),
    (5, "Gomihyu", "Try the other option, Sol.", {"answered_requests": []}),
]:
    log.add(7, "#synthetic", i, i, author, text, when=arrival + i,
            text_provenance="author", addressed=False, **extra)
source_bytes = (log.folder / local_day(arrival) / "7.jsonl").read_bytes()
log.enrich(7, 3, "look at this [image: a blue dog]", when=arrival + 20)
log.enrich(7, 1, "look at this [image: a red cat]", when=arrival + 21)
log.add(7, "#synthetic", None, 9, "Sol", "😂", when=arrival + 22, kind="reaction", to=5)
assert (log.folder / local_day(arrival) / "7.jsonl").read_bytes() == source_bytes
entries = log.read(7)
assert [e["id"] for e in entries] == [1, 2, 3, 4, 5]
assert entries[0]["context"] == "look at this [image: a red cat]"
assert entries[2]["context"] == "look at this [image: a blue dog]"
assert entries[0]["time"] == arrival + 1 and entries[2]["time"] == arrival + 3
assert raw_author_text(entries[0]) == raw_author_text(entries[2]) == "look at this"
assert [e["id"] for e in log.read(7, after=arrival + 2, before=arrival + 4)] == [3, 4]
assert log.read(7, after=arrival + 2, before=arrival + 3)[0]["context"] == entries[2]["context"]
assert len(log.read(7, reactions=True)) == 6  # Context updates are never additional feedback/messages.
example, = landed_replies(log.read(7, reactions=True))
assert [m["id"] for m in example["history_meta"]] == [1, 2, 3, 4]
assert example["answered_requests"] == [] and example["history"][-1] == ["Sol", "what should I try next?"]
prompt = render(example)["messages"][1]["content"]
assert "from Sol:\nSol: what should I try next?" in prompt
assert "Mira: look at this [image: a red cat]" in prompt
assert "Mira: look at this [image: a blue dog]" in prompt

# Deletion removes every event for a source even across dates; an orphan event cannot invent a post.
log.enrich(7, 999, "An orphan description", when=arrival + 23)
assert all(e.get("id") != 999 for e in log.read(7, reactions=True))
log.forget(7, {1, 3})
assert [e["id"] for e in log.read(7)] == [2, 4, 5]
for day in log._days():
    for line in (day / "7.jsonl").read_text().splitlines():
        assert json.loads(line).get("id") not in {1, 3}

# Equal arrival timestamps retain file order; legacy plain records and malformed tails remain usable.
log.add(8, "#legacy", 10, 2, "Mira", "old plain words", when=arrival)
log.add(8, "#legacy", 11, 3, "Sol", "new plain words", when=arrival)
with (log.folder / local_day(arrival) / "8.jsonl").open("a") as f:
    f.write('{"incomplete":')
assert [e["id"] for e in log.read(8)] == [10, 11]
assert [raw_author_text(e) for e in log.read(8)] == ["old plain words", "new plain words"]


async def diary_boundary():
    os.environ.update(DISCORD_BOT_TOKEN="fake", PEOPLE_FILE=str(TMP / "people.json"))
    import bot
    from diary import Diary

    bot.chat_log = ChatLog(TMP / "diary_log")
    bot.diary = Diary(TMP / "diary_boundary.json")
    bot.earned = []
    bot.VIBE_MIN_MESSAGES = 1000
    calls = []

    async def fake(payload):
        calls.append(payload)
        return {"message": {"content": json.dumps({"recap": "A picture and a question.", "notes": []})}}

    bot.ollama_chat = fake
    start, channel = time.time() - 100, 91
    bot.chat_log.add(channel, "#boundary", 101, 2, "Mira", "look at this", when=start,
                     context="look at this [image]", text_provenance="author")
    bot.chat_log.add(channel, "#boundary", 102, 3, "Sol", "what should I try next?", when=start + 1,
                     text_provenance="author")
    ready = asyncio.get_running_loop().create_future()
    bot.pending_vision[channel].add(ready)
    task = asyncio.create_task(bot.write_diary("synthetic boundary", before=start + 2))
    await asyncio.sleep(0)
    assert not task.done() and not calls and bot.diary.read_up_to(channel) == 0, \
        "Diary crossed an unfinished observation and could permanently skip its description"

    # A post arriving while diary waits stays beyond its frozen boundary for the next pass.
    bot.chat_log.add(channel, "#boundary", 103, 3, "Sol", "later follow-up words", when=start + 3,
                     text_provenance="author")
    bot.chat_log.enrich(channel, 101, "look at this [image: a red cat]", when=start + 10)
    bot.pending_vision[channel].discard(ready)
    ready.set_result(None)
    await asyncio.wait_for(task, 3)
    assert len(calls) == 1
    prompt = calls[0]["messages"][1]["content"]
    assert "Mira: look at this [image: a red cat]" in prompt
    assert "Sol: what should I try next?" in prompt and "later follow-up words" not in prompt
    assert bot.diary.read_up_to(channel) == start + 1
    assert [e["id"] for e in bot.chat_log.read(channel, after=bot.diary.read_up_to(channel))] == [103]
    await bot.write_diary("next synthetic boundary", before=start + 20)
    assert bot.diary.read_up_to(channel) == start + 3 and len(calls) == 1
    assert bot.memory.learned_for(2) == []  # The generated picture is display context only.


asyncio.run(diary_boundary())
print("OBSERVATION LOG TESTS PASSED")
