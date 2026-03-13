import asyncio
import logging
import os

from aiogram import Bot, Dispatcher
from dotenv import load_dotenv

from handlers.echo import router as echo_router

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)


async def main() -> None:
    bot = Bot(token=os.environ["BOT_TOKEN"])
    dp = Dispatcher()

    dp.include_router(echo_router)

    bot_info = await bot.get_me()
    logger.info("Bot @%s started successfully", bot_info.username)

    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
