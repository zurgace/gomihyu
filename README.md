# Gomihyu — Discord conversationalist (LFM2.5-2.6B)

## 1. Install and start Ollama, pull the model
```bash
curl -fsSL https://ollama.com/install.sh | sh
ollama pull hf.co/lmstudio-community/LFM2.5-2.6B-GGUF:Q4_K_M
```
Leave Ollama running (`ollama serve`, or it may already run as a background service
depending on your install). Sanity-check it works:
```bash
ollama run hf.co/lmstudio-community/LFM2.5-2.6B-GGUF:Q4_K_M "say hi"
```

## 2. Create the Discord bot application
1. Go to https://discord.com/developers/applications → New Application → name it "Gomihyu".
2. Bot tab → **set the username to `Gomihyu`** (this is what makes `@Gomihyu` autocomplete
   to it in Discord).
3. Bot tab → under **Privileged Gateway Intents**, turn ON **Message Content Intent**.
   Without this, `message.content` arrives empty and the bot can't see what anyone said.
4. Bot tab → Reset/copy the **token** — this goes in `.env` as `DISCORD_BOT_TOKEN`. Treat
   it like a password; never commit it.
5. OAuth2 → URL Generator → scope `bot` → permissions: **Read Messages/View Channels,
   Send Messages, Read Message History, Add Reactions**. Open the generated URL and invite it to your
   5-person server.

## 3. Configure and run
```bash
git clone https://github.com/zurgace/gomihyu.git && cd gomihyu
python3 -m venv venv
venv/bin/pip install -r requirements.txt
cp .env.example .env   # then fill in DISCORD_BOT_TOKEN
venv/bin/python bot.py
```
You should see `Logged in as Gomihyu (id: ...)` in the console once it's connected.

Running through `venv/bin/python` uses the venv without activating it, so it works the same in
bash, zsh or fish. (If you do activate it in fish, the command is `source venv/bin/activate.fish`.)

**`ModuleNotFoundError: No module named 'aiohttp'` (or `discord`)** means the Python running
the bot doesn't have the requirements installed. Either plain `python3` ran instead of the venv's,
or a system update (common on CachyOS/Arch) upgraded Python and left the venv behind. Rebuild it:
```bash
rm -rf venv && python3 -m venv venv && venv/bin/pip install -r requirements.txt
```

## How it behaves
- **@mention → always replies**, and the persona is instructed to fire back rudely in
  character if provoked, rather than staying polite.
- **Any other message → replies with probability `UNPROMPTED_REPLY_CHANCE`** (default 1.0,
  i.e. every message, no cooldown — meant for a slow server) — tune this in `.env` without
  touching code.
- **Reacts with an emoji** to a `REACTION_CHANCE` share of messages (default 0.3), rolled
  separately from replying, so a message can get a reaction, a reply, both or neither. The
  emoji comes from a small in-character set (😤 🔥 👑 💢 🙄 😈 💅), picked by keywords in
  `reactions.py`, with no model call. Sad or serious messages get no reaction. Needs the
  **Add Reactions** permission. If it's missing, the console logs `Couldn't react ...` and
  replies carry on as normal.
- **One reply at a time per channel.** If messages arrive while it's still writing a reply,
  it sends one follow-up afterwards that answers the latest chat, rather than one reply each.
- **Addresses people by their full Discord handle.** The chat log it sees labels everyone by
  handle (e.g. `kaz0: ...`), and when a reply says `@kaz0` the bot turns it into a real ping.
  Discord shows a ping as the person's server display name. It never pings `@everyone`,
  `@here` or roles.
- Keeps the last `HISTORY_LENGTH` messages per channel as context so replies aren't
  totally blind to what's being discussed.
- **Doesn't parrot itself.** If a reply copies `REPEAT_WORDS` (default 5) words in a row from
  one of its own recent messages, it regenerates once at `RETRY_TEMPERATURE` (default 1.0) and
  logs that it did. Small models otherwise tend to reuse their earlier lines word for word.
- **Never says a slur.** Any word from `slurs.txt` in her reply becomes "filtered" before it's
  sent (and in her chat history, so she can't echo it later). Whole words only, so "spicy" is
  safe; swearing isn't on the list. Edit the file to add or remove words, then restart.
- **Remembers what you tell her to.** See [Memory](#memory).
- Ignores its own messages and other bots.

## Memory
Tell her something on purpose and she keeps it, across restarts:
```
@Gomihyu remember that I hate cilantro
Gomihyu, don't forget my birthday is march 3
```
- It only counts if the message is aimed at her: it @mentions her, replies to one of her
  messages with the ping left on, or starts with "Gomihyu". "remember that party lol" in normal chat is ignored, and so are questions
  like "@Gomihyu remember when...?". Nothing is picked up from ordinary conversation.
- When a fact is stored she reacts 📝 and the console logs `Remembered for <handle>: ...`.
  Everything after "remember (that)" / "don't forget (that)" is stored word for word.
- When she replies to you, your facts, and only yours, go into her prompt, with a note to
  bring one up only when it fits. If you ask "what do you remember about me?", she has
  your facts in front of her to answer from.
- Facts live in `people.json` next to `bot.py` (`PEOPLE_FILE` in `.env`), keyed by Discord
  user ID. It's in `.gitignore`, so it stays on your machine. Each person keeps at most
  `MAX_FACTS_PER_PERSON` (default 20) facts; past that, their oldest one drops off.
- To remove or fix a fact, **stop the bot first**, edit `people.json`, then start it again.
  The running bot keeps its own copy and would overwrite your edit the next time it
  remembers something. If the file isn't valid JSON, the bot won't start (it says why), so
  a typo can't wipe it.

## Training data
`finetuning/gomihyu_seed.jsonl` is the hand-written seed data: one example per line, with the
chat so far as `[handle, message]` pairs and the reply Gomihyu should give:
```json
{"history": [["kaz0", "@Gomihyu wanna 1v1 me in valorant"]], "reply": "You dare challenge the Archdemon to combat, @kaz0? ..."}
```
The last `history` entry is the message being answered; put `@Gomihyu` in it to make it an
@mention. Earlier entries are chat context, and Gomihyu's own messages use the speaker `Gomihyu`.
An optional `"facts": [...]` holds what that last speaker asked her to remember, rendered
exactly as the bot does at runtime.

To turn it into training data:
```bash
python3 finetuning/build_dataset.py   # -> finetuning/train.jsonl (system/user/assistant chat format)
```
This builds each prompt with `persona.build_messages()`, the same function the bot uses at
runtime, so the model is trained on exactly the prompt format it will be served.
`finetuning/persona_guide.md` is the style reference for writing more examples.

## Swapping in the fine-tuned LoRA later
The bot code doesn't need to change. Once you have a trained LoRA:
1. Merge it (or serve it as an adapter, depending on your training tool) into a GGUF.
2. `ollama create gomihyu-tuned -f Modelfile` pointing at that GGUF (or `ollama pull` if you
   push it somewhere).
3. Update `OLLAMA_MODEL` in `.env` to the new model name and restart the bot.

The `SYSTEM_PROMPT` in `persona.py` can likely get much shorter once the LoRA is actually
carrying the personality — right now it's doing all the work. If you change it, rebuild
`train.jsonl` and retrain: the LoRA is trained against whatever prompt was in place at the time.

## Known limitations at this scope
- Text-only: it can't see images, only whatever caption/text comes with them.
- Chat history is in-memory only and resets when the bot restarts. Remembered facts
  (`people.json`) do persist.
- Single-server assumption: history is keyed by Discord channel ID, so it naturally
  won't cross-contaminate between channels/servers, but there's no persistence yet.
