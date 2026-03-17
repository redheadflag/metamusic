import logging

from aiogram import Router, F

from bot.constants import TEXT_APPLICATIONS_LIST, TEXT_UPLOAD_MUSIC
from bot.keyboards import BTN_ALREADY_HAVE_ACCOUNT, BTN_APPLICATIONS, BTN_UPLOAD_MUSIC, account_menu


router = Router()
logger = logging.getLogger(__name__)


@router.message(F.text == BTN_ALREADY_HAVE_ACCOUNT)
async def handle_already_have_account(message):
    await message.answer(
        "Добро пожаловать в главное меню!",
        reply_markup=account_menu,
    )


@router.message(F.text == BTN_APPLICATIONS)
async def handle_applications(message):
    await message.answer(
        TEXT_APPLICATIONS_LIST,
        parse_mode="HTML",
    )


@router.message(F.text == BTN_UPLOAD_MUSIC)
async def handle_upload_music(message):
    await message.answer(
        TEXT_UPLOAD_MUSIC,
        parse_mode="HTML",
    )
