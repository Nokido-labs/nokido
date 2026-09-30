/* Référence design (handoff) — NON compilé. Source canonique : composant du DS Nokido. */
function SovereigntyGauge({
  local = 70,
  label = "Souveraineté",
  showLegend = true,
  height = 10,
  style = {},
}) {
  const pct = Math.max(0, Math.min(100, local));

  return (
    <div style={{ ...style }}>
      {label && (
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline", marginBottom: "7px" }}>
          <span style={{ fontSize: "11px", fontWeight: 600, textTransform: "uppercase", letterSpacing: "0.5px", color: "var(--text-secondary)" }}>{label}</span>
          <span style={{ fontFamily: "var(--font-mono)", fontSize: "12px", color: "var(--prov-local)" }}>{pct}% local</span>
        </div>
      )}
      <div style={{
        position: "relative", height: `${height}px`, borderRadius: "var(--radius-pill)",
        background: "var(--prov-remote-tint)", overflow: "hidden", border: "1px solid var(--border-subtle)",
      }}>
        <div style={{
          position: "absolute", left: 0, top: 0, bottom: 0, width: `${pct}%`,
          background: "linear-gradient(90deg, var(--prov-local), #5fd6a0)",
          boxShadow: "0 0 12px rgba(74,194,139,0.4)",
          transition: "width var(--motion-slow) var(--ease-out)",
        }} />
      </div>
      {showLegend && (
        <div style={{ display: "flex", justifyContent: "space-between", marginTop: "6px",
          fontFamily: "var(--font-mono)", fontSize: "10px", color: "var(--text-dim)" }}>
          <span style={{ color: "var(--prov-local)" }}>● local · souverain</span>
          <span style={{ color: "var(--prov-remote)" }}>distant · cloud ●</span>
        </div>
      )}
    </div>
  );
}
