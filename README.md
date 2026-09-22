# Gomihyu — Discord conversationalist (LFM2.5-2.6B)

## 1. Install and start Ollama, pull the model
```bash
curl -fsSL https://ollama.com/install.sh | sh
ollama pull hf.co/lmstudio-community/LFM2.5-2.6B-GGUF:Q4_K_M
```
Leave Ollama running (`ollama serve`, or it may already run as a background service
depending on your install). Sanity-check it works:
```bash
ollama run hf.co/lmstudio-community/LFM2.5-2.6B-GGUF:Q4_K_M "say hi"
```

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
git clone https://github.com/zurgace/gomihyu.git && cd gomihyu
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # then fill in DISCORD_BOT_TOKEN
python3 bot.py
```
You should see `Logged in as Gomihyu (id: ...)` in the console once it's connected.

## How it behaves
- **@mention → always replies**, and the persona is instructed to fire back rudely in
  character if provoked, rather than staying polite.
- **Any other message → replies with probability `UNPROMPTED_REPLY_CHANCE`** (default 1.0,
  i.e. every message, no cooldown — meant for a slow server) — tune this in `.env` without
  touching code.
- **Reacts with an emoji** to a `REACTION_CHANCE` share of messages (default 0.3), rolled
  separately from replying, so a message can get a reaction, a reply, both or neither. The
  emoji comes from a small in-character set (😤 🔥 👑 💢 🙄 😈 💅), picked by keywords in
  `reactions.py`, with no model call. Sad or serious messages get no reaction. Needs the
  **Add Reactions** permission. If it's missing, the console logs `Couldn't react ...` and
  replies carry on as normal.
- **One reply at a time per channel.** If messages arrive while it's still writing a reply,
  it sends one follow-up afterwards that answers the latest chat, rather than one reply each.
- **Addresses people by their full Discord handle.** The chat log it sees labels everyone by
  handle (e.g. `kaz0: ...`), and when a reply says `@kaz0` the bot turns it into a real ping.
  Discord shows a ping as the person's server display name. It never pings `@everyone`,
  `@here` or roles.
- Keeps the last `HISTORY_LENGTH` messages per channel as context so replies aren't
  totally blind to what's being discussed.
- **Doesn't parrot itself.** If a reply copies `REPEAT_WORDS` (default 5) words in a row from
  one of its own recent messages, it regenerates once at `RETRY_TEMPERATURE` (default 1.0) and
  logs that it did. Small models otherwise tend to reuse their earlier lines word for word.
- Ignores its own messages and other bots.

## Training data
`finetuning/gomihyu_seed.jsonl` is the hand-written seed data: one example per line, with the
chat so far as `[handle, message]` pairs and the reply Gomihyu should give:
```json
{"history": [["kaz0", "@Gomihyu wanna 1v1 me in valorant"]], "reply": "You dare challenge the Archdemon to combat, @kaz0? ..."}
```
The last `history` entry is the message being answered; put `@Gomihyu` in it to make it an
@mention. Earlier entries are chat context, and Gomihyu's own messages use the speaker `Gomihyu`.

To turn it into training data:
```bash
python3 finetuning/build_dataset.py   # -> finetuning/train.jsonl (system/user/assistant chat format)
```
This builds each prompt with `persona.build_messages()`, the same function the bot uses at
runtime, so the model is trained on exactly the prompt format it will be served.
`finetuning/persona_guide.md` is the style reference for writing more examples.

## Swapping in the fine-tuned LoRA later
The bot code doesn't need to change. Once you have a trained LoRA:
1. Merge it (or serve it as an adapter, depending on your training tool) into a GGUF.
2. `ollama create gomihyu-tuned -f Modelfile` pointing at that GGUF (or `ollama pull` if you
   push it somewhere).
3. Update `OLLAMA_MODEL` in `.env` to the new model name and restart the bot.

The `SYSTEM_PROMPT` in `persona.py` can likely get much shorter once the LoRA is actually
carrying the personality — right now it's doing all the work. If you change it, rebuild
`train.jsonl` and retrain: the LoRA is trained against whatever prompt was in place at the time.

## Known limitations at this scope
- Text-only: it can't see images, only whatever caption/text comes with them.
- No memory across restarts — channel history resets when the bot restarts.
- Single-server assumption: history is keyed by Discord channel ID, so it naturally
  won't cross-contaminate between channels/servers, but there's no persistence yet.
