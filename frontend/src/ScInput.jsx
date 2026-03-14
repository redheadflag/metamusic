import { useState } from "react";

export default function ScInput({ onFetch, onBack }) {
  const [url,     setUrl]     = useState("");
  const [loading, setLoading] = useState(false);
  const [error,   setError]   = useState(null);

  const valid = /soundcloud\.com\/.+/.test(url.trim());

  async function handleFetch() {
    setLoading(true);
    setError(null);
    try {
      await onFetch(url.trim());
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
      <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
        <label style={{
          fontSize: 11, fontWeight: 600, color: "var(--text)",
          textTransform: "uppercase", letterSpacing: "0.07em",
        }}>
          SoundCloud URL
        </label>
        <input
          type="url"
          value={url}
          placeholder="https://soundcloud.com/artist/track-or-playlist"
          onChange={(e) => { setUrl(e.target.value); setError(null); }}
          onKeyDown={(e) => e.key === "Enter" && valid && !loading && handleFetch()}
          autoFocus
        />
        <p style={{ fontSize: 12, color: "var(--text)", opacity: 0.45 }}>
          Works with tracks, albums, and playlists
        </p>
      </div>

      {error && (
        <p style={{ fontSize: 13, color: "var(--danger)" }}>{error}</p>
      )}

      <div style={{ display: "flex", gap: 10 }}>
        <button onClick={onBack}>← Back</button>
        <button
          className="primary"
          disabled={!valid || loading}
          onClick={handleFetch}
          style={{ flex: 1 }}
        >
          {loading ? "Fetching metadata…" : "Fetch"}
        </button>
      </div>
    </div>
  );
}