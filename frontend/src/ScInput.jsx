import { useState } from "react";

const ARTIST_SUFFIXES = /\/(albums|tracks|sets|likes|following|followers|reposts|spotlight)\/?$/;

function detectType(url) {
  const u = url.replace(ARTIST_SUFFIXES, "");
  if (/soundcloud\.com\/[^/]+\/sets\//.test(url)) return "playlist";
  if (ARTIST_SUFFIXES.test(url))                       return "artist";
  if (/soundcloud\.com\/[^/]+\/[^/]+/.test(u))     return "track";
  if (/soundcloud\.com\/[^/]+\/?$/.test(u))         return "artist";
  return null;
}

const TYPE_LABELS = {
  track:    "Single track",
  playlist: "Playlist / album",
  artist:   "Artist profile — fetches all albums and tracks",
};

export default function ScInput({ onFetch, onBack }) {
  const [url,     setUrl]     = useState("");
  const [loading, setLoading] = useState(false);
  const [error,   setError]   = useState(null);

  const type  = detectType(url.trim());
  const valid = type !== null;

  async function handleFetch() {
    setLoading(true);
    setError(null);
    try {
      await onFetch(url.trim(), type);
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
          placeholder="https://soundcloud.com/artist or /artist/track or /artist/sets/album"
          onChange={(e) => { setUrl(e.target.value); setError(null); }}
          onKeyDown={(e) => e.key === "Enter" && valid && !loading && handleFetch()}
          autoFocus
        />
        {type && (
          <p style={{ fontSize: 12, color: "var(--accent)", opacity: 0.8 }}>
            {TYPE_LABELS[type]}
          </p>
        )}
        {!type && url && (
          <p style={{ fontSize: 12, color: "var(--text)", opacity: 0.45 }}>
            Enter a valid SoundCloud URL
          </p>
        )}
      </div>

      {error && <p style={{ fontSize: 13, color: "var(--danger)" }}>{error}</p>}

      <div style={{ display: "flex", gap: 10 }}>
        <button onClick={onBack}>← Back</button>
        <button
          className="primary"
          disabled={!valid || loading}
          onClick={handleFetch}
          style={{ flex: 1 }}
        >
          {loading
            ? type === "artist" ? "Fetching artist profile…" : "Fetching metadata…"
            : "Fetch"}
        </button>
      </div>
    </div>
  );
}