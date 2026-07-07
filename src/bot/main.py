import asyncio
import logging
import sys
from aiogram import Bot, Dispatcher
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.client.telegram import TelegramAPIServer
from src.core.config import settings
from src.bot.handlers import router

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    stream=sys.stdout
)
logger = logging.getLogger(__name__)

async def main():
    logger.info("Starting Telegram Bot...")
    if settings.BOT_TOKEN == "your_telegram_bot_token_here":
        logger.error("BOT_TOKEN is not set in environment variables! Please set it in .env")
        return

    bot = Bot(token=settings.BOT_TOKEN)
    
    if settings.USE_LOCAL_API:
        logger.info("Configuring Bot to use Local Telegram API Server...")
        session = AiohttpSession(
            api=TelegramAPIServer.from_base('http://telegram-bot-api:8081', is_local=True)
        )
        bot = Bot(token=settings.BOT_TOKEN, session=session)

    dp = Dispatcher()

    # Include routers
    dp.include_router(router)

    try:
        await bot.delete_webhook(drop_pending_updates=True)
        await dp.start_polling(bot)
    except Exception as e:
        logger.error(f"Error starting bot: {e}")
    finally:
        await bot.session.close()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Bot stopped!")
