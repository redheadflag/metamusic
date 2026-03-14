from pydantic import BaseModel


class TrackMeta(BaseModel):
    temp_path: str = ""  # empty for SC tracks (not uploaded yet)
    file_name: str
    title: str
    artist: str
    album_artist: str
    album: str
    release_year: str
    track_number: int | None = None
    cover_art_b64: str | None = None
    sc_url: str | None = None  # set for SoundCloud tracks


class ProcessRequest(BaseModel):
    tracks: list[TrackMeta]
    artist: str
    album_artist: str
    album: str
    release_year: str
    is_single: bool = False
    cover_art_b64: str | None = None


class ScProcessRequest(BaseModel):
    """Process SoundCloud tracks — download + embed metadata."""

    tracks: list[TrackMeta]
    artist: str
    album_artist: str
    album: str
    release_year: str
    is_single: bool = False
    cover_art_b64: str | None = None


class AlbumMeta(BaseModel):
    zip_name: str
    tracks: list[TrackMeta]
    artist: str
    album_artist: str
    album: str
    release_year: str
    cover_art_b64: str | None = None


class BulkProcessRequest(BaseModel):
    albums: list[ProcessRequest]
