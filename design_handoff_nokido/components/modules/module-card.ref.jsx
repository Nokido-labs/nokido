/* Référence design (handoff) — NON compilé. Source canonique : composant du DS Nokido. */
import * as React from "react";

function ModuleCard({
  domain = "transport",
  title,
  desc = null,
  icon = null,
  enabled = true,
  onToggle = null,
  provenance = null,   // "local" | "hybrid" | "remote"
  status = null,       // "up" | "down" | "warn"
  pinned = false,
  comingSoon = false,
  style = {},
}) {
  const accent = `var(--domain-${domain})`;

  const dot = { up: "var(--green)", down: "var(--red)", warn: "var(--yellow)" }[status];
  const provColor = provenance ? { local: "var(--prov-local)", hybrid: "var(--prov-hybrid)", remote: "var(--prov-remote)" }[provenance] : null;
  const provText = provenance ? { local: "LOCAL", hybrid: "HYBRIDE", remote: "DISTANT" }[provenance] : null;

  const dim = comingSoon || !enabled;

  return (
    <div style={{
      position: "relative", background: dim ? "var(--bg-1)" : "var(--bg-2)",
      border: `1px solid ${dim ? "var(--border-subtle)" : "var(--border)"}`,
      borderRadius: "var(--radius-md)", padding: "16px", overflow: "hidden",
      opacity: comingSoon ? 0.55 : 1, transition: "background var(--motion-base)", ...style,
    }}>
      {/* Filet d'accent de domaine */}
      <div style={{ position: "absolute", left: 0, top: 0, bottom: 0, width: "3px", background: accent }} />

      <div style={{ display: "flex", alignItems: "flex-start", justifyContent: "space-between", gap: "10px" }}>
        <div style={{
          display: "inline-flex", alignItems: "center", justifyContent: "center",
          height: "40px", width: "40px", borderRadius: "var(--radius-sm)",
          background: `color-mix(in srgb, ${accent} 16%, transparent)`, color: accent,
        }}>{icon}</div>

        {comingSoon ? (
          <span style={{ fontFamily: "var(--font-mono)", fontSize: "9.5px", fontWeight: 700, letterSpacing: "0.3px",
            color: "var(--text-dim)", border: "1px solid var(--border)", borderRadius: "4px", padding: "1px 6px" }}>BIENTÔT</span>
        ) : onToggle ? (
          <button onClick={() => onToggle(!enabled)} aria-label="Activer le module" style={{
            width: "38px", height: "22px", borderRadius: "var(--radius-pill)", border: "none", cursor: "pointer",
            background: enabled ? accent : "var(--bg-4)", position: "relative", transition: "background var(--motion-fast)", flexShrink: 0,
          }}>
            <span style={{ position: "absolute", top: "3px", left: enabled ? "19px" : "3px", width: "16px", height: "16px",
              borderRadius: "50%", background: "#fff", transition: "left var(--motion-fast)" }} />
          </button>
        ) : (
          status && <span style={{ width: "10px", height: "10px", borderRadius: "50%", background: dot,
            animation: status === "up" ? "laforge-pulse var(--pulse-period) infinite" : "none" }} />
        )}
      </div>

      <h3 style={{ margin: "12px 0 0", fontSize: "16px", fontWeight: 700, color: dim ? "var(--text-secondary)" : "var(--text-primary)",
        display: "flex", alignItems: "center", gap: "7px" }}>
        {title}
        {pinned && (
          <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke={accent} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" style={{ flexShrink: 0 }}>
            <path d="M12 17v5" />
            <path d="M9 10.76a2 2 0 0 1-1.11 1.79l-1.78.9A2 2 0 0 0 5 15.24V16a1 1 0 0 0 1 1h12a1 1 0 0 0 1-1v-.76a2 2 0 0 0-1.11-1.79l-1.78-.9A2 2 0 0 1 15 10.76V7a1 1 0 0 1 1-1 2 2 0 0 0 0-4H8a2 2 0 0 0 0 4 1 1 0 0 1 1 1z" />
          </svg>
        )}
      </h3>
      {desc && <p style={{ margin: "4px 0 0", fontSize: "12.5px", color: "var(--text-secondary)", lineHeight: 1.45 }}>{desc}</p>}

      {provText && (
        <div style={{ marginTop: "12px" }}>
          <span style={{ display: "inline-flex", alignItems: "center", gap: "6px", fontFamily: "var(--font-mono)",
            fontSize: "10px", fontWeight: 600, color: provColor }}>
            <span style={{ width: "6px", height: "6px", borderRadius: "50%", background: "currentColor" }} />{provText}
          </span>
        </div>
      )}
    </div>
  );
}
