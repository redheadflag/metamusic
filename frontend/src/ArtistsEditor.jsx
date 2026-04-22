import { useRef, useState } from "react";

// Mirrors backend/fix_artists.py SEPARATORS: feat., ft., &, /, ;, ,
// The "feat"/"ft" variants only match as whole words so "Knife" isn't split.
const SEPARATORS_RE = /\s*(?:\bfeat\.?|\bft\.?|&|\/|;|,)\s*/i;

function splitInput(s) {
  return s
    .split(SEPARATORS_RE)
    .map((x) => x.trim())
    .filter(Boolean);
}

// True if the raw text contains any separator — used to commit-on-type.
function hasSeparator(s) {
  return /(,|;|&|\/|\bfeat\.?\s|\bft\.?\s)/i.test(s);
}

export default function ArtistsEditor({ value, onChange, placeholder }) {
  const [draft, setDraft] = useState("");
  const dragIdx = useRef(null);
  const [overIdx, setOverIdx] = useState(null);
  const inputRef = useRef(null);

  function commit(raw) {
    const parts = splitInput(raw);
    if (!parts.length) {
      setDraft("");
      return;
    }
    const next = [...value];
    for (const p of parts) if (!next.includes(p)) next.push(p);
    onChange(next);
    setDraft("");
  }

  function onKeyDown(e) {
    if (e.key === "Enter") {
      e.preventDefault();
      commit(draft);
      return;
    }
    if (e.key === "Backspace" && !draft && value.length) {
      onChange(value.slice(0, -1));
    }
  }

  function onInputChange(e) {
    const v = e.target.value;
    if (hasSeparator(v)) {
      commit(v);
      return;
    }
    setDraft(v);
  }

  function removeAt(i) {
    const next = [...value];
    next.splice(i, 1);
    onChange(next);
  }

  function onDragStart(i) { dragIdx.current = i; }
  function onDragEnter(i) { setOverIdx(i); }
  function onDragEnd() {
    const from = dragIdx.current;
    const to = overIdx;
    if (from !== null && to !== null && from !== to) {
      const next = [...value];
      const [moved] = next.splice(from, 1);
      next.splice(to, 0, moved);
      onChange(next);
    }
    dragIdx.current = null;
    setOverIdx(null);
  }

  return (
    <div
      onClick={(e) => {
        if (e.currentTarget === e.target) inputRef.current?.focus();
      }}
      style={{
        display: "flex",
        flexWrap: "wrap",
        gap: 5,
        padding: "5px 6px",
        minHeight: 32,
        border: "1px solid var(--border)",
        borderRadius: 5,
        background: "var(--bg)",
        alignItems: "center",
        cursor: "text",
      }}
    >
      {value.map((name, i) => {
        const isOver = overIdx === i && dragIdx.current !== i;
        return (
          <span
            key={`${name}-${i}`}
            draggable
            onDragStart={() => onDragStart(i)}
            onDragEnter={() => onDragEnter(i)}
            onDragOver={(e) => e.preventDefault()}
            onDragEnd={onDragEnd}
            style={{
              display: "inline-flex",
              alignItems: "center",
              gap: 4,
              padding: "2px 4px 2px 8px",
              borderRadius: 11,
              background: isOver ? "var(--accent-bg)" : "var(--code-bg)",
              border: `1px solid ${isOver ? "var(--accent-border)" : "var(--border)"}`,
              fontSize: 12,
              color: "var(--text-h)",
              userSelect: "none",
              cursor: "grab",
              transition: "background 0.1s, border-color 0.1s",
            }}
          >
            {name}
            <button
              type="button"
              onClick={(e) => { e.stopPropagation(); removeAt(i); }}
              draggable={false}
              onDragStart={(e) => e.stopPropagation()}
              style={{
                border: "none",
                background: "transparent",
                color: "var(--text)",
                opacity: 0.55,
                cursor: "pointer",
                fontSize: 14,
                lineHeight: 1,
                padding: "0 2px",
              }}
            >
              ×
            </button>
          </span>
        );
      })}
      <input
        ref={inputRef}
        value={draft}
        onChange={onInputChange}
        onKeyDown={onKeyDown}
        onBlur={() => draft && commit(draft)}
        placeholder={value.length ? "" : placeholder || ""}
        style={{
          flex: 1,
          minWidth: 90,
          border: "none",
          outline: "none",
          background: "transparent",
          color: "var(--text-h)",
          fontSize: 13,
          padding: "2px 0",
        }}
      />
    </div>
  );
}
