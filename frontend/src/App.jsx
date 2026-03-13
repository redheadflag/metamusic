import { useState } from "react";
import UploadZone from "./UploadZone.jsx";
import MetaEditor from "./MetaEditor.jsx";

const API = "/api";

export default function App() {
  const [state, setState]   = useState("idle");
  const [tracks, setTracks] = useState([]);
  const [saved,  setSaved]  = useState([]);
  const [error,  setError]  = useState(null);

  async function handleFiles(files) {
    setState("uploading");
    setError(null);
    try {
      const body = new FormData();
      files.forEach((f) => body.append("files", f));
      const res  = await fetch(`${API}/upload`, { method: "POST", body });
      if (!res.ok) throw new Error(await res.text());
      setTracks(await res.json());
      setState("editing");
    } catch (e) {
      setError(e.message);
      setState("error");
    }
  }

  async function handleConfirm(meta) {
    setState("saving");
    setError(null);
    try {
      const res = await fetch(`${API}/process`, {
        method:  "POST",
        headers: { "Content-Type": "application/json" },
        body:    JSON.stringify(meta),
      });
      if (!res.ok) throw new Error(await res.text());
      setSaved((await res.json()).saved);
      setState("done");
    } catch (e) {
      setError(e.message);
      setState("error");
    }
  }

  function reset() { setTracks([]); setSaved([]); setState("idle"); }

  return (
    <>
      <header style={{
        marginBottom: 40,
        paddingBottom: 20,
        borderBottom: "1px solid var(--border)",
        display: "flex",
        alignItems: "center",
        justifyContent: "space-between",
      }}>
        <h1>Upload to music.redheadflag.com</h1>
        {state === "editing" && (
          <span style={{ fontSize: 13, color: "var(--text)", opacity: 0.6 }}>
            {tracks.length} track{tracks.length !== 1 ? "s" : ""}
          </span>
        )}
      </header>

      {state === "idle" && <UploadZone onFiles={handleFiles} />}

      {state === "uploading" && (
        <p style={{ color: "var(--text)", opacity: 0.5 }}>Reading metadata…</p>
      )}

      {state === "editing" && (
        <MetaEditor
          tracks={tracks}
          onConfirm={handleConfirm}
          onReset={reset}
        />
      )}

      {state === "saving" && (
        <p style={{ color: "var(--text)", opacity: 0.5 }}>Saving to library…</p>
      )}

      {state === "done" && (
        <div style={{ display: "flex", flexDirection: "column", gap: 20 }}>
          <p style={{ color: "var(--accent)", fontWeight: 500 }}>
            ✓ {saved.length} track{saved.length !== 1 ? "s" : ""} saved
          </p>
          <ul style={{ listStyle: "none", display: "flex", flexDirection: "column", gap: 4 }}>
            {saved.map((p, i) => (
              <li key={i} style={{ fontSize: 12, color: "var(--text)", opacity: 0.6, fontFamily: "monospace" }}>{p}</li>
            ))}
          </ul>
          <div><button onClick={reset}>Upload more</button></div>
        </div>
      )}

      {state === "error" && (
        <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
          <p style={{ color: "var(--danger)", fontSize: 14 }}>{error}</p>
          <div><button onClick={reset}>Try again</button></div>
        </div>
      )}
    </>
  );
}