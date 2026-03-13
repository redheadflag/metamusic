import { useRef, useState } from "react";

const Field = ({ label, value, onChange, required }) => (
  <div style={{ display: "flex", flexDirection: "column", gap: 5 }}>
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

// Drag handle icon (three horizontal lines)
const DragHandle = () => (
  <svg width="14" height="14" viewBox="0 0 14 14" fill="none"
    style={{ flexShrink: 0, cursor: "grab", opacity: 0.35 }}>
    <rect y="2"  width="14" height="1.5" rx="0.75" fill="currentColor"/>
    <rect y="6"  width="14" height="1.5" rx="0.75" fill="currentColor"/>
    <rect y="10" width="14" height="1.5" rx="0.75" fill="currentColor"/>
  </svg>
);

export default function MetaEditor({ tracks, onConfirm, onReset }) {
  const first = tracks[0];

  const [shared, setShared] = useState({
    artist:        first.artist,
    album_artist:  first.artist,
    album:         first.album,
    release_year:  first.release_year,
    cover_art_b64: first.cover_art_b64 ?? null,
  });

  // Single source of truth: rows ordered by current track number
  const [rows, setRows] = useState(() =>
    [...tracks]
      .sort((a, b) => a.track_number - b.track_number)
      .map((t) => ({ track: t, title: t.title }))
  );

  // Drag state
  const dragIndex = useRef(null);
  const [overIndex, setOverIndex] = useState(null);

  function onDragStart(i) {
    dragIndex.current = i;
  }

  function onDragEnter(i) {
    setOverIndex(i);
  }

  function onDragEnd() {
    const from = dragIndex.current;
    const to   = overIndex;
    if (from !== null && to !== null && from !== to) {
      setRows((prev) => {
        const next = [...prev];
        const [moved] = next.splice(from, 1);
        next.splice(to, 0, moved);
        return next;
      });
    }
    dragIndex.current = null;
    setOverIndex(null);
  }

  const set = (key) => (v) =>
    setShared((s) => ({
      ...s, [key]: v,
      ...(key === "artist" ? { album_artist: v } : {}),
    }));

  function handleCoverFile(e) {
    const file = e.target.files[0];
    if (!file) return;
    const reader = new FileReader();
    reader.onload = () =>
      setShared((s) => ({ ...s, cover_art_b64: reader.result.split(",")[1] }));
    reader.readAsDataURL(file);
  }

  const missing = !shared.artist || !shared.album || rows.some((r) => !r.title.trim());

  function confirm() {
    onConfirm({
      ...shared,
      tracks: rows.map((r, i) => ({ ...r.track, title: r.title, track_number: i + 1 })),
    });
  }

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 28 }}>

      {/* Cover + shared fields */}
      <div style={{ display: "flex", gap: 16, alignItems: "flex-start" }}>
        <label style={{ cursor: "pointer", flexShrink: 0 }}>
          <div style={{
            width: 88, height: 88,
            borderRadius: "var(--radius)",
            border: "1px solid var(--border)",
            background: "var(--code-bg)",
            overflow: "hidden",
            display: "flex", alignItems: "center", justifyContent: "center",
          }}>
            {shared.cover_art_b64
              ? <img src={`data:image/jpeg;base64,${shared.cover_art_b64}`}
                     style={{ width: "100%", height: "100%", objectFit: "cover" }} />
              : <span style={{ fontSize: 11, color: "var(--text)", opacity: 0.5 }}>cover</span>
            }
          </div>
          <input type="file" accept="image/*" style={{ display: "none" }} onChange={handleCoverFile} />
        </label>

        <div style={{ flex: 1, display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10 }}>
          <div style={{ gridColumn: "1 / -1" }}>
            <Field label="Artist" value={shared.artist} onChange={set("artist")} required />
          </div>
          <Field label="Album" value={shared.album}        onChange={set("album")}        required />
          <Field label="Year"  value={shared.release_year} onChange={set("release_year")} />
        </div>
      </div>

      <div style={{ borderTop: "1px solid var(--border)" }} />

      {/* Track list */}
      <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
        <span style={{
          fontSize: 11, fontWeight: 600, color: "var(--text)",
          textTransform: "uppercase", letterSpacing: "0.07em",
          marginBottom: 2,
        }}>
          Tracks
        </span>

        {rows.map((r, i) => {
          const isOver = overIndex === i && dragIndex.current !== i;
          return (
            <div
              key={r.track.temp_path}
              draggable
              onDragStart={() => onDragStart(i)}
              onDragEnter={() => onDragEnter(i)}
              onDragOver={(e) => e.preventDefault()}
              onDragEnd={onDragEnd}
              style={{
                display: "flex",
                alignItems: "center",
                gap: 10,
                padding: "6px 8px",
                borderRadius: 7,
                border: isOver
                  ? "1px solid var(--accent-border)"
                  : "1px solid transparent",
                background: isOver ? "var(--accent-bg)" : "transparent",
                transition: "background 0.1s, border-color 0.1s",
                userSelect: "none",
              }}
            >
              <DragHandle />

              <span style={{
                fontSize: 12, color: "var(--text)", opacity: 0.45,
                minWidth: 20, textAlign: "right",
                fontVariantNumeric: "tabular-nums",
              }}>
                {String(i + 1).padStart(2, "0")}
              </span>

              <input
                value={r.title}
                placeholder="Title required"
                draggable={false}
                onChange={(e) => {
                  const v = e.target.value;
                  setRows((rs) => rs.map((row, j) => j === i ? { ...row, title: v } : row));
                }}
                onDragStart={(e) => e.stopPropagation()}
                style={{
                  flex: 1,
                  borderColor: !r.title.trim() ? "var(--danger)" : undefined,
                }}
              />

              <span style={{
                fontSize: 11, color: "var(--text)", opacity: 0.35,
                whiteSpace: "nowrap", maxWidth: 130,
                overflow: "hidden", textOverflow: "ellipsis",
              }}>
                {r.track.file_name}
              </span>
            </div>
          );
        })}
      </div>

      {/* Actions */}
      <div style={{ display: "flex", gap: 10, paddingTop: 4 }}>
        <button onClick={onReset}>← Back</button>
        <button className="primary" disabled={missing} onClick={confirm} style={{ flex: 1 }}>
          Save to library
        </button>
      </div>

    </div>
  );
}