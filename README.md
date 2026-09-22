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
   Send Messages, Read Message History**. Open the generated URL and invite it to your
   5-person server.

## 3. Configure and run
```bash
cd gomihyu-bot
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # then fill in DISCORD_BOT_TOKEN
python3 bot.py
```
You should see `Logged in as Gomihyu (id: ...)` in the console once it's connected.

## How it behaves
- **@mention → always replies**, and the persona is instructed to fire back rudely in
  character if provoked, rather than staying polite.
- **Any other message → replies with probability `UNPROMPTED_REPLY_CHANCE`** (default 0.5,
  no cooldown) — tune this in `.env` without touching code.
- Keeps the last `HISTORY_LENGTH` messages per channel as context so replies aren't
  totally blind to what's being discussed.
- Ignores its own messages and other bots.

## Swapping in the fine-tuned LoRA later
The bot code doesn't need to change. Once you have a trained LoRA:
1. Merge it (or serve it as an adapter, depending on your training tool) into a GGUF.
2. `ollama create gomihyu-tuned -f Modelfile` pointing at that GGUF (or `ollama pull` if you
   push it somewhere).
3. Update `OLLAMA_MODEL` in `.env` to the new model name and restart the bot.

The `SYSTEM_PROMPT` in `persona.py` can likely get much shorter once the LoRA is actually
carrying the personality — right now it's doing all the work.

## Known limitations at this scope
- Text-only: it can't see images, only whatever caption/text comes with them.
- No memory across restarts — channel history resets when the bot restarts.
- Single-server assumption: history is keyed by Discord channel ID, so it naturally
  won't cross-contaminate between channels/servers, but there's no persistence yet.
