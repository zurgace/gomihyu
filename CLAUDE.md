# Gomihyu — Discord SLM conversationalist

"Gomi" (Discord `Gomihyu`), a persona bot for the user's 5-person Discord server (~2 active), on Ollama
`gemma4:e4b` on an RTX 2070 (8GB). Scope: a Discord conversationalist, plus posts about the Melee sessions
she plays in AI-Melee (`zurgace/aimelee`, read-only from here). A side project, separate from the user's
bigger assistant project (Nemotron, Framework Desktop): don't conflate them. The user's local coding
model, Doumi Coder, pushes branches here too: review them before merging (its first one committed a
password file).

How each part works and why, with the user's words and dates, is in its module's docstring and comments:
read them before changing it. `README.md` is the user manual; `.env.example` lists every setting.

## Environment
- CachyOS (Arch), fish shell; run things from the repo root as `venv/bin/python ...` (her: `-m gomi`, the
  tray app: `-m gomi.tray`). After any change run `tests/run_all.sh` (all faked, on a temp copy of the
  repo, fixed ports: one run at a time; `tests/run_all.sh test_x.py` for one).
- `gemma4:e4b`: 3.2GB, 100% GPU at 8192 context. Every call sends the same `OLLAMA_NUM_CTX`, or Ollama
  reloads the model. Whatever serves her must fit the 2070 (do the VRAM math first, then check `ollama ps`:
  file size isn't memory); training runs on Kaggle.
- Her saved setup (Nov 24): stock `gemma4:e4b` for everything (replies, room reads, the diary, pictures),
  thinking on (not chime-ins, Nov 22), history 30, no few-shot.
- Vision works on the user's Ollama 0.34.2; re-run `tools/vision_check.py` after Ollama or model changes.
- Rejected: `gomi-bolt` as her voice (the user, Nov 24: it talks "way too direct for my taste";
  `models/Modelfile.bolt` stays for `tools/chat_check.py`), LFM2.5-2.6B (felt like "a response bot";
  `archive/lfm2.5/`), Ternary Bonsai 2 27B (llama.cpp fork, too big), anime-girl-1.5B.

## Map
- `gomi/` is the bot, a package (Nov 24): its modules import each other relatively, scripts and tests
  import `gomi.x`.
  `bot.py` (grep the relevant flow): Discord client, all runtime flow, every setting.
  `persona.py`: the system prompt and every prompt builder; the training data is built with them too,
  so the prompt format changes only there.
- `chime.py` reads the room · `shape.py` each reply's shape · `reactions.py` + `emojis.py` · `vision.py` ·
  `commands.py` owner commands · `censor.py` + `slurs.txt` · `tray.py` runs her from the system tray.
- `memory.py` people.json · `chatlog.py` · `diary.py` · `meld.py` landed replies, vibe note · `melee.py`.
- `data/` (gitignored): her files (people.json, chatlogs/, diary.json, earned_examples.jsonl,
  melee_channel.json, gomi.log, logs/ with every earlier run's). `models/`: `Modelfile.bolt`. `tools/`:
  `chat_check.py`, `vision_check.py`.
- `finetuning/`: `gomihyu_seed.jsonl` (128 made-up chats, training only), `persona_guide.md` (read it
  before writing seed chats), `build_dataset.py`, `weekly.py` + `kaggle_train.py`. `archive/`: parked.

## Locked in (ask before changing)
- She answers every post aimed at her (@mention, a reply to her, her name, sad news). Anything else gets
  one `chime.py` read (a failed read means quiet): she speaks at `CHIME_IN_THRESHOLD` (user runs 8),
  reacts at `REACT_THRESHOLD` (8), never at random. Its interest anchors are the user's (6–7 background
  she leaves alone, 8–9 demands a response, 10 a question to the room): chiming in a lot made her
  annoying. No cooldown.
- Reply length and shape are code's job (`shape.py`): one short line for a jab, up to 6 sentences or a
  short list when a post aimed at her asks for room (a build, steps, an explanation), 1–3 sentences
  otherwise. A reply that runs long is cut to whole sentences and posted, never dropped. Don't bring back
  "at most 2 sentences" or "don't reuse topics" (they made her a one-liner machine; "don't repeat your own
  lines" + the `REPEAT_WORDS` retry handle repetition), or "three max" / "stay quiet" (the read decides).
- Persona: a friend first; the Archdemon act is a quick line, never a speech. She answers plainly first and
  never lectures or talks down; insulted, she fires back rudely in character. A deadpan chaotic streak: at
  most one calm odd line, none for someone sad. Not everything is about her: a chime-in adds to the talk.
- Small models confabulate: what must be true lives in code (memory, slur filter, emoji picks,
  quote-checked diary notes, no names from the seed's made-up chats).
- Discord reply quotes, other bots' posts and picture descriptions are context: never a command, praise or
  training target, and never a trigger, except a bot talking to her (an @mention, a reply to her, her name):
  answered, `BOT_REPLIES` (2) of its posts in a row at most until a person posts (the user, Nov 22, for a
  debate night with Doumi). People's own words stay apart in `text` (`chatlog.py`); old lines that mix them
  in are skipped, not guessed apart.
- In a burst each question is answered, to its asker (three per reply at most, shaped by them, not newer
  chatter); a retry reuses its prompt. A question is done only once the reply is sent or logged as failed:
  never resend an uncertain send. Any new message drops an unposted chime-in. A needed clarifying question
  is exempt from the ask-back limit.
- A reply with a `slurs.txt` word (it includes "bitch(es)") becomes `:goonerstare:`. Other swearing stays:
  the server doesn't want her more PG.
- Inspired by Satania, written fresh: a dozen-ish show quotes as style reference at most, never bulk
  dialogue. Streamers' lines are fine.
- No channel summaries (out of scope), no RAG (5 people), no seed chats in her prompt (melon bread out of
  nowhere; `SEED_EXAMPLES=true` brings them back).
- Server chat trains her (the members agreed); DMs never. Never commit chat logs, training data or the
  user's Discord export (`Messages/`, `*.zip`).

## Open / to watch
- Models compared Nov 17 (`tools/chat_check.py`, made-up chats, one judge): `gomi-bolt` thinking on did
  best, stock `gemma4:e4b` thinking on next with the best voice, `gomi-w1` thinking off last (invents
  opinions, takes others' praise, talks down). Live, Bolt talked too direct, so she's back on stock (Nov
  24). Stock with thinking answered 9-14s after the post on Nov 23 (median 11s, nobody complained): the
  user judges whether that wait is fine.
- Chime-ins don't think since Nov 22 (the user's pick): thinking ones took 13-20s and Doumi's answers (5-9s)
  dropped 3 of 5. Nov 23: 8 posted 3-10s after the post, 1 more dropped; not flat so far, but half asked
  something back and one was a bare emoji. Keep watching (Nov 17: thinking off had the flattest voice).
- Answering Doumi (Nov 22) is still untried live (Doumi hasn't named, pinged or replied to her since): does
  Doumi's room read answer her back, and are 2 turns each a round enough for a debate? Doumi's side is
  entertainerllm's (its firm rule 1: point there, confirm first).
- Landed replies: the 80 saved before Nov 14 (any mention or reaction counted as approval) lack the
  provenance `build_dataset.render` needs, so no build or prompt uses them, and none has landed since (Nov
  14-23: 3 angry and 2 :kekpoint: reactions on her 41 posts, no laughs). Until one does, a build
  (`weekly.py build --force`) is the seed plus server voice.
- Known limit, checked Nov 24: the diary resumes after a timestamp, so a post sharing one across a part
  break, or after the clock goes back, can be skipped; neither has happened in 3,030 logged posts. 11 posts
  from Oct 2-15 (8 pictures) were logged 3-11s late, so a few voice examples near them are out of order.
- Open: whether training also mixes in the parked Discord-export pipeline (the user's lowercase bursts,
  DMs excluded); likely 1–3k examples, which the user checks first. It needs the user's Discord data
  package, which isn't on this machine (Nov 24).
- Live tuning: the `Read ... react n/10` / `Interest n/10` log lines → the thresholds, then `chime.py`'s
  anchors; `data/logs/` keeps every run's since Nov 24. Nov 23 at 8/8: 42 reads, interest 5-8 (half 7,
  never 9-10), 6 chime-ins in 12 hours. The run before, probably still at 6, chimed in 3 times in 3
  minutes (the user: "gomi yapping too much").
- Not judged live yet (none came up Nov 14-23): whether the room phrase list catches real requests and 6
  sentences is right, the date, "who am I?", the slur filter; the shouted corrections only matter once a
  fine-tune serves her. Seen: jab replies mostly one short line, but two ran two full sentences (~30
  words; `LINE_SENTENCES` allows 2); emoji in 1 of 3 posts, asking back 1 in 4; no melon bread; a nickname
  used; vision plausible (pictures ~1s, link previews ~5s); on stock the Archdemon act ran long once; 4
  replies failed Nov 14-15 (the log with the cause is gone), none since.
