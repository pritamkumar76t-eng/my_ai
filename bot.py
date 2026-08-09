"""Telegram Bot for Lecture Index Parser & Subject/Chapter Detection."""
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

# Configuration
TOKEN = os.environ.get("BOT_TOKEN", "")
PORT = int(os.environ.get("PORT", 8443))
WEBHOOK_URL = os.environ.get("WEBHOOK_URL", "")

# Logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# Initialize matcher
DATA_DIR = os.environ.get("DATA_DIR", "./data")
matcher = ChapterMatcher(DATA_DIR)

SUBJECT_DISPLAY_MAP = {
    "botny": "Botany",
    "zoology": "Zoology",
    "Physics": "Physics",
    "Physical Chemistry": "PhysicalChemistry",
    "Organic Chemistry": "OrganicChemistry",
    "Inorganic Chemistry": "InorganicChemistry",
}


def get_subject_tag(raw_subject: str) -> str:
    return SUBJECT_DISPLAY_MAP.get(raw_subject, raw_subject)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    welcome = (
        "👋 *Welcome to Lecture Parser Bot!*\n\n"
        "📌 Send me any lecture text like:\n"
        "```\n"
        "➭ Index » 004\n"
        "➭ Title » कोशिका जीवन की इकाई 01  कोशिका सिद्धांत  NO DPP 854x480.mkv\n"
        "➭ Quality » 854x480\n"
        "```\n\n"
        "🤖 Reply Format:\n"
        "• @Subject\n"
        "• @Chapter\n"
        "• @Lec XX (if found)\n\n"
        "📂 Supported: Physics, Chemistry, Biology, Botany, Zoology"
    )
    await update.message.reply_text(welcome, parse_mode="Markdown")


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    help_text = (
        "*Commands:*\n"
        "/start - Start the bot\n"
        "/help - Show help\n\n"
        "*Reply Rules:*\n"
        "1️⃣ @SubjectTag\n"
        "2️⃣ @ChapterTag\n"
        "3️⃣ @Lec XX (if lecture number in title)\n\n"
        "*Example Output:*\n"
        "```\n"
        "@Botany\n"
        "@कोशिका : जीवन की इकाई\n"
        "@Lec 01\n"
        "```"
    )
    await update.message.reply_text(help_text, parse_mode="Markdown")


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text

    if not text or len(text.strip()) < 5:
        await update.message.reply_text("⚠️ Please send a valid lecture text.")
        return

    parsed = parse_lecture_text(text)
    search_text = parsed.get("clean_title") or parsed.get("raw_title") or text
    core_text = parsed.get("core_title")
    match_result = matcher.find_best_match(search_text, core_text)

    reply_lines = []
    subject_tag = get_subject_tag(match_result["subject"])
    reply_lines.append(f"@{subject_tag}")
    reply_lines.append(f"@{match_result['chapter']}")

    if parsed.get("lecture_number"):
        reply_lines.append(f"@Lec {parsed['lecture_number']}")

    await update.message.reply_text("\n".join(reply_lines))


async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.error(f"Update {update} caused error: {context.error}")
    if update and update.message:
        await update.message.reply_text("❌ Error occurred. Please try again.")


async def main():
    """Main async function for webhook server."""
    if not TOKEN:
        logger.error("BOT_TOKEN not set!")
        return

    if not WEBHOOK_URL or "your-app" in WEBHOOK_URL:
        logger.error("WEBHOOK_URL not set correctly! Set it to your actual Render URL.")
        return

    application = Application.builder().token(TOKEN).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    application.add_error_handler(error_handler)

    await application.initialize()
    await application.start()

    webhook_path = f"/webhook/{TOKEN}"
    full_webhook_url = f"{WEBHOOK_URL}{webhook_path}"
    await application.bot.set_webhook(url=full_webhook_url)
    logger.info(f"Webhook set to: {full_webhook_url}")

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
