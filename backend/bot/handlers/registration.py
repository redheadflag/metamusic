import logging
import os
import random
import re

from aiogram import Bot, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message

from db import save_user
from keyboards import account_menu
from services.navidrome import create_navidrome_user

router = Router()
logger = logging.getLogger(__name__)

USERNAME_RE = re.compile(r"^[a-zA-Z0-9\-_.]{3,32}$")


class Registration(StatesGroup):
    waiting_for_username = State()


@router.message(Registration.waiting_for_username)
async def handle_username(message: Message, state: FSMContext) -> None:
    username = (message.text or "").strip()

    if not USERNAME_RE.match(username):
        await message.answer(
            "Неправильное имя пользователя. Пожалуйста, попробуйте снова.\n\n"
            "Допустимые символы: буквы, цифры, <code>-</code> <code>_</code> <code>.</code> — "
            "от 3 до 32 символов.",
            parse_mode="HTML",
        )
        return

    suffix = str(random.randint(1000, 9999))
    password = f"{username}{suffix}"

    try:
        await create_navidrome_user(username, password)
    except Exception as exc:
        await message.answer(f"⚠️ Не удалось создать аккаунт: {exc}")
        return

    save_user(message.from_user.id, username, password)
    await state.clear()
    await message.answer(
        f"✅ Аккаунт создан!\n\n"
        f"<b>Имя пользователя:</b> <code>{username}</code>\n"
        f"<b>Пароль:</b> <code>{password}</code>\n\n"
        f"Сервер: <code>{os.environ.get('NAVIDROME_URL')}</code>\n\n"
        "Ты можешь использовать эти данные для входа в сервис и начать слушать музыку!\n\n",
        parse_mode="HTML",
        reply_markup=account_menu,
        disable_web_page_preview=True,
    )

    await _notify_admin(message.bot, message)


async def _notify_admin(bot: Bot, message: Message) -> None:
    admin_id = os.environ.get("ADMIN_USER_TELEGRAM_ID")
    if not admin_id:
        logger.warning(
            "ADMIN_USER_TELEGRAM_ID is not set — skipping admin notification"
        )
        return

    user = message.from_user
    user_id = user.id if user else "unknown"
    username_tg = f"@{user.username}" if user and user.username else "no username"

    try:
        await bot.send_message(
            chat_id=int(admin_id),
            text=(
                f"👤 New account registered\n\n"
                f"<b>Telegram ID:</b> <code>{user_id}</code>\n"
                f"<b>Telegram username:</b> {username_tg}\n\n"
                f"<b>Registered username:</b> <code>{message.text}</code>"
            ),
            parse_mode="HTML",
        )
    except Exception as exc:
        logger.error("Failed to notify admin (chat_id=%s): %s", admin_id, exc)
