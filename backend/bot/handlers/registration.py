import random
import re

from aiogram import Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message

from keyboards import main_menu
from services.navidrome import create_navidrome_user

router = Router()

USERNAME_RE = re.compile(r"^[a-zA-Z0-9\-_.]{3,32}$")


class Registration(StatesGroup):
    waiting_for_username = State()


@router.message(Registration.waiting_for_username)
async def handle_username(message: Message, state: FSMContext) -> None:
    username = (message.text or "").strip()

    if not USERNAME_RE.match(username):
        await message.answer(
            "❌ Invalid username. Please try again.\n\n"
            "Allowed: letters, digits, <code>-</code> <code>_</code> <code>.</code> — "
            "between 3 and 32 characters.",
            parse_mode="HTML",
        )
        return

    suffix = str(random.randint(1000, 9999))
    password = f"{username}{suffix}"

    try:
        await create_navidrome_user(username, password)
    except Exception as exc:
        await message.answer(f"⚠️ Could not create account: {exc}")
        return

    await state.clear()
    await message.answer(
        f"✅ Account created!\n\n"
        f"<b>Username:</b> <code>{username}</code>\n"
        f"<b>Password:</b> <code>{password}</code>\n\n"
        "Save these credentials — the password won't be shown again.",
        parse_mode="HTML",
        reply_markup=main_menu,
    )