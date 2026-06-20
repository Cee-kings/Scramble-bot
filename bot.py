import os
import json
import random
import asyncio
import threading
import psycopg2
import discord
from discord.ext import commands
from flask import Flask

SCORES_FILE = "scores.json"
SKIP_COOLDOWN_SECONDS = 60
CHALLENGE_WORDS = 20
CHALLENGE_WORD_TIMEOUT = 60

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


def scramble_word(word):
    letters = list(word)
    while True:
        random.shuffle(letters)
        scrambled = "".join(letters)
        if scrambled != word:
            return scrambled


intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents, help_command=None)

active_games = {}
active_challenges = {}


@bot.event
async def on_ready():
    print(f"Logged in as {bot.user} (ID: {bot.user.id})")


@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.CommandNotFound):
        return
    if isinstance(error, (commands.MissingPermissions, commands.CommandOnCooldown)):
        return
    print(f"[ERROR] Unhandled command error in '{ctx.command}': {error}")


async def _wait_with_pause(word_event, pause_event, timeout, game_dict=None):
    """Wait for word_event with a pauseable countdown. Returns True if guessed, False if timed out.
    Updates game_dict['elapsed'] each tick so !hint can read active elapsed time."""
    elapsed = 0.0
    tick = 0.25
    while elapsed < timeout:
        if word_event.is_set():
            return True
        if pause_event.is_set():
            elapsed += tick
            if game_dict is not None:
                game_dict["elapsed"] = elapsed
        await asyncio.sleep(tick)
    return False


async def run_challenge(ctx):
    channel_id = ctx.channel.id
    try:
        pause_event = asyncio.Event()
        pause_event.set()
        active_challenges[channel_id]["pause_event"] = pause_event

        await ctx.send(
            f"⚡ **Challenge started! {CHALLENGE_WORDS} words — {CHALLENGE_WORD_TIMEOUT}s per word!**"
        )

        pool = get_words(str(ctx.guild.id))
        word_list = random.sample(pool, min(CHALLENGE_WORDS, len(pool)))

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
            }
            active_games[channel_id] = game_dict

            await ctx.channel.send(
                f"🔀 Word {word_num}/{CHALLENGE_WORDS}: **{scrambled}** — {CHALLENGE_WORD_TIMEOUT}s!"
            )

            guessed = await _wait_with_pause(word_event, pause_event, CHALLENGE_WORD_TIMEOUT, game_dict)
            if not guessed:
                active_games.pop(channel_id, None)
                await ctx.channel.send(f"⏰ Nobody got it! The word was **{word}**.")

        session = active_challenges.pop(channel_id, None)
        active_games.pop(channel_id, None)

        if not session or not session["session_scores"]:
            await ctx.channel.send("🏁 Challenge over! Nobody scored any points.")
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
        await ctx.channel.send(embed=embed)
    except Exception as e:
        print(f"[ERROR] Challenge task crashed: {e}")
        active_challenges.pop(channel_id, None)
        active_games.pop(channel_id, None)


@bot.command(name="challenge")
@commands.has_permissions(manage_messages=True)
async def challenge(ctx):
    channel_id = ctx.channel.id

    if channel_id in active_challenges:
        await ctx.send("A challenge is already running in this channel!")
        return
    if channel_id in active_games:
        await ctx.send("Finish the current `!scramble` game first before starting a challenge.")
        return

    active_challenges[channel_id] = {"session_scores": {}}

    task = asyncio.create_task(run_challenge(ctx))
    active_challenges[channel_id]["task"] = task


@bot.event
async def on_message(message):
    if message.author.bot:
        return

    await bot.process_commands(message)

    if message.content.startswith("!"):
        return

    channel_id = message.channel.id
    guess = message.content.strip().lower()

    # ── Scramble guess handling ──
    try:
        if channel_id in active_games:
            game = active_games[channel_id]
            if guess == game["word"].lower():
                user_id = str(message.author.id)
                user_name = str(message.author)

                if game.get("challenge"):
                    session = active_challenges.get(channel_id)
                    if session:
                        active_games.pop(channel_id, None)
                        if user_id not in session["session_scores"]:
                            session["session_scores"][user_id] = {"name": user_name, "pts": 0}
                        session["session_scores"][user_id]["name"] = user_name
                        session["session_scores"][user_id]["pts"] += 10
                        session_pts = session["session_scores"][user_id]["pts"]
                        await message.channel.send(
                            f"✅ **{message.author.display_name}** got **{game['word']}**! "
                            f"+10 pts ({session_pts} this round)"
                        )
                        word_event = game.get("word_event")
                        if word_event:
                            word_event.set()
                else:
                    scores = load_json(SCORES_FILE, {})
                    if user_id not in scores:
                        scores[user_id] = {"name": user_name, "score": 0}
                    scores[user_id]["name"] = user_name
                    scores[user_id]["score"] += 10
                    save_json(SCORES_FILE, scores)
                    total = scores[user_id]["score"]
                    active_games.pop(channel_id, None)
                    await message.channel.send(
                        f"🎉 **{message.author.display_name}** got it! The word was **{game['word']}**. "
                        f"+10 points! (Total: {total})"
                    )
    except Exception as e:
        print(f"[ERROR] on_message scramble handler: {e}")



@challenge.error
async def challenge_error(ctx, error):
    if isinstance(error, commands.MissingPermissions):
        await ctx.send("You need the **Manage Messages** permission to use this command.")


@bot.command(name="scramble")
@commands.has_permissions(manage_messages=True)
async def scramble(ctx):
    channel_id = ctx.channel.id
    if channel_id in active_challenges:
        await ctx.send("A challenge is running! Wait for it to finish.")
        return
    if channel_id in active_games:
        game = active_games[channel_id]
        await ctx.send(
            f"A game is already running! The scrambled word is: **{game['scrambled']}**"
        )
        return

    word = random.choice(get_words(str(ctx.guild.id)))
    scrambled = scramble_word(word)
    active_games[channel_id] = {"word": word, "scrambled": scrambled}

    await ctx.send(
        f"🔀 Unscramble this word: **{scrambled}**\n"
        f"Type the answer in chat to win 10 points! Use `!hint` if you're stuck."
    )


HINT_UNLOCK_SECONDS = 40

@bot.command(name="hint")
@commands.has_permissions(manage_messages=True)
async def hint(ctx):
    channel_id = ctx.channel.id
    if channel_id not in active_games:
        await ctx.send("No active game! Start one with `!scramble`.")
        return

    game = active_games[channel_id]
    word = game["word"]

    if game.get("challenge"):
        elapsed = game.get("elapsed", 0.0)
        remaining = HINT_UNLOCK_SECONDS - elapsed
        if remaining > 0:
            await ctx.send(
                f"🔒 Hint unlocks after **{HINT_UNLOCK_SECONDS}s** — available in **{int(remaining)+1}s**."
            )
            return

    await ctx.send(f"💡 Hint: The word starts with **{word[0].upper()}** and has **{len(word)}** letters.")


@bot.command(name="skip")
@commands.has_permissions(manage_messages=True)
@commands.cooldown(1, SKIP_COOLDOWN_SECONDS, commands.BucketType.channel)
async def skip(ctx):
    channel_id = ctx.channel.id
    if channel_id in active_challenges:
        await ctx.send("Can't skip during a challenge — just keep guessing!")
        return
    if channel_id not in active_games:
        await ctx.send("No active game! Start one with `!scramble`.")
        return

    word = active_games[channel_id]["word"]
    del active_games[channel_id]
    await ctx.send(f"⏭️ Skipped! The word was **{word}**. Start a new round with `!scramble`.")


@skip.error
async def skip_error(ctx, error):
    if isinstance(error, commands.MissingPermissions):
        await ctx.send("You need the **Manage Messages** permission to use this command.")
    elif isinstance(error, commands.CommandOnCooldown):
        remaining = round(error.retry_after)
        await ctx.send(f"⏳ Skip is on cooldown. Try again in **{remaining}s**.")


@bot.command(name="end")
@commands.has_permissions(manage_messages=True)
async def end(ctx):
    channel_id = ctx.channel.id

    if channel_id in active_challenges:
        session = active_challenges.pop(channel_id, None)
        game = active_games.pop(channel_id, None)
        if session and session.get("task"):
            session["task"].cancel()
        word = game["word"] if game else None
        msg = "🛑 Challenge ended early."
        if word:
            msg += f" The current word was **{word}**."
        await ctx.send(msg)
        return

    if channel_id in active_games:
        word = active_games.pop(channel_id)["word"]
        await ctx.send(f"🛑 Game ended. The word was **{word}**.")
        return

    await ctx.send("There's no active game or challenge in this channel.")


@end.error
async def end_error(ctx, error):
    if isinstance(error, commands.MissingPermissions):
        await ctx.send("You need the **Manage Messages** permission to end a game.")


@bot.command(name="pause")
@commands.has_permissions(manage_messages=True)
async def pause(ctx):
    channel_id = ctx.channel.id
    session = active_challenges.get(channel_id)
    if not session:
        await ctx.send("No challenge is running in this channel.")
        return
    pause_event = session.get("pause_event")
    if pause_event is None or not pause_event.is_set():
        await ctx.send("The challenge is already paused. Use `!resume` to continue.")
        return
    pause_event.clear()
    game = active_games.get(channel_id)
    scrambled = game["scrambled"] if game else "?"
    await ctx.send(f"⏸️ Challenge paused! Timer frozen on **{scrambled}**. Use `!resume` when ready.")


@pause.error
async def pause_error(ctx, error):
    if isinstance(error, commands.MissingPermissions):
        await ctx.send("You need the **Manage Messages** permission to pause a challenge.")


@bot.command(name="resume")
@commands.has_permissions(manage_messages=True)
async def resume(ctx):
    channel_id = ctx.channel.id
    session = active_challenges.get(channel_id)
    if not session:
        await ctx.send("No challenge is running in this channel.")
        return
    pause_event = session.get("pause_event")
    if pause_event is None or pause_event.is_set():
        await ctx.send("The challenge isn't paused.")
        return
    pause_event.set()
    game = active_games.get(channel_id)
    scrambled = game["scrambled"] if game else "?"
    await ctx.send(f"▶️ Challenge resumed! Current word: **{scrambled}** — timer is running!")


@resume.error
async def resume_error(ctx, error):
    if isinstance(error, commands.MissingPermissions):
        await ctx.send("You need the **Manage Messages** permission to resume a challenge.")


@bot.command(name="leaderboard")
async def leaderboard(ctx):
    scores = load_json(SCORES_FILE, {})
    if not scores:
        await ctx.send("No scores yet! Start a game with `!scramble`.")
        return

    sorted_scores = sorted(scores.values(), key=lambda x: x["score"], reverse=True)[:10]
    lines = []
    medals = ["🥇", "🥈", "🥉"]

    for i, entry in enumerate(sorted_scores):
        prefix = medals[i] if i < 3 else f"{i + 1}."
        lines.append(f"{prefix} **{entry['name']}** — {entry['score']} pts")

    embed = discord.Embed(
        title="🏆 Leaderboard — Top 10",
        description="\n".join(lines),
        color=discord.Color.gold(),
    )
    await ctx.send(embed=embed)


@bot.command(name="stats")
async def stats(ctx, member: discord.Member = None):
    member = member or ctx.author
    scores = load_json(SCORES_FILE, {})
    user_id = str(member.id)

    if user_id not in scores:
        await ctx.send(f"**{member.display_name}** hasn't solved any words yet!")
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
    await ctx.send(embed=embed)


@bot.command(name="resetscores")
@commands.has_permissions(administrator=True)
async def resetscores(ctx):
    def check(m):
        return m.author == ctx.author and m.channel == ctx.channel

    await ctx.send(
        "⚠️ This will permanently wipe **all scores**. Type `CONFIRM` to proceed or anything else to cancel."
    )

    try:
        reply = await bot.wait_for("message", check=check, timeout=30)
    except Exception:
        await ctx.send("Reset cancelled — timed out.")
        return

    if reply.content.strip() != "CONFIRM":
        await ctx.send("Reset cancelled.")
        return

    save_json(SCORES_FILE, {})
    await ctx.send("🗑️ All scores have been reset. The leaderboard is now empty.")


@resetscores.error
async def resetscores_error(ctx, error):
    if isinstance(error, commands.MissingPermissions):
        await ctx.send("You need the **Administrator** permission to reset scores.")


@bot.command(name="help")
async def help_command(ctx):
    embed = discord.Embed(
        title="🎮 Unscramble Bot — Commands",
        color=discord.Color.blurple(),
    )
    embed.add_field(
        name="💬 Everyone",
        value=(
            "`!leaderboard` — Top 10 players\n"
            "`!stats [@user]` — View a player's score, words solved & rank\n"
            "`!wordcount` — Total built-in vs. custom words\n"
            "`!words` — List all custom words\n"
            "Just type in chat to guess the current word!"
        ),
        inline=False,
    )
    embed.add_field(
        name="🎯 Manage Messages",
        value=(
            "`!scramble` — Start a new word game\n"
            "`!hint` — Reveal the first letter & word length\n"
            "`!skip` — Give up and reveal the word (60s cooldown)\n"
            "`!challenge` — 20-word round, 60s per word\n"
            "`!addword <word>` — Add a custom word\n"
            "`!removeword <word>` — Remove a custom word\n"
            "`!clearwords` — Clear all custom words"
        ),
        inline=False,
    )
    embed.add_field(
        name="🔐 Admin",
        value="`!resetscores` — Wipe all scores",
        inline=False,
    )
    embed.set_footer(text="Type the answer in chat (no prefix) to score 10 points!")
    await ctx.send(embed=embed)


@bot.command(name="clearwords")
@commands.has_permissions(manage_messages=True)
async def clearwords(ctx):
    def check(m):
        return m.author == ctx.author and m.channel == ctx.channel

    guild_id = str(ctx.guild.id)
    custom = db_get_custom_words(guild_id)
    if not custom:
        await ctx.send("There are no custom words to clear.")
        return

    await ctx.send(
        f"⚠️ This will remove all **{len(custom)} custom words**. Type `CONFIRM` to proceed or anything else to cancel."
    )

    try:
        reply = await bot.wait_for("message", check=check, timeout=30)
    except Exception:
        await ctx.send("Clear cancelled — timed out.")
        return

    if reply.content.strip() != "CONFIRM":
        await ctx.send("Clear cancelled.")
        return

    deleted = db_clear_custom_words(guild_id)
    await ctx.send(f"🗑️ Cleared {deleted} custom word(s). Rounds will now use the {len(DEFAULT_WORDS)} built-in words.")


@clearwords.error
async def clearwords_error(ctx, error):
    if isinstance(error, commands.MissingPermissions):
        await ctx.send("You need the **Manage Messages** permission to clear custom words.")


@bot.command(name="wordcount")
async def wordcount(ctx):
    custom = db_get_custom_words(str(ctx.guild.id))
    if custom:
        await ctx.send(
            f"📚 Word pool: **{len(custom)} custom words** (built-in words are not used while custom words are set)"
        )
    else:
        await ctx.send(
            f"📚 Word pool: **{len(DEFAULT_WORDS)} built-in words** (no custom words set for this server)"
        )


@bot.command(name="words")
@commands.has_permissions(manage_messages=True)
async def words(ctx):
    custom = db_get_custom_words(str(ctx.guild.id))
    if not custom:
        await ctx.send("No custom words yet! Add some with `!addword <word>`.")
        return

    word_list = ", ".join(f"**{w}**" for w in custom)
    await ctx.send(f"📝 Custom words ({len(custom)}): {word_list}")


@bot.command(name="addword")
@commands.has_permissions(manage_messages=True)
async def addword(ctx, *, word: str):
    word = word.strip().lower()
    if len(word) < 3:
        await ctx.send("Words must be at least 3 characters long.")
        return

    guild_id = str(ctx.guild.id)
    if word in DEFAULT_WORDS:
        await ctx.send(f"**{word}** is already a built-in word.")
        return

    added = db_add_custom_word(guild_id, word, str(ctx.author))
    if not added:
        await ctx.send(f"**{word}** is already in the custom word pool.")
        return

    await ctx.send(f"✅ Added **{word}** to this server's word pool. (Pool size: {len(get_words(guild_id))})")


@bot.command(name="removeword")
@commands.has_permissions(manage_messages=True)
async def removeword(ctx, *, word: str):
    word = word.strip().lower()

    if word in DEFAULT_WORDS:
        await ctx.send(f"**{word}** is a built-in word and cannot be removed.")
        return

    removed = db_remove_custom_word(str(ctx.guild.id), word)
    if not removed:
        await ctx.send(f"**{word}** is not in this server's custom word pool.")
        return

    await ctx.send(f"🗑️ Removed **{word}** from this server's word pool.")


@scramble.error
@hint.error
@addword.error
@removeword.error
@words.error
async def manage_messages_error(ctx, error):
    if isinstance(error, commands.MissingPermissions):
        await ctx.send("You need the **Manage Messages** permission to use this command.")



keepalive = Flask(__name__)


@keepalive.route("/")
def alive():
    return "OK", 200


def run_keepalive():
    keepalive.run(host="0.0.0.0", port=8000)


token = os.environ.get("DISCORD_TOKEN")
if not token:
    raise RuntimeError("DISCORD_TOKEN environment variable is not set.")

init_db()
threading.Thread(target=run_keepalive, daemon=True).start()
bot.run(token)
