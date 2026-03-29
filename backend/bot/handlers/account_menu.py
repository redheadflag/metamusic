import logging
import os

from aiogram import Router, F
from aiogram.types import Message

from constants import TEXT_APPLICATIONS_LIST, TEXT_NOW_PLAYING, TEXT_UPLOAD_MUSIC
from db import get_user
from handlers.inline import _auth_params, fetch_now_playing, send_audio_entry
from keyboards import BTN_APPLICATIONS, BTN_NOW_PLAYING, BTN_UPLOAD_MUSIC

router = Router()
logger = logging.getLogger(__name__)


@router.message(F.text == BTN_NOW_PLAYING)
async def handle_now_playing(message: Message):
    bot_info = await message.bot.get_me()
    await message.answer(
        TEXT_NOW_PLAYING.format(bot_username=bot_info.username),
        parse_mode="HTML",
    )

    user = get_user(message.from_user.id)
    if not user:
        return

    base_url = os.environ["NAVIDROME_URL"].rstrip("/")
    auth = _auth_params(user["username"], user["password"])
    entries = await fetch_now_playing(base_url, auth)

    if not entries:
        await message.answer("▶️ Сейчас ничего не играет.")
        return

    await send_audio_entry(message.bot, message.chat.id, base_url, entries[0], auth)


@router.message(F.text == BTN_APPLICATIONS)
async def handle_applications(message: Message):
    await message.answer(
        TEXT_APPLICATIONS_LIST,
        parse_mode="HTML",
    )


@router.message(F.text == BTN_UPLOAD_MUSIC)
async def handle_upload_music(message: Message):
    await message.answer(
        TEXT_UPLOAD_MUSIC,
        parse_mode="HTML",
    )
