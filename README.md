# Gomihyu — Discord conversationalist (LFM2.5-2.6B)

## 1. Install Ollama and build the model
```bash
curl -fsSL https://ollama.com/install.sh | sh
git clone https://github.com/zurgace/gomihyu.git && cd gomihyu
```
Download `LFM2.5-2.6B-Q4_K_M.gguf` (LFM2.5-2.6B at Q4_K_M, ~1.7GB, from Hugging Face:
`LiquidAI/LFM2.5-2.6B-GGUF` or `lmstudio-community/LFM2.5-2.6B-GGUF`) and move it into this
folder, e.g. `mv ~/Downloads/LFM2.5-2.6B-Q4_K_M.gguf .` (`*.gguf` is gitignored). Then:
```bash
ollama create gomihyu-base -f Modelfile
```
**`Error: 400 Bad Request: invalid model name`** means Ollama didn't find the GGUF in this
folder, so it read the `FROM` line as a model name instead. `command ls -lL
LFM2.5-2.6B-Q4_K_M.gguf` should show a file of 1674454368 bytes. If you no longer have the file
but already built a model from it, Ollama kept a copy: it's the path on the `FROM` line of
`ollama show <that model> --modelfile`. Copy it here with
`sudo cp <that path> LFM2.5-2.6B-Q4_K_M.gguf` and `sudo chown $USER: LFM2.5-2.6B-Q4_K_M.gguf`.

Leave Ollama running (`ollama serve`, or it may already run as a background service
depending on your install).

**Why a Modelfile:** LFM2.5-2.6B is a reasoning model. Its own chat template starts every
answer with a `<think>` block, so asking Ollama not to think does nothing, and every reply
cost ~1000 tokens (8–13s) of reasoning. The `Modelfile` gives it a template that hands it an
empty, already-closed think block instead, so it answers straight away. (Built from the bare
GGUF without a template, `ollama show gomihyu-base --modelfile` shows `TEMPLATE {{ .Prompt }}`.)

Sanity-check it: the answer should come back with no `"thinking"` field.
```bash
curl -s localhost:11434/api/chat -d '{"model": "gomihyu-base", "stream": false, "think": false, "messages": [{"role": "user", "content": "say hi in five words"}]}'
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
- **Reacts instead of replying when words aren't needed.** See [Emojis](#emojis).
- **One reply at a time per channel.** If messages arrive while it's still writing a reply,
  it sends one follow-up afterwards that answers the latest chat, rather than one reply each.
- **Goes by Gomi, and calls people by their nicknames** (see [Memory](#memory)), or by their
  Discord handle when she doesn't know one. The chat log she sees labels everyone by handle
  (e.g. `kaz0: ...`), with a line listing the nicknames of the people in it. When a reply says
  `@kaz0` or `@Kaz` (handle, display name or nickname), the bot turns it into a real ping.
  Discord shows a ping as the person's server display name. It never pings `@everyone`,
  `@here` or roles.
- **Joins in, not just one-liners.** Her prompt makes her an active member of the chat: she
  answers the newest message but builds on what others said, gives opinions and reasons, and
  sometimes asks something back. A quick jab can be a few words; a question or a real
  discussion gets 2–4 sentences. `MAX_REPLY_TOKENS` (default 200) caps a runaway reply, and
  one that hits the cap is cut back to its last full sentence.
- **Doesn't "think" before replying** (`OLLAMA_THINK=false`): for chat it only adds delay. The
  `Modelfile` is what makes that work for LFM2.5-2.6B (see step 1). If a model thinks anyway,
  the console logs `... thinks before answering even with OLLAMA_THINK=false` once, and replies
  stop being capped at `MAX_REPLY_TOKENS` from then on, because the thinking counts against
  that cap and would crowd out the answer. Any `<think>` text that ends up in the answer
  itself is cut before posting. `OLLAMA_THINK=true` turns thinking back on, uncapped.
- Keeps the last `HISTORY_LENGTH` messages per channel as context so replies aren't
  totally blind to what's being discussed.
- **Doesn't parrot itself.** If a reply copies `REPEAT_WORDS` (default 5) words in a row from
  one of its own recent messages, it regenerates once at `RETRY_TEMPERATURE` (default 1.0) and
  logs that it did. Small models otherwise tend to reuse their earlier lines word for word.
- **Never says a slur.** If her reply contains any word from `slurs.txt`, the whole reply is
  thrown away and she posts `:goonerstare:` instead (`SLUR_STANDIN` in `emojis.py`). Her chat
  history keeps only the stare, so she can't echo the slur later. Whole words only, so "spicy"
  is safe; swearing isn't on the list. Edit the file to add or remove words, then restart.
- **Remembers what you tell her to.** See [Memory](#memory).
- Ignores its own messages and other bots.

## Emojis
**Posts that don't need words get a reaction as her whole response:** images, stickers, a
bare link (usually a GIF), emoji-only posts, and short interjections of up to
`REACT_ONLY_MAX_WORDS` words (default 2) without a `?`, like "oogaga" or "lol wtf". Anything
that @mentions her, says "gomi"/"gomihyu", or sounds like bad news gets a normal reply instead.
- **Sad news** ("my dog died", "rough week") gets a reply *and* a `:catsad:` reaction
  (`SAD_NEWS` in `emojis.py`). Laughter doesn't count: "im crying lmao" is not sad news.
- **Images, stickers, links:** she can't see them, so she doesn't pretend to judge them: she
  reacts 👀 or `:goonerstare:`. In her chat log they show up as `[image]`, `[sticker: name]`,
  so she knows something was posted instead of seeing an empty line.
- **Emoji-only posts:** she can react with the same emoji, or answer it with a different one.
- **Everything else:** a quick, separate model call picks the emoji. Its answer is restricted
  to the names in `emojis.py` (plus "none", in which case she leaves it be).
- **In her own messages** she can use this server's custom emojis now and then, by writing
  `:kekpoint:`; the bot turns that into the real emoji.

`emojis.py` lists every emoji she uses and **when** to use it. The model never sees the
pictures, only names and those notes, so edit the notes to change how she uses them. Custom
emojis marked `in_text=False` (`aryanosaka`, `goonerstare`) are reaction-only: their names
aren't listed in her chat prompt. (`goonerstare` still shows up in her chat log after she posts
it in place of a slur.) If you rename or delete one in Discord, she just can't use it
until `emojis.py` matches again.

Reactions need the **Add Reactions** permission. If it's missing, the console logs
`Couldn't react ...` and everything else carries on.

## Memory
Tell her something on purpose and she keeps it, across restarts:
```
@Gomihyu remember that I hate cilantro
Gomihyu, don't forget my birthday is march 3
```
- It only counts if the message is aimed at her: it @mentions her, replies to one of her
  messages with the ping left on, or has "Gomi"/"Gomihyu" within its first few words
  ("ok then gomi remember that ..."). "remember that party lol" in normal chat is ignored, and so are questions
  like "@Gomihyu remember when...?". Nothing is picked up from ordinary conversation.
- When a fact is stored she reacts 📝 and the console logs `Remembered for <handle>: ...`.
  Everything after "remember (that)" / "don't forget (that)" is stored word for word.
- **Nicknames** are saved for the person they belong to, not whoever said them, so she uses
  them whenever that person is in the chat: "gomi call me Rex", "gomi my nickname is Rex",
  "gomi remember that Yuzuki's nickname is Yuzu", "@Gomihyu call @yuzuki Yuzu". The person can
  be named by handle, display name or @mention, and needs to have talked since the bot started
  or already be in `people.json`. Otherwise the console logs `Nickname ... not saved: don't
  know who ...`. Nicknames containing a slur aren't saved. Her own name (Gomi) is fixed.
- When she replies to you, your facts, and only yours, go into her prompt, with a note to
  bring one up only when it fits. If you ask "what do you remember about me?", she has
  your facts in front of her to answer from.
- Facts and nicknames live in `people.json` next to `bot.py` (`PEOPLE_FILE` in `.env`), keyed by
  Discord user ID. It's in `.gitignore`, so it stays on your machine. Each person keeps at most
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
2. Copy the `Modelfile`, point its `FROM` at that GGUF and keep its `TEMPLATE`, then
   `ollama create gomihyu-tuned -f <that Modelfile>`. Train with the same empty think block
   (`<think>\n</think>\n\n` at the start of each answer), so the model learns the format it's served.
3. Update `OLLAMA_MODEL` in `.env` to the new model name and restart the bot.

The `SYSTEM_PROMPT` in `persona.py` can likely get much shorter once the LoRA is actually
carrying the personality — right now it's doing all the work. If you change it, rebuild
`train.jsonl` and retrain: the LoRA is trained against whatever prompt was in place at the time.

## Known limitations at this scope
- A 2.6B model makes things up. Her prompt tells her what she can't do (she only sees the
  last few messages; she can't read or search history, look things up or do things later)
  and who she's answering, which helps, but she'll still bluff sometimes. Don't rely on her
  for facts; anything that must be right (memory, the slur filter) is handled in code.
- Text-only: it can't see images, only whatever caption/text comes with them. Image posts
  appear to her as `[image]`, and on their own they get a 👀-style reaction, not a reply.
- Chat history is in-memory only and resets when the bot restarts. Remembered facts
  (`people.json`) do persist.
- Single-server assumption: history is keyed by Discord channel ID, so it naturally
  won't cross-contaminate between channels/servers, but there's no persistence yet.
