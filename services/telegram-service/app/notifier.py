"""
Telegram status notifier worker.
Subscribes to stream:downloads and stream:workflows to render live progress,
download completion, and Jellyfin readiness directly into the group chat message.
"""
from typing import Any, Dict, Optional
from pathlib import Path

from shared.events.events import EventType, StreamName
from shared.events.subscriber import EventSubscriber
from shared.logging.logger import get_logger

logger = get_logger("telegram-notifier")


def render_progress_bar(pct: float) -> str:
    filled = int(pct / 10)
    return "█" * filled + "░" * (10 - filled)


def format_speed(bps: int) -> str:
    if bps >= 1024 * 1024:
        return f"{bps / (1024 * 1024):.1f} MB/s"
    if bps >= 1024:
        return f"{bps / 1024:.1f} KB/s"
    return f"{bps} B/s"


def format_eta(seconds: Optional[int]) -> str:
    if not seconds or seconds > 86400:
        return "calculating..."
    mins, secs = divmod(seconds, 60)
    hrs, mins = divmod(mins, 60)
    if hrs > 0:
        return f"{hrs}h {mins}m"
    if mins > 0:
        return f"{mins}m {secs}s"
    return f"{secs}s"


class TelegramStatusNotifier(EventSubscriber):
    stream = StreamName.DOWNLOADS
    consumer_name = "tg-notifier"
    events = [
        EventType.DOWNLOAD_PROGRESS,
        EventType.DOWNLOAD_COMPLETED,
        EventType.DOWNLOAD_FAILED,
        EventType.FILE_ORGANIZED,
    ]

    def __init__(self, bot) -> None:
        super().__init__(service_name="telegram-service")
        self.bot = bot

    async def handle(
        self,
        event_type: EventType,
        payload: Dict[str, Any],
        raw_event: Dict[str, str],
    ) -> None:
        chat_id = payload.get("chat_id")
        message_id = payload.get("message_id")
        if not chat_id or not message_id:
            return

        title = payload.get("title") or "Media / Torrent"
        download_id = str(payload.get("download_id") or "")

        try:
            if event_type == EventType.DOWNLOAD_PROGRESS:
                progress = float(payload.get("progress") or 0.0)
                speed = int(payload.get("download_speed_bps") or 0)
                eta = payload.get("eta_seconds")
                bar = render_progress_bar(progress)
                spd_str = format_speed(speed)
                eta_str = format_eta(eta)

                text = (
                    f"⏬ <b>Downloading Media...</b>\n\n"
                    f"📄 <b>Title:</b> {title}\n"
                    f"📊 <b>Progress:</b> <code>[{bar}] {progress:.1f}%</code>\n"
                    f"🚀 <b>Speed:</b> <code>{spd_str}</code> | ⏱ <b>ETA:</b> <code>{eta_str}</code>\n"
                    f"🆔 <b>Download:</b> <code>{download_id[:8]}</code>"
                )
                await self.bot.edit_message_text(
                    chat_id=chat_id,
                    message_id=message_id,
                    text=text,
                    parse_mode="HTML",
                )

            elif event_type == EventType.DOWNLOAD_COMPLETED:
                text = (
                    f"⚙️ <b>Download Completed!</b>\n\n"
                    f"📄 <b>Title:</b> {title}\n"
                    f"🍿 <b>Status:</b> Running media pipeline (Metadata, Subtitles, Jellyfin)...\n"
                    f"🆔 <b>Download:</b> <code>{download_id[:8]}</code>"
                )
                await self.bot.edit_message_text(
                    chat_id=chat_id,
                    message_id=message_id,
                    text=text,
                    parse_mode="HTML",
                )

            elif event_type == EventType.DOWNLOAD_FAILED:
                err = payload.get("error") or "Unknown error"
                text = (
                    f"❌ <b>Download Failed</b>\n\n"
                    f"📄 <b>Title:</b> {title}\n"
                    f"⚠️ <b>Error:</b> <code>{err[:200]}</code>"
                )
                await self.bot.edit_message_text(
                    chat_id=chat_id,
                    message_id=message_id,
                    text=text,
                    parse_mode="HTML",
                )

            elif event_type == EventType.FILE_ORGANIZED:
                dest = payload.get("dest_path") or ""
                file_name = Path(dest).name if dest else title
                text = (
                    f"🎉 <b>Ready on Jellyfin!</b>\n\n"
                    f"🎬 <b>Title:</b> {file_name}\n"
                    f"✅ Download, metadata, & subtitle pipeline finished.\n"
                    f"🍿 <i>Available in your library now. Enjoy watching!</i>"
                )
                await self.bot.edit_message_text(
                    chat_id=chat_id,
                    message_id=message_id,
                    text=text,
                    parse_mode="HTML",
                )

        except Exception:
            # Ignore telegram rate limit / message unchanged errors safely
            pass
