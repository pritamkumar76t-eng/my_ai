"""Smart Telegram Bot with Firebase Learning & Correction System."""
import os
import sys
import logging
import asyncio
import re
from aiohttp import web

from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ConversationHandler,
    ContextTypes,
    filters,
)
from telegram.ext.filters import MessageFilter

# ─── Debug: Print env vars at startup ───
print("=" * 60, file=sys.stderr)
print("BOT STARTING...", file=sys.stderr)
print(f"PORT: {os.environ.get('PORT', 'NOT SET')}", file=sys.stderr)
print(f"DATA_DIR: {os.environ.get('DATA_DIR', 'NOT SET')}", file=sys.stderr)
print(f"WEBHOOK_URL: {'SET' if os.environ.get('WEBHOOK_URL') else 'NOT SET'}", file=sys.stderr)
print(f"BOT_TOKEN: {'SET' if os.environ.get('BOT_TOKEN') else 'NOT SET'}", file=sys.stderr)
print(f"FIREBASE_CREDENTIALS: {'SET' if os.environ.get('FIREBASE_CREDENTIALS') else 'NOT SET'}", file=sys.stderr)
print("=" * 60, file=sys.stderr)

from parser import parse_lecture_text
from chapter_matcher import ChapterMatcher
from firebase_db import FirebaseDB

# ─── Config ──────────────────────────────────────────────────
TOKEN = os.environ.get("BOT_TOKEN", "")
PORT = int(os.environ.get("PORT", 8443))
WEBHOOK_URL = os.environ.get("WEBHOOK_URL", "")

# ─── Logging ───────────────────────────────────────────────────
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# ─── Validate Config ─────────────────────────────────────────
if not TOKEN:
    logger.error("❌ BOT_TOKEN is empty!")
    sys.exit(1)

if not WEBHOOK_URL or "your-app" in WEBHOOK_URL or "example" in WEBHOOK_URL:
    logger.error(f"❌ WEBHOOK_URL is still a placeholder: {WEBHOOK_URL}")
    sys.exit(1)

logger.info(f"✅ Config OK. WEBHOOK_URL: {WEBHOOK_URL}")

# ─── Init ──────────────────────────────────────────────────────
DATA_DIR = os.environ.get("DATA_DIR", "./data")
logger.info(f"Loading data from: {DATA_DIR}")
matcher = ChapterMatcher(DATA_DIR)
logger.info("✅ ChapterMatcher loaded")

firebase = FirebaseDB()
logger.info(f"Firebase enabled: {firebase.enabled}")

SUBJECT_DISPLAY_MAP = {
    "botny": "Botany",
    "zoology": "Zoology",
    "Physics": "Physics",
    "Physical Chemistry": "PhysicalChemistry",
    "Organic Chemistry": "OrganicChemistry",
    "Inorganic Chemistry": "InorganicChemistry",
}

# Conversation States
WAITING_SUBJECT = 1
WAITING_CHAPTER = 2
WAITING_LECTURE = 3

# Store last message for correction context
user_last_messages = {}

# ─── Custom Filter for "wrong" (case-insensitive) ────────────
class IsWrong(MessageFilter):
    def filter(self, message):
        return message.text is not None and message.text.strip().lower() == "wrong"

wrong_filter = IsWrong()


def get_subject_tag(raw: str) -> str:
    return SUBJECT_DISPLAY_MAP.get(raw, raw)


# ─── Commands ──────────────────────────────────────────────────
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    welcome = (
        "👋 *Welcome to Smart Lecture Parser Bot!*\n\n"
        "📌 Send me ANY lecture text — I learn from every message!\n\n"
        "🤖 Reply Format:\n"
        "• @Subject\n"
        "• @Chapter\n"
        "• @Lec XX\n\n"
        "⚠️ If I am *WRONG*, just type: *wrong*\n"
        "I will ask what is correct and learn from it!\n\n"
        "📂 Supported: Physics, Chemistry, Biology, Botany, Zoology"
    )
    await update.message.reply_text(welcome, parse_mode="Markdown")


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    help_text = (
        "*Commands:*\n"
        "/start - Start the bot\n"
        "/help - Show help\n"
        "/stats - Show your learning stats\n\n"
        "*How to correct me:*\n"
        "1️⃣ If my answer is wrong, type: *wrong*\n"
        "2️⃣ I will ask: 'What is the correct Subject?'\n"
        "3️⃣ Then: 'What is the correct Chapter?'\n"
        "4️⃣ Then: 'What is the Lecture number?' (or type 'skip')\n"
        "5️⃣ I will remember and never make that mistake again!\n\n"
        "*Reply Rules:*\n"
        "• @SubjectTag\n"
        "• @ChapterTag\n"
        "• @Lec XX (auto-detected)"
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


# ─── Main Message Handler ─────────────────────────────────────
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    user_id = update.effective_user.id

    if not text or len(text.strip()) < 5:
        await update.message.reply_text("⚠️ Please send a valid lecture text.")
        return

    # Check if user said "wrong"
    if text.strip().lower() == "wrong":
        await update.message.reply_text(
            "❓ I am sorry! What is the *correct Subject*?\n"
            "(e.g., Botany, Physics, OrganicChemistry, etc.)"
        )
        return WAITING_SUBJECT

    # Check Firebase Corrections FIRST
    correction = None
    if firebase.enabled:
        correction = firebase.find_correction(user_id, text)

    if correction:
        reply_lines = []
        reply_lines.append(f"@{get_subject_tag(correction['subject'])}")
        reply_lines.append(f"@{correction['chapter']}")
        if correction.get("lecture"):
            reply_lines.append(f"@Lec {correction['lecture']}")
        reply_lines.append("\n✅ *Answer from your previous correction*")
        await update.message.reply_text("\n".join(reply_lines), parse_mode="Markdown")

        if firebase.enabled:
            parsed = parse_lecture_text(text)
            firebase.save_interaction(user_id, text, parsed, correction)
        return

    # Normal Flow
    history_lectures = []
    user_history_subjects = []
    if firebase.enabled:
        learned = firebase.get_learned_lecture_pattern(user_id)
        history_lectures = learned.get("all_lectures", [])
        user_history_subjects = firebase.get_user_top_subjects(user_id)

    parsed = parse_lecture_text(text, history_lectures=history_lectures)
    search_text = parsed.get("clean_title") or parsed.get("raw_title") or text
    core_text = parsed.get("core_title")

    match_result = matcher.find_best_match(
        search_text, core_text,
        user_history_subjects=user_history_subjects,
    )

    if firebase.enabled:
        match_result = firebase.boost_confidence_with_history(user_id, match_result)

    # Store for potential correction
    user_last_messages[user_id] = {
        "raw_text": text,
        "parsed": parsed,
        "match": match_result,
    }

    reply_lines = []
    reply_lines.append(f"@{get_subject_tag(match_result['subject'])}")
    reply_lines.append(f"@{match_result['chapter']}")

    if parsed.get("lecture_number"):
        reply_lines.append(f"@Lec {parsed['lecture_number']}")

    reply_lines.append("\n⚠️ If this is *WRONG*, type: *wrong*")
    await update.message.reply_text("\n".join(reply_lines), parse_mode="Markdown")

    if firebase.enabled:
        firebase.save_interaction(user_id, text, parsed, match_result)
        logger.info(f"[Learned] User {user_id} -> {match_result['subject']}/{match_result['chapter']}")


# ─── Correction Conversation ─────────────────────────────────
async def correction_subject(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    subject = update.message.text.strip()
    context.user_data["correction_subject"] = subject

    await update.message.reply_text(
        "✅ Subject noted!\n\n"
        "❓ Now what is the *correct Chapter*?\n"
        "(e.g., कोशिका : जीवन की इकाई, समतल में गति, etc.)"
    )
    return WAITING_CHAPTER


async def correction_chapter(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    chapter = update.message.text.strip()
    context.user_data["correction_chapter"] = chapter

    await update.message.reply_text(
        "✅ Chapter noted!\n\n"
        "❓ What is the *Lecture number*?\n"
        "(Type the number, or type *skip* if not sure)"
    )
    return WAITING_LECTURE


async def correction_lecture(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    lecture_input = update.message.text.strip()

    lecture = None
    if lecture_input.lower() != "skip":
        num_match = re.search(r'\d+', lecture_input)
        if num_match:
            lecture = num_match.group().zfill(2)

    subject = context.user_data.get("correction_subject", "Unknown")
    chapter = context.user_data.get("correction_chapter", "Unknown")
    last_msg = user_last_messages.get(user_id, {})
    raw_text = last_msg.get("raw_text", "")

    if firebase.enabled and raw_text:
        firebase.save_correction(user_id, raw_text, subject, chapter, lecture)

    reply_lines = [
        "🧠 *Thank you! I have learned the correct answer:*",
        f"@{subject}",
        f"@{chapter}",
    ]
    if lecture:
        reply_lines.append(f"@Lec {lecture}")
    reply_lines.append("\n✅ I will remember this for next time!")

    await update.message.reply_text("\n".join(reply_lines), parse_mode="Markdown")

    context.user_data.clear()
    if user_id in user_last_messages:
        del user_last_messages[user_id]

    return ConversationHandler.END


async def cancel_correction(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("❌ Correction cancelled.")
    context.user_data.clear()
    return ConversationHandler.END


async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.error(f"Update {update} caused error: {context.error}")
    if update and update.message:
        await update.message.reply_text("❌ Error occurred. Please try again.")


# ─── Main ──────────────────────────────────────────────────────
async def main():
    logger.info("Starting bot initialization...")

    application = Application.builder().token(TOKEN).build()
    logger.info("✅ Telegram Application created")

    correction_conv = ConversationHandler(
        entry_points=[MessageHandler(wrong_filter, handle_message)],
        states={
            WAITING_SUBJECT: [MessageHandler(filters.TEXT & ~filters.COMMAND, correction_subject)],
            WAITING_CHAPTER: [MessageHandler(filters.TEXT & ~filters.COMMAND, correction_chapter)],
            WAITING_LECTURE: [MessageHandler(filters.TEXT & ~filters.COMMAND, correction_lecture)],
        },
        fallbacks=[CommandHandler("cancel", cancel_correction)],
    )

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("stats", stats_command))
    application.add_handler(correction_conv)
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    application.add_error_handler(error_handler)

    logger.info("✅ Handlers registered")

    await application.initialize()
    await application.start()
    logger.info("✅ Application initialized and started")

    webhook_path = f"/webhook/{TOKEN}"
    full_url = f"{WEBHOOK_URL}{webhook_path}"
    await application.bot.set_webhook(url=full_url)
    logger.info(f"✅ Webhook set: {full_url}")

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
    logger.info(f"✅ Server running on port {PORT}")

    while True:
        await asyncio.sleep(3600)


if __name__ == "__main__":
    asyncio.run(main())
