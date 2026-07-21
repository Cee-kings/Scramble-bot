import os
import json
import random
import asyncio
import threading
import time
import psycopg2
import discord
from discord import app_commands
from flask import Flask

# ── Constants ──────────────────────────────────────────────────────────────────
SCORES_FILE = "scores.json"
SKIP_COOLDOWN_SECONDS = 60
CHALLENGE_WORDS = 20
CHALLENGE_WORD_TIMEOUT = 60
HINT_UNLOCK_SECONDS = 40

DEFAULT_WORDS = [
    "python", "discord", "scramble", "keyboard", "monitor", "network",
    "server", "client", "database", "function", "variable", "integer",
    "boolean", "library", "package", "module", "class", "object",
    "method", "string", "turtle", "dolphin", "penguin", "elephant",
    "giraffe", "kangaroo", "platypus", "volcano", "glacier", "thunder",
    "lightning", "rainbow", "crystal", "diamond", "emerald", "sapphire",
    "adventure", "mystery", "journey", "treasure", "fortress", "dungeon",
    "champion", "triumph", "victory", "courage", "wisdom", "justice",
]

# ── JSON helpers ───────────────────────────────────────────────────────────────
def load_json(path, default):
    try:
        if os.path.exists(path):
            with open(path, "r") as f:
                return json.load(f)
    except (json.JSONDecodeError, OSError):
        pass
    return default


def save_json(path, data):
    try:
        with open(path, "w") as f:
            json.dump(data, f, indent=2)
    except OSError as e:
        print(f"[ERROR] Failed to save {path}: {e}")


# ── Database ───────────────────────────────────────────────────────────────────
def init_db():
    url = os.environ.get("DATABASE_URL")
    if not url:
        print("[WARN] DATABASE_URL not set — custom words disabled.")
        return
    try:
        with psycopg2.connect(url) as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS custom_words (
                        id         SERIAL PRIMARY KEY,
                        guild_id   TEXT NOT NULL,
                        word       TEXT NOT NULL,
                        added_by   TEXT NOT NULL,
                        created_at TIMESTAMP NOT NULL DEFAULT NOW(),
                        UNIQUE(guild_id, word)
                    )
                """)
                cur.execute(
                    "CREATE INDEX IF NOT EXISTS idx_custom_words_guild "
                    "ON custom_words(guild_id)"
                )
        print("[DB] custom_words table ready.")
    except Exception as e:
        print(f"[ERROR] init_db: {e}")


def _db_conn():
    return psycopg2.connect(os.environ["DATABASE_URL"])


def db_get_custom_words(guild_id: str) -> list:
    try:
        with _db_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT word FROM custom_words WHERE guild_id = %s ORDER BY word",
                    (guild_id,)
                )
                return [row[0] for row in cur.fetchall()]
    except Exception as e:
        print(f"[ERROR] db_get_custom_words: {e}")
        return []


def db_add_custom_word(guild_id: str, word: str, added_by: str) -> bool:
    try:
        with _db_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO custom_words (guild_id, word, added_by) "
                    "VALUES (%s, %s, %s) ON CONFLICT DO NOTHING",
                    (guild_id, word, added_by)
                )
                return cur.rowcount > 0
    except Exception as e:
        print(f"[ERROR] db_add_custom_word: {e}")
        return False


def db_remove_custom_word(guild_id: str, word: str) -> bool:
    try:
        with _db_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "DELETE FROM custom_words WHERE guild_id = %s AND word = %s",
                    (guild_id, word)
                )
                return cur.rowcount > 0
    except Exception as e:
        print(f"[ERROR] db_remove_custom_word: {e}")
        return False


def db_clear_custom_words(guild_id: str) -> int:
    try:
        with _db_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "DELETE FROM custom_words WHERE guild_id = %s",
                    (guild_id,)
                )
                return cur.rowcount
    except Exception as e:
        print(f"[ERROR] db_clear_custom_words: {e}")
        return 0


def get_words(guild_id: str) -> list:
    custom = db_get_custom_words(guild_id)
    if custom:
        return custom
    return list(DEFAULT_WORDS)


def scramble_word(word: str) -> str:
    letters = list(word)
    while True:
        random.shuffle(letters)
        scrambled = "".join(letters)
        if scrambled != word:
            return scrambled


# ── Client setup ───────────────────────────────────────────────────────────────
# No privileged intents needed.
# Replies to the bot and @mentions deliver message content without Message Content intent.
intents = discord.Intents.default()
client = discord.Client(intents=intents)
tree = app_commands.CommandTree(client)

# Game state
active_games: dict[int, dict] = {}       # channel_id -> game dict
active_challenges: dict[int, dict] = {}  # channel_id -> challenge dict
skip_cooldowns: dict[int, float] = {}    # channel_id -> last-skip monotonic time


# ── Shared game logic ──────────────────────────────────────────────────────────
async def _wait_with_pause(
    word_event, pause_event, timeout,
    game_dict=None, on_hint=None, hint_at=None,
):
    """Pauseable countdown. Returns True if guessed, False if timed out."""
    elapsed = 0.0
    tick = 0.25
    hint_fired = False
    while elapsed < timeout:
        if word_event.is_set():
            return True
        if pause_event.is_set():
            elapsed += tick
            if game_dict is not None:
                game_dict["elapsed"] = elapsed
            if on_hint and hint_at and not hint_fired and elapsed >= hint_at:
                hint_fired = True
                await on_hint()
        await asyncio.sleep(tick)
    return False


async def _apply_correct_guess(channel_id: int, user: discord.User | discord.Member) -> str:
    """
    Shared logic for a correct guess. Mutates active_games / active_challenges,
    saves scores, and returns the public announcement string.
    Caller is responsible for sending it.
    """
    game = active_games[channel_id]
    user_id = str(user.id)
    user_name = str(user)
    display_name = user.display_name

    if game.get("challenge"):
        session = active_challenges.get(channel_id)
        if not session:
            return ""
        active_games.pop(channel_id, None)
        if user_id not in session["session_scores"]:
            session["session_scores"][user_id] = {"name": user_name, "pts": 0}
        session["session_scores"][user_id]["name"] = user_name
        session["session_scores"][user_id]["pts"] += 10
        session_pts = session["session_scores"][user_id]["pts"]
        word_event = game.get("word_event")
        if word_event:
            word_event.set()
        return (
            f"✅ **{display_name}** got **{game['word']}**! "
            f"+10 pts ({session_pts} this round)"
        )
    else:
        scores = load_json(SCORES_FILE, {})
        if user_id not in scores:
            scores[user_id] = {"name": user_name, "score": 0}
        scores[user_id]["name"] = user_name
        scores[user_id]["score"] += 10
        save_json(SCORES_FILE, scores)
        total = scores[user_id]["score"]
        active_games.pop(channel_id, None)
        return (
            f"🎉 **{display_name}** got it! The word was **{game['word']}**. "
            f"+10 points! (Total: {total})"
        )


async def run_challenge(channel: discord.TextChannel, guild_id: str):
    """Background task that drives a challenge round."""
    channel_id = channel.id
    try:
        pause_event = asyncio.Event()
        pause_event.set()
        active_challenges[channel_id]["pause_event"] = pause_event

        custom = db_get_custom_words(guild_id)
        custom_set = {w.lower() for w in custom}
        random.shuffle(custom)
        fill = [w for w in DEFAULT_WORDS if w.lower() not in custom_set]
        random.shuffle(fill)
        word_list = (custom + fill)[:CHALLENGE_WORDS]

        for word_num, word in enumerate(word_list, 1):
            if channel_id not in active_challenges:
                break

            scrambled = scramble_word(word)
            word_event = asyncio.Event()
            game_dict = {
                "word": word,
                "scrambled": scrambled,
                "challenge": True,
                "word_event": word_event,
                "elapsed": 0.0,
                "prompt_msg_id": None,   # filled in after send
            }
            active_games[channel_id] = game_dict

            msg = await channel.send(
                f"🔀 Word {word_num}/{CHALLENGE_WORDS}: **{scrambled}** — {CHALLENGE_WORD_TIMEOUT}s!\n"
                f"Reply to this message or mention me with your answer!"
            )
            game_dict["prompt_msg_id"] = msg.id  # store so reply detection works

            async def auto_hint(ch_id=channel_id, we=word_event):
                game = active_games.get(ch_id)
                if game and not we.is_set():
                    w = game["word"]
                    await channel.send(
                        f"💡 **Auto-hint:** The word starts with **{w[0].upper()}** "
                        f"and ends with **{w[-1].upper()}** — **{len(w)}** letters."
                    )

            guessed = await _wait_with_pause(
                word_event, pause_event, CHALLENGE_WORD_TIMEOUT, game_dict,
                on_hint=auto_hint, hint_at=HINT_UNLOCK_SECONDS,
            )
            if not guessed:
                active_games.pop(channel_id, None)
                await channel.send(f"⏰ Nobody got it! The word was **{word}**.")

        session = active_challenges.pop(channel_id, None)
        active_games.pop(channel_id, None)

        if not session or not session["session_scores"]:
            await channel.send("🏁 Challenge over! Nobody scored any points.")
            return

        scores = load_json(SCORES_FILE, {})
        for uid, data in session["session_scores"].items():
            if uid not in scores:
                scores[uid] = {"name": data["name"], "score": 0}
            scores[uid]["name"] = data["name"]
            scores[uid]["score"] += data["pts"]
        save_json(SCORES_FILE, scores)

        sorted_session = sorted(
            session["session_scores"].items(), key=lambda x: x[1]["pts"], reverse=True
        )
        medals = ["🥇", "🥈", "🥉"]
        lines = []
        for i, (uid, data) in enumerate(sorted_session):
            prefix = medals[i] if i < 3 else f"{i + 1}."
            lines.append(f"{prefix} **{data['name']}** — {data['pts']} pts this round")

        winner_name = sorted_session[0][1]["name"]
        embed = discord.Embed(
            title=f"🏁 Challenge Over! All {CHALLENGE_WORDS} Words Done",
            description=f"**{winner_name}** wins the round!\n\n" + "\n".join(lines),
            color=discord.Color.orange(),
        )
        await channel.send(embed=embed)

    except Exception as e:
        print(f"[ERROR] Challenge task crashed: {e}")
        active_challenges.pop(channel_id, None)
        active_games.pop(channel_id, None)


# ── on_ready — register slash commands ────────────────────────────────────────
@client.event
async def on_ready():
    synced = await tree.sync()
    print(f"Logged in as {client.user} (ID: {client.user.id})")
    print(f"Synced {len(synced)} slash command(s) globally.")


# ── on_message — handle replies and @mentions as guesses ──────────────────────
@client.event
async def on_message(message: discord.Message):
    # Ignore bots
    if message.author.bot:
        return

    channel_id = message.channel.id

    # Determine if this message is a reply to the current word prompt
    is_reply_to_prompt = (
        message.reference is not None
        and channel_id in active_games
        and message.reference.message_id == active_games[channel_id].get("prompt_msg_id")
    )

    # Determine if the bot is mentioned
    is_mention = client.user in message.mentions

    if not is_reply_to_prompt and not is_mention:
        return

    if channel_id not in active_games:
        # Mentioned but no game running — let them know
        if is_mention:
            await message.reply(
                "No active game right now! Use `/scramble` to start one.",
                mention_author=False,
            )
        return

    # Extract guess text: strip bot mention(s) and surrounding whitespace
    raw = message.content or ""
    raw = raw.replace(f"<@{client.user.id}>", "").replace(f"<@!{client.user.id}>", "")
    guess = raw.strip().lower()

    if not guess:
        return

    game = active_games[channel_id]
    if guess != game["word"].lower():
        # Wrong — add a ❌ reaction so the channel isn't flooded with "wrong!" messages
        try:
            await message.add_reaction("❌")
        except discord.HTTPException:
            pass
        return

    # Correct guess — process and announce publicly
    result = await _apply_correct_guess(channel_id, message.author)
    if result:
        await message.channel.send(result)


# ── Global app-command error handler ──────────────────────────────────────────
@tree.error
async def on_app_command_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    if isinstance(error, app_commands.MissingPermissions):
        await interaction.response.send_message(
            "You don't have permission to use this command.", ephemeral=True
        )
    else:
        print(f"[ERROR] App command '{interaction.command}': {error}")
        if not interaction.response.is_done():
            await interaction.response.send_message("An unexpected error occurred.", ephemeral=True)


# ══════════════════════════════════════════════════════════════════════════════
# SLASH COMMANDS
# ══════════════════════════════════════════════════════════════════════════════

# ── /scramble ─────────────────────────────────────────────────────────────────
@tree.command(
    name="scramble",
    description="Start a new unscramble round in this channel",
)
@app_commands.default_permissions(manage_messages=True)
async def cmd_scramble(interaction: discord.Interaction):
    channel_id = interaction.channel_id
    if channel_id in active_challenges:
        await interaction.response.send_message(
            "A challenge is running! Wait for it to finish.", ephemeral=True
        )
        return
    if channel_id in active_games:
        game = active_games[channel_id]
        await interaction.response.send_message(
            f"A game is already running! The scrambled word is: **{game['scrambled']}**",
            ephemeral=True,
        )
        return

    guild_id = str(interaction.guild_id)
    word = random.choice(get_words(guild_id))
    scrambled = scramble_word(word)

    await interaction.response.send_message(
        f"🔀 Unscramble this word: **{scrambled}**\n"
        f"**Reply to this message** or **@mention me** with your answer to win 10 points!\n"
        f"Use `/hint` if you're stuck, or `/guess` if you prefer slash commands."
    )

    # Store the prompt message ID so reply detection works
    prompt_msg = await interaction.original_response()
    active_games[channel_id] = {
        "word": word,
        "scrambled": scrambled,
        "prompt_msg_id": prompt_msg.id,
    }


# ── /guess (fallback slash command) ───────────────────────────────────────────
@tree.command(
    name="guess",
    description="Submit your answer for the current scramble word",
)
@app_commands.describe(word="Your answer")
async def cmd_guess(interaction: discord.Interaction, word: str):
    channel_id = interaction.channel_id
    guess = word.strip().lower()

    if channel_id not in active_games:
        await interaction.response.send_message(
            "No active game in this channel! Start one with `/scramble`.", ephemeral=True
        )
        return

    game = active_games[channel_id]
    if guess != game["word"].lower():
        await interaction.response.send_message("❌ Wrong answer — keep trying!", ephemeral=True)
        return

    result = await _apply_correct_guess(channel_id, interaction.user)
    if result:
        await interaction.response.send_message(result)
    else:
        await interaction.response.send_message("Something went wrong processing your guess.", ephemeral=True)


# ── /challenge ────────────────────────────────────────────────────────────────
@tree.command(
    name="challenge",
    description=f"Start a {CHALLENGE_WORDS}-word speed round ({CHALLENGE_WORD_TIMEOUT}s per word)",
)
@app_commands.default_permissions(manage_messages=True)
async def cmd_challenge(interaction: discord.Interaction):
    channel_id = interaction.channel_id

    if channel_id in active_challenges:
        await interaction.response.send_message(
            "A challenge is already running in this channel!", ephemeral=True
        )
        return
    if channel_id in active_games:
        await interaction.response.send_message(
            "Finish the current `/scramble` game first before starting a challenge.",
            ephemeral=True,
        )
        return

    active_challenges[channel_id] = {"session_scores": {}}
    guild_id = str(interaction.guild_id)

    await interaction.response.send_message(
        f"⚡ **Challenge started! {CHALLENGE_WORDS} words — {CHALLENGE_WORD_TIMEOUT}s per word!**\n"
        f"Reply to each word message or @mention me with your answer!"
    )

    task = asyncio.create_task(run_challenge(interaction.channel, guild_id))
    active_challenges[channel_id]["task"] = task


# ── /hint ─────────────────────────────────────────────────────────────────────
@tree.command(
    name="hint",
    description="Get the first letter, last letter, and length of the current word",
)
@app_commands.default_permissions(manage_messages=True)
async def cmd_hint(interaction: discord.Interaction):
    channel_id = interaction.channel_id
    if channel_id not in active_games:
        await interaction.response.send_message(
            "No active game! Start one with `/scramble`.", ephemeral=True
        )
        return

    game = active_games[channel_id]
    word = game["word"]

    if game.get("challenge"):
        elapsed = game.get("elapsed", 0.0)
        remaining = HINT_UNLOCK_SECONDS - elapsed
        if remaining > 0:
            await interaction.response.send_message(
                f"🔒 Hint unlocks after **{HINT_UNLOCK_SECONDS}s** — "
                f"available in **{int(remaining)+1}s**.",
                ephemeral=True,
            )
            return

    await interaction.response.send_message(
        f"💡 Hint: The word starts with **{word[0].upper()}** "
        f"and ends with **{word[-1].upper()}** — **{len(word)}** letters."
    )


# ── /skip ─────────────────────────────────────────────────────────────────────
@tree.command(
    name="skip",
    description=f"Give up and reveal the current word ({SKIP_COOLDOWN_SECONDS}s cooldown per channel)",
)
@app_commands.default_permissions(manage_messages=True)
async def cmd_skip(interaction: discord.Interaction):
    channel_id = interaction.channel_id

    if channel_id in active_challenges:
        await interaction.response.send_message(
            "Can't skip during a challenge — just keep guessing!", ephemeral=True
        )
        return
    if channel_id not in active_games:
        await interaction.response.send_message(
            "No active game! Start one with `/scramble`.", ephemeral=True
        )
        return

    last_skip = skip_cooldowns.get(channel_id, 0.0)
    elapsed_since = time.monotonic() - last_skip
    if elapsed_since < SKIP_COOLDOWN_SECONDS:
        remaining = int(SKIP_COOLDOWN_SECONDS - elapsed_since) + 1
        await interaction.response.send_message(
            f"⏳ Skip is on cooldown. Try again in **{remaining}s**.", ephemeral=True
        )
        return

    word = active_games.pop(channel_id)["word"]
    skip_cooldowns[channel_id] = time.monotonic()
    await interaction.response.send_message(
        f"⏭️ Skipped! The word was **{word}**. Start a new round with `/scramble`."
    )


# ── /end ──────────────────────────────────────────────────────────────────────
@tree.command(
    name="end",
    description="Stop the current game or challenge early",
)
@app_commands.default_permissions(manage_messages=True)
async def cmd_end(interaction: discord.Interaction):
    channel_id = interaction.channel_id

    if channel_id in active_challenges:
        session = active_challenges.pop(channel_id, None)
        game = active_games.pop(channel_id, None)
        if session and session.get("task"):
            session["task"].cancel()
        word = game["word"] if game else None
        msg = "🛑 Challenge ended early."
        if word:
            msg += f" The current word was **{word}**."
        await interaction.response.send_message(msg)
        return

    if channel_id in active_games:
        word = active_games.pop(channel_id)["word"]
        await interaction.response.send_message(f"🛑 Game ended. The word was **{word}**.")
        return

    await interaction.response.send_message(
        "There's no active game or challenge in this channel.", ephemeral=True
    )


# ── /pause ────────────────────────────────────────────────────────────────────
@tree.command(
    name="pause",
    description="Freeze the challenge timer",
)
@app_commands.default_permissions(manage_messages=True)
async def cmd_pause(interaction: discord.Interaction):
    channel_id = interaction.channel_id
    session = active_challenges.get(channel_id)
    if not session:
        await interaction.response.send_message(
            "No challenge is running in this channel.", ephemeral=True
        )
        return
    pause_event = session.get("pause_event")
    if pause_event is None or not pause_event.is_set():
        await interaction.response.send_message(
            "The challenge is already paused. Use `/resume` to continue.", ephemeral=True
        )
        return
    pause_event.clear()
    game = active_games.get(channel_id)
    scrambled = game["scrambled"] if game else "?"
    await interaction.response.send_message(
        f"⏸️ Challenge paused! Timer frozen on **{scrambled}**. Use `/resume` when ready."
    )


# ── /resume ───────────────────────────────────────────────────────────────────
@tree.command(
    name="resume",
    description="Unfreeze the challenge timer",
)
@app_commands.default_permissions(manage_messages=True)
async def cmd_resume(interaction: discord.Interaction):
    channel_id = interaction.channel_id
    session = active_challenges.get(channel_id)
    if not session:
        await interaction.response.send_message(
            "No challenge is running in this channel.", ephemeral=True
        )
        return
    pause_event = session.get("pause_event")
    if pause_event is None or pause_event.is_set():
        await interaction.response.send_message(
            "The challenge isn't paused.", ephemeral=True
        )
        return
    pause_event.set()
    game = active_games.get(channel_id)
    scrambled = game["scrambled"] if game else "?"
    await interaction.response.send_message(
        f"▶️ Challenge resumed! Current word: **{scrambled}** — timer is running!"
    )


# ── /leaderboard ──────────────────────────────────────────────────────────────
@tree.command(
    name="leaderboard",
    description="Show the top 10 players",
)
async def cmd_leaderboard(interaction: discord.Interaction):
    scores = load_json(SCORES_FILE, {})
    if not scores:
        await interaction.response.send_message(
            "No scores yet! Start a game with `/scramble`.", ephemeral=True
        )
        return

    sorted_scores = sorted(scores.values(), key=lambda x: x["score"], reverse=True)[:10]
    medals = ["🥇", "🥈", "🥉"]
    lines = []
    for i, entry in enumerate(sorted_scores):
        prefix = medals[i] if i < 3 else f"{i + 1}."
        lines.append(f"{prefix} **{entry['name']}** — {entry['score']} pts")

    embed = discord.Embed(
        title="🏆 Leaderboard — Top 10",
        description="\n".join(lines),
        color=discord.Color.gold(),
    )
    await interaction.response.send_message(embed=embed)


# ── /stats ────────────────────────────────────────────────────────────────────
@tree.command(
    name="stats",
    description="View a player's score, words solved, and rank",
)
@app_commands.describe(member="The player to look up (defaults to you)")
async def cmd_stats(interaction: discord.Interaction, member: discord.Member = None):
    member = member or interaction.user
    scores = load_json(SCORES_FILE, {})
    user_id = str(member.id)

    if user_id not in scores:
        await interaction.response.send_message(
            f"**{member.display_name}** hasn't solved any words yet!", ephemeral=True
        )
        return

    entry = scores[user_id]
    score = entry["score"]
    words_solved = score // 10
    sorted_ids = sorted(scores, key=lambda k: scores[k]["score"], reverse=True)
    rank = sorted_ids.index(user_id) + 1

    embed = discord.Embed(
        title=f"📊 Stats for {member.display_name}",
        color=discord.Color.blurple(),
    )
    embed.add_field(name="Score", value=f"{score} pts", inline=True)
    embed.add_field(name="Words Solved", value=str(words_solved), inline=True)
    embed.add_field(name="Rank", value=f"#{rank} of {len(scores)}", inline=True)
    embed.set_thumbnail(url=member.display_avatar.url)
    await interaction.response.send_message(embed=embed)


# ── /resetscores ──────────────────────────────────────────────────────────────
@tree.command(
    name="resetscores",
    description="Permanently wipe all scores from the leaderboard (admin only)",
)
@app_commands.describe(confirm="Type 'yes' to confirm — this cannot be undone")
@app_commands.default_permissions(administrator=True)
async def cmd_resetscores(interaction: discord.Interaction, confirm: str):
    if confirm.strip().lower() != "yes":
        await interaction.response.send_message(
            "Reset cancelled. Pass `confirm:yes` to confirm.", ephemeral=True
        )
        return
    save_json(SCORES_FILE, {})
    await interaction.response.send_message(
        "🗑️ All scores have been reset. The leaderboard is now empty."
    )


# ── /words ────────────────────────────────────────────────────────────────────
@tree.command(
    name="words",
    description="List this server's custom word pool",
)
@app_commands.default_permissions(manage_messages=True)
async def cmd_words(interaction: discord.Interaction):
    custom = db_get_custom_words(str(interaction.guild_id))
    if not custom:
        await interaction.response.send_message(
            "No custom words yet! Add some with `/addword`.", ephemeral=True
        )
        return
    word_list = ", ".join(f"**{w}**" for w in custom)
    await interaction.response.send_message(f"📝 Custom words ({len(custom)}): {word_list}")


# ── /wordcount ────────────────────────────────────────────────────────────────
@tree.command(
    name="wordcount",
    description="Show how many words are in this server's word pool",
)
async def cmd_wordcount(interaction: discord.Interaction):
    custom = db_get_custom_words(str(interaction.guild_id))
    if custom:
        await interaction.response.send_message(
            f"📚 Word pool: **{len(custom)} custom words** (only your server's words are used)"
        )
    else:
        await interaction.response.send_message(
            f"📚 Word pool: **{len(DEFAULT_WORDS)} built-in words** (no custom words set for this server)"
        )


# ── /addword ──────────────────────────────────────────────────────────────────
@tree.command(
    name="addword",
    description="Add a custom word to this server's word pool",
)
@app_commands.describe(word="The word to add (3+ letters)")
@app_commands.default_permissions(manage_messages=True)
async def cmd_addword(interaction: discord.Interaction, word: str):
    word = word.strip().lower()
    if len(word) < 3:
        await interaction.response.send_message(
            "Words must be at least 3 characters long.", ephemeral=True
        )
        return

    guild_id = str(interaction.guild_id)
    if word in DEFAULT_WORDS:
        await interaction.response.send_message(
            f"**{word}** is already a built-in word.", ephemeral=True
        )
        return

    added = db_add_custom_word(guild_id, word, str(interaction.user))
    if not added:
        await interaction.response.send_message(
            f"**{word}** is already in the custom word pool.", ephemeral=True
        )
        return

    await interaction.response.send_message(
        f"✅ Added **{word}** to this server's word pool. (Pool size: {len(get_words(guild_id))})"
    )


# ── /removeword ───────────────────────────────────────────────────────────────
@tree.command(
    name="removeword",
    description="Remove a custom word from this server's word pool",
)
@app_commands.describe(word="The word to remove")
@app_commands.default_permissions(manage_messages=True)
async def cmd_removeword(interaction: discord.Interaction, word: str):
    word = word.strip().lower()
    if word in DEFAULT_WORDS:
        await interaction.response.send_message(
            f"**{word}** is a built-in word and cannot be removed.", ephemeral=True
        )
        return

    removed = db_remove_custom_word(str(interaction.guild_id), word)
    if not removed:
        await interaction.response.send_message(
            f"**{word}** is not in this server's custom word pool.", ephemeral=True
        )
        return

    await interaction.response.send_message(f"🗑️ Removed **{word}** from this server's word pool.")


# ── /clearwords ───────────────────────────────────────────────────────────────
@tree.command(
    name="clearwords",
    description="Remove all custom words from this server's word pool",
)
@app_commands.describe(confirm="Type 'yes' to confirm — this cannot be undone")
@app_commands.default_permissions(manage_messages=True)
async def cmd_clearwords(interaction: discord.Interaction, confirm: str):
    guild_id = str(interaction.guild_id)
    custom = db_get_custom_words(guild_id)
    if not custom:
        await interaction.response.send_message(
            "There are no custom words to clear.", ephemeral=True
        )
        return
    if confirm.strip().lower() != "yes":
        await interaction.response.send_message(
            f"This will remove all **{len(custom)} custom words**. "
            f"Pass `confirm:yes` to proceed.",
            ephemeral=True,
        )
        return

    deleted = db_clear_custom_words(guild_id)
    await interaction.response.send_message(
        f"🗑️ Cleared {deleted} custom word(s). "
        f"Rounds will now use the {len(DEFAULT_WORDS)} built-in words."
    )


# ── /help ─────────────────────────────────────────────────────────────────────
@tree.command(
    name="help",
    description="Show all bot commands",
)
async def cmd_help(interaction: discord.Interaction):
    embed = discord.Embed(
        title="🎮 Unscramble Bot — Commands",
        color=discord.Color.blurple(),
    )
    embed.add_field(
        name="💬 Everyone",
        value=(
            "**Reply** to the word message or **@mention me** with your answer to guess!\n"
            "`/guess word:<answer>` — slash command fallback\n"
            "`/leaderboard` — Top 10 players\n"
            "`/stats [member]` — View a player's score, words solved & rank\n"
            "`/wordcount` — Total words in this server's pool"
        ),
        inline=False,
    )
    embed.add_field(
        name="🎯 Manage Messages",
        value=(
            "`/scramble` — Start a new word game\n"
            "`/challenge` — 20-word speed round, 60s per word\n"
            "`/hint` — First & last letter + word length (instant in solo, unlocks at 40s in challenge)\n"
            "`/skip` — Give up and reveal the word (60s cooldown)\n"
            "`/pause` — Freeze the challenge timer\n"
            "`/resume` — Unfreeze the challenge timer\n"
            "`/end` — Stop the current game or challenge early\n"
            "`/words` — List this server's custom words\n"
            "`/addword word:<word>` — Add a custom word\n"
            "`/removeword word:<word>` — Remove a custom word\n"
            "`/clearwords confirm:yes` — Clear all custom words"
        ),
        inline=False,
    )
    embed.add_field(
        name="🔐 Admin",
        value="`/resetscores confirm:yes` — Wipe all scores",
        inline=False,
    )
    embed.set_footer(text="Reply to the word message or @mention the bot to guess!")
    await interaction.response.send_message(embed=embed)


# ── Keepalive server ───────────────────────────────────────────────────────────
keepalive = Flask(__name__)


@keepalive.route("/")
def alive():
    return "OK", 200


def run_keepalive():
    keepalive.run(host="0.0.0.0", port=8000)


# ── Entry point ────────────────────────────────────────────────────────────────
token = os.environ.get("DISCORD_TOKEN")
if not token:
    raise RuntimeError("DISCORD_TOKEN environment variable is not set.")

init_db()
threading.Thread(target=run_keepalive, daemon=True).start()
client.run(token)
