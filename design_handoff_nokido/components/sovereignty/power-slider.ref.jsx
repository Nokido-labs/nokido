/* Référence design (handoff) — NON compilé. Source canonique : composant du DS Nokido. */
import * as React from "react";

function PowerSlider({
  value = 60,
  onChange = null,
  style = {},
}) {
  const [internal, setInternal] = React.useState(value);
  const v = onChange ? value : internal;

  function set(next) {
    if (onChange) onChange(next);
    else setInternal(next);
  }

  // Dérivés lisibles en temps réel : plus de puissance allouée → plus local.
  const localShare = v;
  const privacy = v;                       // ↑ avec le local
  const cost = Math.round(100 - v * 0.85);  // cloud = coût
  const latency = Math.round(30 + (100 - v) * 0.9); // cloud = +latence réseau

  const metric = (lbl, val, unit, color) => (
    <div style={{ flex: 1 }}>
      <div style={{ fontSize: "10px", textTransform: "uppercase", letterSpacing: "0.5px", color: "var(--text-dim)" }}>{lbl}</div>
      <div style={{ fontFamily: "var(--font-mono)", fontSize: "14px", fontWeight: 700, color }}>{val}{unit}</div>
    </div>
  );

  return (
    <div style={{
      background: "var(--bg-2)", border: "1px solid var(--border)", borderRadius: "var(--radius-md)",
      padding: "16px", ...style,
    }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline", marginBottom: "12px" }}>
        <span style={{ fontSize: "13px", fontWeight: 600, color: "var(--text-primary)" }}>Puissance de calcul allouée</span>
        <span style={{ fontFamily: "var(--font-mono)", fontSize: "13px", color: "var(--prov-local)" }}>{v}%</span>
      </div>

      <input
        type="range" min="0" max="100" value={v}
        onChange={(e) => set(Number(e.target.value))}
        style={{
          width: "100%", appearance: "none", WebkitAppearance: "none", height: "6px",
          borderRadius: "var(--radius-pill)", outline: "none", cursor: "pointer",
          background: `linear-gradient(90deg, var(--prov-local) 0%, var(--prov-local) ${v}%, var(--prov-remote-tint) ${v}%, var(--prov-remote-tint) 100%)`,
        }}
        className="lf-power-range"
      />
      <div style={{ display: "flex", justifyContent: "space-between", marginTop: "6px",
        fontFamily: "var(--font-mono)", fontSize: "10px", color: "var(--text-dim)" }}>
        <span>← cloud (délègue)</span>
        <span>local (souverain) →</span>
      </div>

      <div style={{ display: "flex", gap: "12px", marginTop: "16px", paddingTop: "14px", borderTop: "1px solid var(--border-subtle)" }}>
        {metric("Confidentialité", privacy, "%", "var(--prov-local)")}
        {metric("Local", localShare, "%", "var(--prov-hybrid)")}
        {metric("Coût relatif", cost, "%", "var(--orange)")}
        {metric("Latence", latency, "ms", "var(--blue)")}
      </div>

      <style>{`
        .lf-power-range::-webkit-slider-thumb {
          -webkit-appearance: none; width: 18px; height: 18px; border-radius: 50%;
          background: #fff; border: 3px solid var(--prov-local);
          box-shadow: 0 0 10px rgba(74,194,139,0.5); cursor: pointer;
        }
        .lf-power-range::-moz-range-thumb {
          width: 18px; height: 18px; border-radius: 50%;
          background: #fff; border: 3px solid var(--prov-local);
          box-shadow: 0 0 10px rgba(74,194,139,0.5); cursor: pointer;
        }
      `}</style>
    </div>
  );
}
