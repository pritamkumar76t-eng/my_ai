"""Telegram Bot for Lecture Index Parser & Subject/Chapter Detection.
Deploy on Render using Webhook.
Reply Format Rules:
  1. @SubjectTag
  2. @ChapterTag
  3. @Lec XX (if lecture number found)
"""
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

# ─── Configuration ───────────────────────────────────────────
TOKEN = os.environ.get("BOT_TOKEN", "YOUR_BOT_TOKEN_HERE")
PORT = int(os.environ.get("PORT", 8443))
WEBHOOK_URL = os.environ.get("WEBHOOK_URL", "")

# ─── Logging ───────────────────────────────────────────────────
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# ─── Initialize matcher ──────────────────────────────────────
DATA_DIR = os.environ.get("DATA_DIR", "./data")
matcher = ChapterMatcher(DATA_DIR)

# ─── Subject Name Cleaner ────────────────────────────────────
SUBJECT_DISPLAY_MAP = {
    "botny": "Botany",
    "zoology": "Zoology",
    "Physics": "Physics",
    "Physical Chemistry": "PhysicalChemistry",
    "Organic Chemistry": "OrganicChemistry",
    "Inorganic Chemistry": "InorganicChemistry",
}


def get_subject_tag(raw_subject: str) -> str:
    """Convert internal subject name to display tag."""
    return SUBJECT_DISPLAY_MAP.get(raw_subject, raw_subject)


# ─── Handlers ──────────────────────────────────────────────────
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
        "*Example Input:*\n"
        "```\n"
        "➭ Index » 004\n"
        "➭ Title » कोशिका जीवन की इकाई 01  कोशिका सिद्धांत\n"
        "➭ Quality » 854x480\n"
        "```\n\n"
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

    # Parse the text
    parsed = parse_lecture_text(text)

    # Match subject/chapter
    search_text = parsed.get("clean_title") or parsed.get("raw_title") or text
    core_text = parsed.get("core_title")
    match_result = matcher.find_best_match(search_text, core_text)

    # Build reply following the rules
    reply_lines = []

    # Rule 1: Subject Tag
    subject_tag = get_subject_tag(match_result["subject"])
    reply_lines.append(f"@{subject_tag}")

    # Rule 2: Chapter Tag
    chapter_name = match_result["chapter"]
    reply_lines.append(f"@{chapter_name}")

    # Rule 3: Lecture Number (if found in text)
    if parsed.get("lecture_number"):
        reply_lines.append(f"@Lec {parsed['lecture_number']}")

    reply_text = "\n".join(reply_lines)

    await update.message.reply_text(reply_text)


# ─── Error Handler ─────────────────────────────────────────────
async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.error(f"Update {update} caused error: {context.error}")
    if update and update.message:
        await update.message.reply_text("❌ Error occurred. Please try again.")


# ─── Main / Webhook Setup ──────────────────────────────────────
async def main():
    application = Application.builder().token(TOKEN).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    application.add_error_handler(error_handler)

    if WEBHOOK_URL:
        await application.initialize()
        await application.start()

        webhook_path = f"/webhook/{TOKEN}"
        await application.bot.set_webhook(url=f"{WEBHOOK_URL}{webhook_path}")

        app = web.Application()

        async def webhook_handler(request):
            data = await request.json()
            # ✅ NEW (correct way)
update = Update.de_json(data, application.bot)
await application.process_update(update)
            return web.Response()

        app.router.add_post(webhook_path, webhook_handler)

        logger.info(f"Starting webhook on port {PORT}")
        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, "0.0.0.0", PORT)
        await site.start()

        while True:
            await asyncio.sleep(3600)
    else:
        logger.info("Starting polling mode...")
        await application.run_polling()


if __name__ == "__main__":
    asyncio.run(main())
