/* Référence design (handoff) — NON compilé. Source canonique : composant du DS Nokido. */
function Card({
  children,
  title = null,
  subtitle = null,
  icon = null,
  iconColor = "purple",
  interactive = false,
  href = null,
  footer = null,
  style = {},
  ...rest
}) {
  const tints = {
    purple: "var(--tint-purple)", blue: "var(--tint-blue)", cyan: "var(--tint-cyan)",
    green: "var(--tint-green)", yellow: "var(--tint-yellow)", orange: "var(--tint-orange)",
    red: "var(--tint-red)", pink: "var(--tint-pink)",
  };
  const colors = {
    purple: "var(--purple)", blue: "var(--blue)", cyan: "var(--cyan)",
    green: "var(--green)", yellow: "var(--yellow)", orange: "var(--orange)",
    red: "var(--red)", pink: "var(--pink)",
  };

  const base = {
    display: "block",
    position: "relative",
    overflow: "hidden",
    background: "var(--bg-2)",
    border: "1px solid var(--border)",
    borderRadius: "var(--radius-md)",
    padding: "16px",
    boxShadow: "var(--shadow-md)",
    color: "var(--text-primary)",
    textDecoration: "none",
    transition: "background var(--motion-base), box-shadow var(--motion-base)",
    cursor: interactive || href ? "pointer" : "default",
    ...style,
  };

  function onEnter(e) {
    if (!interactive && !href) return;
    e.currentTarget.style.background = "var(--bg-3)";
    e.currentTarget.style.boxShadow = "var(--shadow-glow)";
  }
  function onLeave(e) {
    if (!interactive && !href) return;
    e.currentTarget.style.background = "var(--bg-2)";
    e.currentTarget.style.boxShadow = "var(--shadow-md)";
  }

  const inner = (
    <>
      {icon && (
        <span style={{
          display: "inline-flex", alignItems: "center", justifyContent: "center",
          height: "44px", width: "44px", borderRadius: "var(--radius-sm)",
          background: tints[iconColor], color: colors[iconColor], marginBottom: "10px",
        }}>{icon}</span>
      )}
      {title && (
        <h3 style={{ margin: 0, fontSize: "16px", fontWeight: 700, color: "var(--text-primary)" }}>{title}</h3>
      )}
      {subtitle && (
        <p style={{ margin: "4px 0 0", fontSize: "12.5px", color: "var(--text-secondary)", lineHeight: 1.45 }}>{subtitle}</p>
      )}
      {children}
      {footer && (
        <div style={{ marginTop: "14px", fontSize: "11px", fontFamily: "var(--font-mono)", color: "var(--text-dim)" }}>{footer}</div>
      )}
    </>
  );

  if (href) {
    return <a href={href} style={base} onMouseEnter={onEnter} onMouseLeave={onLeave} {...rest}>{inner}</a>;
  }
  return <div style={base} onMouseEnter={onEnter} onMouseLeave={onLeave} {...rest}>{inner}</div>;
}
