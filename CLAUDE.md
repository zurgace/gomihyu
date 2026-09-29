# Gomihyu — Discord SLM Conversationalist

## What this is
A small-model (Gemma 4 E4B) Discord bot, "Gomihyu," running locally via Ollama on an
RTX 2070 (8GB VRAM). This is a standalone side project — a dry run of Discord +
personality plumbing before a much larger, separate local assistant project
(Nemotron-based, on a different machine — a Framework Desktop) comes online. Don't
conflate the two: this repo is scoped to just being a Discord conversationalist,
nothing more, until told otherwise. (Told otherwise once, 2026-09-29: she posts about the Melee
matches she plays in AI-Melee; see `melee.py` under Current state.)

## Environment
- OS: CachyOS (Arch-based Linux)
- GPU: RTX 2070, 8GB VRAM — every model/training decision here has to fit this
- Inference: Ollama serving `gemma4:e4b` (Ollama's official tag; `OLLAMA_MODEL` in `.env`).
  User switched from LFM2.5-2.6B on 2026-09-26 because it felt like "a response bot, not an
  AI" (Liquid built it for agents/tool calling). Gemma 4 E4B: ~4.5B effective params (8B with
  per-layer embeddings), ~5GB at Q4_K_M; Ollama's tag is listed at ~9.6GB (bundles image + audio
  encoders). Confirmed 2026-09-27 on the 2070: `ollama ps` shows 3.2GB, 100% GPU, at both 4096 and
  8192 context (sliding-window attention keeps its cache small). The bot asks for `OLLAMA_NUM_CTX` (8192) on every
  call: the prompt (system prompt + 8 example chats + 12 messages) is ~1.6–2.5k tokens normally,
  but long posts can pass 4096, which Ollama silently cuts. Every call must send the same value or
  Ollama reloads the model between the reply and emoji-picker calls. Thinking is off unless
  requested (a `<|think|>` token in the system prompt).
  Rejected: Ternary Bonsai 2 27B (needs PrismML's llama.cpp fork, stock Ollama 0.34.2 can't load
  it, 5.95GB of weights is too tight for 8GB, and it's a reasoning model).
- LFM2.5-2.6B history, kept in `archive/lfm2.5/`: it's a pure reasoning model whose template
  always opens `<think>`, so `think: false` did nothing (~1000 tokens, 8–13s per reply). The
  archived `Modelfile` fixed that with a template ending in an empty, closed think block.
- Python 3, using `discord.py`, `aiohttp`, `python-dotenv`

## Current state
- `bot.py` / `persona.py` / `requirements.txt` / `.env.example` — working Discord bot
  that talks to Ollama. Running live on the server (replies and memory confirmed working;
  the emoji rework, prompt fixes and slur filter not yet tested live).
- `persona.py` — the system prompt AND the prompt format (`format_line`, `build_messages`).
  Both the bot and any dataset builder use it, so training prompts match runtime prompts
  exactly. Change the format there, never in only one place.
- `emojis.py` — every emoji she uses (unicode + this server's custom ones) with a "when to use
  it" note; the model only ever sees names + notes. `reactions.py` — when a post gets a
  reaction instead of a reply, and the constrained emoji-picker prompt.
- `censor.py` + `slurs.txt` — a reply containing any slur (whole words, optional plural s) is
  replaced entirely by the `:goonerstare:` emoji (`SLUR_STANDIN`), also in her chat history.
  Swearing is deliberately not filtered; the server doesn't want her more PG.
- `memory.py` — person memory: "remember that ..." parsing + `people.json` store (asked-for facts,
  nicknames, and her diary's "learned" notes, kept apart).
- `chatlog.py` — every server-channel message (hers too) on disk, `chatlogs/<date>/<channel>.jsonl`;
  never DMs or owner commands; deleted posts taken out. Kept (user choice), gitignored.
- `diary.py` — her diary: prompt, `format` schema and checks for the nightly write-up, and `diary.json`
  (recaps, the vibe note, how far each channel's log has been read).
- `meld.py` — how the server slowly shapes her persona: which of her replies landed, which messages
  are the server's voice, the example-chat mix, the vibe note, the training-run schedule.
- `chime.py` — whether she chimes in on a post not aimed at her: the 0–10 interest prompt,
  its `format` schema and parsing.
- `commands.py` — owner commands, parsed in code: `delete_request` ("gomi delete that" /
  "your last 3 messages" / "all your messages"), `mute_request` ("gomi mute" / "for 2 hours" /
  "until i say so"), `quiet_request` ("gomi quiet mode") and `unmute_request` (ends either).
- `finetuning/` — the "Satania" seed, active again (user, 2026-09-26: reuse it until a rented
  GPU is set up for training Gemma): 58 original synthetic exchanges (`gomihyu_seed.jsonl`), the
  voice guide they were written from (`persona_guide.md`: paraphrased wiki bio + tonal patterns,
  no copied dialogue), and `build_dataset.py` (renders them through `persona.build_messages`).
  Nothing has ever been trained on it. Right now it's used as few-shot example chats (below).
- `archive/discord-pipeline/` — parked until the rented GPU: turns the user's Discord export
  into training data in their texting style. `extract.py` (export → cleaned server replies),
  `backtranslate.py` (Ollama writes 1–3 friend messages before each reply; resumable, fixed
  shuffled order, 2 tries then `rejected.jsonl`; 25% get an "@Gomihyu" ping; made-up handles),
  `build_dataset.py` (examples → `train.jsonl`, several input files can be mixed). Runs from the
  archive; output in its gitignored `data/`. Tested with a fake export/Ollama, never run for real.
  On the export: 17,482 replies survive cleanup.
- `melee.py` + `persona.build_match_messages` — Melee results (user, 2026-09-29: "lets have her
  start yapping in discord on the outcome"). The first step past "just a Discord conversationalist":
  AI-Melee (`zurgace/aimelee`, where she plays Mario or Fox through Ollama and learns between matches)
  writes one JSON per match and per in-match taunt to an outbox both know by default,
  `~/.local/share/gomihyu/melee-outbox` (atomic, newest 20 kept; `MELEE_OUTBOX` overrides).
  `bot.py`'s `watch_melee` task (started once in `on_ready`) checks it every 5 s. She only talks once
  a match is over (user, 2026-09-29, same day: she "yaps a bit too often during gameplay"; the first
  version posted taunts live, at most one per 30 s). Taunt files are taken out of the outbox on sight
  (so AI-Melee's newest-20 limit never pushes out a match) into `melee_taunts` (in memory), minus
  slurs; a match post gets the ones said up to `TAUNT_WINDOW_SECONDS` (15 min) before it ended, the
  last 3 quoted in `match_facts` ("call one back if it fits, don't list them"), and they're dropped
  with the match (posted, muted, stale). Unmatched taunts expire with `MELEE_MAX_AGE_MINUTES`. Matches are
  posted about through the normal paths
  (`clean_reply` / `send_reply`, shared with `generate_reply` / `reply_to`): slur filter, repeat
  retry, in her chat history and `posted`, holding the channel's reply lock, with any follow-up owed
  answered right after (`converse`). User choices: through her own bot (not a webhook), one post per
  match. Muted → dropped; model down → kept for the next check; older than
  `MELEE_MAX_AGE_MINUTES` (30) → dropped; unreadable → renamed `.bad`. The player is `MELEE_PLAYER`,
  else the app owner's nickname / display name / handle. The channel: an owner's "gomi post melee
  here" (commands.py, owner-only like delete/mute, reacts 🎮; saved in gitignored
  `melee_channel.json`), "gomi stop posting melee" (🔕, saves none, which also beats the env), else
  `MELEE_CHANNEL_ID`. No channel → everything waits in the outbox. The user hadn't set the `.env`
  lines the first design needed, so setup is a chat command now, not config.
  Match posts say what she'll work on (user, 2026-09-29: "provide more meaningful information ... like
  mention what she wants to work on and improve"). Since then, AI-Melee's match event also carries her `review`
  (her own words), `notes` (its match log: what hit her, openings, how stocks went), `goal` (the drill she
  practises next match) and `drill_result` (last match's goal: its number before -> after, better/worse).
  `match_facts` quotes them; the prompt asks for 2-4 sentences naming what decided the match, whether
  her practice paid off, and next match's goal as a scheme, never an apology (it no longer tells her to
  blame anything but the player). Match posts get `max(MAX_REPLY_TOKENS, 300)` tokens.
- The repo lives on GitHub (`zurgace/gomihyu`); `.env` is gitignored.

## Locked-in design decisions (don't change without asking)
- Bot's Discord username is `Gomihyu`. Always replies when @mentioned — including
  firing back rudely/dramatically if provoked (see `persona.py`: the persona is
  explicitly instructed not to stay polite when insulted).
- Always replies to posts aimed at her: @mention, a Discord reply to her message (ping on or
  off, `replying_to_her`), her name anywhere outside links (`reactions.names_her`), sad news.
  Anything else she chimes in on only if it interests her (user, 2026-09-27, replacing
  `UNPROMPTED_REPLY_CHANCE`, which was 1.0 = every message): `chime.py` rates the newest post
  0–10 in a short Ollama call (`format`-constrained, anchored scale: her topics, bragging,
  plans without her, a funny line, a question to the room, someone answering her), and she
  replies at `CHIME_IN_THRESHOLD` (default 6) or above; 0 skips the call and answers
  everything. A failed or unparseable rating = quiet. Posts arriving while she decides or
  writes get one follow-up, rated on the newest post (or just answered if any was aimed at
  her); a reply covers posts that arrived while she was deciding, so no double reply. No
  cooldown (slow server, 5 people, ~2 active) — don't add one without checking first.
  Exception (user decision): posts that don't need words —
  image/sticker/bare-link/emoji-only, or at most `REACT_ONLY_MAX_WORDS` (2) words without "?"
  — get an emoji reaction as her whole response, unless they @mention or name her ("gomi",
  "gomihyu") or look serious; those always get a reply.
- Owner commands override the persona (user, 2026-09-28: "if I tell gomi to delete her posts,
  I want her to delete them"). An owner (the bot application's owner from `application_info()`
  at login, or a team's members, plus `OWNER_USER_IDS`) saying "delete that / your last N /
  all your messages" in a message aimed at her (name, @mention, Discord reply to her) → the bot
  deletes her own posts (the replied-to post, or her newest N via `channel.history`, "all" =
  hers among the last `DELETE_SCAN` 200), reacts 🗑️ (🤷 if none), never replies, and neither
  the command nor the deleted posts stay in her chat log (`posted` maps message id → log line).
  Non-owners, "don't delete", "I'll delete" → normal chat. No extra permission: bots can always
  delete their own messages.
- Mute (user, 2026-09-28: for when she's "yapping a bit too much" or "wants to butt in"): an
  owner's "gomi mute [for 10 minutes / 2h / an hour | until i say so]" silences her in that
  channel (`muted_until`, in memory, so a restart unmutes; default `MUTE_MINUTES` 30), "gomi
  unmute" ends it; reacts 🔇 / 🔊. While muted she still logs the chat and saves notes (📝), but
  sends nothing and reacts to nothing, except 🤐 on posts aimed at her; a reply in progress is
  dropped before sending and no follow-up runs. Only the literal word "mute": "gomi stfu" is
  banter the user actually says to her. Negation and first-person ("don't make me mute you",
  "I'll mute you") are checked only in the words before the verb.
- Quiet mode, the softer mute (user, 2026-09-29): an owner's "gomi quiet mode [for ... | until i
  say so]" or "gomi only talk/reply when ..." → in that channel she only answers posts aimed at her
  (`for_her`); no chime-ins (no interest call), no reply to sad news not aimed at her (the sad cat
  still goes on), but emoji reactions and Melee match posts continue. `quiet_until`, same default
  and duration parsing as mute, reacts 🤫. Mute and quiet mode replace each other (the newest wins);
  "unmute" / "quiet mode off" / "turn off quiet mode" / "you can talk again" end either (🔊).
  Questions, "don't ..." and "I'll ..." before the phrase aren't commands; "be quiet" is banter.
- One reply in flight per channel (per-channel lock). Messages arriving mid-reply get ONE
  follow-up reply to the latest chat, not one each. The in-flight reply is logged ahead of
  them so the follow-up prompt still ends on the newest unanswered message.
- She goes by Gomi (`BOT_NICKNAME`) and calls people by their nicknames, falling back to
  their handle (user decision; this replaced the earlier "full handle, never a nickname"
  trait). The log labels speakers by handle (`author.name`); a "Nicknames, call these people
  by them: ..." line covers everyone in the log. `@handle`, `@display name` or `@nickname` in
  a reply becomes a real ping, except for the person she's answering (user, 2026-09-27: on Gemma
  she @'d them in every reply and "stop pinging me" didn't stick). Code drops their @
  (`without_ping`: a leading "@name" goes, others become the plain name), the prompt says never
  to @ them, and the seed replies have no @. Never pings @everyone/@here/roles.
- Emoji reactions are a response, not a random roll (the old independent `REACTION_CHANCE`
  was removed at the user's request). Media she can't see → a "looking" emoji (👀 /
  :goonerstare:), never a judgment of the image. Emoji-only posts may get the same emoji
  back. Otherwise a separate short Ollama call picks, with `format` constrained to the
  `emojis.py` names + "none". Reactions are never added to the chat history.
- Sad news (`reactions.sad_news`: serious words, not laughter like "crying lmao") gets a
  reply plus a `:catsad:` reaction (`SAD_NEWS`), never a reaction alone.
- She may write this server's custom emojis in replies as `:name:` (converted to the real
  emoji at send time). Only `in_text=True` ones are listed in her prompt; `aryanosaka` and
  `goonerstare` are reaction-only so those names aren't listed there. `goonerstare` is also
  the slur stand-in, so it's always postable and can appear in her chat log.
- Her diary (user, 2026-09-29: "have gomi store conversations into her memory whenever I shut down
  gomi for the night"; this ended "person memory is explicit only, no auto-extraction"). Chosen: notes
  + daily recaps; triggered by Ctrl+C / SIGTERM / SIGHUP (own `main()` instead of `client.run`; a
  second Ctrl+C skips it) or an owner's "gomi goodnight" (💤, a goodnight line unless muted, then
  `client.close()`), with a background catch-up at the next start for chat older than the start;
  everyone in the server, no opt-out; raw logs kept. Every server-channel message goes to the chat
  log (`chatlog.py`; DMs never, owner commands never, deleted posts removed). `write_diary` reads each
  channel's log since `read_up_to` in ~12k-char parts; a part with <2 human messages is just marked
  read. One `format`-constrained call per part (`who` is an enum of the part's speakers, temperature
  0.3) returns a recap and notes, each note with a quote; `parse_digest` keeps a note only if its
  quote (2+ words, case/punctuation-insensitive) is in one of the part's messages, the note has no
  slur and is <= 200 chars. Notes → `people.json` "learned" (deduped against facts, at most
  `MAX_LEARNED_PER_PERSON` 10); recaps → `diary.json`. Model down → stop, unread; unparseable → skip
  and mark read. Prompt: the speaker's learned notes (after their asked-for facts) and the channel's
  last `RECAP_DAYS` (3) of recaps, both ahead of the log; the system prompt's limits say she
  remembers "what you wrote in your diary after past chats". Restarts reload each channel's last
  `HISTORY_LENGTH` log lines from the last `HISTORY_RELOAD_HOURS` (12) and prefill `handles`.
- Melding (user, 2026-09-29: "I'd like for gomi's personality to get influenced by the discord
  server... slowly meld the current Satania persona to someone that fits in"). User choices: the members
  have agreed to their chat being training data; learn from both her replies that landed and the
  server's own voice; start melding now through the prompt; gradual with an anchor. Nightly (in
  `write_diary`): `meld.landed_replies` over each channel's newly read log, reactions included (the
  bot logs `on_raw_reaction_add` on her posts, `reply_to` on Discord replies, `about` on her posts:
  reply / melee / goodnight). Landed = a reaction from someone else, a Discord reply to it, a laugh
  (`reactions.LAUGHING`) as the next message, or her name in what people said next (up to her next
  post, within 180 s, max 3), and no put-down ("stfu", "shut up", ...). Only "reply" posts of 2+
  words, not the slur stand-in, with a human line in the context (last 6 lines, <= 30 min). Kept in
  `EARNED_FILE` (earned_examples.jsonl, gitignored, dedup by message id, "real": true). Prompt:
  `pick_examples` mixes seed and earned; persona share = max(`MELD_ANCHOR` 0.3, 1 - earned /
  `MELD_FULL_AT` 200), so 8 examples go from 8 seed to 3 seed + 5 earned; with real ones in, the
  examples' intro says so and not to bring up what happened in them; the repeat guard covers earned
  replies. Vibe note: with >= `VIBE_MIN_MESSAGES` (10) new human messages, one `format`-constrained
  call (temperature 0.3, newest ~8k chars) updates <= 6 lines on how the server talks (keep / add /
  drop); in `diary.json`; in the system prompt via `persona.system_content` (all three prompt
  builders). Training: `finetuning/build_dataset.py --meld --run N`: seed x3 + all earned + a
  `Random(run)` pick of `meld.voice_examples` (people's messages answering someone else, 3+ words,
  not naming her, no slur, not a link, not a burst continuation, <= 10 min after the previous line)
  so the seed share is `meld.SCHEDULE` 0.7 / 0.55 / 0.4 / 0.3 for runs 1-4, never below the anchor;
  it prints the actual share (short on data early). Training data keeps the prompt without examples
  and vibe, like recaps and notes.
- Person memory, explicit part: a "remember (that) ..." / "don't forget ..." message aimed
  at her (@mention, reply-ping, or "Gomi"/"Gomihyu" within the first 4 words) stores the rest verbatim for its
  author (her own picked-up notes come only from the diary, above); questions ("remember when...?") are skipped. She
  reacts 📝 on store. Nicknames ("call me X", "my nickname is X", "Y's nickname is X",
  "call @y X") are stored on the person they're about (resolved by handle / display name /
  mention / people.json), never with a slur, never for her. `people.json` (gitignored),
  `{user_id: {"display_name", "facts", "nickname"?}}`,
  deduped, capped at `MAX_FACTS_PER_PERSON` (20) with the oldest dropping off, written
  atomically; invalid JSON stops startup rather than being overwritten. At reply time only
  the latest message's author's facts go into the prompt, as one line ahead of the chat
  log (not the system prompt, not next to the instruction, so it isn't forced into every
  reply). No vector store/embeddings/RAG — it's 5 people.
- Persona is inspired by an existing character but renamed and written fresh —
  original writing only. A small (dozen-ish) set of quotes as a style reference is
  fine; bulk verbatim dialogue as training data is not. This is an intentional
  constraint, not a stylistic preference.
- A small model will confabulate; that can be contained, not eliminated. Anything that has to
  be true lives in code, not the model (memory storage, slur filter, constrained emoji picks).
  The prompt states her limits (sees only the last few messages; can't read/search history,
  look things up, run commands or do things later; remembers only nicknames + notes) and
  spells out who sent the message she's answering ("When X says I/me/my, they mean
  themselves"), because she mixed up "who am I?". Channel-history reading/summaries are out of
  scope here (that's the bigger assistant project); she declines those in character.
- Reply length matches the moment (user wants her to actively join discussions): a jab or
  comeback is one short line, a question or real discussion 2–4 sentences ("never more", added
  when Gemma wrote 5–7), building on others and giving opinions. A question gets a real answer
  (Gemma dodged "the fuck is Malebolge"); asking something back is "now and then, not every
  time" (Gemma ended nearly every reply with a question), and she mustn't open by repeating
  the message back as a question. Don't bring back "a few words, at most 2 sentences" or "don't reuse topics" to fix
  repetition: that turned her into a one-liner machine. Repetition is handled by "don't repeat
  your own earlier lines / pet topics" plus the REPEAT_WORDS retry. `MAX_REPLY_TOKENS` (200)
  is the safety cap; a reply that hits it is trimmed to its last full sentence. The cap counts
  thinking tokens too: 200 tokens of planning left an empty reply and she went silent. So
  thinking is requested off by default, and once any response shows thinking (`OLLAMA_THINK=true`,
  or a model that ignores `think: false`, as LFM2.5-2.6B did) `model_thinks` is set and replies
  go uncapped (the 60s request timeout still bounds them); a capped reply that ran out while
  thinking is retried once uncapped. `<think>` text inside the content is stripped before posting.
- Until a fine-tuned model serves her, her voice comes from few-shot example chats: each reply's
  system prompt gets `FEW_SHOT_EXAMPLES` (8) seed examples, a fresh random pick every reply
  (`persona.format_examples`, last 3 history lines + her reply, labelled made-up and not to be
  reused). The repeat guard also retries a reply that copies 5 words from any example reply.
  Training data is built without them; set `FEW_SHOT_EXAMPLES=0` once a fine-tuned model serves.
- Fine-tuning approach is LoRA/QLoRA (Unsloth is the intended tool), not full fine-tuning.
  Gemma 4 E4B QLoRA reportedly needs ~10GB VRAM, so it won't train on the 2070: training
  happens on a GPU the user will rent; serving stays on the 2070.
- Training data must never be committed: the user's Discord export (`Messages/`, `*.zip`) holds
  personal messages including DMs, and is gitignored. Builders read it from a local path.

## Open / not yet decided
- (Settled 2026-09-29: channel history now survives restarts, reloaded from the chat log.)
- Consent (2026-09-29): the user says the members agreed to their chat being used as training data,
  so the kept chat logs are now option (a) below, via `build_dataset.py --meld`.
- Training data from the user's own Discord export (received 2026-09-26, analysed in a
  scratch space, not in the repo): 83,656 messages, 2017-05 to 2026-09. 56k from server
  channels (4 servers still named in the export, plus 18k from ones that aren't), 27.6k from
  111 DMs + 6 group DMs. Server names and message contents stay out of the repo. Only
  the user's side is in it, never anyone else's messages. Median message is 5–6 words; they
  post in bursts (22.8k server bursts of messages <=90s apart, 9.5k of 12+ words). ~730
  messages contain a word from `slurs.txt`; a few emails / phone numbers; 4.4k link-only or
  attachment-only posts. Decided 2026-09-26:
  - Voice: yes, Gomi should text like the user (lowercase bursts, gaming talk), with the
    archdemon persona from the prompt. Mix in persona examples so she doesn't just become them.
  - DMs: OUT, never used. The user says they likely hold private information; they were deleted
    from the session they were uploaded to. Any builder must skip DM / GROUP_DM channels.
  - Context: option (b), an LLM writes the preceding friend messages ("instruction
    backtranslation", `archive/discord-pipeline/backtranslate.py`). Later, with the other members' consent, the
    bot will export the real channel history of its server (it has Read Message History) as a
    second examples file: option (a).
- Decided 2026-09-29: training runs use `build_dataset.py --meld --run N` (seed + the server). Still
  open: whether to also mix in the parked export pipeline's output. Earlier question, for the record:
  which data the first Gemma training run uses: the seed (58, active), the Discord pipeline's
  output (parked), or a mix. Decide when the rented GPU is set up.
- Target dataset size before a training run (likely 1–3k good examples).

## Next steps
1. See how Gemma does with the seed as example chats. First live log (2026-09-27): voice good and
   in character, but 60–90-word replies of 5–7 sentences (the seed's are ~20 words, max 36), an
   @ping at the person every reply, near every reply opening by echoing the message as a question
   and ending on a question, "Seriously though" filler, :AIEEE: in 3 of 6 replies (posted as plain text: the server's
   emoji is `AIEEEE`, which the user fixed in `emojis.py`), melon bread
   twice as an insult (4 of the seed's 6 melon bread lines are off-topic too). Fixed: pings, the
   length/question/echo rules. Still to check after that: length, emoji and melon bread frequency.
2. When the user has a rented GPU: the LoRA/QLoRA training script (Unsloth) for Gemma 4 E4B, trained on
   `build_dataset.py --meld --run N`, one run number up each time. Watch the nightly meld meanwhile:
   the vibe note (console / `diary.json`), which replies count as landed (`earned_examples.jsonl`), and
   whether she drifts too far or too little (`MELD_ANCHOR`, `MELD_FULL_AT`).
3. After training, produce a GGUF, load it with `ollama create` (Gemma's chat template), then
   update `OLLAMA_MODEL` in `.env` and set `FEW_SHOT_EXAMPLES=0`. No bot code changes needed.
4. Read the first diary entries (console at shutdown, `diary.json`, "learned" in `people.json`):
   are notes lasting facts or chatter, does the quote check drop real notes (paraphrased quotes)
   or let junk through, are recaps useful in her replies, how long shutdown takes.
5. Tell the server she remembers things people tell her to (if not done yet).
6. Test the emoji rework live: react-only posts, picker choices, custom emojis in replies.
7. Gemma 4 E4B live (100% GPU at 8192 context confirmed): reply speed, no thinking warning, and
   whether the prompt (tuned on LFM) needs retuning, e.g. asterisk actions or rambling.
8. Tune chiming in live: watch the `Interest n/10` log lines. Small models tend to give most
   posts the same middling-high number; if she's too chatty or too quiet, move
   `CHIME_IN_THRESHOLD` first, then the prompt's anchors in `chime.py`.
9. Test nicknames, "who am I?" and the stated limits live. If "what do you remember about
   me?" still comes back wrong, answer it from code (list the saved notes) instead.

## Constraints
- Serving runs on one RTX 2070 (8GB VRAM) — keep this in mind for any model change; check
  VRAM math before suggesting a bigger model. Training can run elsewhere (see above).
- Keep bot behavior config-driven via `.env`, not hardcoded, so it can be retuned
  without a code change.
