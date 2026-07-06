# HCCL Telegram Bot v1

This bot reads rankings saved by **HCCL Rankings Dashboard v3** from Supabase.

The Streamlit dashboard saves the rankings. This Telegram bot only reads and displays them.

## Commands

```text
/start
/help
/topbat
/topbat 5
/topbowl
/topall
/player Hasitha
/team DRAGONS
/team DRAGONS batting
/movers
/fallers
/gains
/newentries
/report
/benchmarks
/weeks
```

## 1. Create your Telegram bot

1. Open Telegram.
2. Search for **BotFather**.
3. Send `/newbot`.
4. Choose a bot name and username.
5. Copy the bot token.

Keep the token private. Do not upload it to GitHub.

## 2. Local test on Windows

1. Unzip this folder.
2. Copy `.env.example` and rename the copy to `.env`.
3. Fill in:

```text
TELEGRAM_BOT_TOKEN=
SUPABASE_URL=
SUPABASE_KEY=
```

Use the same Supabase URL and key you used for Streamlit secrets.

4. Double-click:

```text
START_TELEGRAM_BOT_WINDOWS.bat
```

5. Open your bot in Telegram and send:

```text
/start
/topbat
/player Hasitha
```

## 3. Make the bot private

To allow only your own Telegram account or HCCL group, set this in `.env` or deployment secrets:

```text
ALLOWED_CHAT_IDS=123456789
```

For a Telegram group, add the bot to the group and use a command once. If needed, temporarily leave `ALLOWED_CHAT_IDS` blank until you identify the group chat ID from logs or a helper tool.

## 4. Deploy as a permanent bot

Do not deploy this inside Streamlit. Telegram polling needs a continuously running worker.

Recommended options:

- Render Worker
- Railway
- Fly.io
- A small VPS
- Your own computer, if it stays on

### Render quick deploy

1. Push this bot folder to GitHub.
2. Create a new **Background Worker** on Render.
3. Use:

```text
Build command: pip install -r requirements.txt
Start command: python telegram_bot.py
```

4. Add environment variables:

```text
TELEGRAM_BOT_TOKEN
SUPABASE_URL
SUPABASE_KEY
ALLOWED_CHAT_IDS optional
DEFAULT_TOP_LIMIT optional
```

## 5. How it connects to your dashboard

```text
HCCL Streamlit Dashboard
        ↓ Save Current Rankings
Supabase tables
        ↓ Read latest snapshot
Telegram Bot commands
```

Before the Telegram bot can show rankings, your dashboard must save at least one ranking snapshot to Supabase.

## Troubleshooting

### Bot says no saved snapshots

Open Streamlit Dashboard v3, calculate rankings, then click **Save Current Rankings**.

### Bot does not reply

Check that the worker is running and that `TELEGRAM_BOT_TOKEN` is correct.

### Supabase error

Check that `SUPABASE_URL` and `SUPABASE_KEY` are exactly the same as your Streamlit app secrets.

### Private bot blocks you

Remove `ALLOWED_CHAT_IDS` temporarily, restart the bot, and test again.
