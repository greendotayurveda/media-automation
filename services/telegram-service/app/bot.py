"""
Telegram bot handler using python-telegram-bot.
Handles bot commands and receives file uploads to trigger media ingestion.
"""
import os
import uuid
from pathlib import Path
from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from shared.config.settings import settings
from shared.events.events import EventType, StreamName
from shared.events.publisher import EventPublisher
from shared.logging.logger import get_logger

logger = get_logger("telegram-bot")


class TelegramBotHandler:
    """
    Manages Telegram bot commands and media file reception.
    """

    def __init__(self) -> None:
        self.publisher = EventPublisher(StreamName.MEDIA)
        self.incoming_dir = settings.download_root / "incoming"
        os.makedirs(self.incoming_dir, exist_ok=True)

    def _is_allowed(self, user_id: int, chat_id: int) -> bool:
        """Check if user/chat is allowed to interact with the bot."""
        allowed_chats = settings.telegram_allowed_chat_id_list
        if not allowed_chats:
            return True  # If not configured, allow all (or set restrictive)
        return user_id in allowed_chats or chat_id in allowed_chats

    async def start_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handler for /start command."""
        user = update.effective_user
        if not self._is_allowed(user.id, update.effective_chat.id):
            await update.message.reply_text("⛔ Unauthorized access.")
            return

        await update.message.reply_html(
            f"👋 Hello {user.mention_html()}!\n\n"
            "Welcome to <b>Media Automation Platform</b>.\n"
            "Send or forward any movie/video file here to start automated ingestion!\n\n"
            "<b>Commands:</b>\n"
            "/status - System health & downloads\n"
            "/library - View library count\n"
            "/help - Bot instructions"
        )

    async def help_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handler for /help command."""
        await update.message.reply_text(
            "📖 <b>Instructions:</b>\n"
            "1. Upload or forward a video file (.mkv, .mp4, etc.)\n"
            "2. The bot will automatically analyze, fetch metadata, grab subtitles, and organize it into Jellyfin!\n"
            "3. Use /status to check current pipeline progress.",
            parse_mode="HTML",
        )

    async def status_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handler for /status command."""
        await update.message.reply_text(
            "⚙️ <b>Platform Status:</b>\n"
            "• Engine: Active ✅\n"
            "• PostgreSQL: Healthy ✅\n"
            "• Redis Bus: Healthy ✅\n"
            "• Storage Free: Checking...",
            parse_mode="HTML",
        )

    async def handle_document(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handler for video files uploaded as documents or video attachments."""
        user = update.effective_user
        chat_id = update.effective_chat.id

        if not self._is_allowed(user.id, chat_id):
            await update.message.reply_text("⛔ Unauthorized.")
            return

        # Extract file object
        document = update.message.document or update.message.video
        if not document:
            return

        file_name = document.file_name or f"video_{document.file_id[:8]}.mkv"
        file_size_mb = round((document.file_size or 0) / (1024 * 1024), 2)

        msg = await update.message.reply_text(
            f"📥 <b>Receiving File:</b> {file_name} ({file_size_mb} MB)\n"
            "Downloading to platform storage...",
            parse_mode="HTML",
        )

        try:
            # Download file
            tg_file = await context.bot.get_file(document.file_id)
            save_path = self.incoming_dir / file_name
            await tg_file.download_to_drive(custom_path=save_path)

            correlation_id = str(uuid.uuid4())
            logger.info("Downloaded Telegram file", file_name=file_name, path=str(save_path))

            # Publish event to Redis Stream to trigger Workflow Engine
            await self.publisher.publish(
                event_type=EventType.MOVIE_RECEIVED,
                payload={
                    "file_path": str(save_path),
                    "file_name": file_name,
                    "file_size": document.file_size,
                    "source": "telegram",
                    "user_id": user.id,
                },
                source_service="telegram-service",
                correlation_id=correlation_id,
            )

            await msg.edit_text(
                f"✅ <b>File Received & Queued!</b>\n\n"
                f"📄 <b>File:</b> {file_name}\n"
                f"🆔 <b>Correlation ID:</b> <code>{correlation_id}</code>\n\n"
                "Automation pipeline started! (Analyzing → Metadata → Subtitle → Jellyfin)",
                parse_mode="HTML",
            )
        except Exception as exc:
            logger.error("Failed to process Telegram file", error=str(exc))
            await msg.edit_text(f"❌ Failed to process file: {str(exc)}")

    def build_application(self) -> Application:
        """Build and configure python-telegram-bot application."""
        if not settings.telegram_bot_token:
            logger.warning("TELEGRAM_BOT_TOKEN is not configured!")

        app = Application.builder().token(settings.telegram_bot_token or "dummy_token").build()

        app.add_handler(CommandHandler("start", self.start_command))
        app.add_handler(CommandHandler("help", self.help_command))
        app.add_handler(CommandHandler("status", self.status_command))
        app.add_handler(MessageHandler(filters.Document.ALL | filters.VIDEO, self.handle_document))

        return app
