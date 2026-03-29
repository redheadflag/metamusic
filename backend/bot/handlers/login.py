import hashlib
import logging
import os
import secrets

import aiohttp
from aiogram import Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message

from db import save_user
from keyboards import account_menu, main_menu

router = Router()
logger = logging.getLogger(__name__)


class Login(StatesGroup):
    waiting_for_username = State()
    waiting_for_password = State()


async def _verify_navidrome(username: str, password: str) -> bool:
    """Ping Navidrome with the given credentials. Returns True if auth succeeds."""
    base_url = os.environ["NAVIDROME_URL"].rstrip("/")
    salt = secrets.token_hex(6)
    token = hashlib.md5((password + salt).encode()).hexdigest()
    params = {
        "u": username,
        "t": token,
        "s": salt,
        "v": "1.16.1",
        "c": "redheadflagbot",
        "f": "json",
    }
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(f"{base_url}/rest/ping", params=params) as resp:
                data = await resp.json(content_type=None)
        return data.get("subsonic-response", {}).get("status") == "ok"
    except Exception as exc:
        logger.error("Navidrome ping failed: %s", exc)
        return False


@router.message(Login.waiting_for_username)
async def handle_login_username(message: Message, state: FSMContext) -> None:
    await state.update_data(username=(message.text or "").strip())
    await state.set_state(Login.waiting_for_password)
    await message.answer("Введи пароль:")


@router.message(Login.waiting_for_password)
async def handle_login_password(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    username = data.get("username", "")
    password = (message.text or "").strip()

    if not await _verify_navidrome(username, password):
        await state.clear()
        await message.answer(
            "❌ Неверное имя пользователя или пароль.\n"
            "Попробуй снова — нажми «Войти в аккаунт».",
            reply_markup=main_menu,
        )
        return

    save_user(message.from_user.id, username, password)
    await state.clear()
    await message.answer(
        f"✅ Добро пожаловать, <b>{username}</b>!",
        parse_mode="HTML",
        reply_markup=account_menu,
    )
