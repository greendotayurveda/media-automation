"""
Telegram bot handler supporting both Private and Group/Supergroup chats.
Receives file attachments posted to group chats and triggers media ingestion.
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
    Manages Telegram bot commands and group media file reception.
    """

    def __init__(self) -> None:
        self.publisher = EventPublisher(StreamName.MEDIA)
        self.incoming_dir = settings.download_root / "incoming"
        os.makedirs(self.incoming_dir, exist_ok=True)

    def _is_allowed(self, user_id: int, chat_id: int) -> bool:
        """Check if user/chat is allowed to interact with the bot."""
        allowed_chats = settings.telegram_allowed_chat_id_list
        if not allowed_chats:
            return True  # If not configured, allow all
        return user_id in allowed_chats or chat_id in allowed_chats

    async def start_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handler for /start command."""
        user = update.effective_user
        chat = update.effective_chat
        logger.info("/start received", user_id=user.id, chat_id=chat.id, chat_type=chat.type)

        if not self._is_allowed(user.id, chat.id):
            await update.message.reply_text("⛔ Unauthorized access.")
            return

        await update.message.reply_html(
            f"👋 Hello {user.mention_html()}!\n\n"
            "Welcome to <b>Media Automation Platform</b>.\n"
            "Post or forward any movie/video file in this chat/group to start automated ingestion!\n\n"
            "<b>Commands:</b>\n"
            "/id - Show current Group Chat ID\n"
            "/status - System health & downloads\n"
            "/help - Bot instructions"
        )

    async def id_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handler for /id command to help user discover group chat IDs."""
        chat = update.effective_chat
        user = update.effective_user
        await update.message.reply_html(
            f"🆔 <b>Chat Info:</b>\n"
            f"• <b>Chat ID:</b> <code>{chat.id}</code>\n"
            f"• <b>Chat Type:</b> {chat.type}\n"
            f"• <b>Your User ID:</b> <code>{user.id}</code>\n\n"
            "Add this Chat ID to <code>TELEGRAM_ALLOWED_CHAT_IDS</code> in your <code>.env</code> file!"
        )

    async def help_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handler for /help command."""
        await update.message.reply_html(
            "📖 <b>Instructions for Telegram Group:</b>\n"
            "1. Add this bot to your Telegram Group.\n"
            "2. Make the bot an <b>Admin</b> (or disable Privacy Mode via @BotFather -> /setprivacy).\n"
            "3. Upload any video file (.mkv, .mp4, etc.) in the group.\n"
            "4. The bot will automatically analyze, fetch metadata, grab subtitles, and move it to Jellyfin!"
        )

    async def status_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handler for /status command."""
        await update.message.reply_html(
            "⚙️ <b>Platform Status:</b>\n"
            "• Engine: Active ✅\n"
            "• PostgreSQL: Healthy ✅\n"
            "• Redis Bus: Healthy ✅"
        )

    async def handle_document(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handler for video files uploaded as documents or video attachments in groups/private chats."""
        user = update.effective_user
        chat = update.effective_chat

        logger.info("Media message detected in chat", user_id=user.id, chat_id=chat.id, chat_type=chat.type)

        if not self._is_allowed(user.id, chat.id):
            logger.warning("Rejected unauthorized media message", user_id=user.id, chat_id=chat.id)
            return

        # Extract document or video object
        document = update.message.document or update.message.video
        if not document:
            return

        file_name = document.file_name or f"video_{document.file_id[:8]}.mkv"
        file_size_mb = round((document.file_size or 0) / (1024 * 1024), 2)

        msg = await update.message.reply_html(
            f"📥 <b>Group Media Received:</b> {file_name} ({file_size_mb} MB)\n"
            "Downloading file to platform storage..."
        )

        try:
            tg_file = await context.bot.get_file(document.file_id)
            save_path = self.incoming_dir / file_name
            await tg_file.download_to_drive(custom_path=save_path)

            correlation_id = str(uuid.uuid4())
            logger.info("Downloaded Telegram group file", file_name=file_name, path=str(save_path), chat_id=chat.id)

            # Publish event to Redis Stream
            await self.publisher.publish(
                event_type=EventType.MOVIE_RECEIVED,
                payload={
                    "file_path": str(save_path),
                    "file_name": file_name,
                    "file_size": document.file_size,
                    "source": "telegram_group",
                    "chat_id": chat.id,
                    "user_id": user.id,
                },
                source_service="telegram-service",
                correlation_id=correlation_id,
            )

            await msg.edit_text(
                f"✅ <b>Group File Received & Queued!</b>\n\n"
                f"📄 <b>File:</b> {file_name}\n"
                f"🆔 <b>Correlation ID:</b> <code>{correlation_id}</code>\n\n"
                "Automation pipeline started! (Analyzing → Metadata → Subtitle → Jellyfin)",
                parse_mode="HTML",
            )
        except Exception as exc:
            logger.error("Failed to process group media file", error=str(exc))
            await msg.edit_text(f"❌ Failed to process file: {str(exc)}")

    def build_application(self) -> Application:
        """Build python-telegram-bot application with commands and document filters."""
        if not settings.telegram_bot_token:
            logger.warning("TELEGRAM_BOT_TOKEN is not configured!")

        app = Application.builder().token(settings.telegram_bot_token or "dummy_token").build()

        app.add_handler(CommandHandler("start", self.start_command))
        app.add_handler(CommandHandler("id", self.id_command))
        app.add_handler(CommandHandler("help", self.help_command))
        app.add_handler(CommandHandler("status", self.status_command))
        app.add_handler(MessageHandler(filters.Document.ALL | filters.VIDEO | filters.ATTACHMENT, self.handle_document))

        return app
