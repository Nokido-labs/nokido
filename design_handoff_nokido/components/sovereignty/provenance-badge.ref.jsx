/* Référence design (handoff) — NON compilé. Source canonique : composant du DS Nokido. */
function ProvenanceBadge({
  origin = "local",
  ring = null,
  label = null,
  detail = null,
  size = "md",
  style = {},
}) {
  const origins = {
    local:  { color: "var(--prov-local)",  bg: "var(--prov-local-tint)",  text: "LOCAL" },
    hybrid: { color: "var(--prov-hybrid)", bg: "var(--prov-hybrid-tint)", text: "HYBRIDE" },
    remote: { color: "var(--prov-remote)", bg: "var(--prov-remote-tint)", text: "DISTANT" },
  };
  const rings = {
    draft:    { color: "var(--ring-draft)",    text: "brouillon" },
    verified: { color: "var(--ring-verified)", text: "vérifié" },
    gold:     { color: "var(--ring-gold)",     text: "or" },
  };
  const o = origins[origin] || origins.local;
  const r = ring ? rings[ring] : null;
  const sm = size === "sm";

  return (
    <span style={{
      display: "inline-flex", alignItems: "center", gap: "7px",
      fontFamily: "var(--font-mono)", fontSize: sm ? "10px" : "11px", fontWeight: 600,
      padding: sm ? "2px 8px" : "3px 10px", borderRadius: "var(--radius-pill)",
      color: o.color, background: o.bg, ...style,
    }}>
      <span style={{ width: sm ? "6px" : "7px", height: sm ? "6px" : "7px", borderRadius: "50%", background: "currentColor" }} />
      <span>{label || o.text}</span>
      {r && (
        <>
          <span style={{ width: "1px", height: "10px", background: "currentColor", opacity: 0.3 }} />
          <span style={{
            display: "inline-flex", alignItems: "center", gap: "4px", color: r.color, opacity: 0.95,
          }}>
            <span style={{
              width: "8px", height: "8px", borderRadius: "50%",
              background: ring === "draft" ? "transparent" : r.color,
              border: ring === "draft" ? `1.5px dashed ${r.color}` : "none",
              boxShadow: ring === "gold" ? "0 0 6px rgba(255,194,45,0.6)" : "none",
            }} />
            {r.text}
          </span>
        </>
      )}
      {detail && <span style={{ color: "var(--text-dim)", fontWeight: 400 }}>· {detail}</span>}
    </span>
  );
}
