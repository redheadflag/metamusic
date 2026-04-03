import asyncio
import logging
import os

from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties

from dotenv import load_dotenv

from db import init_db
from handlers.menu import router as menu_router
from handlers.registration import router as registration_router
from handlers.login import router as login_router
from handlers.account_menu import router as account_menu_router
from handlers.inline import router as inline_router

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)


async def main() -> None:
    init_db()

    bot = Bot(
        token=os.environ["BOT_TOKEN"],
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dp = Dispatcher(storage=MemoryStorage())

    dp.include_router(menu_router)
    dp.include_router(registration_router)
    dp.include_router(login_router)
    dp.include_router(account_menu_router)
    dp.include_router(inline_router)

    bot_info = await bot.get_me()
    logger.info("Bot @%s started successfully", bot_info.username)

    await dp.start_polling(
        bot,
        allowed_updates=["message", "callback_query", "inline_query", "chosen_inline_result"],
    )


if __name__ == "__main__":
    asyncio.run(main())
