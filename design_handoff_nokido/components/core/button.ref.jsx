/* Référence design (handoff) — NON compilé. Source canonique : composant du DS Nokido. */
function Button({
  children,
  variant = "primary",
  size = "md",
  icon = null,
  iconRight = null,
  disabled = false,
  type = "button",
  onClick,
  style = {},
  ...rest
}) {
  const sizes = {
    sm: { padding: "4px 10px", fontSize: "12px", height: "30px" },
    md: { padding: "6px 14px", fontSize: "13.5px", height: "36px" },
    lg: { padding: "9px 18px", fontSize: "14px", height: "44px" },
  };

  const variants = {
    primary: { background: "var(--purple)", color: "#fff", border: "1px solid transparent" },
    ghost: { background: "transparent", color: "var(--text-secondary)", border: "1px solid var(--border)" },
    danger: { background: "var(--red)", color: "#fff", border: "1px solid transparent" },
    success: { background: "var(--green)", color: "var(--bg-0)", border: "1px solid transparent" },
  };

  const base = {
    display: "inline-flex",
    alignItems: "center",
    justifyContent: "center",
    gap: "7px",
    fontFamily: "var(--font-sans)",
    fontWeight: 600,
    borderRadius: "var(--radius-sm)",
    cursor: disabled ? "not-allowed" : "pointer",
    opacity: disabled ? 0.4 : 1,
    transition: "background var(--motion-fast), border-color var(--motion-fast), color var(--motion-fast)",
    whiteSpace: "nowrap",
    ...sizes[size],
    ...variants[variant],
    ...style,
  };

  const hoverBg = {
    primary: "var(--purple-dim)",
    ghost: "transparent",
    danger: "#d83b3b",
    success: "#3fae7a",
  };

  function onEnter(e) {
    if (disabled) return;
    if (variant === "ghost") {
      e.currentTarget.style.color = "var(--purple)";
      e.currentTarget.style.borderColor = "var(--purple)";
    } else {
      e.currentTarget.style.background = hoverBg[variant];
    }
  }
  function onLeave(e) {
    if (disabled) return;
    if (variant === "ghost") {
      e.currentTarget.style.color = "var(--text-secondary)";
      e.currentTarget.style.borderColor = "var(--border)";
    } else {
      e.currentTarget.style.background = variants[variant].background;
    }
  }

  return (
    <button
      type={type}
      disabled={disabled}
      onClick={onClick}
      onMouseEnter={onEnter}
      onMouseLeave={onLeave}
      style={base}
      {...rest}
    >
      {icon && <span style={{ display: "inline-flex", width: "16px", height: "16px" }}>{icon}</span>}
      {children}
      {iconRight && <span style={{ display: "inline-flex", width: "16px", height: "16px" }}>{iconRight}</span>}
    </button>
  );
}
