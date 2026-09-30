/* Référence design (handoff) — NON compilé. Source canonique : composant du DS Nokido. */
import * as React from "react";

function CapStep({
  index = 1,
  title,
  state = "pending",   // "done" | "active" | "pending"
  provenance = null,   // "local" | "hybrid" | "remote"
  ring = null,         // "draft" | "verified" | "gold"
  parallel = false,
  last = false,
  style = {},
}) {
  const states = {
    done:    { color: "var(--prov-local)", fill: "var(--prov-local)" },
    active:  { color: "var(--purple)",     fill: "var(--purple)" },
    pending: { color: "var(--text-dim)",   fill: "transparent" },
  };
  const s = states[state] || states.pending;
  const provColor = provenance ? { local: "var(--prov-local)", hybrid: "var(--prov-hybrid)", remote: "var(--prov-remote)" }[provenance] : null;
  const ringColor = ring ? { draft: "var(--ring-draft)", verified: "var(--ring-verified)", gold: "var(--ring-gold)" }[ring] : null;

  return (
    <div style={{ display: "flex", gap: "12px", ...style }}>
      {/* Colonne nœud + ligne */}
      <div style={{ display: "flex", flexDirection: "column", alignItems: "center" }}>
        <div style={{
          width: "22px", height: "22px", borderRadius: "50%", flexShrink: 0,
          border: `2px solid ${s.color}`, background: s.fill,
          display: "flex", alignItems: "center", justifyContent: "center",
          boxShadow: state === "active" ? "0 0 10px rgba(119,74,255,0.5)" : "none",
        }}>
          {state === "done" && <i data-lucide="check" style={{ width: "12px", height: "12px", color: "var(--bg-0)" }} />}
          {state === "active" && <span style={{ width: "7px", height: "7px", borderRadius: "50%", background: "#fff" }} />}
        </div>
        {!last && <div style={{ width: "2px", flex: 1, minHeight: "18px",
          background: state === "done" ? "var(--prov-local)" : "var(--border)", marginTop: "2px" }} />}
      </div>

      {/* Contenu */}
      <div style={{ paddingBottom: last ? 0 : "16px", flex: 1 }}>
        <div style={{ display: "flex", alignItems: "center", gap: "8px", flexWrap: "wrap" }}>
          <span style={{ fontFamily: "var(--font-mono)", fontSize: "10px", color: "var(--text-dim)" }}>
            {String(index).padStart(2, "0")}
          </span>
          <span style={{ fontSize: "13px", fontWeight: state === "pending" ? 400 : 600,
            color: state === "pending" ? "var(--text-secondary)" : "var(--text-primary)" }}>{title}</span>
          {parallel && <span style={{ fontFamily: "var(--font-mono)", fontSize: "9px", color: "var(--cyan)",
            border: "1px solid var(--cyan)", borderRadius: "3px", padding: "0 4px" }}>SILO //</span>}
        </div>
        {(provColor || ringColor) && (
          <div style={{ display: "flex", gap: "10px", marginTop: "5px", fontFamily: "var(--font-mono)", fontSize: "10px" }}>
            {provColor && <span style={{ color: provColor }}>● {provenance}</span>}
            {ringColor && <span style={{ color: ringColor }}>◆ {ring}</span>}
          </div>
        )}
      </div>
    </div>
  );
}
