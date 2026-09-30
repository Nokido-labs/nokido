/* Référence design (handoff) — NON compilé. Source canonique : composant du DS Nokido. */
function Badge({
  children,
  color = "purple",
  variant = "soft",
  mono = false,
  style = {},
}) {
  const colors = {
    purple: "var(--purple)", blue: "var(--blue)", cyan: "var(--cyan)",
    green: "var(--green)", yellow: "var(--yellow)", orange: "var(--orange)",
    red: "var(--red)", pink: "var(--pink)", dim: "var(--text-dim)",
  };
  const tints = {
    purple: "var(--tint-purple)", blue: "var(--tint-blue)", cyan: "var(--tint-cyan)",
    green: "var(--tint-green)", yellow: "var(--tint-yellow)", orange: "var(--tint-orange)",
    red: "var(--tint-red)", pink: "var(--tint-pink)", dim: "rgba(110,106,130,0.16)",
  };

  const variants = {
    soft: { background: tints[color], color: colors[color], border: "1px solid transparent" },
    solid: { background: colors[color], color: "var(--bg-0)", border: "1px solid transparent" },
    outline: { background: "transparent", color: colors[color], border: `1px solid ${colors[color]}` },
  };

  return (
    <span style={{
      display: "inline-flex", alignItems: "center", gap: "5px",
      fontSize: mono ? "9.5px" : "11px",
      fontFamily: mono ? "var(--font-mono)" : "var(--font-sans)",
      fontWeight: mono ? 700 : 600,
      letterSpacing: mono ? "0.3px" : 0,
      padding: "2px 8px", borderRadius: "var(--radius-sm)",
      textTransform: mono ? "uppercase" : "none",
      ...variants[variant], ...style,
    }}>{children}</span>
  );
}
