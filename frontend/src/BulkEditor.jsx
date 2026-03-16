import { useState } from "react";
import { useLang } from "./LangContext.jsx";

const formatDuration = (seconds) => {
  if (seconds == null) return null;
  const m = Math.floor(seconds / 60);
  const s = String(seconds % 60).padStart(2, "0");
  return `${m}:${s}`;
};

const Field = ({ label, value, onChange, required }) => (
  <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
    <label style={{
      fontSize: 11, fontWeight: 600, color: "var(--text)",
      textTransform: "uppercase", letterSpacing: "0.07em",
    }}>
      {label}
      {required && <span style={{ color: "var(--danger)", marginLeft: 2 }}>*</span>}
    </label>
    <input value={value} onChange={(e) => onChange(e.target.value)} />
  </div>
);

// collapsed is now passed in as a prop and toggled via onToggle — no internal state.
function AlbumPanel({ albumMeta, index, collapsed, onToggle, onChange, onRemove }) {
  const { t } = useLang();

  const set = (key) => (v) => {
    onChange(index, {
      ...albumMeta,
      [key]: v,
      ...(key === "artist" ? { album_artist: v } : {}),
    });
  };

  function handleCoverFile(e) {
    const file = e.target.files[0];
    if (!file) return;
    const reader = new FileReader();
    reader.onload = () => onChange(index, { ...albumMeta, cover_art_b64: reader.result.split(",")[1] });
    reader.readAsDataURL(file);
  }

  function setTitle(trackIdx, v) {
    const tracks = albumMeta.tracks.map((t, i) => i === trackIdx ? { ...t, title: v } : t);
    onChange(index, { ...albumMeta, tracks });
  }

  function setTrackNumber(trackIdx, v) {
    const tracks = albumMeta.tracks.map((t, i) => i === trackIdx ? { ...t, track_number: v } : t);
    onChange(index, { ...albumMeta, tracks });
  }

  const invalid = !albumMeta.artist || !albumMeta.album || albumMeta.tracks.some((t) => !t.title.trim());

  return (
    <div style={{
      border: `1px solid ${invalid ? "var(--danger)" : "var(--border)"}`,
      borderRadius: "var(--radius)",
      overflow: "hidden",
    }}>
      {/* Header */}
      <div
        onClick={() => onToggle(index)}
        style={{
          display: "flex", alignItems: "center", justifyContent: "space-between",
          padding: "12px 16px",
          background: "var(--code-bg)",
          cursor: "pointer",
          userSelect: "none",
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
          {albumMeta.cover_art_b64 && (
            <img
              src={`data:image/jpeg;base64,${albumMeta.cover_art_b64}`}
              style={{ width: 32, height: 32, borderRadius: 4, objectFit: "cover", flexShrink: 0 }}
            />
          )}
          <div>
            <div style={{ fontSize: 13, fontWeight: 500, color: "var(--text-h)" }}>
              {albumMeta.artist || <span style={{ opacity: 0.4 }}>{t("noArtist")}</span>}
              {albumMeta.album ? ` — ${albumMeta.album}` : ""}
            </div>
            <div style={{ fontSize: 11, color: "var(--text)", opacity: 0.5 }}>
              {albumMeta.zip_name} · {t("trackCount", albumMeta.tracks.length)}
            </div>
          </div>
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <button
            onClick={(e) => { e.stopPropagation(); onRemove(index); }}
            style={{ fontSize: 11, padding: "2px 8px", color: "var(--danger)", borderColor: "var(--danger)", opacity: 0.7 }}
          >
            {t("removeAlbum")}
          </button>
          <span style={{ fontSize: 12, color: "var(--text)", opacity: 0.4 }}>
            {collapsed ? "▶" : "▼"}
          </span>
        </div>
      </div>

      {/* Body */}
      {!collapsed && (
        <div style={{ padding: "20px 20px 24px", display: "flex", flexDirection: "column", gap: 20 }}>

          {/* Cover + fields */}
          <div style={{ display: "flex", gap: 16, alignItems: "flex-start" }}>
            <label style={{ cursor: "pointer", flexShrink: 0 }}>
              <div style={{
                width: 72, height: 72, borderRadius: 8,
                border: "1px solid var(--border)", background: "var(--bg)",
                overflow: "hidden", display: "flex", alignItems: "center", justifyContent: "center",
              }}>
                {albumMeta.cover_art_b64
                  ? <img src={`data:image/jpeg;base64,${albumMeta.cover_art_b64}`}
                         style={{ width: "100%", height: "100%", objectFit: "cover" }} />
                  : <span style={{ fontSize: 10, color: "var(--text)", opacity: 0.4 }}>cover</span>
                }
              </div>
              <input type="file" accept="image/*" style={{ display: "none" }} onChange={handleCoverFile} />
            </label>

            <div style={{ flex: 1, display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>
              <div style={{ gridColumn: "1 / -1" }}>
                <Field label={t("artistLabel")} value={albumMeta.artist} onChange={set("artist")} required />
              </div>
              <Field label={t("albumLabel")}  value={albumMeta.album}        onChange={set("album")}        required />
              <Field label={t("yearLabel")}   value={albumMeta.release_year} onChange={set("release_year")} />
            </div>
          </div>

          {/* Track list */}
          <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
            <span style={{
              fontSize: 11, fontWeight: 600, color: "var(--text)",
              textTransform: "uppercase", letterSpacing: "0.07em",
            }}>
              {t("tracksLabel")}
            </span>
            {albumMeta.tracks.map((tr, i) => (
              <div key={tr.temp_path} style={{ display: "flex", alignItems: "center", gap: 10 }}>
                <input
                  type="number"
                  min={1}
                  value={tr.track_number ?? i + 1}
                  onChange={(e) => {
                    const v = parseInt(e.target.value, 10);
                    if (!isNaN(v) && v > 0) setTrackNumber(i, v);
                  }}
                  style={{ width: 64, textAlign: "center", flexShrink: 0 }}
                />
                <input
                  value={tr.title}
                  placeholder={t("titleRequired")}
                  onChange={(e) => setTitle(i, e.target.value)}
                  style={{
                    flex: 1,
                    borderColor: !tr.title.trim() ? "var(--danger)" : undefined,
                  }}
                />
                {formatDuration(tr.duration) && (
                  <span style={{
                    fontSize: 11, color: "var(--text)", opacity: 0.4,
                    whiteSpace: "nowrap", flexShrink: 0, fontVariantNumeric: "tabular-nums",
                  }}>
                    {formatDuration(tr.duration)}
                  </span>
                )}
                <span style={{
                  fontSize: 11, color: "var(--text)", opacity: 0.35,
                  whiteSpace: "nowrap", maxWidth: 120,
                  overflow: "hidden", textOverflow: "ellipsis",
                  display: "var(--filename-display, inline)",
                }}>
                  {tr.file_name}
                </span>
              </div>
            ))}
          </div>

        </div>
      )}
    </div>
  );
}

export default function BulkEditor({ albums: initial, onConfirm, onReset, onRemove }) {
  const { t } = useLang();
  const [albums,    setAlbums]    = useState(initial);
  // collapsed state lives here so "Collapse all" can actually control it
  const [collapsed, setCollapsed] = useState(() => initial.map(() => false));

  function onChange(index, updated) {
    setAlbums((prev) => prev.map((a, i) => i === index ? updated : a));
  }

  function onToggle(index) {
    setCollapsed((prev) => prev.map((c, i) => i === index ? !c : c));
  }

  function handleRemove(index) {
    const removed = albums[index];
    setAlbums((prev)    => prev.filter((_, i) => i !== index));
    setCollapsed((prev) => prev.filter((_, i) => i !== index));
    if (onRemove) onRemove(removed);
  }

  const allCollapsed = collapsed.every(Boolean);

  function toggleAll() {
    const next = !allCollapsed;
    setCollapsed(albums.map(() => next));
  }

  const anyInvalid = albums.some(
    (a) => !a.artist || !a.album || a.tracks.some((t) => !t.title.trim())
  );

  function confirm() {
    onConfirm(albums.map((a) => ({
      artist:        a.artist,
      album_artist:  a.album_artist || a.artist,
      album:         a.album,
      release_year:  a.release_year,
      cover_art_b64: a.cover_art_b64,
      is_single:     false,
      tracks:        a.tracks.map((tr, i) => ({ ...tr, track_number: tr.track_number ?? i + 1 })),
    })));
  }

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 28 }}>

      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
        <span style={{
          fontSize: 11, fontWeight: 600, color: "var(--text)",
          textTransform: "uppercase", letterSpacing: "0.07em",
        }}>
          {t("albumCount", albums.length)}
        </span>
        <button onClick={toggleAll} style={{ fontSize: 12, padding: "4px 10px" }}>
          {allCollapsed ? t("expandAll") : t("collapseAll")}
        </button>
      </div>

      {albums.map((a, i) => (
        <AlbumPanel
          key={a.zip_name + i}
          albumMeta={a}
          index={i}
          collapsed={collapsed[i]}
          onToggle={onToggle}
          onChange={onChange}
          onRemove={handleRemove}
        />
      ))}

      <div style={{ display: "flex", gap: 10, paddingTop: 8 }}>
        <button onClick={onReset}>{t("back")}</button>
        <button className="primary" disabled={anyInvalid} onClick={confirm} style={{ flex: 1 }}>
          {t("saveAllToLibrary")}
        </button>
      </div>

    </div>
  );
}
