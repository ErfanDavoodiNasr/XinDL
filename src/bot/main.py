import asyncio
import sys
import aiohttp
from aiogram import Bot, Dispatcher
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.client.telegram import TelegramAPIServer
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from src.core.config import settings
from src.core.resources import runtime
from src.bot.handlers import router
from src.core.logger import setup_logger
from src.core.storage import cleanup_download_dir
from src.bot.middlewares import RequestContextMiddleware

logger = setup_logger()


async def wait_for_local_api() -> None:
    if not settings.USE_LOCAL_API:
        return

    base = settings.TELEGRAM_LOCAL_API_URL.rstrip("/")
    timeout = settings.LOCAL_API_STARTUP_TIMEOUT
    logger.info("Waiting for local Telegram API at %s (timeout=%ss)", base, timeout)

    for attempt in range(1, timeout + 1):
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    f"{base}/",
                    timeout=aiohttp.ClientTimeout(total=3),
                ) as response:
                    if response.status < 500:
                        logger.info("Local Telegram API ready after %ss", attempt)
                        return
        except Exception:
            pass
        await asyncio.sleep(1)

    raise RuntimeError(
        f"Local Telegram API not reachable at {base} after {timeout}s. "
        "Check telegram-bot-api container logs and volume permissions."
    )


async def main():
    logger.info("Starting Telegram Bot...")
    cleanup_download_dir(max_age_seconds=runtime.DOWNLOAD_CLEANUP_AGE_SECONDS)
    if settings.BOT_TOKEN == "your_telegram_bot_token_here":
        logger.error("BOT_TOKEN is not set in environment variables! Please set it in .env")
        return

    await wait_for_local_api()

    bot = Bot(
        token=settings.BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML)
    )

    if settings.USE_LOCAL_API:
        logger.info("Configuring Bot to use Local Telegram API Server...")
        session = AiohttpSession(
            api=TelegramAPIServer.from_base(settings.TELEGRAM_LOCAL_API_URL, is_local=True),
            timeout=10800,
        )
        bot = Bot(
            token=settings.BOT_TOKEN,
            session=session,
            default=DefaultBotProperties(parse_mode=ParseMode.HTML)
        )

    dp = Dispatcher()

    dp.update.middleware(RequestContextMiddleware())
    dp.include_router(router)

    try:
        await bot.delete_webhook(drop_pending_updates=True)
        await dp.start_polling(bot)
    except Exception as e:
        logger.error(f"Error starting bot: {e}")
        raise
    finally:
        await bot.session.close()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Bot stopped!")
