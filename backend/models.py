from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, model_validator


# ---------------------------------------------------------------------------
# Artist-list coercion
# ---------------------------------------------------------------------------

def _split_value(value: str) -> list[str]:
    """Split a delimited artist string using the same separators as fix_artists."""
    if not value:
        return []
    from fix_artists import split_artist

    parts = split_artist(value)
    if parts:
        return parts
    stripped = value.strip()
    return [stripped] if stripped else []


def _normalize_artists(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return _split_value(value)
    if isinstance(value, list):
        out: list[str] = []
        for x in value:
            s = str(x).strip()
            if s:
                out.append(s)
        return out
    return []


def _coerce_list_field(data: dict, primary: str, legacy: str) -> None:
    """Normalise *primary* and fold the legacy string field into it."""
    if primary in data:
        data[primary] = _normalize_artists(data[primary])
    if legacy in data:
        legacy_val = data.pop(legacy)
        if not data.get(primary):
            data[primary] = _normalize_artists(legacy_val)


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
    title: str = ""
    artists: list[str] = []
    album_artists: list[str] = []
    album: str = ""
    release_year: str = ""
    track_number: int | None = None
    cover_art_b64: str | None = None
    sc_url: str | None = None
    duration: int | None = None
    codec: str | None = None
    bitrate: int | None = None
    lyrics: str | None = None
    composer: str | None = None
    language: str | None = None

    @model_validator(mode="before")
    @classmethod
    def _coerce_legacy(cls, data):
        if not isinstance(data, dict):
            return data
        _coerce_list_field(data, "artists", "artist")
        _coerce_list_field(data, "album_artists", "album_artist")
        return data


class ProcessRequest(BaseModel):
    tracks: list[TrackMeta]
    artists: list[str] = []
    album_artists: list[str] = []
    album: str = ""
    release_year: str = ""
    is_single: bool = False
    cover_art_b64: str | None = None
    publisher: str | None = None

    @model_validator(mode="before")
    @classmethod
    def _coerce_legacy(cls, data):
        if not isinstance(data, dict):
            return data
        _coerce_list_field(data, "artists", "artist")
        _coerce_list_field(data, "album_artists", "album_artist")
        return data

    @model_validator(mode="after")
    def _default_album_artists(self):
        if not self.album_artists and self.artists:
            self.album_artists = list(self.artists)
        return self


class ScProcessRequest(BaseModel):
    tracks: list[TrackMeta]
    artists: list[str] = []
    album_artists: list[str] = []
    album: str = ""
    release_year: str = ""
    is_single: bool = False
    cover_art_b64: str | None = None
    publisher: str | None = None

    @model_validator(mode="before")
    @classmethod
    def _coerce_legacy(cls, data):
        if not isinstance(data, dict):
            return data
        _coerce_list_field(data, "artists", "artist")
        _coerce_list_field(data, "album_artists", "album_artist")
        return data

    @model_validator(mode="after")
    def _default_album_artists(self):
        if not self.album_artists and self.artists:
            self.album_artists = list(self.artists)
        return self


class AlbumMeta(BaseModel):
    zip_name: str
    tracks: list[TrackMeta]
    artists: list[str] = []
    album_artists: list[str] = []
    album: str = ""
    release_year: str = ""
    cover_art_b64: str | None = None
    publisher: str | None = None

    @model_validator(mode="before")
    @classmethod
    def _coerce_legacy(cls, data):
        if not isinstance(data, dict):
            return data
        _coerce_list_field(data, "artists", "artist")
        _coerce_list_field(data, "album_artists", "album_artist")
        return data


class BulkProcessRequest(BaseModel):
    albums: list[ProcessRequest]


# ---------------------------------------------------------------------------
# YouTube playlist import
# ---------------------------------------------------------------------------


class YtTrackScan(BaseModel):
    """One track returned from /api/yt-scan."""
    video_id: str
    title: str
    artists: list[str] = []
    duration: int | None = None
    thumbnail: str | None = None
    in_navidrome: bool
    navidrome_id: str | None = None

    @model_validator(mode="before")
    @classmethod
    def _coerce_legacy(cls, data):
        if not isinstance(data, dict):
            return data
        _coerce_list_field(data, "artists", "artist")
        return data


class YtPlaylistScan(BaseModel):
    """Full result of /api/yt-scan."""
    playlist_id: str
    playlist_name: str
    tracks: list[YtTrackScan]


class YtTrackImport(BaseModel):
    """One track submitted to /api/yt-import (user may have edited title/artist)."""
    video_id: str
    title: str
    artists: list[str] = []
    album_artists: list[str] = []
    album: str = ""
    release_year: str = ""
    thumbnail: str | None = None
    cover_art_b64: str | None = None
    duration: int | None = None
    in_navidrome: bool = False
    navidrome_id: str | None = None
    skip: bool = False  # user explicitly excluded this track

    @model_validator(mode="before")
    @classmethod
    def _coerce_legacy(cls, data):
        if not isinstance(data, dict):
            return data
        _coerce_list_field(data, "artists", "artist")
        _coerce_list_field(data, "album_artists", "album_artist")
        return data

    @model_validator(mode="after")
    def _default_album_artists(self):
        if not self.album_artists and self.artists:
            self.album_artists = list(self.artists)
        return self


class YtImportRequest(BaseModel):
    """Request body for /api/yt-import."""
    playlist_name: str
    tracks: list[YtTrackImport]
