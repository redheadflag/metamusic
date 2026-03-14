import { useState } from "react";
import ModeSelector from "./ModeSelector.jsx";
import UploadZone   from "./UploadZone.jsx";
import ScInput      from "./ScInput.jsx";
import MetaEditor   from "./MetaEditor.jsx";
import BulkEditor   from "./BulkEditor.jsx";

const API = "/api";

// ── helpers ──────────────────────────────────────────────────────────────────

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

function Spinner() {
  return (
    <span style={{
      display: "inline-block",
      width: 14, height: 14,
      border: "2px solid var(--border)",
      borderTopColor: "var(--accent)",
      borderRadius: "50%",
      animation: "spin 0.7s linear infinite",
      flexShrink: 0,
    }} />
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

/** POST to an endpoint that now returns { job_id, status }.
 *  Then polls GET /api/jobs/{job_id} every `interval` ms until complete/failed.
 *  Calls onStatus(status) on each poll so the UI can update. */
async function enqueueAndPoll(url, body, { onStatus, interval = 1500 } = {}) {
  const res = await fetch(url, {
    method:  "POST",
    headers: { "Content-Type": "application/json" },
    body:    JSON.stringify(body),
  });
  if (!res.ok) throw new Error(await res.text());

  const { job_id } = await res.json();

  // poll until terminal state
  while (true) {
    await new Promise((r) => setTimeout(r, interval));
    const poll = await fetch(`${API}/jobs/${job_id}`);
    if (!poll.ok) throw new Error(`Poll failed: ${poll.status}`);
    const data = await poll.json();
    onStatus?.(data.status);

    if (data.status === "complete") return data.result;
    if (data.status === "failed")   throw new Error(data.error || "Job failed");
    if (data.status === "not_found") throw new Error("Job not found — it may have expired");
    // queued / in_progress → keep polling
  }
}

// ── App ───────────────────────────────────────────────────────────────────────
// mode:  null | "files" | "soundcloud"
// state: "idle" | "uploading" | "sc-input" | "sc-fetching" | "editing"
//      | "bulk-editing" | "saving" | "done" | "error"

export default function App() {
  const [mode,      setMode]      = useState(null);
  const [state,     setState]     = useState("idle");
  const [progress,  setProgress]  = useState(0);
  const [jobStatus, setJobStatus] = useState(null); // "queued" | "in_progress"
  const [tracks,    setTracks]    = useState([]);
  const [albums,    setAlbums]    = useState([]);
  const [saved,     setSaved]     = useState([]);
  const [error,     setError]     = useState(null);

  // ── file upload ─────────────────────────────────────────────────────────
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

  // ── SoundCloud fetch ────────────────────────────────────────────────────
  async function handleScFetch(url, type) {
    setState("sc-fetching");
    setError(null);
    try {
      const endpoint = type === "artist" ? `${API}/sc-fetch-artist` : `${API}/sc-fetch`;
      const res = await fetch(endpoint, {
        method:  "POST",
        headers: { "Content-Type": "application/json" },
        body:    JSON.stringify({ url }),
      });
      if (!res.ok) throw new Error(await res.text());
      const data = await res.json();
      if (type === "artist") {
        setAlbums(data);
        setState("bulk-editing");
      } else {
        setTracks(data);
        setState("editing");
      }
    } catch (e) {
      setState("sc-input");
      throw e;
    }
  }

  // ── remove album from bulk edit ─────────────────────────────────────────
  async function handleRemoveAlbum(album) {
    const tempPaths = (album.tracks || []).map((t) => t.temp_path).filter(Boolean);
    if (tempPaths.length === 0) return;
    try {
      await fetch(`${API}/cancel`, {
        method:  "DELETE",
        headers: { "Content-Type": "application/json" },
        body:    JSON.stringify({ temp_paths: tempPaths }),
      });
    } catch (e) {
      console.warn("Could not clean up temp files:", e);
    }
  }

  // ── process single/SC album ─────────────────────────────────────────────
  async function handleConfirm(meta) {
    setState("saving");
    setJobStatus("queued");
    setError(null);
    try {
      const hasSc    = meta.tracks?.some((t) => t.sc_url);
      const endpoint = hasSc ? `${API}/sc-process` : `${API}/process`;
      const result   = await enqueueAndPoll(endpoint, meta, {
        onStatus: setJobStatus,
      });
      setSaved(result.saved);
      setState("done");
    } catch (e) {
      setError(e.message);
      setState("error");
    }
  }

  // ── process bulk albums ──────────────────────────────────────────────────
  async function handleBulkConfirm(albumRequests) {
    setState("saving");
    setJobStatus("queued");
    setError(null);
    try {
      const result = await enqueueAndPoll(
        `${API}/process-bulk`,
        { albums: albumRequests },
        { onStatus: setJobStatus },
      );
      setSaved(result.saved);
      setState("done");
    } catch (e) {
      setError(e.message);
      setState("error");
    }
  }

  function reset() {
    setMode(null);
    setTracks([]); setAlbums([]); setSaved([]);
    setProgress(0); setJobStatus(null);
    setState("idle");
    setError(null);
  }

  function backToMode() {
    setTracks([]); setAlbums([]); setProgress(0); setError(null);
    setJobStatus(null);
    setState("idle");
  }

  const editingCount = state === "editing"      ? tracks.length
                     : state === "bulk-editing" ? albums.length
                     : 0;
  const showCount = state === "editing" || state === "bulk-editing";

  return (
    <>
      <style>{`@keyframes spin { to { transform: rotate(360deg); } }`}</style>

      <header style={{
        marginBottom: 40, paddingBottom: 20,
        borderBottom: "1px solid var(--border)",
        display: "flex", alignItems: "center", justifyContent: "space-between",
      }}>
        <h1 style={{ cursor: mode ? "pointer" : "default" }} onClick={reset}>
          Upload to music.redheadflag.com
        </h1>
        {showCount && (
          <span style={{ fontSize: 13, color: "var(--text)", opacity: 0.6 }}>
            {editingCount} {state === "bulk-editing" ? "album" : "track"}{editingCount !== 1 ? "s" : ""}
          </span>
        )}
      </header>

      {/* Mode selection */}
      {state === "idle" && !mode && (
        <ModeSelector onSelect={(m) => {
          setMode(m);
          if (m === "soundcloud") setState("sc-input");
        }} />
      )}

      {/* Files mode */}
      {state === "idle" && mode === "files" && (
        <UploadZone onFiles={handleFiles} onBack={() => { setMode(null); }} />
      )}

      {/* SoundCloud mode */}
      {state === "sc-input" && (
        <ScInput
          onFetch={handleScFetch}
          onBack={() => { setMode(null); setState("idle"); }}
        />
      )}

      {state === "sc-fetching" && (
        <p style={{ color: "var(--text)", opacity: 0.5 }}>Fetching metadata from SoundCloud…</p>
      )}

      {/* Upload progress */}
      {state === "uploading" && <ProgressBar progress={progress} label="Uploading…" />}

      {/* Editors */}
      {state === "editing" && (
        <MetaEditor tracks={tracks} onConfirm={handleConfirm} onReset={backToMode} />
      )}
      {state === "bulk-editing" && (
        <BulkEditor albums={albums} onConfirm={handleBulkConfirm} onReset={backToMode} onRemove={handleRemoveAlbum} />
      )}

      {/* Job progress */}
      {state === "saving" && (
        <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
            <Spinner />
            <span style={{ fontSize: 14, color: "var(--text)", opacity: 0.7 }}>
              {jobStatus === "queued"      && "Waiting in queue…"}
              {jobStatus === "in_progress" && "Processing tracks…"}
              {!jobStatus                  && "Submitting job…"}
            </span>
          </div>
          {jobStatus === "in_progress" && (
            <p style={{ fontSize: 12, color: "var(--text)", opacity: 0.4, margin: 0 }}>
              This may take a few minutes for large albums or SoundCloud downloads.
            </p>
          )}
        </div>
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