# Gomihyu — Discord conversationalist (Gemma 4 E4B)

"Gomi" is a persona chat bot for a small Discord server: a bratty self-proclaimed Archdemon who talks
like one of the friends. She answers whatever is aimed at her, reads the room to decide when to chime in
or react with an emoji, sees pictures, remembers facts and nicknames, keeps a diary, and posts about the
Melee games she plays in [AI-Melee](https://github.com/zurgace/aimelee).

**She runs locally.** Every model call goes to [Ollama](https://ollama.com) on your own PC (an 8 GB GPU
is enough); there's no cloud AI API. Only the optional weekly fine-tune runs elsewhere, on Kaggle's free
GPU, with the server's chat (the members agreed).

**Built with [Claude Code](https://claude.com/claude-code).** `CLAUDE.md` holds the design decisions it
works from, and most commits are Claude's.

Every setting is in `.env.example`, with its default.

## Layout
```
gomi/          the bot, a Python package (python -m gomi): bot.py runs the Discord side, persona.py
               builds every prompt, chime.py reads the room, shape.py sizes each reply, tray.py is the app
finetuning/    the weekly fine-tune on Kaggle, and the made-up seed chats it trains on
tools/         model comparison (chat_check.py) and the vision check
tests/         run_all.sh and a suite per feature, with Ollama, Discord and Kaggle faked
models/        Modelfile.bolt, the Ollama model gomi-bolt
archive/       parked experiments
data/          her memory, chat logs and diary (made on her first run, gitignored)
```

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
   venv/bin/python -m gomi  # "Logged in as Gomihyu" when connected
   ```
   Stop with Ctrl+C (or "gomi goodnight"): she writes her diary first; a second Ctrl+C skips it.
   `ModuleNotFoundError` after a system update (CachyOS upgrades Python): rebuild the venv with
   `rm -rf venv && python3 -m venv venv && venv/bin/pip install -r requirements.txt`.

   **As an app** (no console): `venv/bin/python -m gomi.tray` (Qt, from `requirements.txt`) puts her
   icon in the system tray. Right-click it for **Open log** (what the console showed is in
   `data/gomi.log`, the run before in `data/gomi.log.old`) and **Shut down** (the Ctrl+C above; click
   again to skip the diary). The icon goes when she stops, with a notification if she crashed. To start
   her from the app menu (search "Gomi"), once, in the repo folder:
   ```bash
   sed "s|GOMI_DIR|$PWD|g" gomi/gomihyu.desktop > ~/.local/share/applications/gomihyu.desktop
   ```
   Also copy that file into `~/.config/autostart/` to start her at login.

## How she behaves
- **Always answers posts aimed at her**: an @mention, a Discord reply to her, her name, sad news.
- **Everything else, she reads the room first**: one short model call rates how much she'd want to say
  something (she replies at `CHIME_IN_THRESHOLD`, default 6) and how much it gets a rise out of her (she
  reacts at `REACT_THRESHOLD`, default 8). The console shows each read:
  `Read kaz0's post: '...', interest 3, react 9/10 (reacts at 8), 🔥 fits`.
- **Reactions** are for moments: a big win, something really funny or cute, a painful fail. Pictures,
  stickers, emoji-only posts and 1–2 word interjections ("lol wtf") only ever get a reaction; sad news
  gets a reply and `:catsad:`. `gomi/emojis.py` lists every emoji and when to use it: edit the notes to
  change her picks.
- **Talks like a member of the chat**: plain answers first, plays along, teases like a friend. She calls
  people by nickname, pings someone only to pull them in (never the person she's answering), and never
  brings up the made-up people from the seed chats (`kaz0`, `Nori`, ...).
- **Reply shape is decided in code** (`gomi/shape.py`), since a small model copies its own last few messages:
  a post of at most `ONE_LINE_MAX_WORDS` (6) words that isn't a question gets one short line; a post
  aimed at her that asks for room ("make me a build", "explain ...", "list ...", "how do I ...", "walk me
  through", tips, a guide, a recipe) gets the whole answer, up to 6 sentences or a short list; anything
  else gets 1–3 sentences. A reply that runs longer is cut back to whole sentences and still posted
  (`Trimmed to ...` in the console), and so is one over Discord's 2000 characters. She asks back, or uses
  an emoji (one at most), only if her last two messages didn't. A needed clarification is always allowed:
  she can ask what someone means instead of inventing an answer. Pending requests determine length even
  when newer short chatter arrives. At most three requests enter one reply; additional requests stay queued.
- **Never says a slur**: a reply with a word from `gomi/slurs.txt` becomes `:goonerstare:`. Swearing is
  fine.
- **One reply at a time per channel**; whatever arrives meanwhile gets one follow-up, and drops a chime-in
  she hasn't posted yet. Questions to her still get answered, each asker their own, as a Discord reply if
  the chat moved on. A reply that fails, or may not have gone through, isn't resent: ask again.
- **Thinking** (`OLLAMA_THINK=true` in `.env`, then restart): she thinks before each answer, Melee post and
  goodnight, never before a chime-in (a post while she writes drops it); several seconds slower, not
  capped at `MAX_REPLY_TOKENS`, still held to her reply's size. The console shows each thought's start:
  `She thought (212 words, 9.4s for all): '...'`.

## Memory and diary
- "**gomi remember that** I hate cilantro" (or @mention her) stores it word for word (📝).
  "gomi call me Rex" / "gomi Yuzuki's nickname is Yuzu" sets nicknames. Kept in `data/people.json`.
- She logs the server's chat (`data/chatlogs/`, never DMs). At shutdown she writes her **diary**: a recap
  per channel (`data/diary.json`; her last 3 days go in her prompt) and notes on people (kept only if the
  words they're based on are that person's own, not a quote). A crash is caught up on at the next start.
- Each new recap is also **posted** in its channel (📔): right away on "gomi goodnight", at the next start
  after a Ctrl+C. Never her notes on people, and she ignores the post. `POST_DIARY=false` turns it off.
- Each night her replies that **landed** (a person's positive reaction or laugh, with no complaint; a mention
  or a reply alone isn't praise) become examples of her voice (`data/earned_examples.jsonl`, up to
  `FEW_SHOT_EXAMPLES` 8 per reply's prompt), and she updates a short note on how the server talks.
- Stop the bot before editing any of these files. `data/` is gitignored and stays on your PC.

## What she sees
A Discord reply shows her a short quote of the post it answers, even an old one. She sees other bots'
posts too, but they never give her commands or train her, and only set her off when they talk to her (an
@mention, a reply to her, her name): she answers `BOT_REPLIES` (2) of a bot's posts in a row at most, until
a person posts.

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

Mute and quiet mode last `MUTE_MINUTES` (30) by default, and a restart clears them. Muting also drops
the questions she hasn't answered yet: unmuting doesn't bring them back.

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
- Older runs counted examples differently, so `build` stops until a `build --force` run is installed:
  review the examples first (those saved before Nov 14 counted any mention or reaction as praise).
- Each run stays in Ollama as `gomi-wN`. The data is deleted from Kaggle once the model is downloaded;
  everything local stays in `finetuning/runs/` (gitignored).
- The new model can't see pictures, so `switch` points `VISION_MODEL` (and `TASK_MODEL` for reading
  the room and her diary, if both fit on the GPU) at the stock `gemma4:e4b`.

The made-up seed chats (`finetuning/gomihyu_seed.jsonl`) only train her (`SEED_EXAMPLES=true` puts them
back in her prompt); `finetuning/persona_guide.md` is the guide for writing more.
`archive/discord-pipeline/` (parked) turns your own Discord export into training data, never DMs.

## Tests
```bash
tests/run_all.sh                     # all suites
tests/run_all.sh test_reactions.py   # one
```
Ollama, Discord, Kaggle and Unsloth are faked, and the suites run on a temporary copy of the repo, so
your `.env` and data are never touched.

## Comparing conversation models
`tools/chat_check.py` gives `gomi-w1`, `gemma4:e4b` and `gomi-bolt` (made from `models/Modelfile.bolt`)
the same six made-up chats at seeds 17, 29 and 43, and writes every prompt, setting and reply to a new
report. Nothing private is read, not even `.env`; the models must be installed already:
```bash
venv/bin/python tools/chat_check.py --url http://localhost:11434/api/chat --think --output /tmp/gomi-comparison-thinking.md
venv/bin/python tools/chat_check.py --url http://localhost:11434/api/chat --no-think --output /tmp/gomi-comparison-no-thinking.md
```
Give each run a new `--output`: it never overwrites one. Judge whether she stays on topic, asks what's
unclear and admits what she doesn't know, and how long she takes, not how short she is. It checks the
replies only, not the room read or Discord.

## Known limitations
- A small model makes things up. Anything that must be right (memory, the slur filter, diary notes) is
  checked in code; her opinions and facts aren't. A picture is one short description: the gist.
- Built for one small server: history and logs are per channel, with no cooldowns.
