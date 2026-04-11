import { useState } from "react";
import { useLang } from "./LangContext.jsx";

const API = "/api";

// ── Track row ─────────────────────────────────────────────────────────────────

function TrackRow({ track, isEditing, onEdit, onStopEdit, onChange, t }) {
  const matched = track.in_navidrome;

  return (
    <div style={{
      display: "flex",
      alignItems: "flex-start",
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
        marginTop: 3,
        fontSize: 13,
        fontWeight: 600,
        color: matched ? "var(--accent)" : "var(--danger)",
        width: 14,
        textAlign: "center",
      }}>
        {matched ? "✓" : "✕"}
      </span>

      {/* Track info / inline edit */}
      {isEditing && !matched ? (
        <div style={{ flex: 1, display: "flex", flexDirection: "column", gap: 6 }}>
          <input
            autoFocus
            value={track.title}
            onChange={e => onChange({ title: e.target.value })}
            placeholder={t("trackLabel")}
            style={inputStyle}
          />
          <input
            value={track.artist}
            onChange={e => onChange({ artist: e.target.value })}
            placeholder={t("artistLabel")}
            style={inputStyle}
          />
          <button onClick={onStopEdit} style={{ alignSelf: "flex-start", fontSize: 12 }}>
            {t("close")}
          </button>
        </div>
      ) : (
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
            {track.artist || "—"}
          </div>
        </div>
      )}

      {/* Action buttons (only for unmatched tracks) */}
      {!matched && !isEditing && (
        <button
          onClick={onEdit}
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
          style={{
            flexShrink: 0,
            fontSize: 11,
            padding: "3px 8px",
            opacity: 0.45,
          }}
        >
          {track.skip ? t("ytUnskip") : t("ytSkip")}
        </button>
      )}
    </div>
  );
}

const inputStyle = {
  padding: "5px 8px",
  border: "1px solid var(--border)",
  borderRadius: 4,
  background: "var(--code-bg)",
  color: "var(--text)",
  fontSize: 13,
  width: "100%",
  boxSizing: "border-box",
};

// ── Main component ────────────────────────────────────────────────────────────

export default function PlaylistImport({ onBack, onImport }) {
  const { t } = useLang();

  const [url,       setUrl]       = useState("");
  const [scanning,  setScanning]  = useState(false);
  const [playlist,  setPlaylist]  = useState(null);   // YtPlaylistScan
  const [tracks,    setTracks]    = useState([]);
  const [error,     setError]     = useState(null);
  const [editingIdx, setEditingIdx] = useState(null);

  // ── scan ──────────────────────────────────────────────────────────────────

  async function handleScan() {
    const trimmed = url.trim();
    if (!trimmed) return;
    setScanning(true);
    setError(null);
    setPlaylist(null);
    setTracks([]);
    setEditingIdx(null);

    try {
      const res = await fetch(`${API}/yt-scan`, {
        method:  "POST",
        headers: { "Content-Type": "application/json" },
        body:    JSON.stringify({ url: trimmed }),
      });
      if (!res.ok) throw new Error(await res.text());
      const data = await res.json();
      setPlaylist(data);
      setTracks(data.tracks.map(t => ({ ...t, skip: false })));
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

  function handleImport() {
    onImport({
      playlist_name: playlist.playlist_name,
      tracks: tracks.map(t => ({
        video_id:     t.video_id,
        title:        t.title,
        artist:       t.artist,
        duration:     t.duration,
        in_navidrome: t.in_navidrome,
        navidrome_id: t.navidrome_id || null,
        skip:         t.skip,
      })),
    });
  }

  // ── derived ───────────────────────────────────────────────────────────────

  const matched   = tracks.filter(t => t.in_navidrome).length;
  const toDownload = tracks.filter(t => !t.in_navidrome && !t.skip).length;

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 20 }}>

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
            style={{
              flex: 1,
              padding: "10px 12px",
              border: "1px solid var(--border)",
              borderRadius: "var(--radius)",
              background: "var(--code-bg)",
              color: "var(--text)",
              fontSize: 13,
            }}
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

      {/* Results */}
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
                isEditing={editingIdx === idx}
                onEdit={() => setEditingIdx(idx)}
                onStopEdit={() => setEditingIdx(null)}
                onChange={changes => updateTrack(idx, changes)}
                t={t}
              />
            ))}
          </div>

          {/* Action bar */}
          <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
            {toDownload > 0 ? (
              <button
                onClick={handleImport}
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
      <div>
        <button
          onClick={onBack}
          style={{ fontSize: 12, opacity: 0.6 }}
        >
          {t("back")}
        </button>
      </div>
    </div>
  );
}
