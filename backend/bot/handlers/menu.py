from aiogram import F, Router
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from db import delete_user, get_user
from handlers.login import Login, _verify_navidrome
from handlers.registration import Registration
from keyboards import BTN_CREATE_ACCOUNT, BTN_LOGIN, account_menu, main_menu

router = Router()


@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext) -> None:
    await state.clear()

    user = get_user(message.from_user.id)
    if user:
        if await _verify_navidrome(user["username"], user["password"]):
            await message.answer(
                f"👋 С возвращением, <b>{user['username']}</b>!",
                reply_markup=account_menu,
            )
            return
        else:
            delete_user(message.from_user.id)
            await message.answer(
                "⚠️ Не удалось подтвердить ваш аккаунт. Пожалуйста, войдите снова.",
                reply_markup=main_menu,
            )
            return

    await message.answer(
        "👋 Привет! Выбери команду:",
        reply_markup=main_menu,
    )


@router.message(F.text == BTN_CREATE_ACCOUNT)
async def btn_create_account(message: Message, state: FSMContext) -> None:
    await state.set_state(Registration.waiting_for_username)
    await message.answer(
        "Придумай имя пользователя для нового аккаунта\n\n"
        "Оно должно содержать:\n"
        "• 3–32 символа\n"
        "• Только буквы (a–Z), цифры (0–9), и <code>-</code> <code>_</code> <code>.</code>",
    )


@router.message(F.text == BTN_LOGIN)
async def btn_login(message: Message, state: FSMContext) -> None:
    await state.set_state(Login.waiting_for_username)
    await message.answer("Введи своё имя пользователя:")
