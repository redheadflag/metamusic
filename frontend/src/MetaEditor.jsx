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

const formatDuration = (seconds) => {
  if (seconds == null) return null;
  const m = Math.floor(seconds / 60);
  const s = String(seconds % 60).padStart(2, "0");
  return `${m}:${s}`;
};

const DragHandle = () => (
  <svg width="14" height="14" viewBox="0 0 14 14" fill="none"
    style={{ flexShrink: 0, cursor: "grab", opacity: 0.35 }}>
    <rect y="2"  width="14" height="1.5" rx="0.75" fill="currentColor"/>
    <rect y="6"  width="14" height="1.5" rx="0.75" fill="currentColor"/>
    <rect y="10" width="14" height="1.5" rx="0.75" fill="currentColor"/>
  </svg>
);

const SegmentedControl = ({ value, onChange }) => {
  const options = [
    { value: "single", label: "Single" },
    { value: "album",  label: "Song from album" },
  ];
  return (
    <div style={{
      display: "flex",
      background: "var(--code-bg)",
      border: "1px solid var(--border)",
      borderRadius: 8,
      padding: 3,
      gap: 2,
    }}>
      {options.map((opt) => {
        const active = value === opt.value;
        return (
          <button
            key={opt.value}
            onClick={() => onChange(opt.value)}
            style={{
              flex: 1,
              padding: "6px 14px",
              borderRadius: 6,
              border: "none",
              fontSize: 13,
              fontWeight: active ? 500 : 400,
              background: active ? "var(--bg)" : "transparent",
              color: active ? "var(--text-h)" : "var(--text)",
              boxShadow: active ? "0 1px 3px rgba(0,0,0,0.08)" : "none",
              transition: "background 0.15s, color 0.15s, box-shadow 0.15s",
              cursor: "pointer",
              textAlign: "center",
            }}
          >
            {opt.label}
          </button>
        );
      })}
    </div>
  );
};

export default function MetaEditor({ tracks, onConfirm, onReset }) {
  const first = tracks[0];

  const [mode, setMode] = useState(tracks.length === 1 ? "single" : "album");
  const isSingle = mode === "single";

  const [shared, setShared] = useState({
    artist:        first.artist,
    album_artist:  first.artist,
    album:         first.album,
    release_year:  first.release_year,
    cover_art_b64: first.cover_art_b64 ?? null,
  });

  const [rows, setRows] = useState(() =>
    [...tracks]
      .sort((a, b) => (a.track_number ?? 0) - (b.track_number ?? 0))
      .map((t, i) => ({
        track:        t,
        title:        t.title,
        track_number: t.track_number ?? i + 1,
      }))
  );

  const dragIndex = useRef(null);
  const [overIndex, setOverIndex] = useState(null);

  function onDragStart(i) { dragIndex.current = i; }
  function onDragEnter(i) { setOverIndex(i); }
  function onDragEnd() {
    const from = dragIndex.current;
    const to   = overIndex;
    if (from !== null && to !== null && from !== to) {
      setRows((prev) => {
        const next = [...prev];
        const [moved] = next.splice(from, 1);
        next.splice(to, 0, moved);
        // reassign track numbers to match new positions
        return next.map((r, i) => ({ ...r, track_number: i + 1 }));
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

  const missing =
    !shared.artist ||
    (!isSingle && !shared.album) ||
    rows.some((r) => !r.title.trim());

  function confirm() {
    onConfirm({
      ...shared,
      is_single: isSingle,
      album: isSingle ? "" : shared.album,
      tracks: rows.map((r) => ({
        ...r.track,
        title:        r.title,
        track_number: isSingle ? null : r.track_number,
        composer:     r.composer  || null,
        language:     r.language  || null,
        lyrics:       r.lyrics    || null,
      })),
    });
  }

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 20 }}>
    {/* Mode toggle — only relevant when a single file is uploaded */}
      {tracks.length === 1 && <SegmentedControl value={mode} onChange={setMode} />}

      {/* Cover + shared fields */}
      <div style={{ display: "flex", gap: 16, alignItems: "flex-start" }}>
        <label style={{ cursor: "pointer", flexShrink: 0 }}>
          <div style={{
            width: 140, height: 140,
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

        <div style={{ flex: 1, display: "flex", flexDirection: "column", gap: 10 }}>
          <Field label="Artist" value={shared.artist} onChange={set("artist")} required />

          {isSingle ? (
            <div style={{ width: "50%" }}>
              <Field label="Year" value={shared.release_year} onChange={set("release_year")} />
            </div>
          ) : (
            <div style={{ display: "grid", gridTemplateColumns: "1fr 80px", gap: 10 }}>
              <Field label="Album" value={shared.album}        onChange={set("album")}        required />
              <Field label="Year"  value={shared.release_year} onChange={set("release_year")} />
            </div>
          )}
        </div>
      </div>

      {/* Single hint */}
      {isSingle && (
        <div style={{
          fontSize: 12, color: "var(--text)", opacity: 0.5,
          padding: "8px 10px", borderRadius: 7,
          border: "1px solid var(--border)", background: "var(--code-bg)",
        }}>
          Album name will be set to <em>{rows[0]?.title.trim() || "track title"} (Single)</em>
        </div>
      )}

      <div style={{ borderTop: "1px solid var(--border)" }} />

      {/* Track list */}
      <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
        <span style={{
          fontSize: 11, fontWeight: 600, color: "var(--text)",
          textTransform: "uppercase", letterSpacing: "0.07em", marginBottom: 2,
        }}>
          {isSingle ? "Track" : "Tracks"}
        </span>

        {rows.map((r, i) => {
          const isOver = overIndex === i && dragIndex.current !== i;
          return (
            <>
              <div
                key={r.track.temp_path}
                draggable={!isSingle}
                onDragStart={() => !isSingle && onDragStart(i)}
                onDragEnter={() => !isSingle && onDragEnter(i)}
                onDragOver={(e) => e.preventDefault()}
                onDragEnd={onDragEnd}
                style={{
                  display: "flex", alignItems: "center", gap: 10,
                  padding: "6px 8px", borderRadius: 7,
                  border: isOver ? "1px solid var(--accent-border)" : "1px solid transparent",
                  background: isOver ? "var(--accent-bg)" : "transparent",
                  transition: "background 0.1s, border-color 0.1s",
                  userSelect: "none",
                }}
              >
                {!isSingle && <DragHandle />}

                {!isSingle && (
                  <input
                    type="number"
                    min={1}
                    value={r.track_number}
                    draggable={false}
                    onDragStart={(e) => e.stopPropagation()}
                    onChange={(e) => {
                      const v = parseInt(e.target.value, 10);
                      if (!isNaN(v) && v > 0)
                        setRows((rs) => rs.map((row, j) => j === i ? { ...row, track_number: v } : row));
                    }}
                    style={{ width: 64, textAlign: "center", flexShrink: 0 }}
                  />
                )}

                <input
                  value={r.title}
                  placeholder="Title required"
                  draggable={false}
                  onChange={(e) => {
                    const v = e.target.value;
                    setRows((rs) => rs.map((row, j) => j === i ? { ...row, title: v } : row));
                  }}
                  onDragStart={(e) => e.stopPropagation()}
                  style={{ flex: 1, borderColor: !r.title.trim() ? "var(--danger)" : undefined }}
                />

                <span style={{
                  fontSize: 11, color: "var(--text)", opacity: 0.35,
                  whiteSpace: "nowrap", maxWidth: 130,
                  overflow: "hidden", textOverflow: "ellipsis",
                  display: "var(--filename-display, inline)",
                }}>
                  {r.track.file_name}
                </span>
                {formatDuration(r.track.duration) && (
                  <span style={{
                    fontSize: 11, color: "var(--text)", opacity: 0.4,
                    whiteSpace: "nowrap", flexShrink: 0, fontVariantNumeric: "tabular-nums",
                  }}>
                    {formatDuration(r.track.duration)}
                  </span>
                )}
                <button
                  onClick={(e) => {
                    e.stopPropagation();
                    if (window.confirm(`Delete "${r.title || r.track.file_name}"?`))
                      setRows((rs) => rs.filter((_, j) => j !== i).map((row, j) => ({ ...row, track_number: j + 1 })));
                  }}
                  draggable={false}
                  onDragStart={(e) => e.stopPropagation()}
                  style={{ fontSize: 13, padding: "2px 6px", flexShrink: 0, color: "var(--danger)", borderColor: "var(--danger)", opacity: 0.7 }}
                >
                  ✕
                </button>
              </div>
            </>
          )
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