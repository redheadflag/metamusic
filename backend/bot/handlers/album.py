"""
Album upload flow
─────────────────
1. User clicks "Add Album 🎶"          → state: collecting_files
2. User sends audio files one by one   → bot stores file_id + Telegram-visible
                                         fields (title, performer, thumbnail)
3. User clicks "Album is ready ✅"     → bot downloads all files, reads full
                                         ID3 tags (album, year, track#, cover)
4. Bot checks shared fields            (artist, album_artist, album, cover_art)
   • if any missing → state: fixing_shared, ask one by one
5. Bot checks per-track title
   • if missing     → state: fixing_track_title, ask one by one
6. Bot embeds metadata, moves files to MUSIC_LIBRARY_PATH/<album_artist>/<album>/
7. Done — back to main menu

Note: Telegram's Bot API only exposes title, performer, and thumbnail on the
Audio object. album, track_number, year, and full cover art are only available
after downloading the file and reading its ID3 tags.
"""

import logging
import os
import shutil
import tempfile
from typing import Optional

from aiogram import Bot, F, Router
from aiogram.enums import ContentType
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message

from backend.bot.keyboards import album_collect_menu, main_menu, BTN_ALBUM_DONE
from yt_sc_fetch.audio import embed_metadata
from yt_sc_fetch.utils import safe_name

router = Router()
logger = logging.getLogger(__name__)

MUSIC_LIBRARY_PATH = os.environ.get("MUSIC_LIBRARY_PATH", "output")

SHARED_FIELDS = ("artist", "album_artist", "album")
SHARED_PROMPTS = {
    "artist":       "✏️ Enter the <b>artist</b> name:",
    "album_artist": "✏️ Enter the <b>album artist</b> name:",
    "album":        "✏️ Enter the <b>album</b> name:",
}


# ---------------------------------------------------------------------------
# States
# ---------------------------------------------------------------------------

class AlbumStates(StatesGroup):
    collecting_files   = State()
    fixing_shared      = State()
    fixing_track_title = State()
    processing         = State()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _download_file(bot: Bot, file_id: str, dest_path: str) -> None:
    file = await bot.get_file(file_id)
    await bot.download_file(file.file_path, dest_path)


def _read_id3(path: str) -> dict:
    """
    Read ID3 tags from a local file via mutagen.
    Returns a dict with: title, artist, album_artist, album,
    release_year, track_number, cover_art (bytes | None).
    """
    try:
        from mutagen.id3 import ID3
    except ImportError:
        return {}

    try:
        tags = ID3(path)
    except Exception:
        return {}

    def _text(key: str) -> str:
        frame = tags.get(key)
        return str(frame.text[0]).strip() if frame and frame.text else ""

    cover_art: Optional[bytes] = None
    apic_keys = [k for k in tags.keys() if k.startswith("APIC")]
    if apic_keys:
        cover_art = tags[apic_keys[0]].data

    track_number: Optional[int] = None
    trck = tags.get("TRCK")
    if trck and trck.text:
        try:
            track_number = int(str(trck.text[0]).split("/")[0])
        except ValueError:
            pass

    return dict(
        title        = _text("TIT2"),
        artist       = _text("TPE1"),
        album_artist = _text("TPE2"),
        album        = _text("TALB"),
        release_year = _text("TDRC"),
        track_number = track_number,
        cover_art    = cover_art,
    )


def _save_cover(cover_bytes: bytes, tmpdir: str) -> str:
    path = os.path.join(tmpdir, "cover.jpg")
    with open(path, "wb") as f:
        f.write(cover_bytes)
    return path


def _next_missing_shared(shared: dict) -> Optional[str]:
    for f in SHARED_FIELDS:
        if not shared.get(f):
            return f
    return None


def _next_title_missing(tracks: list[dict]) -> Optional[int]:
    for i, t in enumerate(tracks):
        if not t.get("title"):
            return i
    return None


# ---------------------------------------------------------------------------
# Step 1 — start collecting
# ---------------------------------------------------------------------------

@router.message(F.text == "Add Album 🎶")
async def start_album(message: Message, state: FSMContext) -> None:
    await state.set_state(AlbumStates.collecting_files)
    await state.update_data(tracks=[], shared={})
    await message.answer(
        "🎶 Send me the audio files one by one.\n"
        "When you're done, press <b>Album is ready ✅</b>.",
        parse_mode="HTML",
        reply_markup=album_collect_menu,
    )


# ---------------------------------------------------------------------------
# Step 2 — collect file references (no download yet)
# ---------------------------------------------------------------------------

@router.message(AlbumStates.collecting_files, F.content_type == ContentType.AUDIO)
async def collect_file(message: Message, state: FSMContext, bot: Bot) -> None:
    audio  = message.audio
    print(audio)
    data   = await state.get_data()
    tracks: list[dict] = data.get("tracks", [])

    tracks.append({
        "file_id":           audio.file_id,
        "file_name":         audio.file_name or f"track_{len(tracks) + 1}.mp3",
        "message_id":        message.message_id,
        # Telegram-visible fields — may be empty; full tags come after download
        "tg_title":          audio.title or "",
        "tg_performer":      audio.performer or "",
        "tg_thumbnail_id":   audio.thumbnail.file_id if audio.thumbnail else None,
    })

    logger.info(
        "Collected audio [%d]: file_name=%r tg_title=%r tg_performer=%r "
        "duration=%ds has_thumbnail=%s",
        len(tracks),
        audio.file_name,
        audio.title,
        audio.performer,
        audio.duration,
        audio.thumbnail is not None,
    )


# ---------------------------------------------------------------------------
# Step 3 — download all files and read full ID3 tags
# ---------------------------------------------------------------------------

@router.message(AlbumStates.collecting_files, F.text == BTN_ALBUM_DONE)
async def album_ready(message: Message, state: FSMContext, bot: Bot) -> None:
    data   = await state.get_data()
    tracks: list[dict] = data.get("tracks", [])

    if not tracks:
        await message.answer("⚠️ You haven't sent any files yet.")
        return

    status_msg = await message.answer(
        f"⏳ Downloading {len(tracks)} file(s) and reading metadata…",
        reply_markup=main_menu,
    )

    tmpdir = tempfile.mkdtemp(prefix="album_")
    enriched: list[dict] = []
    shared: dict = {}

    for i, t in enumerate(tracks, 1):
        ext        = os.path.splitext(t["file_name"])[1] or ".mp3"
        local_path = os.path.join(tmpdir, f"{i:02d}{ext}")

        try:
            await _download_file(bot, t["file_id"], local_path)
        except Exception as exc:
            await message.answer(f"⚠️ Could not download '{t['file_name']}': {exc}")
            shutil.rmtree(tmpdir, ignore_errors=True)
            await state.clear()
            return

        id3 = _read_id3(local_path)

        logger.info(
            "ID3 tags for track %d (%r): title=%r artist=%r album_artist=%r "
            "album=%r year=%r track_number=%r cover_art=%s",
            i,
            t["file_name"],
            id3.get("title"),
            id3.get("artist"),
            id3.get("album_artist"),
            id3.get("album"),
            id3.get("release_year"),
            id3.get("track_number"),
            f"{len(id3['cover_art'])} bytes" if id3.get("cover_art") else "None",
        )

        enriched.append({
            **t,
            "local_path":   local_path,
            "title":        id3.get("title") or t["tg_title"],
            "track_number": id3.get("track_number") or i,
            "release_year": id3.get("release_year") or "",
        })

        # Initialise shared fields from the first track
        if i == 1:
            artist       = id3.get("artist") or t["tg_performer"]
            album_artist = id3.get("album_artist") or artist
            cover_art    = id3.get("cover_art")
            shared = {
                "artist":        artist,
                "album_artist":  album_artist,
                "album":         id3.get("album") or "",
                "release_year":  id3.get("release_year") or "",
                "cover_art_path": _save_cover(cover_art, tmpdir) if cover_art else None,
            }
            logger.info(
                "Shared fields from first track: artist=%r album_artist=%r "
                "album=%r year=%r cover_art_path=%r",
                shared["artist"],
                shared["album_artist"],
                shared["album"],
                shared["release_year"],
                shared["cover_art_path"],
            )

    await bot.delete_message(message.chat.id, status_msg.message_id)
    await state.update_data(tracks=enriched, tmpdir=tmpdir, shared=shared)
    await _ask_next_shared(message, state)


# ---------------------------------------------------------------------------
# Step 4 — fix shared fields (artist / album_artist / album / cover_art)
# ---------------------------------------------------------------------------

async def _ask_next_shared(message: Message, state: FSMContext) -> None:
    data   = await state.get_data()
    shared = data.get("shared", {})
    nxt    = _next_missing_shared(shared)

    if nxt:
        await state.set_state(AlbumStates.fixing_shared)
        await state.update_data(_fixing_shared_field=nxt)
        await message.answer(SHARED_PROMPTS[nxt], parse_mode="HTML")
        return

    if not shared.get("cover_art_path"):
        await state.set_state(AlbumStates.fixing_shared)
        await state.update_data(_fixing_shared_field="cover_art")
        await message.answer(
            "🖼 No cover art found. Send a cover image or type <b>skip</b>.",
            parse_mode="HTML",
        )
        return

    await _ask_next_title(message, state)


@router.message(AlbumStates.fixing_shared, F.text)
async def receive_shared_text(message: Message, state: FSMContext) -> None:
    data   = await state.get_data()
    field  = data.get("_fixing_shared_field")
    shared = dict(data.get("shared", {}))

    if field == "cover_art":
        shared["cover_art_path"] = None
        await state.update_data(shared=shared)
        await _ask_next_title(message, state)
        return

    if field:
        shared[field] = message.text.strip()
        await state.update_data(shared=shared)

    await _ask_next_shared(message, state)


@router.message(AlbumStates.fixing_shared, F.photo | F.document)
async def receive_shared_cover(message: Message, state: FSMContext, bot: Bot) -> None:
    data = await state.get_data()
    if data.get("_fixing_shared_field") != "cover_art":
        return

    tmpdir  = data.get("tmpdir", tempfile.gettempdir())
    file_id = message.photo[-1].file_id if message.photo else message.document.file_id

    try:
        raw_path = os.path.join(tmpdir, "cover_raw")
        await _download_file(bot, file_id, raw_path)
        with open(raw_path, "rb") as f:
            cover_art_path = _save_cover(f.read(), tmpdir)
    except Exception as exc:
        await message.answer(f"⚠️ Could not save cover: {exc}")
        return

    shared = dict(data.get("shared", {}))
    shared["cover_art_path"] = cover_art_path
    await state.update_data(shared=shared)
    await _ask_next_title(message, state)


# ---------------------------------------------------------------------------
# Step 5 — fix per-track titles
# ---------------------------------------------------------------------------

async def _ask_next_title(message: Message, state: FSMContext) -> None:
    data   = await state.get_data()
    tracks = data.get("tracks", [])
    idx    = _next_title_missing(tracks)

    if idx is not None:
        await state.set_state(AlbumStates.fixing_track_title)
        await state.update_data(_fixing_title_idx=idx)
        t = tracks[idx]
        await message.answer(
            f"✏️ Track {idx + 1} (<code>{t['file_name']}</code>) has no title.\n"
            "Please enter its title:",
            parse_mode="HTML",
        )
        return

    await _process_album(message, state)


@router.message(AlbumStates.fixing_track_title, F.text)
async def receive_track_title(message: Message, state: FSMContext) -> None:
    data   = await state.get_data()
    idx    = data.get("_fixing_title_idx", 0)
    tracks = [dict(t) for t in data.get("tracks", [])]
    tracks[idx]["title"] = message.text.strip()
    await state.update_data(tracks=tracks)
    await _ask_next_title(message, state)


# ---------------------------------------------------------------------------
# Step 6 — embed metadata and save files
# ---------------------------------------------------------------------------

async def _process_album(message: Message, state: FSMContext) -> None:
    await state.set_state(AlbumStates.processing)
    data   = await state.get_data()
    tracks = data.get("tracks", [])
    shared = data.get("shared", {})
    tmpdir = data.get("tmpdir", "")

    cover_art: Optional[bytes] = None
    cover_path = shared.get("cover_art_path")
    if cover_path and os.path.exists(cover_path):
        with open(cover_path, "rb") as f:
            cover_art = f.read()

    out_dir = os.path.join(
        MUSIC_LIBRARY_PATH,
        safe_name(shared["album_artist"]),
        safe_name(shared["album"]),
    )
    os.makedirs(out_dir, exist_ok=True)

    failed = []
    for i, t in enumerate(tracks, 1):
        track_num = t.get("track_number") or i
        meta = {
            "artist":       shared["artist"],
            "album_artist": shared["album_artist"],
            "album":        shared["album"],
            "track":        t["title"],
            "track_number": track_num,
            "release_year": t.get("release_year") or shared.get("release_year") or "0000",
            "tags":         [],
        }
        filename = safe_name(f"{track_num:02d} {t['title']}") + ".mp3"
        dest     = os.path.join(out_dir, filename)
        try:
            embed_metadata(t["local_path"], meta, cover_art)
            shutil.move(t["local_path"], dest)
        except Exception as exc:
            failed.append(f"{t['file_name']}: {exc}")

    shutil.rmtree(tmpdir, ignore_errors=True)
    await state.clear()

    if failed:
        fail_lines = "\n".join(f"• {e}" for e in failed)
        await message.answer(
            f"⚠️ Finished with errors:\n{fail_lines}",
            reply_markup=main_menu,
        )
    else:
        await message.answer(
            f"✅ Album <b>{shared['album']}</b> saved — {len(tracks)} track(s).\n"
            f"📁 <code>{out_dir}</code>",
            parse_mode="HTML",
            reply_markup=main_menu,
        )