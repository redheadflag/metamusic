import asyncio
import logging
import os

from aiogram import Bot, Dispatcher
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.client.telegram import TelegramAPIServer
from aiogram.fsm.storage.memory import MemoryStorage
from dotenv import load_dotenv

from handlers.menu import router as menu_router
from handlers.registration import router as registration_router

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)


async def main() -> None:
    bot_api_url = os.environ.get("BOT_API_URL")

    if bot_api_url:
        logger.info("Using local Bot API server: %s", bot_api_url)
        session = AiohttpSession(api=TelegramAPIServer.from_base(bot_api_url))
    else:
        logger.warning(
            "BOT_API_URL is not set — using official Telegram API (20 MB file limit)"
        )
        session = None

    bot = Bot(token=os.environ["BOT_TOKEN"], session=session)
    dp = Dispatcher(storage=MemoryStorage())

    dp.include_router(menu_router)
    dp.include_router(registration_router)

    bot_info = await bot.get_me()
    logger.info("Bot @%s started successfully", bot_info.username)

    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
