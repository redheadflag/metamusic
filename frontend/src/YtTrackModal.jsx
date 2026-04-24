import { useState } from "react";
import ArtistsEditor from "./ArtistsEditor.jsx";
import { useLang } from "./LangContext.jsx";

const inputStyle = {
  padding: "7px 10px",
  border: "1px solid var(--border)",
  borderRadius: "var(--radius)",
  background: "var(--code-bg)",
  color: "var(--text)",
  fontSize: 13,
  width: "100%",
  boxSizing: "border-box",
};

const labelStyle = {
  fontSize: 11,
  fontWeight: 600,
  color: "var(--text)",
  textTransform: "uppercase",
  letterSpacing: "0.07em",
};

export default function YtTrackModal({ track, onSave, onClose }) {
  const { t } = useLang();

  const [title,        setTitle]        = useState(track.title || "");
  const [artists,      setArtists]      = useState(track.artists || []);
  const [albumArtists, setAlbumArtists] = useState(
    (track.album_artists && track.album_artists.length)
      ? track.album_artists
      : (track.artists || [])
  );
  const [album,        setAlbum]        = useState(track.album || "");
  const [year,         setYear]         = useState(track.release_year || "");

  function handleSave() {
    onSave({
      ...track,
      title,
      artists,
      album_artists: albumArtists.length ? albumArtists : artists,
      album,
      release_year: year,
    });
  }

  return (
    <div
      onClick={onClose}
      style={{
        position: "fixed",
        inset: 0,
        background: "rgba(0,0,0,0.5)",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        zIndex: 200,
        padding: 24,
      }}
    >
      <div
        onClick={(e) => e.stopPropagation()}
        style={{
          background: "var(--bg)",
          border: "1px solid var(--border)",
          borderRadius: "var(--radius)",
          padding: "28px 28px 24px",
          width: "100%",
          maxWidth: 480,
          display: "flex",
          flexDirection: "column",
          gap: 16,
        }}
      >
        <h2 style={{ margin: 0, fontSize: 15, fontWeight: 600, color: "var(--text-h)" }}>
          {t("edit")}
        </h2>

        {/* Title */}
        <div style={{ display: "flex", flexDirection: "column", gap: 5 }}>
          <label style={labelStyle}>{t("trackLabel")}</label>
          <input
            autoFocus
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            style={{ ...inputStyle, borderColor: !title.trim() ? "var(--danger)" : undefined }}
          />
        </div>

        {/* Artists */}
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

        {/* Album Artists */}
        <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
          <label style={{ ...labelStyle, opacity: 0.65 }}>{t("albumArtistsLabel")}</label>
          <ArtistsEditor
            value={albumArtists}
            onChange={setAlbumArtists}
            placeholder={t("artistsPlaceholder")}
          />
          <span style={{ fontSize: 10, color: "var(--text)", opacity: 0.38 }}>
            {t("albumArtistHint")}
          </span>
        </div>

        {/* Album + Year */}
        <div style={{ display: "grid", gridTemplateColumns: "1fr 80px", gap: 10 }}>
          <div style={{ display: "flex", flexDirection: "column", gap: 5 }}>
            <label style={labelStyle}>{t("albumLabel")}</label>
            <input
              value={album}
              onChange={(e) => setAlbum(e.target.value)}
              style={inputStyle}
              placeholder="optional"
            />
          </div>
          <div style={{ display: "flex", flexDirection: "column", gap: 5 }}>
            <label style={labelStyle}>{t("yearLabel")}</label>
            <input
              value={year}
              onChange={(e) => setYear(e.target.value)}
              style={inputStyle}
            />
          </div>
        </div>

        {/* Actions */}
        <div style={{ display: "flex", gap: 8, justifyContent: "flex-end", paddingTop: 4 }}>
          <button onClick={onClose} style={{ opacity: 0.65 }}>{t("back")}</button>
          <button
            className="primary"
            disabled={!title.trim() || !artists.length}
            onClick={handleSave}
          >
            {t("saveToLibrary").split(" ")[0]}
          </button>
        </div>
      </div>
    </div>
  );
}
