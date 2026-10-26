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
- CachyOS (Arch), fish shell; run things as `venv/bin/python ...`. After any change run `tests/run_all.sh`
  (29 suites, everything faked, on a temp copy of the repo; `tests/run_all.sh test_x.py` for one).
- `gemma4:e4b`: 3.2GB, 100% GPU at 8192 context. Every call sends the same `OLLAMA_NUM_CTX`, or Ollama
  reloads the model. Whatever serves her must fit the 2070 (do the VRAM math first); training runs on Kaggle.
- Vision works on the user's Ollama 0.34.2; re-run `tools/vision_check.py` after Ollama or model changes.
- Rejected: LFM2.5-2.6B (felt like "a response bot"; `archive/lfm2.5/`), Ternary Bonsai 2 27B (llama.cpp
  fork, too big), anime-girl-1.5B, Nemotron 3.5 Bolt E4B (a few words a reply without thinking, ~11s a reply
  with it, text only: not a good fit).

## Map
- `bot.py` (1,300 lines: grep it, don't read it whole): Discord client, all runtime flow, every setting.
  `persona.py`: the system prompt and every prompt builder; the training data is built with them too,
  so the prompt format changes only there.
- `chime.py` reads the room · `shape.py` each reply's shape · `reactions.py` + `emojis.py` · `vision.py` ·
  `commands.py` owner commands · `censor.py` + `slurs.txt` · `tray.py` runs her from the system tray.
- `memory.py` people.json · `chatlog.py` · `diary.py` · `meld.py` landed replies, vibe note · `melee.py`.
- `finetuning/`: `gomihyu_seed.jsonl` (108 made-up chats, training only), `persona_guide.md` (read it
  before writing seed chats), `build_dataset.py`, `weekly.py` + `kaggle_train.py`. `archive/`: parked.

## Locked in (ask before changing)
- She answers every post aimed at her (@mention, a reply to her, her name, sad news). Anything else gets
  one `chime.py` read (a failed read means quiet): she speaks at `CHIME_IN_THRESHOLD` (user runs 8),
  reacts at `REACT_THRESHOLD` (8), never at random. Its interest anchors are the user's (6–7 background
  she leaves alone, 8–9 demands a response, 10 a question to the room): chiming in a lot made her
  annoying. No cooldown.
- Reply length and shape are code's job (`shape.py`). Don't bring back "at most 2 sentences" or "don't
  reuse topics" (they made her a one-liner machine; "don't repeat your own lines" + the `REPEAT_WORDS`
  retry handle repetition), or "three max" / "stay quiet" (the read decides).
- Persona: a friend first; the Archdemon act is a quick line, never a speech. She answers plainly first and
  never lectures or talks down; insulted, she fires back rudely in character. A deadpan chaotic streak: at
  most one calm odd line, none for someone sad. Not everything is about her: a chime-in adds to the talk.
- Small models confabulate: what must be true lives in code (memory, slur filter, emoji picks,
  quote-checked diary notes, no names from the seed's made-up chats).
- A reply with a `slurs.txt` word (it includes "bitch(es)") becomes `:goonerstare:`. Other swearing stays:
  the server doesn't want her more PG.
- Inspired by Satania, written fresh: a dozen-ish show quotes as style reference at most, never bulk
  dialogue. Streamers' lines are fine.
- No channel summaries (out of scope), no RAG (5 people), no seed chats in her prompt (melon bread out of
  nowhere; `SEED_EXAMPLES=true` brings them back).
- Server chat trains her (the members agreed); DMs never. Never commit chat logs, training data or the
  user's Discord export (`Messages/`, `*.zip`).

## Open / to watch
- The weekly fine-tune has never run for real. Unknowns: Kaggle honoring `NvidiaTeslaT4`,
  Unsloth/transformers pins, Kaggle disk for the merge, llama.cpp converting Gemma 4, Ollama 0.34.2
  running that GGUF with the stock template, VRAM with gomi-wN and stock loaded together.
- Open: whether training also mixes in the parked Discord-export pipeline (the user's lowercase bursts,
  DMs excluded); likely 1–3k examples before a first run, which the user checks first.
- Live tuning: the `Read ... react n/10` / `Interest n/10` log lines → the thresholds, then `chime.py`'s
  anchors.
- Not judged live yet: reply shapes (jabs one line? emoji / asking back at most 1 in 3?), then
  `OLLAMA_THINK=true` on stock gemma4:e4b (a fine-tune trained without it may not think well), the
  friend-first persona, the date, melon-bread frequency, nicknames and "who am I?", vision, the slur
  filter, and (once a fine-tune serves her) the shouted corrections staying rare.
