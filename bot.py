"""Smart Telegram Bot with Video Frame OCR Cross-Verification."""
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
from video_processor import VideoProcessor, extract_urls

TOKEN = os.environ.get("BOT_TOKEN", "")
PORT = int(os.environ.get("PORT", 8443))
WEBHOOK_URL = os.environ.get("WEBHOOK_URL", "")

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

if not TOKEN:
    logger.error("❌ BOT_TOKEN is empty!")
    sys.exit(1)

if not WEBHOOK_URL or "your-app" in WEBHOOK_URL or "example" in WEBHOOK_URL:
    logger.error(f"❌ WEBHOOK_URL is still a placeholder: {WEBHOOK_URL}")
    sys.exit(1)

logger.info(f"✅ Config OK. WEBHOOK_URL: {WEBHOOK_URL}")

DATA_DIR = os.environ.get("DATA_DIR", "./data")
logger.info(f"Loading data from: {DATA_DIR}")
matcher = ChapterMatcher(DATA_DIR)
logger.info("✅ ChapterMatcher loaded")

firebase = FirebaseDB()
logger.info(f"Firebase enabled: {firebase.enabled}")

video_processor = VideoProcessor()
logger.info(f"VideoProcessor: cv2={video_processor.cv2_available}, ocr={video_processor.ocr_available}")

SUBJECT_DISPLAY_MAP = {
    "botny": "Botany",
    "zoology": "Zoology",
    "Physics": "Physics",
    "Physical Chemistry": "PhysicalChemistry",
    "Organic Chemistry": "OrganicChemistry",
    "Inorganic Chemistry": "InorganicChemistry",
}

WAITING_SUBJECT = 1
WAITING_CHAPTER = 2
WAITING_LECTURE = 3

user_last_messages = {}


class IsWrong(MessageFilter):
    def filter(self, message):
        return message.text is not None and message.text.strip().lower() == "wrong"

wrong_filter = IsWrong()


def get_subject_tag(raw: str) -> str:
    return SUBJECT_DISPLAY_MAP.get(raw, raw)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    welcome = (
        "👋 *Smart Lecture Parser Bot*\n\n"
        "📌 Send me lecture text — I learn from every message!\n\n"
        "🎥 *NEW: Video Frame OCR!*\n"
        "Send text + video link together\n"
        "I will read video frames (1-6 sec) via OCR\n"
        "and cross-verify with your text!\n\n"
        "🤖 Reply Format:\n"
        "• @Subject\n"
        "• @Chapter\n"
        "• @Lec XX\n\n"
        "⚠️ If *WRONG*, type: *wrong* → I learn!"
    )
    await update.message.reply_text(welcome, parse_mode="Markdown")


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    help_text = (
        "*Commands:* /start /help /stats\n\n"
        "*Video Frame OCR:*\n"
        "Send text + video link\n"
        "Bot reads video frames 1-6 sec\n"
        "Extracts Hindi text overlay via OCR\n"
        "Cross-verifies with your text!\n\n"
        "*Correction:* Type *wrong* → tell correct answer"
    )
    await update.message.reply_text(help_text, parse_mode="Markdown")


async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if firebase.enabled:
        top_subjects = firebase.get_user_top_subjects(user_id)
        learned = firebase.get_learned_lecture_pattern(user_id)
        text = (
            "📊 *Your Stats*\n\n"
            f"🎯 Top: {', '.join(top_subjects) if top_subjects else 'None yet'}\n"
        )
        if learned:
            text += f"📚 Pattern: {learned.get('most_common_lecture', 'N/A')}\n"
        await update.message.reply_text(text, parse_mode="Markdown")
    else:
        await update.message.reply_text("📊 Firebase not connected.")


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    user_id = update.effective_user.id

    if not text or len(text.strip()) < 5:
        await update.message.reply_text("⚠️ Please send a valid lecture text.")
        return

    if text.strip().lower() == "wrong":
        await update.message.reply_text(
            "❓ What is the *correct Subject*?\n"
            "(Botany, Physics, OrganicChemistry, etc.)"
        )
        return WAITING_SUBJECT

    urls = extract_urls(text)
    video_url = None
    for url in urls:
        if video_processor.is_video_link(url):
            video_url = url
            break

    text_without_urls = text
    for url in urls:
        text_without_urls = text_without_urls.replace(url, '')
    text_without_urls = re.sub(r'\s+', ' ', text_without_urls).strip()

    correction = None
    if firebase.enabled:
        correction = firebase.find_correction(user_id, text)

    if correction:
        reply_lines = []
        reply_lines.append(f"@{get_subject_tag(correction['subject'])}")
        reply_lines.append(f"@{correction['chapter']}")
        if correction.get("lecture"):
            reply_lines.append(f"@Lec {correction['lecture']}")
        reply_lines.append("\n✅ *From your previous correction*")
        await update.message.reply_text("\n".join(reply_lines), parse_mode="Markdown")

        if firebase.enabled:
            parsed = parse_lecture_text(text)
            firebase.save_interaction(user_id, text, parsed, correction)
        return

    history_lectures = []
    user_history_subjects = []
    if firebase.enabled:
        learned = firebase.get_learned_lecture_pattern(user_id)
        history_lectures = learned.get("all_lectures", [])
        user_history_subjects = firebase.get_user_top_subjects(user_id)

    parsed = parse_lecture_text(text_without_urls, history_lectures=history_lectures)
    search_text = parsed.get("clean_title") or parsed.get("raw_title") or text_without_urls
    core_text = parsed.get("core_title")

    text_match = matcher.find_best_match(
        search_text, core_text,
        user_history_subjects=user_history_subjects,
    )

    if firebase.enabled:
        text_match = firebase.boost_confidence_with_history(user_id, text_match)

    if video_url:
        await update.message.reply_text(
            "🎥 *Video detected!*\n"
            "📸 Extracting frames 1-6 sec...\n"
            "🔍 Running Hindi OCR...",
            parse_mode="Markdown"
        )

        video_result = video_processor.extract_text_from_video(video_url, start_sec=1, end_sec=6)

        if video_result['text']:
            await update.message.reply_text(
                f"📝 *Video OCR found:*\n`{video_result['text'][:200]}`",
                parse_mode="Markdown"
            )

            cross_result = video_processor.cross_verify_with_video(
                {
                    'subject': text_match['subject'],
                    'chapter': text_match['chapter'],
                    'confidence': text_match['confidence'],
                    'lecture': parsed.get('lecture_number')
                },
                video_result['text'],
                matcher
            )

            reply_lines = []
            reply_lines.append(f"@{get_subject_tag(cross_result['subject'])}")
            reply_lines.append(f"@{cross_result['chapter']}")
            if cross_result.get('lecture'):
                reply_lines.append(f"@Lec {cross_result['lecture']}")

            if cross_result['verified']:
                reply_lines.append(f"\n✅ *CROSS-VERIFIED!* Confidence: {cross_result['confidence']}%")
                reply_lines.append("📹 Video OCR + Text both match!")
            else:
                reply_lines.append(f"\n⚠️ *Text result only* (confidence: {cross_result['confidence']}%)")
                if cross_result.get('warning'):
                    reply_lines.append(cross_result['warning'])

            reply_lines.append("\n⚠️ If *WRONG*, type: *wrong*")
            await update.message.reply_text("\n".join(reply_lines), parse_mode="Markdown")

            final_match = {
                'subject': cross_result['subject'],
                'chapter': cross_result['chapter'],
                'confidence': cross_result['confidence'],
            }
            user_last_messages[user_id] = {
                "raw_text": text,
                "parsed": parsed,
                "match": final_match,
            }

            if firebase.enabled:
                firebase.save_interaction(user_id, text, parsed, final_match)
            return
        else:
            error_msg = video_result.get('error', 'Unknown error')
            await update.message.reply_text(
                f"⚠️ *Video found but OCR failed:* {error_msg}\n"
                "Using text analysis only...",
                parse_mode="Markdown"
            )

    reply_lines = []
    reply_lines.append(f"@{get_subject_tag(text_match['subject'])}")
    reply_lines.append(f"@{text_match['chapter']}")

    if parsed.get("lecture_number"):
        reply_lines.append(f"@Lec {parsed['lecture_number']}")

    reply_lines.append("\n⚠️ If this is *WRONG*, type: *wrong*")
    await update.message.reply_text("\n".join(reply_lines), parse_mode="Markdown")

    user_last_messages[user_id] = {
        "raw_text": text,
        "parsed": parsed,
        "match": text_match,
    }

    if firebase.enabled:
        firebase.save_interaction(user_id, text, parsed, text_match)
        logger.info(f"[Learned] User {user_id} -> {text_match['subject']}/{text_match['chapter']}")


async def correction_subject(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    subject = update.message.text.strip()
    context.user_data["correction_subject"] = subject

    await update.message.reply_text(
        "✅ Subject noted!\n\n"
        "❓ Now what is the *correct Chapter*?\n"
        "(e.g., कोशिका : जीवन की इकाई, समतल में गति)"
    )
    return WAITING_CHAPTER


async def correction_chapter(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    chapter = update.message.text.strip()
    context.user_data["correction_chapter"] = chapter

    await update.message.reply_text(
        "✅ Chapter noted!\n\n"
        "❓ What is the *Lecture number*?\n"
        "(Type number, or *skip*)"
    )
    return WAITING_LECTURE


async def correction_lecture(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    lecture_input = update.message.text.strip()

    lecture = None
    if lecture_input.lower() != "skip":
        num_match = re.search(r'\d+', lecture_input)
        if num_match
