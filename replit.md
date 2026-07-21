# Scramble-bot

A Discord unscramble game bot with a leaderboard and custom word pool.

## Stack
- Python (`discord.py`, `flask`, `psycopg2-binary`)
- PostgreSQL (optional — for per-server custom word pools)
- Flask keepalive server on port 8000

## How to run
```
python bot.py
```

## Required secrets
- `DISCORD_TOKEN` — your Discord bot token (required)
- `DATABASE_URL` — PostgreSQL connection string (optional; enables custom word pools per server)

## Features
- `!scramble` — start a word-unscramble game
- `!challenge` — 20-word speed round (60s per word)
- `!hint`, `!skip`, `!end`, `!pause`, `!resume` — game controls
- `!leaderboard`, `!stats`, `!resetscores` — scoring
- `!addword`, `!removeword`, `!clearwords`, `!words`, `!wordcount` — custom word pool management

## User preferences
