import { useState } from "react";
import ArtistsEditor from "./ArtistsEditor.jsx";
import YtTrackModal from "./YtTrackModal.jsx";
import { useLang } from "./LangContext.jsx";

const API = "/api";

// ── helpers ───────────────────────────────────────────────────────────────────

function isSingleVideoUrl(url) {
  // matches watch?v=... but not when a playlist= param is also present
  return /[?&]v=/.test(url) && !/[?&]list=/.test(url);
}

function extractVideoId(url) {
  const m = url.match(/[?&]v=([^&]+)/);
  return m ? m[1] : null;
}

// ── Track row (playlist mode) ─────────────────────────────────────────────────

function TrackRow({ track, onOpenModal, onChange, t }) {
  const matched = track.in_navidrome;

  return (
    <div style={{
      display: "flex",
      alignItems: "center",
      gap: 10,
      padding: "10px 12px",
      borderRadius: "var(--radius)",
      border: "1px solid var(--border)",
      background: track.skip
        ? "transparent"
        : matched
          ? "transparent"
          : "rgba(220,50,50,0.04)",
      opacity: track.skip ? 0.38 : 1,
      transition: "opacity 0.15s",
    }}>

      {/* Status indicator */}
      <span style={{
        flexShrink: 0,
        fontSize: 13,
        fontWeight: 600,
        color: matched ? "var(--accent)" : "var(--danger)",
        width: 14,
        textAlign: "center",
      }}>
        {matched ? "✓" : "✕"}
      </span>

      {/* Track info */}
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{
          fontSize: 13,
          fontWeight: 500,
          color: "var(--text-h)",
          overflow: "hidden",
          textOverflow: "ellipsis",
          whiteSpace: "nowrap",
        }}>
          {track.title}
        </div>
        <div style={{
          fontSize: 12,
          color: "var(--text)",
          opacity: 0.55,
          overflow: "hidden",
          textOverflow: "ellipsis",
          whiteSpace: "nowrap",
        }}>
          {(track.artists && track.artists.length) ? track.artists.join(", ") : "—"}
          {track.album ? ` · ${track.album}` : ""}
        </div>
      </div>

      {/* Actions for unmatched tracks */}
      {!matched && (
        <button
          onClick={onOpenModal}
          disabled={track.skip}
          style={{
            flexShrink: 0,
            fontSize: 11,
            padding: "3px 8px",
            opacity: track.skip ? 0.3 : 0.65,
          }}
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

const inputStyle = {
  flex: 1,
  padding: "10px 12px",
  border: "1px solid var(--border)",
  borderRadius: "var(--radius)",
  background: "var(--code-bg)",
  color: "var(--text)",
  fontSize: 13,
};

// ── Latency warning banner ────────────────────────────────────────────────────

function LatencyWarning({ t }) {
  return (
    <div style={{
      display: "flex",
      gap: 10,
      padding: "10px 14px",
      borderRadius: "var(--radius)",
      border: "1px solid var(--accent-border)",
      background: "var(--accent-bg)",
      fontSize: 12,
      color: "var(--text)",
      lineHeight: 1.5,
    }}>
      <span style={{ flexShrink: 0, color: "var(--accent)", fontWeight: 600 }}>⏳</span>
      <span>{t("ytLatencyWarning")}</span>
    </div>
  );
}

// ── Single video editor ───────────────────────────────────────────────────────

const fieldInputStyle = {
  padding: "8px 12px",
  border: "1px solid var(--border)",
  borderRadius: "var(--radius)",
  background: "var(--code-bg)",
  color: "var(--text)",
  fontSize: 13,
};

function SingleVideoEditor({ videoMeta, onSubmit, onBack, t }) {
  const [title,    setTitle]    = useState(videoMeta.title || "");
  const [artists,  setArtists]  = useState(videoMeta.artists || []);
  const [album,    setAlbum]    = useState("");
  const [year,     setYear]     = useState("");
  const [coverB64, setCoverB64] = useState(null);

  function handleCoverFile(e) {
    const file = e.target.files[0];
    if (!file) return;
    const reader = new FileReader();
    reader.onload = () => setCoverB64(reader.result.split(",")[1]);
    reader.readAsDataURL(file);
  }

  const labelStyle = {
    fontSize: 11, fontWeight: 600, color: "var(--text)",
    textTransform: "uppercase", letterSpacing: "0.07em",
  };

  function handleSubmit() {
    onSubmit({
      video_id:      videoMeta.video_id,
      title,
      artists,
      album_artists: artists,
      album,
      release_year:  year,
      thumbnail:     videoMeta.thumbnail || null,
      cover_art_b64: coverB64 || null,
      duration:      videoMeta.duration || null,
      in_navidrome:  false,
      skip:          false,
    });
  }

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
      <div style={{
        fontSize: 11, color: "var(--accent)", fontWeight: 600,
        textTransform: "uppercase", letterSpacing: "0.07em",
      }}>
        {t("ytSingleTrack")}
      </div>

      {/* Cover art */}
      <label style={{ cursor: "pointer", alignSelf: "flex-start" }}>
        <div style={{
          width: 120, height: 120,
          borderRadius: "var(--radius)",
          border: "1px solid var(--border)",
          background: "var(--code-bg)",
          overflow: "hidden",
          display: "flex", alignItems: "center", justifyContent: "center",
        }}>
          {coverB64
            ? <img src={`data:image/jpeg;base64,${coverB64}`}
                   style={{ width: "100%", height: "100%", objectFit: "cover" }} />
            : videoMeta.thumbnail
              ? <img src={videoMeta.thumbnail}
                     style={{ width: "100%", height: "100%", objectFit: "cover" }} />
              : <span style={{ fontSize: 11, color: "var(--text)", opacity: 0.5 }}>cover</span>
          }
        </div>
        <input type="file" accept="image/*" style={{ display: "none" }} onChange={handleCoverFile} />
      </label>

      {/* Title */}
      <div style={{ display: "flex", flexDirection: "column", gap: 5 }}>
        <label style={labelStyle}>
          {t("trackLabel")}
          <span style={{ color: "var(--danger)", marginLeft: 2 }}>*</span>
        </label>
        <input
          autoFocus
          value={title}
          onChange={(e) => setTitle(e.target.value)}
          style={{ ...fieldInputStyle, borderColor: !title.trim() ? "var(--danger)" : undefined }}
        />
      </div>

      {/* Artists (also sets album_artists) */}
      <div style={{ display: "flex", flexDirection: "column", gap: 5 }}>
        <label style={labelStyle}>
          {t("artistsLabel")}
          <span style={{ color: "var(--danger)", marginLeft: 2 }}>*</span>
        </label>
        <ArtistsEditor
          value={artists}
          onChange={setArtists}
          placeholder={t("artistsPlaceholder")}
        />
      </div>

      {/* Album + Year */}
      <div style={{ display: "grid", gridTemplateColumns: "1fr 80px", gap: 10 }}>
        <div style={{ display: "flex", flexDirection: "column", gap: 5 }}>
          <label style={labelStyle}>{t("albumLabel")}</label>
          <input
            value={album}
            onChange={(e) => setAlbum(e.target.value)}
            placeholder="optional"
            style={fieldInputStyle}
          />
        </div>
        <div style={{ display: "flex", flexDirection: "column", gap: 5 }}>
          <label style={labelStyle}>{t("yearLabel")}</label>
          <input
            value={year}
            onChange={(e) => setYear(e.target.value)}
            style={fieldInputStyle}
          />
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

export default function PlaylistImport({ onBack, onImport }) {
  const { t } = useLang();

  const [url,         setUrl]         = useState("");
  const [scanning,    setScanning]    = useState(false);
  const [playlist,    setPlaylist]    = useState(null);   // YtPlaylistScan
  const [tracks,      setTracks]      = useState([]);
  const [singleMeta,  setSingleMeta]  = useState(null);   // single video metadata
  const [error,       setError]       = useState(null);
  const [modalIdx,    setModalIdx]    = useState(null);   // index of track being edited

  // ── scan / fetch ──────────────────────────────────────────────────────────

  async function handleScan() {
    const trimmed = url.trim();
    if (!trimmed) return;
    setScanning(true);
    setError(null);
    setPlaylist(null);
    setTracks([]);
    setSingleMeta(null);
    setModalIdx(null);

    try {
      if (isSingleVideoUrl(trimmed)) {
        // Try to pre-fill metadata from the backend; fall back to empty editor
        // if the server lacks YT cookies (bot detection) — user fills in manually.
        const videoId = extractVideoId(trimmed);
        try {
          const res = await fetch(`${API}/yt-fetch-video`, {
            method:  "POST",
            headers: { "Content-Type": "application/json" },
            body:    JSON.stringify({ url: trimmed }),
          });
          if (!res.ok) throw new Error(await res.text());
          const data = await res.json();
          setSingleMeta(data);
        } catch {
          // Couldn't fetch metadata — open editor with empty fields
          setSingleMeta({ video_id: videoId || trimmed, title: "", artists: [], duration: null, thumbnail: null });
        }
      } else {
        // Playlist — existing scan flow
        const res = await fetch(`${API}/yt-scan`, {
          method:  "POST",
          headers: { "Content-Type": "application/json" },
          body:    JSON.stringify({ url: trimmed }),
        });
        if (!res.ok) throw new Error(await res.text());
        const data = await res.json();
        setPlaylist(data);
        setTracks(data.tracks.map(t => ({ ...t, skip: false })));
      }
    } catch (e) {
      setError(e.message);
    } finally {
      setScanning(false);
    }
  }

  // ── track editing ─────────────────────────────────────────────────────────

  function updateTrack(idx, changes) {
    setTracks(prev => prev.map((t, i) => i === idx ? { ...t, ...changes } : t));
  }

  // ── import ────────────────────────────────────────────────────────────────

  function handlePlaylistImport() {
    onImport({
      playlist_name: playlist.playlist_name,
      tracks: tracks.map(t => ({
        video_id:     t.video_id,
        title:        t.title,
        artists:      t.artists || [],
        album_artists: t.album_artists || t.artists || [],
        album:        t.album || "",
        release_year: t.release_year || "",
        thumbnail:     t.thumbnail || null,
        cover_art_b64: t.cover_art_b64 || null,
        duration:      t.duration,
        in_navidrome:  t.in_navidrome,
        navidrome_id:  t.navidrome_id || null,
        skip:          t.skip,
      })),
    });
  }

  function handleSingleImport(trackMeta) {
    onImport({
      playlist_name: "",
      tracks: [{ ...trackMeta, in_navidrome: false, skip: false }],
    });
  }

  // ── derived ───────────────────────────────────────────────────────────────

  const matched    = tracks.filter(t => t.in_navidrome).length;
  const toDownload = tracks.filter(t => !t.in_navidrome && !t.skip).length;

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 20 }}>

      {/* Latency warning */}
      <LatencyWarning t={t} />

      {/* URL input */}
      <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
        <label style={{
          fontSize: 11,
          color: "var(--text)",
          opacity: 0.55,
          textTransform: "uppercase",
          letterSpacing: "0.07em",
        }}>
          {t("ytPlaylistUrl")}
        </label>
        <div style={{ display: "flex", gap: 8 }}>
          <input
            type="text"
            value={url}
            onChange={e => setUrl(e.target.value)}
            onKeyDown={e => e.key === "Enter" && !scanning && handleScan()}
            placeholder={t("ytUrlPlaceholder")}
            style={inputStyle}
          />
          <button
            onClick={handleScan}
            disabled={scanning || !url.trim()}
            style={{ flexShrink: 0 }}
          >
            {scanning ? t("ytScanning") : t("ytScan")}
          </button>
        </div>
        {error && (
          <p style={{ margin: 0, color: "var(--danger)", fontSize: 13 }}>{error}</p>
        )}
      </div>

      {/* Single video editor */}
      {singleMeta && (
        <SingleVideoEditor
          videoMeta={singleMeta}
          onSubmit={handleSingleImport}
          onBack={() => setSingleMeta(null)}
          t={t}
        />
      )}

      {/* Playlist results */}
      {playlist && tracks.length > 0 && (
        <>
          {/* Playlist header */}
          <div style={{
            display: "flex",
            alignItems: "baseline",
            gap: 10,
            paddingBottom: 12,
            borderBottom: "1px solid var(--border)",
          }}>
            <span style={{ fontSize: 15, fontWeight: 600, color: "var(--text-h)" }}>
              {playlist.playlist_name}
            </span>
            <span style={{ fontSize: 12, color: "var(--text)", opacity: 0.5 }}>
              {t("ytTracksFound", tracks.length, matched)}
            </span>
          </div>

          {/* Track list */}
          <div style={{ display: "flex", flexDirection: "column", gap: 5 }}>
            {tracks.map((track, idx) => (
              <TrackRow
                key={track.video_id}
                track={track}
                onOpenModal={() => setModalIdx(idx)}
                onChange={changes => updateTrack(idx, changes)}
                t={t}
              />
            ))}
          </div>

          {/* Action bar */}
          <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
            {toDownload > 0 ? (
              <button
                onClick={handlePlaylistImport}
                style={{
                  background: "var(--accent)",
                  color: "#fff",
                  border: "none",
                  fontWeight: 500,
                }}
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

      {/* Back */}
      {!singleMeta && (
        <div>
          <button onClick={onBack} style={{ fontSize: 12, opacity: 0.6 }}>
            {t("back")}
          </button>
        </div>
      )}

      {/* Track metadata modal */}
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
