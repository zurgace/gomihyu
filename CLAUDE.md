# Gomihyu — Discord SLM Conversationalist

## What this is
A small-model (LFM2.5-2.6B) Discord bot, "Gomihyu," running locally via Ollama on an
RTX 2070 (8GB VRAM). This is a standalone side project — a dry run of Discord +
personality plumbing before a much larger, separate local assistant project
(Nemotron-based, on a different machine — a Framework Desktop) comes online. Don't
conflate the two: this repo is scoped to just being a Discord conversationalist,
nothing more, until told otherwise.

## Environment
- OS: CachyOS (Arch-based Linux)
- GPU: RTX 2070, 8GB VRAM — every model/training decision here has to fit this
- Inference: Ollama serving `hf.co/lmstudio-community/LFM2.5-2.6B-GGUF:Q4_K_M`
  (LFM2.5-2.6B has native llama.cpp/Ollama support, no custom build needed). The live
  setup actually runs a locally built `gomihyu-base:latest` (set via `OLLAMA_MODEL` in
  `.env`); its GGUF source/Modelfile isn't in the repo yet.
- Python 3, using `discord.py`, `aiohttp`, `python-dotenv`

## Current state
- `bot.py` / `persona.py` / `requirements.txt` / `.env.example` — working Discord bot
  that talks to Ollama. Running live on the server (replies and memory confirmed working;
  the emoji rework, prompt fixes and slur filter not yet tested live).
- `persona.py` — the system prompt AND the prompt format (`format_line`, `build_messages`).
  Both the bot and the dataset builder use it, so training prompts match runtime prompts
  exactly. Change the format there, never in only one place.
- `emojis.py` — every emoji she uses (unicode + this server's custom ones) with a "when to use
  it" note; the model only ever sees names + notes. `reactions.py` — when a post gets a
  reaction instead of a reply, and the constrained emoji-picker prompt.
- `censor.py` + `slurs.txt` — a reply containing any slur (whole words, optional plural s) is
  replaced entirely by the `:goonerstare:` emoji (`SLUR_STANDIN`), also in her chat history.
  Swearing is deliberately not filtered; the server doesn't want her more PG.
- `memory.py` — person memory: "remember that ..." parsing + `people.json` store.
- `finetuning/persona_guide.md` — voice/personality guide, written from a paraphrased
  summary of a public wiki character bio plus tonal patterns pulled from a short quotes
  list. No source dialogue is copied anywhere in this repo — everything is original
  writing meant to capture voice, not script.
- `finetuning/gomihyu_seed.jsonl` — 47 original synthetic Discord-style exchanges in that
  voice, as `{"history": [[handle, text], ...], "facts"?: [...], "reply": ...}`. This is a SEED, not a
  finished dataset. `finetuning/build_dataset.py` renders it into system/user/assistant
  SFT JSONL (`finetuning/train.jsonl`, gitignored — rebuild it, don't edit it).
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
- Gomihyu addresses people by their full Discord handle as an @mention (this replaced the
  original "full name" trait). The log labels speakers by handle (`author.name`), and
  `@handle` in a reply becomes a real ping. Never pings @everyone/@here/roles.
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
  reacts 📝 on store. `people.json` (gitignored), `{user_id: {"display_name", "facts"}}`,
  deduped, capped at `MAX_FACTS_PER_PERSON` (20) with the oldest dropping off, written
  atomically; invalid JSON stops startup rather than being overwritten. At reply time only
  the latest message's author's facts go into the prompt, as one line ahead of the chat
  log (not the system prompt, not next to the instruction, so it isn't forced into every
  reply). No vector store/embeddings/RAG — it's 5 people.
- Persona is inspired by an existing character but renamed and written fresh —
  original writing only. A small (dozen-ish) set of quotes as a style reference is
  fine; bulk verbatim dialogue as training data is not. This is an intentional
  constraint, not a stylistic preference.
- Fine-tuning approach is LoRA/QLoRA (Unsloth is the intended tool), not full
  fine-tuning — chosen specifically to fit the 8GB VRAM budget.

## Open / not yet decided
- Whether to persist channel history across bot restarts (currently in-memory, resets
  on restart).
- A real Discord transcript export (the user's own messages only) is delayed. Plan is
  to mix real transcripts into the synthetic seed once it arrives — don't assume the
  seed file is the final dataset.
- Target dataset size before an actual training run (47 examples now; likely needs a
  few hundred).

## Next steps
1. Expand `finetuning/gomihyu_seed.jsonl` toward 150–200+ examples, matching
   the existing format and voice.
2. Set up the actual LoRA/QLoRA training script (Unsloth), targeting LFM2.5-2.6B, fed
   from `build_dataset.py` output.
3. After training, produce a merged GGUF, load it with `ollama create`, then update
   `OLLAMA_MODEL` in `.env`. Bot code should not need to change for this.
4. Revisit history persistence if in-memory-only turns out to be annoying in practice.
5. Tell the server she remembers things people tell her to (if not done yet).
6. Test the emoji rework live: react-only posts, picker choices, custom emojis in replies.

## Constraints
- Everything runs on one RTX 2070 (8GB VRAM) — keep this in mind for any model or
  training changes; check VRAM math before suggesting a bigger model.
- Keep bot behavior config-driven via `.env`, not hardcoded, so it can be retuned
  without a code change.
