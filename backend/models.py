from pydantic import BaseModel


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
