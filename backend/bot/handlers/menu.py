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
        "👋 Welcome! Choose an option below:",
        reply_markup=main_menu,
    )


@router.message(F.text == BTN_CREATE_ACCOUNT)
async def btn_create_account(message: Message, state: FSMContext) -> None:
    await state.set_state(Registration.waiting_for_username)
    await message.answer(
        "Please enter a username for your new Navidrome account.\n\n"
        "Rules:\n"
        "• 3–32 characters\n"
        "• Letters (a–Z), digits (0–9), and <code>-</code> <code>_</code> <code>.</code> only",
        parse_mode="HTML",
    )
