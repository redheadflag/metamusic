import { useState } from "react";

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

function AlbumPanel({ albumMeta, index, onChange, onRemove }) {
  const [collapsed, setCollapsed] = useState(false);

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
        onClick={() => setCollapsed((c) => !c)}
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
              {albumMeta.artist || <span style={{ opacity: 0.4 }}>No artist</span>}
              {albumMeta.album ? ` — ${albumMeta.album}` : ""}
            </div>
            <div style={{ fontSize: 11, color: "var(--text)", opacity: 0.5 }}>
              {albumMeta.zip_name} · {albumMeta.tracks.length} track{albumMeta.tracks.length !== 1 ? "s" : ""}
            </div>
          </div>
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <button
            onClick={(e) => { e.stopPropagation(); onRemove(index); }}
            style={{ fontSize: 11, padding: "2px 8px", color: "var(--danger)", borderColor: "var(--danger)", opacity: 0.7 }}
          >
            Remove
          </button>
          <span style={{ fontSize: 12, color: "var(--text)", opacity: 0.4 }}>
            {collapsed ? "▶" : "▼"}
          </span>
        </div>
      </div>

      {/* Body */}
      {!collapsed && (
        <div style={{ padding: 16, display: "flex", flexDirection: "column", gap: 16 }}>

          {/* Cover + fields */}
          <div style={{ display: "flex", gap: 12, alignItems: "flex-start" }}>
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

            <div style={{ flex: 1, display: "grid", gridTemplateColumns: "1fr 1fr", gap: 8 }}>
              <div style={{ gridColumn: "1 / -1" }}>
                <Field label="Artist" value={albumMeta.artist} onChange={set("artist")} required />
              </div>
              <Field label="Album"  value={albumMeta.album}        onChange={set("album")}        required />
              <Field label="Year"   value={albumMeta.release_year} onChange={set("release_year")} />
            </div>
          </div>

          {/* Track list */}
          <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
            <span style={{
              fontSize: 11, fontWeight: 600, color: "var(--text)",
              textTransform: "uppercase", letterSpacing: "0.07em",
            }}>
              Tracks
            </span>
            {albumMeta.tracks.map((t, i) => (
              <div key={t.temp_path} style={{ display: "flex", alignItems: "center", gap: 8 }}>
                <input
                  type="number"
                  min={1}
                  value={t.track_number ?? i + 1}
                  onChange={(e) => {
                    const v = parseInt(e.target.value, 10);
                    if (!isNaN(v) && v > 0) setTrackNumber(i, v);
                  }}
                  style={{ width: 64, textAlign: "center", flexShrink: 0 }}
                />
                <input
                  value={t.title}
                  placeholder="Title required"
                  onChange={(e) => setTitle(i, e.target.value)}
                  style={{
                    flex: 1,
                    borderColor: !t.title.trim() ? "var(--danger)" : undefined,
                  }}
                />
                <span style={{
                  fontSize: 11, color: "var(--text)", opacity: 0.35,
                  whiteSpace: "nowrap", maxWidth: 120,
                  overflow: "hidden", textOverflow: "ellipsis",
                  display: "var(--filename-display, inline)",
                }}>
                  {t.file_name}
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
  const [albums, setAlbums] = useState(initial);

  function onChange(index, updated) {
    setAlbums((prev) => prev.map((a, i) => i === index ? updated : a));
  }

  function handleRemove(index) {
    const removed = albums[index];
    setAlbums((prev) => prev.filter((_, i) => i !== index));
    if (onRemove) onRemove(removed);
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
      tracks:        a.tracks.map((t, i) => ({ ...t, track_number: t.track_number ?? i + 1 })),
    })));
  }

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 20 }}>

      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
        <span style={{
          fontSize: 11, fontWeight: 600, color: "var(--text)",
          textTransform: "uppercase", letterSpacing: "0.07em",
        }}>
          {albums.length} album{albums.length !== 1 ? "s" : ""}
        </span>
        <button
          onClick={() => setAlbums((prev) => prev.map((a) => ({ ...a, _collapsed: true })))}
          style={{ fontSize: 12, padding: "4px 10px" }}
        >
          Collapse all
        </button>
      </div>

      {albums.map((a, i) => (
        <AlbumPanel key={a.zip_name + i} albumMeta={a} index={i} onChange={onChange} onRemove={handleRemove} />
      ))}

      <div style={{ display: "flex", gap: 10, paddingTop: 4 }}>
        <button onClick={onReset}>← Back</button>
        <button className="primary" disabled={anyInvalid} onClick={confirm} style={{ flex: 1 }}>
          Save all to library
        </button>
      </div>

    </div>
  );
}