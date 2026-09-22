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
  (LFM2.5-2.6B has native llama.cpp/Ollama support, no custom build needed)
- Python 3, using `discord.py`, `aiohttp`, `python-dotenv`

## Current state
- `bot.py` / `persona.py` / `requirements.txt` / `.env.example` — working Discord bot
  that talks to Ollama. Behavior-tested against a fake Discord/Ollama, but not yet run
  against a live Discord token.
- `persona.py` — the system prompt AND the prompt format (`format_line`, `build_messages`).
  Both the bot and the dataset builder use it, so training prompts match runtime prompts
  exactly. Change the format there, never in only one place.
- `finetuning/persona_guide.md` — voice/personality guide, written from a paraphrased
  summary of a public wiki character bio plus tonal patterns pulled from a short quotes
  list. No source dialogue is copied anywhere in this repo — everything is original
  writing meant to capture voice, not script.
- `finetuning/gomihyu_seed.jsonl` — 41 original synthetic Discord-style exchanges in that
  voice, as `{"history": [[handle, text], ...], "reply": ...}`. This is a SEED, not a
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
  default without checking first.
- One reply in flight per channel (per-channel lock). Messages arriving mid-reply get ONE
  follow-up reply to the latest chat, not one each. The in-flight reply is logged ahead of
  them so the follow-up prompt still ends on the newest unanswered message.
- Gomihyu addresses people by their full Discord handle as an @mention (this replaced the
  original "full name" trait). The log labels speakers by handle (`author.name`), and
  `@handle` in a reply becomes a real ping. Never pings @everyone/@here/roles.
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
- Target dataset size before an actual training run (41 examples now; likely needs a
  few hundred).

## Next steps
1. Expand `finetuning/gomihyu_seed.jsonl` toward 150–200+ examples, matching
   the existing format and voice.
2. Set up the actual LoRA/QLoRA training script (Unsloth), targeting LFM2.5-2.6B, fed
   from `build_dataset.py` output.
3. After training, produce a merged GGUF, load it with `ollama create`, then update
   `OLLAMA_MODEL` in `.env`. Bot code should not need to change for this.
4. Revisit history persistence if in-memory-only turns out to be annoying in practice.

## Constraints
- Everything runs on one RTX 2070 (8GB VRAM) — keep this in mind for any model or
  training changes; check VRAM math before suggesting a bigger model.
- Keep bot behavior config-driven via `.env`, not hardcoded, so it can be retuned
  without a code change.
