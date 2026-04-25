import { useState } from "react";
import ArtistsEditor from "./ArtistsEditor.jsx";
import YtTrackModal from "./YtTrackModal.jsx";
import { useLang } from "./LangContext.jsx";

const API = "/api";

const inputStyle = {
  flex: 1,
  padding: "10px 12px",
  border: "1px solid var(--border)",
  borderRadius: "var(--radius)",
  background: "var(--code-bg)",
  color: "var(--text)",
  fontSize: 13,
};

const fieldInputStyle = {
  padding: "8px 12px",
  border: "1px solid var(--border)",
  borderRadius: "var(--radius)",
  background: "var(--code-bg)",
  color: "var(--text)",
  fontSize: 13,
};

const labelStyle = {
  fontSize: 11, fontWeight: 600, color: "var(--text)",
  textTransform: "uppercase", letterSpacing: "0.07em",
};

// ── Latency warning ───────────────────────────────────────────────────────────

function LatencyWarning({ t }) {
  return (
    <div style={{
      display: "flex", gap: 10, padding: "10px 14px",
      borderRadius: "var(--radius)",
      border: "1px solid var(--accent-border)",
      background: "var(--accent-bg)",
      fontSize: 12, color: "var(--text)", lineHeight: 1.5,
    }}>
      <span style={{ flexShrink: 0, color: "var(--accent)", fontWeight: 600 }}>⏳</span>
      <span>{t("ytLatencyWarning")}</span>
    </div>
  );
}

// ── Playlist mode: per-track row ──────────────────────────────────────────────

function TrackRow({ track, onOpenModal, onChange, t }) {
  const matched = track.in_navidrome;
  return (
    <div style={{
      display: "flex", alignItems: "center", gap: 10,
      padding: "10px 12px", borderRadius: "var(--radius)",
      border: "1px solid var(--border)",
      background: track.skip ? "transparent" : matched ? "transparent" : "rgba(220,50,50,0.04)",
      opacity: track.skip ? 0.38 : 1,
      transition: "opacity 0.15s",
    }}>
      <span style={{
        flexShrink: 0, fontSize: 13, fontWeight: 600,
        color: matched ? "var(--accent)" : "var(--danger)",
        width: 14, textAlign: "center",
      }}>
        {matched ? "✓" : "✕"}
      </span>
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{
          fontSize: 13, fontWeight: 500, color: "var(--text-h)",
          overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap",
        }}>
          {track.title}
        </div>
        <div style={{
          fontSize: 12, color: "var(--text)", opacity: 0.55,
          overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap",
        }}>
          {(track.artists && track.artists.length) ? track.artists.join(", ") : "—"}
          {track.album ? ` · ${track.album}` : ""}
        </div>
      </div>
      {!matched && (
        <button
          onClick={onOpenModal}
          disabled={track.skip}
          style={{ flexShrink: 0, fontSize: 11, padding: "3px 8px", opacity: track.skip ? 0.3 : 0.65 }}
        >
          {t("edit")}
        </button>
      )}
      {!matched && (
        <button
          onClick={() => onChange({ skip: !track.skip })}
          style={{ flexShrink: 0, fontSize: 11, padding: "3px 8px", opacity: 0.45 }}
        >
          {track.skip ? t("ytUnskip") : t("ytSkip")}
        </button>
      )}
    </div>
  );
}

// ── Album mode: read-only track row ──────────────────────────────────────────

function AlbumTrackRow({ track, index }) {
  return (
    <div style={{
      display: "flex", alignItems: "center", gap: 10,
      padding: "8px 12px", borderRadius: "var(--radius)",
      border: "1px solid var(--border)", fontSize: 12,
    }}>
      <span style={{ flexShrink: 0, color: "var(--text)", opacity: 0.35, width: 20, textAlign: "right" }}>
        {index}
      </span>
      <span style={{
        flex: 1, color: "var(--text-h)",
        overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap",
      }}>
        {track.title}
      </span>
      {track.in_navidrome && (
        <span style={{ flexShrink: 0, color: "var(--accent)", fontSize: 11 }}>✓</span>
      )}
    </div>
  );
}

// ── Single track editor ───────────────────────────────────────────────────────

function SingleTrackEditor({ track, onSubmit, onBack, t }) {
  const [title,    setTitle]    = useState(track.title || "");
  const [artists,  setArtists]  = useState(track.artists || []);
  const [album,    setAlbum]    = useState(track.album || "");
  const [year,     setYear]     = useState(track.release_year || "");
  const [coverB64, setCoverB64] = useState(track.cover_art_b64 || null);

  function handleCoverFile(e) {
    const file = e.target.files[0];
    if (!file) return;
    const reader = new FileReader();
    reader.onload = () => setCoverB64(reader.result.split(",")[1]);
    reader.readAsDataURL(file);
  }

  function handleSubmit() {
    onSubmit({
      ...track,
      title,
      artists,
      album_artists: artists,
      album,
      release_year: year,
      cover_art_b64: coverB64 || track.cover_art_b64 || null,
      skip: false,
    });
  }

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
      <div style={{ fontSize: 11, color: "var(--accent)", fontWeight: 600, textTransform: "uppercase", letterSpacing: "0.07em" }}>
        {t("ytSingleTrack")}
      </div>

      <label style={{ cursor: "pointer", alignSelf: "flex-start" }}>
        <div style={{
          width: 120, height: 120, borderRadius: "var(--radius)",
          border: "1px solid var(--border)", background: "var(--code-bg)",
          overflow: "hidden", display: "flex", alignItems: "center", justifyContent: "center",
        }}>
          {coverB64
            ? <img src={`data:image/jpeg;base64,${coverB64}`} style={{ width: "100%", height: "100%", objectFit: "cover" }} />
            : track.thumbnail
              ? <img src={track.thumbnail} style={{ width: "100%", height: "100%", objectFit: "cover" }} />
              : <span style={{ fontSize: 11, color: "var(--text)", opacity: 0.5 }}>cover</span>
          }
        </div>
        <input type="file" accept="image/*" style={{ display: "none" }} onChange={handleCoverFile} />
      </label>

      <div style={{ display: "flex", flexDirection: "column", gap: 5 }}>
        <label style={labelStyle}>{t("trackLabel")}<span style={{ color: "var(--danger)", marginLeft: 2 }}>*</span></label>
        <input
          autoFocus value={title} onChange={(e) => setTitle(e.target.value)}
          style={{ ...fieldInputStyle, borderColor: !title.trim() ? "var(--danger)" : undefined }}
        />
      </div>

      <div style={{ display: "flex", flexDirection: "column", gap: 5 }}>
        <label style={labelStyle}>{t("artistsLabel")}<span style={{ color: "var(--danger)", marginLeft: 2 }}>*</span></label>
        <ArtistsEditor value={artists} onChange={setArtists} placeholder={t("artistsPlaceholder")} />
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "1fr 80px", gap: 10 }}>
        <div style={{ display: "flex", flexDirection: "column", gap: 5 }}>
          <label style={labelStyle}>{t("albumLabel")}</label>
          <input value={album} onChange={(e) => setAlbum(e.target.value)} placeholder="optional" style={fieldInputStyle} />
        </div>
        <div style={{ display: "flex", flexDirection: "column", gap: 5 }}>
          <label style={labelStyle}>{t("yearLabel")}</label>
          <input value={year} onChange={(e) => setYear(e.target.value)} style={fieldInputStyle} />
        </div>
      </div>

      <div style={{ display: "flex", gap: 10, paddingTop: 4 }}>
        <button onClick={onBack} style={{ opacity: 0.6 }}>{t("back")}</button>
        <button
          className="primary"
          disabled={!title.trim() || !artists.length}
          onClick={handleSubmit}
          style={{ flex: 1 }}
        >
          {t("ytAddToQueue")}
        </button>
      </div>
    </div>
  );
}

// ── Main component ────────────────────────────────────────────────────────────

export default function MediaImport({ onBack, onImport }) {
  const { t } = useLang();

  const [url,          setUrl]          = useState("");
  const [username,     setUsername]     = useState("");
  const [scanning,     setScanning]     = useState(false);
  const [scanResult,   setScanResult]   = useState(null);
  const [tracks,       setTracks]       = useState([]);
  const [singleTrack,  setSingleTrack]  = useState(null);
  const [error,        setError]        = useState(null);
  const [modalIdx,     setModalIdx]     = useState(null);
  const [downloadMode, setDownloadMode] = useState("playlist");

  // Album mode shared metadata
  const [albumArtist, setAlbumArtist] = useState("");
  const [albumTitle,  setAlbumTitle]  = useState("");
  const [albumYear,   setAlbumYear]   = useState("");
  const [albumCover,  setAlbumCover]  = useState(null);

  // ── scan ──────────────────────────────────────────────────────────────────

  async function handleScan() {
    const trimmed = url.trim();
    if (!trimmed) return;
    setScanning(true);
    setError(null);
    setScanResult(null);
    setTracks([]);
    setSingleTrack(null);
    setModalIdx(null);
    setDownloadMode("playlist");

    try {
      const res = await fetch(`${API}/scan`, {
        method:  "POST",
        headers: { "Content-Type": "application/json" },
        body:    JSON.stringify({ url: trimmed }),
      });
      if (!res.ok) throw new Error(await res.text());
      const data = await res.json();

      if (data.type === "single" || data.tracks.length === 1) {
        setSingleTrack(data.tracks[0]);
        setScanResult(data);
      } else {
        setScanResult(data);
        setTracks(data.tracks.map(tr => ({ ...tr, skip: false })));
        const first = data.tracks[0];
        setAlbumTitle(data.playlist_name || "");
        setAlbumArtist(
          (first.album_artists && first.album_artists[0]) ||
          (first.artists && first.artists[0]) || ""
        );
        setAlbumYear(first.release_year || "");
        setAlbumCover(first.cover_art_b64 || null);
      }
    } catch (e) {
      setError(e.message);
    } finally {
      setScanning(false);
    }
  }

  // ── track editing ─────────────────────────────────────────────────────────

  function updateTrack(idx, changes) {
    setTracks(prev => prev.map((tr, i) => i === idx ? { ...tr, ...changes } : tr));
  }

  function handleAlbumCoverFile(e) {
    const file = e.target.files[0];
    if (!file) return;
    const reader = new FileReader();
    reader.onload = () => setAlbumCover(reader.result.split(",")[1]);
    reader.readAsDataURL(file);
  }

  // ── import ────────────────────────────────────────────────────────────────

  function handlePlaylistImport() {
    onImport({
      source:        scanResult.source,
      playlist_name: scanResult.playlist_name,
      username:      username.trim(),
      download_mode: "playlist",
      tracks,
    });
  }

  function handleAlbumImport() {
    onImport({
      source:          scanResult.source,
      playlist_name:   scanResult.playlist_name,
      username:        username.trim(),
      download_mode:   "album",
      album_artist:    albumArtist.trim() || null,
      album_title:     albumTitle.trim() || null,
      release_year:    albumYear.trim() || null,
      album_cover_b64: albumCover || null,
      tracks,
    });
  }

  function handleSingleImport(trackMeta) {
    onImport({
      source:        scanResult.source,
      playlist_name: scanResult.playlist_name || "",
      download_mode: "playlist",
      tracks:        [{ ...trackMeta, skip: false }],
    });
  }

  // ── derived ───────────────────────────────────────────────────────────────

  const matched    = tracks.filter(tr => tr.in_navidrome).length;
  const toDownload = tracks.filter(tr => !tr.in_navidrome && !tr.skip).length;

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 20 }}>

      <LatencyWarning t={t} />

      {/* URL input */}
      <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
        <label style={{
          fontSize: 11, color: "var(--text)", opacity: 0.55,
          textTransform: "uppercase", letterSpacing: "0.07em",
        }}>
          {t("importUrl")}
        </label>
        <div style={{ display: "flex", gap: 8 }}>
          <input
            type="text"
            value={url}
            onChange={e => setUrl(e.target.value)}
            onKeyDown={e => e.key === "Enter" && !scanning && handleScan()}
            placeholder={t("importUrlPlaceholder")}
            style={inputStyle}
          />
          <button onClick={handleScan} disabled={scanning || !url.trim()} style={{ flexShrink: 0 }}>
            {scanning ? t("ytScanning") : t("ytScan")}
          </button>
        </div>
        {error && (
          <p style={{ margin: 0, color: "var(--danger)", fontSize: 13 }}>{error}</p>
        )}
      </div>

      {/* Single track editor */}
      {singleTrack && (
        <SingleTrackEditor
          track={singleTrack}
          onSubmit={handleSingleImport}
          onBack={() => setSingleTrack(null)}
          t={t}
        />
      )}

      {/* Multi-track results */}
      {scanResult && tracks.length > 0 && (
        <>
          {/* Playlist header */}
          <div style={{
            display: "flex", alignItems: "baseline", gap: 10,
            paddingBottom: 12, borderBottom: "1px solid var(--border)",
          }}>
            <span style={{ fontSize: 15, fontWeight: 600, color: "var(--text-h)" }}>
              {scanResult.playlist_name}
            </span>
            <span style={{ fontSize: 12, color: "var(--text)", opacity: 0.5 }}>
              {t("ytTracksFound", tracks.length, matched)}
            </span>
          </div>

          {/* Mode toggle */}
          <div style={{ display: "flex", gap: 6 }}>
            {["playlist", "album"].map((mode) => (
              <button
                key={mode}
                onClick={() => setDownloadMode(mode)}
                style={{
                  padding: "5px 14px", borderRadius: "var(--radius)",
                  border: "1px solid",
                  borderColor: downloadMode === mode ? "var(--accent)" : "var(--border)",
                  background: downloadMode === mode ? "var(--accent-bg)" : "transparent",
                  color: downloadMode === mode ? "var(--accent)" : "var(--text)",
                  fontSize: 12, fontWeight: downloadMode === mode ? 600 : 400,
                  cursor: "pointer",
                }}
              >
                {t(mode === "playlist" ? "importModePlaylist" : "importModeAlbum")}
              </button>
            ))}
          </div>

          {/* Playlist mode: per-track editing */}
          {downloadMode === "playlist" && (
            <div style={{ display: "flex", flexDirection: "column", gap: 5 }}>
              {tracks.map((track, idx) => (
                <TrackRow
                  key={track.source_id}
                  track={track}
                  onOpenModal={() => setModalIdx(idx)}
                  onChange={changes => updateTrack(idx, changes)}
                  t={t}
                />
              ))}
            </div>
          )}

          {/* Album mode: shared metadata form + read-only track list */}
          {downloadMode === "album" && (
            <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
              {/* Cover art picker */}
              <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
                <label style={{ ...labelStyle, cursor: "pointer", alignSelf: "flex-start" }}>
                  <div style={{
                    width: 120, height: 120, borderRadius: "var(--radius)",
                    border: "1px solid var(--border)", background: "var(--code-bg)",
                    overflow: "hidden", display: "flex", alignItems: "center", justifyContent: "center",
                  }}>
                    {albumCover
                      ? <img src={`data:image/jpeg;base64,${albumCover}`} style={{ width: "100%", height: "100%", objectFit: "cover" }} />
                      : tracks[0]?.thumbnail
                        ? <img src={tracks[0].thumbnail} style={{ width: "100%", height: "100%", objectFit: "cover" }} />
                        : <span style={{ fontSize: 11, color: "var(--text)", opacity: 0.5 }}>cover</span>
                    }
                  </div>
                  <input type="file" accept="image/*" style={{ display: "none" }} onChange={handleAlbumCoverFile} />
                </label>
                <span style={{ fontSize: 11, color: "var(--text)", opacity: 0.4 }}>
                  {t("importAlbumCoverHint")}
                </span>
              </div>

              {/* Album artist */}
              <div style={{ display: "flex", flexDirection: "column", gap: 5 }}>
                <label style={labelStyle}>{t("importAlbumArtist")}</label>
                <input
                  value={albumArtist}
                  onChange={(e) => setAlbumArtist(e.target.value)}
                  style={fieldInputStyle}
                />
              </div>

              {/* Album title + Year */}
              <div style={{ display: "grid", gridTemplateColumns: "1fr 80px", gap: 10 }}>
                <div style={{ display: "flex", flexDirection: "column", gap: 5 }}>
                  <label style={labelStyle}>{t("albumLabel")}</label>
                  <input
                    value={albumTitle}
                    onChange={(e) => setAlbumTitle(e.target.value)}
                    style={fieldInputStyle}
                  />
                </div>
                <div style={{ display: "flex", flexDirection: "column", gap: 5 }}>
                  <label style={labelStyle}>{t("yearLabel")}</label>
                  <input
                    value={albumYear}
                    onChange={(e) => setAlbumYear(e.target.value)}
                    style={fieldInputStyle}
                  />
                </div>
              </div>

              {/* Track list (read-only) */}
              <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
                {tracks.map((track, idx) => (
                  <AlbumTrackRow key={track.source_id} track={track} index={idx + 1} />
                ))}
              </div>
            </div>
          )}

          {/* Username */}
          <input
            type="text"
            value={username}
            onChange={e => setUsername(e.target.value)}
            placeholder={t("ytOwnerUsername")}
            style={{ ...inputStyle, fontSize: 12, opacity: 0.8 }}
          />

          {/* Action bar */}
          <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
            {downloadMode === "album" ? (
              <button
                onClick={handleAlbumImport}
                style={{ background: "var(--accent)", color: "#fff", border: "none", fontWeight: 500 }}
              >
                {t("ytImportBtn", tracks.filter(tr => !tr.in_navidrome).length)}
              </button>
            ) : toDownload > 0 ? (
              <button
                onClick={handlePlaylistImport}
                style={{ background: "var(--accent)", color: "#fff", border: "none", fontWeight: 500 }}
              >
                {t("ytImportBtn", toDownload)}
              </button>
            ) : (
              <span style={{ fontSize: 13, color: "var(--accent)" }}>
                {t("ytAllMatched")}
              </span>
            )}
          </div>
        </>
      )}

      {/* Back button */}
      {!singleTrack && (
        <div>
          <button onClick={onBack} style={{ fontSize: 12, opacity: 0.6 }}>{t("back")}</button>
        </div>
      )}

      {/* Track edit modal (playlist mode) */}
      {modalIdx !== null && tracks[modalIdx] && (
        <YtTrackModal
          track={tracks[modalIdx]}
          onSave={(updated) => {
            updateTrack(modalIdx, updated);
            setModalIdx(null);
          }}
          onClose={() => setModalIdx(null)}
        />
      )}
    </div>
  );
}
