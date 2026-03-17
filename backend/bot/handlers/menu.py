from aiogram import F, Router
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from handlers.registration import Registration
from keyboards import BTN_CREATE_ACCOUNT, main_menu

router = Router()


@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext) -> None:
    await state.clear()
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
