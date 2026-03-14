import { useState } from "react";
import UploadZone from "./UploadZone.jsx";
import MetaEditor from "./MetaEditor.jsx";
import BulkEditor from "./BulkEditor.jsx";

const API = "/api";

function ProgressBar({ progress, label }) {
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
      <p style={{ fontSize: 13, color: "var(--text)", opacity: 0.6 }}>{label}</p>
      <div style={{ height: 4, borderRadius: 2, background: "var(--border)", overflow: "hidden" }}>
        <div style={{
          height: "100%", width: `${progress}%`,
          background: "var(--accent)", borderRadius: 2,
          transition: progress > 0 ? "width 0.1s ease" : "none",
        }} />
      </div>
      <p style={{ fontSize: 12, color: "var(--text)", opacity: 0.4, textAlign: "right" }}>
        {progress < 100 ? `${progress}%` : "Processing…"}
      </p>
    </div>
  );
}

function uploadWithProgress(url, formData, onProgress) {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("POST", url);
    xhr.upload.addEventListener("progress", (e) => {
      if (e.lengthComputable) onProgress(Math.round((e.loaded / e.total) * 100));
    });
    xhr.addEventListener("load", () => {
      if (xhr.status >= 200 && xhr.status < 300) resolve(JSON.parse(xhr.responseText));
      else reject(new Error(xhr.responseText));
    });
    xhr.addEventListener("error", () => reject(new Error("Network error")));
    xhr.send(formData);
  });
}

// state: "idle" | "uploading" | "editing" | "bulk-editing" | "saving" | "done" | "error"

export default function App() {
  const [state,    setState]    = useState("idle");
  const [progress, setProgress] = useState(0);
  const [tracks,   setTracks]   = useState([]);
  const [albums,   setAlbums]   = useState([]);
  const [saved,    setSaved]    = useState([]);
  const [error,    setError]    = useState(null);

  async function handleFiles(files, type) {
    setState("uploading");
    setProgress(0);
    setError(null);
    try {
      const body = new FormData();
      files.forEach((f) => body.append("files", f));

      if (type === "zip") {
        const data = await uploadWithProgress(`${API}/upload-zip`, body, setProgress);
        setAlbums(data);
        setState("bulk-editing");
      } else {
        const data = await uploadWithProgress(`${API}/upload`, body, setProgress);
        setTracks(data);
        setState("editing");
      }
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
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(meta),
      });
      if (!res.ok) throw new Error(await res.text());
      setSaved((await res.json()).saved);
      setState("done");
    } catch (e) {
      setError(e.message);
      setState("error");
    }
  }

  async function handleBulkConfirm(albumRequests) {
    setState("saving");
    setError(null);
    try {
      const res = await fetch(`${API}/process-bulk`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ albums: albumRequests }),
      });
      if (!res.ok) throw new Error(await res.text());
      setSaved((await res.json()).saved);
      setState("done");
    } catch (e) {
      setError(e.message);
      setState("error");
    }
  }

  function reset() {
    setTracks([]); setAlbums([]); setSaved([]); setProgress(0); setState("idle");
  }

  const editingCount = state === "editing" ? tracks.length
                     : state === "bulk-editing" ? albums.length
                     : 0;

  return (
    <>
      <header style={{
        marginBottom: 40, paddingBottom: 20,
        borderBottom: "1px solid var(--border)",
        display: "flex", alignItems: "center", justifyContent: "space-between",
      }}>
        <h1>Upload to music.redheadflag.com</h1>
        {(state === "editing" || state === "bulk-editing") && (
          <span style={{ fontSize: 13, color: "var(--text)", opacity: 0.6 }}>
            {editingCount} {state === "bulk-editing" ? "album" : "track"}{editingCount !== 1 ? "s" : ""}
          </span>
        )}
      </header>

      {state === "idle" && <UploadZone onFiles={handleFiles} />}

      {state === "uploading" && <ProgressBar progress={progress} label="Uploading…" />}

      {state === "editing" && (
        <MetaEditor tracks={tracks} onConfirm={handleConfirm} onReset={reset} />
      )}

      {state === "bulk-editing" && (
        <BulkEditor albums={albums} onConfirm={handleBulkConfirm} onReset={reset} />
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