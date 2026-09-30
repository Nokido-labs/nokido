/* Référence design (handoff) — NON compilé. Source canonique : composant du DS Nokido. */
import * as React from "react";

const RING_META = [
  { id: 0, label: "Ring 0", desc: "Lois absolues" },
  { id: 1, label: "Ring 1", desc: "Core Nokido" },
  { id: 2, label: "Ring 2", desc: "TRUSTED humain" },
  { id: 3, label: "Ring 3", desc: "Agents validés" },
  { id: 4, label: "Ring 4", desc: "Agents externes" },
  { id: 5, label: "Ring 5", desc: "RAG web" },
  { id: 6, label: "Ring 6", desc: "Outils CI/CD" },
  { id: 7, label: "Ring 7", desc: "SSH / réseau" },
  { id: 8, label: "Ring 8", desc: "Monitoring" },
  { id: 9, label: "Ring 9", desc: "Système hôte" },
  { id: 10, label: "Ring 10", desc: "Corrections de Cap" },
];

// Dégradé sémantique : centre vert (souverain/core) → extérieur violet (système/externe)
function ringColor(i) {
  const stops = [
    [74, 194, 139],   // vert (local, souverain)
    [45, 212, 191],   // cyan
    [59, 178, 208],   // bleu
    [119, 74, 255],   // violet (système, distant)
  ];
  const t = i / 10;
  const seg = t * (stops.length - 1);
  const k = Math.min(stops.length - 2, Math.floor(seg));
  const f = seg - k;
  const c = stops[k].map((v, j) => Math.round(v + (stops[k + 1][j] - v) * f));
  return `rgb(${c[0]}, ${c[1]}, ${c[2]})`;
}

const STATE_OVERRIDE = {
  alert: "var(--yellow)",
  block: "var(--red)",
  inactive: "var(--bg-4)",
};

function RingMeter({
  states = {},
  selected = null,
  onSelect = null,
  size = 300,
  showLegend = true,
  pulse = true,
  style = {},
}) {
  const cx = size / 2, cy = size / 2;
  const ringW = (size / 2 - 16) / 11;

  const radius = (i) => 16 + (i + 0.5) * ringW;

  return (
    <div style={{ display: "flex", gap: "18px", alignItems: "center", flexWrap: "wrap", ...style }}>
      <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`} style={{ flexShrink: 0 }}>
        {/* halo central */}
        <circle cx={cx} cy={cy} r={ringW * 0.6} fill={ringColor(0)} opacity={0.9} />
        {RING_META.map((r) => {
          const st = states[r.id] || "ok";
          const base = st === "ok" ? ringColor(r.id) : STATE_OVERRIDE[st];
          const on = selected === r.id;
          const isAnim = pulse && st === "alert";
          return (
            <circle
              key={r.id}
              cx={cx} cy={cy} r={radius(r.id)}
              fill="none"
              stroke={base}
              strokeWidth={on ? ringW * 0.95 : ringW * 0.7}
              opacity={st === "inactive" ? 0.4 : on ? 1 : 0.82}
              onClick={onSelect ? () => onSelect(r.id) : undefined}
              style={{
                cursor: onSelect ? "pointer" : "default",
                filter: on ? `drop-shadow(0 0 6px ${base})` : "none",
                transition: "stroke-width var(--motion-base), opacity var(--motion-base)",
                animation: isAnim ? "laforge-pulse var(--pulse-period) infinite" : "none",
              }}
            />
          );
        })}
        {/* étiquette centre */}
        <text x={cx} y={cy + 4} textAnchor="middle" fontFamily="var(--font-mono)" fontSize={size * 0.05} fontWeight="700" fill="var(--bg-0)">R0</text>
      </svg>

      {showLegend && (
        <div style={{ display: "flex", flexDirection: "column", gap: "3px", minWidth: "150px" }}>
          {RING_META.map((r) => {
            const st = states[r.id] || "ok";
            const c = st === "ok" ? ringColor(r.id) : STATE_OVERRIDE[st];
            const on = selected === r.id;
            return (
              <button
                key={r.id}
                onClick={onSelect ? () => onSelect(r.id) : undefined}
                style={{
                  display: "flex", alignItems: "center", gap: "8px", padding: "3px 7px",
                  border: "none", borderRadius: "var(--radius-sm)", cursor: onSelect ? "pointer" : "default",
                  background: on ? "var(--bg-3)" : "transparent", textAlign: "left", width: "100%",
                  fontFamily: "var(--font-sans)",
                }}
              >
                <span style={{ width: "10px", height: "10px", borderRadius: "50%", background: c, flexShrink: 0,
                  boxShadow: st === "block" ? `0 0 6px ${c}` : "none" }} />
                <span style={{ fontFamily: "var(--font-mono)", fontSize: "10px", color: "var(--text-dim)", width: "44px", flexShrink: 0 }}>{r.label}</span>
                <span style={{ fontSize: "11.5px", color: on ? "var(--text-primary)" : "var(--text-secondary)", fontWeight: on ? 600 : 400 }}>{r.desc}</span>
              </button>
            );
          })}
        </div>
      )}
    </div>
  );
}

RingMeter.RING_META = RING_META;
RingMeter.ringColor = ringColor;
