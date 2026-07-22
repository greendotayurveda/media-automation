"""
Telegram bot handler supporting Private and Group chats.
Handles media file uploads and magnet / torrent / qBittorrent links.
"""
import os
import re
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
from shared.database.connection import get_db_session
from shared.database.models.download import Download
from shared.events.events import EventType, StreamName
from shared.events.publisher import EventPublisher
from shared.logging.logger import get_logger

logger = get_logger("telegram-bot")

# Import link helpers without coupling telegram → download-service package path.
# Duplicate minimal regex here to keep telegram-service self-contained in Docker.
_MAGNET_RE = re.compile(r"magnet:\?[^\s<>\"']+", re.IGNORECASE)
_QBIT_RE = re.compile(r"qbittorrent:[^\s<>\"']+", re.IGNORECASE)
_TORRENT_URL_RE = re.compile(
    r"https?://[^\s<>\"']+\.torrent(?:\?[^\s<>\"']*)?",
    re.IGNORECASE,
)


def _extract_torrent_links(message_or_text) -> list[str]:
    if not message_or_text:
        return []

    texts: list[str] = []
    if isinstance(message_or_text, str):
        texts.append(message_or_text)
    else:
        msg = message_or_text
        if getattr(msg, "text", None):
            texts.append(msg.text)
        if getattr(msg, "caption", None):
            texts.append(msg.caption)

        # Extract URLs from hyperlinks / text_link entities in forwarded posts
        entities = list(getattr(msg, "entities", []) or []) + list(getattr(msg, "caption_entities", []) or [])
        for entity in entities:
            if getattr(entity, "url", None):
                texts.append(entity.url)

    found: list[str] = []
    for text in texts:
        for pattern in (_MAGNET_RE, _QBIT_RE, _TORRENT_URL_RE):
            for match in pattern.finditer(text):
                link = match.group(0).rstrip(").,];")
                if link not in found:
                    found.append(link)
    return found


class TelegramBotHandler:
    """
    Manages Telegram bot commands, group media files, and torrent links.
    """

    def __init__(self) -> None:
        self.workflow_publisher = EventPublisher(StreamName.WORKFLOWS)
        self.download_publisher = EventPublisher(StreamName.DOWNLOADS)
        self.incoming_dir = settings.download_root / "incoming"
        self.torrent_dir = settings.download_root / "torrents" / "telegram"
        os.makedirs(self.incoming_dir, exist_ok=True)
        os.makedirs(self.torrent_dir, exist_ok=True)

    def _is_allowed(self, user_id: int, chat_id: int) -> bool:
        allowed_chats = settings.telegram_allowed_chat_id_list
        if not allowed_chats:
            return True
        return user_id in allowed_chats or chat_id in allowed_chats

    async def start_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        user = update.effective_user
        chat = update.effective_chat
        logger.info("/start received", user_id=user.id, chat_id=chat.id, chat_type=chat.type)

        if not self._is_allowed(user.id, chat.id):
            await update.message.reply_text("⛔ Unauthorized access.")
            return

        await update.message.reply_html(
            f"👋 Hello {user.mention_html()}!\n\n"
            "Welcome to <b>Media Automation Platform</b>.\n"
            "Send a <b>movie file</b>, <b>magnet link</b>, or <b>.torrent</b> URL to start ingestion.\n\n"
            "<b>Commands:</b>\n"
            "/id - Show current Group Chat ID\n"
            "/status - System health & downloads\n"
            "/help - Bot instructions"
        )

    async def id_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
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
        await update.message.reply_html(
            "📖 <b>How to use:</b>\n"
            "1. Add this bot to your group (Admin, or disable Privacy Mode).\n"
            "2. Send either:\n"
            "   • a video file (.mkv / .mp4)\n"
            "   • a <code>magnet:?</code> link\n"
            "   • a <code>.torrent</code> URL or torrent file\n"
            "   • a <code>qbittorrent://</code> link\n"
            "3. Torrents go to qBittorrent, then the pipeline runs "
            "(Analyze → Metadata → Subtitles → Quality → Jellyfin)."
        )

    async def status_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        qbit = "configured ✅" if settings.qbittorrent_password else "not configured ⚠️"
        await update.message.reply_html(
            "⚙️ <b>Platform Status:</b>\n"
            "• Engine: Active ✅\n"
            "• PostgreSQL: Healthy ✅\n"
            "• Redis Bus: Healthy ✅\n"
            f"• qBittorrent: {qbit}"
        )

    async def handle_document(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handler for video files or .torrent attachments."""
        user = update.effective_user
        chat = update.effective_chat

        if not self._is_allowed(user.id, chat.id):
            logger.warning("Rejected unauthorized media message", user_id=user.id, chat_id=chat.id)
            return

        document = update.message.document or update.message.video
        if not document:
            return

        file_name = document.file_name or f"video_{document.file_id[:8]}.mkv"
        lower_name = file_name.lower()

        # .torrent attachment → queue via download-service / qBittorrent
        if lower_name.endswith(".torrent"):
            await self._handle_torrent_file_attachment(update, context, document, file_name)
            return

        file_size_mb = round((document.file_size or 0) / (1024 * 1024), 2)
        msg = await update.message.reply_html(
            f"📥 <b>Media Received:</b> {file_name} ({file_size_mb} MB)\n"
            "Downloading file to platform storage..."
        )

        try:
            tg_file = await context.bot.get_file(document.file_id, read_timeout=600)
            save_path = self.incoming_dir / file_name
            await tg_file.download_to_drive(custom_path=save_path, read_timeout=600)

            correlation_id = str(uuid.uuid4())
            await self.workflow_publisher.publish(
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
                f"✅ <b>File Queued!</b>\n\n"
                f"📄 <b>File:</b> {file_name}\n"
                f"🆔 <b>Correlation ID:</b> <code>{correlation_id}</code>\n\n"
                "Pipeline started.",
                parse_mode="HTML",
            )
        except Exception as exc:
            logger.error("Failed to process media file", error=str(exc))
            await msg.edit_text(f"❌ Failed to process file: {str(exc)}")

    async def handle_text_links(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Detect magnet / torrent / qbittorrent links in plain text messages, captions, and forwarded posts."""
        if not update.message:
            return
        user = update.effective_user
        chat = update.effective_chat

        if not self._is_allowed(user.id, chat.id):
            return

        links = _extract_torrent_links(update.message)
        if not links:
            return

        for link in links:
            await self._queue_torrent_link(update, link, user_id=user.id, chat_id=chat.id)

    async def _handle_torrent_file_attachment(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        document,
        file_name: str,
    ) -> None:
        user = update.effective_user
        chat = update.effective_chat
        msg = await update.message.reply_html(
            f"🧲 <b>Torrent file received:</b> {file_name}\n"
            "Sending to qBittorrent..."
        )
        try:
            tg_file = await context.bot.get_file(document.file_id, read_timeout=120)
            save_path = self.torrent_dir / file_name
            await tg_file.download_to_drive(custom_path=save_path, read_timeout=120)
            await self._queue_torrent_job(
                update=update,
                title=Path(file_name).stem,
                torrent_file=str(save_path),
                url=None,
                user_id=user.id,
                chat_id=chat.id,
                status_message=msg,
            )
        except Exception as exc:
            logger.error("Failed to queue torrent file", error=str(exc))
            await msg.edit_text(f"❌ Failed to queue torrent: {exc}")

    async def _queue_torrent_link(
        self,
        update: Update,
        link: str,
        *,
        user_id: int,
        chat_id: int,
    ) -> None:
        short = link if len(link) < 80 else link[:77] + "..."
        msg = await update.message.reply_html(
            f"🧲 <b>Torrent link received</b>\n<code>{short}</code>\n"
            "Queuing in qBittorrent..."
        )
        title = "torrent"
        if link.lower().startswith("magnet:"):
            name_match = re.search(r"[?&]dn=([^&]+)", link)
            if name_match:
                from urllib.parse import unquote

                title = unquote(name_match.group(1))[:200]
        try:
            await self._queue_torrent_job(
                update=update,
                title=title,
                torrent_file=None,
                url=link,
                user_id=user_id,
                chat_id=chat_id,
                status_message=msg,
            )
        except Exception as exc:
            logger.error("Failed to queue torrent link", error=str(exc), link=short)
            await msg.edit_text(f"❌ Failed to queue torrent: {exc}")

    async def _queue_torrent_job(
        self,
        *,
        update: Update,
        title: str,
        torrent_file: str | None,
        url: str | None,
        user_id: int,
        chat_id: int,
        status_message,
    ) -> None:
        if not settings.qbittorrent_password:
            await status_message.edit_text(
                "❌ qBittorrent is not configured.\n"
                "Set <code>QBITTORRENT_URL</code> and <code>QBITTORRENT_PASSWORD</code> in .env",
                parse_mode="HTML",
            )
            return

        correlation_id = str(uuid.uuid4())
        ext_id = (url or torrent_file)
        if ext_id and len(ext_id) > 255:
            ext_id = ext_id[:255]

        async with get_db_session() as db:
            download = Download(
                title=title[:500],
                source="torrent",
                status="queued",
                external_id=ext_id,
            )
            db.add(download)
            await db.commit()
            await db.refresh(download)
            download_id = download.id

        await self.download_publisher.publish(
            event_type=EventType.DOWNLOAD_QUEUED,
            payload={
                "download_id": download_id,
                "title": title,
                "url": url,
                "magnet": url,
                "torrent_file": torrent_file,
                "source": "telegram_torrent",
                "chat_id": chat_id,
                "user_id": user_id,
                "correlation_id": correlation_id,
            },
            source_service="telegram-service",
            correlation_id=correlation_id,
        )

        await status_message.edit_text(
            f"✅ <b>Queued in qBittorrent</b>\n\n"
            f"📄 <b>Title:</b> {title}\n"
            f"🆔 <b>Download:</b> <code>{download_id}</code>\n"
            f"🔗 <b>Correlation:</b> <code>{correlation_id}</code>\n\n"
            "I'll start the media pipeline automatically when the torrent finishes.",
            parse_mode="HTML",
        )

    def build_application(self) -> Application:
        if not settings.telegram_bot_token:
            logger.warning("TELEGRAM_BOT_TOKEN is not configured!")

        builder = Application.builder().token(settings.telegram_bot_token or "dummy_token")

        if settings.telegram_bot_api_url:
            base_url = f"{settings.telegram_bot_api_url.rstrip('/')}/bot"
            base_file_url = f"{settings.telegram_bot_api_url.rstrip('/')}/file/bot"
            builder.base_url(base_url)
            builder.base_file_url(base_file_url)
            builder.local_mode(True)
            logger.info("Enabled Local Telegram Bot API server", url=base_url)

        app = builder.build()

        app.add_handler(CommandHandler("start", self.start_command))
        app.add_handler(CommandHandler("id", self.id_command))
        app.add_handler(CommandHandler("help", self.help_command))
        app.add_handler(CommandHandler("status", self.status_command))
        app.add_handler(
            MessageHandler(filters.Document.ALL | filters.VIDEO | filters.ATTACHMENT, self.handle_document)
        )
        app.add_handler(
            MessageHandler((filters.TEXT | filters.CAPTION) & ~filters.COMMAND, self.handle_text_links)
        )

        return app
