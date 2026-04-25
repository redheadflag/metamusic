import { useState } from "react";
import { LangProvider, useLang } from "./LangContext.jsx";
import ModeSelector    from "./ModeSelector.jsx";
import UploadZone      from "./UploadZone.jsx";
import MetaEditor      from "./MetaEditor.jsx";
import BulkEditor      from "./BulkEditor.jsx";
import MediaImport     from "./MediaImport.jsx";
import QueuePanel      from "./QueuePanel.jsx";

const API = "/api";

// ── helpers ───────────────────────────────────────────────────────────────────

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

function LangSwitcher() {
  const { lang, setLang } = useLang();
  return (
    <div style={{
      display: "flex",
      background: "var(--code-bg)",
      border: "1px solid var(--border)",
      borderRadius: 7,
      padding: 2,
      gap: 1,
    }}>
      {["ru", "en"].map((l) => {
        const active = lang === l;
        return (
          <button
            key={l}
            onClick={() => setLang(l)}
            style={{
              padding: "3px 9px",
              borderRadius: 5,
              border: "none",
              fontSize: 12,
              fontWeight: active ? 600 : 400,
              background: active ? "var(--bg)" : "transparent",
              color: active ? "var(--text-h)" : "var(--text)",
              opacity: active ? 1 : 0.5,
              boxShadow: active ? "0 1px 3px rgba(0,0,0,0.08)" : "none",
              cursor: "pointer",
              transition: "all 0.15s",
              textTransform: "uppercase",
              letterSpacing: "0.04em",
            }}
          >
            {l}
          </button>
        );
      })}
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

/** POST to an endpoint that returns { job_id, status }.
 *  Returns job_id immediately so the caller can fire-and-forget. */
async function enqueueJob(url, body) {
  const res = await fetch(url, {
    method:  "POST",
    headers: { "Content-Type": "application/json" },
    body:    JSON.stringify(body),
  });
  if (!res.ok) throw new Error(await res.text());
  const { job_id } = await res.json();
  return job_id;
}

// ── App (inner — needs useLang) ───────────────────────────────────────────────

// mode:  null | "files" | "import"
// state: "idle" | "uploading" | "media-input" | "editing"
//      | "bulk-editing" | "saving" | "sent" | "done" | "error"

function AppInner() {
  const { t } = useLang();

  const [mode,         setMode]         = useState(null);
  const [state,        setState]        = useState("idle");
  const [progress,     setProgress]     = useState(0);
  const [jobStatus,    setJobStatus]    = useState(null);
  const [tracks,       setTracks]       = useState([]);
  const [albums,       setAlbums]       = useState([]);
  const [saved,        setSaved]        = useState([]);
  const [error,        setError]        = useState(null);
  const [importStats,  setImportStats]  = useState(null);
  const [showQueue,    setShowQueue]    = useState(false);

  // ── file upload ────────────────────────────────────────────────────────
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

  // ── remove album from bulk edit ────────────────────────────────────────
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

  // ── Media import (YouTube + SoundCloud) ──────────────────────────────
  async function handleMediaImport(importReq) {
    const queued      = importReq.tracks.filter(t => !t.in_navidrome && !t.skip).length;
    const inNavidrome = importReq.tracks.filter(t => t.in_navidrome).length;
    setImportStats({ queued, inNavidrome });
    setShowQueue(false);
    setState("saving");
    setError(null);
    try {
      await enqueueJob(`${API}/import`, importReq);
      setState("sent");
    } catch (e) {
      setError(e.message);
      setState("error");
    }
  }

  // ── submit single/SC album ────────────────────────────────────────────
  // Fire-and-forget: switch to "sent" immediately after enqueue, don't poll.
  async function handleConfirm(meta) {
    setState("saving");
    setJobStatus(null);
    setError(null);
    try {
      const hasSc    = meta.tracks?.some((t) => t.sc_url);
      const endpoint = hasSc ? `${API}/sc-process` : `${API}/process`;
      await enqueueJob(endpoint, meta);
      setState("sent");
    } catch (e) {
      setError(e.message);
      setState("error");
    }
  }

  // ── submit bulk albums ────────────────────────────────────────────────
  async function handleBulkConfirm(albumRequests) {
    setState("saving");
    setJobStatus(null);
    setError(null);
    try {
      await enqueueJob(`${API}/process-bulk`, { albums: albumRequests });
      setState("sent");
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
    setImportStats(null);
    setShowQueue(false);
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
        gap: 12,
      }}>
        <h1 style={{ cursor: mode ? "pointer" : "default", margin: 0 }} onClick={reset}>
          {t("appTitle")}
        </h1>
        <div style={{ display: "flex", alignItems: "center", gap: 12, flexShrink: 0 }}>
          {showCount && (
            <span style={{ fontSize: 13, color: "var(--text)", opacity: 0.6 }}>
              {state === "bulk-editing"
                ? t("albumsLabel", editingCount)
                : t("tracksLabel2", editingCount)}
            </span>
          )}
          <LangSwitcher />
        </div>
      </header>

      {/* Mode selection */}
      {state === "idle" && !mode && (
        <ModeSelector onSelect={(m) => {
          setMode(m);
          if (m === "import") setState("media-input");
        }} />
      )}

      {/* Files mode */}
      {state === "idle" && mode === "files" && (
        <UploadZone onFiles={handleFiles} onBack={() => { setMode(null); }} />
      )}

      {/* Unified media import (YouTube + SoundCloud) */}
      {state === "media-input" && !showQueue && (
        <MediaImport
          onBack={() => { setMode(null); setState("idle"); }}
          onImport={handleMediaImport}
        />
      )}
      {state === "media-input" && showQueue && (
        <QueuePanel onBack={() => setShowQueue(false)} />
      )}

      {/* Upload progress */}
      {state === "uploading" && <ProgressBar progress={progress} label={t("uploadingLabel")} />}

      {/* Editors */}
      {state === "editing" && (
        <MetaEditor tracks={tracks} onConfirm={handleConfirm} onReset={backToMode} />
      )}
      {state === "bulk-editing" && (
        <BulkEditor albums={albums} onConfirm={handleBulkConfirm} onReset={backToMode} onRemove={handleRemoveAlbum} />
      )}

      {/* Submitting (brief spinner while POST is in flight) */}
      {state === "saving" && (
        <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
          <Spinner />
          <span style={{ fontSize: 14, color: "var(--text)", opacity: 0.7 }}>
            {t("jobSubmitting")}
          </span>
        </div>
      )}

      {/* Sent — job enqueued, user can go back immediately */}
      {state === "sent" && !showQueue && (
        <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
          <p style={{ color: "var(--accent)", fontWeight: 500, fontSize: 15 }}>
            {t("jobSentTitle")}
          </p>
          <p style={{ fontSize: 13, color: "var(--text)", opacity: 0.6, margin: 0 }}>
            {importStats
              ? t("ytQueued", importStats.queued, importStats.inNavidrome)
              : t("jobSentNote")}
          </p>
          <div style={{ display: "flex", gap: 10 }}>
            <button onClick={reset}>{t("goBack")}</button>
            {importStats && (
              <button onClick={() => setShowQueue(true)} style={{ opacity: 0.7 }}>
                {t("ytViewQueue")}
              </button>
            )}
          </div>
        </div>
      )}
      {state === "sent" && showQueue && (
        <QueuePanel onBack={() => setShowQueue(false)} />
      )}

      {state === "done" && (
        <div style={{ display: "flex", flexDirection: "column", gap: 20 }}>
          <p style={{ color: "var(--accent)", fontWeight: 500 }}>
            {t("savedCount", saved.length)}
          </p>
          <ul style={{ listStyle: "none", display: "flex", flexDirection: "column", gap: 4 }}>
            {saved.map((p, i) => (
              <li key={i} style={{ fontSize: 12, color: "var(--text)", opacity: 0.6, fontFamily: "monospace" }}>{p}</li>
            ))}
          </ul>
          <div><button onClick={reset}>{t("uploadMore")}</button></div>
        </div>
      )}

      {state === "error" && (
        <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
          <p style={{ color: "var(--danger)", fontSize: 14 }}>{error}</p>
          <div><button onClick={reset}>{t("tryAgain")}</button></div>
        </div>
      )}
    </>
  );
}

export default function App() {
  return (
    <LangProvider>
      <AppInner />
    </LangProvider>
  );
}
