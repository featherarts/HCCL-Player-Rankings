"""HCCL Telegram Bot.

Run locally:
    python telegram_bot.py

Required environment variables:
    TELEGRAM_BOT_TOKEN
    SUPABASE_URL
    SUPABASE_KEY

Optional environment variables:
    ALLOWED_CHAT_IDS       comma-separated chat IDs allowed to use the bot
    DEFAULT_TOP_LIMIT      default number for /top commands, default 10
"""

from __future__ import annotations

import logging
import os
from typing import Callable, List, Optional

from dotenv import load_dotenv
from telegram import BotCommand, Update
from telegram.ext import Application, ApplicationBuilder, CommandHandler, ContextTypes

from hccl_bot_data import (
    BENCHMARK_LABELS,
    HCCLBotError,
    HCCLSupabaseStore,
    VALID_CATEGORIES,
    format_player_line,
    format_rank,
    format_rating,
    parse_category,
)

load_dotenv()

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger("hccl-telegram-bot")


def get_allowed_chat_ids() -> Optional[set[int]]:
    raw = os.getenv("ALLOWED_CHAT_IDS", "").strip()
    if not raw:
        return None
    allowed: set[int] = set()
    for part in raw.split(","):
        part = part.strip()
        if part:
            try:
                allowed.add(int(part))
            except ValueError:
                logger.warning("Ignoring invalid chat id in ALLOWED_CHAT_IDS: %s", part)
    return allowed or None


ALLOWED_CHAT_IDS = get_allowed_chat_ids()


def default_limit() -> int:
    try:
        return max(1, min(25, int(os.getenv("DEFAULT_TOP_LIMIT", "10"))))
    except Exception:
        return 10


def parse_limit(args: List[str], fallback: int = 10) -> int:
    if not args:
        return fallback
    try:
        return max(1, min(25, int(args[0])))
    except Exception:
        return fallback


async def guard(update: Update) -> bool:
    """Return True when the message is allowed."""
    if ALLOWED_CHAT_IDS is None:
        return True
    chat = update.effective_chat
    if chat and chat.id in ALLOWED_CHAT_IDS:
        return True
    if update.effective_message:
        await update.effective_message.reply_text("Sorry, this HCCL bot is private.")
    return False


async def safe_reply(update: Update, text: str) -> None:
    """Telegram messages have a hard length limit. Split long replies safely."""
    if not update.effective_message:
        return
    text = text.strip() or "No data found."
    max_len = 3900
    if len(text) <= max_len:
        await update.effective_message.reply_text(text)
        return

    chunks: List[str] = []
    current = ""
    for line in text.splitlines():
        if len(current) + len(line) + 1 > max_len:
            chunks.append(current)
            current = line
        else:
            current = f"{current}\n{line}" if current else line
    if current:
        chunks.append(current)
    for chunk in chunks:
        await update.effective_message.reply_text(chunk)


def store() -> HCCLSupabaseStore:
    return HCCLSupabaseStore()


def snapshot_header(snapshot, title: str) -> str:
    official = "Official only" if snapshot.official_only else "All calculated players"
    return f"{title}\n{snapshot.week_label} | {snapshot.snapshot_date} | {official}\n"


def format_top(category: str, limit: int) -> str:
    snapshot, rows = store().top(category, limit=limit)
    if not rows:
        return f"No {category} rankings found."
    lines = [snapshot_header(snapshot, f"🏏 HCCL {category} Top {limit}" if category == "Batting" else f"HCCL {category} Top {limit}")]
    for row in rows:
        icon = "🏏" if category == "Batting" else "🎯" if category == "Bowling" else "👑"
        lines.append(f"{icon} {format_player_line(row)}")
    return "\n".join(lines)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await guard(update):
        return
    text = """
🏏 Welcome to the HCCL Rankings Bot

Use these commands:
/topbat - top batting rankings
/topbowl - top bowling rankings
/topall - top all-rounder rankings
/player Hasitha - player profile
/team DRAGONS - team-wise rankings
/movers - biggest rank climbers
/fallers - biggest rank fallers
/gains - biggest rating gains
/newentries - new ranking entries
/report - weekly ranking report
/benchmarks - current rating benchmarks
/weeks - saved ranking weeks
/help - command list

Tip: You can add a number, for example /topbat 5
""".strip()
    await safe_reply(update, text)


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await start(update, context)


async def topbat(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await guard(update):
        return
    await safe_reply(update, format_top("Batting", parse_limit(context.args, default_limit())))


async def topbowl(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await guard(update):
        return
    await safe_reply(update, format_top("Bowling", parse_limit(context.args, default_limit())))


async def topall(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await guard(update):
        return
    await safe_reply(update, format_top("All-Rounder", parse_limit(context.args, default_limit())))


async def player(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await guard(update):
        return
    query = " ".join(context.args).strip()
    if not query:
        await safe_reply(update, "Use like this: /player Hasitha")
        return

    snapshot, player_name, rows, suggestions = store().find_player(query)
    if not rows or not player_name:
        suggestion_text = ""
        if suggestions:
            suggestion_text = "\n\nPossible matches:\n" + "\n".join(f"- {name}" for name in suggestions)
        await safe_reply(update, f"Player not found: {query}{suggestion_text}")
        return

    lines = [snapshot_header(snapshot, f"👤 HCCL Player Profile: {player_name}")]
    for row in rows:
        lines.append(
            f"{row.get('category')}: {format_rank(row.get('rank'))}\n"
            f"Rating: {format_rating(row.get('rating'))}\n"
            f"Previous: {format_rating(row.get('previous_rating'))}\n"
            f"Change: {row.get('rating_change') or '—'}\n"
            f"Movement: {row.get('movement') or '—'}\n"
            f"Status: {row.get('status') or '—'}\n"
        )
    await safe_reply(update, "\n".join(lines))


async def team(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await guard(update):
        return
    if not context.args:
        await safe_reply(update, "Use like this: /team DRAGONS or /team DRAGONS batting")
        return

    team_query = context.args[0]
    category = parse_category(context.args[1], default="") if len(context.args) > 1 else None
    snapshot, team_name, rows, suggestions = store().team_rankings(team_query, category=category, per_category_limit=7)
    if not rows or not team_name:
        suggestion_text = ""
        if suggestions:
            suggestion_text = "\n\nAvailable teams / possible matches:\n" + "\n".join(f"- {name}" for name in suggestions)
        await safe_reply(update, f"Team not found: {team_query}{suggestion_text}")
        return

    title = f"🏟️ HCCL Team Rankings: {team_name}"
    if category:
        title += f" | {category}"
    lines = [snapshot_header(snapshot, title)]
    last_category = None
    for row in rows:
        row_category = row.get("category") or ""
        if row_category != last_category:
            lines.append(f"\n{row_category}")
            last_category = row_category
        lines.append(
            f"Team #{row.get('team_rank')} | Overall {format_rank(row.get('overall_rank'))}: "
            f"{row.get('player')} — {format_rating(row.get('rating'))} pts "
            f"{row.get('movement') or '—'} | {row.get('rating_change') or '—'}"
        )
    await safe_reply(update, "\n".join(lines))


def format_report_section(section: str, title: str) -> str:
    snapshot, rows = store().weekly_report(section=section, limit=25)
    if not rows:
        return f"No {title.lower()} found for the latest saved snapshot."
    lines = [snapshot_header(snapshot, title)]
    for row in rows:
        lines.append(
            f"{row.get('category')} #{row.get('current_rank')}: {row.get('player')} ({row.get('team')}) — "
            f"{format_rating(row.get('current_rating'))} pts | {row.get('movement') or '—'} | {row.get('rating_change') or '—'}"
        )
    return "\n".join(lines)


async def movers(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await guard(update):
        return
    await safe_reply(update, format_report_section("Top Climbers", "🚀 HCCL Top Climbers"))


async def fallers(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await guard(update):
        return
    await safe_reply(update, format_report_section("Top Fallers", "📉 HCCL Top Fallers"))


async def gains(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await guard(update):
        return
    await safe_reply(update, format_report_section("Top Rating Gains", "🔥 HCCL Top Rating Gains"))


async def newentries(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await guard(update):
        return
    await safe_reply(update, format_report_section("New Entries", "🆕 HCCL New Entries"))


async def report(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await guard(update):
        return
    snapshot, rows = store().weekly_report(limit=40)
    if not rows:
        await safe_reply(update, "No weekly report rows found for the latest saved snapshot.")
        return
    lines = [snapshot_header(snapshot, "🗞️ HCCL Weekly Ranking Report")]
    last_group = None
    for row in rows:
        group = f"{row.get('category')} | {row.get('report_section')}"
        if group != last_group:
            lines.append(f"\n{group}")
            last_group = group
        lines.append(
            f"#{row.get('current_rank')}: {row.get('player')} ({row.get('team')}) — "
            f"{format_rating(row.get('current_rating'))} pts | {row.get('movement') or '—'} | {row.get('rating_change') or '—'}"
        )
    await safe_reply(update, "\n".join(lines))


async def benchmarks(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await guard(update):
        return
    snapshot, rows = store().benchmarks()
    if not rows:
        await safe_reply(update, "No benchmarks found for the latest saved snapshot.")
        return
    lines = [snapshot_header(snapshot, "📊 HCCL Rating Benchmarks")]
    for row in rows:
        key = row.get("benchmark_key")
        label = BENCHMARK_LABELS.get(key, str(key))
        lines.append(f"{label}: {format_rating(row.get('benchmark_value'))}")
    await safe_reply(update, "\n".join(lines))


async def weeks(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await guard(update):
        return
    snapshots = store().list_snapshots(limit=10)
    if not snapshots:
        await safe_reply(update, "No saved ranking weeks found yet.")
        return
    lines = ["🗓️ Saved HCCL ranking weeks\n"]
    for i, snapshot in enumerate(snapshots, start=1):
        official = "Official only" if snapshot.official_only else "All players"
        lines.append(f"{i}. {snapshot.week_label} — {snapshot.snapshot_date} — {official}")
    await safe_reply(update, "\n".join(lines))


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.exception("Exception while handling update", exc_info=context.error)
    message = "Something went wrong while reading HCCL rankings."
    if isinstance(context.error, HCCLBotError):
        message = str(context.error)
    if isinstance(update, Update) and update.effective_message:
        await update.effective_message.reply_text(message)


async def post_init(application: Application) -> None:
    commands = [
        BotCommand("start", "Show welcome message"),
        BotCommand("topbat", "Top batting rankings"),
        BotCommand("topbowl", "Top bowling rankings"),
        BotCommand("topall", "Top all-rounder rankings"),
        BotCommand("player", "Player profile, e.g. /player Hasitha"),
        BotCommand("team", "Team rankings, e.g. /team DRAGONS"),
        BotCommand("movers", "Top rank climbers"),
        BotCommand("fallers", "Top rank fallers"),
        BotCommand("gains", "Top rating gains"),
        BotCommand("newentries", "New ranking entries"),
        BotCommand("report", "Weekly ranking report"),
        BotCommand("benchmarks", "Current rating benchmarks"),
        BotCommand("weeks", "Saved ranking weeks"),
        BotCommand("help", "Show command list"),
    ]
    await application.bot.set_my_commands(commands)


def build_app() -> Application:
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not token:
        raise RuntimeError("Missing TELEGRAM_BOT_TOKEN environment variable.")

    application = ApplicationBuilder().token(token).post_init(post_init).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("topbat", topbat))
    application.add_handler(CommandHandler("topbowl", topbowl))
    application.add_handler(CommandHandler("topall", topall))
    application.add_handler(CommandHandler("player", player))
    application.add_handler(CommandHandler("team", team))
    application.add_handler(CommandHandler("movers", movers))
    application.add_handler(CommandHandler("fallers", fallers))
    application.add_handler(CommandHandler("gains", gains))
    application.add_handler(CommandHandler("newentries", newentries))
    application.add_handler(CommandHandler("report", report))
    application.add_handler(CommandHandler("benchmarks", benchmarks))
    application.add_handler(CommandHandler("weeks", weeks))
    application.add_error_handler(error_handler)
    return application


if __name__ == "__main__":
    app = build_app()
    logger.info("Starting HCCL Telegram Bot with polling...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)
