# Gomihyu — Discord conversationalist (Gemma 4 E4B)

"Gomi", a bratty self-proclaimed Archdemon for a small Discord server, on a local model via Ollama.
Every setting is in `.env.example`, with its default; `CLAUDE.md` has the design decisions.

## Setup
1. **Ollama and the model**
   ```bash
   curl -fsSL https://ollama.com/install.sh | sh
   ollama pull gemma4:e4b
   git clone https://github.com/zurgace/gomihyu.git && cd gomihyu
   ```
   `ollama ps` after her first reply should show `100% GPU` (about 3.2GB on an RTX 2070) and context
   8192. A CPU/GPU split means slower replies.
2. **The Discord app** (https://discord.com/developers/applications): New Application "Gomihyu".
   Bot tab: username `Gomihyu`, turn on **Message Content Intent**, copy the **token**. OAuth2 → URL
   Generator → scope `bot`, permissions **View Channels, Send Messages, Read Message History, Add
   Reactions** → open the URL to invite her.
3. **Run**
   ```bash
   python3 -m venv venv && venv/bin/pip install -r requirements.txt
   cp .env.example .env    # put the token in DISCORD_BOT_TOKEN
   venv/bin/python bot.py  # "Logged in as Gomihyu" when connected
   ```
   Stop with Ctrl+C (or "gomi goodnight"): she writes her diary first; a second Ctrl+C skips it.
   `ModuleNotFoundError` after a system update (CachyOS upgrades Python): rebuild the venv with
   `rm -rf venv && python3 -m venv venv && venv/bin/pip install -r requirements.txt`.

## How she behaves
- **Always answers posts aimed at her**: an @mention, a Discord reply to her, her name, sad news.
- **Everything else, she reads the room first**: one short model call rates how much she'd want to
  say something (she replies at `CHIME_IN_THRESHOLD`, default 6) and how much it gets a rise out of
  her (she reacts at `REACT_THRESHOLD`, default 8). The console shows each read:
  `Read kaz0's post: '...', interest 3, react 9/10 (reacts at 8), 🔥 fits`.
- **Reactions** are for moments, not chatter: a big win, something really funny or cute, a painful
  fail. Pictures, stickers, emoji-only posts and 1–2 word interjections ("lol wtf") only ever get a
  reaction. Sad news gets a reply and `:catsad:`. `emojis.py` lists every emoji and when to use it;
  edit the notes to change how she uses them. She writes custom emojis in replies as `:kekpoint:`.
- **Talks like a member of the chat**: a jab is one line, a question or discussion 2–4 sentences.
  Calls people by nickname. Pings someone only to pull them in, never the person she's answering.
  See "Her replies" below for how that's kept up.
- **Voice**: until a fine-tuned model serves her, each reply's prompt has 8 example chats
  (`FEW_SHOT_EXAMPLES`) from `finetuning/gomihyu_seed.jsonl`, plus the best of her own real replies.
- **Never says a slur**: a reply with a word from `slurs.txt` becomes `:goonerstare:`. Swearing is fine.
- **One reply at a time per channel**; whatever arrives meanwhile gets one follow-up.

## Her replies
A small model copies the shape of its own last few messages, so once a habit slips in (an emoji before
every sentence, a question at the end of every reply), every reply has it. So code decides each
reply's shape (`shape.py`) and tells her, instead of asking her to do things "now and then":
- A post of at most `ONE_LINE_MAX_WORDS` (6) words that isn't a question ("you're a slop bot",
  "gomi hi") gets one short line. Anything else gets 2–4 sentences. A longer reply is cut after its
  2nd or 4th sentence.
- She asks something back, or uses an emoji, only if her last two messages didn't. A message has at
  most one emoji either way.
- The console shows `Trimmed to ...` when code had to cut what the model wrote.

**Thinking** (`OLLAMA_THINK=true` in `.env`, then restart): she thinks before each reply, Melee post and
goodnight. Reading the room, her diary and pictures never think. The console shows the start of each
thought: `She thought (212 words, 9.4s for all): '...'`. It makes each reply several seconds slower, and
her replies aren't capped at `MAX_REPLY_TOKENS` (the thinking counts against it), but they still stop at
4 sentences. Set it back to `false` to compare.

## Memory and diary
- "**gomi remember that** I hate cilantro" (or @mention her) stores it word for word (📝).
  "gomi call me Rex" / "gomi Yuzuki's nickname is Yuzu" sets nicknames. Kept in `people.json`.
- She keeps a chat log of the server (`chatlogs/`, never DMs). At shutdown she writes her **diary**:
  a recap per channel (`diary.json`, her last 3 days go in her prompt) and notes on people (kept only
  if the words they're based on are really in the log). A crash is caught up on at the next start.
- Each night she also keeps her replies that **landed** (someone reacted, replied or laughed) as
  examples of her voice (`earned_examples.jsonl`), and updates a short note on how the server talks.
- To edit any of these files, stop the bot first. All of them are gitignored and stay on your PC.

## What she sees
Images, GIFs, stickers and link previews are described once by the model, and the description is
what she "sees" from then on (`kaz0: rate my setup [image: a desk with three monitors]`). She never
opens links or plays videos. **Her own avatar** is learned at login: her prompts say it's her face,
and when someone posts it (even as a resized JPEG) her log reads `[image: Gomi's own avatar, ...]`.
`VISION=false` turns vision off; `venv/bin/python tools/vision_check.py` tests it after an Ollama update.

## Owner commands
Said to her (her name, @mention or a reply to her) by the bot's owner or `OWNER_USER_IDS`. Done in code,
so she can't argue. Anyone else saying them just gets a normal reply.

| Say | She does |
|---|---|
| `gomi delete that` / `your last 3 messages` / `all your messages` | deletes her posts, 🗑️ |
| `gomi mute` / `for 2 hours` / `until i say so` | silent in this channel (🔇), 🤐 to people talking to her |
| `gomi quiet mode` (same durations) | only answers posts aimed at her (🤫) |
| `gomi unmute` / `quiet mode off` | back to normal (🔊) |
| `gomi goodnight` | says goodnight, writes her diary, shuts down (💤) |
| `gomi post melee here` / `gomi stop posting melee` | where her Melee posts go (🎮 / 🔕) |
| `gg` (to her, or in the Melee channel) | ends a Melee session now |

Mute and quiet mode last `MUTE_MINUTES` (30) by default, and a restart clears them.

## Melee
[AI-Melee](https://github.com/zurgace/aimelee) has her play Mario or Fox against you. She stays quiet
while you play and posts **once per session**: when you close the game, say "gg", or after 20 minutes
without a match. Her post says what decided it, whether her practice paid off, and what she'll work
on next. Set it up once with "gomi post melee here"; both programs share
`~/.local/share/gomihyu/melee-outbox`. `MELEE_PLAYER` names someone else playing her.

## Training her (weekly, on Kaggle's free GPU)
Her persona slowly melds with the server: each run trains on the seed chats plus the server's chat
(the members agreed), 70% seed at run 1 down to 30% by run 11. Training needs more VRAM than the 2070,
so it runs on Kaggle's free T4 (30 GPU hours a week; a run takes about an hour).

**Once:** verify your phone on [Kaggle](https://www.kaggle.com) (needed for GPUs), get an API token
(Settings → API, saved under `~/.kaggle/`), `venv/bin/pip install kaggle`, and put
`WEEKLY_KAGGLE_USER=<your username>` in `.env`.

**Each week:**
```bash
venv/bin/python finetuning/weekly.py all      # build, upload, train, download, install, check
venv/bin/python finetuning/weekly.py switch   # if the check reads right; then restart the bot
```
- `all` skips a week with fewer than 50 new examples from the server, and never switches by itself.
- The steps one at a time: `build`, `upload`, `fetch`, `install`, `check`. `status` shows the runs so
  far, `rollback` undoes a switch, and `--help` lists the options.
- `check` answers made-up test chats with her current model and the new one, side by side, and tests
  reading the room, the diary, vision and VRAM. The report is saved in `finetuning/runs/wN/check.md`.
- Each run is kept in Ollama as `gomi-wN`. The data is deleted from Kaggle once the model is
  downloaded, and everything local stays in `finetuning/runs/` (gitignored).
- The new model can't see pictures, so `switch` points `VISION_MODEL` (and `TASK_MODEL` for reading
  the room and her diary, if both fit on the GPU) at the stock `gemma4:e4b`.

`finetuning/build_dataset.py [--meld --run N]` builds the training data by hand. `finetuning/persona_guide.md`
is the style reference for writing more seed chats. `archive/discord-pipeline/` (parked) turns your
own Discord export into training data, server channels only, never DMs.

## Tests
```bash
tests/run_all.sh                     # all 28 suites, about half a minute
tests/run_all.sh test_reactions.py   # one
```
Ollama, Discord, Kaggle and Unsloth are faked, and the suites run on a temporary copy of the repo, so
your `.env` and data are never touched.

## Known limitations
- A small model makes things up. Anything that must be right (memory, the slur filter, diary notes)
  is checked in code; her opinions and facts aren't.
- A picture is one short description from a small model: the gist, not the details.
- Built for one small server: history and logs are per channel, with no cooldowns.
