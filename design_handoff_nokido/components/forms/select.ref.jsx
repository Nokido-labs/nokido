/* Référence design (handoff) — NON compilé. Source canonique : composant du DS Nokido. */
import * as React from "react";

function Select({
  value,
  onChange,
  options = [],
  label = null,
  disabled = false,
  style = {},
  ...rest
}) {
  const [focused, setFocused] = React.useState(false);
  const norm = options.map((o) => (typeof o === "string" ? { value: o, label: o } : o));

  return (
    <label style={{ display: "block" }}>
      {label && (
        <span style={{ display: "block", fontSize: "11px", fontWeight: 600, textTransform: "uppercase",
          letterSpacing: "0.5px", color: "var(--text-secondary)", marginBottom: "6px" }}>{label}</span>
      )}
      <span style={{ position: "relative", display: "block" }}>
        <select
          value={value} onChange={onChange} disabled={disabled}
          onFocus={() => setFocused(true)} onBlur={() => setFocused(false)}
          style={{
            width: "100%", appearance: "none", WebkitAppearance: "none",
            background: "var(--bg-0)", color: "var(--text-primary)",
            border: `1px solid ${focused ? "var(--purple)" : "var(--border)"}`,
            borderRadius: "var(--radius-sm)", padding: "7px 30px 7px 10px",
            fontFamily: "var(--font-sans)", fontSize: "13px", outline: "none",
            boxShadow: focused ? "var(--focus-ring)" : "none",
            cursor: disabled ? "not-allowed" : "pointer", opacity: disabled ? 0.5 : 1,
            transition: "border-color var(--motion-fast), box-shadow var(--motion-fast)", ...style,
          }}
          {...rest}
        >
          {norm.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
        </select>
        <span style={{ position: "absolute", right: "10px", top: "50%", transform: "translateY(-50%)",
          pointerEvents: "none", color: "var(--text-dim)", fontSize: "10px" }}>▾</span>
      </span>
    </label>
  );
}
