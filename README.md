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
- **Everything else, she reads the room first**: one short model call rates how much she'd want to say
  something (she replies at `CHIME_IN_THRESHOLD`, default 6) and how much it gets a rise out of her (she
  reacts at `REACT_THRESHOLD`, default 8). The console shows each read:
  `Read kaz0's post: '...', interest 3, react 9/10 (reacts at 8), 🔥 fits`.
- **Reactions** are for moments: a big win, something really funny or cute, a painful fail. Pictures,
  stickers, emoji-only posts and 1–2 word interjections ("lol wtf") only ever get a reaction; sad news
  gets a reply and `:catsad:`. `emojis.py` lists every emoji and when to use it: edit the notes to change
  her picks.
- **Talks like a member of the chat**: plain answers first, plays along, teases like a friend. She calls
  people by nickname, pings someone only to pull them in (never the person she's answering), and never
  brings up the made-up people from the seed chats (`kaz0`, `Nori`, ...).
- **Reply shape is decided in code** (`shape.py`), since a small model copies its own last few messages:
  a post of at most `ONE_LINE_MAX_WORDS` (6) words that isn't a question gets one short line, anything
  else 2–4 sentences (cut if longer: `Trimmed to ...` in the console). She asks back, or uses an emoji
  (one at most), only if her last two messages didn't.
- **Never says a slur**: a reply with a word from `slurs.txt` becomes `:goonerstare:`. Swearing is fine.
- **One reply at a time per channel**; whatever arrives meanwhile gets one follow-up.
- **Thinking** (`OLLAMA_THINK=true` in `.env`, then restart): she thinks before each reply, Melee post and
  goodnight; several seconds slower, not capped at `MAX_REPLY_TOKENS`, still 4 sentences at most. The
  console shows each thought's start: `She thought (212 words, 9.4s for all): '...'`.

## Memory and diary
- "**gomi remember that** I hate cilantro" (or @mention her) stores it word for word (📝).
  "gomi call me Rex" / "gomi Yuzuki's nickname is Yuzu" sets nicknames. Kept in `people.json`.
- She logs the server's chat (`chatlogs/`, never DMs). At shutdown she writes her **diary**: a recap per
  channel (`diary.json`; her last 3 days go in her prompt) and notes on people (kept only if the words
  they're based on are really in the log). A crash is caught up on at the next start.
- Each new recap is also **posted** in its channel (📔): right away on "gomi goodnight", at the next start
  after a Ctrl+C. Never her notes on people, and she ignores the post. `POST_DIARY=false` turns it off.
- Each night her replies that **landed** (someone reacted, replied or laughed) become examples of her
  voice (`earned_examples.jsonl`, up to `FEW_SHOT_EXAMPLES` 8 per reply's prompt), and she updates a
  short note on how the server talks.
- Stop the bot before editing any of these files. All of them are gitignored and stay on your PC.

## What she sees
Images, GIFs, stickers and link previews are described once, and the description is what she "sees"
from then on (`kaz0: rate my setup [image: a desk with three monitors]`). She never opens links or plays
videos, and knows **her own avatar** when someone posts it. `VISION=false` turns vision off;
`venv/bin/python tools/vision_check.py` tests it after an Ollama update.

## Owner commands
Said to her (her name, @mention or a reply to her) by the bot's owner or `OWNER_USER_IDS`. Done in code,
so she can't argue. Anyone else saying them just gets a normal reply.

| Say | She does |
|---|---|
| `gomi delete that` / `your last 3 messages` / `all your messages` | deletes her posts, 🗑️ |
| `gomi mute` / `for 2 hours` / `until i say so` | silent in this channel (🔇), 🤐 to people talking to her |
| `gomi quiet mode` (same durations) | only answers posts aimed at her (🤫) |
| `gomi unmute` / `quiet mode off` | back to normal (🔊) |
| `gomi goodnight` | writes and posts her diary, says goodnight, shuts down (💤) |
| `gomi post melee here` / `gomi stop posting melee` | where her Melee posts go (🎮 / 🔕) |
| `gg` (to her, or in the Melee channel) | ends a Melee session now |

Mute and quiet mode last `MUTE_MINUTES` (30) by default, and a restart clears them.

## Melee
[AI-Melee](https://github.com/zurgace/aimelee) has her play Mario or Fox against you. She posts **once per
session**, when you close the game, say "gg", or after 20 minutes without a match: what decided it,
whether her practice paid off, what she'll work on next. Set it up once with "gomi post melee here"; both
programs share `~/.local/share/gomihyu/melee-outbox`. `MELEE_PLAYER` names someone else playing her.

## Training her (weekly, on Kaggle's free GPU)
Each run trains on the seed chats plus the server's chat (the members agreed), 70% seed at run 1 down to
30% by run 11. Training needs more VRAM than the 2070, so it runs on Kaggle's free T4 (30 GPU hours a
week; a run takes about an hour).

**Once:** verify your phone on [Kaggle](https://www.kaggle.com) (needed for GPUs), get an API token
(Settings → API, saved under `~/.kaggle/`), `venv/bin/pip install kaggle`, and put
`WEEKLY_KAGGLE_USER=<your username>` in `.env`.

**Each week:**
```bash
venv/bin/python finetuning/weekly.py all      # build, upload, train, download, install, check
venv/bin/python finetuning/weekly.py switch   # if the check reads right; then restart the bot
```
- `all` skips a week with fewer than 50 new examples from the server, and never switches by itself.
  `check` puts her current model and the new one side by side (report in
  `finetuning/runs/wN/check.md`); `rollback` undoes a switch; `--help` lists the single steps.
- Each run stays in Ollama as `gomi-wN`. The data is deleted from Kaggle once the model is downloaded;
  everything local stays in `finetuning/runs/` (gitignored).
- The new model can't see pictures, so `switch` points `VISION_MODEL` (and `TASK_MODEL` for reading
  the room and her diary, if both fit on the GPU) at the stock `gemma4:e4b`.

The made-up seed chats (`finetuning/gomihyu_seed.jsonl`) only train her (`SEED_EXAMPLES=true` puts them
back in her prompt); `finetuning/persona_guide.md` is the guide for writing more. Voice clips behind
some of them: `finetuning/vocals_1_clean.wav` (Neuro-sama) and `vocals_clean.wav` (Pippa, 160 MB) on
[Dropbox](removed).
`archive/discord-pipeline/` (parked) turns your own Discord export into training data, never DMs.

## Tests
```bash
tests/run_all.sh                     # all 28 suites, about half a minute
tests/run_all.sh test_reactions.py   # one
```
Ollama, Discord, Kaggle and Unsloth are faked, and the suites run on a temporary copy of the repo, so
your `.env` and data are never touched.

## Known limitations
- A small model makes things up. Anything that must be right (memory, the slur filter, diary notes) is
  checked in code; her opinions and facts aren't. A picture is one short description: the gist.
- Built for one small server: history and logs are per channel, with no cooldowns.
