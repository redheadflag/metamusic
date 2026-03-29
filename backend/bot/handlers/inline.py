import asyncio
import hashlib
import os
import secrets
from urllib.parse import urlencode

import aiohttp
from aiogram import Bot, Router
from aiogram.types import (
    BufferedInputFile,
    InlineQuery,
    InlineQueryResultArticle,
    InlineQueryResultAudio,
    InlineQueryResultCachedAudio,
    InputTextMessageContent,
    URLInputFile,
)

from db import get_user

router = Router()

# song_id → Telegram file_id (audio pre-uploaded with cover art thumbnail)
_file_id_cache: dict[str, str] = {}


def _auth_params(username: str, password: str) -> dict:
    salt = secrets.token_hex(6)
    token = hashlib.md5((password + salt).encode()).hexdigest()
    return {
        "u": username,
        "t": token,
        "s": salt,
        "v": "1.16.1",
        "c": "redheadflagbot",
        "f": "json",
    }


async def fetch_now_playing(base_url: str, auth: dict, username: str) -> list[dict]:
    """Return getNowPlaying entries belonging to `username` only."""
    async with aiohttp.ClientSession() as session:
        async with session.get(f"{base_url}/rest/getNowPlaying", params=auth) as resp:
            data = await resp.json(content_type=None)
    entries = data.get("subsonic-response", {}).get("nowPlaying", {}).get("entry", [])
    if isinstance(entries, dict):
        entries = [entries]
    return [e for e in entries if e.get("username") == username]


async def send_audio_entry(
    bot: Bot, chat_id: int, base_url: str, entry: dict, auth: dict
) -> None:
    """Send a Navidrome track to chat_id, using cached file_id when available."""
    song_id = str(entry["id"])
    cover_art_id = entry.get("coverArt")

    if song_id in _file_id_cache:
        await bot.send_audio(chat_id=chat_id, audio=_file_id_cache[song_id])
        return

    audio_url = f"{base_url}/rest/stream?id={song_id}&format=mp3&{urlencode(auth)}"
    async with aiohttp.ClientSession() as session:
        async with session.get(audio_url) as resp:
            audio_bytes = await resp.read()

    thumbnail = None
    if cover_art_id:
        cover_url = f"{base_url}/rest/getCoverArt?id={cover_art_id}&size=300&{urlencode(auth)}"
        thumbnail = URLInputFile(cover_url, filename="cover.jpg")

    msg = await bot.send_audio(
        chat_id=chat_id,
        audio=BufferedInputFile(audio_bytes, filename=f"{entry.get('title', song_id)}.mp3"),
        thumbnail=thumbnail,
        title=entry.get("title"),
        performer=entry.get("artist"),
        duration=entry.get("duration"),
    )
    _file_id_cache[song_id] = msg.audio.file_id


async def _upload_and_cache(
    bot: Bot, user_id: int, base_url: str, entry: dict, auth: dict
) -> None:
    """Pre-upload audio to a DM, cache file_id, then delete the message."""
    song_id = str(entry["id"])
    if song_id in _file_id_cache:
        return

    audio_url = f"{base_url}/rest/stream?id={song_id}&format=mp3&{urlencode(auth)}"
    cover_art_id = entry.get("coverArt")

    async with aiohttp.ClientSession() as session:
        async with session.get(audio_url) as resp:
            audio_bytes = await resp.read()

    thumbnail = None
    if cover_art_id:
        cover_url = f"{base_url}/rest/getCoverArt?id={cover_art_id}&size=300&{urlencode(auth)}"
        thumbnail = URLInputFile(cover_url, filename="cover.jpg")

    msg = await bot.send_audio(
        chat_id=user_id,
        audio=BufferedInputFile(audio_bytes, filename=f"{entry.get('title', song_id)}.mp3"),
        thumbnail=thumbnail,
        title=entry.get("title"),
        performer=entry.get("artist"),
        duration=entry.get("duration"),
        disable_notification=True,
    )
    _file_id_cache[song_id] = msg.audio.file_id
    await bot.delete_message(user_id, msg.message_id)


@router.inline_query()
async def now_playing_inline(query: InlineQuery) -> None:
    user = get_user(query.from_user.id)
    if not user:
        await query.answer(
            [
                InlineQueryResultArticle(
                    id="not_logged_in",
                    title="Аккаунт не найден",
                    input_message_content=InputTextMessageContent(
                        message_text="Войдите в аккаунт через бота, чтобы использовать inline-режим."
                    ),
                )
            ],
            cache_time=5,
        )
        return

    base_url = os.environ["NAVIDROME_URL"].rstrip("/")
    auth = _auth_params(user["username"], user["password"])
    entries = await fetch_now_playing(base_url, auth, user["username"])

    if not entries:
        await query.answer(
            [
                InlineQueryResultArticle(
                    id="nothing",
                    title="Ничего не играет",
                    input_message_content=InputTextMessageContent(
                        message_text="Сейчас ничего не играет."
                    ),
                )
            ],
            cache_time=10,
        )
        return

    results = []
    for entry in entries:
        song_id = str(entry["id"])
        cover_art_id = entry.get("coverArt")
        auth_entry = _auth_params(user["username"], user["password"])

        if song_id not in _file_id_cache:
            upload = asyncio.ensure_future(
                _upload_and_cache(query.bot, query.from_user.id, base_url, entry, auth_entry)
            )
            try:
                await asyncio.wait_for(asyncio.shield(upload), timeout=5.0)
            except (asyncio.TimeoutError, Exception):
                pass

        if song_id in _file_id_cache:
            results.append(
                InlineQueryResultCachedAudio(
                    id=song_id,
                    audio_file_id=_file_id_cache[song_id],
                )
            )
        else:
            stream_url = f"{base_url}/rest/stream?id={song_id}&{urlencode(auth_entry)}"
            thumb_url = (
                f"{base_url}/rest/getCoverArt?id={cover_art_id}&size=300&{urlencode(auth_entry)}"
                if cover_art_id
                else None
            )
            results.append(
                InlineQueryResultAudio(
                    id=song_id,
                    audio_url=stream_url,
                    title=entry.get("title", "Unknown Title"),
                    performer=entry.get("artist", "Unknown Artist"),
                    audio_duration=entry.get("duration"),
                    thumbnail_url=thumb_url,
                )
            )

    await query.answer(results, cache_time=10)
