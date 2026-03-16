import { useLang } from "./LangContext.jsx";

const modes = [
  {
    id: "files",
    icon: (
      <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
        <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/>
        <polyline points="14 2 14 8 20 8"/>
        <line x1="12" y1="18" x2="12" y2="12"/>
        <line x1="9"  y1="15" x2="15" y2="15"/>
      </svg>
    ),
    labelKey: "fromFiles",
    hintKey:  "fromFilesHint",
  },
  {
    id: "soundcloud",
    icon: (
      <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
        <path d="M3 18a3 3 0 0 1 0-6h.5A5.5 5.5 0 0 1 14 9.5V9a4 4 0 0 1 8 0v.5A4.5 4.5 0 0 1 17.5 18H3z"/>
      </svg>
    ),
    labelKey: "soundcloud",
    hintKey:  "soundcloudHint",
  },
];

export default function ModeSelector({ onSelect }) {
  const { t } = useLang();
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
      {modes.map((m) => (
        <button
          key={m.id}
          onClick={() => onSelect(m.id)}
          style={{
            display: "flex",
            alignItems: "center",
            gap: 16,
            padding: "18px 20px",
            borderRadius: "var(--radius)",
            border: "1px solid var(--border)",
            background: "transparent",
            textAlign: "left",
            cursor: "pointer",
            transition: "background 0.15s, border-color 0.15s",
            width: "100%",
            boxSizing: "border-box",
            minWidth: 0,
          }}
          onMouseEnter={(e) => {
            e.currentTarget.style.background  = "var(--accent-bg)";
            e.currentTarget.style.borderColor = "var(--accent-border)";
          }}
          onMouseLeave={(e) => {
            e.currentTarget.style.background  = "transparent";
            e.currentTarget.style.borderColor = "var(--border)";
          }}
        >
          <span style={{ color: "var(--accent)", flexShrink: 0 }}>{m.icon}</span>
          <div style={{ minWidth: 0, flex: 1 }}>
            <div style={{ fontSize: 14, fontWeight: 500, color: "var(--text-h)", marginBottom: 2 }}>
              {t(m.labelKey)}
            </div>
            <div style={{ fontSize: 12, color: "var(--text)", opacity: 0.55, whiteSpace: "normal", wordBreak: "break-word" }}>
              {t(m.hintKey)}
            </div>
          </div>
          <span style={{ marginLeft: "auto", color: "var(--text)", opacity: 0.3, fontSize: 16 }}>→</span>
        </button>
      ))}
    </div>
  );
}
