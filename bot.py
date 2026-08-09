"""Smart Telegram Bot with Firebase Learning."""
import os
import logging
import asyncio
from aiohttp import web

from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

from parser import parse_lecture_text
from chapter_matcher import ChapterMatcher
from firebase_db import FirebaseDB

# Config
TOKEN = os.environ.get("BOT_TOKEN", "")
PORT = int(os.environ.get("PORT", 8443))
WEBHOOK_URL = os.environ.get("WEBHOOK_URL", "")

# Logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# Init
DATA_DIR = os.environ.get("DATA_DIR", "./data")
matcher = ChapterMatcher(DATA_DIR)
firebase = FirebaseDB()

SUBJECT_DISPLAY_MAP = {
    "botny": "Botany",
    "zoology": "Zoology",
    "Physics": "Physics",
    "Physical Chemistry": "PhysicalChemistry",
    "Organic Chemistry": "OrganicChemistry",
    "Inorganic Chemistry": "InorganicChemistry",
}


def get_subject_tag(raw: str) -> str:
    return SUBJECT_DISPLAY_MAP.get(raw, raw)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    welcome = (
        "👋 *Welcome to Smart Lecture Parser Bot!*\n\n"
        "📌 Send me ANY lecture text — I learn from every message!\n\n"
        "🤖 Reply Format:\n"
        "• @Subject\n"
        "• @Chapter\n"
        "• @Lec XX\n\n"
        "🧠 I remember your patterns and get smarter over time!"
    )
    await update.message.reply_text(welcome, parse_mode="Markdown")


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    help_text = (
        "*Commands:*\n"
        "/start - Start the bot\n"
        "/help - Show help\n"
        "/stats - Show your learning stats\n\n"
        "*Features:*\n"
        "• Any digit count for lecture numbers\n"
        "• Learns your text format\n"
        "• Hindi/English chapter matching\n"
        "• Confidence improves with use"
    )
    await update.message.reply_text(help_text, parse_mode="Markdown")


async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if firebase.enabled:
        top_subjects = firebase.get_user_top_subjects(user_id)
        learned = firebase.get_learned_lecture_pattern(user_id)
        text = (
            "📊 *Your Learning Stats*\n\n"
            f"🎯 Top Subjects: {', '.join(top_subjects) if top_subjects else 'None yet'}\n"
        )
        if learned:
            text += f"📚 Lecture Pattern: {learned.get('most_common_lecture', 'N/A')}\n"
            text += f"🔥 Frequency: {learned.get('frequency', 0)}\n"
        await update.message.reply_text(text, parse_mode="Markdown")
    else:
        await update.message.reply_text("📊 Firebase not connected. Stats unavailable.")


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    user_id = update.effective_user.id

    if not text or len(text.strip()) < 5:
        await update.message.reply_text("⚠️ Please send a valid lecture text.")
        return

    # Learn from history
    history_lectures = []
    user_history_subjects = []
    if firebase.enabled:
        learned = firebase.get_learned_lecture_pattern(user_id)
        history_lectures = learned.get("all_lectures", [])
        user_history_subjects = firebase.get_user_top_subjects(user_id)

    # Parse text
    parsed = parse_lecture_text(text, history_lectures=history_lectures)

    # Match subject/chapter
    search_text = parsed.get("clean_title") or parsed.get("raw_title") or text
    core_text = parsed.get("core_title")

    match_result = matcher.find_best_match(
        search_text,
        core_text,
        user_history_subjects=user_history_subjects,
    )

    # Boost confidence with Firebase
    if firebase.enabled:
        match_result = firebase.boost_confidence_with_history(user_id, match_result)

    # Build reply
    reply_lines = []
    reply_lines.append(f"@{get_subject_tag(match_result['subject'])}")
    reply_lines.append(f"@{match_result['chapter']}")

    if parsed.get("lecture_number"):
        reply_lines.append(f"@Lec {parsed['lecture_number']}")

    await update.message.reply_text("\n".join(reply_lines))

    # Save to Firebase for learning
    if firebase.enabled:
        firebase.save_interaction(user_id, text, parsed, match_result)
        logger.info(f"[Learned] User {user_id} -> {match_result['subject']}/{match_result['chapter']}")


async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.error(f"Update {update} caused error: {context.error}")
    if update and update.message:
        await update.message.reply_text("❌ Error occurred. Please try again.")


async def main():
    if not TOKEN:
        logger.error("BOT_TOKEN not set!")
        return

    if not WEBHOOK_URL or "your-app" in WEBHOOK_URL:
        logger.error("WEBHOOK_URL not set correctly!")
        return

    application = Application.builder().token(TOKEN).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("stats", stats_command))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    application.add_error_handler(error_handler)

    await application.initialize()
    await application.start()

    webhook_path = f"/webhook/{TOKEN}"
    full_url = f"{WEBHOOK_URL}{webhook_path}"
    await application.bot.set_webhook(url=full_url)
    logger.info(f"Webhook set: {full_url}")

    aio_app = web.Application()

    async def webhook_handler(request):
        data = await request.json()
        update = Update.de_json(data, application.bot)
        await application.process_update(update)
        return web.Response()

    aio_app.router.add_post(webhook_path, webhook_handler)

    runner = web.AppRunner(aio_app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", PORT)
    await site.start()
    logger.info(f"Server running on port {PORT}")

    while True:
        await asyncio.sleep(3600)


if __name__ == "__main__":
    asyncio.run(main())
