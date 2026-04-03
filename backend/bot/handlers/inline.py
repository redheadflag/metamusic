import asyncio
import hashlib
import logging
import os
from random import random
import secrets
import subprocess
from urllib.parse import urlencode

import aiohttp
from aiogram import Bot, Router
from aiogram.types import (
    BufferedInputFile,
    ChosenInlineResult,
    InputMediaAudio,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    InlineQuery,
    InlineQueryResultArticle,
    InlineQueryResultAudio,
    InlineQueryResultCachedAudio,
    InputTextMessageContent,
    URLInputFile,
)

from db import get_user

router = Router()

# song_id → Telegram file_id (real audio, pre-uploaded with cover art thumbnail)
_file_id_cache: dict[str, str] = {}

# song_id → Telegram file_id (silent stub with correct track metadata)
_stub_cache: dict[str, str] = {}

# Cached silent MP3 bytes so ffmpeg runs only once
_stub_bytes: bytes | None = None

# Keyboard attached to stubs — required for Telegram to include inline_message_id
# in ChosenInlineResult so we can later edit the message with the real track.
_loading_keyboard = InlineKeyboardMarkup(inline_keyboard=[[
    InlineKeyboardButton(text="⏳ Загрузка...", callback_data="loading")
]])


def _get_silent_stub_bytes() -> bytes:
    global _stub_bytes
    if _stub_bytes is None:
        result = subprocess.run(
            [
                "ffmpeg", "-y",
                "-f", "lavfi", "-i", "anullsrc=r=8000:cl=mono",
                "-t", "1", "-q:a", "9",
                "-f", "mp3", "pipe:1",
            ],
            capture_output=True,
            check=True,
        )
        _stub_bytes = result.stdout
    return _stub_bytes


async def _upload_stub_for_entry(bot: Bot, user_id: int, entry: dict) -> str | None:
    """Upload a silent stub with the track's real metadata; cache per song_id."""
    song_id = str(entry["id"])
    if song_id in _stub_cache:
        return _stub_cache[song_id]
    try:
        msg = await bot.send_audio(
            chat_id=user_id,
            audio=BufferedInputFile(_get_silent_stub_bytes(), filename="stub.mp3"),
            title=entry.get("title", "…"),
            performer=entry.get("artist"),
            duration=entry.get("duration") or 1,
            disable_notification=True,
        )
        _stub_cache[song_id] = msg.audio.file_id
        await bot.delete_message(user_id, msg.message_id)
    except Exception as exc:
        logging.warning("Failed to upload stub for %s: %s", song_id, exc)
        return None
    return _stub_cache[song_id]


async def fetch_song(base_url: str, auth: dict, song_id: str) -> dict | None:
    """Fetch a single track's metadata via Subsonic getSong."""
    async with aiohttp.ClientSession() as session:
        async with session.get(
            f"{base_url}/rest/getSong", params={**auth, "id": song_id}
        ) as resp:
            data = await resp.json(content_type=None)
    return data.get("subsonic-response", {}).get("song") or None


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


async def fetch_last_played_song(base_url: str, username: str, password: str) -> dict | None:
    """Return the most recently played song via Navidrome REST API, or None."""
    async with aiohttp.ClientSession() as session:
        async with session.post(
            f"{base_url}/auth/login",
            json={"username": username, "password": password},
        ) as resp:
            token = (await resp.json(content_type=None)).get("token")

    if not token:
        return None

    async with aiohttp.ClientSession() as session:
        async with session.get(
            f"{base_url}/api/song",
            params={"_sort": "play_date", "_order": "DESC", "_start": "0", "_end": "1"},
            headers={"X-ND-Authorization": f"Bearer {token}"},
        ) as resp:
            songs = await resp.json(content_type=None)

    if not songs or not isinstance(songs, list):
        return None

    song = songs[0]
    if not song.get("playDate"):
        return None

    # Normalise to the same shape used by getNowPlaying / send_audio_entry
    return {
        "id": song["id"],
        "title": song.get("title"),
        "artist": song.get("artist"),
        "coverArt": song.get("coverArtId"),
        "duration": int(song.get("duration") or 0),
    }


async def search_tracks(base_url: str, auth: dict, query: str, count: int = 10) -> list[dict]:
    """Search Navidrome for tracks matching `query` via Subsonic search3."""
    params = {**auth, "query": query, "songCount": count, "albumCount": 0, "artistCount": 0}
    async with aiohttp.ClientSession() as session:
        async with session.get(f"{base_url}/rest/search3", params=params) as resp:
            data = await resp.json(content_type=None)
    songs = (
        data.get("subsonic-response", {})
        .get("searchResult3", {})
        .get("song", [])
    )
    if isinstance(songs, dict):
        songs = [songs]
    return songs


async def fetch_now_playing(base_url: str, auth: dict, username: str) -> list[dict]:
    """Return getNowPlaying entries belonging to `username` only."""
    async with aiohttp.ClientSession() as session:
        async with session.get(f"{base_url}/rest/getNowPlaying", params=auth) as resp:
            data = await resp.json(content_type=None)
    entries = data.get("subsonic-response", {}).get("nowPlaying", {}).get("entry", [])
    if isinstance(entries, dict):
        entries = [entries]
    return [e for e in entries if e.get("username", "").lower() == username.lower()]


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
            audio_bytes = await resp.content.read(-1)

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
            audio_bytes = await resp.content.read(-1)

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
async def now_playing_inline(query: InlineQuery, bot: Bot) -> None:
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
            is_personal=True,
        )
        return

    base_url = os.environ["NAVIDROME_URL"].rstrip("/")
    auth = _auth_params(user["username"], user["password"])

    search_text = query.query.strip()
    if len(search_text) >= 3:
        entries = await search_tracks(base_url, auth, search_text)
        if not entries:
            await query.answer(
                [
                    InlineQueryResultArticle(
                        id="no_results",
                        title="Ничего не найдено",
                        input_message_content=InputTextMessageContent(
                            message_text=f"По запросу «{search_text}» ничего не найдено."
                        ),
                    )
                ],
                cache_time=10,
                is_personal=True,
            )
            return
    else:
        entries = await fetch_now_playing(base_url, auth, user["username"])
        if not entries:
            last = await fetch_last_played_song(base_url, user["username"], user["password"])
            if not last:
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
                    is_personal=True,
                )
                return
            entries = [last]

    # Upload stubs concurrently for all uncached tracks
    uncached = [e for e in entries if str(e["id"]) not in _file_id_cache]
    if uncached:
        await asyncio.gather(*[
            _upload_stub_for_entry(bot, query.from_user.id, e) for e in uncached
        ])

    results = []
    for entry in entries:
        song_id = str(entry["id"])
        cover_art_id = entry.get("coverArt")

        if song_id in _file_id_cache:
            # Real audio already cached — send it directly, no edit needed later
            results.append(
                InlineQueryResultCachedAudio(
                    id=song_id,
                    audio_file_id=_file_id_cache[song_id],
                    caption="music.redheadflag.com" if bool(random() < 0.1) else None,
                )
            )
        elif song_id in _stub_cache:
            # Stub with correct metadata as placeholder; ChosenInlineResult will swap it.
            # The keyboard is required so Telegram includes inline_message_id in
            # ChosenInlineResult — without it we can't edit the sent message.
            results.append(
                InlineQueryResultCachedAudio(
                    id=song_id,
                    audio_file_id=_stub_cache[song_id],
                    reply_markup=_loading_keyboard,
                )
            )
        else:
            # Stub upload failed — fall back to streaming URL
            auth_entry = _auth_params(user["username"], user["password"])
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

    await query.answer(results, cache_time=10, is_personal=True)


@router.chosen_inline_result()
async def on_chosen_inline_result(result: ChosenInlineResult, bot: Bot) -> None:
    """
    Fired when the user picks an inline result. If a stub was sent (track not
    yet cached), download the real audio, upload it to get a file_id, cache it,
    then edit the inline message to replace the stub.
    """
    inline_message_id = result.inline_message_id
    if not inline_message_id:
        return

    song_id = result.result_id
    if song_id in _file_id_cache:
        # Real audio was already in the result — nothing to edit
        return

    user = get_user(result.from_user.id)
    if not user:
        return

    base_url = os.environ["NAVIDROME_URL"].rstrip("/")
    auth = _auth_params(user["username"], user["password"])

    entry = await fetch_song(base_url, auth, song_id)
    if not entry:
        return

    # Download + upload to DM to obtain a cacheable Telegram file_id
    await _upload_and_cache(bot, result.from_user.id, base_url, entry, auth)
    if song_id not in _file_id_cache:
        return  # upload failed, leave the stub in place

    cover_art_id = entry.get("coverArt")
    thumbnail = None
    if cover_art_id:
        cover_url = f"{base_url}/rest/getCoverArt?id={cover_art_id}&size=300&{urlencode(auth)}"
        thumbnail = URLInputFile(cover_url, filename="cover.jpg")

    await bot.edit_message_media(
        media=InputMediaAudio(
            media=_file_id_cache[song_id],
            thumbnail=thumbnail,
            title=entry.get("title"),
            performer=entry.get("artist"),
            duration=entry.get("duration"),
        ),
        inline_message_id=inline_message_id,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[]),  # remove loading button
    )
