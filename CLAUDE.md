# Gomihyu — Discord SLM Conversationalist

## What this is
A small-model (Gemma 4 E4B) Discord bot, "Gomihyu," running locally via Ollama on an
RTX 2070 (8GB VRAM). This is a standalone side project — a dry run of Discord +
personality plumbing before a much larger, separate local assistant project
(Nemotron-based, on a different machine — a Framework Desktop) comes online. Don't
conflate the two: this repo is scoped to just being a Discord conversationalist,
nothing more, until told otherwise.

## Environment
- OS: CachyOS (Arch-based Linux)
- GPU: RTX 2070, 8GB VRAM — every model/training decision here has to fit this
- Inference: Ollama serving `gemma4:e4b` (Ollama's official tag; `OLLAMA_MODEL` in `.env`).
  User switched from LFM2.5-2.6B on 2026-09-26 because it felt like "a response bot, not an
  AI" (Liquid built it for agents/tool calling). Gemma 4 E4B: ~4.5B effective params (8B with
  per-layer embeddings), ~5GB at Q4_K_M; Ollama's tag is listed at ~9.6GB (bundles image + audio
  encoders). Confirmed 2026-09-27 on the 2070: `ollama ps` shows 3.2GB, 100% GPU, at Ollama's
  default 4096 context, so there's VRAM headroom. The bot asks for `OLLAMA_NUM_CTX` (8192) on every
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
- `memory.py` — person memory: "remember that ..." parsing + `people.json` store.
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
- The repo lives on GitHub (`zurgace/gomihyu`); `.env` is gitignored.

## Locked-in design decisions (don't change without asking)
- Bot's Discord username is `Gomihyu`. Always replies when @mentioned — including
  firing back rudely/dramatically if provoked (see `persona.py`: the persona is
  explicitly instructed not to stay polite when insulted).
- Otherwise replies unprompted with probability `UNPROMPTED_REPLY_CHANCE` (default 1.0 —
  every message), no cooldown. This was deliberately tuned for a specific slow,
  low-traffic server (5 people, ~2 actually active) — don't add a cooldown or lower the
  default without checking first. Exception (user decision): posts that don't need words —
  image/sticker/bare-link/emoji-only, or at most `REACT_ONLY_MAX_WORDS` (2) words without "?"
  — get an emoji reaction as her whole response, unless they @mention or name her ("gomi",
  "gomihyu") or look serious; those always get a reply.
- One reply in flight per channel (per-channel lock). Messages arriving mid-reply get ONE
  follow-up reply to the latest chat, not one each. The in-flight reply is logged ahead of
  them so the follow-up prompt still ends on the newest unanswered message.
- She goes by Gomi (`BOT_NICKNAME`) and calls people by their nicknames, falling back to
  their handle (user decision; this replaced the earlier "full handle, never a nickname"
  trait). The log labels speakers by handle (`author.name`); a "Nicknames, call these people
  by them: ..." line covers everyone in the log. `@handle`, `@display name` or `@nickname` in
  a reply becomes a real ping. Never pings @everyone/@here/roles.
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
- Person memory is explicit only: a "remember (that) ..." / "don't forget ..." message aimed
  at her (@mention, reply-ping, or "Gomi"/"Gomihyu" within the first 4 words) stores the rest verbatim for its
  author. No auto-extraction from chat; questions ("remember when...?") are skipped. She
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
- Reply length matches the moment (user wants her to actively join discussions): a jab can
  be a few words, a question or real discussion 2–4 sentences, building on others and giving
  opinions. Don't bring back "a few words, at most 2 sentences" or "don't reuse topics" to fix
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
- Whether to persist channel history across bot restarts (currently in-memory, resets
  on restart).
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
- Which data the first Gemma training run uses: the seed (58, active), the Discord pipeline's
  output (parked), or a mix. Decide when the rented GPU is set up.
- Target dataset size before a training run (likely 1–3k good examples).

## Next steps
1. See how Gemma does with the seed as example chats: voice, reply length (the seed replies are
   ~20 words, 2+ sentences), "Archdemon" frequency (the seed leans on it), copying.
2. When the user has a rented GPU: the LoRA/QLoRA training script (Unsloth) for Gemma 4 E4B.
3. After training, produce a GGUF, load it with `ollama create` (Gemma's chat template), then
   update `OLLAMA_MODEL` in `.env` and set `FEW_SHOT_EXAMPLES=0`. No bot code changes needed.
4. Revisit history persistence if in-memory-only turns out to be annoying in practice.
5. Tell the server she remembers things people tell her to (if not done yet).
6. Test the emoji rework live: react-only posts, picker choices, custom emojis in replies.
7. Gemma 4 E4B live (100% GPU confirmed): check `ollama ps` shows CONTEXT 8192 and still 100% GPU
   after a reply, reply speed, no thinking warning, and whether the prompt (tuned on LFM) needs
   retuning, e.g. asterisk actions or rambling.
8. Test nicknames, "who am I?" and the stated limits live. If "what do you remember about
   me?" still comes back wrong, answer it from code (list the saved notes) instead.

## Constraints
- Serving runs on one RTX 2070 (8GB VRAM) — keep this in mind for any model change; check
  VRAM math before suggesting a bigger model. Training can run elsewhere (see above).
- Keep bot behavior config-driven via `.env`, not hardcoded, so it can be retuned
  without a code change.
