# Gomihyu — Discord SLM Conversationalist

## What this is
"Gomi" (Discord username `Gomihyu`), a persona bot for the user's 5-person Discord server (~2 active),
on a small local model: Ollama `gemma4:e4b` on an RTX 2070 (8GB). A side project and dry run before a
separate, bigger assistant project (Nemotron, Framework Desktop): don't conflate them. Scope is a
Discord conversationalist, plus (user, 2026-09-29) posting about the Melee sessions she plays in
AI-Melee (`zurgace/aimelee`, read-only from here).

## Environment
- CachyOS (Arch), fish shell. Python 3 venv; run things as `venv/bin/python ...`.
- `gemma4:e4b`: ~4.5B effective params; `ollama ps` shows 3.2GB, 100% GPU at 4096 and 8192 context.
  Every call sends the same `OLLAMA_NUM_CTX` (8192), or Ollama reloads the model between calls.
  Thinking is off by default. `OLLAMA_THINK=true` makes only her own writing think (replies, Melee,
  goodnight; never reads, diary, vision), uncapped by `MAX_REPLY_TOKENS`, with the thought logged
  (user, 2026-10-04: trying it for less samey replies; not judged yet). Vision works on the user's
  Ollama 0.34.2 (`tools/vision_check.py`; ollama#18560's blank-image bug hits some setups, so re-run it
  after Ollama/model changes).
- Rejected: LFM2.5-2.6B (felt like "a response bot"; always reasoned; kept in `archive/lfm2.5/`),
  Ternary Bonsai 2 27B (needs a llama.cpp fork, too big for 8GB), anime-girl-1.5B.
- Serving must fit the 2070 (check VRAM math before suggesting a model). Training runs elsewhere.

## Repo map
- `bot.py` — Discord client, all runtime flow, every `.env` setting (documented in `.env.example`).
- `persona.py` — system prompt + prompt builders (`build_messages`, session, goodnight). The dataset
  builders use it too, so training prompts match runtime prompts: change the format only here.
- `chime.py` — reading the room for a post not aimed at her: {read, interest 0–10, react 0–10, emoji}.
- `shape.py` — each reply's shape, decided in code: one line or 2–4 sentences, ask back / emoji or not.
- `reactions.py` — which posts get only a reaction, sad news, names_her. `emojis.py` — every emoji + "when".
- `vision.py` — what she looks at, image prep, describe prompt, `[image: ...]` labels, avatar fingerprint.
- `memory.py` (people.json: facts, nicknames, learned notes) · `chatlog.py` (chatlogs/) · `diary.py`
  (nightly recaps/notes, diary.json) · `meld.py` (landed replies, voice examples, vibe note, schedule) ·
  `melee.py` (AI-Melee outbox → session facts) · `commands.py` (owner commands) · `censor.py` + `slurs.txt`.
- `finetuning/` — `gomihyu_seed.jsonl` (86 original chats, Satania-style + lowercase; training only),
  `persona_guide.md` (voice reference they were written from), `build_dataset.py`, `weekly.py` +
  `kaggle_train.py` + `check_chats.jsonl` (weekly fine-tune), state in gitignored `runs/`.
- `archive/discord-pipeline/` — parked: turns the user's Discord export into training data (never run).
- `tests/run_all.sh` — 28 suites, everything faked (Ollama, Discord, Kaggle, Unsloth), run on a temp copy
  of the repo. Run it after any change; `tests/run_all.sh test_x.py` for one.

## Locked-in decisions (don't change without asking)
**Talking**
- Always replies to posts aimed at her: @mention, a Discord reply to her (ping on or off), her name
  outside links, sad news. Fires back rudely in character when insulted.
- Everything else: one `chime.py` read; she replies at `CHIME_IN_THRESHOLD` (default 6; user runs 8).
  Failed read = quiet. No cooldown (slow server); ask before adding one.
- One reply in flight per channel; posts arriving meanwhile get ONE follow-up on the newest chat.
- Reply length matches the moment: a jab is one line, a question/discussion 2–4 sentences, never more.
  She answers questions for real, builds on others, asks back only now and then, never opens by
  echoing the message. Code decides which, per reply (`shape.py`; user, 2026-10-04: every reply had
  become emoji + sentence ×5, ending in a question): ≤ `ONE_LINE_MAX_WORDS` (6) words, no question,
  not sad news → told "one short line" (cut after 2 sentences), else 2–4 (cut after 4; bits under 3
  words don't count). Told not to ask back / not to use an emoji if one of her last 2 messages did; at
  most one emoji per post, enforced. Her old landed replies get the same caps (`tidy`). Don't bring
  back "at most 2 sentences" or "don't reuse topics" (that made her a one-liner machine); repetition is
  handled by "don't repeat your own lines" + the `REPEAT_WORDS` retry.
  `MAX_REPLY_TOKENS` (200) caps a runaway reply (trimmed to a full sentence); if a model thinks anyway,
  replies go uncapped (thinking ate the cap and she went silent once).
- Friend first, Archdemon second (user, 2026-10-04: a date question got two paragraphs of put-downs;
  "converse properly instead of providing verbose explanations", be useful, follow along). She answers
  plainly first (yes/no first), says "can't" in one line, plays along, teases with affection, never talks
  down or lectures; the act is a quick line, never a speech. The seed's last 8 chats show this.
  Diary notes on someone are never to poke fun at them.
- Goes by Gomi; calls people by nickname, else handle. "@name" in a reply becomes a real ping, except for
  the person she's answering (code strips it; she used to @ them every reply). Never @everyone/roles.
- The prompt states her limits (sees only recent messages, can't search history or browse; knows plenty),
  the local date and time (not in training data), and who "I" is in the message she answers. Channel
  summaries are out of scope; she declines.
- Only real people (user, 2026-10-04: she told someone to "go bother @kaz0", a seed chat's handle): a
  reply naming someone from the seed's made-up chats (handles any case, nicknames as written; checked
  whether or not the seed is in her prompt, since it trains her) or an @name nobody has is redone once,
  then loses those sentences. Real = in handles (whole chat log, the app owner, anyone who posts),
  people.json, or named by someone else in the channel's log ("who's kaz0?" can be answered).
- Small models confabulate: anything that must be true lives in code (memory, slur filter,
  constrained emoji picks, quote-checked diary notes).
- A reply with any `slurs.txt` word (whole words, plural s) is replaced entirely by `:goonerstare:`,
  also in her history. Swearing is not filtered (the server doesn't want her more PG).
- Persona: inspired by an existing character (Satania), renamed and written fresh. Original writing
  only; a dozen-ish quotes as style reference is fine, bulk verbatim dialogue never.

**Reactions** (a response, never a random roll)
- Same `chime.py` call scores `react` on its own scale (0–2 chatter/logistics/questions/plans, 3–5
  fine, 6–7 she notices, 8–10 really funny / big win / cute past her act / cursed / painful fail / sad).
  She reacts only at `REACT_THRESHOLD` (8) (user, 2026-09-30: she reacted to every post).
- Posts that don't need words (picture, sticker, bare link, emoji-only, ≤ `REACT_ONLY_MAX_WORDS` 2
  words without "?") get that reaction as her whole response, or nothing. Chat she doesn't answer
  (`REACT_TO_CHAT`) and posts she chimes in on (`REACT_WHEN_REPLYING`) get it too. Posts aimed at her
  aren't read, so no reaction. Her last 2 picks per channel are left out of the options.
- Media she couldn't see → 👀 / :goonerstare:, never a judgment. Sad news → reply + `:catsad:`.
- She may write in-text custom emojis as `:name:`, one per message at most (`shape.py`);
  `aryanosaka`/`goonerstare` are reaction-only.

**Owner commands** (owner = app owner/team + `OWNER_USER_IDS`; parsed in code, override the persona)
- "gomi delete that / your last N / all your messages" → deletes her posts, 🗑️, no reply, removed from
  her log. "gomi mute [for X | until i say so]" → silent in that channel (🔇, 🤐 to people talking to
  her), "unmute" 🔊; only the literal word "mute" ("gomi stfu" is banter). "gomi quiet mode" → only
  answers posts aimed at her (🤫); reactions, Melee and diary posts continue. "gomi goodnight" → 💤,
  diary written + posted, goodnight line, shutdown. "gomi post melee here" / "stop posting melee"
  (🎮/🔕). "gg" ends a Melee session. Negations, "I'll ...", questions aren't commands. Mute/quiet
  are in memory (restart clears).

**Memory, diary, melding**
- "remember that ..." aimed at her → stored verbatim for its author (📝); nicknames stored on the person
  they're about. Only the replied-to person's facts go in the prompt. No RAG (5 people).
- Every server message is logged (`chatlog.py`; never DMs or owner commands; deleted posts removed).
  At shutdown (Ctrl+C/SIGTERM/goodnight; catch-up at next start) she writes her diary: per-channel
  recaps (last `RECAP_DAYS` 3 in her prompt) and notes on people, kept only if their quote is really
  in the log. History reloads from the log after a restart (`HISTORY_RELOAD_HOURS` 12).
- New recaps are posted in their own channel (user, 2026-10-04; `POST_DIARY`): on goodnight before
  the line, after a Ctrl+C at the next start (Discord's closed by then). Never notes on people (they
  come from every channel). Muted / can't post → dropped. The post is only sent: never in the chat
  log or her history, so she doesn't answer it, recap it again or meld from it (user asked).
- Melding (members agreed to their chat being training data): nightly, her replies that "landed"
  (reaction, Discord reply, a laugh, her name said back; no put-down) are her few-shot examples; a
  ≤6-line vibe note on how the server talks goes in her system prompt. Training data mixes seed ×3 +
  landed + people's messages (`meld.voice_examples`).
- The seed left her prompt (user, 2026-10-04: melon bread out of nowhere; her defiance is in the system
  prompt). `SEED_EXAMPLES=true` brings back the old mix, landed replies replacing seed ones down to
  `MELD_ANCHOR` 30%. It stays in training as her persona anchor (her only persona data there). Same
  day, user: cut the 4 chats that brought up melon bread out of nowhere (the 3 about food stay), added
  24 in the server's lowercase texting style (`persona_guide.md`, "Texting style").

**Vision**
- Pictures, GIFs (first frame), stickers and link previews are described once (cached), and the
  description replaces the placeholder in her chat log. Text in a picture never becomes a memory.
- Her own avatar (user, 2026-10-01; a grey hamster with furrowed brows): fingerprinted at login (dHash
  on 4 backgrounds: it's a transparent cut-out) and described once (or `AVATAR_DESCRIPTION`); every
  prompt says it's her face; a posted copy is labelled "Gomi's own avatar" (≤12 of 64 bits). A
  picture of her alone still only gets a reaction.

**Melee** (one post per session; user, 2026-09-30: "only post once I close the game or tell gomi GG")
- AI-Melee writes match/taunt/session_end JSON to `~/.local/share/gomihyu/melee-outbox`. Taunts are
  held, never posted live. A session ends on `session_end`, the owner's "gg", or 20 idle minutes; then
  one 3–5 sentence post: what decided it, whether her drill paid off, next goal as a scheme (never an
  apology). Muted → dropped; model down → retried after 60 s; older than 120 min → dropped.

**Fine-tuning**
- Until a fine-tune serves her, her voice comes from the system prompt and up to `FEW_SHOT_EXAMPLES`
  (8) of her landed replies per reply.
- LoRA/QLoRA with Unsloth on Kaggle's free T4 (not the 2070: ~10GB+ needed). `finetuning/weekly.py`
  (user, 2026-09-29): build → upload → fetch → install → check → switch, `all` never switches. Every
  run trains stock Gemma again on all data (never last week's model); the seed share goes 70% → 30%
  over `MELD_RUNS` (11) runs; weeks with < `WEEKLY_MIN_NEW` (50) new examples are skipped; each run
  is kept as `gomi-wN`; the Kaggle data is deleted after download. The fine-tune is a text-only GGUF,
  so switch points `VISION_MODEL` (and `TASK_MODEL`, if both fit on the GPU) at stock gemma4:e4b.
- Never commit training data or the user's Discord export (`Messages/`, `*.zip`); DMs are never used.

## Open questions
- Whether training also mixes in the parked Discord-export pipeline (user texts in lowercase bursts;
  voice "like the user" was wanted, DMs excluded). Target size before a run: likely 1–3k examples.
- The user was to check the collected data "later that week" (from 2026-09-29) before a first run.

## Next steps / to watch
1. First weekly run, step by step (never run for real). Unknowns: Kaggle honoring `NvidiaTeslaT4`,
   Unsloth/transformers pins, Kaggle disk for the merge, llama.cpp converting Gemma 4, Ollama 0.34.2
   running the converted GGUF with the stock template, VRAM with gomi-wN + stock loaded together.
2. Live tuning: `Read ... react n/10` / `Interest n/10` log lines → `CHIME_IN_THRESHOLD`,
   `REACT_THRESHOLD`, then the anchors in `chime.py`.
3. Reply shapes live (`shape.py`, 2026-10-04): jabs get one line? Emoji / asking back at most 1 in 3
   feels right? Then `OLLAMA_THINK=true` for a while: more varied replies, worth the seconds? Judge it
   on stock gemma4:e4b (a fine-tune trained without thinking may not think well).
4. Live checks not done yet: the friend-first persona (still her, or too tame?), the date, melon-bread
   frequency, nicknames and "who am I?", vision quality and speed, slur filter. Checked live (user,
   2026-10-04): reactions at 8, reacting when chiming in, her avatar, diary and melding output
   (melding is slow only because the server is).
