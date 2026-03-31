import logging
import os

from aiogram import Bot, Router, F
from aiogram.types import CallbackQuery
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message

from constants import APPS, TEXT_NOW_PLAYING, TEXT_UPLOAD_MUSIC
from db import get_user
from handlers.inline import _auth_params, fetch_last_played_song, fetch_now_playing, send_audio_entry
from keyboards import BTN_APPLICATIONS, BTN_NOW_PLAYING, BTN_UPLOAD_MUSIC, BTN_REQUEST_MUSIC, account_menu, apps_os_keyboard

router = Router()
logger = logging.getLogger(__name__)


class MusicRequest(StatesGroup):
    waiting_for_request = State()


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
    entries = await fetch_now_playing(base_url, auth, user["username"])

    if entries:
        await send_audio_entry(message.bot, message.chat.id, base_url, entries[0], auth)
    else:
        last = await fetch_last_played_song(base_url, user["username"], user["password"])
        if last:
            await message.answer("Сейчас ничего не играет. Последний прослушанный трек:")
            await send_audio_entry(message.bot, message.chat.id, base_url, last, auth)
        else:
            await message.answer("▶️ Сейчас ничего не играет.")


@router.message(F.text == BTN_APPLICATIONS)
async def handle_applications(message: Message):
    await message.answer(
        "Выберите операционную систему:",
        reply_markup=apps_os_keyboard(),
    )


@router.callback_query(F.data.startswith("apps_os:"))
async def handle_apps_os(callback: CallbackQuery):
    assert callback.message

    os_name = callback.data.removeprefix("apps_os:")
    apps = APPS.get(os_name, [])
    if not apps:
        await callback.answer("Неизвестная система", show_alert=True)
        return
    lines = [f"<b>{os_name}</b>"]
    for app in apps:
        app_str_parts = []
        app_str_parts.append(f'<a href="{app["url"]}">{app["name"]}</a>')
        if app.get("note"):
            app_str_parts.append(app["note"])
        lines.append("\n".join(app_str_parts))
    await callback.message.answer("\n\n".join(lines))
    await callback.answer()


@router.message(F.text == BTN_UPLOAD_MUSIC)
async def handle_upload_music(message: Message):
    await message.answer(
        TEXT_UPLOAD_MUSIC,
        parse_mode="HTML",
    )


@router.message(F.text == BTN_REQUEST_MUSIC)
async def handle_request_music(message: Message, state: FSMContext):
    await state.set_state(MusicRequest.waiting_for_request)
    await message.answer(
        "Укажите список исполнителей, альбомов или треков, которые вы хотели бы добавить на сервер. "
        "Просьба добавлять только тех, кого вы действительно слушаете — место на сервере ограничено.",
        reply_markup=account_menu,
    )


@router.message(MusicRequest.waiting_for_request)
async def handle_request_text(message: Message, state: FSMContext):
    await state.clear()
    await _forward_request_to_admin(message.bot, message)
    await message.answer("Запрос отправлен. Спасибо!")


async def _forward_request_to_admin(bot: Bot, message: Message) -> None:
    admin_id = os.environ.get("ADMIN_USER_TELEGRAM_ID")
    if not admin_id:
        logger.warning("ADMIN_USER_TELEGRAM_ID is not set — skipping request forwarding")
        return

    user = message.from_user
    user_id = user.id if user else "unknown"
    username_tg = f"@{user.username}" if user and user.username else "без username"
    full_name = user.full_name if user else "unknown"

    try:
        await bot.send_message(
            chat_id=int(admin_id),
            text=(
                f"🎵 Запрос на добавление музыки\n\n"
                f"<b>От:</b> {full_name} ({username_tg}, <code>{user_id}</code>)\n\n"
                f"<b>Запрос:</b>\n{message.text}"
            ),
            parse_mode="HTML",
        )
    except Exception as exc:
        logger.error("Failed to forward music request to admin (chat_id=%s): %s", admin_id, exc)
