from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel


# ---------------------------------------------------------------------------
# Job status
# ---------------------------------------------------------------------------


class JobStatus(BaseModel):
    job_id: str
    status: Literal["queued", "in_progress", "complete", "not_found", "failed"]
    result: Any | None = None
    error: str | None = None


class TrackMeta(BaseModel):
    temp_path: str = ""
    file_name: str
    title: str
    artist: str
    album_artist: str
    album: str
    release_year: str
    track_number: int | None = None
    cover_art_b64: str | None = None
    sc_url: str | None = None
    duration: int | None = None
    codec: str | None = None
    bitrate: int | None = None  # kbps
    # optional per-track tags
    lyrics: str | None = None  # USLT
    composer: str | None = None  # TCOM
    language: str | None = None  # TLAN


class ProcessRequest(BaseModel):
    tracks: list[TrackMeta]
    artist: str
    album_artist: str
    album: str
    release_year: str
    is_single: bool = False
    cover_art_b64: str | None = None
    # optional shared tags
    publisher: str | None = None  # TPUB


class ScProcessRequest(BaseModel):
    tracks: list[TrackMeta]
    artist: str
    album_artist: str
    album: str
    release_year: str
    is_single: bool = False
    cover_art_b64: str | None = None
    publisher: str | None = None


class AlbumMeta(BaseModel):
    zip_name: str
    tracks: list[TrackMeta]
    artist: str
    album_artist: str
    album: str
    release_year: str
    cover_art_b64: str | None = None
    publisher: str | None = None


class BulkProcessRequest(BaseModel):
    albums: list[ProcessRequest]


# ---------------------------------------------------------------------------
# YouTube playlist import
# ---------------------------------------------------------------------------


class YtTrackScan(BaseModel):
    """One track returned from /api/yt-scan."""
    video_id: str
    title: str
    artist: str
    duration: int | None = None
    thumbnail: str | None = None
    in_navidrome: bool
    navidrome_id: str | None = None


class YtPlaylistScan(BaseModel):
    """Full result of /api/yt-scan."""
    playlist_id: str
    playlist_name: str
    tracks: list[YtTrackScan]


class YtTrackImport(BaseModel):
    """One track submitted to /api/yt-import (user may have edited title/artist)."""
    video_id: str
    title: str
    artist: str
    duration: int | None = None
    in_navidrome: bool = False
    navidrome_id: str | None = None
    skip: bool = False  # user explicitly excluded this track


class YtImportRequest(BaseModel):
    """Request body for /api/yt-import."""
    playlist_name: str
    tracks: list[YtTrackImport]
