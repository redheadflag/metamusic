import { useRef, useState } from "react";

export default function UploadZone({ onFiles }) {
  const inputRef = useRef();
  const [dragging, setDragging] = useState(false);

  function handle(files) {
    const audio = Array.from(files).filter(
      (f) => f.type.startsWith("audio/") || /\.(mp3|flac|ogg|m4a|wav|aiff)$/i.test(f.name)
    );
    if (audio.length) onFiles(audio);
  }

  return (
    <div
      onClick={() => inputRef.current.click()}
      onDragOver={(e) => { e.preventDefault(); setDragging(true); }}
      onDragLeave={() => setDragging(false)}
      onDrop={(e) => { e.preventDefault(); setDragging(false); handle(e.dataTransfer.files); }}
      style={{
        border: `1.5px dashed ${dragging ? "var(--accent)" : "var(--border)"}`,
        borderRadius: "var(--radius)",
        padding: "56px 24px",
        textAlign: "center",
        cursor: "pointer",
        background: dragging ? "var(--accent-bg)" : "transparent",
        transition: "background 0.15s, border-color 0.15s",
      }}
    >
      <p style={{ fontSize: 14, color: "var(--text)", opacity: 0.7, marginBottom: 6 }}>
        Drop audio files here
      </p>
      <p style={{ fontSize: 13, color: "var(--accent)" }}>or click to browse</p>
      <input
        ref={inputRef}
        type="file"
        multiple
        accept="audio/*,.flac,.aiff"
        style={{ display: "none" }}
        onChange={(e) => handle(e.target.files)}
      />
    </div>
  );
}