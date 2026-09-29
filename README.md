# Gomihyu — Discord conversationalist (Gemma 4 E4B)

## 1. Install Ollama and pull the model
```bash
curl -fsSL https://ollama.com/install.sh | sh
ollama pull gemma4:e4b
git clone https://github.com/zurgace/gomihyu.git && cd gomihyu
```
Leave Ollama running (`ollama serve`, or it may already run as a background service
depending on your install). Sanity-check it, then see where it loaded:
```bash
ollama run gemma4:e4b "say hi in five words"
ollama ps
```
`ollama ps` should say `100% GPU` under PROCESSOR; a CPU/GPU split there means part of the model
runs on the CPU and replies are slower. On the RTX 2070 it loads 100% on the GPU at about 3.2GB
(with a 4096-token context). Once the bot has replied, CONTEXT should read 8192: the bot asks for
`OLLAMA_NUM_CTX` (default 8192) on every call, since her prompt can outgrow Ollama's default
4096 when people post long messages.

The earlier model, LFM2.5-2.6B, and the Modelfile that stopped it reasoning before every reply
are in `archive/lfm2.5/`.

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

**To stop her for the night**, press Ctrl+C (or say `gomi goodnight`, see [Her diary](#her-diary)).
She writes her diary before the bot exits, which takes a few seconds per channel; Ctrl+C again
skips it, and she catches up at the next start.

Running through `venv/bin/python` uses the venv without activating it, so it works the same in
bash, zsh or fish. (If you do activate it in fish, the command is `source venv/bin/activate.fish`.)

**`ModuleNotFoundError: No module named 'aiohttp'` (or `discord`)** means the Python running
the bot doesn't have the requirements installed. Either plain `python3` ran instead of the venv's,
or a system update (common on CachyOS/Arch) upgraded Python and left the venv behind. Rebuild it:
```bash
rm -rf venv && python3 -m venv venv && venv/bin/pip install -r requirements.txt
```

## How it behaves
- **Always replies when it's aimed at her:** an @mention, a Discord reply to one of her
  messages (even with the ping off), her name ("gomi", "Gomihyu") anywhere in the post, and
  sad news. The persona is instructed to fire back rudely in character if provoked, rather
  than staying polite.
- **Anything else, she chimes in only if it interests her**, like a friend in a group chat.
  A short extra model call rates the post 0–10 for how much she'd want to say something (her
  topics, someone bragging, plans without her, a funny line to add, a question to the whole
  chat) and she replies at `CHIME_IN_THRESHOLD` (default 6) or above. Raise it to make her
  quieter, lower it for chattier; `0` answers every message without the extra call. Each
  rating is in the console (`Interest 4/10 (chimes in at 6) in "...": staying quiet`), so
  you can see why she spoke or didn't. No cooldown.
- **Reacts instead of replying when words aren't needed.** See [Emojis](#emojis).
- **One reply at a time per channel.** If messages arrive while it's still writing a reply,
  it sends one follow-up afterwards that answers the latest chat, rather than one reply each.
- **Goes by Gomi, and calls people by their nicknames** (see [Memory](#memory)), or by their
  Discord handle when she doesn't know one. The chat log she sees labels everyone by handle
  (e.g. `kaz0: ...`), with a line listing the nicknames of the people in it. When a reply says
  `@kaz0` or `@Kaz` (handle, display name or nickname), the bot turns it into a real ping.
  Discord shows a ping as the person's server display name. The person she's replying to is
  never pinged, since they're already in the conversation: their name just loses the `@`. It
  never pings `@everyone`, `@here` or roles.
- **Joins in, not just one-liners.** Her prompt makes her an active member of the chat: she
  answers the newest message (a question gets a real answer), builds on what others said,
  gives opinions, and now and then asks something back. A quick jab or comeback is one short
  line; a question or a real discussion gets 2–4 sentences, never more. `MAX_REPLY_TOKENS` (default 200) caps a runaway reply, and
  one that hits the cap is cut back to its last full sentence.
- **Doesn't "think" before replying** (`OLLAMA_THINK=false`): for chat it only adds delay.
  Gemma 4 E4B only reasons when asked to. If a model thinks anyway, the console logs `... thinks
  before answering even with OLLAMA_THINK=false` once, and replies stop being capped at
  `MAX_REPLY_TOKENS` from then on, because the thinking counts against that cap and would
  crowd out the answer. Any `<think>` text that ends up in the answer itself is cut before
  posting. `OLLAMA_THINK=true` turns thinking on, uncapped.
- **Learns her voice from example chats.** Until a fine-tuned model carries her personality,
  each reply's prompt includes `FEW_SHOT_EXAMPLES` (default 8) made-up chats picked at random
  from `finetuning/gomihyu_seed.jsonl` (`EXAMPLES_FILE`), showing how Gomi talks. A new pick every
  reply keeps her from latching onto a few lines, and a reply that copies an example's line is
  regenerated, like one that repeats her own. `FEW_SHOT_EXAMPLES=0` turns them off; do that
  once a fine-tuned model is serving, since it was trained without them.
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
  like "@Gomihyu remember when...?". (What she picks up from ordinary chat on her own is in
  [Her diary](#her-diary), kept separately.)
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

## Her diary
When she's shut down for the night, she reads the day's chat and writes her diary, so she learns
from the server without anyone telling her "remember that":
- **During the day**, every message in the server's channels she can see (hers too) goes into a
  chat log on disk: `chatlogs/<date>/<channel id>.jsonl` (`CHAT_LOG_DIR`). DMs are never logged;
  owner commands aren't either, and posts you have her delete are taken out. The logs are kept
  (gitignored, they stay on your PC).
- **At shutdown** (Ctrl+C, a system stop, or you saying **`gomi goodnight`**: she reacts 💤, says
  goodnight in character, then the bot shuts down), she reads each channel's chat since her last
  entry and writes:
  - **a recap**: what happened, 1–3 sentences, as her diary ("Kaz started guitar lessons and Rex
    asked what song he's learning"), kept in `diary.json` (`DIARY_FILE`);
  - **notes on people** ("kaz0 is taking guitar lessons"), kept in `people.json` under "learned",
    next to (not mixed with) the notes people asked her to remember. Each note must come with the
    exact words it's based on, and the code throws out any note whose words aren't in the log, that's
    about someone who didn't talk, or that has a slur, so she can't just make things up about people.
    Each person keeps at most `MAX_LEARNED_PER_PERSON` (10); the oldest drop off.
  The console prints every recap and note as it's written. A stretch of chat with fewer than two
  messages from people is skipped. If Ollama isn't running, the chat stays unread for next time.
- **If the bot didn't shut down cleanly** (crash, terminal closed), she catches up on the unread
  chat at the next start, in the background.
- **The next day**: when she replies, her prompt has the last `RECAP_DAYS` (3) days of recaps for
  that channel, and what she learned about the person she's answering. After a restart she also
  picks the conversation back up: each channel's last messages from the log, if they're from the
  last `HISTORY_RELOAD_HOURS` (12).
- To fix or remove a note or recap, stop the bot, edit `people.json` / `diary.json`, start it again.

## How the server shapes her
Her Satania persona slowly melds with the server, so she ends up fitting in (everyone in the
server agreed to their chat being used for this). It happens in two places:

**Every night, in her prompt** (at the same shutdown as her diary):
- **Her replies that landed** are kept in `earned_examples.jsonl` (`EARNED_FILE`) with the chat
  before them. A reply landed if someone reacted to it (the bot logs reactions on her posts),
  answered it with a Discord reply, laughed right after ("lol", "lmao", 💀...), or answered her by
  name, and nobody told her to shut up. The code decides that, not the model. Match posts,
  goodnights and slur stand-ins don't count.
- They **join her example chats**, replacing the Satania ones bit by bit: the more she's earned,
  the more of the 8 examples are her own real ones (all the way at `MELD_FULL_AT`, 200). At least
  `MELD_ANCHOR` (30%) always stay Satania, so she's still recognizably Gomi.
- **A note on how the server talks** (humor, slang, running jokes, what gets a laugh) is updated
  from the day's chat when there were at least `VIBE_MIN_MESSAGES` (10) new messages: it keeps what's
  still true, adds what's new, drops what's gone stale. It goes in her prompt ("let it rub off on
  you, but you're still you") and is kept in `diary.json`.
The console prints the replies that landed and the updated note at each shutdown.

**Every training run** (on the rented GPU, see [Training data](#training-data)), the dataset mixes
the Satania examples with the server: her landed replies, and people's own messages from the chat
logs as examples of how the server talks. Each run tilts further: 70% Satania for run 1, then 55%,
40%, and 30% from run 4 on, where it stays.


## Owner commands: deleting her posts, muting her, putting her to bed
The bot's owner can make her delete her own posts or go quiet, and this overrides her persona:
the bot does it in code, so the model never sees the command and can't talk back. Say it to her
(her name, an @mention, or a Discord reply to one of her posts). Who counts as the owner is at
the end of this section.

### Deleting her posts
- `gomi delete that` / `gomi delete it` / `gomi del`: her newest post in the channel. As a
  Discord reply to one of her posts, just `delete` removes that post.
- `gomi delete your last 3 messages`: her 3 newest posts.
- `gomi delete all your messages` / `gomi delete those`: all of hers among the channel's last
  `DELETE_SCAN` (default 200) messages.

She reacts 🗑️ when done (🤷 if there was nothing of hers to delete), doesn't reply, and the
deleted posts and the command leave her chat log, so she can't bring them back up. "Don't
delete that" and "I'll delete that" aren't commands.

### Muting her
- `gomi mute`: silent in this channel for `MUTE_MINUTES` (default 30).
- `gomi mute for 10 minutes` / `gomi mute 2h` / `gomi mute for an hour`: for that long.
- `gomi mute until i say so` / `gomi mute forever`: until you unmute her.
- `gomi unmute`: talking again.

She reacts 🔇 / 🔊. While muted she keeps following the chat (so she has context when she's
back) but posts nothing and adds no emoji reactions; anyone who talks to her gets a 🤐 so they
know she's muted, not broken. "Remember that..." still saves (📝). A reply she was in the middle
of writing is dropped. It's per channel: muting her in one channel leaves the others alone.
Only the word "mute" counts, so banter like "gomi stfu" doesn't mute her, and "don't make me
mute you" / "I'll mute you" aren't commands. A restart unmutes her everywhere.

### Quiet mode (the softer mute)
- `gomi quiet mode` / `gomi only talk when spoken to`: in this channel, she only answers people
  talking to her (her name, an @mention, a Discord reply to her post). Same times as a mute:
  `gomi quiet mode for an hour`, `gomi quiet mode until i say so`; default `MUTE_MINUTES`.
- `gomi quiet mode off` / `gomi unmute` / `gomi you can talk again`: back to normal.

She reacts 🤫. In quiet mode she doesn't chime in on her own (the interest check doesn't even
run) and doesn't reply to sad news that isn't aimed at her, but still adds emoji reactions and
posts her Melee match results. A mute and quiet mode replace each other: whichever you said last
counts. "Be quiet" and "stfu" are banter, not commands; so are "don't make me put you in quiet
mode", "I'll put you in quiet mode" and questions about it.

### Putting her to bed
`gomi goodnight` (or `gomi go to sleep` / `gomi gn` / `gomi bedtime`): she reacts 💤, says goodnight
in character (not while muted), and the bot shuts down after writing her diary; see
[Her diary](#her-diary). "Gomi, say goodnight to Kaz", questions and "I'll..." aren't commands.

### Who counts as the owner
Whoever owns the bot application in the Developer Portal (you, if you
created it; the console prints the name at startup), plus any Discord user ids in
`OWNER_USER_IDS` (comma-separated). Anyone else asking just gets a normal, in-character
reply. No extra Discord permission is needed: a bot can always delete its own messages. Finding
older posts uses Read Message History, which the bot already has.

## Melee results
[AI-Melee](https://github.com/zurgace/aimelee) can have Gomi play Mario or Fox against you in Super
Smash Bros. Melee (its "Gomihyu takes over P2" option). She talks about it here, **only once a
match is over**:
- **While she plays**, she stays quiet in Discord. The trash talk she writes in AI-Melee isn't
  posted; the bot holds on to it for her match post.
- **After every match**, she tells the chat how it went in one message, in her own words: she gloats
  if she won, and blames anything but you if she lost. She may call back one of the lines she said
  during the match.

**Setting it up:** say **"gomi post melee here"** (as the bot's owner) in the channel you want. She
reacts 🎮, and remembers it across restarts. "gomi stop posting melee" turns it off (🔕). That's all:
AI-Melee leaves her lines in `~/.local/share/gomihyu/melee-outbox`, which the bot checks every 5
seconds. Both programs run on the same PC.

- She calls you by your nickname if she has one, else your display name. If someone else plays
  her, put their name in `MELEE_PLAYER`.
- Her posts are normal messages of hers: they're in her chat history, so replies about the match get
  answered in context, and "gomi delete that" and muting work as usual.
- While she's muted in that channel, her Melee posts are dropped. Quiet mode doesn't stop them: a
  match post isn't butting in.
- A match she can't write about yet (Ollama down) waits for the next check. A match older than
  `MELEE_MAX_AGE_MINUTES` (30) is dropped unposted, so a bot started late doesn't dump old stuff
  into the channel. Trash talk from a match that never finished is forgotten.
- With no channel picked yet, everything waits (AI-Melee keeps the newest 20, and warns that her posts
  are piling up). The bot's console says which folder and channel it uses when it starts.
- `.env` overrides, rarely needed: `MELEE_OUTBOX` (another folder), `MELEE_CHANNEL_ID` (a channel to
  start with, until one is picked with the command).

## Training data
`finetuning/gomihyu_seed.jsonl` holds 58 hand-written example chats in Gomi's voice, one per line,
with the chat so far as `[handle, message]` pairs and the reply she should give:
```json
{"history": [["kaz0", "@Gomihyu wanna 1v1 me in valorant"]], "reply": "You dare challenge the Archdemon to combat, @kaz0? ..."}
```
The last `history` entry is the message being answered; put `@Gomihyu` in it to make it an
@mention. Earlier entries are chat context, and Gomihyu's own messages use the speaker `Gomihyu`.
Optional `"facts": [...]` and `"nicknames": {handle: nickname}` are rendered the way the bot does
at runtime. `finetuning/persona_guide.md` is the style reference for writing more.

Right now the bot shows a few of these to Gemma in every prompt (see **Learns her voice from
example chats** above), so adding good examples changes her voice without any training. They're
also the training set for a fine-tune:
```bash
venv/bin/python finetuning/build_dataset.py   # -> finetuning/train.jsonl (system/user/assistant chat format)
```
It builds each prompt with `persona.build_messages()`, the same function the bot uses at runtime,
so the model is trained on exactly the prompt format it's served (without the example chats).

**Melding with the server** ([How the server shapes her](#how-the-server-shapes-her)): for each
training run, build the data with `--meld` and the run's number:
```bash
venv/bin/python finetuning/build_dataset.py --meld --run 1   # the first run: 70% Satania
venv/bin/python finetuning/build_dataset.py --meld --run 2   # the next one: 55%, then 40%, then 30%
```
It mixes the seed (3 times over, `--seed-repeat`) with her landed replies and people's messages from
the chat logs, and prints what went in and the actual Satania share: early on, with little chat
logged, there may not be enough server data to reach the aimed-for share. `--persona-share 0.5` sets
the share by hand. The same run number always gives the same data. `train.jsonl` holds real chat:
it's gitignored, keep it that way.

Fine-tuning Gemma 4 E4B with QLoRA reportedly needs about 10GB of VRAM, more than the RTX 2070
has, so training will run on a rented GPU. Serving the result doesn't need bot changes: build it
into Ollama, point `OLLAMA_MODEL` at it, and set `FEW_SHOT_EXAMPLES=0`.

**Parked for then:** `archive/discord-pipeline/` turns your own Discord data export into training
data, so she learns to text like you. It reads public server channels only, never DMs, and
writes to its gitignored `data/` folder: `extract.py` cleans your messages, `backtranslate.py` has
the model write the friend messages each one was answering, and `build_dataset.py` renders them.
Each script's header explains how to run it. A Discord export (`Messages/`, `*.zip`) is
gitignored too.

## Known limitations at this scope
- A small model makes things up. Her prompt tells her what she can't do (she only sees the
  last few messages; she can't read or search history, look things up or do things later)
  and who she's answering, which helps, but she'll still bluff sometimes. Don't rely on her
  for facts; anything that must be right (memory, the slur filter) is handled in code.
- Text-only: it can't see images, only whatever caption/text comes with them. Image posts
  appear to her as `[image]`, and on their own they get a 👀-style reaction, not a reply.
- Her recent chat is picked back up from the chat log after a restart (last
  `HISTORY_RELOAD_HOURS`); older days reach her only as diary recaps.
- Single-server assumption: history, logs and recaps are keyed by Discord channel ID, so they
  naturally won't cross-contaminate between channels/servers.
