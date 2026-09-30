/* Référence design (handoff) — NON compilé. Source canonique : composant du DS Nokido. */
import * as React from "react";

function TextInput({
  value,
  onChange,
  placeholder = "",
  label = null,
  hint = null,
  type = "text",
  multiline = false,
  rows = 3,
  disabled = false,
  invalid = false,
  icon = null,
  style = {},
  ...rest
}) {
  const [focused, setFocused] = React.useState(false);

  const fieldStyle = {
    width: "100%",
    background: "var(--bg-0)",
    color: "var(--text-primary)",
    border: `1px solid ${invalid ? "var(--red)" : focused ? "var(--purple)" : "var(--border)"}`,
    borderRadius: "var(--radius-sm)",
    padding: icon ? "7px 10px 7px 34px" : "7px 10px",
    fontFamily: "var(--font-sans)",
    fontSize: "13px",
    lineHeight: 1.5,
    outline: "none",
    boxShadow: focused ? "var(--focus-ring)" : "none",
    transition: "border-color var(--motion-fast), box-shadow var(--motion-fast)",
    resize: multiline ? "vertical" : "none",
    opacity: disabled ? 0.5 : 1,
    ...style,
  };

  const field = multiline ? (
    <textarea
      value={value} onChange={onChange} placeholder={placeholder} rows={rows} disabled={disabled}
      onFocus={() => setFocused(true)} onBlur={() => setFocused(false)} style={fieldStyle} {...rest}
    />
  ) : (
    <input
      type={type} value={value} onChange={onChange} placeholder={placeholder} disabled={disabled}
      onFocus={() => setFocused(true)} onBlur={() => setFocused(false)} style={fieldStyle} {...rest}
    />
  );

  return (
    <label style={{ display: "block" }}>
      {label && (
        <span style={{ display: "block", fontSize: "11px", fontWeight: 600, textTransform: "uppercase",
          letterSpacing: "0.5px", color: "var(--text-secondary)", marginBottom: "6px" }}>{label}</span>
      )}
      <span style={{ position: "relative", display: "block" }}>
        {icon && (
          <span style={{ position: "absolute", left: "10px", top: "50%", transform: "translateY(-50%)",
            display: "inline-flex", width: "16px", height: "16px", color: "var(--text-dim)", pointerEvents: "none" }}>{icon}</span>
        )}
        {field}
      </span>
      {hint && (
        <span style={{ display: "block", fontSize: "11px", color: invalid ? "var(--red)" : "var(--text-dim)",
          marginTop: "5px", fontFamily: "var(--font-mono)" }}>{hint}</span>
      )}
    </label>
  );
}
