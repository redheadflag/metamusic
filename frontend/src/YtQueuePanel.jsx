import { useState, useEffect } from "react";

const API = "/api";

const STATUS_COLOR = {
  pending: "var(--text)",
  claimed: "#e59a25",
  done:    "var(--accent)",
  failed:  "var(--danger)",
};

export default function YtQueuePanel({ onBack }) {
  const [items,   setItems]   = useState([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let active = true;

    async function load() {
      try {
        const res = await fetch(`${API}/yt-queue`);
        if (res.ok && active) setItems(await res.json());
      } catch {}
      if (active) setLoading(false);
    }

    load();
    const id = setInterval(load, 10_000);
    return () => { active = false; clearInterval(id); };
  }, []);

  const counts = items.reduce((acc, it) => {
    acc[it.status] = (acc[it.status] || 0) + 1;
    return acc;
  }, {});

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>

      {/* Header */}
      <div style={{ display: "flex", alignItems: "center", gap: 14, flexWrap: "wrap" }}>
        <span style={{ fontSize: 15, fontWeight: 600, color: "var(--text-h)" }}>
          Download queue
        </span>
        {!loading && (
          <>
            {(counts.pending || 0) > 0 && (
              <span style={{ fontSize: 12, color: STATUS_COLOR.pending }}>
                {counts.pending} pending
              </span>
            )}
            {(counts.claimed || 0) > 0 && (
              <span style={{ fontSize: 12, color: STATUS_COLOR.claimed }}>
                {counts.claimed} active
              </span>
            )}
            {(counts.done || 0) > 0 && (
              <span style={{ fontSize: 12, color: STATUS_COLOR.done }}>
                {counts.done} done
              </span>
            )}
            {(counts.failed || 0) > 0 && (
              <span style={{ fontSize: 12, color: STATUS_COLOR.failed }}>
                {counts.failed} failed
              </span>
            )}
          </>
        )}
        {loading && (
          <span style={{ fontSize: 12, color: "var(--text)", opacity: 0.5 }}>Loading…</span>
        )}
      </div>

      {/* Item list */}
      {!loading && items.length > 0 && (
        <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
          {items.map(item => (
            <div
              key={item.id}
              style={{
                display: "flex",
                alignItems: "center",
                gap: 10,
                padding: "7px 10px",
                borderRadius: "var(--radius)",
                border: "1px solid var(--border)",
                fontSize: 12,
              }}
            >
              <span style={{
                flexShrink: 0,
                fontWeight: 600,
                color: STATUS_COLOR[item.status] || "var(--text)",
                width: 52,
                textTransform: "uppercase",
                fontSize: 10,
                letterSpacing: "0.05em",
              }}>
                {item.status}
              </span>
              <span style={{
                flex: 1,
                overflow: "hidden",
                textOverflow: "ellipsis",
                whiteSpace: "nowrap",
                color: "var(--text-h)",
              }}>
                {item.title}
              </span>
              <span style={{
                flexShrink: 0,
                color: "var(--text)",
                opacity: 0.5,
                overflow: "hidden",
                textOverflow: "ellipsis",
                whiteSpace: "nowrap",
                maxWidth: 160,
              }}>
                {(item.artists || []).join(", ")}
              </span>
              {item.error && (
                <span
                  title={item.error}
                  style={{
                    flexShrink: 0,
                    color: "var(--danger)",
                    fontSize: 11,
                    maxWidth: 200,
                    overflow: "hidden",
                    textOverflow: "ellipsis",
                    whiteSpace: "nowrap",
                  }}
                >
                  {item.error}
                </span>
              )}
            </div>
          ))}
        </div>
      )}

      {!loading && items.length === 0 && (
        <p style={{ fontSize: 13, color: "var(--text)", opacity: 0.5, margin: 0 }}>
          Queue is empty.
        </p>
      )}

      <div>
        <button onClick={onBack} style={{ fontSize: 12, opacity: 0.6 }}>
          ← Back
        </button>
      </div>
    </div>
  );
}
