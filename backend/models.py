from pydantic import BaseModel


class TrackMeta(BaseModel):
    temp_path: str
    file_name: str
    title: str
    artist: str
    album_artist: str
    album: str
    release_year: str
    track_number: int
    cover_art_b64: str | None = None  # base64 for preview, None if absent


class ProcessRequest(BaseModel):
    tracks: list[TrackMeta]
    # shared fields — applied to every track
    artist: str
    album_artist: str
    album: str
    release_year: str
    cover_art_b64: str | None = None  # base64; None = keep per-track art or skip
