# Scramble-bot

A Discord unscramble game bot with a leaderboard and custom word pool.
All commands are Discord slash commands — no prefix (!) commands, no Message Content privileged intent required.

## Stack
- Python (`discord.py`, `flask`, `psycopg2-binary`)
- PostgreSQL (optional — for per-server custom word pools)
- Flask keepalive server on port 8000

## How to run
```
python bot.py
```

On startup the bot syncs all slash commands to guild `1489965395644387399` for instant availability.

## Required secrets
- `DISCORD_TOKEN` — your Discord bot token (required)
- `DATABASE_URL` — PostgreSQL connection string (optional; enables custom word pools per server)

## Bot invite URL (template)
```
https://discord.com/oauth2/authorize?client_id=YOUR_CLIENT_ID&permissions=2048&scope=bot+applications.commands
```
Replace `YOUR_CLIENT_ID` with the Application ID from the Discord Developer Portal.
The `applications.commands` scope is required for slash commands.

## Slash commands

| Command | Permission | Description |
|---|---|---|
| `/scramble` | Manage Messages | Start a new word game |
| `/guess word:<answer>` | Everyone | Submit an answer |
| `/challenge` | Manage Messages | 20-word speed round |
| `/hint` | Manage Messages | First/last letter + length |
| `/skip` | Manage Messages | Reveal word (60s cooldown) |
| `/pause` | Manage Messages | Freeze challenge timer |
| `/resume` | Manage Messages | Unfreeze challenge timer |
| `/end` | Manage Messages | Stop current game/challenge |
| `/leaderboard` | Everyone | Top 10 players |
| `/stats [member]` | Everyone | Score, words solved, rank |
| `/wordcount` | Everyone | Words in pool |
| `/words` | Manage Messages | List custom words |
| `/addword word:<word>` | Manage Messages | Add custom word |
| `/removeword word:<word>` | Manage Messages | Remove custom word |
| `/clearwords confirm:yes` | Manage Messages | Clear all custom words |
| `/resetscores confirm:yes` | Administrator | Wipe all scores |
| `/help` | Everyone | Show all commands |

## User preferences
