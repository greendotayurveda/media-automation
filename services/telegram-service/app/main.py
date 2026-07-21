"""
Main entrypoint for Telegram Service microservice.
"""
import asyncio
from fastapi import FastAPI
import uvicorn

from shared.config.settings import settings
from shared.logging.logger import get_logger
from app.bot import TelegramBotHandler

logger = get_logger("telegram-service")

app = FastAPI(title="Telegram Service", version=settings.platform_version)


@app.get("/health")
async def health_check():
    return {"status": "ok", "service": "telegram-service"}


async def main():
    bot_handler = TelegramBotHandler()

    if settings.telegram_bot_token and settings.telegram_bot_token != "dummy_token":
        bot_app = bot_handler.build_application()
        await bot_app.initialize()
        await bot_app.start()
        await bot_app.updater.start_polling()
        logger.info("Telegram bot polling started")
    else:
        logger.warning("TELEGRAM_BOT_TOKEN not configured. Bot polling disabled (HTTP health check running).")

    config = uvicorn.Config(app=app, host="0.0.0.0", port=8002, log_level="warning")
    server = uvicorn.Server(config)
    await server.serve()


if __name__ == "__main__":
    asyncio.run(main())
