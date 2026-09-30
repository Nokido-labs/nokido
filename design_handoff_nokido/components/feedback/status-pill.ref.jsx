/* Référence design (handoff) — NON compilé. Source canonique : composant du DS Nokido. */
function StatusPill({
  children,
  status = "info",
  pulse = false,
  style = {},
}) {
  const map = {
    up:   { color: "var(--green)",  bg: "rgba(74, 194, 139, 0.12)" },
    down: { color: "var(--red)",    bg: "rgba(242, 79, 79, 0.12)" },
    warn: { color: "var(--yellow)", bg: "rgba(255, 194, 45, 0.12)" },
    info: { color: "var(--blue)",   bg: "rgba(59, 178, 208, 0.12)" },
    idle: { color: "var(--text-dim)", bg: "rgba(110, 106, 130, 0.12)" },
  };
  const c = map[status] || map.info;

  return (
    <span style={{
      display: "inline-flex", alignItems: "center", gap: "6px",
      fontSize: "11px", fontFamily: "var(--font-mono)",
      padding: "2px 8px", borderRadius: "var(--radius-pill)",
      color: c.color, background: c.bg, ...style,
    }}>
      <span style={{
        width: "6px", height: "6px", borderRadius: "50%", background: "currentColor",
        animation: pulse ? "laforge-pulse var(--pulse-period) infinite" : "none",
      }} />
      {children}
    </span>
  );
}
