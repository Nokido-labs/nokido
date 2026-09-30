/* @ds-bundle: {"format":3,"namespace":"NokidoDesignSystem_bdc2ac","components":[{"name":"Button","sourcePath":"components/core/button.ref.jsx"},{"name":"Card","sourcePath":"components/core/card.ref.jsx"},{"name":"Badge","sourcePath":"components/feedback/badge.ref.jsx"},{"name":"StatusPill","sourcePath":"components/feedback/status-pill.ref.jsx"},{"name":"Select","sourcePath":"components/forms/select.ref.jsx"},{"name":"TextInput","sourcePath":"components/forms/text-input.ref.jsx"},{"name":"CapStep","sourcePath":"components/intent/cap-step.ref.jsx"},{"name":"ModuleCard","sourcePath":"components/modules/Modulecard.ref.jsx"},{"name":"RingMeter","sourcePath":"components/rings/ring-meter.ref.jsx"},{"name":"PowerSlider","sourcePath":"components/sovereignty/power-slider.ref.jsx"},{"name":"ProvenanceBadge","sourcePath":"components/sovereignty/Provenancebadge.ref.jsx"},{"name":"SovereigntyGauge","sourcePath":"components/sovereignty/sovereignty-gauge.ref.jsx"}],"sourceHashes":{"assets/laforge-prefs.js":"9d2ec82f59f7","components/core/button.ref.jsx":"738ab9b2ed53","components/core/card.ref.jsx":"97956ef8a404","components/feedback/badge.ref.jsx":"5edf9bd362de","components/feedback/status-pill.ref.jsx":"4610da58a3a9","components/forms/select.ref.jsx":"3cf527a5c4f0","components/forms/text-input.ref.jsx":"e383969dda5d","components/intent/cap-step.ref.jsx":"d6be1221cf6c","components/modules/Modulecard.ref.jsx":"623578325ba5","components/rings/ring-meter.ref.jsx":"0917f244ade4","components/sovereignty/power-slider.ref.jsx":"203be3aba8d9","components/sovereignty/Provenancebadge.ref.jsx":"667239ce25b6","components/sovereignty/sovereignty-gauge.ref.jsx":"ef351c40c297","design_handoff_nokido/assets/laforge-prefs.js":"9d2ec82f59f7","design_handoff_nokido/components/core/button.ref.jsx":"f28aa1231e9a","design_handoff_nokido/components/core/card.ref.jsx":"f4afbe8e9fd4","design_handoff_nokido/components/feedback/badge.ref.jsx":"9b41b2d53d4c","design_handoff_nokido/components/feedback/status-pill.ref.jsx":"e4cdfae8c7b7","design_handoff_nokido/components/forms/select.ref.jsx":"9412e04cc451","design_handoff_nokido/components/forms/text-input.ref.jsx":"7257eabadcdd","design_handoff_nokido/components/intent/cap-step.ref.jsx":"648588930963","design_handoff_nokido/components/modules/module-card.ref.jsx":"7d10999f2c19","design_handoff_nokido/components/sovereignty/power-slider.ref.jsx":"24f36da352e5","design_handoff_nokido/components/sovereignty/provenance-badge.ref.jsx":"cbf6499c206f","design_handoff_nokido/components/sovereignty/sovereignty-gauge.ref.jsx":"4dcf99f15d6c","design_handoff_nokido/ui_kits/composer/composer-app.ref.jsx":"34eebabc411f","design_handoff_nokido/ui_kits/hub/hub-shell.ref.jsx":"1faeef5112f9","design_handoff_nokido/ui_kits/hub/hub-views.ref.jsx":"df501557f9de","design_handoff_nokido/ui_kits/hub/mobile-hub.ref.jsx":"e8213f227a92","design_handoff_nokido/ui_kits/login/login-screen.ref.jsx":"8b5e2cedf5d2","design_handoff_nokido/ui_kits/onboarding/ios-frame.jsx":"be3343be4b51","design_handoff_nokido/ui_kits/onboarding/onboarding-screens.ref.jsx":"5211413c4757","design_handoff_nokido/ui_kits/webhub/tweaks-panel.jsx":"6591467622ed","design_handoff_nokido/ui_kits/webhub/web-hub-extra.ref.jsx":"3d641e5cba21","design_handoff_nokido/ui_kits/webhub/web-hub-screens.ref.jsx":"e38cc51775ae","design_handoff_nokido/ui_kits/webhub/web-hub.ref.jsx":"bc4393e22da4","ui_kits/composer/composer-app.ref.jsx":"34eebabc411f","ui_kits/hub/hub-shell.ref.jsx":"1faeef5112f9","ui_kits/hub/hub-views.ref.jsx":"df501557f9de","ui_kits/hub/mobile-hub.ref.jsx":"e8213f227a92","ui_kits/login/login-screen.ref.jsx":"8b5e2cedf5d2","ui_kits/onboarding/onboarding-screens.ref.jsx":"5211413c4757","ui_kits/onboarding/ios-frame.jsx":"be3343be4b51","ui_kits/webhub/web-hub.ref.jsx":"9e71f719810a","ui_kits/webhub/web-hub-extra.ref.jsx":"3d641e5cba21","ui_kits/webhub/web-hub-screens.ref.jsx":"e38cc51775ae","ui_kits/webhub/web-hub-setup.ref.jsx":"88ce420c6903","ui_kits/webhub/tweaks-panel.jsx":"6591467622ed"},"inlinedExternals":[],"unexposedExports":[]} */

(() => {

const __ds_ns = (window.NokidoDesignSystem_bdc2ac = window.NokidoDesignSystem_bdc2ac || {});

const __ds_scope = {};

(__ds_ns.__errors = __ds_ns.__errors || []);

// assets/laforge-prefs.js
try { (() => {
/* Nokido — préférences persistantes partagées entre écrans (localStorage).
   Clés : nokido.power (0-100), nokido.theme (dark|light|auto), nokido.lang (fr|en|es|de).
   Charger AVANT les scripts d'app : <script src="…/assets/laforge-prefs.js"></script> */
(function () {
  "use strict";

  var NS = "nokido.";
  function get(key, fallback) {
    try {
      var raw = localStorage.getItem(NS + key);
      return raw === null ? fallback : JSON.parse(raw);
    } catch (e) {
      return fallback;
    }
  }
  function set(key, value) {
    try {
      localStorage.setItem(NS + key, JSON.stringify(value));
    } catch (e) {}
  }
  function applyTheme(theme) {
    var t = theme || get("theme", "dark");
    document.documentElement.setAttribute("data-theme", t);
    return t;
  }
  function cycleTheme() {
    var order = ["dark", "light", "auto"];
    var cur = get("theme", "dark");
    var next = order[(order.indexOf(cur) + 1) % order.length];
    set("theme", next);
    applyTheme(next);
    return next;
  }
  // Applique le thème mémorisé dès le chargement (évite le flash).
  applyTheme();
  window.NokidoPrefs = {
    get: get,
    set: set,
    applyTheme: applyTheme,
    cycleTheme: cycleTheme
  };
})();
})(); } catch (e) { __ds_ns.__errors.push({ path: "assets/laforge-prefs.js", error: String((e && e.message) || e) }); }

// components/core/button.ref.jsx
try { (() => {
function _extends() { return _extends = Object.assign ? Object.assign.bind() : function (n) { for (var e = 1; e < arguments.length; e++) { var t = arguments[e]; for (var r in t) ({}).hasOwnProperty.call(t, r) && (n[r] = t[r]); } return n; }, _extends.apply(null, arguments); }
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
    sm: {
      padding: "4px 10px",
      fontSize: "12px",
      height: "30px"
    },
    md: {
      padding: "6px 14px",
      fontSize: "13.5px",
      height: "36px"
    },
    lg: {
      padding: "9px 18px",
      fontSize: "14px",
      height: "44px"
    }
  };
  const variants = {
    primary: {
      background: "var(--purple)",
      color: "#fff",
      border: "1px solid transparent"
    },
    ghost: {
      background: "transparent",
      color: "var(--text-secondary)",
      border: "1px solid var(--border)"
    },
    danger: {
      background: "var(--red)",
      color: "#fff",
      border: "1px solid transparent"
    },
    success: {
      background: "var(--green)",
      color: "var(--bg-0)",
      border: "1px solid transparent"
    }
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
    ...style
  };
  const hoverBg = {
    primary: "var(--purple-dim)",
    ghost: "transparent",
    danger: "#d83b3b",
    success: "#3fae7a"
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
  return /*#__PURE__*/React.createElement("button", _extends({
    type: type,
    disabled: disabled,
    onClick: onClick,
    onMouseEnter: onEnter,
    onMouseLeave: onLeave,
    style: base
  }, rest), icon && /*#__PURE__*/React.createElement("span", {
    style: {
      display: "inline-flex",
      width: "16px",
      height: "16px"
    }
  }, icon), children, iconRight && /*#__PURE__*/React.createElement("span", {
    style: {
      display: "inline-flex",
      width: "16px",
      height: "16px"
    }
  }, iconRight));
}
Object.assign(__ds_scope, { Button });
})(); } catch (e) { __ds_ns.__errors.push({ path: "components/core/button.ref.jsx", error: String((e && e.message) || e) }); }

// components/core/card.ref.jsx
try { (() => {
function _extends() { return _extends = Object.assign ? Object.assign.bind() : function (n) { for (var e = 1; e < arguments.length; e++) { var t = arguments[e]; for (var r in t) ({}).hasOwnProperty.call(t, r) && (n[r] = t[r]); } return n; }, _extends.apply(null, arguments); }
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
    purple: "var(--tint-purple)",
    blue: "var(--tint-blue)",
    cyan: "var(--tint-cyan)",
    green: "var(--tint-green)",
    yellow: "var(--tint-yellow)",
    orange: "var(--tint-orange)",
    red: "var(--tint-red)",
    pink: "var(--tint-pink)"
  };
  const colors = {
    purple: "var(--purple)",
    blue: "var(--blue)",
    cyan: "var(--cyan)",
    green: "var(--green)",
    yellow: "var(--yellow)",
    orange: "var(--orange)",
    red: "var(--red)",
    pink: "var(--pink)"
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
    ...style
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
  const inner = /*#__PURE__*/React.createElement(React.Fragment, null, icon && /*#__PURE__*/React.createElement("span", {
    style: {
      display: "inline-flex",
      alignItems: "center",
      justifyContent: "center",
      height: "44px",
      width: "44px",
      borderRadius: "var(--radius-sm)",
      background: tints[iconColor],
      color: colors[iconColor],
      marginBottom: "10px"
    }
  }, icon), title && /*#__PURE__*/React.createElement("h3", {
    style: {
      margin: 0,
      fontSize: "16px",
      fontWeight: 700,
      color: "var(--text-primary)"
    }
  }, title), subtitle && /*#__PURE__*/React.createElement("p", {
    style: {
      margin: "4px 0 0",
      fontSize: "12.5px",
      color: "var(--text-secondary)",
      lineHeight: 1.45
    }
  }, subtitle), children, footer && /*#__PURE__*/React.createElement("div", {
    style: {
      marginTop: "14px",
      fontSize: "11px",
      fontFamily: "var(--font-mono)",
      color: "var(--text-dim)"
    }
  }, footer));
  if (href) {
    return /*#__PURE__*/React.createElement("a", _extends({
      href: href,
      style: base,
      onMouseEnter: onEnter,
      onMouseLeave: onLeave
    }, rest), inner);
  }
  return /*#__PURE__*/React.createElement("div", _extends({
    style: base,
    onMouseEnter: onEnter,
    onMouseLeave: onLeave
  }, rest), inner);
}
Object.assign(__ds_scope, { Card });
})(); } catch (e) { __ds_ns.__errors.push({ path: "components/core/card.ref.jsx", error: String((e && e.message) || e) }); }

// components/feedback/badge.ref.jsx
try { (() => {
function Badge({
  children,
  color = "purple",
  variant = "soft",
  mono = false,
  style = {}
}) {
  const colors = {
    purple: "var(--purple)",
    blue: "var(--blue)",
    cyan: "var(--cyan)",
    green: "var(--green)",
    yellow: "var(--yellow)",
    orange: "var(--orange)",
    red: "var(--red)",
    pink: "var(--pink)",
    dim: "var(--text-dim)"
  };
  const tints = {
    purple: "var(--tint-purple)",
    blue: "var(--tint-blue)",
    cyan: "var(--tint-cyan)",
    green: "var(--tint-green)",
    yellow: "var(--tint-yellow)",
    orange: "var(--tint-orange)",
    red: "var(--tint-red)",
    pink: "var(--tint-pink)",
    dim: "rgba(110,106,130,0.16)"
  };
  const variants = {
    soft: {
      background: tints[color],
      color: colors[color],
      border: "1px solid transparent"
    },
    solid: {
      background: colors[color],
      color: "var(--bg-0)",
      border: "1px solid transparent"
    },
    outline: {
      background: "transparent",
      color: colors[color],
      border: `1px solid ${colors[color]}`
    }
  };
  return /*#__PURE__*/React.createElement("span", {
    style: {
      display: "inline-flex",
      alignItems: "center",
      gap: "5px",
      fontSize: mono ? "9.5px" : "11px",
      fontFamily: mono ? "var(--font-mono)" : "var(--font-sans)",
      fontWeight: mono ? 700 : 600,
      letterSpacing: mono ? "0.3px" : 0,
      padding: "2px 8px",
      borderRadius: "var(--radius-sm)",
      textTransform: mono ? "uppercase" : "none",
      ...variants[variant],
      ...style
    }
  }, children);
}
Object.assign(__ds_scope, { Badge });
})(); } catch (e) { __ds_ns.__errors.push({ path: "components/feedback/badge.ref.jsx", error: String((e && e.message) || e) }); }

// components/feedback/status-pill.ref.jsx
try { (() => {
function StatusPill({
  children,
  status = "info",
  pulse = false,
  style = {}
}) {
  const map = {
    up: {
      color: "var(--green)",
      bg: "rgba(74, 194, 139, 0.12)"
    },
    down: {
      color: "var(--red)",
      bg: "rgba(242, 79, 79, 0.12)"
    },
    warn: {
      color: "var(--yellow)",
      bg: "rgba(255, 194, 45, 0.12)"
    },
    info: {
      color: "var(--blue)",
      bg: "rgba(59, 178, 208, 0.12)"
    },
    idle: {
      color: "var(--text-dim)",
      bg: "rgba(110, 106, 130, 0.12)"
    }
  };
  const c = map[status] || map.info;
  return /*#__PURE__*/React.createElement("span", {
    style: {
      display: "inline-flex",
      alignItems: "center",
      gap: "6px",
      fontSize: "11px",
      fontFamily: "var(--font-mono)",
      padding: "2px 8px",
      borderRadius: "var(--radius-pill)",
      color: c.color,
      background: c.bg,
      ...style
    }
  }, /*#__PURE__*/React.createElement("span", {
    style: {
      width: "6px",
      height: "6px",
      borderRadius: "50%",
      background: "currentColor",
      animation: pulse ? "laforge-pulse var(--pulse-period) infinite" : "none"
    }
  }), children);
}
Object.assign(__ds_scope, { StatusPill });
})(); } catch (e) { __ds_ns.__errors.push({ path: "components/feedback/status-pill.ref.jsx", error: String((e && e.message) || e) }); }

// components/forms/select.ref.jsx
try { (() => {
function _extends() { return _extends = Object.assign ? Object.assign.bind() : function (n) { for (var e = 1; e < arguments.length; e++) { var t = arguments[e]; for (var r in t) ({}).hasOwnProperty.call(t, r) && (n[r] = t[r]); } return n; }, _extends.apply(null, arguments); }
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
  const norm = options.map(o => typeof o === "string" ? {
    value: o,
    label: o
  } : o);
  return /*#__PURE__*/React.createElement("label", {
    style: {
      display: "block"
    }
  }, label && /*#__PURE__*/React.createElement("span", {
    style: {
      display: "block",
      fontSize: "11px",
      fontWeight: 600,
      textTransform: "uppercase",
      letterSpacing: "0.5px",
      color: "var(--text-secondary)",
      marginBottom: "6px"
    }
  }, label), /*#__PURE__*/React.createElement("span", {
    style: {
      position: "relative",
      display: "block"
    }
  }, /*#__PURE__*/React.createElement("select", _extends({
    value: value,
    onChange: onChange,
    disabled: disabled,
    onFocus: () => setFocused(true),
    onBlur: () => setFocused(false),
    style: {
      width: "100%",
      appearance: "none",
      WebkitAppearance: "none",
      background: "var(--bg-0)",
      color: "var(--text-primary)",
      border: `1px solid ${focused ? "var(--purple)" : "var(--border)"}`,
      borderRadius: "var(--radius-sm)",
      padding: "7px 30px 7px 10px",
      fontFamily: "var(--font-sans)",
      fontSize: "13px",
      outline: "none",
      boxShadow: focused ? "var(--focus-ring)" : "none",
      cursor: disabled ? "not-allowed" : "pointer",
      opacity: disabled ? 0.5 : 1,
      transition: "border-color var(--motion-fast), box-shadow var(--motion-fast)",
      ...style
    }
  }, rest), norm.map(o => /*#__PURE__*/React.createElement("option", {
    key: o.value,
    value: o.value
  }, o.label))), /*#__PURE__*/React.createElement("span", {
    style: {
      position: "absolute",
      right: "10px",
      top: "50%",
      transform: "translateY(-50%)",
      pointerEvents: "none",
      color: "var(--text-dim)",
      fontSize: "10px"
    }
  }, "\u25BE")));
}
Object.assign(__ds_scope, { Select });
})(); } catch (e) { __ds_ns.__errors.push({ path: "components/forms/select.ref.jsx", error: String((e && e.message) || e) }); }

// components/forms/text-input.ref.jsx
try { (() => {
function _extends() { return _extends = Object.assign ? Object.assign.bind() : function (n) { for (var e = 1; e < arguments.length; e++) { var t = arguments[e]; for (var r in t) ({}).hasOwnProperty.call(t, r) && (n[r] = t[r]); } return n; }, _extends.apply(null, arguments); }
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
    ...style
  };
  const field = multiline ? /*#__PURE__*/React.createElement("textarea", _extends({
    value: value,
    onChange: onChange,
    placeholder: placeholder,
    rows: rows,
    disabled: disabled,
    onFocus: () => setFocused(true),
    onBlur: () => setFocused(false),
    style: fieldStyle
  }, rest)) : /*#__PURE__*/React.createElement("input", _extends({
    type: type,
    value: value,
    onChange: onChange,
    placeholder: placeholder,
    disabled: disabled,
    onFocus: () => setFocused(true),
    onBlur: () => setFocused(false),
    style: fieldStyle
  }, rest));
  return /*#__PURE__*/React.createElement("label", {
    style: {
      display: "block"
    }
  }, label && /*#__PURE__*/React.createElement("span", {
    style: {
      display: "block",
      fontSize: "11px",
      fontWeight: 600,
      textTransform: "uppercase",
      letterSpacing: "0.5px",
      color: "var(--text-secondary)",
      marginBottom: "6px"
    }
  }, label), /*#__PURE__*/React.createElement("span", {
    style: {
      position: "relative",
      display: "block"
    }
  }, icon && /*#__PURE__*/React.createElement("span", {
    style: {
      position: "absolute",
      left: "10px",
      top: "50%",
      transform: "translateY(-50%)",
      display: "inline-flex",
      width: "16px",
      height: "16px",
      color: "var(--text-dim)",
      pointerEvents: "none"
    }
  }, icon), field), hint && /*#__PURE__*/React.createElement("span", {
    style: {
      display: "block",
      fontSize: "11px",
      color: invalid ? "var(--red)" : "var(--text-dim)",
      marginTop: "5px",
      fontFamily: "var(--font-mono)"
    }
  }, hint));
}
Object.assign(__ds_scope, { TextInput });
})(); } catch (e) { __ds_ns.__errors.push({ path: "components/forms/text-input.ref.jsx", error: String((e && e.message) || e) }); }

// components/intent/cap-step.ref.jsx
try { (() => {
function CapStep({
  index = 1,
  title,
  state = "pending",
  // "done" | "active" | "pending"
  provenance = null,
  // "local" | "hybrid" | "remote"
  ring = null,
  // "draft" | "verified" | "gold"
  parallel = false,
  last = false,
  style = {}
}) {
  const states = {
    done: {
      color: "var(--prov-local)",
      fill: "var(--prov-local)"
    },
    active: {
      color: "var(--purple)",
      fill: "var(--purple)"
    },
    pending: {
      color: "var(--text-dim)",
      fill: "transparent"
    }
  };
  const s = states[state] || states.pending;
  const provColor = provenance ? {
    local: "var(--prov-local)",
    hybrid: "var(--prov-hybrid)",
    remote: "var(--prov-remote)"
  }[provenance] : null;
  const ringColor = ring ? {
    draft: "var(--ring-draft)",
    verified: "var(--ring-verified)",
    gold: "var(--ring-gold)"
  }[ring] : null;
  return /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      gap: "12px",
      ...style
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      flexDirection: "column",
      alignItems: "center"
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      width: "22px",
      height: "22px",
      borderRadius: "50%",
      flexShrink: 0,
      border: `2px solid ${s.color}`,
      background: s.fill,
      display: "flex",
      alignItems: "center",
      justifyContent: "center",
      boxShadow: state === "active" ? "0 0 10px rgba(119,74,255,0.5)" : "none"
    }
  }, state === "done" && /*#__PURE__*/React.createElement("i", {
    "data-lucide": "check",
    style: {
      width: "12px",
      height: "12px",
      color: "var(--bg-0)"
    }
  }), state === "active" && /*#__PURE__*/React.createElement("span", {
    style: {
      width: "7px",
      height: "7px",
      borderRadius: "50%",
      background: "#fff"
    }
  })), !last && /*#__PURE__*/React.createElement("div", {
    style: {
      width: "2px",
      flex: 1,
      minHeight: "18px",
      background: state === "done" ? "var(--prov-local)" : "var(--border)",
      marginTop: "2px"
    }
  })), /*#__PURE__*/React.createElement("div", {
    style: {
      paddingBottom: last ? 0 : "16px",
      flex: 1
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      alignItems: "center",
      gap: "8px",
      flexWrap: "wrap"
    }
  }, /*#__PURE__*/React.createElement("span", {
    style: {
      fontFamily: "var(--font-mono)",
      fontSize: "10px",
      color: "var(--text-dim)"
    }
  }, String(index).padStart(2, "0")), /*#__PURE__*/React.createElement("span", {
    style: {
      fontSize: "13px",
      fontWeight: state === "pending" ? 400 : 600,
      color: state === "pending" ? "var(--text-secondary)" : "var(--text-primary)"
    }
  }, title), parallel && /*#__PURE__*/React.createElement("span", {
    style: {
      fontFamily: "var(--font-mono)",
      fontSize: "9px",
      color: "var(--cyan)",
      border: "1px solid var(--cyan)",
      borderRadius: "3px",
      padding: "0 4px"
    }
  }, "SILO //")), (provColor || ringColor) && /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      gap: "10px",
      marginTop: "5px",
      fontFamily: "var(--font-mono)",
      fontSize: "10px"
    }
  }, provColor && /*#__PURE__*/React.createElement("span", {
    style: {
      color: provColor
    }
  }, "\u25CF ", provenance), ringColor && /*#__PURE__*/React.createElement("span", {
    style: {
      color: ringColor
    }
  }, "\u25C6 ", ring))));
}
Object.assign(__ds_scope, { CapStep });
})(); } catch (e) { __ds_ns.__errors.push({ path: "components/intent/cap-step.ref.jsx", error: String((e && e.message) || e) }); }

// components/modules/Modulecard.ref.jsx
try { (() => {
function ModuleCard({
  domain = "transport",
  title,
  desc = null,
  icon = null,
  enabled = true,
  onToggle = null,
  provenance = null,
  // "local" | "hybrid" | "remote"
  status = null,
  // "up" | "down" | "warn"
  pinned = false,
  comingSoon = false,
  style = {}
}) {
  const accent = `var(--domain-${domain})`;
  const dot = {
    up: "var(--green)",
    down: "var(--red)",
    warn: "var(--yellow)"
  }[status];
  const provColor = provenance ? {
    local: "var(--prov-local)",
    hybrid: "var(--prov-hybrid)",
    remote: "var(--prov-remote)"
  }[provenance] : null;
  const provText = provenance ? {
    local: "LOCAL",
    hybrid: "HYBRIDE",
    remote: "DISTANT"
  }[provenance] : null;
  const dim = comingSoon || !enabled;
  return /*#__PURE__*/React.createElement("div", {
    style: {
      position: "relative",
      background: dim ? "var(--bg-1)" : "var(--bg-2)",
      border: `1px solid ${dim ? "var(--border-subtle)" : "var(--border)"}`,
      borderRadius: "var(--radius-md)",
      padding: "16px",
      overflow: "hidden",
      opacity: comingSoon ? 0.55 : 1,
      transition: "background var(--motion-base)",
      ...style
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      position: "absolute",
      left: 0,
      top: 0,
      bottom: 0,
      width: "3px",
      background: accent
    }
  }), /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      alignItems: "flex-start",
      justifyContent: "space-between",
      gap: "10px"
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      display: "inline-flex",
      alignItems: "center",
      justifyContent: "center",
      height: "40px",
      width: "40px",
      borderRadius: "var(--radius-sm)",
      background: `color-mix(in srgb, ${accent} 16%, transparent)`,
      color: accent
    }
  }, icon), comingSoon ? /*#__PURE__*/React.createElement("span", {
    style: {
      fontFamily: "var(--font-mono)",
      fontSize: "9.5px",
      fontWeight: 700,
      letterSpacing: "0.3px",
      color: "var(--text-dim)",
      border: "1px solid var(--border)",
      borderRadius: "4px",
      padding: "1px 6px"
    }
  }, "BIENT\xD4T") : onToggle ? /*#__PURE__*/React.createElement("button", {
    onClick: () => onToggle(!enabled),
    "aria-label": "Activer le module",
    style: {
      width: "38px",
      height: "22px",
      borderRadius: "var(--radius-pill)",
      border: "none",
      cursor: "pointer",
      background: enabled ? accent : "var(--bg-4)",
      position: "relative",
      transition: "background var(--motion-fast)",
      flexShrink: 0
    }
  }, /*#__PURE__*/React.createElement("span", {
    style: {
      position: "absolute",
      top: "3px",
      left: enabled ? "19px" : "3px",
      width: "16px",
      height: "16px",
      borderRadius: "50%",
      background: "#fff",
      transition: "left var(--motion-fast)"
    }
  })) : status && /*#__PURE__*/React.createElement("span", {
    style: {
      width: "10px",
      height: "10px",
      borderRadius: "50%",
      background: dot,
      animation: status === "up" ? "laforge-pulse var(--pulse-period) infinite" : "none"
    }
  })), /*#__PURE__*/React.createElement("h3", {
    style: {
      margin: "12px 0 0",
      fontSize: "16px",
      fontWeight: 700,
      color: dim ? "var(--text-secondary)" : "var(--text-primary)",
      display: "flex",
      alignItems: "center",
      gap: "7px"
    }
  }, title, pinned && /*#__PURE__*/React.createElement("svg", {
    width: "13",
    height: "13",
    viewBox: "0 0 24 24",
    fill: "none",
    stroke: accent,
    strokeWidth: "2",
    strokeLinecap: "round",
    strokeLinejoin: "round",
    style: {
      flexShrink: 0
    }
  }, /*#__PURE__*/React.createElement("path", {
    d: "M12 17v5"
  }), /*#__PURE__*/React.createElement("path", {
    d: "M9 10.76a2 2 0 0 1-1.11 1.79l-1.78.9A2 2 0 0 0 5 15.24V16a1 1 0 0 0 1 1h12a1 1 0 0 0 1-1v-.76a2 2 0 0 0-1.11-1.79l-1.78-.9A2 2 0 0 1 15 10.76V7a1 1 0 0 1 1-1 2 2 0 0 0 0-4H8a2 2 0 0 0 0 4 1 1 0 0 1 1 1z"
  }))), desc && /*#__PURE__*/React.createElement("p", {
    style: {
      margin: "4px 0 0",
      fontSize: "12.5px",
      color: "var(--text-secondary)",
      lineHeight: 1.45
    }
  }, desc), provText && /*#__PURE__*/React.createElement("div", {
    style: {
      marginTop: "12px"
    }
  }, /*#__PURE__*/React.createElement("span", {
    style: {
      display: "inline-flex",
      alignItems: "center",
      gap: "6px",
      fontFamily: "var(--font-mono)",
      fontSize: "10px",
      fontWeight: 600,
      color: provColor
    }
  }, /*#__PURE__*/React.createElement("span", {
    style: {
      width: "6px",
      height: "6px",
      borderRadius: "50%",
      background: "currentColor"
    }
  }), provText)));
}
Object.assign(__ds_scope, { ModuleCard });
})(); } catch (e) { __ds_ns.__errors.push({ path: "components/modules/Modulecard.ref.jsx", error: String((e && e.message) || e) }); }

// components/rings/ring-meter.ref.jsx
try { (() => {
const RING_META = [{
  id: 0,
  label: "Ring 0",
  desc: "Lois absolues"
}, {
  id: 1,
  label: "Ring 1",
  desc: "Core Nokido"
}, {
  id: 2,
  label: "Ring 2",
  desc: "TRUSTED humain"
}, {
  id: 3,
  label: "Ring 3",
  desc: "Agents validés"
}, {
  id: 4,
  label: "Ring 4",
  desc: "Agents externes"
}, {
  id: 5,
  label: "Ring 5",
  desc: "RAG web"
}, {
  id: 6,
  label: "Ring 6",
  desc: "Outils CI/CD"
}, {
  id: 7,
  label: "Ring 7",
  desc: "SSH / réseau"
}, {
  id: 8,
  label: "Ring 8",
  desc: "Monitoring"
}, {
  id: 9,
  label: "Ring 9",
  desc: "Système hôte"
}, {
  id: 10,
  label: "Ring 10",
  desc: "Corrections de Cap"
}];

// Dégradé sémantique : centre vert (souverain/core) → extérieur violet (système/externe)
function ringColor(i) {
  const stops = [[74, 194, 139],
  // vert (local, souverain)
  [45, 212, 191],
  // cyan
  [59, 178, 208],
  // bleu
  [119, 74, 255] // violet (système, distant)
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
  inactive: "var(--bg-4)"
};
function RingMeter({
  states = {},
  selected = null,
  onSelect = null,
  size = 300,
  showLegend = true,
  pulse = true,
  style = {}
}) {
  const cx = size / 2,
    cy = size / 2;
  const ringW = (size / 2 - 16) / 11;
  const radius = i => 16 + (i + 0.5) * ringW;
  return /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      gap: "18px",
      alignItems: "center",
      flexWrap: "wrap",
      ...style
    }
  }, /*#__PURE__*/React.createElement("svg", {
    width: size,
    height: size,
    viewBox: `0 0 ${size} ${size}`,
    style: {
      flexShrink: 0
    }
  }, /*#__PURE__*/React.createElement("circle", {
    cx: cx,
    cy: cy,
    r: ringW * 0.6,
    fill: ringColor(0),
    opacity: 0.9
  }), RING_META.map(r => {
    const st = states[r.id] || "ok";
    const base = st === "ok" ? ringColor(r.id) : STATE_OVERRIDE[st];
    const on = selected === r.id;
    const isAnim = pulse && st === "alert";
    return /*#__PURE__*/React.createElement("circle", {
      key: r.id,
      cx: cx,
      cy: cy,
      r: radius(r.id),
      fill: "none",
      stroke: base,
      strokeWidth: on ? ringW * 0.95 : ringW * 0.7,
      opacity: st === "inactive" ? 0.4 : on ? 1 : 0.82,
      onClick: onSelect ? () => onSelect(r.id) : undefined,
      style: {
        cursor: onSelect ? "pointer" : "default",
        filter: on ? `drop-shadow(0 0 6px ${base})` : "none",
        transition: "stroke-width var(--motion-base), opacity var(--motion-base)",
        animation: isAnim ? "laforge-pulse var(--pulse-period) infinite" : "none"
      }
    });
  }), /*#__PURE__*/React.createElement("text", {
    x: cx,
    y: cy + 4,
    textAnchor: "middle",
    fontFamily: "var(--font-mono)",
    fontSize: size * 0.05,
    fontWeight: "700",
    fill: "var(--bg-0)"
  }, "R0")), showLegend && /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      flexDirection: "column",
      gap: "3px",
      minWidth: "150px"
    }
  }, RING_META.map(r => {
    const st = states[r.id] || "ok";
    const c = st === "ok" ? ringColor(r.id) : STATE_OVERRIDE[st];
    const on = selected === r.id;
    return /*#__PURE__*/React.createElement("button", {
      key: r.id,
      onClick: onSelect ? () => onSelect(r.id) : undefined,
      style: {
        display: "flex",
        alignItems: "center",
        gap: "8px",
        padding: "3px 7px",
        border: "none",
        borderRadius: "var(--radius-sm)",
        cursor: onSelect ? "pointer" : "default",
        background: on ? "var(--bg-3)" : "transparent",
        textAlign: "left",
        width: "100%",
        fontFamily: "var(--font-sans)"
      }
    }, /*#__PURE__*/React.createElement("span", {
      style: {
        width: "10px",
        height: "10px",
        borderRadius: "50%",
        background: c,
        flexShrink: 0,
        boxShadow: st === "block" ? `0 0 6px ${c}` : "none"
      }
    }), /*#__PURE__*/React.createElement("span", {
      style: {
        fontFamily: "var(--font-mono)",
        fontSize: "10px",
        color: "var(--text-dim)",
        width: "44px",
        flexShrink: 0
      }
    }, r.label), /*#__PURE__*/React.createElement("span", {
      style: {
        fontSize: "11.5px",
        color: on ? "var(--text-primary)" : "var(--text-secondary)",
        fontWeight: on ? 600 : 400
      }
    }, r.desc));
  })));
}
RingMeter.RING_META = RING_META;
RingMeter.ringColor = ringColor;
Object.assign(__ds_scope, { RingMeter });
})(); } catch (e) { __ds_ns.__errors.push({ path: "components/rings/ring-meter.ref.jsx", error: String((e && e.message) || e) }); }

// components/sovereignty/power-slider.ref.jsx
try { (() => {
function PowerSlider({
  value = 60,
  onChange = null,
  style = {}
}) {
  const [internal, setInternal] = React.useState(value);
  const v = onChange ? value : internal;
  function set(next) {
    if (onChange) onChange(next);else setInternal(next);
  }

  // Dérivés lisibles en temps réel : plus de puissance allouée → plus local.
  const localShare = v;
  const privacy = v; // ↑ avec le local
  const cost = Math.round(100 - v * 0.85); // cloud = coût
  const latency = Math.round(30 + (100 - v) * 0.9); // cloud = +latence réseau

  const metric = (lbl, val, unit, color) => /*#__PURE__*/React.createElement("div", {
    style: {
      flex: 1
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      fontSize: "10px",
      textTransform: "uppercase",
      letterSpacing: "0.5px",
      color: "var(--text-dim)"
    }
  }, lbl), /*#__PURE__*/React.createElement("div", {
    style: {
      fontFamily: "var(--font-mono)",
      fontSize: "14px",
      fontWeight: 700,
      color
    }
  }, val, unit));
  return /*#__PURE__*/React.createElement("div", {
    style: {
      background: "var(--bg-2)",
      border: "1px solid var(--border)",
      borderRadius: "var(--radius-md)",
      padding: "16px",
      ...style
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      justifyContent: "space-between",
      alignItems: "baseline",
      marginBottom: "12px"
    }
  }, /*#__PURE__*/React.createElement("span", {
    style: {
      fontSize: "13px",
      fontWeight: 600,
      color: "var(--text-primary)"
    }
  }, "Puissance de calcul allou\xE9e"), /*#__PURE__*/React.createElement("span", {
    style: {
      fontFamily: "var(--font-mono)",
      fontSize: "13px",
      color: "var(--prov-local)"
    }
  }, v, "%")), /*#__PURE__*/React.createElement("input", {
    type: "range",
    min: "0",
    max: "100",
    value: v,
    onChange: e => set(Number(e.target.value)),
    style: {
      width: "100%",
      appearance: "none",
      WebkitAppearance: "none",
      height: "6px",
      borderRadius: "var(--radius-pill)",
      outline: "none",
      cursor: "pointer",
      background: `linear-gradient(90deg, var(--prov-local) 0%, var(--prov-local) ${v}%, var(--prov-remote-tint) ${v}%, var(--prov-remote-tint) 100%)`
    },
    className: "lf-power-range"
  }), /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      justifyContent: "space-between",
      marginTop: "6px",
      fontFamily: "var(--font-mono)",
      fontSize: "10px",
      color: "var(--text-dim)"
    }
  }, /*#__PURE__*/React.createElement("span", null, "\u2190 cloud (d\xE9l\xE8gue)"), /*#__PURE__*/React.createElement("span", null, "local (souverain) \u2192")), /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      gap: "12px",
      marginTop: "16px",
      paddingTop: "14px",
      borderTop: "1px solid var(--border-subtle)"
    }
  }, metric("Confidentialité", privacy, "%", "var(--prov-local)"), metric("Local", localShare, "%", "var(--prov-hybrid)"), metric("Coût relatif", cost, "%", "var(--orange)"), metric("Latence", latency, "ms", "var(--blue)")), /*#__PURE__*/React.createElement("style", null, `
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
      `));
}
Object.assign(__ds_scope, { PowerSlider });
})(); } catch (e) { __ds_ns.__errors.push({ path: "components/sovereignty/power-slider.ref.jsx", error: String((e && e.message) || e) }); }

// components/sovereignty/Provenancebadge.ref.jsx
try { (() => {
function ProvenanceBadge({
  origin = "local",
  ring = null,
  label = null,
  detail = null,
  size = "md",
  style = {}
}) {
  const origins = {
    local: {
      color: "var(--prov-local)",
      bg: "var(--prov-local-tint)",
      text: "LOCAL"
    },
    hybrid: {
      color: "var(--prov-hybrid)",
      bg: "var(--prov-hybrid-tint)",
      text: "HYBRIDE"
    },
    remote: {
      color: "var(--prov-remote)",
      bg: "var(--prov-remote-tint)",
      text: "DISTANT"
    }
  };
  const rings = {
    draft: {
      color: "var(--ring-draft)",
      text: "brouillon"
    },
    verified: {
      color: "var(--ring-verified)",
      text: "vérifié"
    },
    gold: {
      color: "var(--ring-gold)",
      text: "or"
    }
  };
  const o = origins[origin] || origins.local;
  const r = ring ? rings[ring] : null;
  const sm = size === "sm";
  return /*#__PURE__*/React.createElement("span", {
    style: {
      display: "inline-flex",
      alignItems: "center",
      gap: "7px",
      fontFamily: "var(--font-mono)",
      fontSize: sm ? "10px" : "11px",
      fontWeight: 600,
      padding: sm ? "2px 8px" : "3px 10px",
      borderRadius: "var(--radius-pill)",
      color: o.color,
      background: o.bg,
      ...style
    }
  }, /*#__PURE__*/React.createElement("span", {
    style: {
      width: sm ? "6px" : "7px",
      height: sm ? "6px" : "7px",
      borderRadius: "50%",
      background: "currentColor"
    }
  }), /*#__PURE__*/React.createElement("span", null, label || o.text), r && /*#__PURE__*/React.createElement(React.Fragment, null, /*#__PURE__*/React.createElement("span", {
    style: {
      width: "1px",
      height: "10px",
      background: "currentColor",
      opacity: 0.3
    }
  }), /*#__PURE__*/React.createElement("span", {
    style: {
      display: "inline-flex",
      alignItems: "center",
      gap: "4px",
      color: r.color,
      opacity: 0.95
    }
  }, /*#__PURE__*/React.createElement("span", {
    style: {
      width: "8px",
      height: "8px",
      borderRadius: "50%",
      background: ring === "draft" ? "transparent" : r.color,
      border: ring === "draft" ? `1.5px dashed ${r.color}` : "none",
      boxShadow: ring === "gold" ? "0 0 6px rgba(255,194,45,0.6)" : "none"
    }
  }), r.text)), detail && /*#__PURE__*/React.createElement("span", {
    style: {
      color: "var(--text-dim)",
      fontWeight: 400
    }
  }, "\xB7 ", detail));
}
Object.assign(__ds_scope, { ProvenanceBadge });
})(); } catch (e) { __ds_ns.__errors.push({ path: "components/sovereignty/Provenancebadge.ref.jsx", error: String((e && e.message) || e) }); }

// components/sovereignty/sovereignty-gauge.ref.jsx
try { (() => {
function SovereigntyGauge({
  local = 70,
  label = "Souveraineté",
  showLegend = true,
  height = 10,
  style = {}
}) {
  const pct = Math.max(0, Math.min(100, local));
  return /*#__PURE__*/React.createElement("div", {
    style: {
      ...style
    }
  }, label && /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      justifyContent: "space-between",
      alignItems: "baseline",
      marginBottom: "7px"
    }
  }, /*#__PURE__*/React.createElement("span", {
    style: {
      fontSize: "11px",
      fontWeight: 600,
      textTransform: "uppercase",
      letterSpacing: "0.5px",
      color: "var(--text-secondary)"
    }
  }, label), /*#__PURE__*/React.createElement("span", {
    style: {
      fontFamily: "var(--font-mono)",
      fontSize: "12px",
      color: "var(--prov-local)"
    }
  }, pct, "% local")), /*#__PURE__*/React.createElement("div", {
    style: {
      position: "relative",
      height: `${height}px`,
      borderRadius: "var(--radius-pill)",
      background: "var(--prov-remote-tint)",
      overflow: "hidden",
      border: "1px solid var(--border-subtle)"
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      position: "absolute",
      left: 0,
      top: 0,
      bottom: 0,
      width: `${pct}%`,
      background: "linear-gradient(90deg, var(--prov-local), #5fd6a0)",
      boxShadow: "0 0 12px rgba(74,194,139,0.4)",
      transition: "width var(--motion-slow) var(--ease-out)"
    }
  })), showLegend && /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      justifyContent: "space-between",
      marginTop: "6px",
      fontFamily: "var(--font-mono)",
      fontSize: "10px",
      color: "var(--text-dim)"
    }
  }, /*#__PURE__*/React.createElement("span", {
    style: {
      color: "var(--prov-local)"
    }
  }, "\u25CF local \xB7 souverain"), /*#__PURE__*/React.createElement("span", {
    style: {
      color: "var(--prov-remote)"
    }
  }, "distant \xB7 cloud \u25CF")));
}
Object.assign(__ds_scope, { SovereigntyGauge });
})(); } catch (e) { __ds_ns.__errors.push({ path: "components/sovereignty/sovereignty-gauge.ref.jsx", error: String((e && e.message) || e) }); }

// design_handoff_nokido/assets/laforge-prefs.js
try { (() => {
/* Nokido — préférences persistantes partagées entre écrans (localStorage).
   Clés : nokido.power (0-100), nokido.theme (dark|light|auto), nokido.lang (fr|en|es|de).
   Charger AVANT les scripts d'app : <script src="…/assets/laforge-prefs.js"></script> */
(function () {
  "use strict";

  var NS = "nokido.";
  function get(key, fallback) {
    try {
      var raw = localStorage.getItem(NS + key);
      return raw === null ? fallback : JSON.parse(raw);
    } catch (e) {
      return fallback;
    }
  }
  function set(key, value) {
    try {
      localStorage.setItem(NS + key, JSON.stringify(value));
    } catch (e) {}
  }
  function applyTheme(theme) {
    var t = theme || get("theme", "dark");
    document.documentElement.setAttribute("data-theme", t);
    return t;
  }
  function cycleTheme() {
    var order = ["dark", "light", "auto"];
    var cur = get("theme", "dark");
    var next = order[(order.indexOf(cur) + 1) % order.length];
    set("theme", next);
    applyTheme(next);
    return next;
  }
  // Applique le thème mémorisé dès le chargement (évite le flash).
  applyTheme();
  window.NokidoPrefs = {
    get: get,
    set: set,
    applyTheme: applyTheme,
    cycleTheme: cycleTheme
  };
})();
})(); } catch (e) { __ds_ns.__errors.push({ path: "design_handoff_nokido/assets/laforge-prefs.js", error: String((e && e.message) || e) }); }

// design_handoff_nokido/components/core/button.ref.jsx
try { (() => {
function _extends() { return _extends = Object.assign ? Object.assign.bind() : function (n) { for (var e = 1; e < arguments.length; e++) { var t = arguments[e]; for (var r in t) ({}).hasOwnProperty.call(t, r) && (n[r] = t[r]); } return n; }, _extends.apply(null, arguments); }
/* Référence design (handoff) — composant du DS Nokido. Source canonique : components/ à la racine du projet. */
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
    sm: {
      padding: "4px 10px",
      fontSize: "12px",
      height: "30px"
    },
    md: {
      padding: "6px 14px",
      fontSize: "13.5px",
      height: "36px"
    },
    lg: {
      padding: "9px 18px",
      fontSize: "14px",
      height: "44px"
    }
  };
  const variants = {
    primary: {
      background: "var(--purple)",
      color: "#fff",
      border: "1px solid transparent"
    },
    ghost: {
      background: "transparent",
      color: "var(--text-secondary)",
      border: "1px solid var(--border)"
    },
    danger: {
      background: "var(--red)",
      color: "#fff",
      border: "1px solid transparent"
    },
    success: {
      background: "var(--green)",
      color: "var(--bg-0)",
      border: "1px solid transparent"
    }
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
    ...style
  };
  const hoverBg = {
    primary: "var(--purple-dim)",
    ghost: "transparent",
    danger: "#d83b3b",
    success: "#3fae7a"
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
  return /*#__PURE__*/React.createElement("button", _extends({
    type: type,
    disabled: disabled,
    onClick: onClick,
    onMouseEnter: onEnter,
    onMouseLeave: onLeave,
    style: base
  }, rest), icon && /*#__PURE__*/React.createElement("span", {
    style: {
      display: "inline-flex",
      width: "16px",
      height: "16px"
    }
  }, icon), children, iconRight && /*#__PURE__*/React.createElement("span", {
    style: {
      display: "inline-flex",
      width: "16px",
      height: "16px"
    }
  }, iconRight));
}
})(); } catch (e) { __ds_ns.__errors.push({ path: "design_handoff_nokido/components/core/button.ref.jsx", error: String((e && e.message) || e) }); }

// design_handoff_nokido/components/core/card.ref.jsx
try { (() => {
function _extends() { return _extends = Object.assign ? Object.assign.bind() : function (n) { for (var e = 1; e < arguments.length; e++) { var t = arguments[e]; for (var r in t) ({}).hasOwnProperty.call(t, r) && (n[r] = t[r]); } return n; }, _extends.apply(null, arguments); }
/* Référence design (handoff) — composant du DS Nokido. Source canonique : components/ à la racine du projet. */
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
    purple: "var(--tint-purple)",
    blue: "var(--tint-blue)",
    cyan: "var(--tint-cyan)",
    green: "var(--tint-green)",
    yellow: "var(--tint-yellow)",
    orange: "var(--tint-orange)",
    red: "var(--tint-red)",
    pink: "var(--tint-pink)"
  };
  const colors = {
    purple: "var(--purple)",
    blue: "var(--blue)",
    cyan: "var(--cyan)",
    green: "var(--green)",
    yellow: "var(--yellow)",
    orange: "var(--orange)",
    red: "var(--red)",
    pink: "var(--pink)"
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
    ...style
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
  const inner = /*#__PURE__*/React.createElement(React.Fragment, null, icon && /*#__PURE__*/React.createElement("span", {
    style: {
      display: "inline-flex",
      alignItems: "center",
      justifyContent: "center",
      height: "44px",
      width: "44px",
      borderRadius: "var(--radius-sm)",
      background: tints[iconColor],
      color: colors[iconColor],
      marginBottom: "10px"
    }
  }, icon), title && /*#__PURE__*/React.createElement("h3", {
    style: {
      margin: 0,
      fontSize: "16px",
      fontWeight: 700,
      color: "var(--text-primary)"
    }
  }, title), subtitle && /*#__PURE__*/React.createElement("p", {
    style: {
      margin: "4px 0 0",
      fontSize: "12.5px",
      color: "var(--text-secondary)",
      lineHeight: 1.45
    }
  }, subtitle), children, footer && /*#__PURE__*/React.createElement("div", {
    style: {
      marginTop: "14px",
      fontSize: "11px",
      fontFamily: "var(--font-mono)",
      color: "var(--text-dim)"
    }
  }, footer));
  if (href) {
    return /*#__PURE__*/React.createElement("a", _extends({
      href: href,
      style: base,
      onMouseEnter: onEnter,
      onMouseLeave: onLeave
    }, rest), inner);
  }
  return /*#__PURE__*/React.createElement("div", _extends({
    style: base,
    onMouseEnter: onEnter,
    onMouseLeave: onLeave
  }, rest), inner);
}
})(); } catch (e) { __ds_ns.__errors.push({ path: "design_handoff_nokido/components/core/card.ref.jsx", error: String((e && e.message) || e) }); }

// design_handoff_nokido/components/feedback/badge.ref.jsx
try { (() => {
/* Référence design (handoff) — composant du DS Nokido. Source canonique : components/ à la racine du projet. */
function Badge({
  children,
  color = "purple",
  variant = "soft",
  mono = false,
  style = {}
}) {
  const colors = {
    purple: "var(--purple)",
    blue: "var(--blue)",
    cyan: "var(--cyan)",
    green: "var(--green)",
    yellow: "var(--yellow)",
    orange: "var(--orange)",
    red: "var(--red)",
    pink: "var(--pink)",
    dim: "var(--text-dim)"
  };
  const tints = {
    purple: "var(--tint-purple)",
    blue: "var(--tint-blue)",
    cyan: "var(--tint-cyan)",
    green: "var(--tint-green)",
    yellow: "var(--tint-yellow)",
    orange: "var(--tint-orange)",
    red: "var(--tint-red)",
    pink: "var(--tint-pink)",
    dim: "rgba(110,106,130,0.16)"
  };
  const variants = {
    soft: {
      background: tints[color],
      color: colors[color],
      border: "1px solid transparent"
    },
    solid: {
      background: colors[color],
      color: "var(--bg-0)",
      border: "1px solid transparent"
    },
    outline: {
      background: "transparent",
      color: colors[color],
      border: `1px solid ${colors[color]}`
    }
  };
  return /*#__PURE__*/React.createElement("span", {
    style: {
      display: "inline-flex",
      alignItems: "center",
      gap: "5px",
      fontSize: mono ? "9.5px" : "11px",
      fontFamily: mono ? "var(--font-mono)" : "var(--font-sans)",
      fontWeight: mono ? 700 : 600,
      letterSpacing: mono ? "0.3px" : 0,
      padding: "2px 8px",
      borderRadius: "var(--radius-sm)",
      textTransform: mono ? "uppercase" : "none",
      ...variants[variant],
      ...style
    }
  }, children);
}
})(); } catch (e) { __ds_ns.__errors.push({ path: "design_handoff_nokido/components/feedback/badge.ref.jsx", error: String((e && e.message) || e) }); }

// design_handoff_nokido/components/feedback/status-pill.ref.jsx
try { (() => {
/* Référence design (handoff) — composant du DS Nokido. Source canonique : components/ à la racine du projet. */
function StatusPill({
  children,
  status = "info",
  pulse = false,
  style = {}
}) {
  const map = {
    up: {
      color: "var(--green)",
      bg: "rgba(74, 194, 139, 0.12)"
    },
    down: {
      color: "var(--red)",
      bg: "rgba(242, 79, 79, 0.12)"
    },
    warn: {
      color: "var(--yellow)",
      bg: "rgba(255, 194, 45, 0.12)"
    },
    info: {
      color: "var(--blue)",
      bg: "rgba(59, 178, 208, 0.12)"
    },
    idle: {
      color: "var(--text-dim)",
      bg: "rgba(110, 106, 130, 0.12)"
    }
  };
  const c = map[status] || map.info;
  return /*#__PURE__*/React.createElement("span", {
    style: {
      display: "inline-flex",
      alignItems: "center",
      gap: "6px",
      fontSize: "11px",
      fontFamily: "var(--font-mono)",
      padding: "2px 8px",
      borderRadius: "var(--radius-pill)",
      color: c.color,
      background: c.bg,
      ...style
    }
  }, /*#__PURE__*/React.createElement("span", {
    style: {
      width: "6px",
      height: "6px",
      borderRadius: "50%",
      background: "currentColor",
      animation: pulse ? "laforge-pulse var(--pulse-period) infinite" : "none"
    }
  }), children);
}
})(); } catch (e) { __ds_ns.__errors.push({ path: "design_handoff_nokido/components/feedback/status-pill.ref.jsx", error: String((e && e.message) || e) }); }

// design_handoff_nokido/components/forms/select.ref.jsx
try { (() => {
function _extends() { return _extends = Object.assign ? Object.assign.bind() : function (n) { for (var e = 1; e < arguments.length; e++) { var t = arguments[e]; for (var r in t) ({}).hasOwnProperty.call(t, r) && (n[r] = t[r]); } return n; }, _extends.apply(null, arguments); }
/* Référence design (handoff) — composant du DS Nokido. Source canonique : components/ à la racine du projet. */

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
  const norm = options.map(o => typeof o === "string" ? {
    value: o,
    label: o
  } : o);
  return /*#__PURE__*/React.createElement("label", {
    style: {
      display: "block"
    }
  }, label && /*#__PURE__*/React.createElement("span", {
    style: {
      display: "block",
      fontSize: "11px",
      fontWeight: 600,
      textTransform: "uppercase",
      letterSpacing: "0.5px",
      color: "var(--text-secondary)",
      marginBottom: "6px"
    }
  }, label), /*#__PURE__*/React.createElement("span", {
    style: {
      position: "relative",
      display: "block"
    }
  }, /*#__PURE__*/React.createElement("select", _extends({
    value: value,
    onChange: onChange,
    disabled: disabled,
    onFocus: () => setFocused(true),
    onBlur: () => setFocused(false),
    style: {
      width: "100%",
      appearance: "none",
      WebkitAppearance: "none",
      background: "var(--bg-0)",
      color: "var(--text-primary)",
      border: `1px solid ${focused ? "var(--purple)" : "var(--border)"}`,
      borderRadius: "var(--radius-sm)",
      padding: "7px 30px 7px 10px",
      fontFamily: "var(--font-sans)",
      fontSize: "13px",
      outline: "none",
      boxShadow: focused ? "var(--focus-ring)" : "none",
      cursor: disabled ? "not-allowed" : "pointer",
      opacity: disabled ? 0.5 : 1,
      transition: "border-color var(--motion-fast), box-shadow var(--motion-fast)",
      ...style
    }
  }, rest), norm.map(o => /*#__PURE__*/React.createElement("option", {
    key: o.value,
    value: o.value
  }, o.label))), /*#__PURE__*/React.createElement("span", {
    style: {
      position: "absolute",
      right: "10px",
      top: "50%",
      transform: "translateY(-50%)",
      pointerEvents: "none",
      color: "var(--text-dim)",
      fontSize: "10px"
    }
  }, "\u25BE")));
}
})(); } catch (e) { __ds_ns.__errors.push({ path: "design_handoff_nokido/components/forms/select.ref.jsx", error: String((e && e.message) || e) }); }

// design_handoff_nokido/components/forms/text-input.ref.jsx
try { (() => {
function _extends() { return _extends = Object.assign ? Object.assign.bind() : function (n) { for (var e = 1; e < arguments.length; e++) { var t = arguments[e]; for (var r in t) ({}).hasOwnProperty.call(t, r) && (n[r] = t[r]); } return n; }, _extends.apply(null, arguments); }
/* Référence design (handoff) — composant du DS Nokido. Source canonique : components/ à la racine du projet. */

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
    ...style
  };
  const field = multiline ? /*#__PURE__*/React.createElement("textarea", _extends({
    value: value,
    onChange: onChange,
    placeholder: placeholder,
    rows: rows,
    disabled: disabled,
    onFocus: () => setFocused(true),
    onBlur: () => setFocused(false),
    style: fieldStyle
  }, rest)) : /*#__PURE__*/React.createElement("input", _extends({
    type: type,
    value: value,
    onChange: onChange,
    placeholder: placeholder,
    disabled: disabled,
    onFocus: () => setFocused(true),
    onBlur: () => setFocused(false),
    style: fieldStyle
  }, rest));
  return /*#__PURE__*/React.createElement("label", {
    style: {
      display: "block"
    }
  }, label && /*#__PURE__*/React.createElement("span", {
    style: {
      display: "block",
      fontSize: "11px",
      fontWeight: 600,
      textTransform: "uppercase",
      letterSpacing: "0.5px",
      color: "var(--text-secondary)",
      marginBottom: "6px"
    }
  }, label), /*#__PURE__*/React.createElement("span", {
    style: {
      position: "relative",
      display: "block"
    }
  }, icon && /*#__PURE__*/React.createElement("span", {
    style: {
      position: "absolute",
      left: "10px",
      top: "50%",
      transform: "translateY(-50%)",
      display: "inline-flex",
      width: "16px",
      height: "16px",
      color: "var(--text-dim)",
      pointerEvents: "none"
    }
  }, icon), field), hint && /*#__PURE__*/React.createElement("span", {
    style: {
      display: "block",
      fontSize: "11px",
      color: invalid ? "var(--red)" : "var(--text-dim)",
      marginTop: "5px",
      fontFamily: "var(--font-mono)"
    }
  }, hint));
}
})(); } catch (e) { __ds_ns.__errors.push({ path: "design_handoff_nokido/components/forms/text-input.ref.jsx", error: String((e && e.message) || e) }); }

// design_handoff_nokido/components/intent/cap-step.ref.jsx
try { (() => {
/* Référence design (handoff) — composant du DS Nokido. Source canonique : components/ à la racine du projet. */

function CapStep({
  index = 1,
  title,
  state = "pending",
  // "done" | "active" | "pending"
  provenance = null,
  // "local" | "hybrid" | "remote"
  ring = null,
  // "draft" | "verified" | "gold"
  parallel = false,
  last = false,
  style = {}
}) {
  const states = {
    done: {
      color: "var(--prov-local)",
      fill: "var(--prov-local)"
    },
    active: {
      color: "var(--purple)",
      fill: "var(--purple)"
    },
    pending: {
      color: "var(--text-dim)",
      fill: "transparent"
    }
  };
  const s = states[state] || states.pending;
  const provColor = provenance ? {
    local: "var(--prov-local)",
    hybrid: "var(--prov-hybrid)",
    remote: "var(--prov-remote)"
  }[provenance] : null;
  const ringColor = ring ? {
    draft: "var(--ring-draft)",
    verified: "var(--ring-verified)",
    gold: "var(--ring-gold)"
  }[ring] : null;
  return /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      gap: "12px",
      ...style
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      flexDirection: "column",
      alignItems: "center"
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      width: "22px",
      height: "22px",
      borderRadius: "50%",
      flexShrink: 0,
      border: `2px solid ${s.color}`,
      background: s.fill,
      display: "flex",
      alignItems: "center",
      justifyContent: "center",
      boxShadow: state === "active" ? "0 0 10px rgba(119,74,255,0.5)" : "none"
    }
  }, state === "done" && /*#__PURE__*/React.createElement("i", {
    "data-lucide": "check",
    style: {
      width: "12px",
      height: "12px",
      color: "var(--bg-0)"
    }
  }), state === "active" && /*#__PURE__*/React.createElement("span", {
    style: {
      width: "7px",
      height: "7px",
      borderRadius: "50%",
      background: "#fff"
    }
  })), !last && /*#__PURE__*/React.createElement("div", {
    style: {
      width: "2px",
      flex: 1,
      minHeight: "18px",
      background: state === "done" ? "var(--prov-local)" : "var(--border)",
      marginTop: "2px"
    }
  })), /*#__PURE__*/React.createElement("div", {
    style: {
      paddingBottom: last ? 0 : "16px",
      flex: 1
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      alignItems: "center",
      gap: "8px",
      flexWrap: "wrap"
    }
  }, /*#__PURE__*/React.createElement("span", {
    style: {
      fontFamily: "var(--font-mono)",
      fontSize: "10px",
      color: "var(--text-dim)"
    }
  }, String(index).padStart(2, "0")), /*#__PURE__*/React.createElement("span", {
    style: {
      fontSize: "13px",
      fontWeight: state === "pending" ? 400 : 600,
      color: state === "pending" ? "var(--text-secondary)" : "var(--text-primary)"
    }
  }, title), parallel && /*#__PURE__*/React.createElement("span", {
    style: {
      fontFamily: "var(--font-mono)",
      fontSize: "9px",
      color: "var(--cyan)",
      border: "1px solid var(--cyan)",
      borderRadius: "3px",
      padding: "0 4px"
    }
  }, "SILO //")), (provColor || ringColor) && /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      gap: "10px",
      marginTop: "5px",
      fontFamily: "var(--font-mono)",
      fontSize: "10px"
    }
  }, provColor && /*#__PURE__*/React.createElement("span", {
    style: {
      color: provColor
    }
  }, "\u25CF ", provenance), ringColor && /*#__PURE__*/React.createElement("span", {
    style: {
      color: ringColor
    }
  }, "\u25C6 ", ring))));
}
})(); } catch (e) { __ds_ns.__errors.push({ path: "design_handoff_nokido/components/intent/cap-step.ref.jsx", error: String((e && e.message) || e) }); }

// design_handoff_nokido/components/modules/module-card.ref.jsx
try { (() => {
/* Référence design (handoff) — composant du DS Nokido. Source canonique : components/ à la racine du projet. */

function ModuleCard({
  domain = "transport",
  title,
  desc = null,
  icon = null,
  enabled = true,
  onToggle = null,
  provenance = null,
  // "local" | "hybrid" | "remote"
  status = null,
  // "up" | "down" | "warn"
  pinned = false,
  comingSoon = false,
  style = {}
}) {
  const accent = `var(--domain-${domain})`;
  const dot = {
    up: "var(--green)",
    down: "var(--red)",
    warn: "var(--yellow)"
  }[status];
  const provColor = provenance ? {
    local: "var(--prov-local)",
    hybrid: "var(--prov-hybrid)",
    remote: "var(--prov-remote)"
  }[provenance] : null;
  const provText = provenance ? {
    local: "LOCAL",
    hybrid: "HYBRIDE",
    remote: "DISTANT"
  }[provenance] : null;
  const dim = comingSoon || !enabled;
  return /*#__PURE__*/React.createElement("div", {
    style: {
      position: "relative",
      background: dim ? "var(--bg-1)" : "var(--bg-2)",
      border: `1px solid ${dim ? "var(--border-subtle)" : "var(--border)"}`,
      borderRadius: "var(--radius-md)",
      padding: "16px",
      overflow: "hidden",
      opacity: comingSoon ? 0.55 : 1,
      transition: "background var(--motion-base)",
      ...style
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      position: "absolute",
      left: 0,
      top: 0,
      bottom: 0,
      width: "3px",
      background: accent
    }
  }), /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      alignItems: "flex-start",
      justifyContent: "space-between",
      gap: "10px"
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      display: "inline-flex",
      alignItems: "center",
      justifyContent: "center",
      height: "40px",
      width: "40px",
      borderRadius: "var(--radius-sm)",
      background: `color-mix(in srgb, ${accent} 16%, transparent)`,
      color: accent
    }
  }, icon), comingSoon ? /*#__PURE__*/React.createElement("span", {
    style: {
      fontFamily: "var(--font-mono)",
      fontSize: "9.5px",
      fontWeight: 700,
      letterSpacing: "0.3px",
      color: "var(--text-dim)",
      border: "1px solid var(--border)",
      borderRadius: "4px",
      padding: "1px 6px"
    }
  }, "BIENT\xD4T") : onToggle ? /*#__PURE__*/React.createElement("button", {
    onClick: () => onToggle(!enabled),
    "aria-label": "Activer le module",
    style: {
      width: "38px",
      height: "22px",
      borderRadius: "var(--radius-pill)",
      border: "none",
      cursor: "pointer",
      background: enabled ? accent : "var(--bg-4)",
      position: "relative",
      transition: "background var(--motion-fast)",
      flexShrink: 0
    }
  }, /*#__PURE__*/React.createElement("span", {
    style: {
      position: "absolute",
      top: "3px",
      left: enabled ? "19px" : "3px",
      width: "16px",
      height: "16px",
      borderRadius: "50%",
      background: "#fff",
      transition: "left var(--motion-fast)"
    }
  })) : status && /*#__PURE__*/React.createElement("span", {
    style: {
      width: "10px",
      height: "10px",
      borderRadius: "50%",
      background: dot,
      animation: status === "up" ? "laforge-pulse var(--pulse-period) infinite" : "none"
    }
  })), /*#__PURE__*/React.createElement("h3", {
    style: {
      margin: "12px 0 0",
      fontSize: "16px",
      fontWeight: 700,
      color: dim ? "var(--text-secondary)" : "var(--text-primary)",
      display: "flex",
      alignItems: "center",
      gap: "7px"
    }
  }, title, pinned && /*#__PURE__*/React.createElement("svg", {
    width: "13",
    height: "13",
    viewBox: "0 0 24 24",
    fill: "none",
    stroke: accent,
    strokeWidth: "2",
    strokeLinecap: "round",
    strokeLinejoin: "round",
    style: {
      flexShrink: 0
    }
  }, /*#__PURE__*/React.createElement("path", {
    d: "M12 17v5"
  }), /*#__PURE__*/React.createElement("path", {
    d: "M9 10.76a2 2 0 0 1-1.11 1.79l-1.78.9A2 2 0 0 0 5 15.24V16a1 1 0 0 0 1 1h12a1 1 0 0 0 1-1v-.76a2 2 0 0 0-1.11-1.79l-1.78-.9A2 2 0 0 1 15 10.76V7a1 1 0 0 1 1-1 2 2 0 0 0 0-4H8a2 2 0 0 0 0 4 1 1 0 0 1 1 1z"
  }))), desc && /*#__PURE__*/React.createElement("p", {
    style: {
      margin: "4px 0 0",
      fontSize: "12.5px",
      color: "var(--text-secondary)",
      lineHeight: 1.45
    }
  }, desc), provText && /*#__PURE__*/React.createElement("div", {
    style: {
      marginTop: "12px"
    }
  }, /*#__PURE__*/React.createElement("span", {
    style: {
      display: "inline-flex",
      alignItems: "center",
      gap: "6px",
      fontFamily: "var(--font-mono)",
      fontSize: "10px",
      fontWeight: 600,
      color: provColor
    }
  }, /*#__PURE__*/React.createElement("span", {
    style: {
      width: "6px",
      height: "6px",
      borderRadius: "50%",
      background: "currentColor"
    }
  }), provText)));
}
})(); } catch (e) { __ds_ns.__errors.push({ path: "design_handoff_nokido/components/modules/module-card.ref.jsx", error: String((e && e.message) || e) }); }

// design_handoff_nokido/components/sovereignty/power-slider.ref.jsx
try { (() => {
/* Référence design (handoff) — composant du DS Nokido. Source canonique : components/ à la racine du projet. */

function PowerSlider({
  value = 60,
  onChange = null,
  style = {}
}) {
  const [internal, setInternal] = React.useState(value);
  const v = onChange ? value : internal;
  function set(next) {
    if (onChange) onChange(next);else setInternal(next);
  }

  // Dérivés lisibles en temps réel : plus de puissance allouée → plus local.
  const localShare = v;
  const privacy = v; // ↑ avec le local
  const cost = Math.round(100 - v * 0.85); // cloud = coût
  const latency = Math.round(30 + (100 - v) * 0.9); // cloud = +latence réseau

  const metric = (lbl, val, unit, color) => /*#__PURE__*/React.createElement("div", {
    style: {
      flex: 1
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      fontSize: "10px",
      textTransform: "uppercase",
      letterSpacing: "0.5px",
      color: "var(--text-dim)"
    }
  }, lbl), /*#__PURE__*/React.createElement("div", {
    style: {
      fontFamily: "var(--font-mono)",
      fontSize: "14px",
      fontWeight: 700,
      color
    }
  }, val, unit));
  return /*#__PURE__*/React.createElement("div", {
    style: {
      background: "var(--bg-2)",
      border: "1px solid var(--border)",
      borderRadius: "var(--radius-md)",
      padding: "16px",
      ...style
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      justifyContent: "space-between",
      alignItems: "baseline",
      marginBottom: "12px"
    }
  }, /*#__PURE__*/React.createElement("span", {
    style: {
      fontSize: "13px",
      fontWeight: 600,
      color: "var(--text-primary)"
    }
  }, "Puissance de calcul allou\xE9e"), /*#__PURE__*/React.createElement("span", {
    style: {
      fontFamily: "var(--font-mono)",
      fontSize: "13px",
      color: "var(--prov-local)"
    }
  }, v, "%")), /*#__PURE__*/React.createElement("input", {
    type: "range",
    min: "0",
    max: "100",
    value: v,
    onChange: e => set(Number(e.target.value)),
    style: {
      width: "100%",
      appearance: "none",
      WebkitAppearance: "none",
      height: "6px",
      borderRadius: "var(--radius-pill)",
      outline: "none",
      cursor: "pointer",
      background: `linear-gradient(90deg, var(--prov-local) 0%, var(--prov-local) ${v}%, var(--prov-remote-tint) ${v}%, var(--prov-remote-tint) 100%)`
    },
    className: "lf-power-range"
  }), /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      justifyContent: "space-between",
      marginTop: "6px",
      fontFamily: "var(--font-mono)",
      fontSize: "10px",
      color: "var(--text-dim)"
    }
  }, /*#__PURE__*/React.createElement("span", null, "\u2190 cloud (d\xE9l\xE8gue)"), /*#__PURE__*/React.createElement("span", null, "local (souverain) \u2192")), /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      gap: "12px",
      marginTop: "16px",
      paddingTop: "14px",
      borderTop: "1px solid var(--border-subtle)"
    }
  }, metric("Confidentialité", privacy, "%", "var(--prov-local)"), metric("Local", localShare, "%", "var(--prov-hybrid)"), metric("Coût relatif", cost, "%", "var(--orange)"), metric("Latence", latency, "ms", "var(--blue)")), /*#__PURE__*/React.createElement("style", null, `
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
      `));
}
})(); } catch (e) { __ds_ns.__errors.push({ path: "design_handoff_nokido/components/sovereignty/power-slider.ref.jsx", error: String((e && e.message) || e) }); }

// design_handoff_nokido/components/sovereignty/provenance-badge.ref.jsx
try { (() => {
/* Référence design (handoff) — composant du DS Nokido. Source canonique : components/ à la racine du projet. */
function ProvenanceBadge({
  origin = "local",
  ring = null,
  label = null,
  detail = null,
  size = "md",
  style = {}
}) {
  const origins = {
    local: {
      color: "var(--prov-local)",
      bg: "var(--prov-local-tint)",
      text: "LOCAL"
    },
    hybrid: {
      color: "var(--prov-hybrid)",
      bg: "var(--prov-hybrid-tint)",
      text: "HYBRIDE"
    },
    remote: {
      color: "var(--prov-remote)",
      bg: "var(--prov-remote-tint)",
      text: "DISTANT"
    }
  };
  const rings = {
    draft: {
      color: "var(--ring-draft)",
      text: "brouillon"
    },
    verified: {
      color: "var(--ring-verified)",
      text: "vérifié"
    },
    gold: {
      color: "var(--ring-gold)",
      text: "or"
    }
  };
  const o = origins[origin] || origins.local;
  const r = ring ? rings[ring] : null;
  const sm = size === "sm";
  return /*#__PURE__*/React.createElement("span", {
    style: {
      display: "inline-flex",
      alignItems: "center",
      gap: "7px",
      fontFamily: "var(--font-mono)",
      fontSize: sm ? "10px" : "11px",
      fontWeight: 600,
      padding: sm ? "2px 8px" : "3px 10px",
      borderRadius: "var(--radius-pill)",
      color: o.color,
      background: o.bg,
      ...style
    }
  }, /*#__PURE__*/React.createElement("span", {
    style: {
      width: sm ? "6px" : "7px",
      height: sm ? "6px" : "7px",
      borderRadius: "50%",
      background: "currentColor"
    }
  }), /*#__PURE__*/React.createElement("span", null, label || o.text), r && /*#__PURE__*/React.createElement(React.Fragment, null, /*#__PURE__*/React.createElement("span", {
    style: {
      width: "1px",
      height: "10px",
      background: "currentColor",
      opacity: 0.3
    }
  }), /*#__PURE__*/React.createElement("span", {
    style: {
      display: "inline-flex",
      alignItems: "center",
      gap: "4px",
      color: r.color,
      opacity: 0.95
    }
  }, /*#__PURE__*/React.createElement("span", {
    style: {
      width: "8px",
      height: "8px",
      borderRadius: "50%",
      background: ring === "draft" ? "transparent" : r.color,
      border: ring === "draft" ? `1.5px dashed ${r.color}` : "none",
      boxShadow: ring === "gold" ? "0 0 6px rgba(255,194,45,0.6)" : "none"
    }
  }), r.text)), detail && /*#__PURE__*/React.createElement("span", {
    style: {
      color: "var(--text-dim)",
      fontWeight: 400
    }
  }, "\xB7 ", detail));
}
})(); } catch (e) { __ds_ns.__errors.push({ path: "design_handoff_nokido/components/sovereignty/provenance-badge.ref.jsx", error: String((e && e.message) || e) }); }

// design_handoff_nokido/components/sovereignty/sovereignty-gauge.ref.jsx
try { (() => {
/* Référence design (handoff) — composant du DS Nokido. Source canonique : components/ à la racine du projet. */
function SovereigntyGauge({
  local = 70,
  label = "Souveraineté",
  showLegend = true,
  height = 10,
  style = {}
}) {
  const pct = Math.max(0, Math.min(100, local));
  return /*#__PURE__*/React.createElement("div", {
    style: {
      ...style
    }
  }, label && /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      justifyContent: "space-between",
      alignItems: "baseline",
      marginBottom: "7px"
    }
  }, /*#__PURE__*/React.createElement("span", {
    style: {
      fontSize: "11px",
      fontWeight: 600,
      textTransform: "uppercase",
      letterSpacing: "0.5px",
      color: "var(--text-secondary)"
    }
  }, label), /*#__PURE__*/React.createElement("span", {
    style: {
      fontFamily: "var(--font-mono)",
      fontSize: "12px",
      color: "var(--prov-local)"
    }
  }, pct, "% local")), /*#__PURE__*/React.createElement("div", {
    style: {
      position: "relative",
      height: `${height}px`,
      borderRadius: "var(--radius-pill)",
      background: "var(--prov-remote-tint)",
      overflow: "hidden",
      border: "1px solid var(--border-subtle)"
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      position: "absolute",
      left: 0,
      top: 0,
      bottom: 0,
      width: `${pct}%`,
      background: "linear-gradient(90deg, var(--prov-local), #5fd6a0)",
      boxShadow: "0 0 12px rgba(74,194,139,0.4)",
      transition: "width var(--motion-slow) var(--ease-out)"
    }
  })), showLegend && /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      justifyContent: "space-between",
      marginTop: "6px",
      fontFamily: "var(--font-mono)",
      fontSize: "10px",
      color: "var(--text-dim)"
    }
  }, /*#__PURE__*/React.createElement("span", {
    style: {
      color: "var(--prov-local)"
    }
  }, "\u25CF local \xB7 souverain"), /*#__PURE__*/React.createElement("span", {
    style: {
      color: "var(--prov-remote)"
    }
  }, "distant \xB7 cloud \u25CF")));
}
})(); } catch (e) { __ds_ns.__errors.push({ path: "design_handoff_nokido/components/sovereignty/sovereignty-gauge.ref.jsx", error: String((e && e.message) || e) }); }

// design_handoff_nokido/ui_kits/composer/composer-app.ref.jsx
try { (() => {
/* Nokido — Composer son app : l'utilisateur compose SA vue à partir des sections.
   Catalogue (gauche) → ta vue (droite) ; épingler, masquer, réordonner. */
const {
  Button,
  Badge,
  ModuleCard,
  ProvenanceBadge,
  SovereigntyGauge
} = window.NokidoDesignSystem_bdc2ac;
function CIco({
  n,
  s = 18
}) {
  return /*#__PURE__*/React.createElement("i", {
    "data-lucide": n,
    style: {
      width: s,
      height: s
    }
  });
}
const CATALOG = [{
  id: "sante",
  domain: "sante",
  title: "Santé",
  desc: "Suivi, rappels, données sensibles",
  icon: "heart-pulse",
  provenance: "local"
}, {
  id: "domotique",
  domain: "domotique",
  title: "Domotique",
  desc: "Hub maison, scènes, local-first",
  icon: "house",
  provenance: "local"
}, {
  id: "transport",
  domain: "transport",
  title: "Transport",
  desc: "Trajets, mobilité, temps réel",
  icon: "route",
  provenance: "hybrid"
}, {
  id: "finance",
  domain: "finance",
  title: "Finance",
  desc: "Comptes, budgets, traçabilité",
  icon: "wallet",
  provenance: "local"
}, {
  id: "loisir",
  domain: "loisir",
  title: "Loisir",
  desc: "Sorties, médias, agenda",
  icon: "compass",
  provenance: "hybrid"
}, {
  id: "achat",
  domain: "achat",
  title: "Achat",
  desc: "Comparaison neutre, suivi prix",
  icon: "shopping-cart",
  provenance: "remote"
}, {
  id: "creation",
  domain: "creation",
  title: "Création",
  desc: "Texte, image, son, code",
  icon: "sparkles",
  provenance: "hybrid"
}, {
  id: "dev",
  domain: "dev",
  title: "Dev",
  desc: "Code, automatisations, skills",
  icon: "terminal",
  provenance: "local"
}, {
  id: "travail",
  domain: "travail",
  title: "Travail",
  desc: "Focus, tâches, documents",
  icon: "briefcase",
  provenance: "local"
}, {
  id: "energie",
  domain: "energie",
  title: "Énergie",
  desc: "Conso, sobriété, pilotage",
  icon: "zap",
  provenance: "local"
}, {
  id: "famille",
  domain: "famille",
  title: "Famille",
  desc: "Agenda commun, partage",
  icon: "users",
  provenance: "hybrid"
}, {
  id: "voyage",
  domain: "voyage",
  title: "Voyage",
  desc: "Itinéraires, découverte",
  icon: "plane",
  provenance: "hybrid"
}];
function CatalogRow({
  mod,
  onAdd
}) {
  const accent = `var(--domain-${mod.domain})`;
  return /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      alignItems: "center",
      gap: "11px",
      padding: "9px 11px",
      background: "var(--bg-2)",
      border: "1px solid var(--border)",
      borderRadius: "var(--radius-sm)"
    }
  }, /*#__PURE__*/React.createElement("span", {
    style: {
      display: "inline-flex",
      alignItems: "center",
      justifyContent: "center",
      width: "32px",
      height: "32px",
      borderRadius: "var(--radius-sm)",
      background: `color-mix(in srgb, ${accent} 16%, transparent)`,
      color: accent,
      flexShrink: 0
    }
  }, /*#__PURE__*/React.createElement(CIco, {
    n: mod.icon,
    s: 17
  })), /*#__PURE__*/React.createElement("div", {
    style: {
      flex: 1,
      minWidth: 0
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      fontSize: "12.5px",
      fontWeight: 600
    }
  }, mod.title), /*#__PURE__*/React.createElement("div", {
    style: {
      fontSize: "10.5px",
      color: "var(--text-dim)",
      whiteSpace: "nowrap",
      overflow: "hidden",
      textOverflow: "ellipsis"
    }
  }, mod.desc)), /*#__PURE__*/React.createElement("button", {
    onClick: () => onAdd(mod.id),
    "aria-label": "Ajouter",
    style: {
      display: "inline-flex",
      alignItems: "center",
      justifyContent: "center",
      width: "28px",
      height: "28px",
      borderRadius: "var(--radius-sm)",
      border: "1px solid var(--border)",
      background: "transparent",
      color: "var(--purple)",
      cursor: "pointer",
      flexShrink: 0
    }
  }, /*#__PURE__*/React.createElement(CIco, {
    n: "plus",
    s: 16
  })));
}
function ComposerApp() {
  const [active, setActive] = React.useState(["sante", "domotique", "transport", "creation"]);
  const [pinned, setPinned] = React.useState({
    sante: true,
    domotique: true
  });
  React.useEffect(() => {
    if (window.lucide) lucide.createIcons();
  });
  const byId = id => CATALOG.find(m => m.id === id);
  const inCatalog = CATALOG.filter(m => !active.includes(m.id));
  const add = id => setActive(a => a.includes(id) ? a : [...a, id]);
  const remove = id => {
    setActive(a => a.filter(x => x !== id));
    setPinned(p => {
      const n = {
        ...p
      };
      delete n[id];
      return n;
    });
  };
  const togglePin = id => setPinned(p => ({
    ...p,
    [id]: !p[id]
  }));
  const move = (id, dir) => setActive(a => {
    const i = a.indexOf(id);
    const j = i + dir;
    if (j < 0 || j >= a.length) return a;
    const n = [...a];
    [n[i], n[j]] = [n[j], n[i]];
    return n;
  });

  // pinned first
  const ordered = [...active].sort((x, y) => (pinned[y] ? 1 : 0) - (pinned[x] ? 1 : 0));
  const localCount = active.filter(id => byId(id).provenance === "local").length;
  const localPct = active.length ? Math.round(localCount / active.length * 100) : 0;
  return /*#__PURE__*/React.createElement("div", {
    style: {
      display: "grid",
      gridTemplateColumns: "300px 1fr",
      height: "100vh",
      background: "var(--bg-0)",
      color: "var(--text-primary)"
    }
  }, /*#__PURE__*/React.createElement("aside", {
    style: {
      background: "var(--bg-1)",
      borderRight: "1px solid var(--border-subtle)",
      display: "flex",
      flexDirection: "column",
      minHeight: 0
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      padding: "16px 16px 12px",
      borderBottom: "1px solid var(--border-subtle)"
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      fontSize: "13px",
      fontWeight: 700
    }
  }, "Catalogue"), /*#__PURE__*/React.createElement("div", {
    style: {
      fontSize: "11px",
      color: "var(--text-dim)"
    }
  }, inCatalog.length, " sections disponibles")), /*#__PURE__*/React.createElement("div", {
    style: {
      flex: 1,
      overflowY: "auto",
      padding: "12px",
      display: "flex",
      flexDirection: "column",
      gap: "8px"
    }
  }, inCatalog.map(m => /*#__PURE__*/React.createElement(CatalogRow, {
    key: m.id,
    mod: m,
    onAdd: add
  })), inCatalog.length === 0 && /*#__PURE__*/React.createElement("div", {
    style: {
      padding: "20px",
      textAlign: "center",
      color: "var(--text-dim)",
      fontSize: "12px"
    }
  }, "Toutes les sections sont dans ta vue."))), /*#__PURE__*/React.createElement("main", {
    style: {
      display: "flex",
      flexDirection: "column",
      minWidth: 0
    }
  }, /*#__PURE__*/React.createElement("header", {
    style: {
      height: "var(--topbar-h)",
      borderBottom: "1px solid var(--border-subtle)",
      background: "var(--bg-1)",
      display: "flex",
      alignItems: "center",
      padding: "0 22px",
      gap: "12px",
      flexShrink: 0
    }
  }, /*#__PURE__*/React.createElement("div", null, /*#__PURE__*/React.createElement("div", {
    style: {
      fontSize: "15px",
      fontWeight: 700,
      lineHeight: 1.1
    }
  }, "Compose ton app"), /*#__PURE__*/React.createElement("div", {
    style: {
      fontSize: "11px",
      color: "var(--text-dim)",
      fontFamily: "var(--font-mono)"
    }
  }, "\xE9pingle \xB7 masque \xB7 r\xE9ordonne tes sections")), /*#__PURE__*/React.createElement("div", {
    style: {
      marginLeft: "auto",
      display: "flex",
      alignItems: "center",
      gap: "12px"
    }
  }, /*#__PURE__*/React.createElement(SovereigntyGauge, {
    local: localPct,
    label: null,
    showLegend: false,
    height: 7,
    style: {
      width: "120px"
    }
  }), /*#__PURE__*/React.createElement("span", {
    style: {
      fontFamily: "var(--font-mono)",
      fontSize: "11px",
      color: "var(--prov-local)"
    }
  }, localPct, "% local"), /*#__PURE__*/React.createElement(Button, {
    variant: "primary",
    size: "sm",
    icon: /*#__PURE__*/React.createElement(CIco, {
      n: "check",
      s: 14
    })
  }, "Enregistrer"))), /*#__PURE__*/React.createElement("div", {
    style: {
      flex: 1,
      overflowY: "auto",
      padding: "22px 24px"
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      alignItems: "baseline",
      gap: "10px",
      marginBottom: "14px"
    }
  }, /*#__PURE__*/React.createElement("h2", {
    style: {
      margin: 0,
      fontSize: "13px",
      fontWeight: 700,
      textTransform: "uppercase",
      letterSpacing: "0.6px",
      color: "var(--text-secondary)"
    }
  }, "Ta vue"), /*#__PURE__*/React.createElement("span", {
    style: {
      fontFamily: "var(--font-mono)",
      fontSize: "11px",
      color: "var(--text-dim)"
    }
  }, active.length, " sections \xB7 ", Object.values(pinned).filter(Boolean).length, " \xE9pingl\xE9es")), active.length === 0 ? /*#__PURE__*/React.createElement("div", {
    style: {
      padding: "50px",
      textAlign: "center",
      color: "var(--text-dim)",
      border: "1px dashed var(--border)",
      borderRadius: "var(--radius-md)"
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      marginBottom: "8px"
    }
  }, /*#__PURE__*/React.createElement(CIco, {
    n: "layout-grid",
    s: 26
  })), "Ajoute des sections depuis le catalogue pour composer ton app.") : /*#__PURE__*/React.createElement("div", {
    style: {
      display: "grid",
      gridTemplateColumns: "repeat(auto-fill, minmax(232px, 1fr))",
      gap: "14px"
    }
  }, ordered.map(id => {
    const m = byId(id);
    return /*#__PURE__*/React.createElement("div", {
      key: id,
      style: {
        position: "relative"
      }
    }, /*#__PURE__*/React.createElement(ModuleCard, {
      domain: m.domain,
      title: m.title,
      desc: m.desc,
      icon: /*#__PURE__*/React.createElement(CIco, {
        n: m.icon,
        s: 22
      }),
      provenance: m.provenance,
      pinned: !!pinned[id]
    }), /*#__PURE__*/React.createElement("div", {
      style: {
        display: "flex",
        gap: "5px",
        marginTop: "8px"
      }
    }, /*#__PURE__*/React.createElement(CtrlBtn, {
      icon: pinned[id] ? "pin-off" : "pin",
      label: pinned[id] ? "Désépingler" : "Épingler",
      active: pinned[id],
      onClick: () => togglePin(id)
    }), /*#__PURE__*/React.createElement(CtrlBtn, {
      icon: "arrow-up",
      onClick: () => move(id, -1)
    }), /*#__PURE__*/React.createElement(CtrlBtn, {
      icon: "arrow-down",
      onClick: () => move(id, 1)
    }), /*#__PURE__*/React.createElement(CtrlBtn, {
      icon: "eye-off",
      label: "Masquer",
      onClick: () => remove(id),
      danger: true
    })));
  })))));
}
function CtrlBtn({
  icon,
  label,
  onClick,
  active,
  danger
}) {
  return /*#__PURE__*/React.createElement("button", {
    onClick: onClick,
    title: label,
    style: {
      display: "inline-flex",
      alignItems: "center",
      gap: "6px",
      padding: label ? "5px 9px" : "5px",
      borderRadius: "var(--radius-sm)",
      cursor: "pointer",
      fontFamily: "var(--font-sans)",
      fontSize: "11px",
      border: `1px solid ${active ? "var(--purple)" : "var(--border)"}`,
      background: active ? "var(--tint-purple)" : "transparent",
      color: danger ? "var(--text-secondary)" : active ? "var(--purple)" : "var(--text-secondary)"
    }
  }, /*#__PURE__*/React.createElement(InlineIcon, {
    name: icon
  }), label);
}

// Inline SVG icons (React-owned — never mutated by lucide.createIcons)
const ICON_PATHS = {
  pin: ["M12 17v5", "M9 10.76a2 2 0 0 1-1.11 1.79l-1.78.9A2 2 0 0 0 5 15.24V16a1 1 0 0 0 1 1h12a1 1 0 0 0 1-1v-.76a2 2 0 0 0-1.11-1.79l-1.78-.9A2 2 0 0 1 15 10.76V7a1 1 0 0 1 1-1 2 2 0 0 0 0-4H8a2 2 0 0 0 0 4 1 1 0 0 1 1 1z"],
  "pin-off": ["M12 17v5", "M15 9.34V7a1 1 0 0 1 1-1 2 2 0 0 0 0-4H7.89", "M9 9v1.76a2 2 0 0 1-1.11 1.79l-1.78.9A2 2 0 0 0 5 15.24V16a1 1 0 0 0 1 1h11", "m2 2 20 20"],
  "arrow-up": ["m5 12 7-7 7 7", "M12 19V5"],
  "arrow-down": ["M12 5v14", "m19 12-7 7-7-7"],
  "eye-off": ["M10.73 5.08A10.43 10.43 0 0 1 12 5c5 0 9 4 10 7a13.16 13.16 0 0 1-1.67 2.68", "M6.61 6.61A13.5 13.5 0 0 0 2 12c1 3 5 7 10 7a9.7 9.7 0 0 0 5.39-1.61", "M9.88 9.88a3 3 0 1 0 4.24 4.24", "m2 2 20 20"]
};
function InlineIcon({
  name,
  size = 13
}) {
  const paths = ICON_PATHS[name] || [];
  return /*#__PURE__*/React.createElement("svg", {
    width: size,
    height: size,
    viewBox: "0 0 24 24",
    fill: "none",
    stroke: "currentColor",
    strokeWidth: "2",
    strokeLinecap: "round",
    strokeLinejoin: "round",
    style: {
      flexShrink: 0
    }
  }, paths.map((d, i) => /*#__PURE__*/React.createElement("path", {
    key: i,
    d: d
  })));
}
Object.assign(window, {
  ComposerApp
});
})(); } catch (e) { __ds_ns.__errors.push({ path: "design_handoff_nokido/ui_kits/composer/composer-app.ref.jsx", error: String((e && e.message) || e) }); }

// design_handoff_nokido/ui_kits/hub/hub-shell.ref.jsx
try { (() => {
/* Nokido Hub — coquille : sidebar souveraine + topbar avec jauge & persona */
const {
  SovereigntyGauge,
  Badge,
  ProvenanceBadge
} = window.NokidoDesignSystem_bdc2ac;
const NAV = [{
  id: "accueil",
  label: "Accueil",
  icon: "layout-grid"
}, {
  id: "cap",
  label: "Intention longue",
  icon: "target"
}, {
  id: "federation",
  label: "Fédération",
  icon: "share-2"
}, {
  id: "maison",
  label: "Maison",
  icon: "house"
}, {
  id: "persona",
  label: "Mémoire persona",
  icon: "brain"
}, {
  id: "souverainete",
  label: "Souveraineté",
  icon: "shield-check"
}];
function Ico({
  n,
  s = 18
}) {
  return /*#__PURE__*/React.createElement("i", {
    "data-lucide": n,
    style: {
      width: s,
      height: s
    }
  });
}
function HubSidebar({
  active,
  onNav,
  local
}) {
  return /*#__PURE__*/React.createElement("aside", {
    style: {
      width: "var(--sidebar-w)",
      background: "var(--bg-1)",
      borderRight: "1px solid var(--border-subtle)",
      display: "flex",
      flexDirection: "column",
      flexShrink: 0
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      alignItems: "center",
      gap: "8px",
      padding: "14px 16px",
      borderBottom: "1px solid var(--border-subtle)"
    }
  }, /*#__PURE__*/React.createElement("svg", {
    width: "26",
    height: "26",
    viewBox: "0 0 64 64",
    fill: "none",
    style: {
      flexShrink: 0
    }
  }, /*#__PURE__*/React.createElement("defs", null, /*#__PURE__*/React.createElement("linearGradient", {
    id: "lfBolt",
    x1: "26",
    y1: "12",
    x2: "40",
    y2: "40",
    gradientUnits: "userSpaceOnUse"
  }, /*#__PURE__*/React.createElement("stop", {
    offset: "0",
    stopColor: "#FFE070"
  }), /*#__PURE__*/React.createElement("stop", {
    offset: "1",
    stopColor: "#FFC22D"
  }))), /*#__PURE__*/React.createElement("g", {
    stroke: "#15121F",
    strokeWidth: "2.4",
    strokeLinejoin: "round"
  }, /*#__PURE__*/React.createElement("path", {
    d: "M6 35 L20 31 H48 q4 0 4 3.5 Q52 39 47 39 H39 q-3 0 -4 3 l-1.5 3 H27 q-1 -3 -4 -3 H15 Q6 42 6 35 Z",
    fill: "#9A90BC"
  }), /*#__PURE__*/React.createElement("path", {
    d: "M28 45 h8 l-1.5 5 h-5 Z",
    fill: "#6F6498"
  }), /*#__PURE__*/React.createElement("path", {
    d: "M17 50 H47 l3 6 H14 Z",
    fill: "#9A90BC"
  })), /*#__PURE__*/React.createElement("g", null, /*#__PURE__*/React.createElement("rect", {
    x: "4",
    y: "29",
    width: "23",
    height: "5",
    rx: "2.5",
    fill: "#C77D4A",
    stroke: "#15121F",
    strokeWidth: "2.4",
    strokeLinejoin: "round"
  }), /*#__PURE__*/React.createElement("rect", {
    x: "25",
    y: "21",
    width: "11",
    height: "21",
    rx: "3",
    fill: "#B7BCD2",
    stroke: "#15121F",
    strokeWidth: "2.4",
    strokeLinejoin: "round"
  }), /*#__PURE__*/React.createElement("rect", {
    x: "27.5",
    y: "24",
    width: "5.5",
    height: "6",
    rx: "1.5",
    fill: "#D9DCE8"
  })), /*#__PURE__*/React.createElement("path", {
    d: "M31 41 L40 26 H34 L42 11 L30 28 H36 Z",
    fill: "url(#lfBolt)",
    stroke: "#15121F",
    strokeWidth: "2",
    strokeLinejoin: "round"
  })), /*#__PURE__*/React.createElement("span", {
    style: {
      fontWeight: 700,
      fontSize: "15px",
      letterSpacing: "0.4px"
    }
  }, "Nokido"), /*#__PURE__*/React.createElement("span", {
    className: "laforge-pulse",
    style: {
      marginLeft: "auto",
      width: "7px",
      height: "7px",
      borderRadius: "50%",
      background: "var(--green)"
    }
  })), /*#__PURE__*/React.createElement("nav", {
    style: {
      padding: "10px 8px",
      display: "flex",
      flexDirection: "column",
      gap: "2px"
    }
  }, NAV.map(n => {
    const on = active === n.id;
    return /*#__PURE__*/React.createElement("button", {
      key: n.id,
      onClick: () => onNav(n.id),
      style: {
        display: "flex",
        alignItems: "center",
        gap: "10px",
        padding: "9px 11px",
        borderRadius: "var(--radius-sm)",
        border: "none",
        cursor: "pointer",
        textAlign: "left",
        fontSize: "13px",
        fontWeight: on ? 600 : 500,
        fontFamily: "var(--font-sans)",
        background: on ? "var(--bg-3)" : "transparent",
        color: on ? "var(--text-primary)" : "var(--text-secondary)",
        boxShadow: on ? "inset 3px 0 0 var(--purple)" : "none",
        transition: "background var(--motion-fast)"
      },
      onMouseEnter: e => {
        if (!on) e.currentTarget.style.background = "var(--bg-2)";
      },
      onMouseLeave: e => {
        if (!on) e.currentTarget.style.background = "transparent";
      }
    }, /*#__PURE__*/React.createElement(Ico, {
      n: n.icon
    }), n.label);
  })), /*#__PURE__*/React.createElement("div", {
    style: {
      marginTop: "auto",
      padding: "14px",
      borderTop: "1px solid var(--border-subtle)"
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      gap: "6px",
      marginBottom: "12px"
    }
  }, /*#__PURE__*/React.createElement("a", {
    href: "../composer/index.html",
    title: "Composer son app",
    style: {
      flex: 1,
      display: "inline-flex",
      alignItems: "center",
      justifyContent: "center",
      gap: "5px",
      padding: "6px",
      borderRadius: "var(--radius-sm)",
      border: "1px solid var(--border)",
      color: "var(--text-secondary)",
      fontSize: "10.5px",
      fontFamily: "var(--font-mono)"
    }
  }, /*#__PURE__*/React.createElement(Ico, {
    n: "layout-dashboard",
    s: 13
  }), "Composer"), /*#__PURE__*/React.createElement("a", {
    href: "../login/index.html",
    title: "Verrouiller le coffre",
    style: {
      display: "inline-flex",
      alignItems: "center",
      justifyContent: "center",
      padding: "6px 9px",
      borderRadius: "var(--radius-sm)",
      border: "1px solid var(--border)",
      color: "var(--text-secondary)"
    }
  }, /*#__PURE__*/React.createElement(Ico, {
    n: "lock",
    s: 13
  }))), /*#__PURE__*/React.createElement(SovereigntyGauge, {
    local: local,
    showLegend: false,
    height: 8
  }), /*#__PURE__*/React.createElement("div", {
    style: {
      marginTop: "12px",
      display: "flex",
      alignItems: "center",
      gap: "8px"
    }
  }, /*#__PURE__*/React.createElement("span", {
    style: {
      width: "26px",
      height: "26px",
      borderRadius: "50%",
      background: "var(--purple-dim)",
      display: "flex",
      alignItems: "center",
      justifyContent: "center",
      fontSize: "11px",
      fontWeight: 700
    }
  }, "N"), /*#__PURE__*/React.createElement("div", {
    style: {
      lineHeight: 1.2
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      fontSize: "12px",
      fontWeight: 600
    }
  }, "user"), /*#__PURE__*/React.createElement("div", {
    style: {
      fontFamily: "var(--font-mono)",
      fontSize: "9.5px",
      color: "var(--text-dim)"
    }
  }, "Ring 0 \xB7 n\u0153ud souverain")))));
}
function HubTopbar({
  title,
  subtitle,
  right
}) {
  return /*#__PURE__*/React.createElement("header", {
    style: {
      height: "var(--topbar-h)",
      borderBottom: "1px solid var(--border-subtle)",
      background: "var(--bg-1)",
      display: "flex",
      alignItems: "center",
      padding: "0 22px",
      gap: "14px",
      flexShrink: 0
    }
  }, /*#__PURE__*/React.createElement("div", null, /*#__PURE__*/React.createElement("div", {
    style: {
      fontSize: "15px",
      fontWeight: 700,
      lineHeight: 1.1
    }
  }, title), subtitle && /*#__PURE__*/React.createElement("div", {
    style: {
      fontSize: "11px",
      color: "var(--text-dim)",
      fontFamily: "var(--font-mono)"
    }
  }, subtitle)), /*#__PURE__*/React.createElement("div", {
    style: {
      marginLeft: "auto",
      display: "flex",
      alignItems: "center",
      gap: "10px"
    }
  }, right));
}
window.HubSidebar = HubSidebar;
window.HubTopbar = HubTopbar;
window.HubIco = Ico;
})(); } catch (e) { __ds_ns.__errors.push({ path: "design_handoff_nokido/ui_kits/hub/hub-shell.ref.jsx", error: String((e && e.message) || e) }); }

// design_handoff_nokido/ui_kits/hub/hub-views.ref.jsx
try { (() => {
function _extends() { return _extends = Object.assign ? Object.assign.bind() : function (n) { for (var e = 1; e < arguments.length; e++) { var t = arguments[e]; for (var r in t) ({}).hasOwnProperty.call(t, r) && (n[r] = t[r]); } return n; }, _extends.apply(null, arguments); }
/* Nokido Hub — vues principales */
const {
  Card,
  Button,
  Badge,
  StatusPill,
  ProvenanceBadge,
  SovereigntyGauge,
  PowerSlider,
  ModuleCard,
  CapStep,
  TextInput
} = window.NokidoDesignSystem_bdc2ac;
const Ico = window.HubIco;
const MODULES = [{
  domain: "transport",
  title: "Transport",
  desc: "Trajets, mobilité, logistique perso",
  icon: "route",
  provenance: "hybrid",
  status: "up"
}, {
  domain: "sante",
  title: "Santé",
  desc: "Suivi, rappels, données sensibles",
  icon: "heart-pulse",
  provenance: "local",
  pinned: true
}, {
  domain: "finance",
  title: "Finance",
  desc: "Comptes, budgets, traçabilité",
  icon: "wallet",
  provenance: "local"
}, {
  domain: "loisir",
  title: "Loisir",
  desc: "Sorties, médias, agenda perso",
  icon: "compass",
  provenance: "hybrid"
}, {
  domain: "achat",
  title: "Achat",
  desc: "Comparaison neutre, suivi prix",
  icon: "shopping-cart",
  provenance: "remote"
}, {
  domain: "creation",
  title: "Création",
  desc: "Texte, image, son, code génératif",
  icon: "sparkles",
  provenance: "hybrid"
}, {
  domain: "dev",
  title: "Dev",
  desc: "Code, automatisations, MCP & skills",
  icon: "terminal",
  provenance: "local"
}, {
  domain: "domotique",
  title: "Domotique",
  desc: "Hub maison, scènes, local-first",
  icon: "house",
  provenance: "local",
  pinned: true
}, {
  domain: "jeux",
  title: "Jeux vidéo",
  desc: "Bibliothèque & compagnons",
  icon: "gamepad-2",
  comingSoon: true
}];
function SectionTitle({
  children,
  hint
}) {
  return /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      alignItems: "baseline",
      gap: "10px",
      margin: "0 0 14px"
    }
  }, /*#__PURE__*/React.createElement("h2", {
    style: {
      margin: 0,
      fontSize: "13px",
      fontWeight: 700,
      textTransform: "uppercase",
      letterSpacing: "0.6px",
      color: "var(--text-secondary)"
    }
  }, children), hint && /*#__PURE__*/React.createElement("span", {
    style: {
      fontSize: "11px",
      color: "var(--text-dim)",
      fontFamily: "var(--font-mono)"
    }
  }, hint));
}

/* ---------------- Accueil ---------------- */
function ViewAccueil({
  enabled,
  onToggle
}) {
  return /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      flexDirection: "column",
      gap: "26px"
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      display: "grid",
      gridTemplateColumns: "2fr 1fr",
      gap: "14px"
    }
  }, /*#__PURE__*/React.createElement(Card, {
    style: {
      background: "var(--bg-1)"
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      alignItems: "center",
      gap: "8px",
      marginBottom: "10px"
    }
  }, /*#__PURE__*/React.createElement(Ico, {
    n: "target",
    s: 16
  }), /*#__PURE__*/React.createElement("span", {
    style: {
      fontWeight: 700,
      fontSize: "14px"
    }
  }, "Cap en cours"), /*#__PURE__*/React.createElement(Badge, {
    color: "purple",
    mono: true
  }, "112 \xE9tapes")), /*#__PURE__*/React.createElement("p", {
    style: {
      margin: 0,
      fontSize: "15px",
      color: "var(--text-primary)",
      lineHeight: 1.5
    }
  }, "\xAB Reprendre le contr\xF4le de mes donn\xE9es de sant\xE9 et passer la maison 100 % local-first d'ici l'automne. \xBB"), /*#__PURE__*/React.createElement("div", {
    style: {
      marginTop: "14px",
      display: "flex",
      alignItems: "center",
      gap: "10px"
    }
  }, /*#__PURE__*/React.createElement(SovereigntyGauge, {
    local: 68,
    label: null,
    showLegend: false,
    height: 8,
    style: {
      flex: 1
    }
  }), /*#__PURE__*/React.createElement("span", {
    style: {
      fontFamily: "var(--font-mono)",
      fontSize: "11px",
      color: "var(--text-dim)"
    }
  }, "jalon 4 / 9"))), /*#__PURE__*/React.createElement(Card, {
    style: {
      background: "var(--bg-1)"
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      alignItems: "center",
      gap: "8px",
      marginBottom: "10px"
    }
  }, /*#__PURE__*/React.createElement(Ico, {
    n: "brain",
    s: 16
  }), /*#__PURE__*/React.createElement("span", {
    style: {
      fontWeight: 700,
      fontSize: "14px"
    }
  }, "Persona")), /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      flexDirection: "column",
      gap: "7px",
      fontSize: "12px",
      color: "var(--text-secondary)"
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      justifyContent: "space-between"
    }
  }, /*#__PURE__*/React.createElement("span", null, "Maturit\xE9"), /*#__PURE__*/React.createElement("span", {
    style: {
      color: "var(--cyan)",
      fontFamily: "var(--font-mono)"
    }
  }, "niveau 3 / 5")), /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      justifyContent: "space-between"
    }
  }, /*#__PURE__*/React.createElement("span", null, "Souvenirs"), /*#__PURE__*/React.createElement("span", {
    style: {
      fontFamily: "var(--font-mono)"
    }
  }, "47 actifs")), /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      justifyContent: "space-between"
    }
  }, /*#__PURE__*/React.createElement("span", null, "Ton appris"), /*#__PURE__*/React.createElement("span", {
    style: {
      fontFamily: "var(--font-mono)",
      color: "var(--text-dim)"
    }
  }, "direct \xB7 concis"))))), /*#__PURE__*/React.createElement("div", null, /*#__PURE__*/React.createElement(SectionTitle, {
    hint: "grille de modules \xB7 glisser pour r\xE9organiser"
  }, "Tes sections"), /*#__PURE__*/React.createElement("div", {
    style: {
      display: "grid",
      gridTemplateColumns: "repeat(auto-fit, minmax(248px, 1fr))",
      gap: "14px"
    }
  }, MODULES.map(m => /*#__PURE__*/React.createElement(ModuleCard, _extends({
    key: m.domain
  }, m, {
    icon: /*#__PURE__*/React.createElement(Ico, {
      n: m.icon,
      s: 22
    }),
    enabled: enabled[m.domain] !== false,
    onToggle: m.comingSoon ? null : v => onToggle(m.domain, v)
  }))))));
}

/* ---------------- Cap (intention longue) ---------------- */
function ViewCap() {
  const [scale, setScale] = React.useState("jalons");
  const steps = [{
    index: 1,
    title: "Cartographier l'historique des échanges",
    state: "done",
    provenance: "local",
    ring: "gold"
  }, {
    index: 2,
    title: "Reconstituer le cap depuis l'historique",
    state: "done",
    provenance: "local",
    ring: "verified"
  }, {
    index: 3,
    title: "Exporter les données de santé du cloud",
    state: "done",
    provenance: "local",
    ring: "verified"
  }, {
    index: 4,
    title: "Décomposer en 112 étapes exécutables",
    state: "active",
    provenance: "remote",
    ring: "verified"
  }, {
    index: 5,
    title: "Estimer dépendances & silos parallèles",
    state: "pending",
    parallel: true
  }, {
    index: 6,
    title: "Migrer la domotique en local-first",
    state: "pending",
    ring: "draft"
  }, {
    index: 7,
    title: "Proposer la prochaine étape",
    state: "pending",
    ring: "draft",
    last: true
  }];
  return /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      flexDirection: "column",
      gap: "20px",
      maxWidth: "780px"
    }
  }, /*#__PURE__*/React.createElement(Card, {
    style: {
      background: "var(--bg-1)"
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      fontSize: "11px",
      textTransform: "uppercase",
      letterSpacing: "0.6px",
      color: "var(--text-dim)",
      marginBottom: "6px"
    }
  }, "Horizon \xB7 le cap"), /*#__PURE__*/React.createElement("p", {
    style: {
      margin: 0,
      fontSize: "18px",
      fontWeight: 600,
      lineHeight: 1.4
    }
  }, "Reprendre le contr\xF4le de mes donn\xE9es de sant\xE9 et passer la maison 100 % local-first.")), /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      gap: "6px"
    }
  }, ["horizon", "jalons", "étapes"].map(s => /*#__PURE__*/React.createElement("button", {
    key: s,
    onClick: () => setScale(s),
    style: {
      padding: "5px 12px",
      borderRadius: "var(--radius-pill)",
      cursor: "pointer",
      fontFamily: "var(--font-mono)",
      fontSize: "11px",
      border: "1px solid var(--border)",
      background: scale === s ? "var(--tint-purple)" : "transparent",
      color: scale === s ? "var(--purple)" : "var(--text-secondary)"
    }
  }, s)), /*#__PURE__*/React.createElement("span", {
    style: {
      marginLeft: "auto",
      alignSelf: "center",
      fontFamily: "var(--font-mono)",
      fontSize: "11px",
      color: "var(--text-dim)"
    }
  }, "112 \xE9tapes \xB7 9 jalons")), /*#__PURE__*/React.createElement(Card, null, /*#__PURE__*/React.createElement("div", {
    style: {
      marginTop: "2px"
    }
  }, steps.map(s => /*#__PURE__*/React.createElement(CapStep, _extends({
    key: s.index
  }, s)))), /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      gap: "8px",
      marginTop: "10px",
      paddingTop: "14px",
      borderTop: "1px solid var(--border-subtle)"
    }
  }, /*#__PURE__*/React.createElement(Button, {
    variant: "primary",
    size: "sm",
    icon: /*#__PURE__*/React.createElement(Ico, {
      n: "check",
      s: 14
    })
  }, "Valider l'\xE9tape"), /*#__PURE__*/React.createElement(Button, {
    variant: "ghost",
    size: "sm",
    icon: /*#__PURE__*/React.createElement(Ico, {
      n: "git-branch",
      s: 14
    })
  }, "Bifurquer"), /*#__PURE__*/React.createElement(Button, {
    variant: "ghost",
    size: "sm",
    icon: /*#__PURE__*/React.createElement(Ico, {
      n: "arrow-up-down",
      s: 14
    })
  }, "R\xE9ordonner"))));
}

/* ---------------- Maison (domotique) ---------------- */
function ViewMaison() {
  const scenes = [{
    name: "Réveil",
    icon: "sunrise",
    on: false
  }, {
    name: "Travail",
    icon: "laptop",
    on: true
  }, {
    name: "Cinéma",
    icon: "clapperboard",
    on: false
  }, {
    name: "Nuit",
    icon: "moon",
    on: false
  }];
  const devices = [{
    name: "Salon — lumières",
    icon: "lightbulb",
    status: "up",
    val: "62 %"
  }, {
    name: "Thermostat",
    icon: "thermometer",
    status: "up",
    val: "21°C"
  }, {
    name: "Porte d'entrée",
    icon: "lock",
    status: "up",
    val: "verrouillée"
  }, {
    name: "Caméra jardin",
    icon: "video",
    status: "warn",
    val: "local seul"
  }];
  return /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      flexDirection: "column",
      gap: "22px",
      maxWidth: "820px"
    }
  }, /*#__PURE__*/React.createElement(Card, {
    style: {
      background: "var(--bg-1)",
      borderColor: "var(--prov-local)",
      boxShadow: "var(--prov-local-glow)"
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      alignItems: "center",
      gap: "10px"
    }
  }, /*#__PURE__*/React.createElement(Ico, {
    n: "shield-check",
    s: 18
  }), /*#__PURE__*/React.createElement("span", {
    style: {
      fontWeight: 600
    }
  }, "Maison vivante \u2014 local-first absolu"), /*#__PURE__*/React.createElement(ProvenanceBadge, {
    origin: "local",
    detail: "ne d\xE9pend jamais du cloud",
    style: {
      marginLeft: "auto"
    }
  }))), /*#__PURE__*/React.createElement("div", null, /*#__PURE__*/React.createElement(SectionTitle, {
    hint: "d\xE9clencheurs"
  }, "Sc\xE8nes"), /*#__PURE__*/React.createElement("div", {
    style: {
      display: "grid",
      gridTemplateColumns: "repeat(4, 1fr)",
      gap: "12px"
    }
  }, scenes.map(s => /*#__PURE__*/React.createElement("button", {
    key: s.name,
    style: {
      display: "flex",
      flexDirection: "column",
      alignItems: "center",
      gap: "8px",
      padding: "16px",
      borderRadius: "var(--radius-md)",
      cursor: "pointer",
      fontFamily: "var(--font-sans)",
      background: s.on ? "var(--tint-green)" : "var(--bg-2)",
      border: `1px solid ${s.on ? "var(--prov-local)" : "var(--border)"}`,
      color: s.on ? "var(--prov-local)" : "var(--text-secondary)"
    }
  }, /*#__PURE__*/React.createElement(Ico, {
    n: s.icon,
    s: 22
  }), /*#__PURE__*/React.createElement("span", {
    style: {
      fontSize: "12.5px",
      fontWeight: 600
    }
  }, s.name))))), /*#__PURE__*/React.createElement("div", null, /*#__PURE__*/React.createElement(SectionTitle, {
    hint: "capteurs & actionneurs"
  }, "Appareils"), /*#__PURE__*/React.createElement("div", {
    style: {
      display: "grid",
      gridTemplateColumns: "1fr 1fr",
      gap: "12px"
    }
  }, devices.map(d => /*#__PURE__*/React.createElement("div", {
    key: d.name,
    style: {
      display: "flex",
      alignItems: "center",
      gap: "12px",
      padding: "13px 15px",
      background: "var(--bg-2)",
      border: "1px solid var(--border)",
      borderRadius: "var(--radius-md)"
    }
  }, /*#__PURE__*/React.createElement("span", {
    style: {
      display: "inline-flex",
      alignItems: "center",
      justifyContent: "center",
      width: "36px",
      height: "36px",
      borderRadius: "var(--radius-sm)",
      background: "var(--tint-green)",
      color: "var(--prov-local)"
    }
  }, /*#__PURE__*/React.createElement(Ico, {
    n: d.icon,
    s: 18
  })), /*#__PURE__*/React.createElement("div", {
    style: {
      flex: 1
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      fontSize: "13px",
      fontWeight: 600
    }
  }, d.name), /*#__PURE__*/React.createElement("div", {
    style: {
      fontFamily: "var(--font-mono)",
      fontSize: "11px",
      color: "var(--text-dim)"
    }
  }, d.val)), /*#__PURE__*/React.createElement(StatusPill, {
    status: d.status,
    pulse: d.status === "up"
  }, d.status === "up" ? "local" : "dégradé"))))));
}

/* ---------------- Persona (mémoire) ---------------- */
function ViewPersona() {
  const [mem, setMem] = React.useState([{
    t: "Préfère les réponses concises et directes",
    prov: "local",
    ring: "gold"
  }, {
    t: "Travaille surtout en Python le soir",
    prov: "local",
    ring: "verified"
  }, {
    t: "Données de santé : jamais vers le cloud",
    prov: "local",
    ring: "gold"
  }, {
    t: "Aime comparer les prix avant d'acheter",
    prov: "hybrid",
    ring: "verified"
  }, {
    t: "Objectif : maison 100 % local-first",
    prov: "local",
    ring: "verified"
  }]);
  const revoke = i => setMem(mem.filter((_, j) => j !== i));
  return /*#__PURE__*/React.createElement("div", {
    style: {
      maxWidth: "720px"
    }
  }, /*#__PURE__*/React.createElement(Card, {
    style: {
      background: "var(--bg-1)",
      marginBottom: "16px"
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      alignItems: "center",
      gap: "10px"
    }
  }, /*#__PURE__*/React.createElement(Ico, {
    n: "brain",
    s: 18
  }), /*#__PURE__*/React.createElement("div", null, /*#__PURE__*/React.createElement("div", {
    style: {
      fontWeight: 600
    }
  }, "Ce que Nokido a compris de toi"), /*#__PURE__*/React.createElement("div", {
    style: {
      fontSize: "12px",
      color: "var(--text-dim)"
    }
  }, "Tout est visible, \xE9ditable et r\xE9vocable. La confiance passe par le contr\xF4le.")))), /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      flexDirection: "column",
      gap: "8px"
    }
  }, mem.map((m, i) => /*#__PURE__*/React.createElement("div", {
    key: i,
    style: {
      display: "flex",
      alignItems: "center",
      gap: "12px",
      padding: "12px 15px",
      background: "var(--bg-2)",
      border: "1px solid var(--border)",
      borderRadius: "var(--radius-md)"
    }
  }, /*#__PURE__*/React.createElement("span", {
    style: {
      flex: 1,
      fontSize: "13px"
    }
  }, m.t), /*#__PURE__*/React.createElement(ProvenanceBadge, {
    origin: m.prov,
    ring: m.ring,
    size: "sm"
  }), /*#__PURE__*/React.createElement(Button, {
    variant: "ghost",
    size: "sm",
    icon: /*#__PURE__*/React.createElement(Ico, {
      n: "x",
      s: 13
    }),
    onClick: () => revoke(i)
  }, "Oublier"))), mem.length === 0 && /*#__PURE__*/React.createElement("div", {
    style: {
      padding: "30px",
      textAlign: "center",
      color: "var(--text-dim)",
      fontSize: "13px"
    }
  }, "M\xE9moire vide \u2014 Nokido repart de z\xE9ro.")));
}

/* ---------------- Souveraineté ---------------- */
function ViewSouverainete({
  local,
  setLocal
}) {
  const log = [{
    ts: "14:32:08",
    act: "ask",
    prov: "local",
    model: "ollama:mistral",
    lat: "612ms",
    ring: "gold"
  }, {
    ts: "14:31:54",
    act: "ingest",
    prov: "local",
    model: "embed:bge-m3",
    lat: "88ms",
    ring: "verified"
  }, {
    ts: "14:30:12",
    act: "ask",
    prov: "remote",
    model: "groq:llama-70b",
    lat: "248ms",
    ring: "verified"
  }, {
    ts: "14:28:03",
    act: "compare",
    prov: "hybrid",
    model: "router",
    lat: "1.2s",
    ring: "draft"
  }];
  return /*#__PURE__*/React.createElement("div", {
    style: {
      display: "grid",
      gridTemplateColumns: "1fr 1fr",
      gap: "18px",
      maxWidth: "900px",
      alignItems: "start"
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      flexDirection: "column",
      gap: "16px"
    }
  }, /*#__PURE__*/React.createElement(PowerSlider, {
    value: local,
    onChange: setLocal
  }), /*#__PURE__*/React.createElement(BasculeTask, {
    local: local
  }), /*#__PURE__*/React.createElement(Card, null, /*#__PURE__*/React.createElement("div", {
    style: {
      fontSize: "12px",
      color: "var(--text-secondary)",
      lineHeight: 1.6
    }
  }, "La cascade : ", /*#__PURE__*/React.createElement("b", {
    style: {
      color: "var(--prov-local)"
    }
  }, "NPU \u2192 iGPU \u2192 Ollama/llama.cpp local"), " \u2192 ", /*#__PURE__*/React.createElement("b", {
    style: {
      color: "var(--prov-remote)"
    }
  }, "cloud"), " en dernier recours. Plus tu alloues de puissance, plus Nokido reste local tout en restant performant."))), /*#__PURE__*/React.createElement(Card, null, /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      alignItems: "center",
      gap: "8px",
      marginBottom: "12px"
    }
  }, /*#__PURE__*/React.createElement(Ico, {
    n: "receipt-text",
    s: 16
  }), /*#__PURE__*/React.createElement("span", {
    style: {
      fontWeight: 700,
      fontSize: "13px"
    }
  }, "Journal de provenance")), /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      flexDirection: "column",
      gap: "9px"
    }
  }, log.map((l, i) => /*#__PURE__*/React.createElement("div", {
    key: i,
    style: {
      display: "flex",
      alignItems: "center",
      gap: "8px",
      fontFamily: "var(--font-mono)",
      fontSize: "11px"
    }
  }, /*#__PURE__*/React.createElement("span", {
    style: {
      color: "var(--text-dim)"
    }
  }, l.ts), /*#__PURE__*/React.createElement("span", {
    style: {
      color: "var(--text-secondary)",
      minWidth: "52px"
    }
  }, l.act), /*#__PURE__*/React.createElement(ProvenanceBadge, {
    origin: l.prov,
    ring: l.ring,
    size: "sm",
    detail: l.model,
    style: {
      marginLeft: "auto"
    }
  }))))));
}

/* Bascule local ↔ distant sur une tâche réelle, pilotée par le curseur */
function BasculeTask({
  local
}) {
  const target = local >= 60 ? "local" : local >= 30 ? "hybrid" : "remote";
  const cfg = {
    local: {
      color: "var(--prov-local)",
      tint: "var(--prov-local-tint)",
      where: "Sur ta machine (Ollama)",
      lat: "0,6 s",
      conf: "Maximale",
      cost: "0 €"
    },
    hybrid: {
      color: "var(--prov-hybrid)",
      tint: "var(--prov-hybrid-tint)",
      where: "Local + cloud (anonymisé)",
      lat: "0,9 s",
      conf: "Élevée",
      cost: "~0,01 €"
    },
    remote: {
      color: "var(--prov-remote)",
      tint: "var(--prov-remote-tint)",
      where: "Cloud (Groq)",
      lat: "0,3 s",
      conf: "Réduite",
      cost: "~0,04 €"
    }
  }[target];
  const metric = (l, v) => /*#__PURE__*/React.createElement("div", null, /*#__PURE__*/React.createElement("div", {
    style: {
      fontSize: "10px",
      color: "var(--text-dim)",
      textTransform: "uppercase",
      letterSpacing: "0.4px"
    }
  }, l), /*#__PURE__*/React.createElement("div", {
    style: {
      fontFamily: "var(--font-mono)",
      fontSize: "12.5px",
      fontWeight: 700
    }
  }, v));
  return /*#__PURE__*/React.createElement(Card, {
    style: {
      borderColor: cfg.color
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      alignItems: "center",
      gap: "8px",
      marginBottom: "10px"
    }
  }, /*#__PURE__*/React.createElement(Ico, {
    n: "git-compare-arrows",
    s: 16
  }), /*#__PURE__*/React.createElement("span", {
    style: {
      fontWeight: 700,
      fontSize: "13px"
    }
  }, "Bascule en direct"), /*#__PURE__*/React.createElement(ProvenanceBadge, {
    origin: target,
    size: "sm",
    style: {
      marginLeft: "auto"
    }
  })), /*#__PURE__*/React.createElement("div", {
    style: {
      fontSize: "12.5px",
      color: "var(--text-secondary)",
      marginBottom: "12px"
    }
  }, "T\xE2che : ", /*#__PURE__*/React.createElement("b", {
    style: {
      color: "var(--text-primary)"
    }
  }, "\xAB Analyser mes d\xE9penses du mois \xBB")), /*#__PURE__*/React.createElement("div", {
    style: {
      padding: "10px 12px",
      borderRadius: "var(--radius-sm)",
      background: cfg.tint,
      marginBottom: "12px",
      display: "flex",
      alignItems: "center",
      gap: "8px",
      fontSize: "12px",
      color: cfg.color,
      fontWeight: 600
    }
  }, /*#__PURE__*/React.createElement(Ico, {
    n: target === "local" ? "house" : target === "hybrid" ? "git-fork" : "cloud",
    s: 15
  }), cfg.where), /*#__PURE__*/React.createElement("div", {
    style: {
      display: "grid",
      gridTemplateColumns: "repeat(3,1fr)",
      gap: "10px",
      marginBottom: "10px"
    }
  }, metric("Confidentialité", cfg.conf), metric("Latence", cfg.lat), metric("Coût", cfg.cost)), target !== "local" && /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      gap: "8px",
      fontSize: "11px",
      color: "var(--text-dim)",
      fontFamily: "var(--font-mono)",
      paddingTop: "10px",
      borderTop: "1px solid var(--border-subtle)"
    }
  }, /*#__PURE__*/React.createElement(Ico, {
    n: "shield-alert",
    s: 14
  }), "Cloud coup\xE9 \u2192 bascule locale annonc\xE9e, sans perte."));
}

/* ---------------- Fédération (Exposer son hub d'IA) ---------------- */
function ViewFederation() {
  const [exposed, setExposed] = React.useState(true);
  const [nodes, setNodes] = React.useState([{
    name: "Hub de Camille",
    scope: "Création · lecture",
    prov: "remote",
    ring: "verified",
    dir: "out"
  }, {
    name: "Nœud Atelier-3",
    scope: "Dev · skills partagés",
    prov: "hybrid",
    ring: "verified",
    dir: "in"
  }, {
    name: "Hub de Léo",
    scope: "Loisir · recommandations",
    prov: "remote",
    ring: "draft",
    dir: "out"
  }]);
  const revoke = i => setNodes(nodes.filter((_, j) => j !== i));
  return /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      flexDirection: "column",
      gap: "18px",
      maxWidth: "820px"
    }
  }, /*#__PURE__*/React.createElement(Card, {
    style: {
      background: "var(--bg-1)",
      borderColor: exposed ? "var(--prov-remote)" : "var(--border)"
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      alignItems: "center",
      gap: "12px"
    }
  }, /*#__PURE__*/React.createElement("span", {
    style: {
      display: "inline-flex",
      alignItems: "center",
      justifyContent: "center",
      width: "40px",
      height: "40px",
      borderRadius: "var(--radius-sm)",
      background: "var(--tint-purple)",
      color: "var(--purple)"
    }
  }, /*#__PURE__*/React.createElement(Ico, {
    n: "share-2",
    s: 20
  })), /*#__PURE__*/React.createElement("div", {
    style: {
      flex: 1
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      fontWeight: 700,
      fontSize: "15px"
    }
  }, "Exposer mon hub d'IA"), /*#__PURE__*/React.createElement("div", {
    style: {
      fontSize: "12px",
      color: "var(--text-dim)"
    }
  }, "F\xE9d\xE8re ton intelligence avec d'autres n\u0153uds. Tu restes souverain : rien ne sort sans r\xE8gle explicite.")), /*#__PURE__*/React.createElement("button", {
    onClick: () => setExposed(!exposed),
    "aria-label": "Exposer",
    style: {
      width: "46px",
      height: "26px",
      borderRadius: "var(--radius-pill)",
      border: "none",
      cursor: "pointer",
      background: exposed ? "var(--purple)" : "var(--bg-4)",
      position: "relative",
      flexShrink: 0,
      transition: "background var(--motion-fast)"
    }
  }, /*#__PURE__*/React.createElement("span", {
    style: {
      position: "absolute",
      top: "3px",
      left: exposed ? "23px" : "3px",
      width: "20px",
      height: "20px",
      borderRadius: "50%",
      background: "#fff",
      transition: "left var(--motion-fast)"
    }
  })))), /*#__PURE__*/React.createElement("div", {
    style: {
      display: "grid",
      gridTemplateColumns: "repeat(3,1fr)",
      gap: "12px"
    }
  }, [["eye-off", "Anonymisé", "Aucune intention brute ne sort"], ["scan-line", "Périmètre limité", "Tu choisis quoi partager"], ["undo-2", "Révocable", "Coupe un nœud à tout moment"]].map(([ic, t, d]) => /*#__PURE__*/React.createElement("div", {
    key: t,
    style: {
      padding: "13px 14px",
      background: "var(--bg-2)",
      border: "1px solid var(--border)",
      borderRadius: "var(--radius-md)"
    }
  }, /*#__PURE__*/React.createElement("span", {
    style: {
      color: "var(--prov-local)"
    }
  }, /*#__PURE__*/React.createElement(Ico, {
    n: ic,
    s: 17
  })), /*#__PURE__*/React.createElement("div", {
    style: {
      fontSize: "13px",
      fontWeight: 600,
      marginTop: "7px"
    }
  }, t), /*#__PURE__*/React.createElement("div", {
    style: {
      fontSize: "11px",
      color: "var(--text-dim)",
      lineHeight: 1.4
    }
  }, d)))), /*#__PURE__*/React.createElement("div", null, /*#__PURE__*/React.createElement(SectionTitle, {
    hint: `${nodes.length} connexions actives`
  }, "N\u0153uds f\xE9d\xE9r\xE9s"), /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      flexDirection: "column",
      gap: "8px",
      opacity: exposed ? 1 : 0.45,
      pointerEvents: exposed ? "auto" : "none"
    }
  }, nodes.map((n, i) => /*#__PURE__*/React.createElement("div", {
    key: i,
    style: {
      display: "flex",
      alignItems: "center",
      gap: "12px",
      padding: "12px 15px",
      background: "var(--bg-2)",
      border: "1px solid var(--border)",
      borderRadius: "var(--radius-md)"
    }
  }, /*#__PURE__*/React.createElement("span", {
    style: {
      display: "inline-flex",
      alignItems: "center",
      justifyContent: "center",
      width: "30px",
      height: "30px",
      borderRadius: "50%",
      background: "var(--bg-4)",
      color: "var(--text-secondary)",
      fontFamily: "var(--font-mono)",
      fontSize: "11px",
      fontWeight: 700
    }
  }, n.name.replace("Hub de ", "")[0]), /*#__PURE__*/React.createElement("div", {
    style: {
      flex: 1,
      minWidth: 0
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      fontSize: "13px",
      fontWeight: 600,
      display: "flex",
      alignItems: "center",
      gap: "7px"
    }
  }, n.name, /*#__PURE__*/React.createElement("span", {
    style: {
      fontFamily: "var(--font-mono)",
      fontSize: "9px",
      color: n.dir === "in" ? "var(--cyan)" : "var(--purple)",
      border: `1px solid ${n.dir === "in" ? "var(--cyan)" : "var(--purple)"}`,
      borderRadius: "3px",
      padding: "0 4px"
    }
  }, n.dir === "in" ? "↓ entrant" : "↑ sortant")), /*#__PURE__*/React.createElement("div", {
    style: {
      fontSize: "11px",
      color: "var(--text-dim)",
      fontFamily: "var(--font-mono)"
    }
  }, n.scope)), /*#__PURE__*/React.createElement(ProvenanceBadge, {
    origin: n.prov,
    ring: n.ring,
    size: "sm"
  }), /*#__PURE__*/React.createElement(Button, {
    variant: "ghost",
    size: "sm",
    icon: /*#__PURE__*/React.createElement(Ico, {
      n: "x",
      s: 13
    }),
    onClick: () => revoke(i)
  }, "R\xE9voquer"))), nodes.length === 0 && /*#__PURE__*/React.createElement("div", {
    style: {
      padding: "28px",
      textAlign: "center",
      color: "var(--text-dim)",
      fontSize: "13px"
    }
  }, "Aucun n\u0153ud f\xE9d\xE9r\xE9. Ton hub est enti\xE8rement priv\xE9."))));
}
Object.assign(window, {
  ViewAccueil,
  ViewCap,
  ViewMaison,
  ViewPersona,
  ViewSouverainete,
  ViewFederation
});
})(); } catch (e) { __ds_ns.__errors.push({ path: "design_handoff_nokido/ui_kits/hub/hub-views.ref.jsx", error: String((e && e.message) || e) }); }

// design_handoff_nokido/ui_kits/hub/mobile-hub.ref.jsx
try { (() => {
function _extends() { return _extends = Object.assign ? Object.assign.bind() : function (n) { for (var e = 1; e < arguments.length; e++) { var t = arguments[e]; for (var r in t) ({}).hasOwnProperty.call(t, r) && (n[r] = t[r]); } return n; }, _extends.apply(null, arguments); }
/* Nokido — Hub mobile (glance). Colonne unique, onglets bas. Réutilise le DS. */
const {
  Card,
  ModuleCard,
  SovereigntyGauge,
  ProvenanceBadge,
  PowerSlider,
  CapStep,
  Badge
} = window.NokidoDesignSystem_bdc2ac;
const PREF = window.NokidoPrefs; // util de persistance partagé

function MIco({
  n,
  s = 20
}) {
  return /*#__PURE__*/React.createElement("i", {
    "data-lucide": n,
    style: {
      width: s,
      height: s
    }
  });
}
const MODS = [{
  domain: "sante",
  title: "Santé",
  desc: "Local forcé — confidentialité max",
  icon: "heart-pulse",
  provenance: "local",
  pinned: true
}, {
  domain: "domotique",
  title: "Maison",
  desc: "Local-first absolu",
  icon: "house",
  provenance: "local",
  pinned: true
}, {
  domain: "transport",
  title: "Transport",
  desc: "Trajets, temps réel",
  icon: "route",
  provenance: "hybrid"
}, {
  domain: "creation",
  title: "Création",
  desc: "Atelier génératif",
  icon: "sparkles",
  provenance: "hybrid"
}];
function Logo({
  size = 26
}) {
  return /*#__PURE__*/React.createElement("svg", {
    width: size,
    height: size,
    viewBox: "0 0 64 64",
    fill: "none",
    style: {
      flexShrink: 0
    }
  }, /*#__PURE__*/React.createElement("defs", null, /*#__PURE__*/React.createElement("linearGradient", {
    id: "mbolt",
    x1: "26",
    y1: "12",
    x2: "40",
    y2: "40",
    gradientUnits: "userSpaceOnUse"
  }, /*#__PURE__*/React.createElement("stop", {
    offset: "0",
    stopColor: "#FFE070"
  }), /*#__PURE__*/React.createElement("stop", {
    offset: "1",
    stopColor: "#FFC22D"
  }))), /*#__PURE__*/React.createElement("g", {
    stroke: "#15121F",
    strokeWidth: "2.4",
    strokeLinejoin: "round"
  }, /*#__PURE__*/React.createElement("path", {
    d: "M6 35 L20 31 H48 q4 0 4 3.5 Q52 39 47 39 H39 q-3 0 -4 3 l-1.5 3 H27 q-1 -3 -4 -3 H15 Q6 42 6 35 Z",
    fill: "#9A90BC"
  }), /*#__PURE__*/React.createElement("path", {
    d: "M28 45 h8 l-1.5 5 h-5 Z",
    fill: "#6F6498"
  }), /*#__PURE__*/React.createElement("path", {
    d: "M17 50 H47 l3 6 H14 Z",
    fill: "#9A90BC"
  })), /*#__PURE__*/React.createElement("g", null, /*#__PURE__*/React.createElement("rect", {
    x: "4",
    y: "29",
    width: "23",
    height: "5",
    rx: "2.5",
    fill: "#C77D4A",
    stroke: "#15121F",
    strokeWidth: "2.4",
    strokeLinejoin: "round"
  }), /*#__PURE__*/React.createElement("rect", {
    x: "25",
    y: "21",
    width: "11",
    height: "21",
    rx: "3",
    fill: "#B7BCD2",
    stroke: "#15121F",
    strokeWidth: "2.4",
    strokeLinejoin: "round"
  }), /*#__PURE__*/React.createElement("rect", {
    x: "27.5",
    y: "24",
    width: "5.5",
    height: "6",
    rx: "1.5",
    fill: "#D9DCE8"
  })), /*#__PURE__*/React.createElement("path", {
    d: "M31 41 L40 26 H34 L42 11 L30 28 H36 Z",
    fill: "url(#mbolt)",
    stroke: "#15121F",
    strokeWidth: "2",
    strokeLinejoin: "round"
  }));
}
const TABS = [{
  id: "accueil",
  icon: "layout-grid",
  label: "Accueil"
}, {
  id: "cap",
  icon: "target",
  label: "Cap"
}, {
  id: "maison",
  icon: "house",
  label: "Maison"
}, {
  id: "souv",
  icon: "shield-check",
  label: "Souv."
}];
function MobileHub() {
  const [tab, setTab] = React.useState("accueil");
  const [power, setPower] = React.useState(() => PREF ? PREF.get("power", 68) : 68);
  React.useEffect(() => {
    if (PREF) PREF.set("power", power);
  }, [power]);
  React.useEffect(() => {
    if (window.lucide) lucide.createIcons();
  });
  return /*#__PURE__*/React.createElement("div", {
    style: {
      height: "100%",
      display: "flex",
      flexDirection: "column",
      background: "var(--bg-0)",
      color: "var(--text-primary)",
      paddingTop: "50px",
      boxSizing: "border-box"
    }
  }, /*#__PURE__*/React.createElement("header", {
    style: {
      display: "flex",
      alignItems: "center",
      gap: "9px",
      padding: "6px 18px 12px",
      borderBottom: "1px solid var(--border-subtle)"
    }
  }, /*#__PURE__*/React.createElement(Logo, null), /*#__PURE__*/React.createElement("span", {
    style: {
      fontWeight: 700,
      fontSize: "15px",
      letterSpacing: "0.3px"
    }
  }, "Nokido"), /*#__PURE__*/React.createElement(ProvenanceBadge, {
    origin: power >= 60 ? "local" : power >= 30 ? "hybrid" : "remote",
    detail: `${power}%`,
    size: "sm",
    style: {
      marginLeft: "auto"
    }
  }), /*#__PURE__*/React.createElement("a", {
    href: "../login/index.html",
    style: {
      color: "var(--text-dim)",
      display: "inline-flex"
    }
  }, /*#__PURE__*/React.createElement(MIco, {
    n: "lock",
    s: 17
  }))), /*#__PURE__*/React.createElement("div", {
    style: {
      flex: 1,
      overflowY: "auto",
      padding: "16px 18px 18px"
    }
  }, tab === "accueil" && /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      flexDirection: "column",
      gap: "14px"
    }
  }, /*#__PURE__*/React.createElement(Card, {
    style: {
      background: "var(--bg-1)"
    }
  }, /*#__PURE__*/React.createElement(SovereigntyGauge, {
    local: power
  })), /*#__PURE__*/React.createElement(Card, {
    style: {
      background: "var(--bg-1)"
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      alignItems: "center",
      gap: "7px",
      marginBottom: "8px"
    }
  }, /*#__PURE__*/React.createElement(MIco, {
    n: "target",
    s: 15
  }), /*#__PURE__*/React.createElement("span", {
    style: {
      fontWeight: 700,
      fontSize: "13px"
    }
  }, "Cap en cours"), /*#__PURE__*/React.createElement(Badge, {
    color: "purple",
    mono: true
  }, "jalon 4/9")), /*#__PURE__*/React.createElement("div", {
    style: {
      fontSize: "13.5px",
      lineHeight: 1.5
    }
  }, "Reprendre le contr\xF4le de mes donn\xE9es de sant\xE9 \xB7 maison 100 % local-first.")), /*#__PURE__*/React.createElement("div", {
    style: {
      fontFamily: "var(--font-mono)",
      fontSize: "10px",
      textTransform: "uppercase",
      letterSpacing: "0.6px",
      color: "var(--text-dim)",
      marginTop: "2px"
    }
  }, "Tes sections"), MODS.map(m => /*#__PURE__*/React.createElement(ModuleCard, _extends({
    key: m.domain
  }, m, {
    icon: /*#__PURE__*/React.createElement(MIco, {
      n: m.icon,
      s: 22
    })
  })))), tab === "cap" && /*#__PURE__*/React.createElement("div", null, /*#__PURE__*/React.createElement(Card, {
    style: {
      background: "var(--bg-1)",
      marginBottom: "14px"
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      fontSize: "10px",
      textTransform: "uppercase",
      letterSpacing: "0.6px",
      color: "var(--text-dim)",
      marginBottom: "5px"
    }
  }, "Horizon"), /*#__PURE__*/React.createElement("div", {
    style: {
      fontSize: "15px",
      fontWeight: 600,
      lineHeight: 1.4
    }
  }, "Maison 100 % local-first d'ici l'automne.")), /*#__PURE__*/React.createElement("div", null, /*#__PURE__*/React.createElement(CapStep, {
    index: 1,
    title: "Cartographier l'historique",
    state: "done",
    provenance: "local",
    ring: "gold"
  }), /*#__PURE__*/React.createElement(CapStep, {
    index: 2,
    title: "Reconstituer le cap",
    state: "done",
    provenance: "local",
    ring: "verified"
  }), /*#__PURE__*/React.createElement(CapStep, {
    index: 3,
    title: "D\xE9composer en 112 \xE9tapes",
    state: "active",
    provenance: "remote",
    ring: "verified"
  }), /*#__PURE__*/React.createElement(CapStep, {
    index: 4,
    title: "Migrer la domotique",
    state: "pending",
    ring: "draft",
    last: true
  }))), tab === "maison" && /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      flexDirection: "column",
      gap: "12px"
    }
  }, /*#__PURE__*/React.createElement(Card, {
    style: {
      background: "var(--bg-1)",
      borderColor: "var(--prov-local)"
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      alignItems: "center",
      gap: "8px"
    }
  }, /*#__PURE__*/React.createElement(MIco, {
    n: "shield-check",
    s: 16
  }), /*#__PURE__*/React.createElement("span", {
    style: {
      fontWeight: 600,
      fontSize: "13px"
    }
  }, "Maison vivante"), /*#__PURE__*/React.createElement(ProvenanceBadge, {
    origin: "local",
    size: "sm",
    style: {
      marginLeft: "auto"
    }
  }))), /*#__PURE__*/React.createElement("div", {
    style: {
      display: "grid",
      gridTemplateColumns: "1fr 1fr",
      gap: "10px"
    }
  }, [["sunrise", "Réveil", false], ["laptop", "Travail", true], ["clapperboard", "Cinéma", false], ["moon", "Nuit", false]].map(([ic, n, on]) => /*#__PURE__*/React.createElement("div", {
    key: n,
    style: {
      display: "flex",
      flexDirection: "column",
      alignItems: "center",
      gap: "7px",
      padding: "16px",
      borderRadius: "var(--radius-md)",
      background: on ? "var(--tint-green)" : "var(--bg-2)",
      border: `1px solid ${on ? "var(--prov-local)" : "var(--border)"}`,
      color: on ? "var(--prov-local)" : "var(--text-secondary)"
    }
  }, /*#__PURE__*/React.createElement(MIco, {
    n: ic,
    s: 22
  }), /*#__PURE__*/React.createElement("span", {
    style: {
      fontSize: "12.5px",
      fontWeight: 600
    }
  }, n))))), tab === "souv" && /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      flexDirection: "column",
      gap: "14px"
    }
  }, /*#__PURE__*/React.createElement(PowerSlider, {
    value: power,
    onChange: setPower
  }), /*#__PURE__*/React.createElement(Card, null, /*#__PURE__*/React.createElement("div", {
    style: {
      fontSize: "12px",
      color: "var(--text-secondary)",
      lineHeight: 1.6
    }
  }, /*#__PURE__*/React.createElement("b", {
    style: {
      color: "var(--prov-local)"
    }
  }, "NPU \u2192 iGPU \u2192 local"), " \u2192 ", /*#__PURE__*/React.createElement("b", {
    style: {
      color: "var(--prov-remote)"
    }
  }, "cloud"), " en dernier recours. Ta machine traite ", power, "% des requ\xEAtes.")))), /*#__PURE__*/React.createElement("nav", {
    style: {
      display: "flex",
      borderTop: "1px solid var(--border-subtle)",
      background: "var(--bg-1)",
      paddingBottom: "calc(8px + env(safe-area-inset-bottom))",
      paddingTop: "8px"
    }
  }, TABS.map(t => {
    const on = tab === t.id;
    return /*#__PURE__*/React.createElement("button", {
      key: t.id,
      onClick: () => setTab(t.id),
      style: {
        flex: 1,
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        gap: "3px",
        padding: "4px",
        minHeight: "48px",
        border: "none",
        background: "transparent",
        cursor: "pointer",
        color: on ? "var(--purple)" : "var(--text-dim)",
        fontFamily: "var(--font-sans)"
      }
    }, /*#__PURE__*/React.createElement(MIco, {
      n: t.icon,
      s: 20
    }), /*#__PURE__*/React.createElement("span", {
      style: {
        fontSize: "10px",
        fontWeight: on ? 700 : 500
      }
    }, t.label));
  })));
}
Object.assign(window, {
  MobileHub
});
})(); } catch (e) { __ds_ns.__errors.push({ path: "design_handoff_nokido/ui_kits/hub/mobile-hub.ref.jsx", error: String((e && e.message) || e) }); }

// design_handoff_nokido/ui_kits/login/login-screen.ref.jsx
try { (() => {
/* Nokido — Écran de verrouillage au démarrage : mot de passe + choix de langue.
   Coffre souverain : le déverrouillage est local. i18n FR/EN/ES/DE. */
const {
  Button,
  TextInput,
  ProvenanceBadge,
  Badge
} = window.NokidoDesignSystem_bdc2ac;
const I18N = {
  fr: {
    name: "Français",
    title: "Déverrouille ton hub",
    sub: "Coffre souverain — tout reste sur ta machine.",
    pwd: "Mot de passe",
    ph: "Ton mot de passe local",
    unlock: "Déverrouiller",
    forgot: "Phrase de récupération",
    offline: "Hors-ligne · le coffre ne quitte jamais l'appareil",
    err: "Mot de passe incorrect",
    lang: "Langue",
    bio: "Déverrouiller par biométrie"
  },
  en: {
    name: "English",
    title: "Unlock your hub",
    sub: "Sovereign vault — everything stays on your machine.",
    pwd: "Password",
    ph: "Your local password",
    unlock: "Unlock",
    forgot: "Recovery phrase",
    offline: "Offline · the vault never leaves the device",
    err: "Incorrect password",
    lang: "Language",
    bio: "Unlock with biometrics"
  },
  es: {
    name: "Español",
    title: "Desbloquea tu hub",
    sub: "Bóveda soberana — todo se queda en tu máquina.",
    pwd: "Contraseña",
    ph: "Tu contraseña local",
    unlock: "Desbloquear",
    forgot: "Frase de recuperación",
    offline: "Sin conexión · la bóveda nunca sale del dispositivo",
    err: "Contraseña incorrecta",
    lang: "Idioma",
    bio: "Desbloquear con biometría"
  },
  de: {
    name: "Deutsch",
    title: "Entsperre dein Hub",
    sub: "Souveräner Tresor — alles bleibt auf deinem Gerät.",
    pwd: "Passwort",
    ph: "Dein lokales Passwort",
    unlock: "Entsperren",
    forgot: "Wiederherstellungsphrase",
    offline: "Offline · der Tresor verlässt das Gerät nie",
    err: "Falsches Passwort",
    lang: "Sprache",
    bio: "Mit Biometrie entsperren"
  }
};
const LANGS = ["fr", "en", "es", "de"];
const FLAG = {
  fr: "FR",
  en: "EN",
  es: "ES",
  de: "DE"
};
function LIco({
  n,
  s = 16
}) {
  return /*#__PURE__*/React.createElement("i", {
    "data-lucide": n,
    style: {
      width: s,
      height: s
    }
  });
}
function LogoMark({
  size = 60,
  animated = true
}) {
  return /*#__PURE__*/React.createElement("svg", {
    className: "lf-logmark" + (animated ? " anim" : ""),
    width: size,
    height: size,
    viewBox: "0 0 64 64",
    fill: "none",
    style: {
      overflow: "visible"
    }
  }, /*#__PURE__*/React.createElement("defs", null, /*#__PURE__*/React.createElement("linearGradient", {
    id: "loginBolt",
    x1: "26",
    y1: "12",
    x2: "40",
    y2: "40",
    gradientUnits: "userSpaceOnUse"
  }, /*#__PURE__*/React.createElement("stop", {
    offset: "0",
    stopColor: "#FFE070"
  }), /*#__PURE__*/React.createElement("stop", {
    offset: "1",
    stopColor: "#FFC22D"
  }))), /*#__PURE__*/React.createElement("g", {
    className: "anvil",
    stroke: "#15121F",
    strokeWidth: "2.4",
    strokeLinejoin: "round"
  }, /*#__PURE__*/React.createElement("path", {
    d: "M6 35 L20 31 H48 q4 0 4 3.5 Q52 39 47 39 H39 q-3 0 -4 3 l-1.5 3 H27 q-1 -3 -4 -3 H15 Q6 42 6 35 Z",
    fill: "#9A90BC"
  }), /*#__PURE__*/React.createElement("path", {
    d: "M28 45 h8 l-1.5 5 h-5 Z",
    fill: "#6F6498"
  }), /*#__PURE__*/React.createElement("path", {
    d: "M17 50 H47 l3 6 H14 Z",
    fill: "#9A90BC"
  })), /*#__PURE__*/React.createElement("g", {
    className: "hammer"
  }, /*#__PURE__*/React.createElement("rect", {
    x: "4",
    y: "29",
    width: "23",
    height: "5",
    rx: "2.5",
    fill: "#C77D4A",
    stroke: "#15121F",
    strokeWidth: "2.4",
    strokeLinejoin: "round"
  }), /*#__PURE__*/React.createElement("rect", {
    x: "25",
    y: "21",
    width: "11",
    height: "21",
    rx: "3",
    fill: "#B7BCD2",
    stroke: "#15121F",
    strokeWidth: "2.4",
    strokeLinejoin: "round"
  }), /*#__PURE__*/React.createElement("rect", {
    x: "27.5",
    y: "24",
    width: "5.5",
    height: "6",
    rx: "1.5",
    fill: "#D9DCE8"
  })), /*#__PURE__*/React.createElement("path", {
    className: "bolt",
    d: "M31 41 L40 26 H34 L42 11 L30 28 H36 Z",
    fill: "url(#loginBolt)",
    stroke: "#15121F",
    strokeWidth: "2",
    strokeLinejoin: "round"
  }));
}
function LangSwitch({
  lang,
  setLang
}) {
  return /*#__PURE__*/React.createElement("div", {
    style: {
      display: "inline-flex",
      gap: "4px",
      padding: "4px",
      background: "var(--bg-2)",
      border: "1px solid var(--border)",
      borderRadius: "var(--radius-pill)"
    }
  }, LANGS.map(l => {
    const on = lang === l;
    return /*#__PURE__*/React.createElement("button", {
      key: l,
      onClick: () => setLang(l),
      title: I18N[l].name,
      "aria-pressed": on,
      style: {
        display: "inline-flex",
        alignItems: "center",
        justifyContent: "center",
        minWidth: "38px",
        height: "30px",
        padding: "0 10px",
        borderRadius: "var(--radius-pill)",
        border: "none",
        cursor: "pointer",
        fontFamily: "var(--font-mono)",
        fontSize: "11px",
        fontWeight: 700,
        letterSpacing: "0.3px",
        background: on ? "var(--purple)" : "transparent",
        color: on ? "#fff" : "var(--text-secondary)",
        transition: "all var(--motion-fast)"
      }
    }, FLAG[l]);
  }));
}
function LoginScreen({
  onUnlock
}) {
  const PREF = window.NokidoPrefs;
  const [lang, setLang] = React.useState(() => PREF ? PREF.get("lang", "fr") : "fr");
  const setLangP = l => {
    setLang(l);
    if (PREF) PREF.set("lang", l);
  };
  const [pwd, setPwd] = React.useState("");
  const [show, setShow] = React.useState(false);
  const [err, setErr] = React.useState(false);
  const t = I18N[lang];
  React.useEffect(() => {
    if (window.lucide) lucide.createIcons();
  });
  const submit = e => {
    e && e.preventDefault();
    if (pwd.trim().length < 3) {
      setErr(true);
      return;
    }
    setErr(false);
    onUnlock && onUnlock();
  };
  return /*#__PURE__*/React.createElement("div", {
    style: {
      minHeight: "100vh",
      display: "flex",
      flexDirection: "column",
      alignItems: "center",
      justifyContent: "center",
      padding: "24px",
      boxSizing: "border-box",
      position: "relative"
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      position: "absolute",
      top: "20px",
      right: "20px",
      display: "flex",
      alignItems: "center",
      gap: "8px"
    }
  }, /*#__PURE__*/React.createElement(LIco, {
    n: "languages",
    s: 15
  }), /*#__PURE__*/React.createElement(LangSwitch, {
    lang: lang,
    setLang: setLangP
  })), /*#__PURE__*/React.createElement("form", {
    onSubmit: submit,
    style: {
      width: "100%",
      maxWidth: "380px",
      background: "var(--bg-1)",
      border: "1px solid var(--border)",
      borderRadius: "var(--radius-lg)",
      padding: "30px 26px",
      boxShadow: "var(--shadow-lg)",
      display: "flex",
      flexDirection: "column",
      alignItems: "center",
      gap: "4px"
    }
  }, /*#__PURE__*/React.createElement(LogoMark, {
    size: 62
  }), /*#__PURE__*/React.createElement("div", {
    style: {
      display: "inline-flex",
      alignItems: "center",
      gap: "8px",
      marginTop: "8px"
    }
  }, /*#__PURE__*/React.createElement("span", {
    style: {
      fontFamily: "var(--font-sans)",
      fontWeight: 800,
      fontSize: "20px",
      letterSpacing: "0.3px",
      background: "linear-gradient(90deg, var(--text-primary), #B98BFF)",
      WebkitBackgroundClip: "text",
      backgroundClip: "text",
      color: "transparent"
    }
  }, "Nokido")), /*#__PURE__*/React.createElement("h1", {
    style: {
      margin: "10px 0 4px",
      fontSize: "20px",
      fontWeight: 700,
      textAlign: "center"
    }
  }, t.title), /*#__PURE__*/React.createElement("p", {
    style: {
      margin: "0 0 6px",
      fontSize: "12.5px",
      color: "var(--text-secondary)",
      textAlign: "center",
      lineHeight: 1.45
    }
  }, t.sub), /*#__PURE__*/React.createElement("div", {
    style: {
      margin: "8px 0 14px"
    }
  }, /*#__PURE__*/React.createElement(ProvenanceBadge, {
    origin: "local",
    label: t.offline,
    size: "sm"
  })), /*#__PURE__*/React.createElement("div", {
    style: {
      width: "100%",
      position: "relative"
    }
  }, /*#__PURE__*/React.createElement(TextInput, {
    label: t.pwd,
    type: show ? "text" : "password",
    placeholder: t.ph,
    value: pwd,
    onChange: e => {
      setPwd(e.target.value);
      setErr(false);
    },
    icon: /*#__PURE__*/React.createElement(LIco, {
      n: "lock",
      s: 15
    }),
    invalid: err,
    hint: err ? t.err : null
  }), /*#__PURE__*/React.createElement("button", {
    type: "button",
    onClick: () => setShow(s => !s),
    "aria-label": "show/hide",
    style: {
      position: "absolute",
      right: "10px",
      top: "30px",
      border: "none",
      background: "transparent",
      color: "var(--text-dim)",
      cursor: "pointer",
      display: "inline-flex",
      padding: "4px"
    }
  }, /*#__PURE__*/React.createElement(LIco, {
    n: show ? "eye-off" : "eye",
    s: 16
  }))), /*#__PURE__*/React.createElement(Button, {
    variant: "primary",
    size: "lg",
    type: "submit",
    style: {
      width: "100%",
      marginTop: "16px"
    },
    iconRight: /*#__PURE__*/React.createElement(LIco, {
      n: "arrow-right",
      s: 16
    })
  }, t.unlock), /*#__PURE__*/React.createElement("button", {
    type: "button",
    onClick: submit,
    style: {
      display: "inline-flex",
      alignItems: "center",
      gap: "8px",
      marginTop: "12px",
      border: "1px solid var(--border)",
      background: "transparent",
      color: "var(--text-secondary)",
      cursor: "pointer",
      padding: "8px 14px",
      borderRadius: "var(--radius-sm)",
      fontSize: "12.5px",
      fontFamily: "var(--font-sans)"
    }
  }, /*#__PURE__*/React.createElement(LIco, {
    n: "fingerprint",
    s: 16
  }), t.bio), /*#__PURE__*/React.createElement("a", {
    href: "#",
    onClick: e => e.preventDefault(),
    style: {
      fontSize: "11.5px",
      color: "var(--text-dim)",
      marginTop: "14px",
      fontFamily: "var(--font-mono)"
    }
  }, t.forgot)), /*#__PURE__*/React.createElement("div", {
    style: {
      marginTop: "18px",
      display: "flex",
      alignItems: "center",
      gap: "8px",
      fontFamily: "var(--font-mono)",
      fontSize: "10.5px",
      color: "var(--text-dim)"
    }
  }, /*#__PURE__*/React.createElement("span", {
    className: "laforge-pulse",
    style: {
      width: "6px",
      height: "6px",
      borderRadius: "50%",
      background: "var(--prov-local)"
    }
  }), "Ring 0 \xB7 n\u0153ud souverain \xB7 v18.3"), /*#__PURE__*/React.createElement("style", null, `
        .lf-logmark.anim .hammer { transform-box: view-box; transform-origin: 6px 31px; animation: lf-swing 1.3s cubic-bezier(.5,0,.4,1) infinite; }
        .lf-logmark.anim .bolt { transform-box: view-box; transform-origin: 31px 40px; opacity:0; animation: lf-flash 1.3s linear infinite; }
        .lf-logmark.anim .anvil { transform-box: view-box; transform-origin: 32px 54px; animation: lf-squash 1.3s linear infinite; }
        @keyframes lf-swing { 0%{transform:rotate(-38deg)} 29%{transform:rotate(2deg)} 38%{transform:rotate(-5deg)} 46%{transform:rotate(0deg)} 100%{transform:rotate(-38deg)} }
        @keyframes lf-flash { 0%,26%{opacity:0;transform:scale(.4)} 31%{opacity:1;transform:scale(1.1)} 43%{opacity:1;transform:scale(1)} 58%{opacity:0} 100%{opacity:0} }
        @keyframes lf-squash { 0%,26%{transform:scaleY(1)} 31%{transform:scaleY(.93) translateY(2px)} 43%{transform:scaleY(1.02)} 50%,100%{transform:scaleY(1)} }
        @media (prefers-reduced-motion: reduce){ .lf-logmark.anim .hammer{animation:none} .lf-logmark.anim .bolt{animation:none;opacity:1} .lf-logmark.anim .anvil{animation:none} }
      `));
}
Object.assign(window, {
  LoginScreen
});
})(); } catch (e) { __ds_ns.__errors.push({ path: "design_handoff_nokido/ui_kits/login/login-screen.ref.jsx", error: String((e && e.message) || e) }); }

// design_handoff_nokido/ui_kits/onboarding/ios-frame.jsx
try { (() => {
// @ds-adherence-ignore -- omelette starter scaffold (raw elements/hex/px by design)

/* BEGIN USAGE */
// iOS.jsx — Simplified iOS 26 (Liquid Glass) device frame
// Based on the iOS 26 UI Kit + Figma status bar spec. No assets, no deps.
// Exports (to window): IOSDevice, IOSStatusBar, IOSNavBar, IOSGlassPill, IOSList, IOSListRow, IOSKeyboard
//
// Usage — wrap your screen content in <IOSDevice> to get the bezel, status bar
// and home indicator (props: title, dark, keyboard):
//
//   <IOSDevice title="Settings">
//     ...your screen content...
//   </IOSDevice>
//   <IOSDevice dark title="Search" keyboard>…</IOSDevice>
/* END USAGE */

// ─────────────────────────────────────────────────────────────
// Status bar
// ─────────────────────────────────────────────────────────────
function IOSStatusBar({
  dark = false,
  time = '9:41'
}) {
  const c = dark ? '#fff' : '#000';
  return /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      gap: 154,
      alignItems: 'center',
      justifyContent: 'center',
      padding: '21px 24px 19px',
      boxSizing: 'border-box',
      position: 'relative',
      zIndex: 20,
      width: '100%'
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      flex: 1,
      height: 22,
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'center',
      paddingTop: 1.5
    }
  }, /*#__PURE__*/React.createElement("span", {
    style: {
      fontFamily: '-apple-system, "SF Pro", system-ui',
      fontWeight: 590,
      fontSize: 17,
      lineHeight: '22px',
      color: c
    }
  }, time)), /*#__PURE__*/React.createElement("div", {
    style: {
      flex: 1,
      height: 22,
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'center',
      gap: 7,
      paddingTop: 1,
      paddingRight: 1
    }
  }, /*#__PURE__*/React.createElement("svg", {
    width: "19",
    height: "12",
    viewBox: "0 0 19 12"
  }, /*#__PURE__*/React.createElement("rect", {
    x: "0",
    y: "7.5",
    width: "3.2",
    height: "4.5",
    rx: "0.7",
    fill: c
  }), /*#__PURE__*/React.createElement("rect", {
    x: "4.8",
    y: "5",
    width: "3.2",
    height: "7",
    rx: "0.7",
    fill: c
  }), /*#__PURE__*/React.createElement("rect", {
    x: "9.6",
    y: "2.5",
    width: "3.2",
    height: "9.5",
    rx: "0.7",
    fill: c
  }), /*#__PURE__*/React.createElement("rect", {
    x: "14.4",
    y: "0",
    width: "3.2",
    height: "12",
    rx: "0.7",
    fill: c
  })), /*#__PURE__*/React.createElement("svg", {
    width: "17",
    height: "12",
    viewBox: "0 0 17 12"
  }, /*#__PURE__*/React.createElement("path", {
    d: "M8.5 3.2C10.8 3.2 12.9 4.1 14.4 5.6L15.5 4.5C13.7 2.7 11.2 1.5 8.5 1.5C5.8 1.5 3.3 2.7 1.5 4.5L2.6 5.6C4.1 4.1 6.2 3.2 8.5 3.2Z",
    fill: c
  }), /*#__PURE__*/React.createElement("path", {
    d: "M8.5 6.8C9.9 6.8 11.1 7.3 12 8.2L13.1 7.1C11.8 5.9 10.2 5.1 8.5 5.1C6.8 5.1 5.2 5.9 3.9 7.1L5 8.2C5.9 7.3 7.1 6.8 8.5 6.8Z",
    fill: c
  }), /*#__PURE__*/React.createElement("circle", {
    cx: "8.5",
    cy: "10.5",
    r: "1.5",
    fill: c
  })), /*#__PURE__*/React.createElement("svg", {
    width: "27",
    height: "13",
    viewBox: "0 0 27 13"
  }, /*#__PURE__*/React.createElement("rect", {
    x: "0.5",
    y: "0.5",
    width: "23",
    height: "12",
    rx: "3.5",
    stroke: c,
    strokeOpacity: "0.35",
    fill: "none"
  }), /*#__PURE__*/React.createElement("rect", {
    x: "2",
    y: "2",
    width: "20",
    height: "9",
    rx: "2",
    fill: c
  }), /*#__PURE__*/React.createElement("path", {
    d: "M25 4.5V8.5C25.8 8.2 26.5 7.2 26.5 6.5C26.5 5.8 25.8 4.8 25 4.5Z",
    fill: c,
    fillOpacity: "0.4"
  }))));
}

// ─────────────────────────────────────────────────────────────
// Liquid glass pill — blur + tint + shine
// ─────────────────────────────────────────────────────────────
function IOSGlassPill({
  children,
  dark = false,
  style = {}
}) {
  return /*#__PURE__*/React.createElement("div", {
    style: {
      height: 44,
      minWidth: 44,
      borderRadius: 9999,
      position: 'relative',
      overflow: 'hidden',
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'center',
      boxShadow: dark ? '0 2px 6px rgba(0,0,0,0.35), 0 6px 16px rgba(0,0,0,0.2)' : '0 1px 3px rgba(0,0,0,0.07), 0 3px 10px rgba(0,0,0,0.06)',
      ...style
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      position: 'absolute',
      inset: 0,
      borderRadius: 9999,
      backdropFilter: 'blur(12px) saturate(180%)',
      WebkitBackdropFilter: 'blur(12px) saturate(180%)',
      background: dark ? 'rgba(120,120,128,0.28)' : 'rgba(255,255,255,0.5)'
    }
  }), /*#__PURE__*/React.createElement("div", {
    style: {
      position: 'absolute',
      inset: 0,
      borderRadius: 9999,
      boxShadow: dark ? 'inset 1.5px 1.5px 1px rgba(255,255,255,0.15), inset -1px -1px 1px rgba(255,255,255,0.08)' : 'inset 1.5px 1.5px 1px rgba(255,255,255,0.7), inset -1px -1px 1px rgba(255,255,255,0.4)',
      border: dark ? '0.5px solid rgba(255,255,255,0.15)' : '0.5px solid rgba(0,0,0,0.06)'
    }
  }), /*#__PURE__*/React.createElement("div", {
    style: {
      position: 'relative',
      zIndex: 1,
      display: 'flex',
      alignItems: 'center',
      padding: '0 4px'
    }
  }, children));
}

// ─────────────────────────────────────────────────────────────
// Navigation bar — glass pills + large title
// ─────────────────────────────────────────────────────────────
function IOSNavBar({
  title = 'Title',
  dark = false,
  trailingIcon = true
}) {
  const muted = dark ? 'rgba(255,255,255,0.6)' : '#404040';
  const text = dark ? '#fff' : '#000';
  const pillIcon = content => /*#__PURE__*/React.createElement(IOSGlassPill, {
    dark: dark
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      width: 36,
      height: 36,
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'center'
    }
  }, content));
  return /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      flexDirection: 'column',
      gap: 10,
      paddingTop: 62,
      paddingBottom: 10,
      position: 'relative',
      zIndex: 5
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'space-between',
      padding: '0 16px'
    }
  }, pillIcon(/*#__PURE__*/React.createElement("svg", {
    width: "12",
    height: "20",
    viewBox: "0 0 12 20",
    fill: "none",
    style: {
      marginLeft: -1
    }
  }, /*#__PURE__*/React.createElement("path", {
    d: "M10 2L2 10l8 8",
    stroke: muted,
    strokeWidth: "2.5",
    strokeLinecap: "round",
    strokeLinejoin: "round"
  }))), trailingIcon && pillIcon(/*#__PURE__*/React.createElement("svg", {
    width: "22",
    height: "6",
    viewBox: "0 0 22 6"
  }, /*#__PURE__*/React.createElement("circle", {
    cx: "3",
    cy: "3",
    r: "2.5",
    fill: muted
  }), /*#__PURE__*/React.createElement("circle", {
    cx: "11",
    cy: "3",
    r: "2.5",
    fill: muted
  }), /*#__PURE__*/React.createElement("circle", {
    cx: "19",
    cy: "3",
    r: "2.5",
    fill: muted
  })))), /*#__PURE__*/React.createElement("div", {
    style: {
      padding: '0 16px',
      fontFamily: '-apple-system, system-ui',
      fontSize: 34,
      fontWeight: 700,
      lineHeight: '41px',
      color: text,
      letterSpacing: 0.4
    }
  }, title));
}

// ─────────────────────────────────────────────────────────────
// Grouped list (inset card, r:26) + row (52px)
// ─────────────────────────────────────────────────────────────
function IOSListRow({
  title,
  detail,
  icon,
  chevron = true,
  isLast = false,
  dark = false
}) {
  const text = dark ? '#fff' : '#000';
  const sec = dark ? 'rgba(235,235,245,0.6)' : 'rgba(60,60,67,0.6)';
  const ter = dark ? 'rgba(235,235,245,0.3)' : 'rgba(60,60,67,0.3)';
  const sep = dark ? 'rgba(84,84,88,0.65)' : 'rgba(60,60,67,0.12)';
  return /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      alignItems: 'center',
      minHeight: 52,
      padding: '0 16px',
      position: 'relative',
      fontFamily: '-apple-system, system-ui',
      fontSize: 17,
      letterSpacing: -0.43
    }
  }, icon && /*#__PURE__*/React.createElement("div", {
    style: {
      width: 30,
      height: 30,
      borderRadius: 7,
      background: icon,
      marginRight: 12,
      flexShrink: 0
    }
  }), /*#__PURE__*/React.createElement("div", {
    style: {
      flex: 1,
      color: text
    }
  }, title), detail && /*#__PURE__*/React.createElement("span", {
    style: {
      color: sec,
      marginRight: 6
    }
  }, detail), chevron && /*#__PURE__*/React.createElement("svg", {
    width: "8",
    height: "14",
    viewBox: "0 0 8 14",
    style: {
      flexShrink: 0
    }
  }, /*#__PURE__*/React.createElement("path", {
    d: "M1 1l6 6-6 6",
    stroke: ter,
    strokeWidth: "2",
    fill: "none",
    strokeLinecap: "round",
    strokeLinejoin: "round"
  })), !isLast && /*#__PURE__*/React.createElement("div", {
    style: {
      position: 'absolute',
      bottom: 0,
      right: 0,
      left: icon ? 58 : 16,
      height: 0.5,
      background: sep
    }
  }));
}
function IOSList({
  header,
  children,
  dark = false
}) {
  const hc = dark ? 'rgba(235,235,245,0.6)' : 'rgba(60,60,67,0.6)';
  const bg = dark ? '#1C1C1E' : '#fff';
  return /*#__PURE__*/React.createElement("div", null, header && /*#__PURE__*/React.createElement("div", {
    style: {
      fontFamily: '-apple-system, system-ui',
      fontSize: 13,
      color: hc,
      textTransform: 'uppercase',
      padding: '8px 36px 6px',
      letterSpacing: -0.08
    }
  }, header), /*#__PURE__*/React.createElement("div", {
    style: {
      background: bg,
      borderRadius: 26,
      margin: '0 16px',
      overflow: 'hidden'
    }
  }, children));
}

// ─────────────────────────────────────────────────────────────
// Device frame
// ─────────────────────────────────────────────────────────────
function IOSDevice({
  children,
  width = 402,
  height = 874,
  dark = false,
  title,
  keyboard = false
}) {
  return /*#__PURE__*/React.createElement("div", {
    style: {
      width,
      height,
      borderRadius: 48,
      overflow: 'hidden',
      position: 'relative',
      background: dark ? '#000' : '#F2F2F7',
      boxShadow: '0 40px 80px rgba(0,0,0,0.18), 0 0 0 1px rgba(0,0,0,0.12)',
      fontFamily: '-apple-system, system-ui, sans-serif',
      WebkitFontSmoothing: 'antialiased'
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      position: 'absolute',
      top: 11,
      left: '50%',
      transform: 'translateX(-50%)',
      width: 126,
      height: 37,
      borderRadius: 24,
      background: '#000',
      zIndex: 50
    }
  }), /*#__PURE__*/React.createElement("div", {
    style: {
      position: 'absolute',
      top: 0,
      left: 0,
      right: 0,
      zIndex: 10
    }
  }, /*#__PURE__*/React.createElement(IOSStatusBar, {
    dark: dark
  })), /*#__PURE__*/React.createElement("div", {
    style: {
      height: '100%',
      display: 'flex',
      flexDirection: 'column'
    }
  }, title !== undefined && /*#__PURE__*/React.createElement(IOSNavBar, {
    title: title,
    dark: dark
  }), /*#__PURE__*/React.createElement("div", {
    style: {
      flex: 1,
      overflow: 'auto'
    }
  }, children), keyboard && /*#__PURE__*/React.createElement(IOSKeyboard, {
    dark: dark
  })), /*#__PURE__*/React.createElement("div", {
    style: {
      position: 'absolute',
      bottom: 0,
      left: 0,
      right: 0,
      zIndex: 60,
      height: 34,
      display: 'flex',
      justifyContent: 'center',
      alignItems: 'flex-end',
      paddingBottom: 8,
      pointerEvents: 'none'
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      width: 139,
      height: 5,
      borderRadius: 100,
      background: dark ? 'rgba(255,255,255,0.7)' : 'rgba(0,0,0,0.25)'
    }
  })));
}

// ─────────────────────────────────────────────────────────────
// Keyboard — iOS 26 liquid glass
// ─────────────────────────────────────────────────────────────
function IOSKeyboard({
  dark = false
}) {
  const glyph = dark ? 'rgba(255,255,255,0.7)' : '#595959';
  const sugg = dark ? 'rgba(255,255,255,0.6)' : '#333';
  const keyBg = dark ? 'rgba(255,255,255,0.22)' : 'rgba(255,255,255,0.85)';

  // special-key icons
  const icons = {
    shift: /*#__PURE__*/React.createElement("svg", {
      width: "19",
      height: "17",
      viewBox: "0 0 19 17"
    }, /*#__PURE__*/React.createElement("path", {
      d: "M9.5 1L1 9.5h4.5V16h8V9.5H18L9.5 1z",
      fill: glyph
    })),
    del: /*#__PURE__*/React.createElement("svg", {
      width: "23",
      height: "17",
      viewBox: "0 0 23 17"
    }, /*#__PURE__*/React.createElement("path", {
      d: "M7 1h13a2 2 0 012 2v11a2 2 0 01-2 2H7l-6-7.5L7 1z",
      fill: "none",
      stroke: glyph,
      strokeWidth: "1.6",
      strokeLinejoin: "round"
    }), /*#__PURE__*/React.createElement("path", {
      d: "M10 5l7 7M17 5l-7 7",
      stroke: glyph,
      strokeWidth: "1.6",
      strokeLinecap: "round"
    })),
    ret: /*#__PURE__*/React.createElement("svg", {
      width: "20",
      height: "14",
      viewBox: "0 0 20 14"
    }, /*#__PURE__*/React.createElement("path", {
      d: "M18 1v6H4m0 0l4-4M4 7l4 4",
      fill: "none",
      stroke: "#fff",
      strokeWidth: "1.8",
      strokeLinecap: "round",
      strokeLinejoin: "round"
    }))
  };
  const key = (content, {
    w,
    flex,
    ret,
    fs = 25,
    k
  } = {}) => /*#__PURE__*/React.createElement("div", {
    key: k,
    style: {
      height: 42,
      borderRadius: 8.5,
      flex: flex ? 1 : undefined,
      width: w,
      minWidth: 0,
      background: ret ? '#08f' : keyBg,
      boxShadow: '0 1px 0 rgba(0,0,0,0.075)',
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'center',
      fontFamily: '-apple-system, "SF Compact", system-ui',
      fontSize: fs,
      fontWeight: 458,
      color: ret ? '#fff' : glyph
    }
  }, content);
  const row = (keys, pad = 0) => /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      gap: 6.5,
      justifyContent: 'center',
      padding: `0 ${pad}px`
    }
  }, keys.map(l => key(l, {
    flex: true,
    k: l
  })));
  return /*#__PURE__*/React.createElement("div", {
    style: {
      position: 'relative',
      zIndex: 15,
      borderRadius: 27,
      overflow: 'hidden',
      padding: '11px 0 2px',
      display: 'flex',
      flexDirection: 'column',
      alignItems: 'center',
      boxShadow: dark ? '0 -2px 20px rgba(0,0,0,0.09)' : '0 -1px 6px rgba(0,0,0,0.018), 0 -3px 20px rgba(0,0,0,0.012)'
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      position: 'absolute',
      inset: 0,
      borderRadius: 27,
      backdropFilter: 'blur(12px) saturate(180%)',
      WebkitBackdropFilter: 'blur(12px) saturate(180%)',
      background: dark ? 'rgba(120,120,128,0.14)' : 'rgba(255,255,255,0.25)'
    }
  }), /*#__PURE__*/React.createElement("div", {
    style: {
      position: 'absolute',
      inset: 0,
      borderRadius: 27,
      boxShadow: dark ? 'inset 1.5px 1.5px 1px rgba(255,255,255,0.15)' : 'inset 1.5px 1.5px 1px rgba(255,255,255,0.7), inset -1px -1px 1px rgba(255,255,255,0.4)',
      border: dark ? '0.5px solid rgba(255,255,255,0.15)' : '0.5px solid rgba(0,0,0,0.06)',
      pointerEvents: 'none'
    }
  }), /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      gap: 20,
      alignItems: 'center',
      padding: '8px 22px 13px',
      width: '100%',
      boxSizing: 'border-box',
      position: 'relative'
    }
  }, ['"The"', 'the', 'to'].map((w, i) => /*#__PURE__*/React.createElement(React.Fragment, {
    key: i
  }, i > 0 && /*#__PURE__*/React.createElement("div", {
    style: {
      width: 1,
      height: 25,
      background: '#ccc',
      opacity: 0.3
    }
  }), /*#__PURE__*/React.createElement("div", {
    style: {
      flex: 1,
      textAlign: 'center',
      fontFamily: '-apple-system, system-ui',
      fontSize: 17,
      color: sugg,
      letterSpacing: -0.43,
      lineHeight: '22px'
    }
  }, w)))), /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      flexDirection: 'column',
      gap: 13,
      padding: '0 6.5px',
      width: '100%',
      boxSizing: 'border-box',
      position: 'relative'
    }
  }, row(['q', 'w', 'e', 'r', 't', 'y', 'u', 'i', 'o', 'p']), row(['a', 's', 'd', 'f', 'g', 'h', 'j', 'k', 'l'], 20), /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      gap: 14.25,
      alignItems: 'center'
    }
  }, key(icons.shift, {
    w: 45,
    k: 'shift'
  }), /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      gap: 6.5,
      flex: 1
    }
  }, ['z', 'x', 'c', 'v', 'b', 'n', 'm'].map(l => key(l, {
    flex: true,
    k: l
  }))), key(icons.del, {
    w: 45,
    k: 'del'
  })), /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      gap: 6,
      alignItems: 'center'
    }
  }, key('ABC', {
    w: 92.25,
    fs: 18,
    k: 'abc'
  }), key('', {
    flex: true,
    k: 'space'
  }), key(icons.ret, {
    w: 92.25,
    ret: true,
    k: 'ret'
  }))), /*#__PURE__*/React.createElement("div", {
    style: {
      height: 56,
      width: '100%',
      position: 'relative'
    }
  }));
}
Object.assign(window, {
  IOSDevice,
  IOSStatusBar,
  IOSNavBar,
  IOSGlassPill,
  IOSList,
  IOSListRow,
  IOSKeyboard
});
})(); } catch (e) { __ds_ns.__errors.push({ path: "design_handoff_nokido/ui_kits/onboarding/ios-frame.jsx", error: String((e && e.message) || e) }); }

// design_handoff_nokido/ui_kits/onboarding/onboarding-screens.ref.jsx
try { (() => {
/* Nokido — Onboarding souverain (mobile). Étapes : accueil → niveau local/cloud
   → allocation de puissance → activation des sections → récap. */
const {
  Button,
  PowerSlider,
  SovereigntyGauge,
  ProvenanceBadge,
  Badge
} = window.NokidoDesignSystem_bdc2ac;
function OIco({
  n,
  s = 20
}) {
  return /*#__PURE__*/React.createElement("i", {
    "data-lucide": n,
    style: {
      width: s,
      height: s
    }
  });
}
const STEP_COUNT = 5;
function Progress({
  step
}) {
  return /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      gap: "6px",
      padding: "0 4px"
    }
  }, Array.from({
    length: STEP_COUNT
  }).map((_, i) => /*#__PURE__*/React.createElement("div", {
    key: i,
    style: {
      flex: 1,
      height: "4px",
      borderRadius: "var(--radius-pill)",
      background: i <= step ? "var(--purple)" : "var(--bg-3)",
      transition: "background var(--motion-base)"
    }
  })));
}
function Screen({
  children,
  footer
}) {
  return /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      flexDirection: "column",
      height: "100%",
      background: "var(--bg-0)",
      color: "var(--text-primary)"
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      flex: 1,
      overflowY: "auto",
      padding: "8px 22px 16px"
    }
  }, children), /*#__PURE__*/React.createElement("div", {
    style: {
      padding: "12px 22px calc(12px + env(safe-area-inset-bottom))",
      borderTop: "1px solid var(--border-subtle)",
      background: "var(--bg-1)"
    }
  }, footer));
}
function Eyebrow({
  children
}) {
  return /*#__PURE__*/React.createElement("div", {
    style: {
      fontFamily: "var(--font-mono)",
      fontSize: "11px",
      letterSpacing: "0.5px",
      color: "var(--purple)",
      textTransform: "uppercase",
      marginBottom: "8px"
    }
  }, children);
}
function Title({
  children
}) {
  return /*#__PURE__*/React.createElement("h1", {
    style: {
      margin: "0 0 10px",
      fontSize: "26px",
      fontWeight: 700,
      lineHeight: 1.2,
      letterSpacing: "-0.01em"
    }
  }, children);
}
function Lede({
  children
}) {
  return /*#__PURE__*/React.createElement("p", {
    style: {
      margin: "0 0 18px",
      fontSize: "14px",
      color: "var(--text-secondary)",
      lineHeight: 1.55
    }
  }, children);
}

/* 0 — Accueil */
function S0({
  onNext
}) {
  return /*#__PURE__*/React.createElement(Screen, {
    footer: /*#__PURE__*/React.createElement(Button, {
      variant: "primary",
      size: "lg",
      style: {
        width: "100%"
      },
      onClick: onNext,
      iconRight: /*#__PURE__*/React.createElement(OIco, {
        n: "arrow-right",
        s: 16
      })
    }, "Commencer")
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      flexDirection: "column",
      alignItems: "center",
      textAlign: "center",
      paddingTop: "60px"
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      width: "78px",
      height: "78px",
      borderRadius: "22px",
      background: "var(--tint-purple)",
      display: "flex",
      alignItems: "center",
      justifyContent: "center",
      fontSize: "40px",
      color: "var(--purple)",
      boxShadow: "var(--shadow-glow)",
      marginBottom: "22px"
    }
  }, "\u26A1"), /*#__PURE__*/React.createElement(Title, null, "Bienvenue dans Nokido"), /*#__PURE__*/React.createElement(Lede, null, "Ton hub personnel d'IA et de services. ", /*#__PURE__*/React.createElement("b", {
    style: {
      color: "var(--prov-local)"
    }
  }, "Local d'abord"), " : ton intention reste sur ta machine, sauf autorisation explicite."), /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      flexDirection: "column",
      gap: "10px",
      width: "100%",
      marginTop: "8px"
    }
  }, [["shield-check", "Souverain", "Ton calcul, ta machine"], ["git-fork", "Fédéré", "Un nœud parmi 8 milliards"], ["sliders-horizontal", "Composable", "Ton app, tes règles"]].map(([ic, t, d]) => /*#__PURE__*/React.createElement("div", {
    key: t,
    style: {
      display: "flex",
      alignItems: "center",
      gap: "12px",
      padding: "12px 14px",
      background: "var(--bg-2)",
      border: "1px solid var(--border)",
      borderRadius: "var(--radius-md)",
      textAlign: "left"
    }
  }, /*#__PURE__*/React.createElement("span", {
    style: {
      display: "inline-flex",
      alignItems: "center",
      justifyContent: "center",
      width: "34px",
      height: "34px",
      borderRadius: "var(--radius-sm)",
      background: "var(--tint-purple)",
      color: "var(--purple)"
    }
  }, /*#__PURE__*/React.createElement(OIco, {
    n: ic,
    s: 17
  })), /*#__PURE__*/React.createElement("div", null, /*#__PURE__*/React.createElement("div", {
    style: {
      fontSize: "13px",
      fontWeight: 600
    }
  }, t), /*#__PURE__*/React.createElement("div", {
    style: {
      fontSize: "11.5px",
      color: "var(--text-dim)"
    }
  }, d)))))));
}

/* 1 — Niveau local / cloud */
function S1({
  onNext,
  onBack,
  level,
  setLevel
}) {
  const opts = [{
    id: "local",
    icon: "house",
    color: "var(--prov-local)",
    title: "Tout local",
    desc: "100 % sur ta machine. Hors-ligne possible. Confidentialité maximale.",
    tag: "SOUVERAIN"
  }, {
    id: "hybrid",
    icon: "git-fork",
    color: "var(--prov-hybrid)",
    title: "Hybride",
    desc: "Local par défaut, cloud en renfort pour les tâches lourdes — anonymisé.",
    tag: "RECOMMANDÉ"
  }, {
    id: "cloud",
    icon: "cloud",
    color: "var(--prov-remote)",
    title: "Cloud d'abord",
    desc: "Plus de puissance, plus de coût. Externe et réversible à tout moment.",
    tag: "DISTANT"
  }];
  return /*#__PURE__*/React.createElement(Screen, {
    footer: /*#__PURE__*/React.createElement("div", {
      style: {
        display: "flex",
        gap: "10px"
      }
    }, /*#__PURE__*/React.createElement(Button, {
      variant: "ghost",
      size: "lg",
      onClick: onBack,
      icon: /*#__PURE__*/React.createElement(OIco, {
        n: "arrow-left",
        s: 16
      })
    }, "Retour"), /*#__PURE__*/React.createElement(Button, {
      variant: "primary",
      size: "lg",
      style: {
        flex: 1
      },
      onClick: onNext
    }, "Continuer"))
  }, /*#__PURE__*/React.createElement(Eyebrow, null, "\xC9tape 1 \xB7 Souverainet\xE9"), /*#__PURE__*/React.createElement(Title, null, "O\xF9 vit ton calcul ?"), /*#__PURE__*/React.createElement(Lede, null, "Tu pourras l'ajuster \xE0 tout moment \u2014 c'est un curseur, pas un choix d\xE9finitif."), /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      flexDirection: "column",
      gap: "11px"
    }
  }, opts.map(o => {
    const on = level === o.id;
    return /*#__PURE__*/React.createElement("button", {
      key: o.id,
      onClick: () => setLevel(o.id),
      style: {
        display: "flex",
        gap: "13px",
        textAlign: "left",
        padding: "15px",
        cursor: "pointer",
        borderRadius: "var(--radius-md)",
        background: on ? "var(--bg-2)" : "var(--bg-1)",
        border: `1.5px solid ${on ? o.color : "var(--border)"}`,
        boxShadow: on ? `0 0 0 1px ${o.color}, 0 0 18px color-mix(in srgb, ${o.color} 18%, transparent)` : "none",
        fontFamily: "var(--font-sans)",
        color: "var(--text-primary)",
        transition: "all var(--motion-base)"
      }
    }, /*#__PURE__*/React.createElement("span", {
      style: {
        display: "inline-flex",
        alignItems: "center",
        justifyContent: "center",
        width: "42px",
        height: "42px",
        flexShrink: 0,
        borderRadius: "var(--radius-sm)",
        background: `color-mix(in srgb, ${o.color} 16%, transparent)`,
        color: o.color
      }
    }, /*#__PURE__*/React.createElement(OIco, {
      n: o.icon,
      s: 21
    })), /*#__PURE__*/React.createElement("div", {
      style: {
        flex: 1
      }
    }, /*#__PURE__*/React.createElement("div", {
      style: {
        display: "flex",
        alignItems: "center",
        gap: "8px"
      }
    }, /*#__PURE__*/React.createElement("span", {
      style: {
        fontSize: "15px",
        fontWeight: 700
      }
    }, o.title), /*#__PURE__*/React.createElement("span", {
      style: {
        fontFamily: "var(--font-mono)",
        fontSize: "9px",
        fontWeight: 700,
        letterSpacing: "0.3px",
        color: o.color,
        border: `1px solid ${o.color}`,
        borderRadius: "4px",
        padding: "1px 5px"
      }
    }, o.tag)), /*#__PURE__*/React.createElement("div", {
      style: {
        fontSize: "12px",
        color: "var(--text-secondary)",
        lineHeight: 1.45,
        marginTop: "4px"
      }
    }, o.desc)), /*#__PURE__*/React.createElement("span", {
      style: {
        alignSelf: "center",
        color: on ? o.color : "var(--text-disabled)"
      }
    }, /*#__PURE__*/React.createElement(OIco, {
      n: on ? "check-circle-2" : "circle",
      s: 20
    })));
  })));
}

/* 2 — Allocation de puissance */
function S2({
  onNext,
  onBack,
  power,
  setPower
}) {
  return /*#__PURE__*/React.createElement(Screen, {
    footer: /*#__PURE__*/React.createElement("div", {
      style: {
        display: "flex",
        gap: "10px"
      }
    }, /*#__PURE__*/React.createElement(Button, {
      variant: "ghost",
      size: "lg",
      onClick: onBack,
      icon: /*#__PURE__*/React.createElement(OIco, {
        n: "arrow-left",
        s: 16
      })
    }, "Retour"), /*#__PURE__*/React.createElement(Button, {
      variant: "primary",
      size: "lg",
      style: {
        flex: 1
      },
      onClick: onNext
    }, "Continuer"))
  }, /*#__PURE__*/React.createElement(Eyebrow, null, "\xC9tape 2 \xB7 Puissance"), /*#__PURE__*/React.createElement(Title, null, "Puissance allou\xE9e"), /*#__PURE__*/React.createElement(Lede, null, "Plus tu alloues de puissance locale, plus Nokido reste souverain tout en restant rapide. Le compromis se lit en direct."), /*#__PURE__*/React.createElement(PowerSlider, {
    value: power,
    onChange: setPower
  }), /*#__PURE__*/React.createElement("div", {
    style: {
      marginTop: "16px",
      padding: "13px 15px",
      background: "var(--prov-local-tint)",
      border: "1px solid var(--border-subtle)",
      borderRadius: "var(--radius-md)",
      display: "flex",
      gap: "10px"
    }
  }, /*#__PURE__*/React.createElement("span", {
    style: {
      color: "var(--prov-local)"
    }
  }, /*#__PURE__*/React.createElement(OIco, {
    n: "info",
    s: 17
  })), /*#__PURE__*/React.createElement("div", {
    style: {
      fontSize: "12px",
      color: "var(--text-secondary)",
      lineHeight: 1.5
    }
  }, "Cascade : ", /*#__PURE__*/React.createElement("b", {
    style: {
      color: "var(--prov-local)"
    }
  }, "NPU \u2192 iGPU \u2192 Ollama local"), " \u2192 cloud en dernier recours. Ta machine traite ", power, "% des requ\xEAtes.")));
}

/* 3 — Activer les sections */
function S3({
  onNext,
  onBack,
  enabled,
  toggle
}) {
  const mods = [{
    id: "sante",
    domain: "sante",
    icon: "heart-pulse",
    title: "Santé",
    note: "local forcé"
  }, {
    id: "domotique",
    domain: "domotique",
    icon: "house",
    title: "Domotique",
    note: "local-first"
  }, {
    id: "transport",
    domain: "transport",
    icon: "route",
    title: "Transport",
    note: "temps réel"
  }, {
    id: "finance",
    domain: "finance",
    icon: "wallet",
    title: "Finance",
    note: "traçable"
  }, {
    id: "creation",
    domain: "creation",
    icon: "sparkles",
    title: "Création",
    note: "atelier"
  }, {
    id: "dev",
    domain: "dev",
    icon: "terminal",
    title: "Dev",
    note: "skills & MCP"
  }];
  const count = mods.filter(m => enabled[m.id]).length;
  return /*#__PURE__*/React.createElement(Screen, {
    footer: /*#__PURE__*/React.createElement("div", {
      style: {
        display: "flex",
        gap: "10px"
      }
    }, /*#__PURE__*/React.createElement(Button, {
      variant: "ghost",
      size: "lg",
      onClick: onBack,
      icon: /*#__PURE__*/React.createElement(OIco, {
        n: "arrow-left",
        s: 16
      })
    }, "Retour"), /*#__PURE__*/React.createElement(Button, {
      variant: "primary",
      size: "lg",
      style: {
        flex: 1
      },
      onClick: onNext
    }, "Activer ", count, " section", count > 1 ? "s" : ""))
  }, /*#__PURE__*/React.createElement(Eyebrow, null, "\xC9tape 3 \xB7 Sections"), /*#__PURE__*/React.createElement(Title, null, "Compose ton app"), /*#__PURE__*/React.createElement(Lede, null, "Active tes premi\xE8res sections. Tu pourras en ajouter, r\xE9organiser ou masquer plus tard."), /*#__PURE__*/React.createElement("div", {
    style: {
      display: "grid",
      gridTemplateColumns: "1fr 1fr",
      gap: "10px"
    }
  }, mods.map(m => {
    const on = !!enabled[m.id];
    const accent = `var(--domain-${m.domain})`;
    return /*#__PURE__*/React.createElement("button", {
      key: m.id,
      onClick: () => toggle(m.id),
      style: {
        position: "relative",
        textAlign: "left",
        padding: "13px",
        cursor: "pointer",
        borderRadius: "var(--radius-md)",
        background: on ? "var(--bg-2)" : "var(--bg-1)",
        border: `1px solid ${on ? accent : "var(--border)"}`,
        fontFamily: "var(--font-sans)",
        color: "var(--text-primary)",
        overflow: "hidden",
        transition: "all var(--motion-base)"
      }
    }, /*#__PURE__*/React.createElement("div", {
      style: {
        position: "absolute",
        left: 0,
        top: 0,
        bottom: 0,
        width: "3px",
        background: on ? accent : "transparent"
      }
    }), /*#__PURE__*/React.createElement("div", {
      style: {
        display: "flex",
        alignItems: "center",
        justifyContent: "space-between"
      }
    }, /*#__PURE__*/React.createElement("span", {
      style: {
        display: "inline-flex",
        alignItems: "center",
        justifyContent: "center",
        width: "34px",
        height: "34px",
        borderRadius: "var(--radius-sm)",
        background: `color-mix(in srgb, ${accent} 16%, transparent)`,
        color: accent
      }
    }, /*#__PURE__*/React.createElement(OIco, {
      n: m.icon,
      s: 17
    })), /*#__PURE__*/React.createElement("span", {
      style: {
        color: on ? accent : "var(--text-disabled)"
      }
    }, /*#__PURE__*/React.createElement(OIco, {
      n: on ? "check-circle-2" : "circle",
      s: 18
    }))), /*#__PURE__*/React.createElement("div", {
      style: {
        fontSize: "13.5px",
        fontWeight: 700,
        marginTop: "9px"
      }
    }, m.title), /*#__PURE__*/React.createElement("div", {
      style: {
        fontFamily: "var(--font-mono)",
        fontSize: "10px",
        color: "var(--text-dim)"
      }
    }, m.note));
  })));
}

/* 4 — Récap */
function S4({
  onBack,
  onDone,
  level,
  power,
  enabled
}) {
  const labels = {
    local: "Tout local",
    hybrid: "Hybride",
    cloud: "Cloud d'abord"
  };
  const origin = level === "cloud" ? "remote" : level === "hybrid" ? "hybrid" : "local";
  const count = Object.values(enabled).filter(Boolean).length;
  return /*#__PURE__*/React.createElement(Screen, {
    footer: /*#__PURE__*/React.createElement("div", {
      style: {
        display: "flex",
        gap: "10px"
      }
    }, /*#__PURE__*/React.createElement(Button, {
      variant: "ghost",
      size: "lg",
      onClick: onBack,
      icon: /*#__PURE__*/React.createElement(OIco, {
        n: "arrow-left",
        s: 16
      })
    }, "Retour"), /*#__PURE__*/React.createElement(Button, {
      variant: "success",
      size: "lg",
      style: {
        flex: 1
      },
      onClick: onDone,
      iconRight: /*#__PURE__*/React.createElement(OIco, {
        n: "arrow-right",
        s: 16
      })
    }, "Entrer dans le hub"))
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      flexDirection: "column",
      alignItems: "center",
      textAlign: "center",
      paddingTop: "20px"
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      width: "64px",
      height: "64px",
      borderRadius: "50%",
      background: "var(--tint-green)",
      color: "var(--prov-local)",
      display: "flex",
      alignItems: "center",
      justifyContent: "center",
      marginBottom: "16px",
      boxShadow: "var(--prov-local-glow)"
    }
  }, /*#__PURE__*/React.createElement(OIco, {
    n: "check",
    s: 30
  })), /*#__PURE__*/React.createElement(Title, null, "Ton n\u0153ud est pr\xEAt"), /*#__PURE__*/React.createElement(Lede, null, "Voici ta configuration souveraine. Tout reste modifiable \xE0 tout moment.")), /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      flexDirection: "column",
      gap: "10px"
    }
  }, /*#__PURE__*/React.createElement(Row, {
    label: "Niveau",
    value: labels[level],
    right: /*#__PURE__*/React.createElement(ProvenanceBadge, {
      origin: origin,
      size: "sm"
    })
  }), /*#__PURE__*/React.createElement(Row, {
    label: "Puissance locale",
    value: `${power}%`,
    right: /*#__PURE__*/React.createElement(SovereigntyGauge, {
      local: power,
      label: null,
      showLegend: false,
      height: 6,
      style: {
        width: "90px"
      }
    })
  }), /*#__PURE__*/React.createElement(Row, {
    label: "Sections actives",
    value: `${count} activée${count > 1 ? "s" : ""}`,
    right: /*#__PURE__*/React.createElement(Badge, {
      color: "purple",
      mono: true
    }, count)
  })));
}
function Row({
  label,
  value,
  right
}) {
  return /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      alignItems: "center",
      gap: "12px",
      padding: "13px 15px",
      background: "var(--bg-2)",
      border: "1px solid var(--border)",
      borderRadius: "var(--radius-md)"
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      flex: 1
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      fontFamily: "var(--font-mono)",
      fontSize: "10px",
      textTransform: "uppercase",
      letterSpacing: "0.5px",
      color: "var(--text-dim)"
    }
  }, label), /*#__PURE__*/React.createElement("div", {
    style: {
      fontSize: "14px",
      fontWeight: 600,
      marginTop: "2px"
    }
  }, value)), right);
}
Object.assign(window, {
  OnbProgress: Progress,
  OnbS0: S0,
  OnbS1: S1,
  OnbS2: S2,
  OnbS3: S3,
  OnbS4: S4
});
})(); } catch (e) { __ds_ns.__errors.push({ path: "design_handoff_nokido/ui_kits/onboarding/onboarding-screens.ref.jsx", error: String((e && e.message) || e) }); }

// design_handoff_nokido/ui_kits/webhub/tweaks-panel.jsx
try { (() => {
// @ds-adherence-ignore -- omelette starter scaffold (raw elements/hex/px by design)

/* BEGIN USAGE */
// tweaks-panel.jsx
// Reusable Tweaks shell + form-control helpers.
// Exports (to window): useTweaks, TweaksPanel, TweakSection, TweakRow, TweakSlider,
//   TweakToggle, TweakRadio, TweakSelect, TweakText, TweakNumber, TweakColor, TweakButton.
//
// Owns the host protocol (listens for __activate_edit_mode / __deactivate_edit_mode,
// posts __edit_mode_available / __edit_mode_set_keys / __edit_mode_dismissed) so
// individual prototypes don't re-roll it. Ships a consistent set of controls so you
// don't hand-draw <input type="range">, segmented radios, steppers, etc.
//
// Usage (in an HTML file that loads React + Babel):
//
//   const TWEAK_DEFAULTS = /*EDITMODE-BEGIN*/{
//     "primaryColor": "#D97757",
//     "palette": ["#D97757", "#29261b", "#f6f4ef"],
//     "fontSize": 16,
//     "density": "regular",
//     "dark": false
//   }/*EDITMODE-END*/;
//
//   function App() {
//     const [t, setTweak] = useTweaks(TWEAK_DEFAULTS);
//     return (
//       <div style={{ fontSize: t.fontSize, color: t.primaryColor }}>
//         Hello
//         <TweaksPanel>
//           <TweakSection label="Typography" />
//           <TweakSlider label="Font size" value={t.fontSize} min={10} max={32} unit="px"
//                        onChange={(v) => setTweak('fontSize', v)} />
//           <TweakRadio  label="Density" value={t.density}
//                        options={['compact', 'regular', 'comfy']}
//                        onChange={(v) => setTweak('density', v)} />
//           <TweakSection label="Theme" />
//           <TweakColor  label="Primary" value={t.primaryColor}
//                        options={['#D97757', '#2A6FDB', '#1F8A5B', '#7A5AE0']}
//                        onChange={(v) => setTweak('primaryColor', v)} />
//           <TweakColor  label="Palette" value={t.palette}
//                        options={[['#D97757', '#29261b', '#f6f4ef'],
//                                  ['#475569', '#0f172a', '#f1f5f9']]}
//                        onChange={(v) => setTweak('palette', v)} />
//           <TweakToggle label="Dark mode" value={t.dark}
//                        onChange={(v) => setTweak('dark', v)} />
//         </TweaksPanel>
//       </div>
//     );
//   }
//
// TweakRadio is the segmented control for 2–3 short options (auto-falls-back to
// TweakSelect past ~16/~10 chars per label); reach for TweakSelect directly when
// options are many or long. For color tweaks always curate 3-4 options rather than
// a free picker; an option can also be a whole 2–5 color palette (the stored value
// is the array). The Tweak* controls are a floor, not a ceiling — build custom
// controls inside the panel if a tweak calls for UI they don't cover.
/* END USAGE */
// ─────────────────────────────────────────────────────────────────────────────

const __TWEAKS_STYLE = `
  .twk-panel{position:fixed;right:16px;bottom:16px;z-index:2147483646;width:280px;
    max-height:calc(100vh - 32px);display:flex;flex-direction:column;
    transform:scale(var(--dc-inv-zoom,1));transform-origin:bottom right;
    background:rgba(250,249,247,.78);color:#29261b;
    -webkit-backdrop-filter:blur(24px) saturate(160%);backdrop-filter:blur(24px) saturate(160%);
    border:.5px solid rgba(255,255,255,.6);border-radius:14px;
    box-shadow:0 1px 0 rgba(255,255,255,.5) inset,0 12px 40px rgba(0,0,0,.18);
    font:11.5px/1.4 ui-sans-serif,system-ui,-apple-system,sans-serif;overflow:hidden}
  .twk-hd{display:flex;align-items:center;justify-content:space-between;
    padding:10px 8px 10px 14px;cursor:move;user-select:none}
  .twk-hd b{font-size:12px;font-weight:600;letter-spacing:.01em}
  .twk-x{appearance:none;border:0;background:transparent;color:rgba(41,38,27,.55);
    width:22px;height:22px;border-radius:6px;cursor:default;font-size:13px;line-height:1}
  .twk-x:hover{background:rgba(0,0,0,.06);color:#29261b}
  .twk-body{padding:2px 14px 14px;display:flex;flex-direction:column;gap:10px;
    overflow-y:auto;overflow-x:hidden;min-height:0;
    scrollbar-width:thin;scrollbar-color:rgba(0,0,0,.15) transparent}
  .twk-body::-webkit-scrollbar{width:8px}
  .twk-body::-webkit-scrollbar-track{background:transparent;margin:2px}
  .twk-body::-webkit-scrollbar-thumb{background:rgba(0,0,0,.15);border-radius:4px;
    border:2px solid transparent;background-clip:content-box}
  .twk-body::-webkit-scrollbar-thumb:hover{background:rgba(0,0,0,.25);
    border:2px solid transparent;background-clip:content-box}
  .twk-row{display:flex;flex-direction:column;gap:5px}
  .twk-row-h{flex-direction:row;align-items:center;justify-content:space-between;gap:10px}
  .twk-lbl{display:flex;justify-content:space-between;align-items:baseline;
    color:rgba(41,38,27,.72)}
  .twk-lbl>span:first-child{font-weight:500}
  .twk-val{color:rgba(41,38,27,.5);font-variant-numeric:tabular-nums}

  .twk-sect{font-size:10px;font-weight:600;letter-spacing:.06em;text-transform:uppercase;
    color:rgba(41,38,27,.45);padding:10px 0 0}
  .twk-sect:first-child{padding-top:0}

  .twk-field{appearance:none;box-sizing:border-box;width:100%;min-width:0;height:26px;padding:0 8px;
    border:.5px solid rgba(0,0,0,.1);border-radius:7px;
    background:rgba(255,255,255,.6);color:inherit;font:inherit;outline:none}
  .twk-field:focus{border-color:rgba(0,0,0,.25);background:rgba(255,255,255,.85)}
  select.twk-field{padding-right:22px;
    background-image:url("data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' width='10' height='6' viewBox='0 0 10 6'><path fill='rgba(0,0,0,.5)' d='M0 0h10L5 6z'/></svg>");
    background-repeat:no-repeat;background-position:right 8px center}

  .twk-slider{appearance:none;-webkit-appearance:none;width:100%;height:4px;margin:6px 0;
    border-radius:999px;background:rgba(0,0,0,.12);outline:none}
  .twk-slider::-webkit-slider-thumb{-webkit-appearance:none;appearance:none;
    width:14px;height:14px;border-radius:50%;background:#fff;
    border:.5px solid rgba(0,0,0,.12);box-shadow:0 1px 3px rgba(0,0,0,.2);cursor:default}
  .twk-slider::-moz-range-thumb{width:14px;height:14px;border-radius:50%;
    background:#fff;border:.5px solid rgba(0,0,0,.12);box-shadow:0 1px 3px rgba(0,0,0,.2);cursor:default}

  .twk-seg{position:relative;display:flex;padding:2px;border-radius:8px;
    background:rgba(0,0,0,.06);user-select:none}
  .twk-seg-thumb{position:absolute;top:2px;bottom:2px;border-radius:6px;
    background:rgba(255,255,255,.9);box-shadow:0 1px 2px rgba(0,0,0,.12);
    transition:left .15s cubic-bezier(.3,.7,.4,1),width .15s}
  .twk-seg.dragging .twk-seg-thumb{transition:none}
  .twk-seg button{appearance:none;position:relative;z-index:1;flex:1;border:0;
    background:transparent;color:inherit;font:inherit;font-weight:500;min-height:22px;
    border-radius:6px;cursor:default;padding:4px 6px;line-height:1.2;
    overflow-wrap:anywhere}

  .twk-toggle{position:relative;width:32px;height:18px;border:0;border-radius:999px;
    background:rgba(0,0,0,.15);transition:background .15s;cursor:default;padding:0}
  .twk-toggle[data-on="1"]{background:#34c759}
  .twk-toggle i{position:absolute;top:2px;left:2px;width:14px;height:14px;border-radius:50%;
    background:#fff;box-shadow:0 1px 2px rgba(0,0,0,.25);transition:transform .15s}
  .twk-toggle[data-on="1"] i{transform:translateX(14px)}

  .twk-num{display:flex;align-items:center;box-sizing:border-box;min-width:0;height:26px;padding:0 0 0 8px;
    border:.5px solid rgba(0,0,0,.1);border-radius:7px;background:rgba(255,255,255,.6)}
  .twk-num-lbl{font-weight:500;color:rgba(41,38,27,.6);cursor:ew-resize;
    user-select:none;padding-right:8px}
  .twk-num input{flex:1;min-width:0;height:100%;border:0;background:transparent;
    font:inherit;font-variant-numeric:tabular-nums;text-align:right;padding:0 8px 0 0;
    outline:none;color:inherit;-moz-appearance:textfield}
  .twk-num input::-webkit-inner-spin-button,.twk-num input::-webkit-outer-spin-button{
    -webkit-appearance:none;margin:0}
  .twk-num-unit{padding-right:8px;color:rgba(41,38,27,.45)}

  .twk-btn{appearance:none;height:26px;padding:0 12px;border:0;border-radius:7px;
    background:rgba(0,0,0,.78);color:#fff;font:inherit;font-weight:500;cursor:default}
  .twk-btn:hover{background:rgba(0,0,0,.88)}
  .twk-btn.secondary{background:rgba(0,0,0,.06);color:inherit}
  .twk-btn.secondary:hover{background:rgba(0,0,0,.1)}

  .twk-swatch{appearance:none;-webkit-appearance:none;width:56px;height:22px;
    border:.5px solid rgba(0,0,0,.1);border-radius:6px;padding:0;cursor:default;
    background:transparent;flex-shrink:0}
  .twk-swatch::-webkit-color-swatch-wrapper{padding:0}
  .twk-swatch::-webkit-color-swatch{border:0;border-radius:5.5px}
  .twk-swatch::-moz-color-swatch{border:0;border-radius:5.5px}

  .twk-chips{display:flex;gap:6px}
  .twk-chip{position:relative;appearance:none;flex:1;min-width:0;height:46px;
    padding:0;border:0;border-radius:6px;overflow:hidden;cursor:default;
    box-shadow:0 0 0 .5px rgba(0,0,0,.12),0 1px 2px rgba(0,0,0,.06);
    transition:transform .12s cubic-bezier(.3,.7,.4,1),box-shadow .12s}
  .twk-chip:hover{transform:translateY(-1px);
    box-shadow:0 0 0 .5px rgba(0,0,0,.18),0 4px 10px rgba(0,0,0,.12)}
  .twk-chip[data-on="1"]{box-shadow:0 0 0 1.5px rgba(0,0,0,.85),
    0 2px 6px rgba(0,0,0,.15)}
  .twk-chip>span{position:absolute;top:0;bottom:0;right:0;width:34%;
    display:flex;flex-direction:column;box-shadow:-1px 0 0 rgba(0,0,0,.1)}
  .twk-chip>span>i{flex:1;box-shadow:0 -1px 0 rgba(0,0,0,.1)}
  .twk-chip>span>i:first-child{box-shadow:none}
  .twk-chip svg{position:absolute;top:6px;left:6px;width:13px;height:13px;
    filter:drop-shadow(0 1px 1px rgba(0,0,0,.3))}
`;

// ── useTweaks ───────────────────────────────────────────────────────────────
// Single source of truth for tweak values. setTweak persists via the host
// (__edit_mode_set_keys → host rewrites the EDITMODE block on disk).
function useTweaks(defaults) {
  const [values, setValues] = React.useState(defaults);
  // Accepts either setTweak('key', value) or setTweak({ key: value, ... }) so a
  // useState-style call doesn't write a "[object Object]" key into the persisted
  // JSON block.
  const setTweak = React.useCallback((keyOrEdits, val) => {
    const edits = typeof keyOrEdits === 'object' && keyOrEdits !== null ? keyOrEdits : {
      [keyOrEdits]: val
    };
    setValues(prev => ({
      ...prev,
      ...edits
    }));
    window.parent.postMessage({
      type: '__edit_mode_set_keys',
      edits
    }, '*');
    // Same-window signal so in-page listeners (deck-stage rail thumbnails)
    // can react — the parent message only reaches the host, not peers.
    window.dispatchEvent(new CustomEvent('tweakchange', {
      detail: edits
    }));
  }, []);
  return [values, setTweak];
}

// ── TweaksPanel ─────────────────────────────────────────────────────────────
// Floating shell. Registers the protocol listener BEFORE announcing
// availability — if the announce ran first, the host's activate could land
// before our handler exists and the toolbar toggle would silently no-op.
// The close button posts __edit_mode_dismissed so the host's toolbar toggle
// flips off in lockstep; the host echoes __deactivate_edit_mode back which
// is what actually hides the panel.
function TweaksPanel({
  title = 'Tweaks',
  children
}) {
  const [open, setOpen] = React.useState(false);
  const dragRef = React.useRef(null);
  const offsetRef = React.useRef({
    x: 16,
    y: 16
  });
  const PAD = 16;
  const clampToViewport = React.useCallback(() => {
    const panel = dragRef.current;
    if (!panel) return;
    const w = panel.offsetWidth,
      h = panel.offsetHeight;
    const maxRight = Math.max(PAD, window.innerWidth - w - PAD);
    const maxBottom = Math.max(PAD, window.innerHeight - h - PAD);
    offsetRef.current = {
      x: Math.min(maxRight, Math.max(PAD, offsetRef.current.x)),
      y: Math.min(maxBottom, Math.max(PAD, offsetRef.current.y))
    };
    panel.style.right = offsetRef.current.x + 'px';
    panel.style.bottom = offsetRef.current.y + 'px';
  }, []);
  React.useEffect(() => {
    if (!open) return;
    clampToViewport();
    if (typeof ResizeObserver === 'undefined') {
      window.addEventListener('resize', clampToViewport);
      return () => window.removeEventListener('resize', clampToViewport);
    }
    const ro = new ResizeObserver(clampToViewport);
    ro.observe(document.documentElement);
    return () => ro.disconnect();
  }, [open, clampToViewport]);
  React.useEffect(() => {
    const onMsg = e => {
      const t = e?.data?.type;
      if (t === '__activate_edit_mode') setOpen(true);else if (t === '__deactivate_edit_mode') setOpen(false);
    };
    window.addEventListener('message', onMsg);
    window.parent.postMessage({
      type: '__edit_mode_available'
    }, '*');
    return () => window.removeEventListener('message', onMsg);
  }, []);
  const dismiss = () => {
    setOpen(false);
    window.parent.postMessage({
      type: '__edit_mode_dismissed'
    }, '*');
  };
  const onDragStart = e => {
    const panel = dragRef.current;
    if (!panel) return;
    const r = panel.getBoundingClientRect();
    const sx = e.clientX,
      sy = e.clientY;
    const startRight = window.innerWidth - r.right;
    const startBottom = window.innerHeight - r.bottom;
    const move = ev => {
      offsetRef.current = {
        x: startRight - (ev.clientX - sx),
        y: startBottom - (ev.clientY - sy)
      };
      clampToViewport();
    };
    const up = () => {
      window.removeEventListener('mousemove', move);
      window.removeEventListener('mouseup', up);
    };
    window.addEventListener('mousemove', move);
    window.addEventListener('mouseup', up);
  };
  if (!open) return null;
  return /*#__PURE__*/React.createElement(React.Fragment, null, /*#__PURE__*/React.createElement("style", null, __TWEAKS_STYLE), /*#__PURE__*/React.createElement("div", {
    ref: dragRef,
    className: "twk-panel",
    "data-omelette-chrome": "",
    style: {
      right: offsetRef.current.x,
      bottom: offsetRef.current.y
    }
  }, /*#__PURE__*/React.createElement("div", {
    className: "twk-hd",
    onMouseDown: onDragStart
  }, /*#__PURE__*/React.createElement("b", null, title), /*#__PURE__*/React.createElement("button", {
    className: "twk-x",
    "aria-label": "Close tweaks",
    onMouseDown: e => e.stopPropagation(),
    onClick: dismiss
  }, "\u2715")), /*#__PURE__*/React.createElement("div", {
    className: "twk-body"
  }, children)));
}

// ── Layout helpers ──────────────────────────────────────────────────────────

function TweakSection({
  label,
  children
}) {
  return /*#__PURE__*/React.createElement(React.Fragment, null, /*#__PURE__*/React.createElement("div", {
    className: "twk-sect"
  }, label), children);
}
function TweakRow({
  label,
  value,
  children,
  inline = false
}) {
  return /*#__PURE__*/React.createElement("div", {
    className: inline ? 'twk-row twk-row-h' : 'twk-row'
  }, /*#__PURE__*/React.createElement("div", {
    className: "twk-lbl"
  }, /*#__PURE__*/React.createElement("span", null, label), value != null && /*#__PURE__*/React.createElement("span", {
    className: "twk-val"
  }, value)), children);
}

// ── Controls ────────────────────────────────────────────────────────────────

function TweakSlider({
  label,
  value,
  min = 0,
  max = 100,
  step = 1,
  unit = '',
  onChange
}) {
  return /*#__PURE__*/React.createElement(TweakRow, {
    label: label,
    value: `${value}${unit}`
  }, /*#__PURE__*/React.createElement("input", {
    type: "range",
    className: "twk-slider",
    min: min,
    max: max,
    step: step,
    value: value,
    onChange: e => onChange(Number(e.target.value))
  }));
}
function TweakToggle({
  label,
  value,
  onChange
}) {
  return /*#__PURE__*/React.createElement("div", {
    className: "twk-row twk-row-h"
  }, /*#__PURE__*/React.createElement("div", {
    className: "twk-lbl"
  }, /*#__PURE__*/React.createElement("span", null, label)), /*#__PURE__*/React.createElement("button", {
    type: "button",
    className: "twk-toggle",
    "data-on": value ? '1' : '0',
    role: "switch",
    "aria-checked": !!value,
    onClick: () => onChange(!value)
  }, /*#__PURE__*/React.createElement("i", null)));
}
function TweakRadio({
  label,
  value,
  options,
  onChange
}) {
  const trackRef = React.useRef(null);
  const [dragging, setDragging] = React.useState(false);
  // The active value is read by pointer-move handlers attached for the lifetime
  // of a drag — ref it so a stale closure doesn't fire onChange for every move.
  const valueRef = React.useRef(value);
  valueRef.current = value;

  // Segments wrap mid-word once per-segment width runs out. The track is
  // ~248px (280 panel − 28 body pad − 4 seg pad), each button loses 12px
  // to its own padding, and 11.5px system-ui averages ~6.3px/char — so 2
  // options fit ~16 chars each, 3 fit ~10. Past that (or >3 options), fall
  // back to a dropdown rather than wrap.
  const labelLen = o => String(typeof o === 'object' ? o.label : o).length;
  const maxLen = options.reduce((m, o) => Math.max(m, labelLen(o)), 0);
  const fitsAsSegments = maxLen <= ({
    2: 16,
    3: 10
  }[options.length] ?? 0);
  if (!fitsAsSegments) {
    // <select> emits strings — map back to the original option value so the
    // fallback stays type-preserving (numbers, booleans) like the segment path.
    const resolve = s => {
      const m = options.find(o => String(typeof o === 'object' ? o.value : o) === s);
      return m === undefined ? s : typeof m === 'object' ? m.value : m;
    };
    return /*#__PURE__*/React.createElement(TweakSelect, {
      label: label,
      value: value,
      options: options,
      onChange: s => onChange(resolve(s))
    });
  }
  const opts = options.map(o => typeof o === 'object' ? o : {
    value: o,
    label: o
  });
  const idx = Math.max(0, opts.findIndex(o => o.value === value));
  const n = opts.length;
  const segAt = clientX => {
    const r = trackRef.current.getBoundingClientRect();
    const inner = r.width - 4;
    const i = Math.floor((clientX - r.left - 2) / inner * n);
    return opts[Math.max(0, Math.min(n - 1, i))].value;
  };
  const onPointerDown = e => {
    setDragging(true);
    const v0 = segAt(e.clientX);
    if (v0 !== valueRef.current) onChange(v0);
    const move = ev => {
      if (!trackRef.current) return;
      const v = segAt(ev.clientX);
      if (v !== valueRef.current) onChange(v);
    };
    const up = () => {
      setDragging(false);
      window.removeEventListener('pointermove', move);
      window.removeEventListener('pointerup', up);
    };
    window.addEventListener('pointermove', move);
    window.addEventListener('pointerup', up);
  };
  return /*#__PURE__*/React.createElement(TweakRow, {
    label: label
  }, /*#__PURE__*/React.createElement("div", {
    ref: trackRef,
    role: "radiogroup",
    onPointerDown: onPointerDown,
    className: dragging ? 'twk-seg dragging' : 'twk-seg'
  }, /*#__PURE__*/React.createElement("div", {
    className: "twk-seg-thumb",
    style: {
      left: `calc(2px + ${idx} * (100% - 4px) / ${n})`,
      width: `calc((100% - 4px) / ${n})`
    }
  }), opts.map(o => /*#__PURE__*/React.createElement("button", {
    key: o.value,
    type: "button",
    role: "radio",
    "aria-checked": o.value === value
  }, o.label))));
}
function TweakSelect({
  label,
  value,
  options,
  onChange
}) {
  return /*#__PURE__*/React.createElement(TweakRow, {
    label: label
  }, /*#__PURE__*/React.createElement("select", {
    className: "twk-field",
    value: value,
    onChange: e => onChange(e.target.value)
  }, options.map(o => {
    const v = typeof o === 'object' ? o.value : o;
    const l = typeof o === 'object' ? o.label : o;
    return /*#__PURE__*/React.createElement("option", {
      key: v,
      value: v
    }, l);
  })));
}
function TweakText({
  label,
  value,
  placeholder,
  onChange
}) {
  return /*#__PURE__*/React.createElement(TweakRow, {
    label: label
  }, /*#__PURE__*/React.createElement("input", {
    className: "twk-field",
    type: "text",
    value: value,
    placeholder: placeholder,
    onChange: e => onChange(e.target.value)
  }));
}
function TweakNumber({
  label,
  value,
  min,
  max,
  step = 1,
  unit = '',
  onChange
}) {
  const clamp = n => {
    if (min != null && n < min) return min;
    if (max != null && n > max) return max;
    return n;
  };
  const startRef = React.useRef({
    x: 0,
    val: 0
  });
  const onScrubStart = e => {
    e.preventDefault();
    startRef.current = {
      x: e.clientX,
      val: value
    };
    const decimals = (String(step).split('.')[1] || '').length;
    const move = ev => {
      const dx = ev.clientX - startRef.current.x;
      const raw = startRef.current.val + dx * step;
      const snapped = Math.round(raw / step) * step;
      onChange(clamp(Number(snapped.toFixed(decimals))));
    };
    const up = () => {
      window.removeEventListener('pointermove', move);
      window.removeEventListener('pointerup', up);
    };
    window.addEventListener('pointermove', move);
    window.addEventListener('pointerup', up);
  };
  return /*#__PURE__*/React.createElement("div", {
    className: "twk-num"
  }, /*#__PURE__*/React.createElement("span", {
    className: "twk-num-lbl",
    onPointerDown: onScrubStart
  }, label), /*#__PURE__*/React.createElement("input", {
    type: "number",
    value: value,
    min: min,
    max: max,
    step: step,
    onChange: e => onChange(clamp(Number(e.target.value)))
  }), unit && /*#__PURE__*/React.createElement("span", {
    className: "twk-num-unit"
  }, unit));
}

// Relative-luminance contrast pick — checkmarks drawn over a swatch need to
// read on both #111 and #fafafa without per-option configuration. Hex input
// only (#rgb / #rrggbb); named or rgb()/hsl() colors fall through to "light".
function __twkIsLight(hex) {
  const h = String(hex).replace('#', '');
  const x = h.length === 3 ? h.replace(/./g, c => c + c) : h.padEnd(6, '0');
  const n = parseInt(x.slice(0, 6), 16);
  if (Number.isNaN(n)) return true;
  const r = n >> 16 & 255,
    g = n >> 8 & 255,
    b = n & 255;
  return r * 299 + g * 587 + b * 114 > 148000;
}
const __TwkCheck = ({
  light
}) => /*#__PURE__*/React.createElement("svg", {
  viewBox: "0 0 14 14",
  "aria-hidden": "true"
}, /*#__PURE__*/React.createElement("path", {
  d: "M3 7.2 5.8 10 11 4.2",
  fill: "none",
  strokeWidth: "2.2",
  strokeLinecap: "round",
  strokeLinejoin: "round",
  stroke: light ? 'rgba(0,0,0,.78)' : '#fff'
}));

// TweakColor — curated color/palette picker. Each option is either a single
// hex string or an array of 1-5 hex strings; the card adapts — a lone color
// renders solid, a palette renders colors[0] as the hero (left ~2/3) with the
// rest stacked in a sharp column on the right. onChange emits the
// option in the shape it was passed (string stays string, array stays array).
// Without options it falls back to the native color input for back-compat.
function TweakColor({
  label,
  value,
  options,
  onChange
}) {
  if (!options || !options.length) {
    return /*#__PURE__*/React.createElement("div", {
      className: "twk-row twk-row-h"
    }, /*#__PURE__*/React.createElement("div", {
      className: "twk-lbl"
    }, /*#__PURE__*/React.createElement("span", null, label)), /*#__PURE__*/React.createElement("input", {
      type: "color",
      className: "twk-swatch",
      value: value,
      onChange: e => onChange(e.target.value)
    }));
  }
  // Native <input type=color> emits lowercase hex per the HTML spec, so
  // compare case-insensitively. String() guards JSON.stringify(undefined),
  // which returns the primitive undefined (no .toLowerCase).
  const key = o => String(JSON.stringify(o)).toLowerCase();
  const cur = key(value);
  return /*#__PURE__*/React.createElement(TweakRow, {
    label: label
  }, /*#__PURE__*/React.createElement("div", {
    className: "twk-chips",
    role: "radiogroup"
  }, options.map((o, i) => {
    const colors = Array.isArray(o) ? o : [o];
    const [hero, ...rest] = colors;
    const sup = rest.slice(0, 4);
    const on = key(o) === cur;
    return /*#__PURE__*/React.createElement("button", {
      key: i,
      type: "button",
      className: "twk-chip",
      role: "radio",
      "aria-checked": on,
      "data-on": on ? '1' : '0',
      "aria-label": colors.join(', '),
      title: colors.join(' · '),
      style: {
        background: hero
      },
      onClick: () => onChange(o)
    }, sup.length > 0 && /*#__PURE__*/React.createElement("span", null, sup.map((c, j) => /*#__PURE__*/React.createElement("i", {
      key: j,
      style: {
        background: c
      }
    }))), on && /*#__PURE__*/React.createElement(__TwkCheck, {
      light: __twkIsLight(hero)
    }));
  })));
}
function TweakButton({
  label,
  onClick,
  secondary = false
}) {
  return /*#__PURE__*/React.createElement("button", {
    type: "button",
    className: secondary ? 'twk-btn secondary' : 'twk-btn',
    onClick: onClick
  }, label);
}
Object.assign(window, {
  useTweaks,
  TweaksPanel,
  TweakSection,
  TweakRow,
  TweakSlider,
  TweakToggle,
  TweakRadio,
  TweakSelect,
  TweakText,
  TweakNumber,
  TweakColor,
  TweakButton
});
})(); } catch (e) { __ds_ns.__errors.push({ path: "design_handoff_nokido/ui_kits/webhub/tweaks-panel.jsx", error: String((e && e.message) || e) }); }

// design_handoff_nokido/ui_kits/webhub/web-hub-extra.ref.jsx
try { (() => {
/* Nokido Web Hub — écrans ouverts par les puces & tuiles :
   Network Graph (forge/network), MCP Lab (skills), CTF Reports, Status JSON, Épistémique. */
const {
  Card,
  Badge,
  StatusPill,
  Button,
  ProvenanceBadge,
  TextInput
} = window.NokidoDesignSystem_bdc2ac;
const XIco = window.WIco || (({
  n,
  s = 18
}) => /*#__PURE__*/React.createElement("i", {
  "data-lucide": n,
  style: {
    width: s,
    height: s
  }
}));
const provShow = () => window.__WH_TW ? window.__WH_TW.provenance !== false : true;

/* ============================ Network Graph ============================ */
const NET_NODES = [{
  id: "brain",
  label: "Cerveau",
  group: "core",
  prov: "local",
  x: 0.50,
  y: 0.46,
  r: 26
}, {
  id: "router",
  label: "Routeur",
  group: "core",
  prov: "local",
  x: 0.50,
  y: 0.74,
  r: 18
}, {
  id: "rag",
  label: "RAG",
  group: "memory",
  prov: "local",
  x: 0.24,
  y: 0.34,
  r: 18
}, {
  id: "mem",
  label: "Mémoire",
  group: "memory",
  prov: "local",
  x: 0.18,
  y: 0.60,
  r: 15
}, {
  id: "mcp",
  label: "MCP",
  group: "tools",
  prov: "hybrid",
  x: 0.74,
  y: 0.30,
  r: 18
}, {
  id: "skills",
  label: "Skills",
  group: "tools",
  prov: "hybrid",
  x: 0.86,
  y: 0.52,
  r: 15
}, {
  id: "ollama",
  label: "Ollama",
  group: "compute",
  prov: "local",
  x: 0.40,
  y: 0.18,
  r: 16
}, {
  id: "cloud",
  label: "Cloud",
  group: "compute",
  prov: "remote",
  x: 0.66,
  y: 0.84,
  r: 16
}, {
  id: "vision",
  label: "Vision",
  group: "perception",
  prov: "local",
  x: 0.78,
  y: 0.70,
  r: 13
}, {
  id: "audio",
  label: "Audio",
  group: "perception",
  prov: "local",
  x: 0.30,
  y: 0.84,
  r: 13
}];
const NET_EDGES = [["brain", "router"], ["brain", "rag"], ["brain", "ollama"], ["brain", "mcp"], ["rag", "mem"], ["router", "cloud"], ["router", "mcp"], ["mcp", "skills"], ["router", "vision"], ["router", "audio"], ["brain", "mem"], ["mcp", "cloud"]];
const NET_COLOR = {
  local: "var(--prov-local)",
  hybrid: "var(--prov-hybrid)",
  remote: "var(--prov-remote)"
};
const NET_RAW = {
  local: "#4AC28B",
  hybrid: "#2DD4BF",
  remote: "#774AFF"
};
function NetworkView() {
  const W = 760,
    H = 460;
  const [sel, setSel] = React.useState("brain");
  const [t, setT] = React.useState(0);
  React.useEffect(() => {
    if (window.__WH_TW && window.__WH_TW.motion === false) return;
    let raf,
      start = performance.now();
    const loop = now => {
      setT((now - start) / 1000);
      raf = requestAnimationFrame(loop);
    };
    raf = requestAnimationFrame(loop);
    return () => cancelAnimationFrame(raf);
  }, []);
  const pos = n => ({
    x: n.x * W,
    y: n.y * H
  });
  const node = id => NET_NODES.find(n => n.id === id);
  const selNode = node(sel);
  const neighbours = NET_EDGES.filter(e => e.includes(sel)).map(e => e[0] === sel ? e[1] : e[0]);
  return /*#__PURE__*/React.createElement("div", {
    style: {
      maxWidth: "1100px",
      margin: "0 auto"
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      alignItems: "baseline",
      gap: "10px",
      marginBottom: "14px"
    }
  }, /*#__PURE__*/React.createElement("h2", {
    style: {
      margin: 0,
      fontSize: "13px",
      fontWeight: 700,
      textTransform: "uppercase",
      letterSpacing: "0.6px",
      color: "var(--text-secondary)"
    }
  }, "Network Graph"), /*#__PURE__*/React.createElement("span", {
    style: {
      fontFamily: "var(--font-mono)",
      fontSize: "11px",
      color: "var(--text-dim)"
    }
  }, "forge/network \xB7 ", NET_NODES.length, " n\u0153uds \xB7 ", NET_EDGES.length, " liens"), /*#__PURE__*/React.createElement("div", {
    style: {
      marginLeft: "auto",
      display: "flex",
      gap: "12px",
      fontFamily: "var(--font-mono)",
      fontSize: "10.5px"
    }
  }, /*#__PURE__*/React.createElement("span", {
    style: {
      color: "var(--prov-local)"
    }
  }, "\u25CF local"), /*#__PURE__*/React.createElement("span", {
    style: {
      color: "var(--prov-hybrid)"
    }
  }, "\u25CF hybride"), /*#__PURE__*/React.createElement("span", {
    style: {
      color: "var(--prov-remote)"
    }
  }, "\u25CF distant"))), /*#__PURE__*/React.createElement("div", {
    style: {
      display: "grid",
      gridTemplateColumns: "1fr 280px",
      gap: "14px",
      alignItems: "stretch"
    }
  }, /*#__PURE__*/React.createElement(Card, {
    style: {
      padding: 0,
      overflow: "hidden",
      background: "var(--bg-1)"
    }
  }, /*#__PURE__*/React.createElement("svg", {
    viewBox: `0 0 ${W} ${H}`,
    style: {
      width: "100%",
      display: "block",
      background: "radial-gradient(ellipse at 50% 40%, color-mix(in srgb, var(--purple) 7%, transparent), transparent 70%)"
    }
  }, NET_EDGES.map(([a, b], i) => {
    const pa = pos(node(a)),
      pb = pos(node(b));
    const active = sel === a || sel === b;
    const dash = 60,
      off = -(t * 40) % dash;
    return /*#__PURE__*/React.createElement("g", {
      key: i
    }, /*#__PURE__*/React.createElement("line", {
      x1: pa.x,
      y1: pa.y,
      x2: pb.x,
      y2: pb.y,
      stroke: active ? "var(--purple)" : "var(--border)",
      strokeWidth: active ? 2 : 1.2,
      opacity: active ? 0.9 : 0.5
    }), active && /*#__PURE__*/React.createElement("line", {
      x1: pa.x,
      y1: pa.y,
      x2: pb.x,
      y2: pb.y,
      stroke: NET_RAW[node(b).prov],
      strokeWidth: 2.5,
      strokeLinecap: "round",
      strokeDasharray: `6 ${dash - 6}`,
      strokeDashoffset: off,
      opacity: 0.9
    }));
  }), NET_NODES.map(n => {
    const p = pos(n);
    const on = sel === n.id;
    const near = neighbours.includes(n.id);
    const pulse = 1 + (window.__WH_TW && window.__WH_TW.motion === false ? 0 : Math.sin(t * 2 + n.x * 6) * 0.06);
    return /*#__PURE__*/React.createElement("g", {
      key: n.id,
      onClick: () => setSel(n.id),
      style: {
        cursor: "pointer"
      }
    }, /*#__PURE__*/React.createElement("circle", {
      cx: p.x,
      cy: p.y,
      r: n.r * pulse + (on ? 7 : 0),
      fill: NET_RAW[n.prov],
      opacity: on ? 0.22 : near ? 0.14 : 0.08
    }), /*#__PURE__*/React.createElement("circle", {
      cx: p.x,
      cy: p.y,
      r: n.r * pulse,
      fill: "var(--bg-2)",
      stroke: NET_RAW[n.prov],
      strokeWidth: on ? 3 : near ? 2 : 1.5
    }), /*#__PURE__*/React.createElement("circle", {
      cx: p.x,
      cy: p.y,
      r: n.r * pulse * 0.4,
      fill: NET_RAW[n.prov],
      opacity: 0.85
    }), /*#__PURE__*/React.createElement("text", {
      x: p.x,
      y: p.y + n.r * pulse + 13,
      textAnchor: "middle",
      fontSize: "11",
      fontFamily: "var(--font-mono)",
      fill: on ? "var(--text-primary)" : "var(--text-secondary)",
      fontWeight: on ? 700 : 500
    }, n.label));
  }))), /*#__PURE__*/React.createElement(Card, null, /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      alignItems: "center",
      gap: "9px",
      marginBottom: "12px"
    }
  }, /*#__PURE__*/React.createElement("span", {
    style: {
      width: "12px",
      height: "12px",
      borderRadius: "50%",
      background: NET_COLOR[selNode.prov],
      boxShadow: `0 0 8px ${NET_COLOR[selNode.prov]}`
    }
  }), /*#__PURE__*/React.createElement("span", {
    style: {
      fontSize: "16px",
      fontWeight: 700
    }
  }, selNode.label)), provShow() && /*#__PURE__*/React.createElement(ProvenanceBadge, {
    origin: selNode.prov,
    size: "sm"
  }), /*#__PURE__*/React.createElement("div", {
    style: {
      marginTop: "14px",
      display: "flex",
      flexDirection: "column",
      gap: "8px",
      fontFamily: "var(--font-mono)",
      fontSize: "11px",
      color: "var(--text-dim)"
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      justifyContent: "space-between"
    }
  }, /*#__PURE__*/React.createElement("span", null, "node.id"), /*#__PURE__*/React.createElement("span", {
    style: {
      color: "var(--text-secondary)"
    }
  }, selNode.id)), /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      justifyContent: "space-between"
    }
  }, /*#__PURE__*/React.createElement("span", null, "groupe"), /*#__PURE__*/React.createElement("span", {
    style: {
      color: "var(--text-secondary)"
    }
  }, selNode.group)), /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      justifyContent: "space-between"
    }
  }, /*#__PURE__*/React.createElement("span", null, "liens"), /*#__PURE__*/React.createElement("span", {
    style: {
      color: "var(--text-secondary)"
    }
  }, neighbours.length))), /*#__PURE__*/React.createElement("div", {
    style: {
      marginTop: "14px",
      paddingTop: "12px",
      borderTop: "1px solid var(--border-subtle)"
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      fontFamily: "var(--font-mono)",
      fontSize: "10px",
      textTransform: "uppercase",
      letterSpacing: "0.5px",
      color: "var(--text-dim)",
      marginBottom: "8px"
    }
  }, "Connect\xE9 \xE0"), /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      flexWrap: "wrap",
      gap: "6px"
    }
  }, neighbours.map(id => /*#__PURE__*/React.createElement("button", {
    key: id,
    onClick: () => setSel(id),
    style: {
      display: "inline-flex",
      alignItems: "center",
      gap: "5px",
      padding: "3px 9px",
      borderRadius: "var(--radius-pill)",
      border: "1px solid var(--border)",
      background: "transparent",
      color: "var(--text-secondary)",
      fontSize: "11px",
      fontFamily: "var(--font-mono)",
      cursor: "pointer"
    }
  }, /*#__PURE__*/React.createElement("span", {
    style: {
      width: "6px",
      height: "6px",
      borderRadius: "50%",
      background: NET_COLOR[node(id).prov]
    }
  }), node(id).label)))))));
}

/* ============================ MCP Lab (skills) ============================ */
const SKILLS = [{
  name: "web.fetch",
  cat: "Réseau",
  prov: "remote",
  ring: "verified",
  desc: "Récupère une URL (anonymisé)",
  calls: 142
}, {
  name: "fs.read",
  cat: "Système",
  prov: "local",
  ring: "gold",
  desc: "Lecture fichier local",
  calls: 980
}, {
  name: "rag.search",
  cat: "Mémoire",
  prov: "local",
  ring: "gold",
  desc: "Recherche sémantique locale",
  calls: 411
}, {
  name: "shell.run",
  cat: "Système",
  prov: "local",
  ring: "verified",
  desc: "Commande sandboxée",
  calls: 67
}, {
  name: "vision.ocr",
  cat: "Perception",
  prov: "local",
  ring: "draft",
  desc: "OCR d'image locale",
  calls: 23
}, {
  name: "cloud.ask",
  cat: "LLM",
  prov: "remote",
  ring: "verified",
  desc: "Délègue au cloud (anonymisé)",
  calls: 88
}];
function McpLabView() {
  const [sel, setSel] = React.useState(SKILLS[1]);
  const [q, setQ] = React.useState("");
  const [out, setOut] = React.useState(null);
  const list = SKILLS.filter(s => s.name.includes(q.toLowerCase()) || s.cat.toLowerCase().includes(q.toLowerCase()));
  const invoke = () => setOut({
    ok: true,
    skill: sel.name,
    prov: sel.prov,
    ms: 40 + Math.floor(Math.random() * 600),
    ring: sel.ring
  });
  return /*#__PURE__*/React.createElement("div", {
    style: {
      maxWidth: "1000px",
      margin: "0 auto"
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      alignItems: "baseline",
      gap: "10px",
      marginBottom: "14px"
    }
  }, /*#__PURE__*/React.createElement("h2", {
    style: {
      margin: 0,
      fontSize: "13px",
      fontWeight: 700,
      textTransform: "uppercase",
      letterSpacing: "0.6px",
      color: "var(--text-secondary)"
    }
  }, "MCP Lab"), /*#__PURE__*/React.createElement("span", {
    style: {
      fontFamily: "var(--font-mono)",
      fontSize: "11px",
      color: "var(--text-dim)"
    }
  }, "marketplace de skills \xB7 endpoint :8766")), /*#__PURE__*/React.createElement("div", {
    style: {
      display: "grid",
      gridTemplateColumns: "1fr 340px",
      gap: "14px",
      alignItems: "start"
    }
  }, /*#__PURE__*/React.createElement("div", null, /*#__PURE__*/React.createElement("div", {
    style: {
      marginBottom: "10px"
    }
  }, /*#__PURE__*/React.createElement(TextInput, {
    placeholder: "Filtrer les skills\u2026",
    icon: /*#__PURE__*/React.createElement(XIco, {
      n: "search",
      s: 15
    }),
    value: q,
    onChange: e => setQ(e.target.value)
  })), /*#__PURE__*/React.createElement("div", {
    style: {
      display: "grid",
      gridTemplateColumns: "1fr 1fr",
      gap: "10px"
    }
  }, list.map(s => {
    const on = sel.name === s.name;
    return /*#__PURE__*/React.createElement("button", {
      key: s.name,
      onClick: () => {
        setSel(s);
        setOut(null);
      },
      style: {
        textAlign: "left",
        padding: "13px",
        borderRadius: "var(--radius-md)",
        cursor: "pointer",
        background: on ? "var(--bg-3)" : "var(--bg-2)",
        border: `1px solid ${on ? "var(--purple)" : "var(--border)"}`,
        color: "var(--text-primary)"
      }
    }, /*#__PURE__*/React.createElement("div", {
      style: {
        display: "flex",
        justifyContent: "space-between",
        alignItems: "center"
      }
    }, /*#__PURE__*/React.createElement("span", {
      style: {
        fontFamily: "var(--font-mono)",
        fontSize: "13px",
        fontWeight: 700
      }
    }, s.name), /*#__PURE__*/React.createElement(Badge, {
      color: "dim",
      mono: true
    }, s.cat)), /*#__PURE__*/React.createElement("div", {
      style: {
        fontSize: "11.5px",
        color: "var(--text-secondary)",
        margin: "5px 0 9px"
      }
    }, s.desc), /*#__PURE__*/React.createElement("div", {
      style: {
        display: "flex",
        alignItems: "center",
        gap: "8px"
      }
    }, provShow() && /*#__PURE__*/React.createElement(ProvenanceBadge, {
      origin: s.prov,
      ring: s.ring,
      size: "sm"
    }), /*#__PURE__*/React.createElement("span", {
      style: {
        marginLeft: "auto",
        fontFamily: "var(--font-mono)",
        fontSize: "10px",
        color: "var(--text-dim)"
      }
    }, s.calls, " appels")));
  }))), /*#__PURE__*/React.createElement(Card, null, /*#__PURE__*/React.createElement("div", {
    style: {
      fontFamily: "var(--font-mono)",
      fontSize: "10px",
      textTransform: "uppercase",
      letterSpacing: "0.5px",
      color: "var(--text-dim)",
      marginBottom: "10px"
    }
  }, "Invoke"), /*#__PURE__*/React.createElement("div", {
    style: {
      fontFamily: "var(--font-mono)",
      fontSize: "14px",
      fontWeight: 700,
      marginBottom: "6px"
    }
  }, sel.name), provShow() && /*#__PURE__*/React.createElement(ProvenanceBadge, {
    origin: sel.prov,
    ring: sel.ring,
    size: "sm"
  }), /*#__PURE__*/React.createElement("div", {
    style: {
      marginTop: "12px"
    }
  }, /*#__PURE__*/React.createElement(TextInput, {
    multiline: true,
    rows: 3,
    placeholder: `{ "arg": "valeur" }`,
    value: "",
    onChange: () => {}
  })), /*#__PURE__*/React.createElement(Button, {
    variant: "primary",
    size: "md",
    icon: /*#__PURE__*/React.createElement(XIco, {
      n: "play",
      s: 14
    }),
    style: {
      width: "100%",
      marginTop: "10px"
    },
    onClick: invoke
  }, "Ex\xE9cuter"), out && /*#__PURE__*/React.createElement("pre", {
    style: {
      marginTop: "12px",
      marginBottom: 0,
      background: "var(--bg-0)",
      border: "1px solid var(--border-subtle)",
      borderRadius: "var(--radius-sm)",
      padding: "11px",
      fontSize: "11px",
      fontFamily: "var(--font-mono)",
      color: "var(--text-secondary)",
      whiteSpace: "pre-wrap"
    }
  }, JSON.stringify(out, null, 2)))));
}

/* ============================ CTF Reports ============================ */
const REPORTS = [{
  id: "LF-2026-0042",
  title: "Recon réseau interne",
  state: "or",
  date: "08/06",
  prov: "local",
  ring: "gold"
}, {
  id: "LF-2026-0041",
  title: "Audit dépendances RAG",
  state: "vérifié",
  date: "07/06",
  prov: "local",
  ring: "verified"
}, {
  id: "LF-2026-0039",
  title: "Test exfiltration (sandbox)",
  state: "brouillon",
  date: "05/06",
  prov: "hybrid",
  ring: "draft"
}, {
  id: "LF-2026-0036",
  title: "Cartographie CVE",
  state: "vérifié",
  date: "02/06",
  prov: "local",
  ring: "verified"
}];
function ReportsView() {
  return /*#__PURE__*/React.createElement("div", {
    style: {
      maxWidth: "860px",
      margin: "0 auto"
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      alignItems: "baseline",
      gap: "10px",
      marginBottom: "14px"
    }
  }, /*#__PURE__*/React.createElement("h2", {
    style: {
      margin: 0,
      fontSize: "13px",
      fontWeight: 700,
      textTransform: "uppercase",
      letterSpacing: "0.6px",
      color: "var(--text-secondary)"
    }
  }, "CTF Reports"), /*#__PURE__*/React.createElement("span", {
    style: {
      fontFamily: "var(--font-mono)",
      fontSize: "11px",
      color: "var(--text-dim)"
    }
  }, "rapports & traces \xB7 /reports/"), /*#__PURE__*/React.createElement(Badge, {
    color: "dim",
    mono: true,
    style: {
      marginLeft: "auto"
    }
  }, "EXT")), /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      flexDirection: "column",
      gap: "8px"
    }
  }, REPORTS.map(r => /*#__PURE__*/React.createElement("div", {
    key: r.id,
    style: {
      display: "flex",
      alignItems: "center",
      gap: "13px",
      padding: "13px 16px",
      background: "var(--bg-2)",
      border: "1px solid var(--border)",
      borderRadius: "var(--radius-md)"
    }
  }, /*#__PURE__*/React.createElement("span", {
    style: {
      display: "inline-flex",
      alignItems: "center",
      justifyContent: "center",
      width: "34px",
      height: "34px",
      borderRadius: "var(--radius-sm)",
      background: "var(--tint-red)",
      color: "var(--red)",
      flexShrink: 0
    }
  }, /*#__PURE__*/React.createElement(XIco, {
    n: "flag",
    s: 16
  })), /*#__PURE__*/React.createElement("div", {
    style: {
      flex: 1,
      minWidth: 0
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      fontSize: "13.5px",
      fontWeight: 600
    }
  }, r.title), /*#__PURE__*/React.createElement("div", {
    style: {
      fontFamily: "var(--font-mono)",
      fontSize: "10.5px",
      color: "var(--text-dim)"
    }
  }, r.id, " \xB7 ", r.date)), provShow() && /*#__PURE__*/React.createElement(ProvenanceBadge, {
    origin: r.prov,
    ring: r.ring,
    size: "sm"
  }), /*#__PURE__*/React.createElement(Button, {
    variant: "ghost",
    size: "sm",
    icon: /*#__PURE__*/React.createElement(XIco, {
      n: "arrow-up-right",
      s: 13
    })
  }, "Ouvrir")))));
}

/* ============================ Status JSON ============================ */
function StatusView() {
  const status = {
    node: "souverain-0",
    ring: 0,
    version: "18.3",
    uptime_s: 8064,
    sovereignty: {
      local_pct: 68,
      opsec: "STANDARD",
      kill_switch: false
    },
    services: {
      brain_worker: "running",
      web_hub: "running",
      hub_mcp: "running",
      rag_indexer: "running",
      swarm: "stale",
      deno_edge: "stopped"
    },
    rag: {
      documents: 128,
      chunks: 3412,
      model: "bge-m3",
      dims: 1024
    }
  };
  const color = v => typeof v === "boolean" ? v ? "var(--green)" : "var(--red)" : v === "running" ? "var(--green)" : v === "stale" ? "var(--yellow)" : v === "stopped" ? "var(--text-dim)" : typeof v === "number" ? "var(--cyan)" : "var(--orange)";
  const render = (obj, depth = 0) => Object.entries(obj).map(([k, v]) => {
    const isObj = v && typeof v === "object";
    return /*#__PURE__*/React.createElement("div", {
      key: k,
      style: {
        paddingLeft: depth * 16
      }
    }, /*#__PURE__*/React.createElement("span", {
      style: {
        color: "var(--purple)"
      }
    }, "\"", k, "\""), /*#__PURE__*/React.createElement("span", {
      style: {
        color: "var(--text-dim)"
      }
    }, ": "), isObj ? /*#__PURE__*/React.createElement("span", {
      style: {
        color: "var(--text-dim)"
      }
    }, Array.isArray(v) ? "[" : "{") : /*#__PURE__*/React.createElement("span", {
      style: {
        color: color(v)
      }
    }, JSON.stringify(v)), isObj && /*#__PURE__*/React.createElement("div", null, render(v, depth + 1)), isObj && /*#__PURE__*/React.createElement("span", {
      style: {
        color: "var(--text-dim)",
        paddingLeft: depth * 16
      }
    }, Array.isArray(v) ? "]" : "}"));
  });
  return /*#__PURE__*/React.createElement("div", {
    style: {
      maxWidth: "720px",
      margin: "0 auto"
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      alignItems: "baseline",
      gap: "10px",
      marginBottom: "14px"
    }
  }, /*#__PURE__*/React.createElement("h2", {
    style: {
      margin: 0,
      fontSize: "13px",
      fontWeight: 700,
      textTransform: "uppercase",
      letterSpacing: "0.6px",
      color: "var(--text-secondary)"
    }
  }, "Status JSON"), /*#__PURE__*/React.createElement("span", {
    style: {
      fontFamily: "var(--font-mono)",
      fontSize: "11px",
      color: "var(--text-dim)"
    }
  }, "GET /status.json"), /*#__PURE__*/React.createElement(StatusPill, {
    status: "up",
    pulse: true,
    style: {
      marginLeft: "auto"
    }
  }, "200 OK")), /*#__PURE__*/React.createElement(Card, {
    style: {
      background: "var(--bg-1)"
    }
  }, /*#__PURE__*/React.createElement("pre", {
    style: {
      margin: 0,
      fontFamily: "var(--font-mono)",
      fontSize: "12px",
      lineHeight: 1.7,
      overflow: "auto"
    }
  }, /*#__PURE__*/React.createElement("span", {
    style: {
      color: "var(--text-dim)"
    }
  }, "{"), render(status, 1), /*#__PURE__*/React.createElement("span", {
    style: {
      color: "var(--text-dim)"
    }
  }, "}"))));
}
Object.assign(window, {
  NetworkView,
  McpLabView,
  ReportsView,
  StatusView,
  PipelineView,
  SwarmView,
  DebateView
});

/* ============================ Swarm (essaim d'agents) ============================ */
const AGENTS = [{
  id: "archiviste",
  label: "Archiviste-Paléographe",
  role: "Archives & paléographie",
  prov: "local",
  state: "active",
  load: 0.74
}, {
  id: "cryptographe",
  label: "Cryptographe",
  role: "Chiffrement & analyse",
  prov: "local",
  state: "active",
  load: 0.61
}, {
  id: "cartographe",
  label: "Géomaticien-Cartographe",
  role: "SIG & cartographie",
  prov: "hybrid",
  state: "alive",
  load: 0.33
}, {
  id: "graphiste",
  label: "Graphiste-DA",
  role: "Direction artistique",
  prov: "local",
  state: "idle",
  load: 0.08
}, {
  id: "libraire",
  label: "Libraire-Bibliographe",
  role: "Recherche bibliographique",
  prov: "local",
  state: "active",
  load: 0.52
}, {
  id: "sociologue",
  label: "Sociologue-Démographe",
  role: "Analyse sociale",
  prov: "remote",
  state: "alive",
  load: 0.27
}];
const A_STATE = {
  active: {
    c: "var(--green)",
    t: "active"
  },
  alive: {
    c: "var(--cyan)",
    t: "alive"
  },
  idle: {
    c: "var(--text-dim)",
    t: "idle"
  }
};
function SwarmView() {
  const [tasks] = React.useState(34);
  const active = AGENTS.filter(a => a.state === "active").length;
  return /*#__PURE__*/React.createElement("div", {
    style: {
      maxWidth: "1000px",
      margin: "0 auto"
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      alignItems: "baseline",
      gap: "10px",
      marginBottom: "14px"
    }
  }, /*#__PURE__*/React.createElement("h2", {
    style: {
      margin: 0,
      fontSize: "13px",
      fontWeight: 700,
      textTransform: "uppercase",
      letterSpacing: "0.6px",
      color: "var(--text-secondary)"
    }
  }, "Swarm"), /*#__PURE__*/React.createElement("span", {
    style: {
      fontFamily: "var(--font-mono)",
      fontSize: "11px",
      color: "var(--text-dim)"
    }
  }, "essaim d'agents \xB7 ", active, " actifs \xB7 ", tasks, " t\xE2ches en silo"), provShow() && /*#__PURE__*/React.createElement(ProvenanceBadge, {
    origin: "hybrid",
    detail: "orchestration locale",
    size: "sm",
    style: {
      marginLeft: "auto"
    }
  })), /*#__PURE__*/React.createElement("div", {
    style: {
      display: "grid",
      gridTemplateColumns: "repeat(auto-fill, minmax(300px, 1fr))",
      gap: "12px"
    }
  }, AGENTS.map(a => {
    const st = A_STATE[a.state];
    return /*#__PURE__*/React.createElement(Card, {
      key: a.id
    }, /*#__PURE__*/React.createElement("div", {
      style: {
        display: "flex",
        alignItems: "flex-start",
        gap: "11px"
      }
    }, /*#__PURE__*/React.createElement("span", {
      style: {
        display: "inline-flex",
        alignItems: "center",
        justifyContent: "center",
        width: "40px",
        height: "40px",
        borderRadius: "var(--radius-sm)",
        background: "var(--tint-purple)",
        color: "var(--purple)",
        flexShrink: 0
      }
    }, /*#__PURE__*/React.createElement(XIco, {
      n: "bot",
      s: 20
    })), /*#__PURE__*/React.createElement("div", {
      style: {
        flex: 1,
        minWidth: 0
      }
    }, /*#__PURE__*/React.createElement("div", {
      style: {
        fontSize: "14px",
        fontWeight: 700
      }
    }, a.label), /*#__PURE__*/React.createElement("div", {
      style: {
        fontSize: "11.5px",
        color: "var(--text-dim)"
      }
    }, a.role)), /*#__PURE__*/React.createElement("span", {
      className: a.state !== "idle" ? "laforge-pulse" : "",
      style: {
        width: "10px",
        height: "10px",
        borderRadius: "50%",
        background: st.c,
        boxShadow: `0 0 8px ${st.c}`,
        flexShrink: 0,
        marginTop: "5px"
      }
    })), /*#__PURE__*/React.createElement("div", {
      style: {
        marginTop: "12px",
        display: "flex",
        alignItems: "center",
        gap: "10px"
      }
    }, /*#__PURE__*/React.createElement("div", {
      style: {
        flex: 1,
        height: "5px",
        borderRadius: "3px",
        background: "var(--bg-4)",
        overflow: "hidden"
      }
    }, /*#__PURE__*/React.createElement("div", {
      style: {
        width: `${Math.round(a.load * 100)}%`,
        height: "100%",
        background: st.c
      }
    })), /*#__PURE__*/React.createElement("span", {
      style: {
        fontFamily: "var(--font-mono)",
        fontSize: "10px",
        color: "var(--text-dim)"
      }
    }, Math.round(a.load * 100), "%"), provShow() && /*#__PURE__*/React.createElement(ProvenanceBadge, {
      origin: a.prov,
      size: "sm"
    })));
  })));
}

/* ============================ LLM Debate ============================ */
const DEBATE = [{
  model: "ollama:mistral",
  prov: "local",
  side: "Pour",
  text: "Rester 100% local : la confidentialité prime, le NPU suffit pour 90% des requêtes.",
  ring: "verified"
}, {
  model: "groq:llama-70b",
  prov: "remote",
  side: "Contre",
  text: "Le cloud apporte une puissance que le local n'atteint pas sur les longues roadmaps.",
  ring: "verified"
}, {
  model: "ollama:qwen",
  prov: "local",
  side: "Nuance",
  text: "Hybride adaptatif : local par défaut, cloud anonymisé uniquement au-delà d'un seuil de complexité.",
  ring: "gold"
}];
function DebateView() {
  const [round] = React.useState(2);
  const sideColor = {
    Pour: "var(--green)",
    Contre: "var(--red)",
    Nuance: "var(--cyan)"
  };
  return /*#__PURE__*/React.createElement("div", {
    style: {
      maxWidth: "840px",
      margin: "0 auto"
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      alignItems: "baseline",
      gap: "10px",
      marginBottom: "14px"
    }
  }, /*#__PURE__*/React.createElement("h2", {
    style: {
      margin: 0,
      fontSize: "13px",
      fontWeight: 700,
      textTransform: "uppercase",
      letterSpacing: "0.6px",
      color: "var(--text-secondary)"
    }
  }, "LLM Debate"), /*#__PURE__*/React.createElement("span", {
    style: {
      fontFamily: "var(--font-mono)",
      fontSize: "11px",
      color: "var(--text-dim)"
    }
  }, "d\xE9bat multi-mod\xE8les \xB7 round ", round, "/3")), /*#__PURE__*/React.createElement(Card, {
    style: {
      background: "var(--bg-1)",
      marginBottom: "14px"
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      fontSize: "11px",
      textTransform: "uppercase",
      letterSpacing: "0.5px",
      color: "var(--text-dim)",
      marginBottom: "5px"
    }
  }, "Motion"), /*#__PURE__*/React.createElement("p", {
    style: {
      margin: 0,
      fontSize: "15px",
      fontWeight: 600,
      lineHeight: 1.4
    }
  }, "\xAB Nokido devrait-il rester strictement local, ou d\xE9l\xE9guer au cloud quand c'est plus performant ? \xBB")), /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      flexDirection: "column",
      gap: "12px"
    }
  }, DEBATE.map((d, i) => /*#__PURE__*/React.createElement("div", {
    key: i,
    style: {
      display: "flex",
      gap: "12px"
    }
  }, /*#__PURE__*/React.createElement("span", {
    style: {
      display: "inline-flex",
      alignItems: "center",
      justifyContent: "center",
      width: "38px",
      height: "38px",
      borderRadius: "var(--radius-sm)",
      flexShrink: 0,
      background: `color-mix(in srgb, ${d.prov === "remote" ? "var(--prov-remote)" : "var(--prov-local)"} 16%, transparent)`,
      color: d.prov === "remote" ? "var(--prov-remote)" : "var(--prov-local)"
    }
  }, /*#__PURE__*/React.createElement(XIco, {
    n: "message-circle",
    s: 18
  })), /*#__PURE__*/React.createElement(Card, {
    style: {
      flex: 1
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      alignItems: "center",
      gap: "8px",
      marginBottom: "7px"
    }
  }, /*#__PURE__*/React.createElement("span", {
    style: {
      fontFamily: "var(--font-mono)",
      fontSize: "12px",
      fontWeight: 700
    }
  }, d.model), /*#__PURE__*/React.createElement("span", {
    style: {
      fontFamily: "var(--font-mono)",
      fontSize: "9px",
      fontWeight: 700,
      color: sideColor[d.side],
      border: `1px solid ${sideColor[d.side]}`,
      borderRadius: "4px",
      padding: "1px 6px"
    }
  }, d.side), provShow() && /*#__PURE__*/React.createElement(ProvenanceBadge, {
    origin: d.prov,
    ring: d.ring,
    size: "sm",
    style: {
      marginLeft: "auto"
    }
  })), /*#__PURE__*/React.createElement("p", {
    style: {
      margin: 0,
      fontSize: "13px",
      color: "var(--text-secondary)",
      lineHeight: 1.5
    }
  }, d.text))))), /*#__PURE__*/React.createElement(Card, {
    style: {
      marginTop: "14px",
      background: "var(--bg-1)",
      display: "flex",
      alignItems: "center",
      gap: "10px"
    }
  }, /*#__PURE__*/React.createElement(XIco, {
    n: "gavel",
    s: 16
  }), /*#__PURE__*/React.createElement("span", {
    style: {
      fontSize: "12.5px",
      color: "var(--text-secondary)"
    }
  }, "Synth\xE8se de l'arbitre : ", /*#__PURE__*/React.createElement("b", {
    style: {
      color: "var(--cyan)"
    }
  }, "hybride adaptatif"), " retenu \u2014 anneau"), /*#__PURE__*/React.createElement("span", {
    style: {
      marginLeft: "auto"
    }
  }, /*#__PURE__*/React.createElement(Badge, {
    color: "yellow",
    variant: "outline"
  }, "Or"))));
}

/* ============================ Pipeline souverain (CI) ============================ */
function PipelineView() {
  // Gate PRIMAIRE = local (gratuit, hors quota) ; fallback = cloud (manuel, workflow_dispatch).
  const LOCAL_GATE = [{
    name: "pre-commit · secret-scan",
    desc: "gitleaks local au commit",
    state: "pass",
    ring: "gold",
    ms: 420
  }, {
    name: "tools/ci_local.py",
    desc: "pre-push : ruff + bandit + AST",
    state: "pass",
    ring: "gold",
    ms: 3100
  }, {
    name: "pytest (sélection)",
    desc: "tests unitaires rapides",
    state: "pass",
    ring: "verified",
    ms: 8800
  }, {
    name: "ci-selfhosted.yml",
    desc: "runner local gratuit",
    state: "running",
    ring: "verified",
    ms: null
  }];
  const CLOUD_FALLBACK = [{
    name: "ci.yml",
    desc: "matrice 3-OS (portabilité)",
    trigger: "workflow_dispatch"
  }, {
    name: "eco-shield.yml",
    desc: "ruff + bandit cross-OS",
    trigger: "workflow_dispatch"
  }, {
    name: "gitleaks.yml",
    desc: "scan secrets profond",
    trigger: "workflow_dispatch"
  }, {
    name: "docker-publish.yml",
    desc: "image OCI",
    trigger: "release"
  }, {
    name: "release.yml",
    desc: "publication miroir public",
    trigger: "tag v*"
  }, {
    name: "cla.yml",
    desc: "contributor agreement",
    trigger: "pull_request"
  }];
  const STATE = {
    pass: {
      c: "var(--green)",
      i: "check",
      t: "ok"
    },
    running: {
      c: "var(--cyan)",
      i: "loader",
      t: "en cours"
    },
    fail: {
      c: "var(--red)",
      i: "x",
      t: "échec"
    }
  };
  const FLOW = [{
    label: "commit",
    icon: "git-commit-horizontal",
    prov: "local"
  }, {
    label: "pre-commit",
    icon: "shield-check",
    prov: "local"
  }, {
    label: "pre-push",
    icon: "terminal",
    prov: "local"
  }, {
    label: "self-hosted",
    icon: "server",
    prov: "local"
  }, {
    label: "merge",
    icon: "git-merge",
    prov: "local"
  }, {
    label: "cloud (manuel)",
    icon: "cloud",
    prov: "remote"
  }];
  const provC = {
    local: "var(--prov-local)",
    remote: "var(--prov-remote)"
  };
  return /*#__PURE__*/React.createElement("div", {
    style: {
      maxWidth: "1040px",
      margin: "0 auto"
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      alignItems: "baseline",
      gap: "10px",
      marginBottom: "14px"
    }
  }, /*#__PURE__*/React.createElement("h2", {
    style: {
      margin: 0,
      fontSize: "13px",
      fontWeight: 700,
      textTransform: "uppercase",
      letterSpacing: "0.6px",
      color: "var(--text-secondary)"
    }
  }, "Pipeline souverain"), /*#__PURE__*/React.createElement("span", {
    style: {
      fontFamily: "var(--font-mono)",
      fontSize: "11px",
      color: "var(--text-dim)"
    }
  }, "gate local d'abord \xB7 cloud en dernier recours"), provShow() && /*#__PURE__*/React.createElement(ProvenanceBadge, {
    origin: "local",
    detail: "hors quota Actions",
    size: "sm",
    style: {
      marginLeft: "auto"
    }
  })), /*#__PURE__*/React.createElement(Card, {
    style: {
      background: "var(--bg-1)",
      marginBottom: "16px"
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      alignItems: "center",
      gap: "4px",
      flexWrap: "wrap"
    }
  }, FLOW.map((f, i) => /*#__PURE__*/React.createElement(React.Fragment, {
    key: f.label
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      flexDirection: "column",
      alignItems: "center",
      gap: "6px",
      minWidth: "82px"
    }
  }, /*#__PURE__*/React.createElement("span", {
    style: {
      display: "inline-flex",
      alignItems: "center",
      justifyContent: "center",
      width: "38px",
      height: "38px",
      borderRadius: "var(--radius-sm)",
      background: `color-mix(in srgb, ${provC[f.prov]} 16%, transparent)`,
      color: provC[f.prov],
      border: `1px solid ${provC[f.prov]}`
    }
  }, /*#__PURE__*/React.createElement(XIco, {
    n: f.icon,
    s: 18
  })), /*#__PURE__*/React.createElement("span", {
    style: {
      fontFamily: "var(--font-mono)",
      fontSize: "10px",
      color: "var(--text-secondary)",
      textAlign: "center"
    }
  }, f.label)), i < FLOW.length - 1 && /*#__PURE__*/React.createElement("span", {
    style: {
      flex: 1,
      minWidth: "16px",
      height: "2px",
      borderRadius: "2px",
      background: FLOW[i + 1].prov === "remote" ? "repeating-linear-gradient(90deg, var(--prov-remote) 0 5px, transparent 5px 10px)" : "var(--prov-local)",
      opacity: 0.6
    }
  }))))), /*#__PURE__*/React.createElement("div", {
    style: {
      display: "grid",
      gridTemplateColumns: "1fr 1fr",
      gap: "14px",
      alignItems: "start"
    }
  }, /*#__PURE__*/React.createElement(Card, {
    style: {
      borderColor: "var(--prov-local)",
      boxShadow: "var(--prov-local-glow)"
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      alignItems: "center",
      gap: "8px",
      marginBottom: "4px"
    }
  }, /*#__PURE__*/React.createElement(XIco, {
    n: "shield-check",
    s: 16
  }), /*#__PURE__*/React.createElement("span", {
    style: {
      fontWeight: 700,
      fontSize: "14px"
    }
  }, "Gate primaire \xB7 LOCAL"), /*#__PURE__*/React.createElement(Badge, {
    color: "green",
    mono: true,
    style: {
      marginLeft: "auto"
    }
  }, "Gratuit")), /*#__PURE__*/React.createElement("div", {
    style: {
      fontSize: "11.5px",
      color: "var(--text-dim)",
      marginBottom: "12px"
    }
  }, "Tourne sur ta machine / runner self-hosted. Bloquant."), /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      flexDirection: "column",
      gap: "8px"
    }
  }, LOCAL_GATE.map(c => {
    const st = STATE[c.state];
    return /*#__PURE__*/React.createElement("div", {
      key: c.name,
      style: {
        display: "flex",
        alignItems: "center",
        gap: "11px",
        padding: "10px 12px",
        background: "var(--bg-2)",
        border: "1px solid var(--border)",
        borderRadius: "var(--radius-sm)"
      }
    }, /*#__PURE__*/React.createElement("span", {
      className: c.state === "running" ? "laforge-pulse" : "",
      style: {
        display: "inline-flex",
        alignItems: "center",
        justifyContent: "center",
        width: "22px",
        height: "22px",
        borderRadius: "50%",
        background: `color-mix(in srgb, ${st.c} 16%, transparent)`,
        color: st.c,
        flexShrink: 0
      }
    }, /*#__PURE__*/React.createElement(XIco, {
      n: st.i,
      s: 13
    })), /*#__PURE__*/React.createElement("div", {
      style: {
        flex: 1,
        minWidth: 0
      }
    }, /*#__PURE__*/React.createElement("div", {
      style: {
        fontFamily: "var(--font-mono)",
        fontSize: "12px",
        fontWeight: 600
      }
    }, c.name), /*#__PURE__*/React.createElement("div", {
      style: {
        fontSize: "10.5px",
        color: "var(--text-dim)"
      }
    }, c.desc)), /*#__PURE__*/React.createElement("span", {
      style: {
        fontFamily: "var(--font-mono)",
        fontSize: "10px",
        color: "var(--text-dim)"
      }
    }, c.ms ? `${c.ms}ms` : "…"), provShow() && /*#__PURE__*/React.createElement("span", {
      style: {
        width: "9px",
        height: "9px",
        borderRadius: "50%",
        background: c.ring === "gold" ? "var(--ring-gold)" : "var(--ring-verified)",
        boxShadow: `0 0 6px ${c.ring === "gold" ? "var(--ring-gold)" : "var(--ring-verified)"}`
      }
    }));
  }))), /*#__PURE__*/React.createElement(Card, null, /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      alignItems: "center",
      gap: "8px",
      marginBottom: "4px"
    }
  }, /*#__PURE__*/React.createElement(XIco, {
    n: "cloud",
    s: 16
  }), /*#__PURE__*/React.createElement("span", {
    style: {
      fontWeight: 700,
      fontSize: "14px"
    }
  }, "Fallback cloud \xB7 MANUEL"), /*#__PURE__*/React.createElement(Badge, {
    color: "purple",
    mono: true,
    style: {
      marginLeft: "auto"
    }
  }, "\xC0 la demande")), /*#__PURE__*/React.createElement("div", {
    style: {
      fontSize: "11.5px",
      color: "var(--text-dim)",
      marginBottom: "12px"
    }
  }, "GitHub-hosted = quota payant. ", /*#__PURE__*/React.createElement("span", {
    style: {
      fontFamily: "var(--font-mono)"
    }
  }, "workflow_dispatch"), " seulement."), /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      flexDirection: "column",
      gap: "8px"
    }
  }, CLOUD_FALLBACK.map(w => /*#__PURE__*/React.createElement("div", {
    key: w.name,
    style: {
      display: "flex",
      alignItems: "center",
      gap: "11px",
      padding: "10px 12px",
      background: "var(--bg-1)",
      border: "1px solid var(--border-subtle)",
      borderRadius: "var(--radius-sm)",
      opacity: 0.92
    }
  }, /*#__PURE__*/React.createElement("span", {
    style: {
      display: "inline-flex",
      alignItems: "center",
      justifyContent: "center",
      width: "22px",
      height: "22px",
      borderRadius: "50%",
      background: "var(--prov-remote-tint)",
      color: "var(--prov-remote)",
      flexShrink: 0
    }
  }, /*#__PURE__*/React.createElement(XIco, {
    n: "circle-pause",
    s: 13
  })), /*#__PURE__*/React.createElement("div", {
    style: {
      flex: 1,
      minWidth: 0
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      fontFamily: "var(--font-mono)",
      fontSize: "12px",
      fontWeight: 600
    }
  }, w.name), /*#__PURE__*/React.createElement("div", {
    style: {
      fontSize: "10.5px",
      color: "var(--text-dim)"
    }
  }, w.desc)), /*#__PURE__*/React.createElement("span", {
    style: {
      fontFamily: "var(--font-mono)",
      fontSize: "9px",
      color: "var(--prov-remote)",
      border: "1px solid var(--prov-remote)",
      borderRadius: "4px",
      padding: "1px 5px"
    }
  }, w.trigger)))), /*#__PURE__*/React.createElement("div", {
    style: {
      marginTop: "12px",
      display: "flex",
      alignItems: "center",
      gap: "8px",
      fontSize: "11px",
      color: "var(--text-dim)"
    }
  }, /*#__PURE__*/React.createElement(XIco, {
    n: "info",
    s: 13
  }), /*#__PURE__*/React.createElement("span", null, "Lanc\xE9 avant un miroir/release public, ou pour valider la portabilit\xE9 cross-OS.")))));
}
})(); } catch (e) { __ds_ns.__errors.push({ path: "design_handoff_nokido/ui_kits/webhub/web-hub-extra.ref.jsx", error: String((e && e.message) || e) }); }

// design_handoff_nokido/ui_kits/webhub/web-hub-screens.ref.jsx
try { (() => {
/* Nokido Web Hub — écrans réels supplémentaires modernisés :
   Launcher (modules), Anatomie Live (organes & flux), RAG Dashboard. */
const {
  Card,
  Badge,
  StatusPill,
  Button,
  ProvenanceBadge,
  TextInput
} = window.NokidoDesignSystem_bdc2ac;
const SIco = window.WIco || (({
  n,
  s = 18
}) => /*#__PURE__*/React.createElement("i", {
  "data-lucide": n,
  style: {
    width: s,
    height: s
  }
}));
const showProv = () => window.__WH_TW ? window.__WH_TW.provenance !== false : true;

/* ====================== Launcher ====================== */
const MODULES0 = [{
  mod: "brain_worker",
  title: "Brain Worker",
  desc: "Cœur de raisonnement",
  status: "running",
  pid: 4821,
  port: null,
  uptime: "2 h 14",
  prov: "local"
}, {
  mod: "web_hub",
  title: "Web Hub",
  desc: "Portail :7400",
  status: "running",
  pid: 4822,
  port: 7400,
  uptime: "2 h 14",
  prov: "local"
}, {
  mod: "hub_mcp",
  title: "Hub MCP",
  desc: "Endpoint :8766",
  status: "running",
  pid: 4830,
  port: 8766,
  uptime: "2 h 13",
  prov: "local"
}, {
  mod: "rag_indexer",
  title: "RAG Indexer",
  desc: "Embeddings bge-m3",
  status: "running",
  pid: 4901,
  port: null,
  uptime: "1 h 58",
  prov: "local"
}, {
  mod: "swarm",
  title: "Swarm",
  desc: "Essaim d'agents",
  status: "stale",
  pid: 5012,
  port: null,
  uptime: "—",
  prov: "hybrid"
}, {
  mod: "deno_edge",
  title: "Deno Edge",
  desc: "Runtime :7401",
  status: "stopped",
  pid: null,
  port: 7401,
  uptime: "—",
  prov: "remote"
}];
const ST = {
  running: {
    label: "running",
    color: "var(--green)",
    bg: "rgba(74,194,139,0.12)"
  },
  stopped: {
    label: "stopped",
    color: "var(--text-dim)",
    bg: "rgba(110,106,130,0.12)"
  },
  stale: {
    label: "stale",
    color: "var(--red)",
    bg: "rgba(242,79,79,0.12)"
  }
};
function Launcher() {
  const [mods, setMods] = React.useState(MODULES0);
  const [logs, setLogs] = React.useState({});
  const set = (mod, patch) => setMods(m => m.map(x => x.mod === mod ? {
    ...x,
    ...patch
  } : x));
  const start = mod => set(mod, {
    status: "running",
    pid: 5000 + Math.floor(Math.random() * 900),
    uptime: "0 s"
  });
  const stop = mod => set(mod, {
    status: "stopped",
    pid: null,
    uptime: "—"
  });
  const toggleLog = mod => setLogs(l => ({
    ...l,
    [mod]: !l[mod]
  }));
  return /*#__PURE__*/React.createElement("div", {
    style: {
      maxWidth: "1000px",
      margin: "0 auto"
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      alignItems: "baseline",
      gap: "10px",
      marginBottom: "16px"
    }
  }, /*#__PURE__*/React.createElement("h2", {
    style: {
      margin: 0,
      fontSize: "13px",
      fontWeight: 700,
      textTransform: "uppercase",
      letterSpacing: "0.6px",
      color: "var(--text-secondary)"
    }
  }, "Modules"), /*#__PURE__*/React.createElement("span", {
    style: {
      fontFamily: "var(--font-mono)",
      fontSize: "11px",
      color: "var(--text-dim)"
    }
  }, mods.filter(m => m.status === "running").length, "/", mods.length, " actifs \xB7 refresh 3s")), /*#__PURE__*/React.createElement("div", {
    style: {
      display: "grid",
      gridTemplateColumns: "1fr 1fr",
      gap: "12px"
    }
  }, mods.map(m => {
    const st = ST[m.status];
    return /*#__PURE__*/React.createElement(Card, {
      key: m.mod
    }, /*#__PURE__*/React.createElement("div", {
      style: {
        display: "flex",
        alignItems: "flex-start",
        justifyContent: "space-between",
        gap: "10px"
      }
    }, /*#__PURE__*/React.createElement("div", null, /*#__PURE__*/React.createElement("div", {
      style: {
        fontSize: "15px",
        fontWeight: 700
      }
    }, m.title), /*#__PURE__*/React.createElement("div", {
      style: {
        fontSize: "12px",
        color: "var(--text-dim)"
      }
    }, m.desc)), /*#__PURE__*/React.createElement("span", {
      style: {
        fontFamily: "var(--font-mono)",
        fontSize: "10px",
        fontWeight: 700,
        textTransform: "uppercase",
        letterSpacing: "0.4px",
        color: st.color,
        background: st.bg,
        padding: "3px 9px",
        borderRadius: "var(--radius-pill)"
      }
    }, st.label)), /*#__PURE__*/React.createElement("div", {
      style: {
        marginTop: "8px",
        display: "flex",
        gap: "10px",
        alignItems: "center",
        fontFamily: "var(--font-mono)",
        fontSize: "11px",
        color: "var(--text-dim)"
      }
    }, m.pid && /*#__PURE__*/React.createElement("span", null, "pid ", m.pid), m.port && /*#__PURE__*/React.createElement("span", null, ":", m.port), m.uptime !== "—" && /*#__PURE__*/React.createElement("span", null, "up ", m.uptime), showProv() && /*#__PURE__*/React.createElement(ProvenanceBadge, {
      origin: m.prov,
      size: "sm",
      style: {
        marginLeft: "auto"
      }
    })), /*#__PURE__*/React.createElement("div", {
      style: {
        marginTop: "12px",
        display: "flex",
        gap: "6px",
        flexWrap: "wrap"
      }
    }, /*#__PURE__*/React.createElement(Button, {
      variant: "success",
      size: "sm",
      disabled: m.status === "running",
      onClick: () => start(m.mod)
    }, "Start"), /*#__PURE__*/React.createElement(Button, {
      variant: "danger",
      size: "sm",
      disabled: m.status === "stopped",
      onClick: () => stop(m.mod)
    }, "Stop"), /*#__PURE__*/React.createElement(Button, {
      variant: "ghost",
      size: "sm",
      icon: /*#__PURE__*/React.createElement(SIco, {
        n: "scroll-text",
        s: 13
      }),
      onClick: () => toggleLog(m.mod)
    }, "Logs"), /*#__PURE__*/React.createElement(Button, {
      variant: "ghost",
      size: "sm",
      icon: /*#__PURE__*/React.createElement(SIco, {
        n: "radio",
        s: 13
      })
    }, "Live")), logs[m.mod] && /*#__PURE__*/React.createElement("pre", {
      style: {
        marginTop: "10px",
        marginBottom: 0,
        background: "var(--bg-0)",
        border: "1px solid var(--border-subtle)",
        borderRadius: "var(--radius-sm)",
        padding: "10px",
        fontSize: "10.5px",
        color: "var(--text-secondary)",
        fontFamily: "var(--font-mono)",
        maxHeight: "120px",
        overflow: "auto",
        whiteSpace: "pre-wrap"
      }
    }, `[${m.mod}] booting ring 0…
[${m.mod}] bind ${m.port ? ":" + m.port : "ipc"} ok
[${m.mod}] health=${m.status} provenance=${m.prov}
[${m.mod}] heartbeat 200 OK`));
  })));
}

/* ====================== Anatomie Live ====================== */
const OPSEC = {
  PARANOID: "var(--green)",
  STANDARD: "var(--cyan)",
  CTF: "var(--yellow)"
};
const HEALTH = {
  active: "var(--green)",
  alive: "var(--cyan)",
  idle: "var(--text-dim)",
  dead: "var(--red)"
};
const ORGANS = {
  "Système nerveux": [{
    label: "Cerveau souverain",
    module: "brain_worker",
    health: "active",
    act: 0.92
  }, {
    label: "Orchestrateur",
    module: "forge_orchestrator",
    health: "active",
    act: 0.78
  }],
  "Mémoire": [{
    label: "RAG / embeddings",
    module: "rag_indexer",
    health: "alive",
    act: 0.54
  }, {
    label: "Historique",
    module: "session_store",
    health: "idle",
    act: 0.12
  }],
  "Perception": [{
    label: "Vision (VLM)",
    module: "perception_vlm",
    health: "idle",
    act: 0.08
  }, {
    label: "Audio",
    module: "audio_in",
    health: "dead",
    act: 0
  }],
  "Routage & action": [{
    label: "Cascade routeur",
    module: "router",
    health: "active",
    act: 0.86
  }, {
    label: "Outils MCP",
    module: "mcp_server",
    health: "alive",
    act: 0.41
  }],
  "Intégrité": [{
    label: "Anneaux",
    module: "integrity_rings",
    health: "alive",
    act: 0.33
  }, {
    label: "Sécurité OPSEC",
    module: "security",
    health: "active",
    act: 0.7
  }]
};
function Anatomy() {
  const [opsec, setOpsec] = React.useState("STANDARD");
  const [killed, setKilled] = React.useState(false);
  const kill = () => {
    setKilled(true);
    setOpsec("PARANOID");
  };
  const stat = (l, v, c) => /*#__PURE__*/React.createElement("div", {
    style: {
      padding: "8px 14px",
      background: "var(--bg-2)",
      border: "1px solid var(--border)",
      borderRadius: "var(--radius-sm)"
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      fontSize: "10px",
      textTransform: "uppercase",
      letterSpacing: "0.4px",
      color: "var(--text-dim)"
    }
  }, l), /*#__PURE__*/React.createElement("div", {
    style: {
      fontFamily: "var(--font-mono)",
      fontSize: "15px",
      fontWeight: 700,
      color: c || "var(--text-primary)"
    }
  }, v));
  return /*#__PURE__*/React.createElement("div", {
    style: {
      maxWidth: "1000px",
      margin: "0 auto"
    }
  }, killed && /*#__PURE__*/React.createElement("div", {
    style: {
      marginBottom: "14px",
      padding: "11px 15px",
      borderRadius: "var(--radius-md)",
      background: "rgba(242,79,79,0.12)",
      border: "1px solid var(--red)",
      color: "var(--red)",
      fontSize: "13px",
      fontWeight: 600,
      display: "flex",
      alignItems: "center",
      gap: "9px"
    }
  }, /*#__PURE__*/React.createElement(SIco, {
    n: "octagon-alert",
    s: 17
  }), "Kill switch activ\xE9 \u2014 tous les outbounds cloud coup\xE9s, OPSEC forc\xE9 PARANOID, lock humain requis."), /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      alignItems: "center",
      gap: "10px",
      flexWrap: "wrap",
      marginBottom: "18px"
    }
  }, stat("msgs / 60s", "142", "var(--purple)"), stat("RAG / 60s", "18", "var(--green)"), stat("services", "5 / 6", "var(--blue)"), /*#__PURE__*/React.createElement("div", {
    style: {
      padding: "8px 14px",
      background: "var(--bg-2)",
      border: `1px solid ${OPSEC[opsec]}`,
      borderRadius: "var(--radius-sm)"
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      fontSize: "10px",
      textTransform: "uppercase",
      letterSpacing: "0.4px",
      color: "var(--text-dim)"
    }
  }, "OPSEC"), /*#__PURE__*/React.createElement("div", {
    style: {
      fontFamily: "var(--font-mono)",
      fontSize: "15px",
      fontWeight: 700,
      color: OPSEC[opsec]
    }
  }, opsec)), /*#__PURE__*/React.createElement("button", {
    onClick: kill,
    disabled: killed,
    style: {
      marginLeft: "auto",
      display: "inline-flex",
      alignItems: "center",
      gap: "7px",
      background: killed ? "var(--bg-3)" : "var(--red)",
      color: killed ? "var(--text-dim)" : "#fff",
      border: "none",
      borderRadius: "var(--radius-sm)",
      padding: "10px 16px",
      fontWeight: 700,
      fontSize: "13px",
      cursor: killed ? "not-allowed" : "pointer",
      boxShadow: killed ? "none" : "0 0 14px rgba(242,79,79,0.4)"
    }
  }, /*#__PURE__*/React.createElement(SIco, {
    n: "octagon-x",
    s: 16
  }), "KILL SWITCH")), /*#__PURE__*/React.createElement("div", {
    style: {
      display: "grid",
      gridTemplateColumns: "repeat(auto-fill, minmax(300px, 1fr))",
      gap: "14px"
    }
  }, Object.entries(ORGANS).map(([system, organs]) => /*#__PURE__*/React.createElement(Card, {
    key: system
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      fontFamily: "var(--font-mono)",
      fontSize: "10px",
      textTransform: "uppercase",
      letterSpacing: "0.6px",
      color: "var(--text-dim)",
      marginBottom: "10px"
    }
  }, system), /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      flexDirection: "column",
      gap: "10px"
    }
  }, organs.map(o => {
    const dead = killed && o.module === "mcp_server";
    const health = dead ? "idle" : o.health;
    const act = dead ? 0.05 : o.act;
    return /*#__PURE__*/React.createElement("div", {
      key: o.module,
      style: {
        display: "flex",
        alignItems: "center",
        gap: "11px"
      }
    }, /*#__PURE__*/React.createElement("span", {
      className: health === "active" || health === "alive" ? "laforge-pulse" : "",
      style: {
        width: "10px",
        height: "10px",
        borderRadius: "50%",
        background: HEALTH[health],
        boxShadow: `0 0 8px ${HEALTH[health]}`,
        flexShrink: 0
      }
    }), /*#__PURE__*/React.createElement("div", {
      style: {
        flex: 1,
        minWidth: 0
      }
    }, /*#__PURE__*/React.createElement("div", {
      style: {
        fontSize: "13px",
        fontWeight: 600
      }
    }, o.label), /*#__PURE__*/React.createElement("div", {
      style: {
        fontFamily: "var(--font-mono)",
        fontSize: "10px",
        color: "var(--text-dim)"
      }
    }, o.module)), /*#__PURE__*/React.createElement("div", {
      style: {
        width: "56px",
        height: "5px",
        borderRadius: "3px",
        background: "var(--bg-4)",
        overflow: "hidden",
        flexShrink: 0
      }
    }, /*#__PURE__*/React.createElement("div", {
      style: {
        width: `${Math.round(act * 100)}%`,
        height: "100%",
        background: HEALTH[health],
        transition: "width var(--motion-base)"
      }
    })));
  }))))));
}

/* ====================== RAG Dashboard ====================== */
const CHUNKS = [{
  title: "Bilan sanguin — mars",
  domain: "sante",
  ring: "gold",
  n: 12
}, {
  title: "Budget mensuel 2026",
  domain: "finance",
  ring: "verified",
  n: 8
}, {
  title: "Notes projet Nokido",
  domain: "dev",
  ring: "verified",
  n: 41
}, {
  title: "Recettes & courses",
  domain: "achat",
  ring: "draft",
  n: 5
}];
function Rag() {
  const [q, setQ] = React.useState("");
  const stat = (l, v, c) => /*#__PURE__*/React.createElement(Card, {
    style: {
      flex: 1
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      fontSize: "10px",
      textTransform: "uppercase",
      letterSpacing: "0.4px",
      color: "var(--text-dim)"
    }
  }, l), /*#__PURE__*/React.createElement("div", {
    style: {
      fontFamily: "var(--font-mono)",
      fontSize: "20px",
      fontWeight: 700,
      color: c || "var(--text-primary)",
      marginTop: "3px"
    }
  }, v));
  return /*#__PURE__*/React.createElement("div", {
    style: {
      maxWidth: "880px",
      margin: "0 auto",
      display: "flex",
      flexDirection: "column",
      gap: "16px"
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      gap: "12px"
    }
  }, stat("Documents", "128", "var(--purple)"), stat("Chunks", "3 412", "var(--blue)"), stat("Modèle", "bge-m3", "var(--green)"), stat("Dimensions", "1024", "var(--cyan)")), /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      gap: "8px",
      alignItems: "flex-end"
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      flex: 1
    }
  }, /*#__PURE__*/React.createElement(TextInput, {
    label: "Recherche s\xE9mantique (locale)",
    placeholder: "Ex : mes d\xE9penses de sant\xE9\u2026",
    icon: /*#__PURE__*/React.createElement(SIco, {
      n: "search",
      s: 15
    }),
    value: q,
    onChange: e => setQ(e.target.value)
  })), /*#__PURE__*/React.createElement(Button, {
    variant: "primary",
    size: "lg",
    icon: /*#__PURE__*/React.createElement(SIco, {
      n: "sparkles",
      s: 15
    })
  }, "Chercher")), /*#__PURE__*/React.createElement(Card, {
    style: {
      background: "var(--bg-1)",
      display: "flex",
      alignItems: "center",
      gap: "10px"
    }
  }, /*#__PURE__*/React.createElement(SIco, {
    n: "download",
    s: 16
  }), /*#__PURE__*/React.createElement("span", {
    style: {
      fontSize: "12.5px",
      color: "var(--text-secondary)"
    }
  }, "Ingestion centralis\xE9e via ", /*#__PURE__*/React.createElement("span", {
    style: {
      fontFamily: "var(--font-mono)",
      color: "var(--text-dim)"
    }
  }, "/api/ingest"), " \u2014 URL ou texte, index\xE9 en local."), showProv() && /*#__PURE__*/React.createElement(ProvenanceBadge, {
    origin: "local",
    size: "sm",
    style: {
      marginLeft: "auto"
    }
  })), /*#__PURE__*/React.createElement("div", null, /*#__PURE__*/React.createElement("div", {
    style: {
      fontFamily: "var(--font-mono)",
      fontSize: "10px",
      textTransform: "uppercase",
      letterSpacing: "0.6px",
      color: "var(--text-dim)",
      margin: "4px 0 8px"
    }
  }, "Documents r\xE9cents"), /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      flexDirection: "column",
      gap: "8px"
    }
  }, CHUNKS.map(c => /*#__PURE__*/React.createElement("div", {
    key: c.title,
    style: {
      display: "flex",
      alignItems: "center",
      gap: "12px",
      padding: "12px 15px",
      background: "var(--bg-2)",
      border: "1px solid var(--border)",
      borderRadius: "var(--radius-md)"
    }
  }, /*#__PURE__*/React.createElement("span", {
    style: {
      display: "inline-flex",
      alignItems: "center",
      justifyContent: "center",
      width: "32px",
      height: "32px",
      borderRadius: "var(--radius-sm)",
      background: `color-mix(in srgb, var(--domain-${c.domain}) 16%, transparent)`,
      color: `var(--domain-${c.domain})`,
      flexShrink: 0
    }
  }, /*#__PURE__*/React.createElement(SIco, {
    n: "file-text",
    s: 16
  })), /*#__PURE__*/React.createElement("div", {
    style: {
      flex: 1,
      minWidth: 0
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      fontSize: "13px",
      fontWeight: 600
    }
  }, c.title), /*#__PURE__*/React.createElement("div", {
    style: {
      fontFamily: "var(--font-mono)",
      fontSize: "10px",
      color: "var(--text-dim)"
    }
  }, c.n, " chunks \xB7 domaine ", c.domain)), showProv() && /*#__PURE__*/React.createElement(ProvenanceBadge, {
    origin: "local",
    ring: c.ring,
    size: "sm"
  }))))));
}
Object.assign(window, {
  LauncherView: Launcher,
  AnatomyView: Anatomy,
  RagView: Rag
});
})(); } catch (e) { __ds_ns.__errors.push({ path: "design_handoff_nokido/ui_kits/webhub/web-hub-screens.ref.jsx", error: String((e && e.message) || e) }); }

// design_handoff_nokido/ui_kits/webhub/web-hub.ref.jsx
try { (() => {
/* Nokido — Web Hub modernisé : recréation du portail réel (:7400) avec le DS.
   Portail de services + Chat (ask) + Event Feed (audit), provenance partout. */
const {
  Card,
  Badge,
  StatusPill,
  Button,
  ProvenanceBadge,
  TextInput,
  Select
} = window.NokidoDesignSystem_bdc2ac;
const WPREF = window.NokidoPrefs;
function WIco({
  n,
  s = 18
}) {
  return /*#__PURE__*/React.createElement("i", {
    "data-lucide": n,
    style: {
      width: s,
      height: s
    }
  });
}

/* Tweaks partagés (lus par les vues ci-dessous). Mis à jour par <WebHub t={…}>. */
let TW = {
  accent: "#774AFF",
  density: "confort",
  provenance: true,
  quicklinks: true,
  mcpPanel: true,
  motion: true
};
const pad = (comfy, compact) => TW.density === "compact" ? compact : comfy;

/* Services réels du hub (dashboard.html) */
const SERVICES = [{
  slug: "chat",
  title: "Chat / Ask",
  desc: "Dialogue multi-fournisseurs",
  icon: "message-square",
  color: "purple",
  prov: "local",
  status: "up",
  target: "/sidebar"
}, {
  slug: "rag",
  title: "RAG Dashboard",
  desc: "Embeddings & recherche locale",
  icon: "database",
  color: "green",
  prov: "local",
  status: "up",
  target: "/rag"
}, {
  slug: "network",
  title: "Network Graph",
  desc: "Graphe de connaissances",
  icon: "share-2",
  color: "blue",
  prov: "local",
  status: "up",
  target: "/network"
}, {
  slug: "mcp_lab",
  title: "MCP Lab",
  desc: "Outils & serveurs MCP",
  icon: "blocks",
  color: "cyan",
  prov: "hybrid",
  status: "up",
  target: "/mcp_lab/"
}, {
  slug: "swarm",
  title: "Swarm",
  desc: "Essaim d'agents",
  icon: "boxes",
  color: "orange",
  prov: "hybrid",
  status: "up",
  target: "/swarm"
}, {
  slug: "debate",
  title: "LLM Debate",
  desc: "Débat contradictoire multi-modèles",
  icon: "messages-square",
  color: "pink",
  prov: "remote",
  status: "up",
  target: "/llm_debate"
}, {
  slug: "anatomy",
  title: "Anatomie Live",
  desc: "Organes & flux en temps réel",
  icon: "activity",
  color: "green",
  prov: "local",
  status: "up",
  target: "/anatomy"
}, {
  slug: "feed",
  title: "Event Feed",
  desc: "Journal d'audit (bus d'événements)",
  icon: "scroll-text",
  color: "yellow",
  prov: "local",
  status: "up",
  target: "/forge/feed"
}, {
  slug: "launcher",
  title: "Launcher",
  desc: "Pilotage des modules",
  icon: "rocket",
  color: "purple",
  prov: "local",
  status: "up",
  target: "/launcher"
}, {
  slug: "reports",
  title: "CTF Reports",
  desc: "Rapports & traces",
  icon: "flag",
  color: "red",
  prov: "local",
  status: "up",
  target: "/reports/",
  ext: true
}, {
  slug: "epistemic",
  title: "Épistémique",
  desc: "Incertitude & calibration",
  icon: "brain-circuit",
  color: "blue",
  prov: "hybrid",
  status: "warn",
  target: "/epistemic"
}, {
  slug: "pipeline",
  title: "Pipeline souverain",
  desc: "CI local-first, cloud en fallback",
  icon: "git-pull-request",
  color: "green",
  prov: "local",
  status: "up",
  target: "/pipeline"
}, {
  slug: "recon",
  title: "Recon",
  desc: "Reconnaissance (non déployé)",
  icon: "radar",
  color: "cyan",
  prov: "local",
  coming: true,
  target: "/recon"
}];
const QUICK = [["Launcher", "launcher"], ["Pipeline", "pipeline"], ["Swarm", "swarm"], ["LLM Debate", "debate"], ["Event Feed", "feed"], ["MCP Lab", "mcp"], ["Network", "network"], ["RAG", "rag"], ["CTF Reports", "reports"], ["Status JSON", "status"]];
const GO = v => {
  if (window.__WH_GO) window.__WH_GO(v);
};
const COLOR_VAR = {
  purple: "--purple",
  blue: "--blue",
  cyan: "--cyan",
  green: "--green",
  yellow: "--yellow",
  orange: "--orange",
  red: "--red",
  pink: "--pink"
};
const SLUG_VIEW = {
  chat: "chat",
  rag: "rag",
  feed: "feed",
  launcher: "launcher",
  reports: "reports",
  epistemic: "epistemic",
  pipeline: "pipeline",
  swarm: "swarm",
  debate: "debate",
  network: "network",
  mcp_lab: "mcp"
};

/* ---------------- Portail ---------------- */
function Portail() {
  return /*#__PURE__*/React.createElement("div", {
    style: {
      maxWidth: "1180px",
      margin: "0 auto"
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      gap: "8px",
      flexWrap: "wrap",
      marginBottom: "18px",
      display: TW.quicklinks ? "flex" : "none"
    }
  }, QUICK.map(([q, v]) => /*#__PURE__*/React.createElement("button", {
    key: q,
    onClick: () => GO(v),
    style: {
      padding: "6px 12px",
      border: "1px solid var(--border)",
      background: "transparent",
      cursor: "pointer",
      borderRadius: "var(--radius-sm)",
      color: "var(--text-secondary)",
      fontSize: "12.5px",
      fontFamily: "var(--font-sans)",
      transition: "all var(--motion-fast)"
    },
    onMouseEnter: e => {
      e.currentTarget.style.borderColor = "var(--purple)";
      e.currentTarget.style.color = "var(--purple)";
    },
    onMouseLeave: e => {
      e.currentTarget.style.borderColor = "var(--border)";
      e.currentTarget.style.color = "var(--text-secondary)";
    }
  }, q))), /*#__PURE__*/React.createElement("div", {
    style: {
      display: "grid",
      gridTemplateColumns: `repeat(auto-fill, minmax(280px, 1fr))`,
      gap: pad("14px", "9px")
    }
  }, SERVICES.map(s => {
    const cvar = `var(${COLOR_VAR[s.color]})`;
    if (s.coming) {
      return /*#__PURE__*/React.createElement("div", {
        key: s.slug,
        style: {
          position: "relative",
          padding: "18px",
          background: "var(--bg-1)",
          border: "1px solid var(--border-subtle)",
          borderRadius: "var(--radius-md)",
          opacity: 0.6
        }
      }, /*#__PURE__*/React.createElement("div", {
        style: {
          display: "flex",
          justifyContent: "space-between",
          alignItems: "flex-start"
        }
      }, /*#__PURE__*/React.createElement("span", {
        style: {
          display: "inline-flex",
          alignItems: "center",
          justifyContent: "center",
          width: "44px",
          height: "44px",
          borderRadius: "var(--radius-sm)",
          background: `color-mix(in srgb, ${cvar} 12%, transparent)`,
          color: cvar,
          opacity: 0.5,
          marginBottom: "10px"
        }
      }, /*#__PURE__*/React.createElement(WIco, {
        n: s.icon,
        s: 22
      })), /*#__PURE__*/React.createElement("span", {
        style: {
          width: "10px",
          height: "10px",
          borderRadius: "50%",
          background: "var(--text-disabled)"
        }
      })), /*#__PURE__*/React.createElement("h3", {
        style: {
          margin: 0,
          fontSize: "16px",
          fontWeight: 700,
          display: "flex",
          alignItems: "center",
          gap: "7px"
        }
      }, s.title, /*#__PURE__*/React.createElement(Badge, {
        color: "dim",
        mono: true
      }, "Bient\xF4t")), /*#__PURE__*/React.createElement("p", {
        style: {
          margin: "4px 0 0",
          fontSize: "12.5px",
          color: "var(--text-dim)"
        }
      }, s.desc), /*#__PURE__*/React.createElement("div", {
        style: {
          marginTop: "14px",
          fontFamily: "var(--font-mono)",
          fontSize: "11px",
          color: "var(--text-disabled)"
        }
      }, s.target, " (non d\xE9ploy\xE9)"));
    }
    return /*#__PURE__*/React.createElement("a", {
      key: s.slug,
      href: "#",
      onClick: e => {
        e.preventDefault();
        GO(SLUG_VIEW[s.slug] || "portail");
      },
      style: {
        display: "block",
        position: "relative",
        padding: "18px",
        background: "var(--bg-2)",
        border: "1px solid var(--border)",
        borderRadius: "var(--radius-md)",
        boxShadow: "var(--shadow-md)",
        textDecoration: "none",
        color: "var(--text-primary)",
        transition: "all var(--motion-base)"
      },
      onMouseEnter: e => {
        e.currentTarget.style.background = "var(--bg-3)";
        e.currentTarget.style.boxShadow = "var(--shadow-glow)";
      },
      onMouseLeave: e => {
        e.currentTarget.style.background = "var(--bg-2)";
        e.currentTarget.style.boxShadow = "var(--shadow-md)";
      }
    }, /*#__PURE__*/React.createElement("div", {
      style: {
        display: "flex",
        justifyContent: "space-between",
        alignItems: "flex-start"
      }
    }, /*#__PURE__*/React.createElement("span", {
      style: {
        display: "inline-flex",
        alignItems: "center",
        justifyContent: "center",
        width: "44px",
        height: "44px",
        borderRadius: "var(--radius-sm)",
        background: `color-mix(in srgb, ${cvar} 16%, transparent)`,
        color: cvar,
        marginBottom: "10px"
      }
    }, /*#__PURE__*/React.createElement(WIco, {
      n: s.icon,
      s: 22
    })), /*#__PURE__*/React.createElement("span", {
      className: "laforge-pulse",
      style: {
        width: "10px",
        height: "10px",
        borderRadius: "50%",
        background: s.status === "up" ? "var(--green)" : s.status === "warn" ? "var(--yellow)" : "var(--red)"
      }
    })), /*#__PURE__*/React.createElement("h3", {
      style: {
        margin: 0,
        fontSize: "16px",
        fontWeight: 700,
        display: "flex",
        alignItems: "center",
        gap: "7px"
      }
    }, s.title, s.ext && /*#__PURE__*/React.createElement(Badge, {
      color: "dim",
      mono: true
    }, "EXT")), /*#__PURE__*/React.createElement("p", {
      style: {
        margin: "4px 0 0",
        fontSize: "12.5px",
        color: "var(--text-secondary)"
      }
    }, s.desc), /*#__PURE__*/React.createElement("div", {
      style: {
        marginTop: "14px",
        display: "flex",
        alignItems: "center",
        gap: "8px"
      }
    }, TW.provenance && /*#__PURE__*/React.createElement(ProvenanceBadge, {
      origin: s.prov,
      size: "sm"
    }), /*#__PURE__*/React.createElement("span", {
      style: {
        marginLeft: "auto",
        fontFamily: "var(--font-mono)",
        fontSize: "11px",
        color: "var(--text-dim)"
      }
    }, s.target)));
  })), /*#__PURE__*/React.createElement("div", {
    style: {
      marginTop: "22px",
      padding: "14px 16px",
      border: "1px solid var(--border-subtle)",
      borderRadius: "var(--radius-md)",
      background: "var(--bg-1)",
      color: "var(--text-secondary)",
      fontSize: "12.5px",
      display: TW.mcpPanel ? "block" : "none"
    }
  }, "MCP endpoint actif : ", /*#__PURE__*/React.createElement("span", {
    style: {
      fontFamily: "var(--font-mono)",
      color: "var(--text-dim)"
    }
  }, "http://127.0.0.1:8766/mcp"), " \xB7 Web Hub sur ", /*#__PURE__*/React.createElement("span", {
    style: {
      fontFamily: "var(--font-mono)",
      color: "var(--text-dim)"
    }
  }, ":7400"), " \xB7 Charte : ", /*#__PURE__*/React.createElement("span", {
    style: {
      fontFamily: "var(--font-mono)",
      color: "var(--purple)"
    }
  }, "styles.css")));
}

/* ---------------- Chat (ask) ---------------- */
const PROVIDERS = [{
  v: "ollama",
  label: "Ollama (local)",
  prov: "local"
}, {
  v: "groq",
  label: "Groq",
  prov: "remote"
}, {
  v: "gemini",
  label: "Gemini",
  prov: "remote"
}, {
  v: "mistral",
  label: "Mistral",
  prov: "remote"
}];
function Chat() {
  const [provider, setProvider] = React.useState("ollama");
  const [input, setInput] = React.useState("");
  const [msgs, setMsgs] = React.useState([{
    role: "sys",
    text: "Nokido Hub v18.3 · Ring 0 · LF1.S.H.1.3.INT"
  }, {
    role: "bot",
    text: "Bonjour. Je tourne en local par défaut — où veux-tu forger aujourd'hui ?",
    prov: "local",
    model: "ollama:mistral",
    lat: "418ms"
  }]);
  const provOf = p => (PROVIDERS.find(x => x.v === p) || PROVIDERS[0]).prov;
  const send = () => {
    const t = input.trim();
    if (!t) return;
    const p = provOf(provider);
    setMsgs(m => [...m, {
      role: "user",
      text: t
    }, {
      role: "bot",
      text: "(réponse simulée) — calcul " + (p === "local" ? "sur ta machine" : "délégué au cloud, anonymisé") + ".",
      prov: p,
      model: provider + (p === "local" ? ":mistral" : ":llama-70b"),
      lat: p === "local" ? "612ms" : "248ms"
    }]);
    setInput("");
  };
  const endRef = React.useRef(null);
  React.useEffect(() => {
    if (endRef.current) endRef.current.scrollTop = endRef.current.scrollHeight;
  });
  return /*#__PURE__*/React.createElement("div", {
    style: {
      maxWidth: "720px",
      margin: "0 auto",
      height: "100%",
      display: "flex",
      flexDirection: "column",
      gap: "12px"
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      alignItems: "center",
      gap: "10px"
    }
  }, /*#__PURE__*/React.createElement("span", {
    style: {
      width: "8px",
      height: "8px",
      borderRadius: "50%",
      background: "var(--green)"
    },
    className: "laforge-pulse"
  }), /*#__PURE__*/React.createElement("span", {
    style: {
      fontWeight: 700
    }
  }, "Chat"), /*#__PURE__*/React.createElement("div", {
    style: {
      marginLeft: "auto",
      width: "180px"
    }
  }, /*#__PURE__*/React.createElement(Select, {
    value: provider,
    onChange: e => setProvider(e.target.value),
    options: PROVIDERS.map(p => ({
      value: p.v,
      label: p.label
    }))
  }))), /*#__PURE__*/React.createElement("div", {
    ref: endRef,
    style: {
      flex: 1,
      overflowY: "auto",
      display: "flex",
      flexDirection: "column",
      gap: "10px",
      padding: "4px"
    }
  }, msgs.map((m, i) => /*#__PURE__*/React.createElement("div", {
    key: i,
    style: {
      alignSelf: m.role === "user" ? "flex-end" : m.role === "sys" ? "center" : "flex-start",
      maxWidth: m.role === "sys" ? "100%" : "86%"
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      padding: m.role === "sys" ? "5px 10px" : "9px 13px",
      borderRadius: "var(--radius-md)",
      fontSize: m.role === "sys" ? "11px" : "13px",
      lineHeight: 1.55,
      fontFamily: m.role === "sys" ? "var(--font-mono)" : "var(--font-sans)",
      background: m.role === "user" ? "rgba(119,74,255,0.12)" : m.role === "sys" ? "var(--prov-local-tint)" : "var(--bg-2)",
      border: `1px solid ${m.role === "user" ? "rgba(119,74,255,0.3)" : m.role === "sys" ? "var(--border-subtle)" : "var(--border)"}`,
      color: m.role === "sys" ? "var(--text-dim)" : "var(--text-primary)",
      textAlign: m.role === "sys" ? "center" : "left"
    }
  }, m.text), m.role === "bot" && m.prov && /*#__PURE__*/React.createElement("div", {
    style: {
      marginTop: "5px"
    }
  }, /*#__PURE__*/React.createElement(ProvenanceBadge, {
    origin: m.prov,
    ring: "verified",
    size: "sm",
    detail: `${m.model} · ${m.lat}`
  }))))), /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      gap: "8px",
      alignItems: "flex-end"
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      flex: 1
    }
  }, /*#__PURE__*/React.createElement(TextInput, {
    multiline: true,
    rows: 1,
    placeholder: "Message \xE0 LaForge\u2026",
    value: input,
    onChange: e => setInput(e.target.value)
  })), /*#__PURE__*/React.createElement(Button, {
    variant: "primary",
    size: "lg",
    onClick: send,
    icon: /*#__PURE__*/React.createElement(WIco, {
      n: "send-horizontal",
      s: 16
    })
  }, "Envoyer")), /*#__PURE__*/React.createElement("div", {
    style: {
      fontFamily: "var(--font-mono)",
      fontSize: "10px",
      color: "var(--text-dim)",
      textAlign: "center"
    }
  }, "Header : LF1.S.H.1.3.INT \xB7 ingest centralis\xE9 via /api/ingest"));
}

/* ---------------- Event Feed (audit) ---------------- */
const TOPIC_COLORS = {
  tool: "#ff7b72",
  rpc: "#79c0ff",
  silo: "#7ee787",
  skill: "#ffa657",
  debate: "#d2a8ff",
  agent: "#f2cc60",
  system: "#8b949e"
};
const EVENTS = [{
  ts: "14:32:08",
  agent: "ROUTER",
  topic: "rpc.dispatch",
  data: '{"provider":"ollama","tokens":812}'
}, {
  ts: "14:32:08",
  agent: "BRAIN",
  topic: "silo.reason",
  data: '{"silo":"finance","depth":3}'
}, {
  ts: "14:32:07",
  agent: "ASK",
  topic: "tool.call",
  data: '{"name":"ask","local":true}'
}, {
  ts: "14:31:54",
  agent: "RAG",
  topic: "skill.ingest",
  data: '{"domain":"sante","tags":["bilan"]}'
}, {
  ts: "14:31:40",
  agent: "SWARM",
  topic: "agent.spawn",
  data: '{"role":"critic","ring":2}'
}, {
  ts: "14:30:12",
  agent: "DEBATE",
  topic: "debate.round",
  data: '{"models":["groq","mistral"],"round":2}'
}, {
  ts: "14:29:55",
  agent: "SYSTEM",
  topic: "system.health",
  data: '{"opsec":"STANDARD","up":true}'
}];
function Feed() {
  const [filter, setFilter] = React.useState("");
  const rows = EVENTS.filter(e => !filter || (e.topic + e.agent).toLowerCase().includes(filter.toLowerCase()));
  return /*#__PURE__*/React.createElement("div", {
    style: {
      maxWidth: "1000px",
      margin: "0 auto"
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      alignItems: "center",
      gap: "10px",
      marginBottom: "16px"
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      width: "280px"
    }
  }, /*#__PURE__*/React.createElement(TextInput, {
    placeholder: "Filtrer par topic / agent\u2026",
    icon: /*#__PURE__*/React.createElement(WIco, {
      n: "filter",
      s: 15
    }),
    value: filter,
    onChange: e => setFilter(e.target.value)
  })), /*#__PURE__*/React.createElement(Badge, {
    color: "green"
  }, /*#__PURE__*/React.createElement("span", {
    className: "laforge-pulse",
    style: {
      display: "inline-block",
      width: "6px",
      height: "6px",
      borderRadius: "50%",
      background: "currentColor",
      marginRight: "5px"
    }
  }), "Live \xB7 2s"), /*#__PURE__*/React.createElement("span", {
    style: {
      marginLeft: "auto",
      fontFamily: "var(--font-mono)",
      fontSize: "11px",
      color: "var(--text-dim)"
    }
  }, rows.length, " \xE9v\xE9nements \xB7 bus d'audit")), /*#__PURE__*/React.createElement(Card, {
    style: {
      padding: 0,
      overflow: "hidden"
    }
  }, rows.map((e, i) => {
    const pre = e.topic.split(".")[0];
    const tc = TOPIC_COLORS[pre] || "var(--text-dim)";
    return /*#__PURE__*/React.createElement("div", {
      key: i,
      style: {
        display: "flex",
        gap: "14px",
        alignItems: "center",
        padding: "9px 14px",
        borderBottom: i < rows.length - 1 ? "1px solid var(--border-subtle)" : "none",
        fontFamily: "var(--font-mono)",
        fontSize: "12px"
      }
    }, /*#__PURE__*/React.createElement("span", {
      style: {
        color: "var(--text-dim)",
        minWidth: "62px"
      }
    }, e.ts), /*#__PURE__*/React.createElement("span", {
      style: {
        color: "var(--blue)",
        fontWeight: 700,
        minWidth: "72px"
      }
    }, e.agent), /*#__PURE__*/React.createElement("span", {
      style: {
        color: tc,
        fontWeight: 700,
        minWidth: "120px"
      }
    }, e.topic), /*#__PURE__*/React.createElement("span", {
      style: {
        color: "var(--text-secondary)",
        overflow: "hidden",
        textOverflow: "ellipsis",
        whiteSpace: "nowrap"
      }
    }, e.data));
  }), rows.length === 0 && /*#__PURE__*/React.createElement("div", {
    style: {
      padding: "26px",
      textAlign: "center",
      color: "var(--text-dim)",
      fontSize: "12px"
    }
  }, "Aucun \xE9v\xE9nement correspondant.")));
}
function WebHub({
  t
}) {
  if (t) {
    TW = t;
    window.__WH_TW = t;
  }
  const [view, setView] = React.useState("portail");
  React.useEffect(() => {
    window.__WH_GO = setView;
  }, []);
  const [theme, setTheme] = React.useState(() => WPREF ? WPREF.get("theme", "dark") : "dark");
  React.useEffect(() => {
    if (window.lucide) lucide.createIcons();
  });
  const cycleTheme = () => {
    const n = WPREF ? WPREF.cycleTheme() : theme;
    setTheme(n);
  };
  const themeIcon = {
    dark: "moon",
    light: "sun",
    auto: "monitor"
  }[theme] || "moon";
  const TABS = [["portail", "Portail", "layout-grid"], ["chat", "Chat", "message-square"], ["launcher", "Launcher", "rocket"], ["anatomy", "Anatomie", "activity"], ["network", "Network", "share-2"], ["mcp", "MCP Lab", "blocks"], ["rag", "RAG", "database"], ["feed", "Feed", "scroll-text"]];
  return /*#__PURE__*/React.createElement("div", {
    style: {
      height: "100vh",
      display: "flex",
      flexDirection: "column",
      background: "var(--bg-0)",
      color: "var(--text-primary)",
      ["--purple"]: TW.accent,
      ["--accent"]: TW.accent,
      ["--tint-purple"]: `color-mix(in srgb, ${TW.accent} 16%, transparent)`
    }
  }, !TW.motion && /*#__PURE__*/React.createElement("style", null, `.laforge-pulse{animation:none !important;}`), /*#__PURE__*/React.createElement("header", {
    style: {
      display: "flex",
      alignItems: "center",
      gap: "14px",
      padding: "12px 22px",
      background: "var(--bg-1)",
      borderBottom: "1px solid var(--border-subtle)",
      flexShrink: 0
    }
  }, /*#__PURE__*/React.createElement("svg", {
    width: "26",
    height: "26",
    viewBox: "0 0 64 64",
    fill: "none",
    style: {
      flexShrink: 0
    }
  }, /*#__PURE__*/React.createElement("defs", null, /*#__PURE__*/React.createElement("linearGradient", {
    id: "whBolt",
    x1: "26",
    y1: "12",
    x2: "40",
    y2: "40",
    gradientUnits: "userSpaceOnUse"
  }, /*#__PURE__*/React.createElement("stop", {
    offset: "0",
    stopColor: "#FFE070"
  }), /*#__PURE__*/React.createElement("stop", {
    offset: "1",
    stopColor: "#FFC22D"
  }))), /*#__PURE__*/React.createElement("g", {
    stroke: "#15121F",
    strokeWidth: "2.4",
    strokeLinejoin: "round"
  }, /*#__PURE__*/React.createElement("path", {
    d: "M6 35 L20 31 H48 q4 0 4 3.5 Q52 39 47 39 H39 q-3 0 -4 3 l-1.5 3 H27 q-1 -3 -4 -3 H15 Q6 42 6 35 Z",
    fill: "#9A90BC"
  }), /*#__PURE__*/React.createElement("path", {
    d: "M28 45 h8 l-1.5 5 h-5 Z",
    fill: "#6F6498"
  }), /*#__PURE__*/React.createElement("path", {
    d: "M17 50 H47 l3 6 H14 Z",
    fill: "#9A90BC"
  })), /*#__PURE__*/React.createElement("g", null, /*#__PURE__*/React.createElement("rect", {
    x: "4",
    y: "29",
    width: "23",
    height: "5",
    rx: "2.5",
    fill: "#C77D4A",
    stroke: "#15121F",
    strokeWidth: "2.4",
    strokeLinejoin: "round"
  }), /*#__PURE__*/React.createElement("rect", {
    x: "25",
    y: "21",
    width: "11",
    height: "21",
    rx: "3",
    fill: "#B7BCD2",
    stroke: "#15121F",
    strokeWidth: "2.4",
    strokeLinejoin: "round"
  }), /*#__PURE__*/React.createElement("rect", {
    x: "27.5",
    y: "24",
    width: "5.5",
    height: "6",
    rx: "1.5",
    fill: "#D9DCE8"
  })), /*#__PURE__*/React.createElement("path", {
    d: "M31 41 L40 26 H34 L42 11 L30 28 H36 Z",
    fill: "url(#whBolt)",
    stroke: "#15121F",
    strokeWidth: "2",
    strokeLinejoin: "round"
  })), /*#__PURE__*/React.createElement("span", {
    style: {
      fontWeight: 700,
      fontSize: "16px",
      letterSpacing: "0.3px"
    }
  }, "Nokido Hub"), /*#__PURE__*/React.createElement("span", {
    style: {
      fontFamily: "var(--font-mono)",
      fontSize: "11px",
      color: "var(--text-dim)",
      border: "1px solid var(--border)",
      borderRadius: "var(--radius-sm)",
      padding: "2px 8px"
    }
  }, "v18.3"), /*#__PURE__*/React.createElement("nav", {
    style: {
      display: "flex",
      gap: "4px",
      marginLeft: "12px"
    }
  }, TABS.map(([id, label, icon]) => {
    const on = view === id;
    return /*#__PURE__*/React.createElement("button", {
      key: id,
      onClick: () => setView(id),
      style: {
        display: "inline-flex",
        alignItems: "center",
        gap: "7px",
        padding: "6px 12px",
        borderRadius: "var(--radius-sm)",
        border: "none",
        cursor: "pointer",
        fontFamily: "var(--font-sans)",
        fontSize: "13px",
        fontWeight: on ? 600 : 500,
        background: on ? "var(--bg-3)" : "transparent",
        color: on ? "var(--text-primary)" : "var(--text-secondary)"
      }
    }, /*#__PURE__*/React.createElement(WIco, {
      n: icon,
      s: 15
    }), label);
  })), /*#__PURE__*/React.createElement("div", {
    style: {
      marginLeft: "auto",
      display: "flex",
      alignItems: "center",
      gap: "10px"
    }
  }, /*#__PURE__*/React.createElement("button", {
    onClick: cycleTheme,
    title: `Thème : ${theme}`,
    "aria-label": "Th\xE8me",
    style: {
      display: "inline-flex",
      alignItems: "center",
      justifyContent: "center",
      width: "32px",
      height: "32px",
      borderRadius: "var(--radius-sm)",
      border: "1px solid var(--border)",
      background: "transparent",
      color: "var(--text-secondary)",
      cursor: "pointer"
    }
  }, /*#__PURE__*/React.createElement(WIco, {
    n: themeIcon,
    s: 15
  })), /*#__PURE__*/React.createElement("a", {
    href: "../login/index.html",
    title: "Se d\xE9connecter",
    "aria-label": "Se d\xE9connecter",
    style: {
      display: "inline-flex",
      alignItems: "center",
      gap: "7px",
      height: "32px",
      padding: "0 11px",
      borderRadius: "var(--radius-sm)",
      border: "1px solid var(--border)",
      background: "transparent",
      color: "var(--text-secondary)",
      textDecoration: "none",
      fontSize: "12.5px",
      fontFamily: "var(--font-sans)",
      transition: "all var(--motion-fast)"
    },
    onMouseEnter: e => {
      e.currentTarget.style.borderColor = "var(--red)";
      e.currentTarget.style.color = "var(--red)";
    },
    onMouseLeave: e => {
      e.currentTarget.style.borderColor = "var(--border)";
      e.currentTarget.style.color = "var(--text-secondary)";
    }
  }, /*#__PURE__*/React.createElement(WIco, {
    n: "log-out",
    s: 14
  }), "D\xE9connexion"), /*#__PURE__*/React.createElement("span", {
    style: {
      fontFamily: "var(--font-mono)",
      fontSize: "11px",
      color: "var(--text-dim)"
    }
  }, "Web Hub :7400"))), /*#__PURE__*/React.createElement("main", {
    style: {
      flex: 1,
      overflowY: "auto",
      padding: pad("24px 22px", "14px 16px")
    }
  }, view === "portail" && /*#__PURE__*/React.createElement(Portail, null), view === "chat" && /*#__PURE__*/React.createElement(Chat, null), view === "launcher" && /*#__PURE__*/React.createElement(window.LauncherView, null), view === "anatomy" && /*#__PURE__*/React.createElement(window.AnatomyView, null), view === "rag" && /*#__PURE__*/React.createElement(window.RagView, null), view === "feed" && /*#__PURE__*/React.createElement(Feed, null), view === "network" && /*#__PURE__*/React.createElement(window.NetworkView, null), view === "mcp" && /*#__PURE__*/React.createElement(window.McpLabView, null), view === "reports" && /*#__PURE__*/React.createElement(window.ReportsView, null), view === "status" && /*#__PURE__*/React.createElement(window.StatusView, null), view === "pipeline" && /*#__PURE__*/React.createElement(window.PipelineView, null), view === "swarm" && /*#__PURE__*/React.createElement(window.SwarmView, null), view === "debate" && /*#__PURE__*/React.createElement(window.DebateView, null), view === "epistemic" && /*#__PURE__*/React.createElement(window.RagView, null)));
}
Object.assign(window, {
  WebHub
});
})(); } catch (e) { __ds_ns.__errors.push({ path: "design_handoff_nokido/ui_kits/webhub/web-hub.ref.jsx", error: String((e && e.message) || e) }); }

// ui_kits/composer/composer-app.ref.jsx
try { (() => {
/* Nokido — Composer son app : l'utilisateur compose SA vue à partir des sections.
   Catalogue (gauche) → ta vue (droite) ; épingler, masquer, réordonner. */
const {
  Button,
  Badge,
  ModuleCard,
  ProvenanceBadge,
  SovereigntyGauge
} = window.NokidoDesignSystem_bdc2ac;
function CIco({
  n,
  s = 18
}) {
  return /*#__PURE__*/React.createElement("i", {
    "data-lucide": n,
    style: {
      width: s,
      height: s
    }
  });
}
const CATALOG = [{
  id: "sante",
  domain: "sante",
  title: "Santé",
  desc: "Suivi, rappels, données sensibles",
  icon: "heart-pulse",
  provenance: "local"
}, {
  id: "domotique",
  domain: "domotique",
  title: "Domotique",
  desc: "Hub maison, scènes, local-first",
  icon: "house",
  provenance: "local"
}, {
  id: "transport",
  domain: "transport",
  title: "Transport",
  desc: "Trajets, mobilité, temps réel",
  icon: "route",
  provenance: "hybrid"
}, {
  id: "finance",
  domain: "finance",
  title: "Finance",
  desc: "Comptes, budgets, traçabilité",
  icon: "wallet",
  provenance: "local"
}, {
  id: "loisir",
  domain: "loisir",
  title: "Loisir",
  desc: "Sorties, médias, agenda",
  icon: "compass",
  provenance: "hybrid"
}, {
  id: "achat",
  domain: "achat",
  title: "Achat",
  desc: "Comparaison neutre, suivi prix",
  icon: "shopping-cart",
  provenance: "remote"
}, {
  id: "creation",
  domain: "creation",
  title: "Création",
  desc: "Texte, image, son, code",
  icon: "sparkles",
  provenance: "hybrid"
}, {
  id: "dev",
  domain: "dev",
  title: "Dev",
  desc: "Code, automatisations, skills",
  icon: "terminal",
  provenance: "local"
}, {
  id: "travail",
  domain: "travail",
  title: "Travail",
  desc: "Focus, tâches, documents",
  icon: "briefcase",
  provenance: "local"
}, {
  id: "energie",
  domain: "energie",
  title: "Énergie",
  desc: "Conso, sobriété, pilotage",
  icon: "zap",
  provenance: "local"
}, {
  id: "famille",
  domain: "famille",
  title: "Famille",
  desc: "Agenda commun, partage",
  icon: "users",
  provenance: "hybrid"
}, {
  id: "voyage",
  domain: "voyage",
  title: "Voyage",
  desc: "Itinéraires, découverte",
  icon: "plane",
  provenance: "hybrid"
}];
function CatalogRow({
  mod,
  onAdd
}) {
  const accent = `var(--domain-${mod.domain})`;
  return /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      alignItems: "center",
      gap: "11px",
      padding: "9px 11px",
      background: "var(--bg-2)",
      border: "1px solid var(--border)",
      borderRadius: "var(--radius-sm)"
    }
  }, /*#__PURE__*/React.createElement("span", {
    style: {
      display: "inline-flex",
      alignItems: "center",
      justifyContent: "center",
      width: "32px",
      height: "32px",
      borderRadius: "var(--radius-sm)",
      background: `color-mix(in srgb, ${accent} 16%, transparent)`,
      color: accent,
      flexShrink: 0
    }
  }, /*#__PURE__*/React.createElement(CIco, {
    n: mod.icon,
    s: 17
  })), /*#__PURE__*/React.createElement("div", {
    style: {
      flex: 1,
      minWidth: 0
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      fontSize: "12.5px",
      fontWeight: 600
    }
  }, mod.title), /*#__PURE__*/React.createElement("div", {
    style: {
      fontSize: "10.5px",
      color: "var(--text-dim)",
      whiteSpace: "nowrap",
      overflow: "hidden",
      textOverflow: "ellipsis"
    }
  }, mod.desc)), /*#__PURE__*/React.createElement("button", {
    onClick: () => onAdd(mod.id),
    "aria-label": "Ajouter",
    style: {
      display: "inline-flex",
      alignItems: "center",
      justifyContent: "center",
      width: "28px",
      height: "28px",
      borderRadius: "var(--radius-sm)",
      border: "1px solid var(--border)",
      background: "transparent",
      color: "var(--purple)",
      cursor: "pointer",
      flexShrink: 0
    }
  }, /*#__PURE__*/React.createElement(CIco, {
    n: "plus",
    s: 16
  })));
}
function ComposerApp() {
  const [active, setActive] = React.useState(["sante", "domotique", "transport", "creation"]);
  const [pinned, setPinned] = React.useState({
    sante: true,
    domotique: true
  });
  React.useEffect(() => {
    if (window.lucide) lucide.createIcons();
  });
  const byId = id => CATALOG.find(m => m.id === id);
  const inCatalog = CATALOG.filter(m => !active.includes(m.id));
  const add = id => setActive(a => a.includes(id) ? a : [...a, id]);
  const remove = id => {
    setActive(a => a.filter(x => x !== id));
    setPinned(p => {
      const n = {
        ...p
      };
      delete n[id];
      return n;
    });
  };
  const togglePin = id => setPinned(p => ({
    ...p,
    [id]: !p[id]
  }));
  const move = (id, dir) => setActive(a => {
    const i = a.indexOf(id);
    const j = i + dir;
    if (j < 0 || j >= a.length) return a;
    const n = [...a];
    [n[i], n[j]] = [n[j], n[i]];
    return n;
  });

  // pinned first
  const ordered = [...active].sort((x, y) => (pinned[y] ? 1 : 0) - (pinned[x] ? 1 : 0));
  const localCount = active.filter(id => byId(id).provenance === "local").length;
  const localPct = active.length ? Math.round(localCount / active.length * 100) : 0;
  return /*#__PURE__*/React.createElement("div", {
    style: {
      display: "grid",
      gridTemplateColumns: "300px 1fr",
      height: "100vh",
      background: "var(--bg-0)",
      color: "var(--text-primary)"
    }
  }, /*#__PURE__*/React.createElement("aside", {
    style: {
      background: "var(--bg-1)",
      borderRight: "1px solid var(--border-subtle)",
      display: "flex",
      flexDirection: "column",
      minHeight: 0
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      padding: "16px 16px 12px",
      borderBottom: "1px solid var(--border-subtle)"
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      fontSize: "13px",
      fontWeight: 700
    }
  }, "Catalogue"), /*#__PURE__*/React.createElement("div", {
    style: {
      fontSize: "11px",
      color: "var(--text-dim)"
    }
  }, inCatalog.length, " sections disponibles")), /*#__PURE__*/React.createElement("div", {
    style: {
      flex: 1,
      overflowY: "auto",
      padding: "12px",
      display: "flex",
      flexDirection: "column",
      gap: "8px"
    }
  }, inCatalog.map(m => /*#__PURE__*/React.createElement(CatalogRow, {
    key: m.id,
    mod: m,
    onAdd: add
  })), inCatalog.length === 0 && /*#__PURE__*/React.createElement("div", {
    style: {
      padding: "20px",
      textAlign: "center",
      color: "var(--text-dim)",
      fontSize: "12px"
    }
  }, "Toutes les sections sont dans ta vue."))), /*#__PURE__*/React.createElement("main", {
    style: {
      display: "flex",
      flexDirection: "column",
      minWidth: 0
    }
  }, /*#__PURE__*/React.createElement("header", {
    style: {
      height: "var(--topbar-h)",
      borderBottom: "1px solid var(--border-subtle)",
      background: "var(--bg-1)",
      display: "flex",
      alignItems: "center",
      padding: "0 22px",
      gap: "12px",
      flexShrink: 0
    }
  }, /*#__PURE__*/React.createElement("div", null, /*#__PURE__*/React.createElement("div", {
    style: {
      fontSize: "15px",
      fontWeight: 700,
      lineHeight: 1.1
    }
  }, "Compose ton app"), /*#__PURE__*/React.createElement("div", {
    style: {
      fontSize: "11px",
      color: "var(--text-dim)",
      fontFamily: "var(--font-mono)"
    }
  }, "\xE9pingle \xB7 masque \xB7 r\xE9ordonne tes sections")), /*#__PURE__*/React.createElement("div", {
    style: {
      marginLeft: "auto",
      display: "flex",
      alignItems: "center",
      gap: "12px"
    }
  }, /*#__PURE__*/React.createElement(SovereigntyGauge, {
    local: localPct,
    label: null,
    showLegend: false,
    height: 7,
    style: {
      width: "120px"
    }
  }), /*#__PURE__*/React.createElement("span", {
    style: {
      fontFamily: "var(--font-mono)",
      fontSize: "11px",
      color: "var(--prov-local)"
    }
  }, localPct, "% local"), /*#__PURE__*/React.createElement(Button, {
    variant: "primary",
    size: "sm",
    icon: /*#__PURE__*/React.createElement(CIco, {
      n: "check",
      s: 14
    })
  }, "Enregistrer"))), /*#__PURE__*/React.createElement("div", {
    style: {
      flex: 1,
      overflowY: "auto",
      padding: "22px 24px"
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      alignItems: "baseline",
      gap: "10px",
      marginBottom: "14px"
    }
  }, /*#__PURE__*/React.createElement("h2", {
    style: {
      margin: 0,
      fontSize: "13px",
      fontWeight: 700,
      textTransform: "uppercase",
      letterSpacing: "0.6px",
      color: "var(--text-secondary)"
    }
  }, "Ta vue"), /*#__PURE__*/React.createElement("span", {
    style: {
      fontFamily: "var(--font-mono)",
      fontSize: "11px",
      color: "var(--text-dim)"
    }
  }, active.length, " sections \xB7 ", Object.values(pinned).filter(Boolean).length, " \xE9pingl\xE9es")), active.length === 0 ? /*#__PURE__*/React.createElement("div", {
    style: {
      padding: "50px",
      textAlign: "center",
      color: "var(--text-dim)",
      border: "1px dashed var(--border)",
      borderRadius: "var(--radius-md)"
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      marginBottom: "8px"
    }
  }, /*#__PURE__*/React.createElement(CIco, {
    n: "layout-grid",
    s: 26
  })), "Ajoute des sections depuis le catalogue pour composer ton app.") : /*#__PURE__*/React.createElement("div", {
    style: {
      display: "grid",
      gridTemplateColumns: "repeat(auto-fill, minmax(232px, 1fr))",
      gap: "14px"
    }
  }, ordered.map(id => {
    const m = byId(id);
    return /*#__PURE__*/React.createElement("div", {
      key: id,
      style: {
        position: "relative"
      }
    }, /*#__PURE__*/React.createElement(ModuleCard, {
      domain: m.domain,
      title: m.title,
      desc: m.desc,
      icon: /*#__PURE__*/React.createElement(CIco, {
        n: m.icon,
        s: 22
      }),
      provenance: m.provenance,
      pinned: !!pinned[id]
    }), /*#__PURE__*/React.createElement("div", {
      style: {
        display: "flex",
        gap: "5px",
        marginTop: "8px"
      }
    }, /*#__PURE__*/React.createElement(CtrlBtn, {
      icon: pinned[id] ? "pin-off" : "pin",
      label: pinned[id] ? "Désépingler" : "Épingler",
      active: pinned[id],
      onClick: () => togglePin(id)
    }), /*#__PURE__*/React.createElement(CtrlBtn, {
      icon: "arrow-up",
      onClick: () => move(id, -1)
    }), /*#__PURE__*/React.createElement(CtrlBtn, {
      icon: "arrow-down",
      onClick: () => move(id, 1)
    }), /*#__PURE__*/React.createElement(CtrlBtn, {
      icon: "eye-off",
      label: "Masquer",
      onClick: () => remove(id),
      danger: true
    })));
  })))));
}
function CtrlBtn({
  icon,
  label,
  onClick,
  active,
  danger
}) {
  return /*#__PURE__*/React.createElement("button", {
    onClick: onClick,
    title: label,
    style: {
      display: "inline-flex",
      alignItems: "center",
      gap: "6px",
      padding: label ? "5px 9px" : "5px",
      borderRadius: "var(--radius-sm)",
      cursor: "pointer",
      fontFamily: "var(--font-sans)",
      fontSize: "11px",
      border: `1px solid ${active ? "var(--purple)" : "var(--border)"}`,
      background: active ? "var(--tint-purple)" : "transparent",
      color: danger ? "var(--text-secondary)" : active ? "var(--purple)" : "var(--text-secondary)"
    }
  }, /*#__PURE__*/React.createElement(InlineIcon, {
    name: icon
  }), label);
}

// Inline SVG icons (React-owned — never mutated by lucide.createIcons)
const ICON_PATHS = {
  pin: ["M12 17v5", "M9 10.76a2 2 0 0 1-1.11 1.79l-1.78.9A2 2 0 0 0 5 15.24V16a1 1 0 0 0 1 1h12a1 1 0 0 0 1-1v-.76a2 2 0 0 0-1.11-1.79l-1.78-.9A2 2 0 0 1 15 10.76V7a1 1 0 0 1 1-1 2 2 0 0 0 0-4H8a2 2 0 0 0 0 4 1 1 0 0 1 1 1z"],
  "pin-off": ["M12 17v5", "M15 9.34V7a1 1 0 0 1 1-1 2 2 0 0 0 0-4H7.89", "M9 9v1.76a2 2 0 0 1-1.11 1.79l-1.78.9A2 2 0 0 0 5 15.24V16a1 1 0 0 0 1 1h11", "m2 2 20 20"],
  "arrow-up": ["m5 12 7-7 7 7", "M12 19V5"],
  "arrow-down": ["M12 5v14", "m19 12-7 7-7-7"],
  "eye-off": ["M10.73 5.08A10.43 10.43 0 0 1 12 5c5 0 9 4 10 7a13.16 13.16 0 0 1-1.67 2.68", "M6.61 6.61A13.5 13.5 0 0 0 2 12c1 3 5 7 10 7a9.7 9.7 0 0 0 5.39-1.61", "M9.88 9.88a3 3 0 1 0 4.24 4.24", "m2 2 20 20"]
};
function InlineIcon({
  name,
  size = 13
}) {
  const paths = ICON_PATHS[name] || [];
  return /*#__PURE__*/React.createElement("svg", {
    width: size,
    height: size,
    viewBox: "0 0 24 24",
    fill: "none",
    stroke: "currentColor",
    strokeWidth: "2",
    strokeLinecap: "round",
    strokeLinejoin: "round",
    style: {
      flexShrink: 0
    }
  }, paths.map((d, i) => /*#__PURE__*/React.createElement("path", {
    key: i,
    d: d
  })));
}
Object.assign(window, {
  ComposerApp
});
})(); } catch (e) { __ds_ns.__errors.push({ path: "ui_kits/composer/composer-app.ref.jsx", error: String((e && e.message) || e) }); }

// ui_kits/hub/hub-shell.ref.jsx
try { (() => {
/* Nokido Hub — coquille : sidebar souveraine + topbar avec jauge & persona */
const {
  SovereigntyGauge,
  Badge,
  ProvenanceBadge
} = window.NokidoDesignSystem_bdc2ac;
const NAV = [{
  id: "accueil",
  label: "Accueil",
  icon: "layout-grid"
}, {
  id: "cap",
  label: "Intention longue",
  icon: "target"
}, {
  id: "federation",
  label: "Fédération",
  icon: "share-2"
}, {
  id: "maison",
  label: "Maison",
  icon: "house"
}, {
  id: "persona",
  label: "Mémoire persona",
  icon: "brain"
}, {
  id: "souverainete",
  label: "Souveraineté",
  icon: "shield-check"
}];
function Ico({
  n,
  s = 18
}) {
  return /*#__PURE__*/React.createElement("i", {
    "data-lucide": n,
    style: {
      width: s,
      height: s
    }
  });
}
function HubSidebar({
  active,
  onNav,
  local
}) {
  return /*#__PURE__*/React.createElement("aside", {
    style: {
      width: "var(--sidebar-w)",
      background: "var(--bg-1)",
      borderRight: "1px solid var(--border-subtle)",
      display: "flex",
      flexDirection: "column",
      flexShrink: 0
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      alignItems: "center",
      gap: "8px",
      padding: "14px 16px",
      borderBottom: "1px solid var(--border-subtle)"
    }
  }, /*#__PURE__*/React.createElement("svg", {
    width: "26",
    height: "26",
    viewBox: "0 0 64 64",
    fill: "none",
    style: {
      flexShrink: 0
    }
  }, /*#__PURE__*/React.createElement("defs", null, /*#__PURE__*/React.createElement("linearGradient", {
    id: "lfBolt",
    x1: "26",
    y1: "12",
    x2: "40",
    y2: "40",
    gradientUnits: "userSpaceOnUse"
  }, /*#__PURE__*/React.createElement("stop", {
    offset: "0",
    stopColor: "#FFE070"
  }), /*#__PURE__*/React.createElement("stop", {
    offset: "1",
    stopColor: "#FFC22D"
  }))), /*#__PURE__*/React.createElement("g", {
    stroke: "#15121F",
    strokeWidth: "2.4",
    strokeLinejoin: "round"
  }, /*#__PURE__*/React.createElement("path", {
    d: "M6 35 L20 31 H48 q4 0 4 3.5 Q52 39 47 39 H39 q-3 0 -4 3 l-1.5 3 H27 q-1 -3 -4 -3 H15 Q6 42 6 35 Z",
    fill: "#9A90BC"
  }), /*#__PURE__*/React.createElement("path", {
    d: "M28 45 h8 l-1.5 5 h-5 Z",
    fill: "#6F6498"
  }), /*#__PURE__*/React.createElement("path", {
    d: "M17 50 H47 l3 6 H14 Z",
    fill: "#9A90BC"
  })), /*#__PURE__*/React.createElement("g", null, /*#__PURE__*/React.createElement("rect", {
    x: "4",
    y: "29",
    width: "23",
    height: "5",
    rx: "2.5",
    fill: "#C77D4A",
    stroke: "#15121F",
    strokeWidth: "2.4",
    strokeLinejoin: "round"
  }), /*#__PURE__*/React.createElement("rect", {
    x: "25",
    y: "21",
    width: "11",
    height: "21",
    rx: "3",
    fill: "#B7BCD2",
    stroke: "#15121F",
    strokeWidth: "2.4",
    strokeLinejoin: "round"
  }), /*#__PURE__*/React.createElement("rect", {
    x: "27.5",
    y: "24",
    width: "5.5",
    height: "6",
    rx: "1.5",
    fill: "#D9DCE8"
  })), /*#__PURE__*/React.createElement("path", {
    d: "M31 41 L40 26 H34 L42 11 L30 28 H36 Z",
    fill: "url(#lfBolt)",
    stroke: "#15121F",
    strokeWidth: "2",
    strokeLinejoin: "round"
  })), /*#__PURE__*/React.createElement("span", {
    style: {
      fontWeight: 700,
      fontSize: "15px",
      letterSpacing: "0.4px"
    }
  }, "Nokido"), /*#__PURE__*/React.createElement("span", {
    className: "laforge-pulse",
    style: {
      marginLeft: "auto",
      width: "7px",
      height: "7px",
      borderRadius: "50%",
      background: "var(--green)"
    }
  })), /*#__PURE__*/React.createElement("nav", {
    style: {
      padding: "10px 8px",
      display: "flex",
      flexDirection: "column",
      gap: "2px"
    }
  }, NAV.map(n => {
    const on = active === n.id;
    return /*#__PURE__*/React.createElement("button", {
      key: n.id,
      onClick: () => onNav(n.id),
      style: {
        display: "flex",
        alignItems: "center",
        gap: "10px",
        padding: "9px 11px",
        borderRadius: "var(--radius-sm)",
        border: "none",
        cursor: "pointer",
        textAlign: "left",
        fontSize: "13px",
        fontWeight: on ? 600 : 500,
        fontFamily: "var(--font-sans)",
        background: on ? "var(--bg-3)" : "transparent",
        color: on ? "var(--text-primary)" : "var(--text-secondary)",
        boxShadow: on ? "inset 3px 0 0 var(--purple)" : "none",
        transition: "background var(--motion-fast)"
      },
      onMouseEnter: e => {
        if (!on) e.currentTarget.style.background = "var(--bg-2)";
      },
      onMouseLeave: e => {
        if (!on) e.currentTarget.style.background = "transparent";
      }
    }, /*#__PURE__*/React.createElement(Ico, {
      n: n.icon
    }), n.label);
  })), /*#__PURE__*/React.createElement("div", {
    style: {
      marginTop: "auto",
      padding: "14px",
      borderTop: "1px solid var(--border-subtle)"
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      gap: "6px",
      marginBottom: "12px"
    }
  }, /*#__PURE__*/React.createElement("a", {
    href: "../composer/index.html",
    title: "Composer son app",
    style: {
      flex: 1,
      display: "inline-flex",
      alignItems: "center",
      justifyContent: "center",
      gap: "5px",
      padding: "6px",
      borderRadius: "var(--radius-sm)",
      border: "1px solid var(--border)",
      color: "var(--text-secondary)",
      fontSize: "10.5px",
      fontFamily: "var(--font-mono)"
    }
  }, /*#__PURE__*/React.createElement(Ico, {
    n: "layout-dashboard",
    s: 13
  }), "Composer"), /*#__PURE__*/React.createElement("a", {
    href: "../login/index.html",
    title: "Verrouiller le coffre",
    style: {
      display: "inline-flex",
      alignItems: "center",
      justifyContent: "center",
      padding: "6px 9px",
      borderRadius: "var(--radius-sm)",
      border: "1px solid var(--border)",
      color: "var(--text-secondary)"
    }
  }, /*#__PURE__*/React.createElement(Ico, {
    n: "lock",
    s: 13
  }))), /*#__PURE__*/React.createElement(SovereigntyGauge, {
    local: local,
    showLegend: false,
    height: 8
  }), /*#__PURE__*/React.createElement("div", {
    style: {
      marginTop: "12px",
      display: "flex",
      alignItems: "center",
      gap: "8px"
    }
  }, /*#__PURE__*/React.createElement("span", {
    style: {
      width: "26px",
      height: "26px",
      borderRadius: "50%",
      background: "var(--purple-dim)",
      display: "flex",
      alignItems: "center",
      justifyContent: "center",
      fontSize: "11px",
      fontWeight: 700
    }
  }, "N"), /*#__PURE__*/React.createElement("div", {
    style: {
      lineHeight: 1.2
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      fontSize: "12px",
      fontWeight: 600
    }
  }, "user"), /*#__PURE__*/React.createElement("div", {
    style: {
      fontFamily: "var(--font-mono)",
      fontSize: "9.5px",
      color: "var(--text-dim)"
    }
  }, "Ring 0 \xB7 n\u0153ud souverain")))));
}
function HubTopbar({
  title,
  subtitle,
  right
}) {
  return /*#__PURE__*/React.createElement("header", {
    style: {
      height: "var(--topbar-h)",
      borderBottom: "1px solid var(--border-subtle)",
      background: "var(--bg-1)",
      display: "flex",
      alignItems: "center",
      padding: "0 22px",
      gap: "14px",
      flexShrink: 0
    }
  }, /*#__PURE__*/React.createElement("div", null, /*#__PURE__*/React.createElement("div", {
    style: {
      fontSize: "15px",
      fontWeight: 700,
      lineHeight: 1.1
    }
  }, title), subtitle && /*#__PURE__*/React.createElement("div", {
    style: {
      fontSize: "11px",
      color: "var(--text-dim)",
      fontFamily: "var(--font-mono)"
    }
  }, subtitle)), /*#__PURE__*/React.createElement("div", {
    style: {
      marginLeft: "auto",
      display: "flex",
      alignItems: "center",
      gap: "10px"
    }
  }, right));
}
window.HubSidebar = HubSidebar;
window.HubTopbar = HubTopbar;
window.HubIco = Ico;
})(); } catch (e) { __ds_ns.__errors.push({ path: "ui_kits/hub/hub-shell.ref.jsx", error: String((e && e.message) || e) }); }

// ui_kits/hub/hub-views.ref.jsx
try { (() => {
function _extends() { return _extends = Object.assign ? Object.assign.bind() : function (n) { for (var e = 1; e < arguments.length; e++) { var t = arguments[e]; for (var r in t) ({}).hasOwnProperty.call(t, r) && (n[r] = t[r]); } return n; }, _extends.apply(null, arguments); }
/* Nokido Hub — vues principales */
const {
  Card,
  Button,
  Badge,
  StatusPill,
  ProvenanceBadge,
  SovereigntyGauge,
  PowerSlider,
  ModuleCard,
  CapStep,
  TextInput
} = window.NokidoDesignSystem_bdc2ac;
const Ico = window.HubIco;
const MODULES = [{
  domain: "transport",
  title: "Transport",
  desc: "Trajets, mobilité, logistique perso",
  icon: "route",
  provenance: "hybrid",
  status: "up"
}, {
  domain: "sante",
  title: "Santé",
  desc: "Suivi, rappels, données sensibles",
  icon: "heart-pulse",
  provenance: "local",
  pinned: true
}, {
  domain: "finance",
  title: "Finance",
  desc: "Comptes, budgets, traçabilité",
  icon: "wallet",
  provenance: "local"
}, {
  domain: "loisir",
  title: "Loisir",
  desc: "Sorties, médias, agenda perso",
  icon: "compass",
  provenance: "hybrid"
}, {
  domain: "achat",
  title: "Achat",
  desc: "Comparaison neutre, suivi prix",
  icon: "shopping-cart",
  provenance: "remote"
}, {
  domain: "creation",
  title: "Création",
  desc: "Texte, image, son, code génératif",
  icon: "sparkles",
  provenance: "hybrid"
}, {
  domain: "dev",
  title: "Dev",
  desc: "Code, automatisations, MCP & skills",
  icon: "terminal",
  provenance: "local"
}, {
  domain: "domotique",
  title: "Domotique",
  desc: "Hub maison, scènes, local-first",
  icon: "house",
  provenance: "local",
  pinned: true
}, {
  domain: "jeux",
  title: "Jeux vidéo",
  desc: "Bibliothèque & compagnons",
  icon: "gamepad-2",
  comingSoon: true
}];
function SectionTitle({
  children,
  hint
}) {
  return /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      alignItems: "baseline",
      gap: "10px",
      margin: "0 0 14px"
    }
  }, /*#__PURE__*/React.createElement("h2", {
    style: {
      margin: 0,
      fontSize: "13px",
      fontWeight: 700,
      textTransform: "uppercase",
      letterSpacing: "0.6px",
      color: "var(--text-secondary)"
    }
  }, children), hint && /*#__PURE__*/React.createElement("span", {
    style: {
      fontSize: "11px",
      color: "var(--text-dim)",
      fontFamily: "var(--font-mono)"
    }
  }, hint));
}

/* ---------------- Accueil ---------------- */
function ViewAccueil({
  enabled,
  onToggle
}) {
  return /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      flexDirection: "column",
      gap: "26px"
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      display: "grid",
      gridTemplateColumns: "2fr 1fr",
      gap: "14px"
    }
  }, /*#__PURE__*/React.createElement(Card, {
    style: {
      background: "var(--bg-1)"
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      alignItems: "center",
      gap: "8px",
      marginBottom: "10px"
    }
  }, /*#__PURE__*/React.createElement(Ico, {
    n: "target",
    s: 16
  }), /*#__PURE__*/React.createElement("span", {
    style: {
      fontWeight: 700,
      fontSize: "14px"
    }
  }, "Cap en cours"), /*#__PURE__*/React.createElement(Badge, {
    color: "purple",
    mono: true
  }, "112 \xE9tapes")), /*#__PURE__*/React.createElement("p", {
    style: {
      margin: 0,
      fontSize: "15px",
      color: "var(--text-primary)",
      lineHeight: 1.5
    }
  }, "\xAB Reprendre le contr\xF4le de mes donn\xE9es de sant\xE9 et passer la maison 100 % local-first d'ici l'automne. \xBB"), /*#__PURE__*/React.createElement("div", {
    style: {
      marginTop: "14px",
      display: "flex",
      alignItems: "center",
      gap: "10px"
    }
  }, /*#__PURE__*/React.createElement(SovereigntyGauge, {
    local: 68,
    label: null,
    showLegend: false,
    height: 8,
    style: {
      flex: 1
    }
  }), /*#__PURE__*/React.createElement("span", {
    style: {
      fontFamily: "var(--font-mono)",
      fontSize: "11px",
      color: "var(--text-dim)"
    }
  }, "jalon 4 / 9"))), /*#__PURE__*/React.createElement(Card, {
    style: {
      background: "var(--bg-1)"
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      alignItems: "center",
      gap: "8px",
      marginBottom: "10px"
    }
  }, /*#__PURE__*/React.createElement(Ico, {
    n: "brain",
    s: 16
  }), /*#__PURE__*/React.createElement("span", {
    style: {
      fontWeight: 700,
      fontSize: "14px"
    }
  }, "Persona")), /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      flexDirection: "column",
      gap: "7px",
      fontSize: "12px",
      color: "var(--text-secondary)"
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      justifyContent: "space-between"
    }
  }, /*#__PURE__*/React.createElement("span", null, "Maturit\xE9"), /*#__PURE__*/React.createElement("span", {
    style: {
      color: "var(--cyan)",
      fontFamily: "var(--font-mono)"
    }
  }, "niveau 3 / 5")), /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      justifyContent: "space-between"
    }
  }, /*#__PURE__*/React.createElement("span", null, "Souvenirs"), /*#__PURE__*/React.createElement("span", {
    style: {
      fontFamily: "var(--font-mono)"
    }
  }, "47 actifs")), /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      justifyContent: "space-between"
    }
  }, /*#__PURE__*/React.createElement("span", null, "Ton appris"), /*#__PURE__*/React.createElement("span", {
    style: {
      fontFamily: "var(--font-mono)",
      color: "var(--text-dim)"
    }
  }, "direct \xB7 concis"))))), /*#__PURE__*/React.createElement("div", null, /*#__PURE__*/React.createElement(SectionTitle, {
    hint: "grille de modules \xB7 glisser pour r\xE9organiser"
  }, "Tes sections"), /*#__PURE__*/React.createElement("div", {
    style: {
      display: "grid",
      gridTemplateColumns: "repeat(auto-fit, minmax(248px, 1fr))",
      gap: "14px"
    }
  }, MODULES.map(m => /*#__PURE__*/React.createElement(ModuleCard, _extends({
    key: m.domain
  }, m, {
    icon: /*#__PURE__*/React.createElement(Ico, {
      n: m.icon,
      s: 22
    }),
    enabled: enabled[m.domain] !== false,
    onToggle: m.comingSoon ? null : v => onToggle(m.domain, v)
  }))))));
}

/* ---------------- Cap (intention longue) ---------------- */
function ViewCap() {
  const [scale, setScale] = React.useState("jalons");
  const steps = [{
    index: 1,
    title: "Cartographier l'historique des échanges",
    state: "done",
    provenance: "local",
    ring: "gold"
  }, {
    index: 2,
    title: "Reconstituer le cap depuis l'historique",
    state: "done",
    provenance: "local",
    ring: "verified"
  }, {
    index: 3,
    title: "Exporter les données de santé du cloud",
    state: "done",
    provenance: "local",
    ring: "verified"
  }, {
    index: 4,
    title: "Décomposer en 112 étapes exécutables",
    state: "active",
    provenance: "remote",
    ring: "verified"
  }, {
    index: 5,
    title: "Estimer dépendances & silos parallèles",
    state: "pending",
    parallel: true
  }, {
    index: 6,
    title: "Migrer la domotique en local-first",
    state: "pending",
    ring: "draft"
  }, {
    index: 7,
    title: "Proposer la prochaine étape",
    state: "pending",
    ring: "draft",
    last: true
  }];
  return /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      flexDirection: "column",
      gap: "20px",
      maxWidth: "780px"
    }
  }, /*#__PURE__*/React.createElement(Card, {
    style: {
      background: "var(--bg-1)"
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      fontSize: "11px",
      textTransform: "uppercase",
      letterSpacing: "0.6px",
      color: "var(--text-dim)",
      marginBottom: "6px"
    }
  }, "Horizon \xB7 le cap"), /*#__PURE__*/React.createElement("p", {
    style: {
      margin: 0,
      fontSize: "18px",
      fontWeight: 600,
      lineHeight: 1.4
    }
  }, "Reprendre le contr\xF4le de mes donn\xE9es de sant\xE9 et passer la maison 100 % local-first.")), /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      gap: "6px"
    }
  }, ["horizon", "jalons", "étapes"].map(s => /*#__PURE__*/React.createElement("button", {
    key: s,
    onClick: () => setScale(s),
    style: {
      padding: "5px 12px",
      borderRadius: "var(--radius-pill)",
      cursor: "pointer",
      fontFamily: "var(--font-mono)",
      fontSize: "11px",
      border: "1px solid var(--border)",
      background: scale === s ? "var(--tint-purple)" : "transparent",
      color: scale === s ? "var(--purple)" : "var(--text-secondary)"
    }
  }, s)), /*#__PURE__*/React.createElement("span", {
    style: {
      marginLeft: "auto",
      alignSelf: "center",
      fontFamily: "var(--font-mono)",
      fontSize: "11px",
      color: "var(--text-dim)"
    }
  }, "112 \xE9tapes \xB7 9 jalons")), /*#__PURE__*/React.createElement(Card, null, /*#__PURE__*/React.createElement("div", {
    style: {
      marginTop: "2px"
    }
  }, steps.map(s => /*#__PURE__*/React.createElement(CapStep, _extends({
    key: s.index
  }, s)))), /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      gap: "8px",
      marginTop: "10px",
      paddingTop: "14px",
      borderTop: "1px solid var(--border-subtle)"
    }
  }, /*#__PURE__*/React.createElement(Button, {
    variant: "primary",
    size: "sm",
    icon: /*#__PURE__*/React.createElement(Ico, {
      n: "check",
      s: 14
    })
  }, "Valider l'\xE9tape"), /*#__PURE__*/React.createElement(Button, {
    variant: "ghost",
    size: "sm",
    icon: /*#__PURE__*/React.createElement(Ico, {
      n: "git-branch",
      s: 14
    })
  }, "Bifurquer"), /*#__PURE__*/React.createElement(Button, {
    variant: "ghost",
    size: "sm",
    icon: /*#__PURE__*/React.createElement(Ico, {
      n: "arrow-up-down",
      s: 14
    })
  }, "R\xE9ordonner"))));
}

/* ---------------- Maison (domotique) ---------------- */
function ViewMaison() {
  const scenes = [{
    name: "Réveil",
    icon: "sunrise",
    on: false
  }, {
    name: "Travail",
    icon: "laptop",
    on: true
  }, {
    name: "Cinéma",
    icon: "clapperboard",
    on: false
  }, {
    name: "Nuit",
    icon: "moon",
    on: false
  }];
  const devices = [{
    name: "Salon — lumières",
    icon: "lightbulb",
    status: "up",
    val: "62 %"
  }, {
    name: "Thermostat",
    icon: "thermometer",
    status: "up",
    val: "21°C"
  }, {
    name: "Porte d'entrée",
    icon: "lock",
    status: "up",
    val: "verrouillée"
  }, {
    name: "Caméra jardin",
    icon: "video",
    status: "warn",
    val: "local seul"
  }];
  return /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      flexDirection: "column",
      gap: "22px",
      maxWidth: "820px"
    }
  }, /*#__PURE__*/React.createElement(Card, {
    style: {
      background: "var(--bg-1)",
      borderColor: "var(--prov-local)",
      boxShadow: "var(--prov-local-glow)"
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      alignItems: "center",
      gap: "10px"
    }
  }, /*#__PURE__*/React.createElement(Ico, {
    n: "shield-check",
    s: 18
  }), /*#__PURE__*/React.createElement("span", {
    style: {
      fontWeight: 600
    }
  }, "Maison vivante \u2014 local-first absolu"), /*#__PURE__*/React.createElement(ProvenanceBadge, {
    origin: "local",
    detail: "ne d\xE9pend jamais du cloud",
    style: {
      marginLeft: "auto"
    }
  }))), /*#__PURE__*/React.createElement("div", null, /*#__PURE__*/React.createElement(SectionTitle, {
    hint: "d\xE9clencheurs"
  }, "Sc\xE8nes"), /*#__PURE__*/React.createElement("div", {
    style: {
      display: "grid",
      gridTemplateColumns: "repeat(4, 1fr)",
      gap: "12px"
    }
  }, scenes.map(s => /*#__PURE__*/React.createElement("button", {
    key: s.name,
    style: {
      display: "flex",
      flexDirection: "column",
      alignItems: "center",
      gap: "8px",
      padding: "16px",
      borderRadius: "var(--radius-md)",
      cursor: "pointer",
      fontFamily: "var(--font-sans)",
      background: s.on ? "var(--tint-green)" : "var(--bg-2)",
      border: `1px solid ${s.on ? "var(--prov-local)" : "var(--border)"}`,
      color: s.on ? "var(--prov-local)" : "var(--text-secondary)"
    }
  }, /*#__PURE__*/React.createElement(Ico, {
    n: s.icon,
    s: 22
  }), /*#__PURE__*/React.createElement("span", {
    style: {
      fontSize: "12.5px",
      fontWeight: 600
    }
  }, s.name))))), /*#__PURE__*/React.createElement("div", null, /*#__PURE__*/React.createElement(SectionTitle, {
    hint: "capteurs & actionneurs"
  }, "Appareils"), /*#__PURE__*/React.createElement("div", {
    style: {
      display: "grid",
      gridTemplateColumns: "1fr 1fr",
      gap: "12px"
    }
  }, devices.map(d => /*#__PURE__*/React.createElement("div", {
    key: d.name,
    style: {
      display: "flex",
      alignItems: "center",
      gap: "12px",
      padding: "13px 15px",
      background: "var(--bg-2)",
      border: "1px solid var(--border)",
      borderRadius: "var(--radius-md)"
    }
  }, /*#__PURE__*/React.createElement("span", {
    style: {
      display: "inline-flex",
      alignItems: "center",
      justifyContent: "center",
      width: "36px",
      height: "36px",
      borderRadius: "var(--radius-sm)",
      background: "var(--tint-green)",
      color: "var(--prov-local)"
    }
  }, /*#__PURE__*/React.createElement(Ico, {
    n: d.icon,
    s: 18
  })), /*#__PURE__*/React.createElement("div", {
    style: {
      flex: 1
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      fontSize: "13px",
      fontWeight: 600
    }
  }, d.name), /*#__PURE__*/React.createElement("div", {
    style: {
      fontFamily: "var(--font-mono)",
      fontSize: "11px",
      color: "var(--text-dim)"
    }
  }, d.val)), /*#__PURE__*/React.createElement(StatusPill, {
    status: d.status,
    pulse: d.status === "up"
  }, d.status === "up" ? "local" : "dégradé"))))));
}

/* ---------------- Persona (mémoire) ---------------- */
function ViewPersona() {
  const [mem, setMem] = React.useState([{
    t: "Préfère les réponses concises et directes",
    prov: "local",
    ring: "gold"
  }, {
    t: "Travaille surtout en Python le soir",
    prov: "local",
    ring: "verified"
  }, {
    t: "Données de santé : jamais vers le cloud",
    prov: "local",
    ring: "gold"
  }, {
    t: "Aime comparer les prix avant d'acheter",
    prov: "hybrid",
    ring: "verified"
  }, {
    t: "Objectif : maison 100 % local-first",
    prov: "local",
    ring: "verified"
  }]);
  const revoke = i => setMem(mem.filter((_, j) => j !== i));
  return /*#__PURE__*/React.createElement("div", {
    style: {
      maxWidth: "720px"
    }
  }, /*#__PURE__*/React.createElement(Card, {
    style: {
      background: "var(--bg-1)",
      marginBottom: "16px"
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      alignItems: "center",
      gap: "10px"
    }
  }, /*#__PURE__*/React.createElement(Ico, {
    n: "brain",
    s: 18
  }), /*#__PURE__*/React.createElement("div", null, /*#__PURE__*/React.createElement("div", {
    style: {
      fontWeight: 600
    }
  }, "Ce que Nokido a compris de toi"), /*#__PURE__*/React.createElement("div", {
    style: {
      fontSize: "12px",
      color: "var(--text-dim)"
    }
  }, "Tout est visible, \xE9ditable et r\xE9vocable. La confiance passe par le contr\xF4le.")))), /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      flexDirection: "column",
      gap: "8px"
    }
  }, mem.map((m, i) => /*#__PURE__*/React.createElement("div", {
    key: i,
    style: {
      display: "flex",
      alignItems: "center",
      gap: "12px",
      padding: "12px 15px",
      background: "var(--bg-2)",
      border: "1px solid var(--border)",
      borderRadius: "var(--radius-md)"
    }
  }, /*#__PURE__*/React.createElement("span", {
    style: {
      flex: 1,
      fontSize: "13px"
    }
  }, m.t), /*#__PURE__*/React.createElement(ProvenanceBadge, {
    origin: m.prov,
    ring: m.ring,
    size: "sm"
  }), /*#__PURE__*/React.createElement(Button, {
    variant: "ghost",
    size: "sm",
    icon: /*#__PURE__*/React.createElement(Ico, {
      n: "x",
      s: 13
    }),
    onClick: () => revoke(i)
  }, "Oublier"))), mem.length === 0 && /*#__PURE__*/React.createElement("div", {
    style: {
      padding: "30px",
      textAlign: "center",
      color: "var(--text-dim)",
      fontSize: "13px"
    }
  }, "M\xE9moire vide \u2014 Nokido repart de z\xE9ro.")));
}

/* ---------------- Souveraineté ---------------- */
function ViewSouverainete({
  local,
  setLocal
}) {
  const log = [{
    ts: "14:32:08",
    act: "ask",
    prov: "local",
    model: "ollama:mistral",
    lat: "612ms",
    ring: "gold"
  }, {
    ts: "14:31:54",
    act: "ingest",
    prov: "local",
    model: "embed:bge-m3",
    lat: "88ms",
    ring: "verified"
  }, {
    ts: "14:30:12",
    act: "ask",
    prov: "remote",
    model: "groq:llama-70b",
    lat: "248ms",
    ring: "verified"
  }, {
    ts: "14:28:03",
    act: "compare",
    prov: "hybrid",
    model: "router",
    lat: "1.2s",
    ring: "draft"
  }];
  return /*#__PURE__*/React.createElement("div", {
    style: {
      display: "grid",
      gridTemplateColumns: "1fr 1fr",
      gap: "18px",
      maxWidth: "900px",
      alignItems: "start"
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      flexDirection: "column",
      gap: "16px"
    }
  }, /*#__PURE__*/React.createElement(PowerSlider, {
    value: local,
    onChange: setLocal
  }), /*#__PURE__*/React.createElement(BasculeTask, {
    local: local
  }), /*#__PURE__*/React.createElement(Card, null, /*#__PURE__*/React.createElement("div", {
    style: {
      fontSize: "12px",
      color: "var(--text-secondary)",
      lineHeight: 1.6
    }
  }, "La cascade : ", /*#__PURE__*/React.createElement("b", {
    style: {
      color: "var(--prov-local)"
    }
  }, "NPU \u2192 iGPU \u2192 Ollama/llama.cpp local"), " \u2192 ", /*#__PURE__*/React.createElement("b", {
    style: {
      color: "var(--prov-remote)"
    }
  }, "cloud"), " en dernier recours. Plus tu alloues de puissance, plus Nokido reste local tout en restant performant."))), /*#__PURE__*/React.createElement(Card, null, /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      alignItems: "center",
      gap: "8px",
      marginBottom: "12px"
    }
  }, /*#__PURE__*/React.createElement(Ico, {
    n: "receipt-text",
    s: 16
  }), /*#__PURE__*/React.createElement("span", {
    style: {
      fontWeight: 700,
      fontSize: "13px"
    }
  }, "Journal de provenance")), /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      flexDirection: "column",
      gap: "9px"
    }
  }, log.map((l, i) => /*#__PURE__*/React.createElement("div", {
    key: i,
    style: {
      display: "flex",
      alignItems: "center",
      gap: "8px",
      fontFamily: "var(--font-mono)",
      fontSize: "11px"
    }
  }, /*#__PURE__*/React.createElement("span", {
    style: {
      color: "var(--text-dim)"
    }
  }, l.ts), /*#__PURE__*/React.createElement("span", {
    style: {
      color: "var(--text-secondary)",
      minWidth: "52px"
    }
  }, l.act), /*#__PURE__*/React.createElement(ProvenanceBadge, {
    origin: l.prov,
    ring: l.ring,
    size: "sm",
    detail: l.model,
    style: {
      marginLeft: "auto"
    }
  }))))));
}

/* Bascule local ↔ distant sur une tâche réelle, pilotée par le curseur */
function BasculeTask({
  local
}) {
  const target = local >= 60 ? "local" : local >= 30 ? "hybrid" : "remote";
  const cfg = {
    local: {
      color: "var(--prov-local)",
      tint: "var(--prov-local-tint)",
      where: "Sur ta machine (Ollama)",
      lat: "0,6 s",
      conf: "Maximale",
      cost: "0 €"
    },
    hybrid: {
      color: "var(--prov-hybrid)",
      tint: "var(--prov-hybrid-tint)",
      where: "Local + cloud (anonymisé)",
      lat: "0,9 s",
      conf: "Élevée",
      cost: "~0,01 €"
    },
    remote: {
      color: "var(--prov-remote)",
      tint: "var(--prov-remote-tint)",
      where: "Cloud (Groq)",
      lat: "0,3 s",
      conf: "Réduite",
      cost: "~0,04 €"
    }
  }[target];
  const metric = (l, v) => /*#__PURE__*/React.createElement("div", null, /*#__PURE__*/React.createElement("div", {
    style: {
      fontSize: "10px",
      color: "var(--text-dim)",
      textTransform: "uppercase",
      letterSpacing: "0.4px"
    }
  }, l), /*#__PURE__*/React.createElement("div", {
    style: {
      fontFamily: "var(--font-mono)",
      fontSize: "12.5px",
      fontWeight: 700
    }
  }, v));
  return /*#__PURE__*/React.createElement(Card, {
    style: {
      borderColor: cfg.color
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      alignItems: "center",
      gap: "8px",
      marginBottom: "10px"
    }
  }, /*#__PURE__*/React.createElement(Ico, {
    n: "git-compare-arrows",
    s: 16
  }), /*#__PURE__*/React.createElement("span", {
    style: {
      fontWeight: 700,
      fontSize: "13px"
    }
  }, "Bascule en direct"), /*#__PURE__*/React.createElement(ProvenanceBadge, {
    origin: target,
    size: "sm",
    style: {
      marginLeft: "auto"
    }
  })), /*#__PURE__*/React.createElement("div", {
    style: {
      fontSize: "12.5px",
      color: "var(--text-secondary)",
      marginBottom: "12px"
    }
  }, "T\xE2che : ", /*#__PURE__*/React.createElement("b", {
    style: {
      color: "var(--text-primary)"
    }
  }, "\xAB Analyser mes d\xE9penses du mois \xBB")), /*#__PURE__*/React.createElement("div", {
    style: {
      padding: "10px 12px",
      borderRadius: "var(--radius-sm)",
      background: cfg.tint,
      marginBottom: "12px",
      display: "flex",
      alignItems: "center",
      gap: "8px",
      fontSize: "12px",
      color: cfg.color,
      fontWeight: 600
    }
  }, /*#__PURE__*/React.createElement(Ico, {
    n: target === "local" ? "house" : target === "hybrid" ? "git-fork" : "cloud",
    s: 15
  }), cfg.where), /*#__PURE__*/React.createElement("div", {
    style: {
      display: "grid",
      gridTemplateColumns: "repeat(3,1fr)",
      gap: "10px",
      marginBottom: "10px"
    }
  }, metric("Confidentialité", cfg.conf), metric("Latence", cfg.lat), metric("Coût", cfg.cost)), target !== "local" && /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      gap: "8px",
      fontSize: "11px",
      color: "var(--text-dim)",
      fontFamily: "var(--font-mono)",
      paddingTop: "10px",
      borderTop: "1px solid var(--border-subtle)"
    }
  }, /*#__PURE__*/React.createElement(Ico, {
    n: "shield-alert",
    s: 14
  }), "Cloud coup\xE9 \u2192 bascule locale annonc\xE9e, sans perte."));
}

/* ---------------- Fédération (Exposer son hub d'IA) ---------------- */
function ViewFederation() {
  const [exposed, setExposed] = React.useState(true);
  const [nodes, setNodes] = React.useState([{
    name: "Hub de Camille",
    scope: "Création · lecture",
    prov: "remote",
    ring: "verified",
    dir: "out"
  }, {
    name: "Nœud Atelier-3",
    scope: "Dev · skills partagés",
    prov: "hybrid",
    ring: "verified",
    dir: "in"
  }, {
    name: "Hub de Léo",
    scope: "Loisir · recommandations",
    prov: "remote",
    ring: "draft",
    dir: "out"
  }]);
  const revoke = i => setNodes(nodes.filter((_, j) => j !== i));
  return /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      flexDirection: "column",
      gap: "18px",
      maxWidth: "820px"
    }
  }, /*#__PURE__*/React.createElement(Card, {
    style: {
      background: "var(--bg-1)",
      borderColor: exposed ? "var(--prov-remote)" : "var(--border)"
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      alignItems: "center",
      gap: "12px"
    }
  }, /*#__PURE__*/React.createElement("span", {
    style: {
      display: "inline-flex",
      alignItems: "center",
      justifyContent: "center",
      width: "40px",
      height: "40px",
      borderRadius: "var(--radius-sm)",
      background: "var(--tint-purple)",
      color: "var(--purple)"
    }
  }, /*#__PURE__*/React.createElement(Ico, {
    n: "share-2",
    s: 20
  })), /*#__PURE__*/React.createElement("div", {
    style: {
      flex: 1
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      fontWeight: 700,
      fontSize: "15px"
    }
  }, "Exposer mon hub d'IA"), /*#__PURE__*/React.createElement("div", {
    style: {
      fontSize: "12px",
      color: "var(--text-dim)"
    }
  }, "F\xE9d\xE8re ton intelligence avec d'autres n\u0153uds. Tu restes souverain : rien ne sort sans r\xE8gle explicite.")), /*#__PURE__*/React.createElement("button", {
    onClick: () => setExposed(!exposed),
    "aria-label": "Exposer",
    style: {
      width: "46px",
      height: "26px",
      borderRadius: "var(--radius-pill)",
      border: "none",
      cursor: "pointer",
      background: exposed ? "var(--purple)" : "var(--bg-4)",
      position: "relative",
      flexShrink: 0,
      transition: "background var(--motion-fast)"
    }
  }, /*#__PURE__*/React.createElement("span", {
    style: {
      position: "absolute",
      top: "3px",
      left: exposed ? "23px" : "3px",
      width: "20px",
      height: "20px",
      borderRadius: "50%",
      background: "#fff",
      transition: "left var(--motion-fast)"
    }
  })))), /*#__PURE__*/React.createElement("div", {
    style: {
      display: "grid",
      gridTemplateColumns: "repeat(3,1fr)",
      gap: "12px"
    }
  }, [["eye-off", "Anonymisé", "Aucune intention brute ne sort"], ["scan-line", "Périmètre limité", "Tu choisis quoi partager"], ["undo-2", "Révocable", "Coupe un nœud à tout moment"]].map(([ic, t, d]) => /*#__PURE__*/React.createElement("div", {
    key: t,
    style: {
      padding: "13px 14px",
      background: "var(--bg-2)",
      border: "1px solid var(--border)",
      borderRadius: "var(--radius-md)"
    }
  }, /*#__PURE__*/React.createElement("span", {
    style: {
      color: "var(--prov-local)"
    }
  }, /*#__PURE__*/React.createElement(Ico, {
    n: ic,
    s: 17
  })), /*#__PURE__*/React.createElement("div", {
    style: {
      fontSize: "13px",
      fontWeight: 600,
      marginTop: "7px"
    }
  }, t), /*#__PURE__*/React.createElement("div", {
    style: {
      fontSize: "11px",
      color: "var(--text-dim)",
      lineHeight: 1.4
    }
  }, d)))), /*#__PURE__*/React.createElement("div", null, /*#__PURE__*/React.createElement(SectionTitle, {
    hint: `${nodes.length} connexions actives`
  }, "N\u0153uds f\xE9d\xE9r\xE9s"), /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      flexDirection: "column",
      gap: "8px",
      opacity: exposed ? 1 : 0.45,
      pointerEvents: exposed ? "auto" : "none"
    }
  }, nodes.map((n, i) => /*#__PURE__*/React.createElement("div", {
    key: i,
    style: {
      display: "flex",
      alignItems: "center",
      gap: "12px",
      padding: "12px 15px",
      background: "var(--bg-2)",
      border: "1px solid var(--border)",
      borderRadius: "var(--radius-md)"
    }
  }, /*#__PURE__*/React.createElement("span", {
    style: {
      display: "inline-flex",
      alignItems: "center",
      justifyContent: "center",
      width: "30px",
      height: "30px",
      borderRadius: "50%",
      background: "var(--bg-4)",
      color: "var(--text-secondary)",
      fontFamily: "var(--font-mono)",
      fontSize: "11px",
      fontWeight: 700
    }
  }, n.name.replace("Hub de ", "")[0]), /*#__PURE__*/React.createElement("div", {
    style: {
      flex: 1,
      minWidth: 0
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      fontSize: "13px",
      fontWeight: 600,
      display: "flex",
      alignItems: "center",
      gap: "7px"
    }
  }, n.name, /*#__PURE__*/React.createElement("span", {
    style: {
      fontFamily: "var(--font-mono)",
      fontSize: "9px",
      color: n.dir === "in" ? "var(--cyan)" : "var(--purple)",
      border: `1px solid ${n.dir === "in" ? "var(--cyan)" : "var(--purple)"}`,
      borderRadius: "3px",
      padding: "0 4px"
    }
  }, n.dir === "in" ? "↓ entrant" : "↑ sortant")), /*#__PURE__*/React.createElement("div", {
    style: {
      fontSize: "11px",
      color: "var(--text-dim)",
      fontFamily: "var(--font-mono)"
    }
  }, n.scope)), /*#__PURE__*/React.createElement(ProvenanceBadge, {
    origin: n.prov,
    ring: n.ring,
    size: "sm"
  }), /*#__PURE__*/React.createElement(Button, {
    variant: "ghost",
    size: "sm",
    icon: /*#__PURE__*/React.createElement(Ico, {
      n: "x",
      s: 13
    }),
    onClick: () => revoke(i)
  }, "R\xE9voquer"))), nodes.length === 0 && /*#__PURE__*/React.createElement("div", {
    style: {
      padding: "28px",
      textAlign: "center",
      color: "var(--text-dim)",
      fontSize: "13px"
    }
  }, "Aucun n\u0153ud f\xE9d\xE9r\xE9. Ton hub est enti\xE8rement priv\xE9."))));
}
Object.assign(window, {
  ViewAccueil,
  ViewCap,
  ViewMaison,
  ViewPersona,
  ViewSouverainete,
  ViewFederation
});
})(); } catch (e) { __ds_ns.__errors.push({ path: "ui_kits/hub/hub-views.ref.jsx", error: String((e && e.message) || e) }); }

// ui_kits/hub/mobile-hub.ref.jsx
try { (() => {
function _extends() { return _extends = Object.assign ? Object.assign.bind() : function (n) { for (var e = 1; e < arguments.length; e++) { var t = arguments[e]; for (var r in t) ({}).hasOwnProperty.call(t, r) && (n[r] = t[r]); } return n; }, _extends.apply(null, arguments); }
/* Nokido — Hub mobile (glance). Colonne unique, onglets bas. Réutilise le DS. */
const {
  Card,
  ModuleCard,
  SovereigntyGauge,
  ProvenanceBadge,
  PowerSlider,
  CapStep,
  Badge
} = window.NokidoDesignSystem_bdc2ac;
const PREF = window.NokidoPrefs; // util de persistance partagé

function MIco({
  n,
  s = 20
}) {
  return /*#__PURE__*/React.createElement("i", {
    "data-lucide": n,
    style: {
      width: s,
      height: s
    }
  });
}
const MODS = [{
  domain: "sante",
  title: "Santé",
  desc: "Local forcé — confidentialité max",
  icon: "heart-pulse",
  provenance: "local",
  pinned: true
}, {
  domain: "domotique",
  title: "Maison",
  desc: "Local-first absolu",
  icon: "house",
  provenance: "local",
  pinned: true
}, {
  domain: "transport",
  title: "Transport",
  desc: "Trajets, temps réel",
  icon: "route",
  provenance: "hybrid"
}, {
  domain: "creation",
  title: "Création",
  desc: "Atelier génératif",
  icon: "sparkles",
  provenance: "hybrid"
}];
function Logo({
  size = 26
}) {
  return /*#__PURE__*/React.createElement("svg", {
    width: size,
    height: size,
    viewBox: "0 0 64 64",
    fill: "none",
    style: {
      flexShrink: 0
    }
  }, /*#__PURE__*/React.createElement("defs", null, /*#__PURE__*/React.createElement("linearGradient", {
    id: "mbolt",
    x1: "26",
    y1: "12",
    x2: "40",
    y2: "40",
    gradientUnits: "userSpaceOnUse"
  }, /*#__PURE__*/React.createElement("stop", {
    offset: "0",
    stopColor: "#FFE070"
  }), /*#__PURE__*/React.createElement("stop", {
    offset: "1",
    stopColor: "#FFC22D"
  }))), /*#__PURE__*/React.createElement("g", {
    stroke: "#15121F",
    strokeWidth: "2.4",
    strokeLinejoin: "round"
  }, /*#__PURE__*/React.createElement("path", {
    d: "M6 35 L20 31 H48 q4 0 4 3.5 Q52 39 47 39 H39 q-3 0 -4 3 l-1.5 3 H27 q-1 -3 -4 -3 H15 Q6 42 6 35 Z",
    fill: "#9A90BC"
  }), /*#__PURE__*/React.createElement("path", {
    d: "M28 45 h8 l-1.5 5 h-5 Z",
    fill: "#6F6498"
  }), /*#__PURE__*/React.createElement("path", {
    d: "M17 50 H47 l3 6 H14 Z",
    fill: "#9A90BC"
  })), /*#__PURE__*/React.createElement("g", null, /*#__PURE__*/React.createElement("rect", {
    x: "4",
    y: "29",
    width: "23",
    height: "5",
    rx: "2.5",
    fill: "#C77D4A",
    stroke: "#15121F",
    strokeWidth: "2.4",
    strokeLinejoin: "round"
  }), /*#__PURE__*/React.createElement("rect", {
    x: "25",
    y: "21",
    width: "11",
    height: "21",
    rx: "3",
    fill: "#B7BCD2",
    stroke: "#15121F",
    strokeWidth: "2.4",
    strokeLinejoin: "round"
  }), /*#__PURE__*/React.createElement("rect", {
    x: "27.5",
    y: "24",
    width: "5.5",
    height: "6",
    rx: "1.5",
    fill: "#D9DCE8"
  })), /*#__PURE__*/React.createElement("path", {
    d: "M31 41 L40 26 H34 L42 11 L30 28 H36 Z",
    fill: "url(#mbolt)",
    stroke: "#15121F",
    strokeWidth: "2",
    strokeLinejoin: "round"
  }));
}
const TABS = [{
  id: "accueil",
  icon: "layout-grid",
  label: "Accueil"
}, {
  id: "cap",
  icon: "target",
  label: "Cap"
}, {
  id: "maison",
  icon: "house",
  label: "Maison"
}, {
  id: "souv",
  icon: "shield-check",
  label: "Souv."
}];
function MobileHub() {
  const [tab, setTab] = React.useState("accueil");
  const [power, setPower] = React.useState(() => PREF ? PREF.get("power", 68) : 68);
  React.useEffect(() => {
    if (PREF) PREF.set("power", power);
  }, [power]);
  React.useEffect(() => {
    if (window.lucide) lucide.createIcons();
  });
  return /*#__PURE__*/React.createElement("div", {
    style: {
      height: "100%",
      display: "flex",
      flexDirection: "column",
      background: "var(--bg-0)",
      color: "var(--text-primary)",
      paddingTop: "50px",
      boxSizing: "border-box"
    }
  }, /*#__PURE__*/React.createElement("header", {
    style: {
      display: "flex",
      alignItems: "center",
      gap: "9px",
      padding: "6px 18px 12px",
      borderBottom: "1px solid var(--border-subtle)"
    }
  }, /*#__PURE__*/React.createElement(Logo, null), /*#__PURE__*/React.createElement("span", {
    style: {
      fontWeight: 700,
      fontSize: "15px",
      letterSpacing: "0.3px"
    }
  }, "Nokido"), /*#__PURE__*/React.createElement(ProvenanceBadge, {
    origin: power >= 60 ? "local" : power >= 30 ? "hybrid" : "remote",
    detail: `${power}%`,
    size: "sm",
    style: {
      marginLeft: "auto"
    }
  }), /*#__PURE__*/React.createElement("a", {
    href: "../login/index.html",
    style: {
      color: "var(--text-dim)",
      display: "inline-flex"
    }
  }, /*#__PURE__*/React.createElement(MIco, {
    n: "lock",
    s: 17
  }))), /*#__PURE__*/React.createElement("div", {
    style: {
      flex: 1,
      overflowY: "auto",
      padding: "16px 18px 18px"
    }
  }, tab === "accueil" && /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      flexDirection: "column",
      gap: "14px"
    }
  }, /*#__PURE__*/React.createElement(Card, {
    style: {
      background: "var(--bg-1)"
    }
  }, /*#__PURE__*/React.createElement(SovereigntyGauge, {
    local: power
  })), /*#__PURE__*/React.createElement(Card, {
    style: {
      background: "var(--bg-1)"
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      alignItems: "center",
      gap: "7px",
      marginBottom: "8px"
    }
  }, /*#__PURE__*/React.createElement(MIco, {
    n: "target",
    s: 15
  }), /*#__PURE__*/React.createElement("span", {
    style: {
      fontWeight: 700,
      fontSize: "13px"
    }
  }, "Cap en cours"), /*#__PURE__*/React.createElement(Badge, {
    color: "purple",
    mono: true
  }, "jalon 4/9")), /*#__PURE__*/React.createElement("div", {
    style: {
      fontSize: "13.5px",
      lineHeight: 1.5
    }
  }, "Reprendre le contr\xF4le de mes donn\xE9es de sant\xE9 \xB7 maison 100 % local-first.")), /*#__PURE__*/React.createElement("div", {
    style: {
      fontFamily: "var(--font-mono)",
      fontSize: "10px",
      textTransform: "uppercase",
      letterSpacing: "0.6px",
      color: "var(--text-dim)",
      marginTop: "2px"
    }
  }, "Tes sections"), MODS.map(m => /*#__PURE__*/React.createElement(ModuleCard, _extends({
    key: m.domain
  }, m, {
    icon: /*#__PURE__*/React.createElement(MIco, {
      n: m.icon,
      s: 22
    })
  })))), tab === "cap" && /*#__PURE__*/React.createElement("div", null, /*#__PURE__*/React.createElement(Card, {
    style: {
      background: "var(--bg-1)",
      marginBottom: "14px"
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      fontSize: "10px",
      textTransform: "uppercase",
      letterSpacing: "0.6px",
      color: "var(--text-dim)",
      marginBottom: "5px"
    }
  }, "Horizon"), /*#__PURE__*/React.createElement("div", {
    style: {
      fontSize: "15px",
      fontWeight: 600,
      lineHeight: 1.4
    }
  }, "Maison 100 % local-first d'ici l'automne.")), /*#__PURE__*/React.createElement("div", null, /*#__PURE__*/React.createElement(CapStep, {
    index: 1,
    title: "Cartographier l'historique",
    state: "done",
    provenance: "local",
    ring: "gold"
  }), /*#__PURE__*/React.createElement(CapStep, {
    index: 2,
    title: "Reconstituer le cap",
    state: "done",
    provenance: "local",
    ring: "verified"
  }), /*#__PURE__*/React.createElement(CapStep, {
    index: 3,
    title: "D\xE9composer en 112 \xE9tapes",
    state: "active",
    provenance: "remote",
    ring: "verified"
  }), /*#__PURE__*/React.createElement(CapStep, {
    index: 4,
    title: "Migrer la domotique",
    state: "pending",
    ring: "draft",
    last: true
  }))), tab === "maison" && /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      flexDirection: "column",
      gap: "12px"
    }
  }, /*#__PURE__*/React.createElement(Card, {
    style: {
      background: "var(--bg-1)",
      borderColor: "var(--prov-local)"
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      alignItems: "center",
      gap: "8px"
    }
  }, /*#__PURE__*/React.createElement(MIco, {
    n: "shield-check",
    s: 16
  }), /*#__PURE__*/React.createElement("span", {
    style: {
      fontWeight: 600,
      fontSize: "13px"
    }
  }, "Maison vivante"), /*#__PURE__*/React.createElement(ProvenanceBadge, {
    origin: "local",
    size: "sm",
    style: {
      marginLeft: "auto"
    }
  }))), /*#__PURE__*/React.createElement("div", {
    style: {
      display: "grid",
      gridTemplateColumns: "1fr 1fr",
      gap: "10px"
    }
  }, [["sunrise", "Réveil", false], ["laptop", "Travail", true], ["clapperboard", "Cinéma", false], ["moon", "Nuit", false]].map(([ic, n, on]) => /*#__PURE__*/React.createElement("div", {
    key: n,
    style: {
      display: "flex",
      flexDirection: "column",
      alignItems: "center",
      gap: "7px",
      padding: "16px",
      borderRadius: "var(--radius-md)",
      background: on ? "var(--tint-green)" : "var(--bg-2)",
      border: `1px solid ${on ? "var(--prov-local)" : "var(--border)"}`,
      color: on ? "var(--prov-local)" : "var(--text-secondary)"
    }
  }, /*#__PURE__*/React.createElement(MIco, {
    n: ic,
    s: 22
  }), /*#__PURE__*/React.createElement("span", {
    style: {
      fontSize: "12.5px",
      fontWeight: 600
    }
  }, n))))), tab === "souv" && /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      flexDirection: "column",
      gap: "14px"
    }
  }, /*#__PURE__*/React.createElement(PowerSlider, {
    value: power,
    onChange: setPower
  }), /*#__PURE__*/React.createElement(Card, null, /*#__PURE__*/React.createElement("div", {
    style: {
      fontSize: "12px",
      color: "var(--text-secondary)",
      lineHeight: 1.6
    }
  }, /*#__PURE__*/React.createElement("b", {
    style: {
      color: "var(--prov-local)"
    }
  }, "NPU \u2192 iGPU \u2192 local"), " \u2192 ", /*#__PURE__*/React.createElement("b", {
    style: {
      color: "var(--prov-remote)"
    }
  }, "cloud"), " en dernier recours. Ta machine traite ", power, "% des requ\xEAtes.")))), /*#__PURE__*/React.createElement("nav", {
    style: {
      display: "flex",
      borderTop: "1px solid var(--border-subtle)",
      background: "var(--bg-1)",
      paddingBottom: "calc(8px + env(safe-area-inset-bottom))",
      paddingTop: "8px"
    }
  }, TABS.map(t => {
    const on = tab === t.id;
    return /*#__PURE__*/React.createElement("button", {
      key: t.id,
      onClick: () => setTab(t.id),
      style: {
        flex: 1,
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        gap: "3px",
        padding: "4px",
        minHeight: "48px",
        border: "none",
        background: "transparent",
        cursor: "pointer",
        color: on ? "var(--purple)" : "var(--text-dim)",
        fontFamily: "var(--font-sans)"
      }
    }, /*#__PURE__*/React.createElement(MIco, {
      n: t.icon,
      s: 20
    }), /*#__PURE__*/React.createElement("span", {
      style: {
        fontSize: "10px",
        fontWeight: on ? 700 : 500
      }
    }, t.label));
  })));
}
Object.assign(window, {
  MobileHub
});
})(); } catch (e) { __ds_ns.__errors.push({ path: "ui_kits/hub/mobile-hub.ref.jsx", error: String((e && e.message) || e) }); }

// ui_kits/login/login-screen.ref.jsx
try { (() => {
/* Nokido — Écran de verrouillage au démarrage : mot de passe + choix de langue.
   Coffre souverain : le déverrouillage est local. i18n FR/EN/ES/DE. */
const {
  Button,
  TextInput,
  ProvenanceBadge,
  Badge
} = window.NokidoDesignSystem_bdc2ac;
const I18N = {
  fr: {
    name: "Français",
    title: "Déverrouille ton hub",
    sub: "Coffre souverain — tout reste sur ta machine.",
    pwd: "Mot de passe",
    ph: "Ton mot de passe local",
    unlock: "Déverrouiller",
    forgot: "Phrase de récupération",
    offline: "Hors-ligne · le coffre ne quitte jamais l'appareil",
    err: "Mot de passe incorrect",
    lang: "Langue",
    bio: "Déverrouiller par biométrie"
  },
  en: {
    name: "English",
    title: "Unlock your hub",
    sub: "Sovereign vault — everything stays on your machine.",
    pwd: "Password",
    ph: "Your local password",
    unlock: "Unlock",
    forgot: "Recovery phrase",
    offline: "Offline · the vault never leaves the device",
    err: "Incorrect password",
    lang: "Language",
    bio: "Unlock with biometrics"
  },
  es: {
    name: "Español",
    title: "Desbloquea tu hub",
    sub: "Bóveda soberana — todo se queda en tu máquina.",
    pwd: "Contraseña",
    ph: "Tu contraseña local",
    unlock: "Desbloquear",
    forgot: "Frase de recuperación",
    offline: "Sin conexión · la bóveda nunca sale del dispositivo",
    err: "Contraseña incorrecta",
    lang: "Idioma",
    bio: "Desbloquear con biometría"
  },
  de: {
    name: "Deutsch",
    title: "Entsperre dein Hub",
    sub: "Souveräner Tresor — alles bleibt auf deinem Gerät.",
    pwd: "Passwort",
    ph: "Dein lokales Passwort",
    unlock: "Entsperren",
    forgot: "Wiederherstellungsphrase",
    offline: "Offline · der Tresor verlässt das Gerät nie",
    err: "Falsches Passwort",
    lang: "Sprache",
    bio: "Mit Biometrie entsperren"
  }
};
const LANGS = ["fr", "en", "es", "de"];
const FLAG = {
  fr: "FR",
  en: "EN",
  es: "ES",
  de: "DE"
};
function LIco({
  n,
  s = 16
}) {
  return /*#__PURE__*/React.createElement("i", {
    "data-lucide": n,
    style: {
      width: s,
      height: s
    }
  });
}
function LogoMark({
  size = 60,
  animated = true
}) {
  return /*#__PURE__*/React.createElement("svg", {
    className: "lf-logmark" + (animated ? " anim" : ""),
    width: size,
    height: size,
    viewBox: "0 0 64 64",
    fill: "none",
    style: {
      overflow: "visible"
    }
  }, /*#__PURE__*/React.createElement("defs", null, /*#__PURE__*/React.createElement("linearGradient", {
    id: "loginBolt",
    x1: "26",
    y1: "12",
    x2: "40",
    y2: "40",
    gradientUnits: "userSpaceOnUse"
  }, /*#__PURE__*/React.createElement("stop", {
    offset: "0",
    stopColor: "#FFE070"
  }), /*#__PURE__*/React.createElement("stop", {
    offset: "1",
    stopColor: "#FFC22D"
  }))), /*#__PURE__*/React.createElement("g", {
    className: "anvil",
    stroke: "#15121F",
    strokeWidth: "2.4",
    strokeLinejoin: "round"
  }, /*#__PURE__*/React.createElement("path", {
    d: "M6 35 L20 31 H48 q4 0 4 3.5 Q52 39 47 39 H39 q-3 0 -4 3 l-1.5 3 H27 q-1 -3 -4 -3 H15 Q6 42 6 35 Z",
    fill: "#9A90BC"
  }), /*#__PURE__*/React.createElement("path", {
    d: "M28 45 h8 l-1.5 5 h-5 Z",
    fill: "#6F6498"
  }), /*#__PURE__*/React.createElement("path", {
    d: "M17 50 H47 l3 6 H14 Z",
    fill: "#9A90BC"
  })), /*#__PURE__*/React.createElement("g", {
    className: "hammer"
  }, /*#__PURE__*/React.createElement("rect", {
    x: "4",
    y: "29",
    width: "23",
    height: "5",
    rx: "2.5",
    fill: "#C77D4A",
    stroke: "#15121F",
    strokeWidth: "2.4",
    strokeLinejoin: "round"
  }), /*#__PURE__*/React.createElement("rect", {
    x: "25",
    y: "21",
    width: "11",
    height: "21",
    rx: "3",
    fill: "#B7BCD2",
    stroke: "#15121F",
    strokeWidth: "2.4",
    strokeLinejoin: "round"
  }), /*#__PURE__*/React.createElement("rect", {
    x: "27.5",
    y: "24",
    width: "5.5",
    height: "6",
    rx: "1.5",
    fill: "#D9DCE8"
  })), /*#__PURE__*/React.createElement("path", {
    className: "bolt",
    d: "M31 41 L40 26 H34 L42 11 L30 28 H36 Z",
    fill: "url(#loginBolt)",
    stroke: "#15121F",
    strokeWidth: "2",
    strokeLinejoin: "round"
  }));
}
function LangSwitch({
  lang,
  setLang
}) {
  return /*#__PURE__*/React.createElement("div", {
    style: {
      display: "inline-flex",
      gap: "4px",
      padding: "4px",
      background: "var(--bg-2)",
      border: "1px solid var(--border)",
      borderRadius: "var(--radius-pill)"
    }
  }, LANGS.map(l => {
    const on = lang === l;
    return /*#__PURE__*/React.createElement("button", {
      key: l,
      onClick: () => setLang(l),
      title: I18N[l].name,
      "aria-pressed": on,
      style: {
        display: "inline-flex",
        alignItems: "center",
        justifyContent: "center",
        minWidth: "38px",
        height: "30px",
        padding: "0 10px",
        borderRadius: "var(--radius-pill)",
        border: "none",
        cursor: "pointer",
        fontFamily: "var(--font-mono)",
        fontSize: "11px",
        fontWeight: 700,
        letterSpacing: "0.3px",
        background: on ? "var(--purple)" : "transparent",
        color: on ? "#fff" : "var(--text-secondary)",
        transition: "all var(--motion-fast)"
      }
    }, FLAG[l]);
  }));
}
function LoginScreen({
  onUnlock
}) {
  const PREF = window.NokidoPrefs;
  const [lang, setLang] = React.useState(() => PREF ? PREF.get("lang", "fr") : "fr");
  const setLangP = l => {
    setLang(l);
    if (PREF) PREF.set("lang", l);
  };
  const [pwd, setPwd] = React.useState("");
  const [show, setShow] = React.useState(false);
  const [err, setErr] = React.useState(false);
  const t = I18N[lang];
  React.useEffect(() => {
    if (window.lucide) lucide.createIcons();
  });
  const submit = e => {
    e && e.preventDefault();
    if (pwd.trim().length < 3) {
      setErr(true);
      return;
    }
    setErr(false);
    onUnlock && onUnlock();
  };
  return /*#__PURE__*/React.createElement("div", {
    style: {
      minHeight: "100vh",
      display: "flex",
      flexDirection: "column",
      alignItems: "center",
      justifyContent: "center",
      padding: "24px",
      boxSizing: "border-box",
      position: "relative"
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      position: "absolute",
      top: "20px",
      right: "20px",
      display: "flex",
      alignItems: "center",
      gap: "8px"
    }
  }, /*#__PURE__*/React.createElement(LIco, {
    n: "languages",
    s: 15
  }), /*#__PURE__*/React.createElement(LangSwitch, {
    lang: lang,
    setLang: setLangP
  })), /*#__PURE__*/React.createElement("form", {
    onSubmit: submit,
    style: {
      width: "100%",
      maxWidth: "380px",
      background: "var(--bg-1)",
      border: "1px solid var(--border)",
      borderRadius: "var(--radius-lg)",
      padding: "30px 26px",
      boxShadow: "var(--shadow-lg)",
      display: "flex",
      flexDirection: "column",
      alignItems: "center",
      gap: "4px"
    }
  }, /*#__PURE__*/React.createElement(LogoMark, {
    size: 62
  }), /*#__PURE__*/React.createElement("div", {
    style: {
      display: "inline-flex",
      alignItems: "center",
      gap: "8px",
      marginTop: "8px"
    }
  }, /*#__PURE__*/React.createElement("span", {
    style: {
      fontFamily: "var(--font-sans)",
      fontWeight: 800,
      fontSize: "20px",
      letterSpacing: "0.3px",
      background: "linear-gradient(90deg, var(--text-primary), #B98BFF)",
      WebkitBackgroundClip: "text",
      backgroundClip: "text",
      color: "transparent"
    }
  }, "Nokido")), /*#__PURE__*/React.createElement("h1", {
    style: {
      margin: "10px 0 4px",
      fontSize: "20px",
      fontWeight: 700,
      textAlign: "center"
    }
  }, t.title), /*#__PURE__*/React.createElement("p", {
    style: {
      margin: "0 0 6px",
      fontSize: "12.5px",
      color: "var(--text-secondary)",
      textAlign: "center",
      lineHeight: 1.45
    }
  }, t.sub), /*#__PURE__*/React.createElement("div", {
    style: {
      margin: "8px 0 14px"
    }
  }, /*#__PURE__*/React.createElement(ProvenanceBadge, {
    origin: "local",
    label: t.offline,
    size: "sm"
  })), /*#__PURE__*/React.createElement("div", {
    style: {
      width: "100%",
      position: "relative"
    }
  }, /*#__PURE__*/React.createElement(TextInput, {
    label: t.pwd,
    type: show ? "text" : "password",
    placeholder: t.ph,
    value: pwd,
    onChange: e => {
      setPwd(e.target.value);
      setErr(false);
    },
    icon: /*#__PURE__*/React.createElement(LIco, {
      n: "lock",
      s: 15
    }),
    invalid: err,
    hint: err ? t.err : null
  }), /*#__PURE__*/React.createElement("button", {
    type: "button",
    onClick: () => setShow(s => !s),
    "aria-label": "show/hide",
    style: {
      position: "absolute",
      right: "10px",
      top: "30px",
      border: "none",
      background: "transparent",
      color: "var(--text-dim)",
      cursor: "pointer",
      display: "inline-flex",
      padding: "4px"
    }
  }, /*#__PURE__*/React.createElement(LIco, {
    n: show ? "eye-off" : "eye",
    s: 16
  }))), /*#__PURE__*/React.createElement(Button, {
    variant: "primary",
    size: "lg",
    type: "submit",
    style: {
      width: "100%",
      marginTop: "16px"
    },
    iconRight: /*#__PURE__*/React.createElement(LIco, {
      n: "arrow-right",
      s: 16
    })
  }, t.unlock), /*#__PURE__*/React.createElement("button", {
    type: "button",
    onClick: submit,
    style: {
      display: "inline-flex",
      alignItems: "center",
      gap: "8px",
      marginTop: "12px",
      border: "1px solid var(--border)",
      background: "transparent",
      color: "var(--text-secondary)",
      cursor: "pointer",
      padding: "8px 14px",
      borderRadius: "var(--radius-sm)",
      fontSize: "12.5px",
      fontFamily: "var(--font-sans)"
    }
  }, /*#__PURE__*/React.createElement(LIco, {
    n: "fingerprint",
    s: 16
  }), t.bio), /*#__PURE__*/React.createElement("a", {
    href: "#",
    onClick: e => e.preventDefault(),
    style: {
      fontSize: "11.5px",
      color: "var(--text-dim)",
      marginTop: "14px",
      fontFamily: "var(--font-mono)"
    }
  }, t.forgot)), /*#__PURE__*/React.createElement("div", {
    style: {
      marginTop: "18px",
      display: "flex",
      alignItems: "center",
      gap: "8px",
      fontFamily: "var(--font-mono)",
      fontSize: "10.5px",
      color: "var(--text-dim)"
    }
  }, /*#__PURE__*/React.createElement("span", {
    className: "laforge-pulse",
    style: {
      width: "6px",
      height: "6px",
      borderRadius: "50%",
      background: "var(--prov-local)"
    }
  }), "Ring 0 \xB7 n\u0153ud souverain \xB7 v18.3"), /*#__PURE__*/React.createElement("style", null, `
        .lf-logmark.anim .hammer { transform-box: view-box; transform-origin: 6px 31px; animation: lf-swing 1.3s cubic-bezier(.5,0,.4,1) infinite; }
        .lf-logmark.anim .bolt { transform-box: view-box; transform-origin: 31px 40px; opacity:0; animation: lf-flash 1.3s linear infinite; }
        .lf-logmark.anim .anvil { transform-box: view-box; transform-origin: 32px 54px; animation: lf-squash 1.3s linear infinite; }
        @keyframes lf-swing { 0%{transform:rotate(-38deg)} 29%{transform:rotate(2deg)} 38%{transform:rotate(-5deg)} 46%{transform:rotate(0deg)} 100%{transform:rotate(-38deg)} }
        @keyframes lf-flash { 0%,26%{opacity:0;transform:scale(.4)} 31%{opacity:1;transform:scale(1.1)} 43%{opacity:1;transform:scale(1)} 58%{opacity:0} 100%{opacity:0} }
        @keyframes lf-squash { 0%,26%{transform:scaleY(1)} 31%{transform:scaleY(.93) translateY(2px)} 43%{transform:scaleY(1.02)} 50%,100%{transform:scaleY(1)} }
        @media (prefers-reduced-motion: reduce){ .lf-logmark.anim .hammer{animation:none} .lf-logmark.anim .bolt{animation:none;opacity:1} .lf-logmark.anim .anvil{animation:none} }
      `));
}
Object.assign(window, {
  LoginScreen
});
})(); } catch (e) { __ds_ns.__errors.push({ path: "ui_kits/login/login-screen.ref.jsx", error: String((e && e.message) || e) }); }

// ui_kits/onboarding/onboarding-screens.ref.jsx
try { (() => {
/* Nokido — Onboarding souverain (mobile). Étapes : accueil → niveau local/cloud
   → allocation de puissance → activation des sections → récap. */
const {
  Button,
  PowerSlider,
  SovereigntyGauge,
  ProvenanceBadge,
  Badge
} = window.NokidoDesignSystem_bdc2ac;
function OIco({
  n,
  s = 20
}) {
  return /*#__PURE__*/React.createElement("i", {
    "data-lucide": n,
    style: {
      width: s,
      height: s
    }
  });
}
const STEP_COUNT = 5;
function Progress({
  step
}) {
  return /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      gap: "6px",
      padding: "0 4px"
    }
  }, Array.from({
    length: STEP_COUNT
  }).map((_, i) => /*#__PURE__*/React.createElement("div", {
    key: i,
    style: {
      flex: 1,
      height: "4px",
      borderRadius: "var(--radius-pill)",
      background: i <= step ? "var(--purple)" : "var(--bg-3)",
      transition: "background var(--motion-base)"
    }
  })));
}
function Screen({
  children,
  footer
}) {
  return /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      flexDirection: "column",
      height: "100%",
      background: "var(--bg-0)",
      color: "var(--text-primary)"
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      flex: 1,
      overflowY: "auto",
      padding: "8px 22px 16px"
    }
  }, children), /*#__PURE__*/React.createElement("div", {
    style: {
      padding: "12px 22px calc(12px + env(safe-area-inset-bottom))",
      borderTop: "1px solid var(--border-subtle)",
      background: "var(--bg-1)"
    }
  }, footer));
}
function Eyebrow({
  children
}) {
  return /*#__PURE__*/React.createElement("div", {
    style: {
      fontFamily: "var(--font-mono)",
      fontSize: "11px",
      letterSpacing: "0.5px",
      color: "var(--purple)",
      textTransform: "uppercase",
      marginBottom: "8px"
    }
  }, children);
}
function Title({
  children
}) {
  return /*#__PURE__*/React.createElement("h1", {
    style: {
      margin: "0 0 10px",
      fontSize: "26px",
      fontWeight: 700,
      lineHeight: 1.2,
      letterSpacing: "-0.01em"
    }
  }, children);
}
function Lede({
  children
}) {
  return /*#__PURE__*/React.createElement("p", {
    style: {
      margin: "0 0 18px",
      fontSize: "14px",
      color: "var(--text-secondary)",
      lineHeight: 1.55
    }
  }, children);
}

/* 0 — Accueil */
function S0({
  onNext
}) {
  return /*#__PURE__*/React.createElement(Screen, {
    footer: /*#__PURE__*/React.createElement(Button, {
      variant: "primary",
      size: "lg",
      style: {
        width: "100%"
      },
      onClick: onNext,
      iconRight: /*#__PURE__*/React.createElement(OIco, {
        n: "arrow-right",
        s: 16
      })
    }, "Commencer")
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      flexDirection: "column",
      alignItems: "center",
      textAlign: "center",
      paddingTop: "60px"
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      width: "78px",
      height: "78px",
      borderRadius: "22px",
      background: "var(--tint-purple)",
      display: "flex",
      alignItems: "center",
      justifyContent: "center",
      fontSize: "40px",
      color: "var(--purple)",
      boxShadow: "var(--shadow-glow)",
      marginBottom: "22px"
    }
  }, "\u26A1"), /*#__PURE__*/React.createElement(Title, null, "Bienvenue dans Nokido"), /*#__PURE__*/React.createElement(Lede, null, "Ton hub personnel d'IA et de services. ", /*#__PURE__*/React.createElement("b", {
    style: {
      color: "var(--prov-local)"
    }
  }, "Local d'abord"), " : ton intention reste sur ta machine, sauf autorisation explicite."), /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      flexDirection: "column",
      gap: "10px",
      width: "100%",
      marginTop: "8px"
    }
  }, [["shield-check", "Souverain", "Ton calcul, ta machine"], ["git-fork", "Fédéré", "Un nœud parmi 8 milliards"], ["sliders-horizontal", "Composable", "Ton app, tes règles"]].map(([ic, t, d]) => /*#__PURE__*/React.createElement("div", {
    key: t,
    style: {
      display: "flex",
      alignItems: "center",
      gap: "12px",
      padding: "12px 14px",
      background: "var(--bg-2)",
      border: "1px solid var(--border)",
      borderRadius: "var(--radius-md)",
      textAlign: "left"
    }
  }, /*#__PURE__*/React.createElement("span", {
    style: {
      display: "inline-flex",
      alignItems: "center",
      justifyContent: "center",
      width: "34px",
      height: "34px",
      borderRadius: "var(--radius-sm)",
      background: "var(--tint-purple)",
      color: "var(--purple)"
    }
  }, /*#__PURE__*/React.createElement(OIco, {
    n: ic,
    s: 17
  })), /*#__PURE__*/React.createElement("div", null, /*#__PURE__*/React.createElement("div", {
    style: {
      fontSize: "13px",
      fontWeight: 600
    }
  }, t), /*#__PURE__*/React.createElement("div", {
    style: {
      fontSize: "11.5px",
      color: "var(--text-dim)"
    }
  }, d)))))));
}

/* 1 — Niveau local / cloud */
function S1({
  onNext,
  onBack,
  level,
  setLevel
}) {
  const opts = [{
    id: "local",
    icon: "house",
    color: "var(--prov-local)",
    title: "Tout local",
    desc: "100 % sur ta machine. Hors-ligne possible. Confidentialité maximale.",
    tag: "SOUVERAIN"
  }, {
    id: "hybrid",
    icon: "git-fork",
    color: "var(--prov-hybrid)",
    title: "Hybride",
    desc: "Local par défaut, cloud en renfort pour les tâches lourdes — anonymisé.",
    tag: "RECOMMANDÉ"
  }, {
    id: "cloud",
    icon: "cloud",
    color: "var(--prov-remote)",
    title: "Cloud d'abord",
    desc: "Plus de puissance, plus de coût. Externe et réversible à tout moment.",
    tag: "DISTANT"
  }];
  return /*#__PURE__*/React.createElement(Screen, {
    footer: /*#__PURE__*/React.createElement("div", {
      style: {
        display: "flex",
        gap: "10px"
      }
    }, /*#__PURE__*/React.createElement(Button, {
      variant: "ghost",
      size: "lg",
      onClick: onBack,
      icon: /*#__PURE__*/React.createElement(OIco, {
        n: "arrow-left",
        s: 16
      })
    }, "Retour"), /*#__PURE__*/React.createElement(Button, {
      variant: "primary",
      size: "lg",
      style: {
        flex: 1
      },
      onClick: onNext
    }, "Continuer"))
  }, /*#__PURE__*/React.createElement(Eyebrow, null, "\xC9tape 1 \xB7 Souverainet\xE9"), /*#__PURE__*/React.createElement(Title, null, "O\xF9 vit ton calcul ?"), /*#__PURE__*/React.createElement(Lede, null, "Tu pourras l'ajuster \xE0 tout moment \u2014 c'est un curseur, pas un choix d\xE9finitif."), /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      flexDirection: "column",
      gap: "11px"
    }
  }, opts.map(o => {
    const on = level === o.id;
    return /*#__PURE__*/React.createElement("button", {
      key: o.id,
      onClick: () => setLevel(o.id),
      style: {
        display: "flex",
        gap: "13px",
        textAlign: "left",
        padding: "15px",
        cursor: "pointer",
        borderRadius: "var(--radius-md)",
        background: on ? "var(--bg-2)" : "var(--bg-1)",
        border: `1.5px solid ${on ? o.color : "var(--border)"}`,
        boxShadow: on ? `0 0 0 1px ${o.color}, 0 0 18px color-mix(in srgb, ${o.color} 18%, transparent)` : "none",
        fontFamily: "var(--font-sans)",
        color: "var(--text-primary)",
        transition: "all var(--motion-base)"
      }
    }, /*#__PURE__*/React.createElement("span", {
      style: {
        display: "inline-flex",
        alignItems: "center",
        justifyContent: "center",
        width: "42px",
        height: "42px",
        flexShrink: 0,
        borderRadius: "var(--radius-sm)",
        background: `color-mix(in srgb, ${o.color} 16%, transparent)`,
        color: o.color
      }
    }, /*#__PURE__*/React.createElement(OIco, {
      n: o.icon,
      s: 21
    })), /*#__PURE__*/React.createElement("div", {
      style: {
        flex: 1
      }
    }, /*#__PURE__*/React.createElement("div", {
      style: {
        display: "flex",
        alignItems: "center",
        gap: "8px"
      }
    }, /*#__PURE__*/React.createElement("span", {
      style: {
        fontSize: "15px",
        fontWeight: 700
      }
    }, o.title), /*#__PURE__*/React.createElement("span", {
      style: {
        fontFamily: "var(--font-mono)",
        fontSize: "9px",
        fontWeight: 700,
        letterSpacing: "0.3px",
        color: o.color,
        border: `1px solid ${o.color}`,
        borderRadius: "4px",
        padding: "1px 5px"
      }
    }, o.tag)), /*#__PURE__*/React.createElement("div", {
      style: {
        fontSize: "12px",
        color: "var(--text-secondary)",
        lineHeight: 1.45,
        marginTop: "4px"
      }
    }, o.desc)), /*#__PURE__*/React.createElement("span", {
      style: {
        alignSelf: "center",
        color: on ? o.color : "var(--text-disabled)"
      }
    }, /*#__PURE__*/React.createElement(OIco, {
      n: on ? "check-circle-2" : "circle",
      s: 20
    })));
  })));
}

/* 2 — Allocation de puissance */
function S2({
  onNext,
  onBack,
  power,
  setPower
}) {
  return /*#__PURE__*/React.createElement(Screen, {
    footer: /*#__PURE__*/React.createElement("div", {
      style: {
        display: "flex",
        gap: "10px"
      }
    }, /*#__PURE__*/React.createElement(Button, {
      variant: "ghost",
      size: "lg",
      onClick: onBack,
      icon: /*#__PURE__*/React.createElement(OIco, {
        n: "arrow-left",
        s: 16
      })
    }, "Retour"), /*#__PURE__*/React.createElement(Button, {
      variant: "primary",
      size: "lg",
      style: {
        flex: 1
      },
      onClick: onNext
    }, "Continuer"))
  }, /*#__PURE__*/React.createElement(Eyebrow, null, "\xC9tape 2 \xB7 Puissance"), /*#__PURE__*/React.createElement(Title, null, "Puissance allou\xE9e"), /*#__PURE__*/React.createElement(Lede, null, "Plus tu alloues de puissance locale, plus Nokido reste souverain tout en restant rapide. Le compromis se lit en direct."), /*#__PURE__*/React.createElement(PowerSlider, {
    value: power,
    onChange: setPower
  }), /*#__PURE__*/React.createElement("div", {
    style: {
      marginTop: "16px",
      padding: "13px 15px",
      background: "var(--prov-local-tint)",
      border: "1px solid var(--border-subtle)",
      borderRadius: "var(--radius-md)",
      display: "flex",
      gap: "10px"
    }
  }, /*#__PURE__*/React.createElement("span", {
    style: {
      color: "var(--prov-local)"
    }
  }, /*#__PURE__*/React.createElement(OIco, {
    n: "info",
    s: 17
  })), /*#__PURE__*/React.createElement("div", {
    style: {
      fontSize: "12px",
      color: "var(--text-secondary)",
      lineHeight: 1.5
    }
  }, "Cascade : ", /*#__PURE__*/React.createElement("b", {
    style: {
      color: "var(--prov-local)"
    }
  }, "NPU \u2192 iGPU \u2192 Ollama local"), " \u2192 cloud en dernier recours. Ta machine traite ", power, "% des requ\xEAtes.")));
}

/* 3 — Activer les sections */
function S3({
  onNext,
  onBack,
  enabled,
  toggle
}) {
  const mods = [{
    id: "sante",
    domain: "sante",
    icon: "heart-pulse",
    title: "Santé",
    note: "local forcé"
  }, {
    id: "domotique",
    domain: "domotique",
    icon: "house",
    title: "Domotique",
    note: "local-first"
  }, {
    id: "transport",
    domain: "transport",
    icon: "route",
    title: "Transport",
    note: "temps réel"
  }, {
    id: "finance",
    domain: "finance",
    icon: "wallet",
    title: "Finance",
    note: "traçable"
  }, {
    id: "creation",
    domain: "creation",
    icon: "sparkles",
    title: "Création",
    note: "atelier"
  }, {
    id: "dev",
    domain: "dev",
    icon: "terminal",
    title: "Dev",
    note: "skills & MCP"
  }];
  const count = mods.filter(m => enabled[m.id]).length;
  return /*#__PURE__*/React.createElement(Screen, {
    footer: /*#__PURE__*/React.createElement("div", {
      style: {
        display: "flex",
        gap: "10px"
      }
    }, /*#__PURE__*/React.createElement(Button, {
      variant: "ghost",
      size: "lg",
      onClick: onBack,
      icon: /*#__PURE__*/React.createElement(OIco, {
        n: "arrow-left",
        s: 16
      })
    }, "Retour"), /*#__PURE__*/React.createElement(Button, {
      variant: "primary",
      size: "lg",
      style: {
        flex: 1
      },
      onClick: onNext
    }, "Activer ", count, " section", count > 1 ? "s" : ""))
  }, /*#__PURE__*/React.createElement(Eyebrow, null, "\xC9tape 3 \xB7 Sections"), /*#__PURE__*/React.createElement(Title, null, "Compose ton app"), /*#__PURE__*/React.createElement(Lede, null, "Active tes premi\xE8res sections. Tu pourras en ajouter, r\xE9organiser ou masquer plus tard."), /*#__PURE__*/React.createElement("div", {
    style: {
      display: "grid",
      gridTemplateColumns: "1fr 1fr",
      gap: "10px"
    }
  }, mods.map(m => {
    const on = !!enabled[m.id];
    const accent = `var(--domain-${m.domain})`;
    return /*#__PURE__*/React.createElement("button", {
      key: m.id,
      onClick: () => toggle(m.id),
      style: {
        position: "relative",
        textAlign: "left",
        padding: "13px",
        cursor: "pointer",
        borderRadius: "var(--radius-md)",
        background: on ? "var(--bg-2)" : "var(--bg-1)",
        border: `1px solid ${on ? accent : "var(--border)"}`,
        fontFamily: "var(--font-sans)",
        color: "var(--text-primary)",
        overflow: "hidden",
        transition: "all var(--motion-base)"
      }
    }, /*#__PURE__*/React.createElement("div", {
      style: {
        position: "absolute",
        left: 0,
        top: 0,
        bottom: 0,
        width: "3px",
        background: on ? accent : "transparent"
      }
    }), /*#__PURE__*/React.createElement("div", {
      style: {
        display: "flex",
        alignItems: "center",
        justifyContent: "space-between"
      }
    }, /*#__PURE__*/React.createElement("span", {
      style: {
        display: "inline-flex",
        alignItems: "center",
        justifyContent: "center",
        width: "34px",
        height: "34px",
        borderRadius: "var(--radius-sm)",
        background: `color-mix(in srgb, ${accent} 16%, transparent)`,
        color: accent
      }
    }, /*#__PURE__*/React.createElement(OIco, {
      n: m.icon,
      s: 17
    })), /*#__PURE__*/React.createElement("span", {
      style: {
        color: on ? accent : "var(--text-disabled)"
      }
    }, /*#__PURE__*/React.createElement(OIco, {
      n: on ? "check-circle-2" : "circle",
      s: 18
    }))), /*#__PURE__*/React.createElement("div", {
      style: {
        fontSize: "13.5px",
        fontWeight: 700,
        marginTop: "9px"
      }
    }, m.title), /*#__PURE__*/React.createElement("div", {
      style: {
        fontFamily: "var(--font-mono)",
        fontSize: "10px",
        color: "var(--text-dim)"
      }
    }, m.note));
  })));
}

/* 4 — Récap */
function S4({
  onBack,
  onDone,
  level,
  power,
  enabled
}) {
  const labels = {
    local: "Tout local",
    hybrid: "Hybride",
    cloud: "Cloud d'abord"
  };
  const origin = level === "cloud" ? "remote" : level === "hybrid" ? "hybrid" : "local";
  const count = Object.values(enabled).filter(Boolean).length;
  return /*#__PURE__*/React.createElement(Screen, {
    footer: /*#__PURE__*/React.createElement("div", {
      style: {
        display: "flex",
        gap: "10px"
      }
    }, /*#__PURE__*/React.createElement(Button, {
      variant: "ghost",
      size: "lg",
      onClick: onBack,
      icon: /*#__PURE__*/React.createElement(OIco, {
        n: "arrow-left",
        s: 16
      })
    }, "Retour"), /*#__PURE__*/React.createElement(Button, {
      variant: "success",
      size: "lg",
      style: {
        flex: 1
      },
      onClick: onDone,
      iconRight: /*#__PURE__*/React.createElement(OIco, {
        n: "arrow-right",
        s: 16
      })
    }, "Entrer dans le hub"))
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      flexDirection: "column",
      alignItems: "center",
      textAlign: "center",
      paddingTop: "20px"
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      width: "64px",
      height: "64px",
      borderRadius: "50%",
      background: "var(--tint-green)",
      color: "var(--prov-local)",
      display: "flex",
      alignItems: "center",
      justifyContent: "center",
      marginBottom: "16px",
      boxShadow: "var(--prov-local-glow)"
    }
  }, /*#__PURE__*/React.createElement(OIco, {
    n: "check",
    s: 30
  })), /*#__PURE__*/React.createElement(Title, null, "Ton n\u0153ud est pr\xEAt"), /*#__PURE__*/React.createElement(Lede, null, "Voici ta configuration souveraine. Tout reste modifiable \xE0 tout moment.")), /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      flexDirection: "column",
      gap: "10px"
    }
  }, /*#__PURE__*/React.createElement(Row, {
    label: "Niveau",
    value: labels[level],
    right: /*#__PURE__*/React.createElement(ProvenanceBadge, {
      origin: origin,
      size: "sm"
    })
  }), /*#__PURE__*/React.createElement(Row, {
    label: "Puissance locale",
    value: `${power}%`,
    right: /*#__PURE__*/React.createElement(SovereigntyGauge, {
      local: power,
      label: null,
      showLegend: false,
      height: 6,
      style: {
        width: "90px"
      }
    })
  }), /*#__PURE__*/React.createElement(Row, {
    label: "Sections actives",
    value: `${count} activée${count > 1 ? "s" : ""}`,
    right: /*#__PURE__*/React.createElement(Badge, {
      color: "purple",
      mono: true
    }, count)
  })));
}
function Row({
  label,
  value,
  right
}) {
  return /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      alignItems: "center",
      gap: "12px",
      padding: "13px 15px",
      background: "var(--bg-2)",
      border: "1px solid var(--border)",
      borderRadius: "var(--radius-md)"
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      flex: 1
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      fontFamily: "var(--font-mono)",
      fontSize: "10px",
      textTransform: "uppercase",
      letterSpacing: "0.5px",
      color: "var(--text-dim)"
    }
  }, label), /*#__PURE__*/React.createElement("div", {
    style: {
      fontSize: "14px",
      fontWeight: 600,
      marginTop: "2px"
    }
  }, value)), right);
}
Object.assign(window, {
  OnbProgress: Progress,
  OnbS0: S0,
  OnbS1: S1,
  OnbS2: S2,
  OnbS3: S3,
  OnbS4: S4
});
})(); } catch (e) { __ds_ns.__errors.push({ path: "ui_kits/onboarding/onboarding-screens.ref.jsx", error: String((e && e.message) || e) }); }

// ui_kits/onboarding/ios-frame.jsx
try { (() => {
// @ds-adherence-ignore -- omelette starter scaffold (raw elements/hex/px by design)

/* BEGIN USAGE */
// iOS.jsx — Simplified iOS 26 (Liquid Glass) device frame
// Based on the iOS 26 UI Kit + Figma status bar spec. No assets, no deps.
// Exports (to window): IOSDevice, IOSStatusBar, IOSNavBar, IOSGlassPill, IOSList, IOSListRow, IOSKeyboard
//
// Usage — wrap your screen content in <IOSDevice> to get the bezel, status bar
// and home indicator (props: title, dark, keyboard):
//
//   <IOSDevice title="Settings">
//     ...your screen content...
//   </IOSDevice>
//   <IOSDevice dark title="Search" keyboard>…</IOSDevice>
/* END USAGE */

// ─────────────────────────────────────────────────────────────
// Status bar
// ─────────────────────────────────────────────────────────────
function IOSStatusBar({
  dark = false,
  time = '9:41'
}) {
  const c = dark ? '#fff' : '#000';
  return /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      gap: 154,
      alignItems: 'center',
      justifyContent: 'center',
      padding: '21px 24px 19px',
      boxSizing: 'border-box',
      position: 'relative',
      zIndex: 20,
      width: '100%'
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      flex: 1,
      height: 22,
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'center',
      paddingTop: 1.5
    }
  }, /*#__PURE__*/React.createElement("span", {
    style: {
      fontFamily: '-apple-system, "SF Pro", system-ui',
      fontWeight: 590,
      fontSize: 17,
      lineHeight: '22px',
      color: c
    }
  }, time)), /*#__PURE__*/React.createElement("div", {
    style: {
      flex: 1,
      height: 22,
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'center',
      gap: 7,
      paddingTop: 1,
      paddingRight: 1
    }
  }, /*#__PURE__*/React.createElement("svg", {
    width: "19",
    height: "12",
    viewBox: "0 0 19 12"
  }, /*#__PURE__*/React.createElement("rect", {
    x: "0",
    y: "7.5",
    width: "3.2",
    height: "4.5",
    rx: "0.7",
    fill: c
  }), /*#__PURE__*/React.createElement("rect", {
    x: "4.8",
    y: "5",
    width: "3.2",
    height: "7",
    rx: "0.7",
    fill: c
  }), /*#__PURE__*/React.createElement("rect", {
    x: "9.6",
    y: "2.5",
    width: "3.2",
    height: "9.5",
    rx: "0.7",
    fill: c
  }), /*#__PURE__*/React.createElement("rect", {
    x: "14.4",
    y: "0",
    width: "3.2",
    height: "12",
    rx: "0.7",
    fill: c
  })), /*#__PURE__*/React.createElement("svg", {
    width: "17",
    height: "12",
    viewBox: "0 0 17 12"
  }, /*#__PURE__*/React.createElement("path", {
    d: "M8.5 3.2C10.8 3.2 12.9 4.1 14.4 5.6L15.5 4.5C13.7 2.7 11.2 1.5 8.5 1.5C5.8 1.5 3.3 2.7 1.5 4.5L2.6 5.6C4.1 4.1 6.2 3.2 8.5 3.2Z",
    fill: c
  }), /*#__PURE__*/React.createElement("path", {
    d: "M8.5 6.8C9.9 6.8 11.1 7.3 12 8.2L13.1 7.1C11.8 5.9 10.2 5.1 8.5 5.1C6.8 5.1 5.2 5.9 3.9 7.1L5 8.2C5.9 7.3 7.1 6.8 8.5 6.8Z",
    fill: c
  }), /*#__PURE__*/React.createElement("circle", {
    cx: "8.5",
    cy: "10.5",
    r: "1.5",
    fill: c
  })), /*#__PURE__*/React.createElement("svg", {
    width: "27",
    height: "13",
    viewBox: "0 0 27 13"
  }, /*#__PURE__*/React.createElement("rect", {
    x: "0.5",
    y: "0.5",
    width: "23",
    height: "12",
    rx: "3.5",
    stroke: c,
    strokeOpacity: "0.35",
    fill: "none"
  }), /*#__PURE__*/React.createElement("rect", {
    x: "2",
    y: "2",
    width: "20",
    height: "9",
    rx: "2",
    fill: c
  }), /*#__PURE__*/React.createElement("path", {
    d: "M25 4.5V8.5C25.8 8.2 26.5 7.2 26.5 6.5C26.5 5.8 25.8 4.8 25 4.5Z",
    fill: c,
    fillOpacity: "0.4"
  }))));
}

// ─────────────────────────────────────────────────────────────
// Liquid glass pill — blur + tint + shine
// ─────────────────────────────────────────────────────────────
function IOSGlassPill({
  children,
  dark = false,
  style = {}
}) {
  return /*#__PURE__*/React.createElement("div", {
    style: {
      height: 44,
      minWidth: 44,
      borderRadius: 9999,
      position: 'relative',
      overflow: 'hidden',
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'center',
      boxShadow: dark ? '0 2px 6px rgba(0,0,0,0.35), 0 6px 16px rgba(0,0,0,0.2)' : '0 1px 3px rgba(0,0,0,0.07), 0 3px 10px rgba(0,0,0,0.06)',
      ...style
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      position: 'absolute',
      inset: 0,
      borderRadius: 9999,
      backdropFilter: 'blur(12px) saturate(180%)',
      WebkitBackdropFilter: 'blur(12px) saturate(180%)',
      background: dark ? 'rgba(120,120,128,0.28)' : 'rgba(255,255,255,0.5)'
    }
  }), /*#__PURE__*/React.createElement("div", {
    style: {
      position: 'absolute',
      inset: 0,
      borderRadius: 9999,
      boxShadow: dark ? 'inset 1.5px 1.5px 1px rgba(255,255,255,0.15), inset -1px -1px 1px rgba(255,255,255,0.08)' : 'inset 1.5px 1.5px 1px rgba(255,255,255,0.7), inset -1px -1px 1px rgba(255,255,255,0.4)',
      border: dark ? '0.5px solid rgba(255,255,255,0.15)' : '0.5px solid rgba(0,0,0,0.06)'
    }
  }), /*#__PURE__*/React.createElement("div", {
    style: {
      position: 'relative',
      zIndex: 1,
      display: 'flex',
      alignItems: 'center',
      padding: '0 4px'
    }
  }, children));
}

// ─────────────────────────────────────────────────────────────
// Navigation bar — glass pills + large title
// ─────────────────────────────────────────────────────────────
function IOSNavBar({
  title = 'Title',
  dark = false,
  trailingIcon = true
}) {
  const muted = dark ? 'rgba(255,255,255,0.6)' : '#404040';
  const text = dark ? '#fff' : '#000';
  const pillIcon = content => /*#__PURE__*/React.createElement(IOSGlassPill, {
    dark: dark
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      width: 36,
      height: 36,
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'center'
    }
  }, content));
  return /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      flexDirection: 'column',
      gap: 10,
      paddingTop: 62,
      paddingBottom: 10,
      position: 'relative',
      zIndex: 5
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'space-between',
      padding: '0 16px'
    }
  }, pillIcon(/*#__PURE__*/React.createElement("svg", {
    width: "12",
    height: "20",
    viewBox: "0 0 12 20",
    fill: "none",
    style: {
      marginLeft: -1
    }
  }, /*#__PURE__*/React.createElement("path", {
    d: "M10 2L2 10l8 8",
    stroke: muted,
    strokeWidth: "2.5",
    strokeLinecap: "round",
    strokeLinejoin: "round"
  }))), trailingIcon && pillIcon(/*#__PURE__*/React.createElement("svg", {
    width: "22",
    height: "6",
    viewBox: "0 0 22 6"
  }, /*#__PURE__*/React.createElement("circle", {
    cx: "3",
    cy: "3",
    r: "2.5",
    fill: muted
  }), /*#__PURE__*/React.createElement("circle", {
    cx: "11",
    cy: "3",
    r: "2.5",
    fill: muted
  }), /*#__PURE__*/React.createElement("circle", {
    cx: "19",
    cy: "3",
    r: "2.5",
    fill: muted
  })))), /*#__PURE__*/React.createElement("div", {
    style: {
      padding: '0 16px',
      fontFamily: '-apple-system, system-ui',
      fontSize: 34,
      fontWeight: 700,
      lineHeight: '41px',
      color: text,
      letterSpacing: 0.4
    }
  }, title));
}

// ─────────────────────────────────────────────────────────────
// Grouped list (inset card, r:26) + row (52px)
// ─────────────────────────────────────────────────────────────
function IOSListRow({
  title,
  detail,
  icon,
  chevron = true,
  isLast = false,
  dark = false
}) {
  const text = dark ? '#fff' : '#000';
  const sec = dark ? 'rgba(235,235,245,0.6)' : 'rgba(60,60,67,0.6)';
  const ter = dark ? 'rgba(235,235,245,0.3)' : 'rgba(60,60,67,0.3)';
  const sep = dark ? 'rgba(84,84,88,0.65)' : 'rgba(60,60,67,0.12)';
  return /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      alignItems: 'center',
      minHeight: 52,
      padding: '0 16px',
      position: 'relative',
      fontFamily: '-apple-system, system-ui',
      fontSize: 17,
      letterSpacing: -0.43
    }
  }, icon && /*#__PURE__*/React.createElement("div", {
    style: {
      width: 30,
      height: 30,
      borderRadius: 7,
      background: icon,
      marginRight: 12,
      flexShrink: 0
    }
  }), /*#__PURE__*/React.createElement("div", {
    style: {
      flex: 1,
      color: text
    }
  }, title), detail && /*#__PURE__*/React.createElement("span", {
    style: {
      color: sec,
      marginRight: 6
    }
  }, detail), chevron && /*#__PURE__*/React.createElement("svg", {
    width: "8",
    height: "14",
    viewBox: "0 0 8 14",
    style: {
      flexShrink: 0
    }
  }, /*#__PURE__*/React.createElement("path", {
    d: "M1 1l6 6-6 6",
    stroke: ter,
    strokeWidth: "2",
    fill: "none",
    strokeLinecap: "round",
    strokeLinejoin: "round"
  })), !isLast && /*#__PURE__*/React.createElement("div", {
    style: {
      position: 'absolute',
      bottom: 0,
      right: 0,
      left: icon ? 58 : 16,
      height: 0.5,
      background: sep
    }
  }));
}
function IOSList({
  header,
  children,
  dark = false
}) {
  const hc = dark ? 'rgba(235,235,245,0.6)' : 'rgba(60,60,67,0.6)';
  const bg = dark ? '#1C1C1E' : '#fff';
  return /*#__PURE__*/React.createElement("div", null, header && /*#__PURE__*/React.createElement("div", {
    style: {
      fontFamily: '-apple-system, system-ui',
      fontSize: 13,
      color: hc,
      textTransform: 'uppercase',
      padding: '8px 36px 6px',
      letterSpacing: -0.08
    }
  }, header), /*#__PURE__*/React.createElement("div", {
    style: {
      background: bg,
      borderRadius: 26,
      margin: '0 16px',
      overflow: 'hidden'
    }
  }, children));
}

// ─────────────────────────────────────────────────────────────
// Device frame
// ─────────────────────────────────────────────────────────────
function IOSDevice({
  children,
  width = 402,
  height = 874,
  dark = false,
  title,
  keyboard = false
}) {
  return /*#__PURE__*/React.createElement("div", {
    style: {
      width,
      height,
      borderRadius: 48,
      overflow: 'hidden',
      position: 'relative',
      background: dark ? '#000' : '#F2F2F7',
      boxShadow: '0 40px 80px rgba(0,0,0,0.18), 0 0 0 1px rgba(0,0,0,0.12)',
      fontFamily: '-apple-system, system-ui, sans-serif',
      WebkitFontSmoothing: 'antialiased'
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      position: 'absolute',
      top: 11,
      left: '50%',
      transform: 'translateX(-50%)',
      width: 126,
      height: 37,
      borderRadius: 24,
      background: '#000',
      zIndex: 50
    }
  }), /*#__PURE__*/React.createElement("div", {
    style: {
      position: 'absolute',
      top: 0,
      left: 0,
      right: 0,
      zIndex: 10
    }
  }, /*#__PURE__*/React.createElement(IOSStatusBar, {
    dark: dark
  })), /*#__PURE__*/React.createElement("div", {
    style: {
      height: '100%',
      display: 'flex',
      flexDirection: 'column'
    }
  }, title !== undefined && /*#__PURE__*/React.createElement(IOSNavBar, {
    title: title,
    dark: dark
  }), /*#__PURE__*/React.createElement("div", {
    style: {
      flex: 1,
      overflow: 'auto'
    }
  }, children), keyboard && /*#__PURE__*/React.createElement(IOSKeyboard, {
    dark: dark
  })), /*#__PURE__*/React.createElement("div", {
    style: {
      position: 'absolute',
      bottom: 0,
      left: 0,
      right: 0,
      zIndex: 60,
      height: 34,
      display: 'flex',
      justifyContent: 'center',
      alignItems: 'flex-end',
      paddingBottom: 8,
      pointerEvents: 'none'
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      width: 139,
      height: 5,
      borderRadius: 100,
      background: dark ? 'rgba(255,255,255,0.7)' : 'rgba(0,0,0,0.25)'
    }
  })));
}

// ─────────────────────────────────────────────────────────────
// Keyboard — iOS 26 liquid glass
// ─────────────────────────────────────────────────────────────
function IOSKeyboard({
  dark = false
}) {
  const glyph = dark ? 'rgba(255,255,255,0.7)' : '#595959';
  const sugg = dark ? 'rgba(255,255,255,0.6)' : '#333';
  const keyBg = dark ? 'rgba(255,255,255,0.22)' : 'rgba(255,255,255,0.85)';

  // special-key icons
  const icons = {
    shift: /*#__PURE__*/React.createElement("svg", {
      width: "19",
      height: "17",
      viewBox: "0 0 19 17"
    }, /*#__PURE__*/React.createElement("path", {
      d: "M9.5 1L1 9.5h4.5V16h8V9.5H18L9.5 1z",
      fill: glyph
    })),
    del: /*#__PURE__*/React.createElement("svg", {
      width: "23",
      height: "17",
      viewBox: "0 0 23 17"
    }, /*#__PURE__*/React.createElement("path", {
      d: "M7 1h13a2 2 0 012 2v11a2 2 0 01-2 2H7l-6-7.5L7 1z",
      fill: "none",
      stroke: glyph,
      strokeWidth: "1.6",
      strokeLinejoin: "round"
    }), /*#__PURE__*/React.createElement("path", {
      d: "M10 5l7 7M17 5l-7 7",
      stroke: glyph,
      strokeWidth: "1.6",
      strokeLinecap: "round"
    })),
    ret: /*#__PURE__*/React.createElement("svg", {
      width: "20",
      height: "14",
      viewBox: "0 0 20 14"
    }, /*#__PURE__*/React.createElement("path", {
      d: "M18 1v6H4m0 0l4-4M4 7l4 4",
      fill: "none",
      stroke: "#fff",
      strokeWidth: "1.8",
      strokeLinecap: "round",
      strokeLinejoin: "round"
    }))
  };
  const key = (content, {
    w,
    flex,
    ret,
    fs = 25,
    k
  } = {}) => /*#__PURE__*/React.createElement("div", {
    key: k,
    style: {
      height: 42,
      borderRadius: 8.5,
      flex: flex ? 1 : undefined,
      width: w,
      minWidth: 0,
      background: ret ? '#08f' : keyBg,
      boxShadow: '0 1px 0 rgba(0,0,0,0.075)',
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'center',
      fontFamily: '-apple-system, "SF Compact", system-ui',
      fontSize: fs,
      fontWeight: 458,
      color: ret ? '#fff' : glyph
    }
  }, content);
  const row = (keys, pad = 0) => /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      gap: 6.5,
      justifyContent: 'center',
      padding: `0 ${pad}px`
    }
  }, keys.map(l => key(l, {
    flex: true,
    k: l
  })));
  return /*#__PURE__*/React.createElement("div", {
    style: {
      position: 'relative',
      zIndex: 15,
      borderRadius: 27,
      overflow: 'hidden',
      padding: '11px 0 2px',
      display: 'flex',
      flexDirection: 'column',
      alignItems: 'center',
      boxShadow: dark ? '0 -2px 20px rgba(0,0,0,0.09)' : '0 -1px 6px rgba(0,0,0,0.018), 0 -3px 20px rgba(0,0,0,0.012)'
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      position: 'absolute',
      inset: 0,
      borderRadius: 27,
      backdropFilter: 'blur(12px) saturate(180%)',
      WebkitBackdropFilter: 'blur(12px) saturate(180%)',
      background: dark ? 'rgba(120,120,128,0.14)' : 'rgba(255,255,255,0.25)'
    }
  }), /*#__PURE__*/React.createElement("div", {
    style: {
      position: 'absolute',
      inset: 0,
      borderRadius: 27,
      boxShadow: dark ? 'inset 1.5px 1.5px 1px rgba(255,255,255,0.15)' : 'inset 1.5px 1.5px 1px rgba(255,255,255,0.7), inset -1px -1px 1px rgba(255,255,255,0.4)',
      border: dark ? '0.5px solid rgba(255,255,255,0.15)' : '0.5px solid rgba(0,0,0,0.06)',
      pointerEvents: 'none'
    }
  }), /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      gap: 20,
      alignItems: 'center',
      padding: '8px 22px 13px',
      width: '100%',
      boxSizing: 'border-box',
      position: 'relative'
    }
  }, ['"The"', 'the', 'to'].map((w, i) => /*#__PURE__*/React.createElement(React.Fragment, {
    key: i
  }, i > 0 && /*#__PURE__*/React.createElement("div", {
    style: {
      width: 1,
      height: 25,
      background: '#ccc',
      opacity: 0.3
    }
  }), /*#__PURE__*/React.createElement("div", {
    style: {
      flex: 1,
      textAlign: 'center',
      fontFamily: '-apple-system, system-ui',
      fontSize: 17,
      color: sugg,
      letterSpacing: -0.43,
      lineHeight: '22px'
    }
  }, w)))), /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      flexDirection: 'column',
      gap: 13,
      padding: '0 6.5px',
      width: '100%',
      boxSizing: 'border-box',
      position: 'relative'
    }
  }, row(['q', 'w', 'e', 'r', 't', 'y', 'u', 'i', 'o', 'p']), row(['a', 's', 'd', 'f', 'g', 'h', 'j', 'k', 'l'], 20), /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      gap: 14.25,
      alignItems: 'center'
    }
  }, key(icons.shift, {
    w: 45,
    k: 'shift'
  }), /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      gap: 6.5,
      flex: 1
    }
  }, ['z', 'x', 'c', 'v', 'b', 'n', 'm'].map(l => key(l, {
    flex: true,
    k: l
  }))), key(icons.del, {
    w: 45,
    k: 'del'
  })), /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      gap: 6,
      alignItems: 'center'
    }
  }, key('ABC', {
    w: 92.25,
    fs: 18,
    k: 'abc'
  }), key('', {
    flex: true,
    k: 'space'
  }), key(icons.ret, {
    w: 92.25,
    ret: true,
    k: 'ret'
  }))), /*#__PURE__*/React.createElement("div", {
    style: {
      height: 56,
      width: '100%',
      position: 'relative'
    }
  }));
}
Object.assign(window, {
  IOSDevice,
  IOSStatusBar,
  IOSNavBar,
  IOSGlassPill,
  IOSList,
  IOSListRow,
  IOSKeyboard
});
})(); } catch (e) { __ds_ns.__errors.push({ path: "ui_kits/onboarding/ios-frame.jsx", error: String((e && e.message) || e) }); }

// ui_kits/webhub/web-hub.ref.jsx
try { (() => {
/* Nokido — Web Hub modernisé : recréation du portail réel (:7400) avec le DS.
   Portail de services + Chat (ask) + Event Feed (audit), provenance partout. */
const {
  Card,
  Badge,
  StatusPill,
  Button,
  ProvenanceBadge,
  TextInput,
  Select
} = window.NokidoDesignSystem_bdc2ac;
const WPREF = window.NokidoPrefs;
function WIco({
  n,
  s = 18
}) {
  return /*#__PURE__*/React.createElement("i", {
    "data-lucide": n,
    style: {
      width: s,
      height: s
    }
  });
}

/* Tweaks partagés (lus par les vues ci-dessous). Mis à jour par <WebHub t={…}>. */
let TW = {
  accent: "#774AFF",
  density: "confort",
  provenance: true,
  quicklinks: true,
  mcpPanel: true,
  motion: true
};
const pad = (comfy, compact) => TW.density === "compact" ? compact : comfy;

/* Services réels du hub (dashboard.html) */
const SERVICES = [{
  slug: "chat",
  title: "Chat / Ask",
  desc: "Dialogue multi-fournisseurs",
  icon: "message-square",
  color: "purple",
  prov: "local",
  status: "up",
  target: "/sidebar"
}, {
  slug: "rag",
  title: "RAG Dashboard",
  desc: "Embeddings & recherche locale",
  icon: "database",
  color: "green",
  prov: "local",
  status: "up",
  target: "/rag"
}, {
  slug: "network",
  title: "Network Graph",
  desc: "Graphe de connaissances",
  icon: "share-2",
  color: "blue",
  prov: "local",
  status: "up",
  target: "/network"
}, {
  slug: "mcp_lab",
  title: "MCP Lab",
  desc: "Outils & serveurs MCP",
  icon: "blocks",
  color: "cyan",
  prov: "hybrid",
  status: "up",
  target: "/mcp_lab/"
}, {
  slug: "swarm",
  title: "Swarm",
  desc: "Essaim d'agents",
  icon: "boxes",
  color: "orange",
  prov: "hybrid",
  status: "up",
  target: "/swarm"
}, {
  slug: "debate",
  title: "LLM Debate",
  desc: "Débat contradictoire multi-modèles",
  icon: "messages-square",
  color: "pink",
  prov: "remote",
  status: "up",
  target: "/llm_debate"
}, {
  slug: "anatomy",
  title: "Anatomie Live",
  desc: "Organes & flux en temps réel",
  icon: "activity",
  color: "green",
  prov: "local",
  status: "up",
  target: "/anatomy"
}, {
  slug: "feed",
  title: "Event Feed",
  desc: "Journal d'audit (bus d'événements)",
  icon: "scroll-text",
  color: "yellow",
  prov: "local",
  status: "up",
  target: "/forge/feed"
}, {
  slug: "launcher",
  title: "Launcher",
  desc: "Pilotage des modules",
  icon: "rocket",
  color: "purple",
  prov: "local",
  status: "up",
  target: "/launcher"
}, {
  slug: "reports",
  title: "CTF Reports",
  desc: "Rapports & traces",
  icon: "flag",
  color: "red",
  prov: "local",
  status: "up",
  target: "/reports/",
  ext: true
}, {
  slug: "epistemic",
  title: "Épistémique",
  desc: "Incertitude & calibration",
  icon: "brain-circuit",
  color: "blue",
  prov: "hybrid",
  status: "warn",
  target: "/epistemic"
}, {
  slug: "setup",
  title: "Setup souverain",
  desc: "Scan machine, profils, tiers DB, lancement",
  icon: "sliders-horizontal",
  color: "purple",
  prov: "local",
  status: "up",
  target: "/setup"
}, {
  slug: "rings",
  title: "Rings",
  desc: "Placement des agents sur les 11 anneaux",
  icon: "target",
  color: "green",
  prov: "local",
  status: "up",
  target: "/rings"
}, {
  slug: "pipeline",
  title: "Pipeline souverain",
  desc: "CI local-first, cloud en fallback",
  icon: "git-pull-request",
  color: "green",
  prov: "local",
  status: "up",
  target: "/pipeline"
}, {
  slug: "recon",
  title: "Recon",
  desc: "Reconnaissance (non déployé)",
  icon: "radar",
  color: "cyan",
  prov: "local",
  coming: true,
  target: "/recon"
}];
const QUICK = [["Setup souverain", "setup"], ["Rings", "rings"], ["Launcher", "launcher"], ["Pipeline", "pipeline"], ["Swarm", "swarm"], ["LLM Debate", "debate"], ["MCP Lab", "mcp"], ["Network", "network"], ["RAG", "rag"], ["Status JSON", "status"]];
const GO = v => {
  if (window.__WH_GO) window.__WH_GO(v);
};
const COLOR_VAR = {
  purple: "--purple",
  blue: "--blue",
  cyan: "--cyan",
  green: "--green",
  yellow: "--yellow",
  orange: "--orange",
  red: "--red",
  pink: "--pink"
};
const SLUG_VIEW = {
  chat: "chat",
  rag: "rag",
  feed: "feed",
  launcher: "launcher",
  reports: "reports",
  epistemic: "epistemic",
  pipeline: "pipeline",
  swarm: "swarm",
  debate: "debate",
  network: "network",
  mcp_lab: "mcp",
  setup: "setup",
  rings: "rings"
};

/* ---------------- Portail ---------------- */
function Portail() {
  return /*#__PURE__*/React.createElement("div", {
    style: {
      maxWidth: "1180px",
      margin: "0 auto"
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      gap: "8px",
      flexWrap: "wrap",
      marginBottom: "18px",
      display: TW.quicklinks ? "flex" : "none"
    }
  }, QUICK.map(([q, v]) => /*#__PURE__*/React.createElement("button", {
    key: q,
    onClick: () => GO(v),
    style: {
      padding: "6px 12px",
      border: "1px solid var(--border)",
      background: "transparent",
      cursor: "pointer",
      borderRadius: "var(--radius-sm)",
      color: "var(--text-secondary)",
      fontSize: "12.5px",
      fontFamily: "var(--font-sans)",
      transition: "all var(--motion-fast)"
    },
    onMouseEnter: e => {
      e.currentTarget.style.borderColor = "var(--purple)";
      e.currentTarget.style.color = "var(--purple)";
    },
    onMouseLeave: e => {
      e.currentTarget.style.borderColor = "var(--border)";
      e.currentTarget.style.color = "var(--text-secondary)";
    }
  }, q))), /*#__PURE__*/React.createElement("div", {
    style: {
      display: "grid",
      gridTemplateColumns: `repeat(auto-fill, minmax(280px, 1fr))`,
      gap: pad("14px", "9px")
    }
  }, SERVICES.map(s => {
    const cvar = `var(${COLOR_VAR[s.color]})`;
    if (s.coming) {
      return /*#__PURE__*/React.createElement("div", {
        key: s.slug,
        style: {
          position: "relative",
          padding: "18px",
          background: "var(--bg-1)",
          border: "1px solid var(--border-subtle)",
          borderRadius: "var(--radius-md)",
          opacity: 0.6
        }
      }, /*#__PURE__*/React.createElement("div", {
        style: {
          display: "flex",
          justifyContent: "space-between",
          alignItems: "flex-start"
        }
      }, /*#__PURE__*/React.createElement("span", {
        style: {
          display: "inline-flex",
          alignItems: "center",
          justifyContent: "center",
          width: "44px",
          height: "44px",
          borderRadius: "var(--radius-sm)",
          background: `color-mix(in srgb, ${cvar} 12%, transparent)`,
          color: cvar,
          opacity: 0.5,
          marginBottom: "10px"
        }
      }, /*#__PURE__*/React.createElement(WIco, {
        n: s.icon,
        s: 22
      })), /*#__PURE__*/React.createElement("span", {
        style: {
          width: "10px",
          height: "10px",
          borderRadius: "50%",
          background: "var(--text-disabled)"
        }
      })), /*#__PURE__*/React.createElement("h3", {
        style: {
          margin: 0,
          fontSize: "16px",
          fontWeight: 700,
          display: "flex",
          alignItems: "center",
          gap: "7px"
        }
      }, s.title, /*#__PURE__*/React.createElement(Badge, {
        color: "dim",
        mono: true
      }, "Bient\xF4t")), /*#__PURE__*/React.createElement("p", {
        style: {
          margin: "4px 0 0",
          fontSize: "12.5px",
          color: "var(--text-dim)"
        }
      }, s.desc), /*#__PURE__*/React.createElement("div", {
        style: {
          marginTop: "14px",
          fontFamily: "var(--font-mono)",
          fontSize: "11px",
          color: "var(--text-disabled)"
        }
      }, s.target, " (non d\xE9ploy\xE9)"));
    }
    return /*#__PURE__*/React.createElement("a", {
      key: s.slug,
      href: "#",
      onClick: e => {
        e.preventDefault();
        GO(SLUG_VIEW[s.slug] || "portail");
      },
      style: {
        display: "block",
        position: "relative",
        padding: "18px",
        background: "var(--bg-2)",
        border: "1px solid var(--border)",
        borderRadius: "var(--radius-md)",
        boxShadow: "var(--shadow-md)",
        textDecoration: "none",
        color: "var(--text-primary)",
        transition: "all var(--motion-base)"
      },
      onMouseEnter: e => {
        e.currentTarget.style.background = "var(--bg-3)";
        e.currentTarget.style.boxShadow = "var(--shadow-glow)";
      },
      onMouseLeave: e => {
        e.currentTarget.style.background = "var(--bg-2)";
        e.currentTarget.style.boxShadow = "var(--shadow-md)";
      }
    }, /*#__PURE__*/React.createElement("div", {
      style: {
        display: "flex",
        justifyContent: "space-between",
        alignItems: "flex-start"
      }
    }, /*#__PURE__*/React.createElement("span", {
      style: {
        display: "inline-flex",
        alignItems: "center",
        justifyContent: "center",
        width: "44px",
        height: "44px",
        borderRadius: "var(--radius-sm)",
        background: `color-mix(in srgb, ${cvar} 16%, transparent)`,
        color: cvar,
        marginBottom: "10px"
      }
    }, /*#__PURE__*/React.createElement(WIco, {
      n: s.icon,
      s: 22
    })), /*#__PURE__*/React.createElement("span", {
      className: "laforge-pulse",
      style: {
        width: "10px",
        height: "10px",
        borderRadius: "50%",
        background: s.status === "up" ? "var(--green)" : s.status === "warn" ? "var(--yellow)" : "var(--red)"
      }
    })), /*#__PURE__*/React.createElement("h3", {
      style: {
        margin: 0,
        fontSize: "16px",
        fontWeight: 700,
        display: "flex",
        alignItems: "center",
        gap: "7px"
      }
    }, s.title, s.ext && /*#__PURE__*/React.createElement(Badge, {
      color: "dim",
      mono: true
    }, "EXT")), /*#__PURE__*/React.createElement("p", {
      style: {
        margin: "4px 0 0",
        fontSize: "12.5px",
        color: "var(--text-secondary)"
      }
    }, s.desc), /*#__PURE__*/React.createElement("div", {
      style: {
        marginTop: "14px",
        display: "flex",
        alignItems: "center",
        gap: "8px"
      }
    }, TW.provenance && /*#__PURE__*/React.createElement(ProvenanceBadge, {
      origin: s.prov,
      size: "sm"
    }), /*#__PURE__*/React.createElement("span", {
      style: {
        marginLeft: "auto",
        fontFamily: "var(--font-mono)",
        fontSize: "11px",
        color: "var(--text-dim)"
      }
    }, s.target)));
  })), /*#__PURE__*/React.createElement("div", {
    style: {
      marginTop: "22px",
      padding: "14px 16px",
      border: "1px solid var(--border-subtle)",
      borderRadius: "var(--radius-md)",
      background: "var(--bg-1)",
      color: "var(--text-secondary)",
      fontSize: "12.5px",
      display: TW.mcpPanel ? "block" : "none"
    }
  }, "MCP endpoint actif : ", /*#__PURE__*/React.createElement("span", {
    style: {
      fontFamily: "var(--font-mono)",
      color: "var(--text-dim)"
    }
  }, "http://127.0.0.1:8766/mcp"), " \xB7 Web Hub sur ", /*#__PURE__*/React.createElement("span", {
    style: {
      fontFamily: "var(--font-mono)",
      color: "var(--text-dim)"
    }
  }, ":7400"), " \xB7 Charte : ", /*#__PURE__*/React.createElement("span", {
    style: {
      fontFamily: "var(--font-mono)",
      color: "var(--purple)"
    }
  }, "styles.css")));
}

/* ---------------- Chat (ask) ---------------- */
const PROVIDERS = [{
  v: "ollama",
  label: "Ollama (local)",
  prov: "local"
}, {
  v: "groq",
  label: "Groq",
  prov: "remote"
}, {
  v: "gemini",
  label: "Gemini",
  prov: "remote"
}, {
  v: "mistral",
  label: "Mistral",
  prov: "remote"
}];
function Chat() {
  const [provider, setProvider] = React.useState("ollama");
  const [input, setInput] = React.useState("");
  const [msgs, setMsgs] = React.useState([{
    role: "sys",
    text: "Nokido Hub v18.3 · Ring 0 · LF1.S.H.1.3.INT"
  }, {
    role: "bot",
    text: "Bonjour. Je tourne en local par défaut — où veux-tu forger aujourd'hui ?",
    prov: "local",
    model: "ollama:mistral",
    lat: "418ms"
  }]);
  const provOf = p => (PROVIDERS.find(x => x.v === p) || PROVIDERS[0]).prov;
  const send = () => {
    const t = input.trim();
    if (!t) return;
    const p = provOf(provider);
    setMsgs(m => [...m, {
      role: "user",
      text: t
    }, {
      role: "bot",
      text: "(réponse simulée) — calcul " + (p === "local" ? "sur ta machine" : "délégué au cloud, anonymisé") + ".",
      prov: p,
      model: provider + (p === "local" ? ":mistral" : ":llama-70b"),
      lat: p === "local" ? "612ms" : "248ms"
    }]);
    setInput("");
  };
  const endRef = React.useRef(null);
  React.useEffect(() => {
    if (endRef.current) endRef.current.scrollTop = endRef.current.scrollHeight;
  });
  return /*#__PURE__*/React.createElement("div", {
    style: {
      maxWidth: "720px",
      margin: "0 auto",
      height: "100%",
      display: "flex",
      flexDirection: "column",
      gap: "12px"
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      alignItems: "center",
      gap: "10px"
    }
  }, /*#__PURE__*/React.createElement("span", {
    style: {
      width: "8px",
      height: "8px",
      borderRadius: "50%",
      background: "var(--green)"
    },
    className: "laforge-pulse"
  }), /*#__PURE__*/React.createElement("span", {
    style: {
      fontWeight: 700
    }
  }, "Chat"), /*#__PURE__*/React.createElement("div", {
    style: {
      marginLeft: "auto",
      width: "180px"
    }
  }, /*#__PURE__*/React.createElement(Select, {
    value: provider,
    onChange: e => setProvider(e.target.value),
    options: PROVIDERS.map(p => ({
      value: p.v,
      label: p.label
    }))
  }))), /*#__PURE__*/React.createElement("div", {
    ref: endRef,
    style: {
      flex: 1,
      overflowY: "auto",
      display: "flex",
      flexDirection: "column",
      gap: "10px",
      padding: "4px"
    }
  }, msgs.map((m, i) => /*#__PURE__*/React.createElement("div", {
    key: i,
    style: {
      alignSelf: m.role === "user" ? "flex-end" : m.role === "sys" ? "center" : "flex-start",
      maxWidth: m.role === "sys" ? "100%" : "86%"
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      padding: m.role === "sys" ? "5px 10px" : "9px 13px",
      borderRadius: "var(--radius-md)",
      fontSize: m.role === "sys" ? "11px" : "13px",
      lineHeight: 1.55,
      fontFamily: m.role === "sys" ? "var(--font-mono)" : "var(--font-sans)",
      background: m.role === "user" ? "rgba(119,74,255,0.12)" : m.role === "sys" ? "var(--prov-local-tint)" : "var(--bg-2)",
      border: `1px solid ${m.role === "user" ? "rgba(119,74,255,0.3)" : m.role === "sys" ? "var(--border-subtle)" : "var(--border)"}`,
      color: m.role === "sys" ? "var(--text-dim)" : "var(--text-primary)",
      textAlign: m.role === "sys" ? "center" : "left"
    }
  }, m.text), m.role === "bot" && m.prov && /*#__PURE__*/React.createElement("div", {
    style: {
      marginTop: "5px"
    }
  }, /*#__PURE__*/React.createElement(ProvenanceBadge, {
    origin: m.prov,
    ring: "verified",
    size: "sm",
    detail: `${m.model} · ${m.lat}`
  }))))), /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      gap: "8px",
      alignItems: "flex-end"
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      flex: 1
    }
  }, /*#__PURE__*/React.createElement(TextInput, {
    multiline: true,
    rows: 1,
    placeholder: "Message \xE0 LaForge\u2026",
    value: input,
    onChange: e => setInput(e.target.value)
  })), /*#__PURE__*/React.createElement(Button, {
    variant: "primary",
    size: "lg",
    onClick: send,
    icon: /*#__PURE__*/React.createElement(WIco, {
      n: "send-horizontal",
      s: 16
    })
  }, "Envoyer")), /*#__PURE__*/React.createElement("div", {
    style: {
      fontFamily: "var(--font-mono)",
      fontSize: "10px",
      color: "var(--text-dim)",
      textAlign: "center"
    }
  }, "Header : LF1.S.H.1.3.INT \xB7 ingest centralis\xE9 via /api/ingest"));
}

/* ---------------- Event Feed (audit) ---------------- */
const TOPIC_COLORS = {
  tool: "#ff7b72",
  rpc: "#79c0ff",
  silo: "#7ee787",
  skill: "#ffa657",
  debate: "#d2a8ff",
  agent: "#f2cc60",
  system: "#8b949e"
};
const EVENTS = [{
  ts: "14:32:08",
  agent: "ROUTER",
  topic: "rpc.dispatch",
  data: '{"provider":"ollama","tokens":812}'
}, {
  ts: "14:32:08",
  agent: "BRAIN",
  topic: "silo.reason",
  data: '{"silo":"finance","depth":3}'
}, {
  ts: "14:32:07",
  agent: "ASK",
  topic: "tool.call",
  data: '{"name":"ask","local":true}'
}, {
  ts: "14:31:54",
  agent: "RAG",
  topic: "skill.ingest",
  data: '{"domain":"sante","tags":["bilan"]}'
}, {
  ts: "14:31:40",
  agent: "SWARM",
  topic: "agent.spawn",
  data: '{"role":"critic","ring":2}'
}, {
  ts: "14:30:12",
  agent: "DEBATE",
  topic: "debate.round",
  data: '{"models":["groq","mistral"],"round":2}'
}, {
  ts: "14:29:55",
  agent: "SYSTEM",
  topic: "system.health",
  data: '{"opsec":"STANDARD","up":true}'
}];
function Feed() {
  const [filter, setFilter] = React.useState("");
  const rows = EVENTS.filter(e => !filter || (e.topic + e.agent).toLowerCase().includes(filter.toLowerCase()));
  return /*#__PURE__*/React.createElement("div", {
    style: {
      maxWidth: "1000px",
      margin: "0 auto"
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      alignItems: "center",
      gap: "10px",
      marginBottom: "16px"
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      width: "280px"
    }
  }, /*#__PURE__*/React.createElement(TextInput, {
    placeholder: "Filtrer par topic / agent\u2026",
    icon: /*#__PURE__*/React.createElement(WIco, {
      n: "filter",
      s: 15
    }),
    value: filter,
    onChange: e => setFilter(e.target.value)
  })), /*#__PURE__*/React.createElement(Badge, {
    color: "green"
  }, /*#__PURE__*/React.createElement("span", {
    className: "laforge-pulse",
    style: {
      display: "inline-block",
      width: "6px",
      height: "6px",
      borderRadius: "50%",
      background: "currentColor",
      marginRight: "5px"
    }
  }), "Live \xB7 2s"), /*#__PURE__*/React.createElement("span", {
    style: {
      marginLeft: "auto",
      fontFamily: "var(--font-mono)",
      fontSize: "11px",
      color: "var(--text-dim)"
    }
  }, rows.length, " \xE9v\xE9nements \xB7 bus d'audit")), /*#__PURE__*/React.createElement(Card, {
    style: {
      padding: 0,
      overflow: "hidden"
    }
  }, rows.map((e, i) => {
    const pre = e.topic.split(".")[0];
    const tc = TOPIC_COLORS[pre] || "var(--text-dim)";
    return /*#__PURE__*/React.createElement("div", {
      key: i,
      style: {
        display: "flex",
        gap: "14px",
        alignItems: "center",
        padding: "9px 14px",
        borderBottom: i < rows.length - 1 ? "1px solid var(--border-subtle)" : "none",
        fontFamily: "var(--font-mono)",
        fontSize: "12px"
      }
    }, /*#__PURE__*/React.createElement("span", {
      style: {
        color: "var(--text-dim)",
        minWidth: "62px"
      }
    }, e.ts), /*#__PURE__*/React.createElement("span", {
      style: {
        color: "var(--blue)",
        fontWeight: 700,
        minWidth: "72px"
      }
    }, e.agent), /*#__PURE__*/React.createElement("span", {
      style: {
        color: tc,
        fontWeight: 700,
        minWidth: "120px"
      }
    }, e.topic), /*#__PURE__*/React.createElement("span", {
      style: {
        color: "var(--text-secondary)",
        overflow: "hidden",
        textOverflow: "ellipsis",
        whiteSpace: "nowrap"
      }
    }, e.data));
  }), rows.length === 0 && /*#__PURE__*/React.createElement("div", {
    style: {
      padding: "26px",
      textAlign: "center",
      color: "var(--text-dim)",
      fontSize: "12px"
    }
  }, "Aucun \xE9v\xE9nement correspondant.")));
}
function WebHub({
  t
}) {
  if (t) {
    TW = t;
    window.__WH_TW = t;
  }
  const [view, setView] = React.useState("portail");
  React.useEffect(() => {
    window.__WH_GO = setView;
  }, []);
  const [theme, setTheme] = React.useState(() => WPREF ? WPREF.get("theme", "dark") : "dark");
  React.useEffect(() => {
    if (window.lucide) lucide.createIcons();
  });
  const cycleTheme = () => {
    const n = WPREF ? WPREF.cycleTheme() : theme;
    setTheme(n);
  };
  const themeIcon = {
    dark: "moon",
    light: "sun",
    auto: "monitor"
  }[theme] || "moon";
  const TABS = [["portail", "Portail", "layout-grid"], ["setup", "Setup", "sliders-horizontal"], ["rings", "Rings", "target"], ["chat", "Chat", "message-square"], ["launcher", "Launcher", "rocket"], ["anatomy", "Anatomie", "activity"], ["network", "Network", "share-2"], ["mcp", "MCP Lab", "blocks"], ["rag", "RAG", "database"], ["feed", "Feed", "scroll-text"]];
  return /*#__PURE__*/React.createElement("div", {
    style: {
      height: "100vh",
      display: "flex",
      flexDirection: "column",
      background: "var(--bg-0)",
      color: "var(--text-primary)",
      ["--purple"]: TW.accent,
      ["--accent"]: TW.accent,
      ["--tint-purple"]: `color-mix(in srgb, ${TW.accent} 16%, transparent)`
    }
  }, !TW.motion && /*#__PURE__*/React.createElement("style", null, `.laforge-pulse{animation:none !important;}`), /*#__PURE__*/React.createElement("header", {
    style: {
      display: "flex",
      alignItems: "center",
      gap: "14px",
      padding: "12px 22px",
      background: "var(--bg-1)",
      borderBottom: "1px solid var(--border-subtle)",
      flexShrink: 0
    }
  }, /*#__PURE__*/React.createElement("svg", {
    width: "26",
    height: "26",
    viewBox: "0 0 64 64",
    fill: "none",
    style: {
      flexShrink: 0
    }
  }, /*#__PURE__*/React.createElement("defs", null, /*#__PURE__*/React.createElement("linearGradient", {
    id: "whBolt",
    x1: "26",
    y1: "12",
    x2: "40",
    y2: "40",
    gradientUnits: "userSpaceOnUse"
  }, /*#__PURE__*/React.createElement("stop", {
    offset: "0",
    stopColor: "#FFE070"
  }), /*#__PURE__*/React.createElement("stop", {
    offset: "1",
    stopColor: "#FFC22D"
  }))), /*#__PURE__*/React.createElement("g", {
    stroke: "#15121F",
    strokeWidth: "2.4",
    strokeLinejoin: "round"
  }, /*#__PURE__*/React.createElement("path", {
    d: "M6 35 L20 31 H48 q4 0 4 3.5 Q52 39 47 39 H39 q-3 0 -4 3 l-1.5 3 H27 q-1 -3 -4 -3 H15 Q6 42 6 35 Z",
    fill: "#9A90BC"
  }), /*#__PURE__*/React.createElement("path", {
    d: "M28 45 h8 l-1.5 5 h-5 Z",
    fill: "#6F6498"
  }), /*#__PURE__*/React.createElement("path", {
    d: "M17 50 H47 l3 6 H14 Z",
    fill: "#9A90BC"
  })), /*#__PURE__*/React.createElement("g", null, /*#__PURE__*/React.createElement("rect", {
    x: "4",
    y: "29",
    width: "23",
    height: "5",
    rx: "2.5",
    fill: "#C77D4A",
    stroke: "#15121F",
    strokeWidth: "2.4",
    strokeLinejoin: "round"
  }), /*#__PURE__*/React.createElement("rect", {
    x: "25",
    y: "21",
    width: "11",
    height: "21",
    rx: "3",
    fill: "#B7BCD2",
    stroke: "#15121F",
    strokeWidth: "2.4",
    strokeLinejoin: "round"
  }), /*#__PURE__*/React.createElement("rect", {
    x: "27.5",
    y: "24",
    width: "5.5",
    height: "6",
    rx: "1.5",
    fill: "#D9DCE8"
  })), /*#__PURE__*/React.createElement("path", {
    d: "M31 41 L40 26 H34 L42 11 L30 28 H36 Z",
    fill: "url(#whBolt)",
    stroke: "#15121F",
    strokeWidth: "2",
    strokeLinejoin: "round"
  })), /*#__PURE__*/React.createElement("span", {
    style: {
      fontWeight: 700,
      fontSize: "16px",
      letterSpacing: "0.3px"
    }
  }, "Nokido Hub"), /*#__PURE__*/React.createElement("span", {
    style: {
      fontFamily: "var(--font-mono)",
      fontSize: "11px",
      color: "var(--text-dim)",
      border: "1px solid var(--border)",
      borderRadius: "var(--radius-sm)",
      padding: "2px 8px"
    }
  }, "v18.3"), /*#__PURE__*/React.createElement("nav", {
    style: {
      display: "flex",
      gap: "4px",
      marginLeft: "12px"
    }
  }, TABS.map(([id, label, icon]) => {
    const on = view === id;
    return /*#__PURE__*/React.createElement("button", {
      key: id,
      onClick: () => setView(id),
      style: {
        display: "inline-flex",
        alignItems: "center",
        gap: "7px",
        padding: "6px 12px",
        borderRadius: "var(--radius-sm)",
        border: "none",
        cursor: "pointer",
        fontFamily: "var(--font-sans)",
        fontSize: "13px",
        fontWeight: on ? 600 : 500,
        background: on ? "var(--bg-3)" : "transparent",
        color: on ? "var(--text-primary)" : "var(--text-secondary)"
      }
    }, /*#__PURE__*/React.createElement(WIco, {
      n: icon,
      s: 15
    }), label);
  })), /*#__PURE__*/React.createElement("div", {
    style: {
      marginLeft: "auto",
      display: "flex",
      alignItems: "center",
      gap: "10px"
    }
  }, /*#__PURE__*/React.createElement("button", {
    onClick: cycleTheme,
    title: `Thème : ${theme}`,
    "aria-label": "Th\xE8me",
    style: {
      display: "inline-flex",
      alignItems: "center",
      justifyContent: "center",
      width: "32px",
      height: "32px",
      borderRadius: "var(--radius-sm)",
      border: "1px solid var(--border)",
      background: "transparent",
      color: "var(--text-secondary)",
      cursor: "pointer"
    }
  }, /*#__PURE__*/React.createElement(WIco, {
    n: themeIcon,
    s: 15
  })), /*#__PURE__*/React.createElement("a", {
    href: "../login/index.html",
    title: "Se d\xE9connecter",
    "aria-label": "Se d\xE9connecter",
    style: {
      display: "inline-flex",
      alignItems: "center",
      gap: "7px",
      height: "32px",
      padding: "0 11px",
      borderRadius: "var(--radius-sm)",
      border: "1px solid var(--border)",
      background: "transparent",
      color: "var(--text-secondary)",
      textDecoration: "none",
      fontSize: "12.5px",
      fontFamily: "var(--font-sans)",
      transition: "all var(--motion-fast)"
    },
    onMouseEnter: e => {
      e.currentTarget.style.borderColor = "var(--red)";
      e.currentTarget.style.color = "var(--red)";
    },
    onMouseLeave: e => {
      e.currentTarget.style.borderColor = "var(--border)";
      e.currentTarget.style.color = "var(--text-secondary)";
    }
  }, /*#__PURE__*/React.createElement(WIco, {
    n: "log-out",
    s: 14
  }), "D\xE9connexion"), /*#__PURE__*/React.createElement("span", {
    style: {
      fontFamily: "var(--font-mono)",
      fontSize: "11px",
      color: "var(--text-dim)"
    }
  }, "Web Hub :7400"))), /*#__PURE__*/React.createElement("main", {
    style: {
      flex: 1,
      overflowY: "auto",
      padding: pad("24px 22px", "14px 16px")
    }
  }, view === "portail" && /*#__PURE__*/React.createElement(Portail, null), view === "setup" && /*#__PURE__*/React.createElement(window.SetupView, null), view === "rings" && /*#__PURE__*/React.createElement(window.RingsView, null), view === "chat" && /*#__PURE__*/React.createElement(Chat, null), view === "launcher" && /*#__PURE__*/React.createElement(window.LauncherView, null), view === "anatomy" && /*#__PURE__*/React.createElement(window.AnatomyView, null), view === "rag" && /*#__PURE__*/React.createElement(window.RagView, null), view === "feed" && /*#__PURE__*/React.createElement(Feed, null), view === "network" && /*#__PURE__*/React.createElement(window.NetworkView, null), view === "mcp" && /*#__PURE__*/React.createElement(window.McpLabView, null), view === "reports" && /*#__PURE__*/React.createElement(window.ReportsView, null), view === "status" && /*#__PURE__*/React.createElement(window.StatusView, null), view === "pipeline" && /*#__PURE__*/React.createElement(window.PipelineView, null), view === "swarm" && /*#__PURE__*/React.createElement(window.SwarmView, null), view === "debate" && /*#__PURE__*/React.createElement(window.DebateView, null), view === "epistemic" && /*#__PURE__*/React.createElement(window.RagView, null)));
}
Object.assign(window, {
  WebHub
});
})(); } catch (e) { __ds_ns.__errors.push({ path: "ui_kits/webhub/web-hub.ref.jsx", error: String((e && e.message) || e) }); }

// ui_kits/webhub/web-hub-extra.ref.jsx
try { (() => {
/* Nokido Web Hub — écrans ouverts par les puces & tuiles :
   Network Graph (forge/network), MCP Lab (skills), CTF Reports, Status JSON, Épistémique. */
const {
  Card,
  Badge,
  StatusPill,
  Button,
  ProvenanceBadge,
  TextInput
} = window.NokidoDesignSystem_bdc2ac;
const XIco = window.WIco || (({
  n,
  s = 18
}) => /*#__PURE__*/React.createElement("i", {
  "data-lucide": n,
  style: {
    width: s,
    height: s
  }
}));
const provShow = () => window.__WH_TW ? window.__WH_TW.provenance !== false : true;

/* ============================ Network Graph ============================ */
const NET_NODES = [{
  id: "brain",
  label: "Cerveau",
  group: "core",
  prov: "local",
  x: 0.50,
  y: 0.46,
  r: 26
}, {
  id: "router",
  label: "Routeur",
  group: "core",
  prov: "local",
  x: 0.50,
  y: 0.74,
  r: 18
}, {
  id: "rag",
  label: "RAG",
  group: "memory",
  prov: "local",
  x: 0.24,
  y: 0.34,
  r: 18
}, {
  id: "mem",
  label: "Mémoire",
  group: "memory",
  prov: "local",
  x: 0.18,
  y: 0.60,
  r: 15
}, {
  id: "mcp",
  label: "MCP",
  group: "tools",
  prov: "hybrid",
  x: 0.74,
  y: 0.30,
  r: 18
}, {
  id: "skills",
  label: "Skills",
  group: "tools",
  prov: "hybrid",
  x: 0.86,
  y: 0.52,
  r: 15
}, {
  id: "ollama",
  label: "Ollama",
  group: "compute",
  prov: "local",
  x: 0.40,
  y: 0.18,
  r: 16
}, {
  id: "cloud",
  label: "Cloud",
  group: "compute",
  prov: "remote",
  x: 0.66,
  y: 0.84,
  r: 16
}, {
  id: "vision",
  label: "Vision",
  group: "perception",
  prov: "local",
  x: 0.78,
  y: 0.70,
  r: 13
}, {
  id: "audio",
  label: "Audio",
  group: "perception",
  prov: "local",
  x: 0.30,
  y: 0.84,
  r: 13
}];
const NET_EDGES = [["brain", "router"], ["brain", "rag"], ["brain", "ollama"], ["brain", "mcp"], ["rag", "mem"], ["router", "cloud"], ["router", "mcp"], ["mcp", "skills"], ["router", "vision"], ["router", "audio"], ["brain", "mem"], ["mcp", "cloud"]];
const NET_COLOR = {
  local: "var(--prov-local)",
  hybrid: "var(--prov-hybrid)",
  remote: "var(--prov-remote)"
};
const NET_RAW = {
  local: "#4AC28B",
  hybrid: "#2DD4BF",
  remote: "#774AFF"
};
function NetworkView() {
  const W = 760,
    H = 460;
  const [sel, setSel] = React.useState("brain");
  const [t, setT] = React.useState(0);
  React.useEffect(() => {
    if (window.__WH_TW && window.__WH_TW.motion === false) return;
    let raf,
      start = performance.now();
    const loop = now => {
      setT((now - start) / 1000);
      raf = requestAnimationFrame(loop);
    };
    raf = requestAnimationFrame(loop);
    return () => cancelAnimationFrame(raf);
  }, []);
  const pos = n => ({
    x: n.x * W,
    y: n.y * H
  });
  const node = id => NET_NODES.find(n => n.id === id);
  const selNode = node(sel);
  const neighbours = NET_EDGES.filter(e => e.includes(sel)).map(e => e[0] === sel ? e[1] : e[0]);
  return /*#__PURE__*/React.createElement("div", {
    style: {
      maxWidth: "1100px",
      margin: "0 auto"
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      alignItems: "baseline",
      gap: "10px",
      marginBottom: "14px"
    }
  }, /*#__PURE__*/React.createElement("h2", {
    style: {
      margin: 0,
      fontSize: "13px",
      fontWeight: 700,
      textTransform: "uppercase",
      letterSpacing: "0.6px",
      color: "var(--text-secondary)"
    }
  }, "Network Graph"), /*#__PURE__*/React.createElement("span", {
    style: {
      fontFamily: "var(--font-mono)",
      fontSize: "11px",
      color: "var(--text-dim)"
    }
  }, "forge/network \xB7 ", NET_NODES.length, " n\u0153uds \xB7 ", NET_EDGES.length, " liens"), /*#__PURE__*/React.createElement("div", {
    style: {
      marginLeft: "auto",
      display: "flex",
      gap: "12px",
      fontFamily: "var(--font-mono)",
      fontSize: "10.5px"
    }
  }, /*#__PURE__*/React.createElement("span", {
    style: {
      color: "var(--prov-local)"
    }
  }, "\u25CF local"), /*#__PURE__*/React.createElement("span", {
    style: {
      color: "var(--prov-hybrid)"
    }
  }, "\u25CF hybride"), /*#__PURE__*/React.createElement("span", {
    style: {
      color: "var(--prov-remote)"
    }
  }, "\u25CF distant"))), /*#__PURE__*/React.createElement("div", {
    style: {
      display: "grid",
      gridTemplateColumns: "1fr 280px",
      gap: "14px",
      alignItems: "stretch"
    }
  }, /*#__PURE__*/React.createElement(Card, {
    style: {
      padding: 0,
      overflow: "hidden",
      background: "var(--bg-1)"
    }
  }, /*#__PURE__*/React.createElement("svg", {
    viewBox: `0 0 ${W} ${H}`,
    style: {
      width: "100%",
      display: "block",
      background: "radial-gradient(ellipse at 50% 40%, color-mix(in srgb, var(--purple) 7%, transparent), transparent 70%)"
    }
  }, NET_EDGES.map(([a, b], i) => {
    const pa = pos(node(a)),
      pb = pos(node(b));
    const active = sel === a || sel === b;
    const dash = 60,
      off = -(t * 40) % dash;
    return /*#__PURE__*/React.createElement("g", {
      key: i
    }, /*#__PURE__*/React.createElement("line", {
      x1: pa.x,
      y1: pa.y,
      x2: pb.x,
      y2: pb.y,
      stroke: active ? "var(--purple)" : "var(--border)",
      strokeWidth: active ? 2 : 1.2,
      opacity: active ? 0.9 : 0.5
    }), active && /*#__PURE__*/React.createElement("line", {
      x1: pa.x,
      y1: pa.y,
      x2: pb.x,
      y2: pb.y,
      stroke: NET_RAW[node(b).prov],
      strokeWidth: 2.5,
      strokeLinecap: "round",
      strokeDasharray: `6 ${dash - 6}`,
      strokeDashoffset: off,
      opacity: 0.9
    }));
  }), NET_NODES.map(n => {
    const p = pos(n);
    const on = sel === n.id;
    const near = neighbours.includes(n.id);
    const pulse = 1 + (window.__WH_TW && window.__WH_TW.motion === false ? 0 : Math.sin(t * 2 + n.x * 6) * 0.06);
    return /*#__PURE__*/React.createElement("g", {
      key: n.id,
      onClick: () => setSel(n.id),
      style: {
        cursor: "pointer"
      }
    }, /*#__PURE__*/React.createElement("circle", {
      cx: p.x,
      cy: p.y,
      r: n.r * pulse + (on ? 7 : 0),
      fill: NET_RAW[n.prov],
      opacity: on ? 0.22 : near ? 0.14 : 0.08
    }), /*#__PURE__*/React.createElement("circle", {
      cx: p.x,
      cy: p.y,
      r: n.r * pulse,
      fill: "var(--bg-2)",
      stroke: NET_RAW[n.prov],
      strokeWidth: on ? 3 : near ? 2 : 1.5
    }), /*#__PURE__*/React.createElement("circle", {
      cx: p.x,
      cy: p.y,
      r: n.r * pulse * 0.4,
      fill: NET_RAW[n.prov],
      opacity: 0.85
    }), /*#__PURE__*/React.createElement("text", {
      x: p.x,
      y: p.y + n.r * pulse + 13,
      textAnchor: "middle",
      fontSize: "11",
      fontFamily: "var(--font-mono)",
      fill: on ? "var(--text-primary)" : "var(--text-secondary)",
      fontWeight: on ? 700 : 500
    }, n.label));
  }))), /*#__PURE__*/React.createElement(Card, null, /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      alignItems: "center",
      gap: "9px",
      marginBottom: "12px"
    }
  }, /*#__PURE__*/React.createElement("span", {
    style: {
      width: "12px",
      height: "12px",
      borderRadius: "50%",
      background: NET_COLOR[selNode.prov],
      boxShadow: `0 0 8px ${NET_COLOR[selNode.prov]}`
    }
  }), /*#__PURE__*/React.createElement("span", {
    style: {
      fontSize: "16px",
      fontWeight: 700
    }
  }, selNode.label)), provShow() && /*#__PURE__*/React.createElement(ProvenanceBadge, {
    origin: selNode.prov,
    size: "sm"
  }), /*#__PURE__*/React.createElement("div", {
    style: {
      marginTop: "14px",
      display: "flex",
      flexDirection: "column",
      gap: "8px",
      fontFamily: "var(--font-mono)",
      fontSize: "11px",
      color: "var(--text-dim)"
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      justifyContent: "space-between"
    }
  }, /*#__PURE__*/React.createElement("span", null, "node.id"), /*#__PURE__*/React.createElement("span", {
    style: {
      color: "var(--text-secondary)"
    }
  }, selNode.id)), /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      justifyContent: "space-between"
    }
  }, /*#__PURE__*/React.createElement("span", null, "groupe"), /*#__PURE__*/React.createElement("span", {
    style: {
      color: "var(--text-secondary)"
    }
  }, selNode.group)), /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      justifyContent: "space-between"
    }
  }, /*#__PURE__*/React.createElement("span", null, "liens"), /*#__PURE__*/React.createElement("span", {
    style: {
      color: "var(--text-secondary)"
    }
  }, neighbours.length))), /*#__PURE__*/React.createElement("div", {
    style: {
      marginTop: "14px",
      paddingTop: "12px",
      borderTop: "1px solid var(--border-subtle)"
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      fontFamily: "var(--font-mono)",
      fontSize: "10px",
      textTransform: "uppercase",
      letterSpacing: "0.5px",
      color: "var(--text-dim)",
      marginBottom: "8px"
    }
  }, "Connect\xE9 \xE0"), /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      flexWrap: "wrap",
      gap: "6px"
    }
  }, neighbours.map(id => /*#__PURE__*/React.createElement("button", {
    key: id,
    onClick: () => setSel(id),
    style: {
      display: "inline-flex",
      alignItems: "center",
      gap: "5px",
      padding: "3px 9px",
      borderRadius: "var(--radius-pill)",
      border: "1px solid var(--border)",
      background: "transparent",
      color: "var(--text-secondary)",
      fontSize: "11px",
      fontFamily: "var(--font-mono)",
      cursor: "pointer"
    }
  }, /*#__PURE__*/React.createElement("span", {
    style: {
      width: "6px",
      height: "6px",
      borderRadius: "50%",
      background: NET_COLOR[node(id).prov]
    }
  }), node(id).label)))))));
}

/* ============================ MCP Lab (skills) ============================ */
const SKILLS = [{
  name: "web.fetch",
  cat: "Réseau",
  prov: "remote",
  ring: "verified",
  desc: "Récupère une URL (anonymisé)",
  calls: 142
}, {
  name: "fs.read",
  cat: "Système",
  prov: "local",
  ring: "gold",
  desc: "Lecture fichier local",
  calls: 980
}, {
  name: "rag.search",
  cat: "Mémoire",
  prov: "local",
  ring: "gold",
  desc: "Recherche sémantique locale",
  calls: 411
}, {
  name: "shell.run",
  cat: "Système",
  prov: "local",
  ring: "verified",
  desc: "Commande sandboxée",
  calls: 67
}, {
  name: "vision.ocr",
  cat: "Perception",
  prov: "local",
  ring: "draft",
  desc: "OCR d'image locale",
  calls: 23
}, {
  name: "cloud.ask",
  cat: "LLM",
  prov: "remote",
  ring: "verified",
  desc: "Délègue au cloud (anonymisé)",
  calls: 88
}];
function McpLabView() {
  const [sel, setSel] = React.useState(SKILLS[1]);
  const [q, setQ] = React.useState("");
  const [out, setOut] = React.useState(null);
  const list = SKILLS.filter(s => s.name.includes(q.toLowerCase()) || s.cat.toLowerCase().includes(q.toLowerCase()));
  const invoke = () => setOut({
    ok: true,
    skill: sel.name,
    prov: sel.prov,
    ms: 40 + Math.floor(Math.random() * 600),
    ring: sel.ring
  });
  return /*#__PURE__*/React.createElement("div", {
    style: {
      maxWidth: "1000px",
      margin: "0 auto"
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      alignItems: "baseline",
      gap: "10px",
      marginBottom: "14px"
    }
  }, /*#__PURE__*/React.createElement("h2", {
    style: {
      margin: 0,
      fontSize: "13px",
      fontWeight: 700,
      textTransform: "uppercase",
      letterSpacing: "0.6px",
      color: "var(--text-secondary)"
    }
  }, "MCP Lab"), /*#__PURE__*/React.createElement("span", {
    style: {
      fontFamily: "var(--font-mono)",
      fontSize: "11px",
      color: "var(--text-dim)"
    }
  }, "marketplace de skills \xB7 endpoint :8766")), /*#__PURE__*/React.createElement("div", {
    style: {
      display: "grid",
      gridTemplateColumns: "1fr 340px",
      gap: "14px",
      alignItems: "start"
    }
  }, /*#__PURE__*/React.createElement("div", null, /*#__PURE__*/React.createElement("div", {
    style: {
      marginBottom: "10px"
    }
  }, /*#__PURE__*/React.createElement(TextInput, {
    placeholder: "Filtrer les skills\u2026",
    icon: /*#__PURE__*/React.createElement(XIco, {
      n: "search",
      s: 15
    }),
    value: q,
    onChange: e => setQ(e.target.value)
  })), /*#__PURE__*/React.createElement("div", {
    style: {
      display: "grid",
      gridTemplateColumns: "1fr 1fr",
      gap: "10px"
    }
  }, list.map(s => {
    const on = sel.name === s.name;
    return /*#__PURE__*/React.createElement("button", {
      key: s.name,
      onClick: () => {
        setSel(s);
        setOut(null);
      },
      style: {
        textAlign: "left",
        padding: "13px",
        borderRadius: "var(--radius-md)",
        cursor: "pointer",
        background: on ? "var(--bg-3)" : "var(--bg-2)",
        border: `1px solid ${on ? "var(--purple)" : "var(--border)"}`,
        color: "var(--text-primary)"
      }
    }, /*#__PURE__*/React.createElement("div", {
      style: {
        display: "flex",
        justifyContent: "space-between",
        alignItems: "center"
      }
    }, /*#__PURE__*/React.createElement("span", {
      style: {
        fontFamily: "var(--font-mono)",
        fontSize: "13px",
        fontWeight: 700
      }
    }, s.name), /*#__PURE__*/React.createElement(Badge, {
      color: "dim",
      mono: true
    }, s.cat)), /*#__PURE__*/React.createElement("div", {
      style: {
        fontSize: "11.5px",
        color: "var(--text-secondary)",
        margin: "5px 0 9px"
      }
    }, s.desc), /*#__PURE__*/React.createElement("div", {
      style: {
        display: "flex",
        alignItems: "center",
        gap: "8px"
      }
    }, provShow() && /*#__PURE__*/React.createElement(ProvenanceBadge, {
      origin: s.prov,
      ring: s.ring,
      size: "sm"
    }), /*#__PURE__*/React.createElement("span", {
      style: {
        marginLeft: "auto",
        fontFamily: "var(--font-mono)",
        fontSize: "10px",
        color: "var(--text-dim)"
      }
    }, s.calls, " appels")));
  }))), /*#__PURE__*/React.createElement(Card, null, /*#__PURE__*/React.createElement("div", {
    style: {
      fontFamily: "var(--font-mono)",
      fontSize: "10px",
      textTransform: "uppercase",
      letterSpacing: "0.5px",
      color: "var(--text-dim)",
      marginBottom: "10px"
    }
  }, "Invoke"), /*#__PURE__*/React.createElement("div", {
    style: {
      fontFamily: "var(--font-mono)",
      fontSize: "14px",
      fontWeight: 700,
      marginBottom: "6px"
    }
  }, sel.name), provShow() && /*#__PURE__*/React.createElement(ProvenanceBadge, {
    origin: sel.prov,
    ring: sel.ring,
    size: "sm"
  }), /*#__PURE__*/React.createElement("div", {
    style: {
      marginTop: "12px"
    }
  }, /*#__PURE__*/React.createElement(TextInput, {
    multiline: true,
    rows: 3,
    placeholder: `{ "arg": "valeur" }`,
    value: "",
    onChange: () => {}
  })), /*#__PURE__*/React.createElement(Button, {
    variant: "primary",
    size: "md",
    icon: /*#__PURE__*/React.createElement(XIco, {
      n: "play",
      s: 14
    }),
    style: {
      width: "100%",
      marginTop: "10px"
    },
    onClick: invoke
  }, "Ex\xE9cuter"), out && /*#__PURE__*/React.createElement("pre", {
    style: {
      marginTop: "12px",
      marginBottom: 0,
      background: "var(--bg-0)",
      border: "1px solid var(--border-subtle)",
      borderRadius: "var(--radius-sm)",
      padding: "11px",
      fontSize: "11px",
      fontFamily: "var(--font-mono)",
      color: "var(--text-secondary)",
      whiteSpace: "pre-wrap"
    }
  }, JSON.stringify(out, null, 2)))));
}

/* ============================ CTF Reports ============================ */
const REPORTS = [{
  id: "LF-2026-0042",
  title: "Recon réseau interne",
  state: "or",
  date: "08/06",
  prov: "local",
  ring: "gold"
}, {
  id: "LF-2026-0041",
  title: "Audit dépendances RAG",
  state: "vérifié",
  date: "07/06",
  prov: "local",
  ring: "verified"
}, {
  id: "LF-2026-0039",
  title: "Test exfiltration (sandbox)",
  state: "brouillon",
  date: "05/06",
  prov: "hybrid",
  ring: "draft"
}, {
  id: "LF-2026-0036",
  title: "Cartographie CVE",
  state: "vérifié",
  date: "02/06",
  prov: "local",
  ring: "verified"
}];
function ReportsView() {
  return /*#__PURE__*/React.createElement("div", {
    style: {
      maxWidth: "860px",
      margin: "0 auto"
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      alignItems: "baseline",
      gap: "10px",
      marginBottom: "14px"
    }
  }, /*#__PURE__*/React.createElement("h2", {
    style: {
      margin: 0,
      fontSize: "13px",
      fontWeight: 700,
      textTransform: "uppercase",
      letterSpacing: "0.6px",
      color: "var(--text-secondary)"
    }
  }, "CTF Reports"), /*#__PURE__*/React.createElement("span", {
    style: {
      fontFamily: "var(--font-mono)",
      fontSize: "11px",
      color: "var(--text-dim)"
    }
  }, "rapports & traces \xB7 /reports/"), /*#__PURE__*/React.createElement(Badge, {
    color: "dim",
    mono: true,
    style: {
      marginLeft: "auto"
    }
  }, "EXT")), /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      flexDirection: "column",
      gap: "8px"
    }
  }, REPORTS.map(r => /*#__PURE__*/React.createElement("div", {
    key: r.id,
    style: {
      display: "flex",
      alignItems: "center",
      gap: "13px",
      padding: "13px 16px",
      background: "var(--bg-2)",
      border: "1px solid var(--border)",
      borderRadius: "var(--radius-md)"
    }
  }, /*#__PURE__*/React.createElement("span", {
    style: {
      display: "inline-flex",
      alignItems: "center",
      justifyContent: "center",
      width: "34px",
      height: "34px",
      borderRadius: "var(--radius-sm)",
      background: "var(--tint-red)",
      color: "var(--red)",
      flexShrink: 0
    }
  }, /*#__PURE__*/React.createElement(XIco, {
    n: "flag",
    s: 16
  })), /*#__PURE__*/React.createElement("div", {
    style: {
      flex: 1,
      minWidth: 0
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      fontSize: "13.5px",
      fontWeight: 600
    }
  }, r.title), /*#__PURE__*/React.createElement("div", {
    style: {
      fontFamily: "var(--font-mono)",
      fontSize: "10.5px",
      color: "var(--text-dim)"
    }
  }, r.id, " \xB7 ", r.date)), provShow() && /*#__PURE__*/React.createElement(ProvenanceBadge, {
    origin: r.prov,
    ring: r.ring,
    size: "sm"
  }), /*#__PURE__*/React.createElement(Button, {
    variant: "ghost",
    size: "sm",
    icon: /*#__PURE__*/React.createElement(XIco, {
      n: "arrow-up-right",
      s: 13
    })
  }, "Ouvrir")))));
}

/* ============================ Status JSON ============================ */
function StatusView() {
  const status = {
    node: "souverain-0",
    ring: 0,
    version: "18.3",
    uptime_s: 8064,
    sovereignty: {
      local_pct: 68,
      opsec: "STANDARD",
      kill_switch: false
    },
    services: {
      brain_worker: "running",
      web_hub: "running",
      hub_mcp: "running",
      rag_indexer: "running",
      swarm: "stale",
      deno_edge: "stopped"
    },
    rag: {
      documents: 128,
      chunks: 3412,
      model: "bge-m3",
      dims: 1024
    }
  };
  const color = v => typeof v === "boolean" ? v ? "var(--green)" : "var(--red)" : v === "running" ? "var(--green)" : v === "stale" ? "var(--yellow)" : v === "stopped" ? "var(--text-dim)" : typeof v === "number" ? "var(--cyan)" : "var(--orange)";
  const render = (obj, depth = 0) => Object.entries(obj).map(([k, v]) => {
    const isObj = v && typeof v === "object";
    return /*#__PURE__*/React.createElement("div", {
      key: k,
      style: {
        paddingLeft: depth * 16
      }
    }, /*#__PURE__*/React.createElement("span", {
      style: {
        color: "var(--purple)"
      }
    }, "\"", k, "\""), /*#__PURE__*/React.createElement("span", {
      style: {
        color: "var(--text-dim)"
      }
    }, ": "), isObj ? /*#__PURE__*/React.createElement("span", {
      style: {
        color: "var(--text-dim)"
      }
    }, Array.isArray(v) ? "[" : "{") : /*#__PURE__*/React.createElement("span", {
      style: {
        color: color(v)
      }
    }, JSON.stringify(v)), isObj && /*#__PURE__*/React.createElement("div", null, render(v, depth + 1)), isObj && /*#__PURE__*/React.createElement("span", {
      style: {
        color: "var(--text-dim)",
        paddingLeft: depth * 16
      }
    }, Array.isArray(v) ? "]" : "}"));
  });
  return /*#__PURE__*/React.createElement("div", {
    style: {
      maxWidth: "720px",
      margin: "0 auto"
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      alignItems: "baseline",
      gap: "10px",
      marginBottom: "14px"
    }
  }, /*#__PURE__*/React.createElement("h2", {
    style: {
      margin: 0,
      fontSize: "13px",
      fontWeight: 700,
      textTransform: "uppercase",
      letterSpacing: "0.6px",
      color: "var(--text-secondary)"
    }
  }, "Status JSON"), /*#__PURE__*/React.createElement("span", {
    style: {
      fontFamily: "var(--font-mono)",
      fontSize: "11px",
      color: "var(--text-dim)"
    }
  }, "GET /status.json"), /*#__PURE__*/React.createElement(StatusPill, {
    status: "up",
    pulse: true,
    style: {
      marginLeft: "auto"
    }
  }, "200 OK")), /*#__PURE__*/React.createElement(Card, {
    style: {
      background: "var(--bg-1)"
    }
  }, /*#__PURE__*/React.createElement("pre", {
    style: {
      margin: 0,
      fontFamily: "var(--font-mono)",
      fontSize: "12px",
      lineHeight: 1.7,
      overflow: "auto"
    }
  }, /*#__PURE__*/React.createElement("span", {
    style: {
      color: "var(--text-dim)"
    }
  }, "{"), render(status, 1), /*#__PURE__*/React.createElement("span", {
    style: {
      color: "var(--text-dim)"
    }
  }, "}"))));
}
Object.assign(window, {
  NetworkView,
  McpLabView,
  ReportsView,
  StatusView,
  PipelineView,
  SwarmView,
  DebateView
});

/* ============================ Swarm (essaim d'agents) ============================ */
const AGENTS = [{
  id: "archiviste",
  label: "Archiviste-Paléographe",
  role: "Archives & paléographie",
  prov: "local",
  state: "active",
  load: 0.74
}, {
  id: "cryptographe",
  label: "Cryptographe",
  role: "Chiffrement & analyse",
  prov: "local",
  state: "active",
  load: 0.61
}, {
  id: "cartographe",
  label: "Géomaticien-Cartographe",
  role: "SIG & cartographie",
  prov: "hybrid",
  state: "alive",
  load: 0.33
}, {
  id: "graphiste",
  label: "Graphiste-DA",
  role: "Direction artistique",
  prov: "local",
  state: "idle",
  load: 0.08
}, {
  id: "libraire",
  label: "Libraire-Bibliographe",
  role: "Recherche bibliographique",
  prov: "local",
  state: "active",
  load: 0.52
}, {
  id: "sociologue",
  label: "Sociologue-Démographe",
  role: "Analyse sociale",
  prov: "remote",
  state: "alive",
  load: 0.27
}];
const A_STATE = {
  active: {
    c: "var(--green)",
    t: "active"
  },
  alive: {
    c: "var(--cyan)",
    t: "alive"
  },
  idle: {
    c: "var(--text-dim)",
    t: "idle"
  }
};
function SwarmView() {
  const [tasks] = React.useState(34);
  const active = AGENTS.filter(a => a.state === "active").length;
  return /*#__PURE__*/React.createElement("div", {
    style: {
      maxWidth: "1000px",
      margin: "0 auto"
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      alignItems: "baseline",
      gap: "10px",
      marginBottom: "14px"
    }
  }, /*#__PURE__*/React.createElement("h2", {
    style: {
      margin: 0,
      fontSize: "13px",
      fontWeight: 700,
      textTransform: "uppercase",
      letterSpacing: "0.6px",
      color: "var(--text-secondary)"
    }
  }, "Swarm"), /*#__PURE__*/React.createElement("span", {
    style: {
      fontFamily: "var(--font-mono)",
      fontSize: "11px",
      color: "var(--text-dim)"
    }
  }, "essaim d'agents \xB7 ", active, " actifs \xB7 ", tasks, " t\xE2ches en silo"), provShow() && /*#__PURE__*/React.createElement(ProvenanceBadge, {
    origin: "hybrid",
    detail: "orchestration locale",
    size: "sm",
    style: {
      marginLeft: "auto"
    }
  })), /*#__PURE__*/React.createElement("div", {
    style: {
      display: "grid",
      gridTemplateColumns: "repeat(auto-fill, minmax(300px, 1fr))",
      gap: "12px"
    }
  }, AGENTS.map(a => {
    const st = A_STATE[a.state];
    return /*#__PURE__*/React.createElement(Card, {
      key: a.id
    }, /*#__PURE__*/React.createElement("div", {
      style: {
        display: "flex",
        alignItems: "flex-start",
        gap: "11px"
      }
    }, /*#__PURE__*/React.createElement("span", {
      style: {
        display: "inline-flex",
        alignItems: "center",
        justifyContent: "center",
        width: "40px",
        height: "40px",
        borderRadius: "var(--radius-sm)",
        background: "var(--tint-purple)",
        color: "var(--purple)",
        flexShrink: 0
      }
    }, /*#__PURE__*/React.createElement(XIco, {
      n: "bot",
      s: 20
    })), /*#__PURE__*/React.createElement("div", {
      style: {
        flex: 1,
        minWidth: 0
      }
    }, /*#__PURE__*/React.createElement("div", {
      style: {
        fontSize: "14px",
        fontWeight: 700
      }
    }, a.label), /*#__PURE__*/React.createElement("div", {
      style: {
        fontSize: "11.5px",
        color: "var(--text-dim)"
      }
    }, a.role)), /*#__PURE__*/React.createElement("span", {
      className: a.state !== "idle" ? "laforge-pulse" : "",
      style: {
        width: "10px",
        height: "10px",
        borderRadius: "50%",
        background: st.c,
        boxShadow: `0 0 8px ${st.c}`,
        flexShrink: 0,
        marginTop: "5px"
      }
    })), /*#__PURE__*/React.createElement("div", {
      style: {
        marginTop: "12px",
        display: "flex",
        alignItems: "center",
        gap: "10px"
      }
    }, /*#__PURE__*/React.createElement("div", {
      style: {
        flex: 1,
        height: "5px",
        borderRadius: "3px",
        background: "var(--bg-4)",
        overflow: "hidden"
      }
    }, /*#__PURE__*/React.createElement("div", {
      style: {
        width: `${Math.round(a.load * 100)}%`,
        height: "100%",
        background: st.c
      }
    })), /*#__PURE__*/React.createElement("span", {
      style: {
        fontFamily: "var(--font-mono)",
        fontSize: "10px",
        color: "var(--text-dim)"
      }
    }, Math.round(a.load * 100), "%"), provShow() && /*#__PURE__*/React.createElement(ProvenanceBadge, {
      origin: a.prov,
      size: "sm"
    })));
  })));
}

/* ============================ LLM Debate ============================ */
const DEBATE = [{
  model: "ollama:mistral",
  prov: "local",
  side: "Pour",
  text: "Rester 100% local : la confidentialité prime, le NPU suffit pour 90% des requêtes.",
  ring: "verified"
}, {
  model: "groq:llama-70b",
  prov: "remote",
  side: "Contre",
  text: "Le cloud apporte une puissance que le local n'atteint pas sur les longues roadmaps.",
  ring: "verified"
}, {
  model: "ollama:qwen",
  prov: "local",
  side: "Nuance",
  text: "Hybride adaptatif : local par défaut, cloud anonymisé uniquement au-delà d'un seuil de complexité.",
  ring: "gold"
}];
function DebateView() {
  const [round] = React.useState(2);
  const sideColor = {
    Pour: "var(--green)",
    Contre: "var(--red)",
    Nuance: "var(--cyan)"
  };
  return /*#__PURE__*/React.createElement("div", {
    style: {
      maxWidth: "840px",
      margin: "0 auto"
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      alignItems: "baseline",
      gap: "10px",
      marginBottom: "14px"
    }
  }, /*#__PURE__*/React.createElement("h2", {
    style: {
      margin: 0,
      fontSize: "13px",
      fontWeight: 700,
      textTransform: "uppercase",
      letterSpacing: "0.6px",
      color: "var(--text-secondary)"
    }
  }, "LLM Debate"), /*#__PURE__*/React.createElement("span", {
    style: {
      fontFamily: "var(--font-mono)",
      fontSize: "11px",
      color: "var(--text-dim)"
    }
  }, "d\xE9bat multi-mod\xE8les \xB7 round ", round, "/3")), /*#__PURE__*/React.createElement(Card, {
    style: {
      background: "var(--bg-1)",
      marginBottom: "14px"
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      fontSize: "11px",
      textTransform: "uppercase",
      letterSpacing: "0.5px",
      color: "var(--text-dim)",
      marginBottom: "5px"
    }
  }, "Motion"), /*#__PURE__*/React.createElement("p", {
    style: {
      margin: 0,
      fontSize: "15px",
      fontWeight: 600,
      lineHeight: 1.4
    }
  }, "\xAB Nokido devrait-il rester strictement local, ou d\xE9l\xE9guer au cloud quand c'est plus performant ? \xBB")), /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      flexDirection: "column",
      gap: "12px"
    }
  }, DEBATE.map((d, i) => /*#__PURE__*/React.createElement("div", {
    key: i,
    style: {
      display: "flex",
      gap: "12px"
    }
  }, /*#__PURE__*/React.createElement("span", {
    style: {
      display: "inline-flex",
      alignItems: "center",
      justifyContent: "center",
      width: "38px",
      height: "38px",
      borderRadius: "var(--radius-sm)",
      flexShrink: 0,
      background: `color-mix(in srgb, ${d.prov === "remote" ? "var(--prov-remote)" : "var(--prov-local)"} 16%, transparent)`,
      color: d.prov === "remote" ? "var(--prov-remote)" : "var(--prov-local)"
    }
  }, /*#__PURE__*/React.createElement(XIco, {
    n: "message-circle",
    s: 18
  })), /*#__PURE__*/React.createElement(Card, {
    style: {
      flex: 1
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      alignItems: "center",
      gap: "8px",
      marginBottom: "7px"
    }
  }, /*#__PURE__*/React.createElement("span", {
    style: {
      fontFamily: "var(--font-mono)",
      fontSize: "12px",
      fontWeight: 700
    }
  }, d.model), /*#__PURE__*/React.createElement("span", {
    style: {
      fontFamily: "var(--font-mono)",
      fontSize: "9px",
      fontWeight: 700,
      color: sideColor[d.side],
      border: `1px solid ${sideColor[d.side]}`,
      borderRadius: "4px",
      padding: "1px 6px"
    }
  }, d.side), provShow() && /*#__PURE__*/React.createElement(ProvenanceBadge, {
    origin: d.prov,
    ring: d.ring,
    size: "sm",
    style: {
      marginLeft: "auto"
    }
  })), /*#__PURE__*/React.createElement("p", {
    style: {
      margin: 0,
      fontSize: "13px",
      color: "var(--text-secondary)",
      lineHeight: 1.5
    }
  }, d.text))))), /*#__PURE__*/React.createElement(Card, {
    style: {
      marginTop: "14px",
      background: "var(--bg-1)",
      display: "flex",
      alignItems: "center",
      gap: "10px"
    }
  }, /*#__PURE__*/React.createElement(XIco, {
    n: "gavel",
    s: 16
  }), /*#__PURE__*/React.createElement("span", {
    style: {
      fontSize: "12.5px",
      color: "var(--text-secondary)"
    }
  }, "Synth\xE8se de l'arbitre : ", /*#__PURE__*/React.createElement("b", {
    style: {
      color: "var(--cyan)"
    }
  }, "hybride adaptatif"), " retenu \u2014 anneau"), /*#__PURE__*/React.createElement("span", {
    style: {
      marginLeft: "auto"
    }
  }, /*#__PURE__*/React.createElement(Badge, {
    color: "yellow",
    variant: "outline"
  }, "Or"))));
}

/* ============================ Pipeline souverain (CI) ============================ */
function PipelineView() {
  // Gate PRIMAIRE = local (gratuit, hors quota) ; fallback = cloud (manuel, workflow_dispatch).
  const LOCAL_GATE = [{
    name: "pre-commit · secret-scan",
    desc: "gitleaks local au commit",
    state: "pass",
    ring: "gold",
    ms: 420
  }, {
    name: "tools/ci_local.py",
    desc: "pre-push : ruff + bandit + AST",
    state: "pass",
    ring: "gold",
    ms: 3100
  }, {
    name: "pytest (sélection)",
    desc: "tests unitaires rapides",
    state: "pass",
    ring: "verified",
    ms: 8800
  }, {
    name: "ci-selfhosted.yml",
    desc: "runner local gratuit",
    state: "running",
    ring: "verified",
    ms: null
  }];
  const CLOUD_FALLBACK = [{
    name: "ci.yml",
    desc: "matrice 3-OS (portabilité)",
    trigger: "workflow_dispatch"
  }, {
    name: "eco-shield.yml",
    desc: "ruff + bandit cross-OS",
    trigger: "workflow_dispatch"
  }, {
    name: "gitleaks.yml",
    desc: "scan secrets profond",
    trigger: "workflow_dispatch"
  }, {
    name: "docker-publish.yml",
    desc: "image OCI",
    trigger: "release"
  }, {
    name: "release.yml",
    desc: "publication miroir public",
    trigger: "tag v*"
  }, {
    name: "cla.yml",
    desc: "contributor agreement",
    trigger: "pull_request"
  }];
  const STATE = {
    pass: {
      c: "var(--green)",
      i: "check",
      t: "ok"
    },
    running: {
      c: "var(--cyan)",
      i: "loader",
      t: "en cours"
    },
    fail: {
      c: "var(--red)",
      i: "x",
      t: "échec"
    }
  };
  const FLOW = [{
    label: "commit",
    icon: "git-commit-horizontal",
    prov: "local"
  }, {
    label: "pre-commit",
    icon: "shield-check",
    prov: "local"
  }, {
    label: "pre-push",
    icon: "terminal",
    prov: "local"
  }, {
    label: "self-hosted",
    icon: "server",
    prov: "local"
  }, {
    label: "merge",
    icon: "git-merge",
    prov: "local"
  }, {
    label: "cloud (manuel)",
    icon: "cloud",
    prov: "remote"
  }];
  const provC = {
    local: "var(--prov-local)",
    remote: "var(--prov-remote)"
  };
  return /*#__PURE__*/React.createElement("div", {
    style: {
      maxWidth: "1040px",
      margin: "0 auto"
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      alignItems: "baseline",
      gap: "10px",
      marginBottom: "14px"
    }
  }, /*#__PURE__*/React.createElement("h2", {
    style: {
      margin: 0,
      fontSize: "13px",
      fontWeight: 700,
      textTransform: "uppercase",
      letterSpacing: "0.6px",
      color: "var(--text-secondary)"
    }
  }, "Pipeline souverain"), /*#__PURE__*/React.createElement("span", {
    style: {
      fontFamily: "var(--font-mono)",
      fontSize: "11px",
      color: "var(--text-dim)"
    }
  }, "gate local d'abord \xB7 cloud en dernier recours"), provShow() && /*#__PURE__*/React.createElement(ProvenanceBadge, {
    origin: "local",
    detail: "hors quota Actions",
    size: "sm",
    style: {
      marginLeft: "auto"
    }
  })), /*#__PURE__*/React.createElement(Card, {
    style: {
      background: "var(--bg-1)",
      marginBottom: "16px"
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      alignItems: "center",
      gap: "4px",
      flexWrap: "wrap"
    }
  }, FLOW.map((f, i) => /*#__PURE__*/React.createElement(React.Fragment, {
    key: f.label
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      flexDirection: "column",
      alignItems: "center",
      gap: "6px",
      minWidth: "82px"
    }
  }, /*#__PURE__*/React.createElement("span", {
    style: {
      display: "inline-flex",
      alignItems: "center",
      justifyContent: "center",
      width: "38px",
      height: "38px",
      borderRadius: "var(--radius-sm)",
      background: `color-mix(in srgb, ${provC[f.prov]} 16%, transparent)`,
      color: provC[f.prov],
      border: `1px solid ${provC[f.prov]}`
    }
  }, /*#__PURE__*/React.createElement(XIco, {
    n: f.icon,
    s: 18
  })), /*#__PURE__*/React.createElement("span", {
    style: {
      fontFamily: "var(--font-mono)",
      fontSize: "10px",
      color: "var(--text-secondary)",
      textAlign: "center"
    }
  }, f.label)), i < FLOW.length - 1 && /*#__PURE__*/React.createElement("span", {
    style: {
      flex: 1,
      minWidth: "16px",
      height: "2px",
      borderRadius: "2px",
      background: FLOW[i + 1].prov === "remote" ? "repeating-linear-gradient(90deg, var(--prov-remote) 0 5px, transparent 5px 10px)" : "var(--prov-local)",
      opacity: 0.6
    }
  }))))), /*#__PURE__*/React.createElement("div", {
    style: {
      display: "grid",
      gridTemplateColumns: "1fr 1fr",
      gap: "14px",
      alignItems: "start"
    }
  }, /*#__PURE__*/React.createElement(Card, {
    style: {
      borderColor: "var(--prov-local)",
      boxShadow: "var(--prov-local-glow)"
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      alignItems: "center",
      gap: "8px",
      marginBottom: "4px"
    }
  }, /*#__PURE__*/React.createElement(XIco, {
    n: "shield-check",
    s: 16
  }), /*#__PURE__*/React.createElement("span", {
    style: {
      fontWeight: 700,
      fontSize: "14px"
    }
  }, "Gate primaire \xB7 LOCAL"), /*#__PURE__*/React.createElement(Badge, {
    color: "green",
    mono: true,
    style: {
      marginLeft: "auto"
    }
  }, "Gratuit")), /*#__PURE__*/React.createElement("div", {
    style: {
      fontSize: "11.5px",
      color: "var(--text-dim)",
      marginBottom: "12px"
    }
  }, "Tourne sur ta machine / runner self-hosted. Bloquant."), /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      flexDirection: "column",
      gap: "8px"
    }
  }, LOCAL_GATE.map(c => {
    const st = STATE[c.state];
    return /*#__PURE__*/React.createElement("div", {
      key: c.name,
      style: {
        display: "flex",
        alignItems: "center",
        gap: "11px",
        padding: "10px 12px",
        background: "var(--bg-2)",
        border: "1px solid var(--border)",
        borderRadius: "var(--radius-sm)"
      }
    }, /*#__PURE__*/React.createElement("span", {
      className: c.state === "running" ? "laforge-pulse" : "",
      style: {
        display: "inline-flex",
        alignItems: "center",
        justifyContent: "center",
        width: "22px",
        height: "22px",
        borderRadius: "50%",
        background: `color-mix(in srgb, ${st.c} 16%, transparent)`,
        color: st.c,
        flexShrink: 0
      }
    }, /*#__PURE__*/React.createElement(XIco, {
      n: st.i,
      s: 13
    })), /*#__PURE__*/React.createElement("div", {
      style: {
        flex: 1,
        minWidth: 0
      }
    }, /*#__PURE__*/React.createElement("div", {
      style: {
        fontFamily: "var(--font-mono)",
        fontSize: "12px",
        fontWeight: 600
      }
    }, c.name), /*#__PURE__*/React.createElement("div", {
      style: {
        fontSize: "10.5px",
        color: "var(--text-dim)"
      }
    }, c.desc)), /*#__PURE__*/React.createElement("span", {
      style: {
        fontFamily: "var(--font-mono)",
        fontSize: "10px",
        color: "var(--text-dim)"
      }
    }, c.ms ? `${c.ms}ms` : "…"), provShow() && /*#__PURE__*/React.createElement("span", {
      style: {
        width: "9px",
        height: "9px",
        borderRadius: "50%",
        background: c.ring === "gold" ? "var(--ring-gold)" : "var(--ring-verified)",
        boxShadow: `0 0 6px ${c.ring === "gold" ? "var(--ring-gold)" : "var(--ring-verified)"}`
      }
    }));
  }))), /*#__PURE__*/React.createElement(Card, null, /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      alignItems: "center",
      gap: "8px",
      marginBottom: "4px"
    }
  }, /*#__PURE__*/React.createElement(XIco, {
    n: "cloud",
    s: 16
  }), /*#__PURE__*/React.createElement("span", {
    style: {
      fontWeight: 700,
      fontSize: "14px"
    }
  }, "Fallback cloud \xB7 MANUEL"), /*#__PURE__*/React.createElement(Badge, {
    color: "purple",
    mono: true,
    style: {
      marginLeft: "auto"
    }
  }, "\xC0 la demande")), /*#__PURE__*/React.createElement("div", {
    style: {
      fontSize: "11.5px",
      color: "var(--text-dim)",
      marginBottom: "12px"
    }
  }, "GitHub-hosted = quota payant. ", /*#__PURE__*/React.createElement("span", {
    style: {
      fontFamily: "var(--font-mono)"
    }
  }, "workflow_dispatch"), " seulement."), /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      flexDirection: "column",
      gap: "8px"
    }
  }, CLOUD_FALLBACK.map(w => /*#__PURE__*/React.createElement("div", {
    key: w.name,
    style: {
      display: "flex",
      alignItems: "center",
      gap: "11px",
      padding: "10px 12px",
      background: "var(--bg-1)",
      border: "1px solid var(--border-subtle)",
      borderRadius: "var(--radius-sm)",
      opacity: 0.92
    }
  }, /*#__PURE__*/React.createElement("span", {
    style: {
      display: "inline-flex",
      alignItems: "center",
      justifyContent: "center",
      width: "22px",
      height: "22px",
      borderRadius: "50%",
      background: "var(--prov-remote-tint)",
      color: "var(--prov-remote)",
      flexShrink: 0
    }
  }, /*#__PURE__*/React.createElement(XIco, {
    n: "circle-pause",
    s: 13
  })), /*#__PURE__*/React.createElement("div", {
    style: {
      flex: 1,
      minWidth: 0
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      fontFamily: "var(--font-mono)",
      fontSize: "12px",
      fontWeight: 600
    }
  }, w.name), /*#__PURE__*/React.createElement("div", {
    style: {
      fontSize: "10.5px",
      color: "var(--text-dim)"
    }
  }, w.desc)), /*#__PURE__*/React.createElement("span", {
    style: {
      fontFamily: "var(--font-mono)",
      fontSize: "9px",
      color: "var(--prov-remote)",
      border: "1px solid var(--prov-remote)",
      borderRadius: "4px",
      padding: "1px 5px"
    }
  }, w.trigger)))), /*#__PURE__*/React.createElement("div", {
    style: {
      marginTop: "12px",
      display: "flex",
      alignItems: "center",
      gap: "8px",
      fontSize: "11px",
      color: "var(--text-dim)"
    }
  }, /*#__PURE__*/React.createElement(XIco, {
    n: "info",
    s: 13
  }), /*#__PURE__*/React.createElement("span", null, "Lanc\xE9 avant un miroir/release public, ou pour valider la portabilit\xE9 cross-OS.")))));
}
})(); } catch (e) { __ds_ns.__errors.push({ path: "ui_kits/webhub/web-hub-extra.ref.jsx", error: String((e && e.message) || e) }); }

// ui_kits/webhub/web-hub-screens.ref.jsx
try { (() => {
/* Nokido Web Hub — écrans réels supplémentaires modernisés :
   Launcher (modules), Anatomie Live (organes & flux), RAG Dashboard. */
const {
  Card,
  Badge,
  StatusPill,
  Button,
  ProvenanceBadge,
  TextInput
} = window.NokidoDesignSystem_bdc2ac;
const SIco = window.WIco || (({
  n,
  s = 18
}) => /*#__PURE__*/React.createElement("i", {
  "data-lucide": n,
  style: {
    width: s,
    height: s
  }
}));
const showProv = () => window.__WH_TW ? window.__WH_TW.provenance !== false : true;

/* ====================== Launcher ====================== */
const MODULES0 = [{
  mod: "brain_worker",
  title: "Brain Worker",
  desc: "Cœur de raisonnement",
  status: "running",
  pid: 4821,
  port: null,
  uptime: "2 h 14",
  prov: "local"
}, {
  mod: "web_hub",
  title: "Web Hub",
  desc: "Portail :7400",
  status: "running",
  pid: 4822,
  port: 7400,
  uptime: "2 h 14",
  prov: "local"
}, {
  mod: "hub_mcp",
  title: "Hub MCP",
  desc: "Endpoint :8766",
  status: "running",
  pid: 4830,
  port: 8766,
  uptime: "2 h 13",
  prov: "local"
}, {
  mod: "rag_indexer",
  title: "RAG Indexer",
  desc: "Embeddings bge-m3",
  status: "running",
  pid: 4901,
  port: null,
  uptime: "1 h 58",
  prov: "local"
}, {
  mod: "swarm",
  title: "Swarm",
  desc: "Essaim d'agents",
  status: "stale",
  pid: 5012,
  port: null,
  uptime: "—",
  prov: "hybrid"
}, {
  mod: "deno_edge",
  title: "Deno Edge",
  desc: "Runtime :7401",
  status: "stopped",
  pid: null,
  port: 7401,
  uptime: "—",
  prov: "remote"
}];
const ST = {
  running: {
    label: "running",
    color: "var(--green)",
    bg: "rgba(74,194,139,0.12)"
  },
  stopped: {
    label: "stopped",
    color: "var(--text-dim)",
    bg: "rgba(110,106,130,0.12)"
  },
  stale: {
    label: "stale",
    color: "var(--red)",
    bg: "rgba(242,79,79,0.12)"
  }
};
function Launcher() {
  const [mods, setMods] = React.useState(MODULES0);
  const [logs, setLogs] = React.useState({});
  const set = (mod, patch) => setMods(m => m.map(x => x.mod === mod ? {
    ...x,
    ...patch
  } : x));
  const start = mod => set(mod, {
    status: "running",
    pid: 5000 + Math.floor(Math.random() * 900),
    uptime: "0 s"
  });
  const stop = mod => set(mod, {
    status: "stopped",
    pid: null,
    uptime: "—"
  });
  const toggleLog = mod => setLogs(l => ({
    ...l,
    [mod]: !l[mod]
  }));
  return /*#__PURE__*/React.createElement("div", {
    style: {
      maxWidth: "1000px",
      margin: "0 auto"
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      alignItems: "baseline",
      gap: "10px",
      marginBottom: "16px"
    }
  }, /*#__PURE__*/React.createElement("h2", {
    style: {
      margin: 0,
      fontSize: "13px",
      fontWeight: 700,
      textTransform: "uppercase",
      letterSpacing: "0.6px",
      color: "var(--text-secondary)"
    }
  }, "Modules"), /*#__PURE__*/React.createElement("span", {
    style: {
      fontFamily: "var(--font-mono)",
      fontSize: "11px",
      color: "var(--text-dim)"
    }
  }, mods.filter(m => m.status === "running").length, "/", mods.length, " actifs \xB7 refresh 3s")), /*#__PURE__*/React.createElement("div", {
    style: {
      display: "grid",
      gridTemplateColumns: "1fr 1fr",
      gap: "12px"
    }
  }, mods.map(m => {
    const st = ST[m.status];
    return /*#__PURE__*/React.createElement(Card, {
      key: m.mod
    }, /*#__PURE__*/React.createElement("div", {
      style: {
        display: "flex",
        alignItems: "flex-start",
        justifyContent: "space-between",
        gap: "10px"
      }
    }, /*#__PURE__*/React.createElement("div", null, /*#__PURE__*/React.createElement("div", {
      style: {
        fontSize: "15px",
        fontWeight: 700
      }
    }, m.title), /*#__PURE__*/React.createElement("div", {
      style: {
        fontSize: "12px",
        color: "var(--text-dim)"
      }
    }, m.desc)), /*#__PURE__*/React.createElement("span", {
      style: {
        fontFamily: "var(--font-mono)",
        fontSize: "10px",
        fontWeight: 700,
        textTransform: "uppercase",
        letterSpacing: "0.4px",
        color: st.color,
        background: st.bg,
        padding: "3px 9px",
        borderRadius: "var(--radius-pill)"
      }
    }, st.label)), /*#__PURE__*/React.createElement("div", {
      style: {
        marginTop: "8px",
        display: "flex",
        gap: "10px",
        alignItems: "center",
        fontFamily: "var(--font-mono)",
        fontSize: "11px",
        color: "var(--text-dim)"
      }
    }, m.pid && /*#__PURE__*/React.createElement("span", null, "pid ", m.pid), m.port && /*#__PURE__*/React.createElement("span", null, ":", m.port), m.uptime !== "—" && /*#__PURE__*/React.createElement("span", null, "up ", m.uptime), showProv() && /*#__PURE__*/React.createElement(ProvenanceBadge, {
      origin: m.prov,
      size: "sm",
      style: {
        marginLeft: "auto"
      }
    })), /*#__PURE__*/React.createElement("div", {
      style: {
        marginTop: "12px",
        display: "flex",
        gap: "6px",
        flexWrap: "wrap"
      }
    }, /*#__PURE__*/React.createElement(Button, {
      variant: "success",
      size: "sm",
      disabled: m.status === "running",
      onClick: () => start(m.mod)
    }, "Start"), /*#__PURE__*/React.createElement(Button, {
      variant: "danger",
      size: "sm",
      disabled: m.status === "stopped",
      onClick: () => stop(m.mod)
    }, "Stop"), /*#__PURE__*/React.createElement(Button, {
      variant: "ghost",
      size: "sm",
      icon: /*#__PURE__*/React.createElement(SIco, {
        n: "scroll-text",
        s: 13
      }),
      onClick: () => toggleLog(m.mod)
    }, "Logs"), /*#__PURE__*/React.createElement(Button, {
      variant: "ghost",
      size: "sm",
      icon: /*#__PURE__*/React.createElement(SIco, {
        n: "radio",
        s: 13
      })
    }, "Live")), logs[m.mod] && /*#__PURE__*/React.createElement("pre", {
      style: {
        marginTop: "10px",
        marginBottom: 0,
        background: "var(--bg-0)",
        border: "1px solid var(--border-subtle)",
        borderRadius: "var(--radius-sm)",
        padding: "10px",
        fontSize: "10.5px",
        color: "var(--text-secondary)",
        fontFamily: "var(--font-mono)",
        maxHeight: "120px",
        overflow: "auto",
        whiteSpace: "pre-wrap"
      }
    }, `[${m.mod}] booting ring 0…
[${m.mod}] bind ${m.port ? ":" + m.port : "ipc"} ok
[${m.mod}] health=${m.status} provenance=${m.prov}
[${m.mod}] heartbeat 200 OK`));
  })));
}

/* ====================== Anatomie Live ====================== */
const OPSEC = {
  PARANOID: "var(--green)",
  STANDARD: "var(--cyan)",
  CTF: "var(--yellow)"
};
const HEALTH = {
  active: "var(--green)",
  alive: "var(--cyan)",
  idle: "var(--text-dim)",
  dead: "var(--red)"
};
const ORGANS = {
  "Système nerveux": [{
    label: "Cerveau souverain",
    module: "brain_worker",
    health: "active",
    act: 0.92
  }, {
    label: "Orchestrateur",
    module: "forge_orchestrator",
    health: "active",
    act: 0.78
  }],
  "Mémoire": [{
    label: "RAG / embeddings",
    module: "rag_indexer",
    health: "alive",
    act: 0.54
  }, {
    label: "Historique",
    module: "session_store",
    health: "idle",
    act: 0.12
  }],
  "Perception": [{
    label: "Vision (VLM)",
    module: "perception_vlm",
    health: "idle",
    act: 0.08
  }, {
    label: "Audio",
    module: "audio_in",
    health: "dead",
    act: 0
  }],
  "Routage & action": [{
    label: "Cascade routeur",
    module: "router",
    health: "active",
    act: 0.86
  }, {
    label: "Outils MCP",
    module: "mcp_server",
    health: "alive",
    act: 0.41
  }],
  "Intégrité": [{
    label: "Anneaux",
    module: "integrity_rings",
    health: "alive",
    act: 0.33
  }, {
    label: "Sécurité OPSEC",
    module: "security",
    health: "active",
    act: 0.7
  }]
};
function Anatomy() {
  const [opsec, setOpsec] = React.useState("STANDARD");
  const [killed, setKilled] = React.useState(false);
  const kill = () => {
    setKilled(true);
    setOpsec("PARANOID");
  };
  const stat = (l, v, c) => /*#__PURE__*/React.createElement("div", {
    style: {
      padding: "8px 14px",
      background: "var(--bg-2)",
      border: "1px solid var(--border)",
      borderRadius: "var(--radius-sm)"
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      fontSize: "10px",
      textTransform: "uppercase",
      letterSpacing: "0.4px",
      color: "var(--text-dim)"
    }
  }, l), /*#__PURE__*/React.createElement("div", {
    style: {
      fontFamily: "var(--font-mono)",
      fontSize: "15px",
      fontWeight: 700,
      color: c || "var(--text-primary)"
    }
  }, v));
  return /*#__PURE__*/React.createElement("div", {
    style: {
      maxWidth: "1000px",
      margin: "0 auto"
    }
  }, killed && /*#__PURE__*/React.createElement("div", {
    style: {
      marginBottom: "14px",
      padding: "11px 15px",
      borderRadius: "var(--radius-md)",
      background: "rgba(242,79,79,0.12)",
      border: "1px solid var(--red)",
      color: "var(--red)",
      fontSize: "13px",
      fontWeight: 600,
      display: "flex",
      alignItems: "center",
      gap: "9px"
    }
  }, /*#__PURE__*/React.createElement(SIco, {
    n: "octagon-alert",
    s: 17
  }), "Kill switch activ\xE9 \u2014 tous les outbounds cloud coup\xE9s, OPSEC forc\xE9 PARANOID, lock humain requis."), /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      alignItems: "center",
      gap: "10px",
      flexWrap: "wrap",
      marginBottom: "18px"
    }
  }, stat("msgs / 60s", "142", "var(--purple)"), stat("RAG / 60s", "18", "var(--green)"), stat("services", "5 / 6", "var(--blue)"), /*#__PURE__*/React.createElement("div", {
    style: {
      padding: "8px 14px",
      background: "var(--bg-2)",
      border: `1px solid ${OPSEC[opsec]}`,
      borderRadius: "var(--radius-sm)"
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      fontSize: "10px",
      textTransform: "uppercase",
      letterSpacing: "0.4px",
      color: "var(--text-dim)"
    }
  }, "OPSEC"), /*#__PURE__*/React.createElement("div", {
    style: {
      fontFamily: "var(--font-mono)",
      fontSize: "15px",
      fontWeight: 700,
      color: OPSEC[opsec]
    }
  }, opsec)), /*#__PURE__*/React.createElement("button", {
    onClick: kill,
    disabled: killed,
    style: {
      marginLeft: "auto",
      display: "inline-flex",
      alignItems: "center",
      gap: "7px",
      background: killed ? "var(--bg-3)" : "var(--red)",
      color: killed ? "var(--text-dim)" : "#fff",
      border: "none",
      borderRadius: "var(--radius-sm)",
      padding: "10px 16px",
      fontWeight: 700,
      fontSize: "13px",
      cursor: killed ? "not-allowed" : "pointer",
      boxShadow: killed ? "none" : "0 0 14px rgba(242,79,79,0.4)"
    }
  }, /*#__PURE__*/React.createElement(SIco, {
    n: "octagon-x",
    s: 16
  }), "KILL SWITCH")), /*#__PURE__*/React.createElement("div", {
    style: {
      display: "grid",
      gridTemplateColumns: "repeat(auto-fill, minmax(300px, 1fr))",
      gap: "14px"
    }
  }, Object.entries(ORGANS).map(([system, organs]) => /*#__PURE__*/React.createElement(Card, {
    key: system
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      fontFamily: "var(--font-mono)",
      fontSize: "10px",
      textTransform: "uppercase",
      letterSpacing: "0.6px",
      color: "var(--text-dim)",
      marginBottom: "10px"
    }
  }, system), /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      flexDirection: "column",
      gap: "10px"
    }
  }, organs.map(o => {
    const dead = killed && o.module === "mcp_server";
    const health = dead ? "idle" : o.health;
    const act = dead ? 0.05 : o.act;
    return /*#__PURE__*/React.createElement("div", {
      key: o.module,
      style: {
        display: "flex",
        alignItems: "center",
        gap: "11px"
      }
    }, /*#__PURE__*/React.createElement("span", {
      className: health === "active" || health === "alive" ? "laforge-pulse" : "",
      style: {
        width: "10px",
        height: "10px",
        borderRadius: "50%",
        background: HEALTH[health],
        boxShadow: `0 0 8px ${HEALTH[health]}`,
        flexShrink: 0
      }
    }), /*#__PURE__*/React.createElement("div", {
      style: {
        flex: 1,
        minWidth: 0
      }
    }, /*#__PURE__*/React.createElement("div", {
      style: {
        fontSize: "13px",
        fontWeight: 600
      }
    }, o.label), /*#__PURE__*/React.createElement("div", {
      style: {
        fontFamily: "var(--font-mono)",
        fontSize: "10px",
        color: "var(--text-dim)"
      }
    }, o.module)), /*#__PURE__*/React.createElement("div", {
      style: {
        width: "56px",
        height: "5px",
        borderRadius: "3px",
        background: "var(--bg-4)",
        overflow: "hidden",
        flexShrink: 0
      }
    }, /*#__PURE__*/React.createElement("div", {
      style: {
        width: `${Math.round(act * 100)}%`,
        height: "100%",
        background: HEALTH[health],
        transition: "width var(--motion-base)"
      }
    })));
  }))))));
}

/* ====================== RAG Dashboard ====================== */
const CHUNKS = [{
  title: "Bilan sanguin — mars",
  domain: "sante",
  ring: "gold",
  n: 12
}, {
  title: "Budget mensuel 2026",
  domain: "finance",
  ring: "verified",
  n: 8
}, {
  title: "Notes projet Nokido",
  domain: "dev",
  ring: "verified",
  n: 41
}, {
  title: "Recettes & courses",
  domain: "achat",
  ring: "draft",
  n: 5
}];
function Rag() {
  const [q, setQ] = React.useState("");
  const stat = (l, v, c) => /*#__PURE__*/React.createElement(Card, {
    style: {
      flex: 1
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      fontSize: "10px",
      textTransform: "uppercase",
      letterSpacing: "0.4px",
      color: "var(--text-dim)"
    }
  }, l), /*#__PURE__*/React.createElement("div", {
    style: {
      fontFamily: "var(--font-mono)",
      fontSize: "20px",
      fontWeight: 700,
      color: c || "var(--text-primary)",
      marginTop: "3px"
    }
  }, v));
  return /*#__PURE__*/React.createElement("div", {
    style: {
      maxWidth: "880px",
      margin: "0 auto",
      display: "flex",
      flexDirection: "column",
      gap: "16px"
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      gap: "12px"
    }
  }, stat("Documents", "128", "var(--purple)"), stat("Chunks", "3 412", "var(--blue)"), stat("Modèle", "bge-m3", "var(--green)"), stat("Dimensions", "1024", "var(--cyan)")), /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      gap: "8px",
      alignItems: "flex-end"
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      flex: 1
    }
  }, /*#__PURE__*/React.createElement(TextInput, {
    label: "Recherche s\xE9mantique (locale)",
    placeholder: "Ex : mes d\xE9penses de sant\xE9\u2026",
    icon: /*#__PURE__*/React.createElement(SIco, {
      n: "search",
      s: 15
    }),
    value: q,
    onChange: e => setQ(e.target.value)
  })), /*#__PURE__*/React.createElement(Button, {
    variant: "primary",
    size: "lg",
    icon: /*#__PURE__*/React.createElement(SIco, {
      n: "sparkles",
      s: 15
    })
  }, "Chercher")), /*#__PURE__*/React.createElement(Card, {
    style: {
      background: "var(--bg-1)",
      display: "flex",
      alignItems: "center",
      gap: "10px"
    }
  }, /*#__PURE__*/React.createElement(SIco, {
    n: "download",
    s: 16
  }), /*#__PURE__*/React.createElement("span", {
    style: {
      fontSize: "12.5px",
      color: "var(--text-secondary)"
    }
  }, "Ingestion centralis\xE9e via ", /*#__PURE__*/React.createElement("span", {
    style: {
      fontFamily: "var(--font-mono)",
      color: "var(--text-dim)"
    }
  }, "/api/ingest"), " \u2014 URL ou texte, index\xE9 en local."), showProv() && /*#__PURE__*/React.createElement(ProvenanceBadge, {
    origin: "local",
    size: "sm",
    style: {
      marginLeft: "auto"
    }
  })), /*#__PURE__*/React.createElement("div", null, /*#__PURE__*/React.createElement("div", {
    style: {
      fontFamily: "var(--font-mono)",
      fontSize: "10px",
      textTransform: "uppercase",
      letterSpacing: "0.6px",
      color: "var(--text-dim)",
      margin: "4px 0 8px"
    }
  }, "Documents r\xE9cents"), /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      flexDirection: "column",
      gap: "8px"
    }
  }, CHUNKS.map(c => /*#__PURE__*/React.createElement("div", {
    key: c.title,
    style: {
      display: "flex",
      alignItems: "center",
      gap: "12px",
      padding: "12px 15px",
      background: "var(--bg-2)",
      border: "1px solid var(--border)",
      borderRadius: "var(--radius-md)"
    }
  }, /*#__PURE__*/React.createElement("span", {
    style: {
      display: "inline-flex",
      alignItems: "center",
      justifyContent: "center",
      width: "32px",
      height: "32px",
      borderRadius: "var(--radius-sm)",
      background: `color-mix(in srgb, var(--domain-${c.domain}) 16%, transparent)`,
      color: `var(--domain-${c.domain})`,
      flexShrink: 0
    }
  }, /*#__PURE__*/React.createElement(SIco, {
    n: "file-text",
    s: 16
  })), /*#__PURE__*/React.createElement("div", {
    style: {
      flex: 1,
      minWidth: 0
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      fontSize: "13px",
      fontWeight: 600
    }
  }, c.title), /*#__PURE__*/React.createElement("div", {
    style: {
      fontFamily: "var(--font-mono)",
      fontSize: "10px",
      color: "var(--text-dim)"
    }
  }, c.n, " chunks \xB7 domaine ", c.domain)), showProv() && /*#__PURE__*/React.createElement(ProvenanceBadge, {
    origin: "local",
    ring: c.ring,
    size: "sm"
  }))))));
}
Object.assign(window, {
  LauncherView: Launcher,
  AnatomyView: Anatomy,
  RagView: Rag
});
})(); } catch (e) { __ds_ns.__errors.push({ path: "ui_kits/webhub/web-hub-screens.ref.jsx", error: String((e && e.message) || e) }); }

// ui_kits/webhub/web-hub-setup.ref.jsx
try { (() => {
/* Nokido Web Hub — Setup souverain & Rings (centralisés dans le hub).
   Scan machine · compromis souveraineté · profils de conf · tiers DB · modes de lancement
   · placement des agents sur les 11 rings. */
const {
  Card,
  Badge,
  StatusPill,
  Button,
  ProvenanceBadge,
  PowerSlider
} = window.NokidoDesignSystem_bdc2ac;
const UIco = window.WIco || (({
  n,
  s = 18
}) => /*#__PURE__*/React.createElement("i", {
  "data-lucide": n,
  style: {
    width: s,
    height: s
  }
}));
const uprov = () => window.__WH_TW ? window.__WH_TW.provenance !== false : true;

/* Helpers rings (locaux — les statics du composant bundlé ne sont pas garantis) */
const RING_DESC = ["Lois absolues", "Core Nokido", "TRUSTED humain", "Agents validés", "Agents externes", "RAG web", "Outils CI/CD", "SSH / réseau", "Monitoring", "Système hôte", "Corrections de Cap"];
function ringColor(i) {
  const stops = [[74, 194, 139], [45, 212, 191], [59, 178, 208], [119, 74, 255]];
  const t = i / 10,
    seg = t * (stops.length - 1),
    k = Math.min(stops.length - 2, Math.floor(seg)),
    f = seg - k;
  const c = stops[k].map((v, j) => Math.round(v + (stops[k + 1][j] - v) * f));
  return `rgb(${c[0]}, ${c[1]}, ${c[2]})`;
}

/* Dial des 11 rings (inline — miroir du composant DS RingMeter) */
function RingDial({
  states = {},
  selected = null,
  onSelect = null,
  size = 320
}) {
  const cx = size / 2,
    cy = size / 2,
    ringW = (size / 2 - 16) / 11;
  const radius = i => 16 + (i + 0.5) * ringW;
  const override = {
    alert: "var(--yellow)",
    block: "var(--red)",
    inactive: "var(--bg-4)"
  };
  return /*#__PURE__*/React.createElement("svg", {
    width: size,
    height: size,
    viewBox: `0 0 ${size} ${size}`,
    style: {
      flexShrink: 0
    }
  }, /*#__PURE__*/React.createElement("circle", {
    cx: cx,
    cy: cy,
    r: ringW * 0.6,
    fill: ringColor(0),
    opacity: 0.9
  }), Array.from({
    length: 11
  }).map((_, i) => {
    const st = states[i] || "ok";
    const base = st === "ok" ? ringColor(i) : override[st];
    const on = selected === i;
    return /*#__PURE__*/React.createElement("circle", {
      key: i,
      cx: cx,
      cy: cy,
      r: radius(i),
      fill: "none",
      stroke: base,
      strokeWidth: on ? ringW * 0.95 : ringW * 0.7,
      opacity: st === "inactive" ? 0.4 : on ? 1 : 0.82,
      onClick: onSelect ? () => onSelect(i) : undefined,
      style: {
        cursor: onSelect ? "pointer" : "default",
        filter: on ? `drop-shadow(0 0 6px ${base})` : "none",
        transition: "stroke-width var(--motion-base), opacity var(--motion-base)",
        animation: st === "alert" ? "laforge-pulse var(--pulse-period) infinite" : "none"
      }
    });
  }), /*#__PURE__*/React.createElement("text", {
    x: cx,
    y: cy + 4,
    textAnchor: "middle",
    fontFamily: "var(--font-mono)",
    fontSize: size * 0.05,
    fontWeight: "700",
    fill: "var(--bg-0)"
  }, "R0"));
}
function SubTitle({
  children,
  hint
}) {
  return /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      alignItems: "baseline",
      gap: "10px",
      margin: "0 0 12px"
    }
  }, /*#__PURE__*/React.createElement("h2", {
    style: {
      margin: 0,
      fontSize: "13px",
      fontWeight: 700,
      textTransform: "uppercase",
      letterSpacing: "0.6px",
      color: "var(--text-secondary)"
    }
  }, children), hint && /*#__PURE__*/React.createElement("span", {
    style: {
      fontFamily: "var(--font-mono)",
      fontSize: "11px",
      color: "var(--text-dim)"
    }
  }, hint));
}

/* ===== Profils de conf : presets de souveraineté ===== */
const PROFILES = {
  full_local: {
    label: "Full local",
    icon: "house",
    power: 100,
    color: "var(--prov-local)",
    desc: "Tout sur la machine. Hors-ligne. Aucun connecteur cloud.",
    maxRing: 4
  },
  souverain: {
    label: "Local souverain + cloud",
    icon: "shield-check",
    power: 78,
    color: "var(--prov-local)",
    desc: "Local par défaut, cloud anonymisé au-delà d'un seuil.",
    maxRing: 6
  },
  hybride: {
    label: "Hybride",
    icon: "git-fork",
    power: 55,
    color: "var(--prov-hybrid)",
    desc: "Équilibre puissance/souveraineté, connecteurs branchés.",
    maxRing: 8
  },
  dev: {
    label: "Dev / paramétrable",
    icon: "terminal",
    power: 40,
    color: "var(--prov-remote)",
    desc: "Tout ouvert, rings configurables manuellement.",
    maxRing: 10
  }
};

/* ===== Scan machine ===== */
const HW = [{
  label: "NPU",
  detail: "AMD XDNA · 16 TOPS",
  icon: "cpu",
  ok: true,
  note: "embeddings + petits LLM"
}, {
  label: "iGPU",
  detail: "Radeon 780M · DML",
  icon: "gpu",
  ok: true,
  note: "inférence accélérée"
}, {
  label: "RAM",
  detail: "32 Go",
  icon: "memory-stick",
  ok: true,
  note: "LLM ≤ 14B en local"
}, {
  label: "Disque",
  detail: "SSD 1 To · 420 Go libres",
  icon: "hard-drive",
  ok: true,
  note: "RAG + modèles"
}, {
  label: "Réseau",
  detail: "Connecté",
  icon: "wifi",
  ok: true,
  note: "cloud disponible (optionnel)"
}];
const LOCAL_MODELS = [{
  name: "mistral:7b",
  tier: "local",
  ok: true
}, {
  name: "qwen2.5:14b",
  tier: "local",
  ok: true
}, {
  name: "bge-m3 (embed)",
  tier: "local",
  ok: true
}, {
  name: "llama:70b",
  tier: "cloud",
  ok: false
}];

/* ===== Tiers DB vectorielle ===== */
const DB_TIERS = [{
  tier: "AMI World",
  dims: "4096d",
  kind: "multivectoriel",
  icon: "globe",
  color: "var(--purple)",
  desc: "Mode monde multivectoriel — contexte riche, raisonnement long."
}, {
  tier: "Code · hot",
  dims: "1024d",
  kind: "FAISS",
  icon: "code",
  color: "var(--blue)",
  desc: "Tier chaud : code & artefacts récents, recherche FAISS rapide."
}, {
  tier: "RAG · cold",
  dims: "FTS",
  kind: "rerank RRF",
  icon: "snowflake",
  color: "var(--cyan)",
  desc: "Tier froid : full-text search + reranking (RRF) sur l'archive."
}];

/* ===== Modes de lancement ===== */
const LAUNCH = [{
  id: "tui",
  label: "TUI · PTY",
  icon: "square-terminal",
  desc: "Terminal interactif avec pseudo-TTY",
  prov: "local"
}, {
  id: "chat",
  label: "Chat LLM connecté",
  icon: "message-square",
  desc: "Dialogue multi-fournisseurs",
  prov: "hybrid"
}, {
  id: "ia_local",
  label: "Nokido IA locale",
  icon: "cpu",
  desc: "Agent souverain, 100% machine",
  prov: "local"
}, {
  id: "base",
  label: "Interface de base",
  icon: "layout-grid",
  desc: "Le hub complet (recommandé)",
  prov: "local"
}];
function SetupView() {
  const [profile, setProfile] = React.useState("souverain");
  const [power, setPower] = React.useState(PROFILES.souverain.power);
  const [launch, setLaunch] = React.useState("base");
  const pick = k => {
    setProfile(k);
    setPower(PROFILES[k].power);
  };
  return /*#__PURE__*/React.createElement("div", {
    style: {
      maxWidth: "1080px",
      margin: "0 auto",
      display: "flex",
      flexDirection: "column",
      gap: "26px"
    }
  }, /*#__PURE__*/React.createElement("div", null, /*#__PURE__*/React.createElement(SubTitle, {
    hint: "ce qui peut tourner en local vis-\xE0-vis des modules install\xE9s"
  }, "1 \xB7 Scan machine"), /*#__PURE__*/React.createElement("div", {
    style: {
      display: "grid",
      gridTemplateColumns: "repeat(auto-fill, minmax(190px, 1fr))",
      gap: "10px"
    }
  }, HW.map(h => /*#__PURE__*/React.createElement(Card, {
    key: h.label
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      alignItems: "center",
      gap: "9px"
    }
  }, /*#__PURE__*/React.createElement("span", {
    style: {
      display: "inline-flex",
      alignItems: "center",
      justifyContent: "center",
      width: "34px",
      height: "34px",
      borderRadius: "var(--radius-sm)",
      background: "var(--tint-green)",
      color: "var(--prov-local)"
    }
  }, /*#__PURE__*/React.createElement(UIco, {
    n: h.icon,
    s: 17
  })), /*#__PURE__*/React.createElement("div", {
    style: {
      flex: 1
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      fontSize: "13px",
      fontWeight: 700
    }
  }, h.label), /*#__PURE__*/React.createElement("div", {
    style: {
      fontFamily: "var(--font-mono)",
      fontSize: "10px",
      color: "var(--text-dim)"
    }
  }, h.detail)), /*#__PURE__*/React.createElement(UIco, {
    n: "check",
    s: 15
  })), /*#__PURE__*/React.createElement("div", {
    style: {
      fontSize: "11px",
      color: "var(--text-secondary)",
      marginTop: "8px"
    }
  }, h.note)))), /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      flexWrap: "wrap",
      gap: "7px",
      marginTop: "10px"
    }
  }, LOCAL_MODELS.map(m => /*#__PURE__*/React.createElement("span", {
    key: m.name,
    style: {
      display: "inline-flex",
      alignItems: "center",
      gap: "6px",
      padding: "4px 10px",
      borderRadius: "var(--radius-pill)",
      fontFamily: "var(--font-mono)",
      fontSize: "11px",
      border: `1px solid ${m.ok ? "var(--prov-local)" : "var(--border)"}`,
      color: m.ok ? "var(--prov-local)" : "var(--text-dim)",
      background: m.ok ? "var(--prov-local-tint)" : "transparent"
    }
  }, /*#__PURE__*/React.createElement(UIco, {
    n: m.ok ? "check" : "cloud",
    s: 12
  }), m.name)))), /*#__PURE__*/React.createElement("div", null, /*#__PURE__*/React.createElement(SubTitle, {
    hint: "confidentialit\xE9 \u2194 puissance \u2194 cloud"
  }, "2 \xB7 Compromis de souverainet\xE9"), /*#__PURE__*/React.createElement(PowerSlider, {
    value: power,
    onChange: setPower
  })), /*#__PURE__*/React.createElement("div", null, /*#__PURE__*/React.createElement(SubTitle, {
    hint: "conf optimis\xE9e selon tes crit\xE8res"
  }, "3 \xB7 Profil de configuration"), /*#__PURE__*/React.createElement("div", {
    style: {
      display: "grid",
      gridTemplateColumns: "repeat(auto-fit, minmax(230px, 1fr))",
      gap: "11px"
    }
  }, Object.entries(PROFILES).map(([k, p]) => {
    const on = profile === k;
    return /*#__PURE__*/React.createElement("button", {
      key: k,
      onClick: () => pick(k),
      style: {
        textAlign: "left",
        padding: "14px",
        borderRadius: "var(--radius-md)",
        cursor: "pointer",
        background: on ? "var(--bg-2)" : "var(--bg-1)",
        border: `1.5px solid ${on ? p.color : "var(--border)"}`,
        boxShadow: on ? `0 0 0 1px ${p.color}, 0 0 16px color-mix(in srgb, ${p.color} 16%, transparent)` : "none",
        color: "var(--text-primary)",
        fontFamily: "var(--font-sans)",
        transition: "all var(--motion-base)"
      }
    }, /*#__PURE__*/React.createElement("div", {
      style: {
        display: "flex",
        alignItems: "center",
        gap: "9px",
        marginBottom: "7px"
      }
    }, /*#__PURE__*/React.createElement("span", {
      style: {
        color: p.color
      }
    }, /*#__PURE__*/React.createElement(UIco, {
      n: p.icon,
      s: 18
    })), /*#__PURE__*/React.createElement("span", {
      style: {
        fontSize: "14px",
        fontWeight: 700
      }
    }, p.label), /*#__PURE__*/React.createElement("span", {
      style: {
        marginLeft: "auto",
        color: on ? p.color : "var(--text-disabled)"
      }
    }, /*#__PURE__*/React.createElement(UIco, {
      n: on ? "check-circle-2" : "circle",
      s: 17
    }))), /*#__PURE__*/React.createElement("div", {
      style: {
        fontSize: "11.5px",
        color: "var(--text-secondary)",
        lineHeight: 1.45
      }
    }, p.desc), /*#__PURE__*/React.createElement("div", {
      style: {
        marginTop: "9px",
        fontFamily: "var(--font-mono)",
        fontSize: "10px",
        color: "var(--text-dim)"
      }
    }, "jusqu'au ring ", p.maxRing, " \xB7 ", p.power, "% local"));
  }))), /*#__PURE__*/React.createElement("div", null, /*#__PURE__*/React.createElement(SubTitle, {
    hint: "deux mod\xE8les d'embeddings + tier froid"
  }, "4 \xB7 DB vectorielle multi-tiers"), /*#__PURE__*/React.createElement("div", {
    style: {
      display: "grid",
      gridTemplateColumns: "repeat(auto-fit, minmax(260px, 1fr))",
      gap: "11px"
    }
  }, DB_TIERS.map(d => /*#__PURE__*/React.createElement(Card, {
    key: d.tier
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      alignItems: "center",
      gap: "9px",
      marginBottom: "8px"
    }
  }, /*#__PURE__*/React.createElement("span", {
    style: {
      display: "inline-flex",
      alignItems: "center",
      justifyContent: "center",
      width: "34px",
      height: "34px",
      borderRadius: "var(--radius-sm)",
      background: `color-mix(in srgb, ${d.color} 16%, transparent)`,
      color: d.color
    }
  }, /*#__PURE__*/React.createElement(UIco, {
    n: d.icon,
    s: 17
  })), /*#__PURE__*/React.createElement("div", null, /*#__PURE__*/React.createElement("div", {
    style: {
      fontSize: "13.5px",
      fontWeight: 700
    }
  }, d.tier), /*#__PURE__*/React.createElement("div", {
    style: {
      fontFamily: "var(--font-mono)",
      fontSize: "10px",
      color: d.color
    }
  }, d.dims, " \xB7 ", d.kind))), /*#__PURE__*/React.createElement("div", {
    style: {
      fontSize: "11.5px",
      color: "var(--text-secondary)",
      lineHeight: 1.45
    }
  }, d.desc))))), /*#__PURE__*/React.createElement("div", null, /*#__PURE__*/React.createElement(SubTitle, {
    hint: "selon le contr\xF4le souhait\xE9"
  }, "5 \xB7 Mode de lancement"), /*#__PURE__*/React.createElement("div", {
    style: {
      display: "grid",
      gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))",
      gap: "11px"
    }
  }, LAUNCH.map(l => {
    const on = launch === l.id;
    return /*#__PURE__*/React.createElement("button", {
      key: l.id,
      onClick: () => setLaunch(l.id),
      style: {
        textAlign: "left",
        padding: "13px",
        borderRadius: "var(--radius-md)",
        cursor: "pointer",
        background: on ? "var(--bg-3)" : "var(--bg-2)",
        border: `1px solid ${on ? "var(--purple)" : "var(--border)"}`,
        color: "var(--text-primary)",
        fontFamily: "var(--font-sans)"
      }
    }, /*#__PURE__*/React.createElement("div", {
      style: {
        display: "flex",
        alignItems: "center",
        gap: "9px"
      }
    }, /*#__PURE__*/React.createElement("span", {
      style: {
        color: "var(--purple)"
      }
    }, /*#__PURE__*/React.createElement(UIco, {
      n: l.icon,
      s: 17
    })), /*#__PURE__*/React.createElement("span", {
      style: {
        fontSize: "13.5px",
        fontWeight: 700
      }
    }, l.label)), /*#__PURE__*/React.createElement("div", {
      style: {
        fontSize: "11px",
        color: "var(--text-secondary)",
        margin: "6px 0 8px"
      }
    }, l.desc), uprov() && /*#__PURE__*/React.createElement(ProvenanceBadge, {
      origin: l.prov,
      size: "sm"
    }));
  }))), /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      gap: "10px",
      paddingTop: "6px",
      borderTop: "1px solid var(--border-subtle)"
    }
  }, /*#__PURE__*/React.createElement(Button, {
    variant: "primary",
    size: "lg",
    icon: /*#__PURE__*/React.createElement(UIco, {
      n: "rocket",
      s: 16
    })
  }, "Lancer Nokido"), /*#__PURE__*/React.createElement(Button, {
    variant: "ghost",
    size: "lg",
    icon: /*#__PURE__*/React.createElement(UIco, {
      n: "share-2",
      s: 15
    }),
    onClick: () => window.__WH_GO && window.__WH_GO("rings")
  }, "Voir le placement sur les rings")));
}

/* ===== Rings : placement des agents ===== */
const AGENT_RING = [{
  ring: 0,
  agent: "Lois fondatrices",
  implies: "Immuables. Aucun agent ne peut les modifier.",
  prov: "local"
}, {
  ring: 1,
  agent: "Cœur Nokido",
  implies: "Orchestrateur souverain. Confiance maximale.",
  prov: "local"
}, {
  ring: 2,
  agent: "Toi (humain TRUSTED)",
  implies: "Validation finale, révocation, kill switch.",
  prov: "local"
}, {
  ring: 3,
  agent: "Agents validés",
  implies: "Exécutent sans confirmation dans leur périmètre.",
  prov: "local"
}, {
  ring: 4,
  agent: "Agents externes",
  implies: "Sandbox, confirmation requise pour agir.",
  prov: "hybrid"
}, {
  ring: 5,
  agent: "RAG web",
  implies: "Lecture seule, sources distantes anonymisées.",
  prov: "hybrid"
}, {
  ring: 8,
  agent: "Monitoring",
  implies: "Observe, n'agit pas. Lecture des organes.",
  prov: "local"
}, {
  ring: 9,
  agent: "Système hôte",
  implies: "Accès OS — le ring le plus surveillé.",
  prov: "remote"
}];
function RingsView() {
  const [sel, setSel] = React.useState(2);
  const [profile, setProfile] = React.useState("souverain");
  const maxRing = PROFILES[profile].maxRing;
  const states = {};
  for (let i = 0; i <= 10; i++) states[i] = i > maxRing ? "inactive" : "ok";
  if (sel === 9) states[9] = "alert";
  const selInfo = AGENT_RING.find(a => a.ring === sel);
  return /*#__PURE__*/React.createElement("div", {
    style: {
      maxWidth: "1080px",
      margin: "0 auto"
    }
  }, /*#__PURE__*/React.createElement(SubTitle, {
    hint: "sur quelle couche placer un agent \u2014 et ce que \xE7a implique"
  }, "Placement sur les 11 rings"), /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      gap: "7px",
      flexWrap: "wrap",
      marginBottom: "16px"
    }
  }, Object.entries(PROFILES).map(([k, p]) => {
    const on = profile === k;
    return /*#__PURE__*/React.createElement("button", {
      key: k,
      onClick: () => setProfile(k),
      style: {
        display: "inline-flex",
        alignItems: "center",
        gap: "6px",
        padding: "6px 12px",
        borderRadius: "var(--radius-pill)",
        cursor: "pointer",
        fontFamily: "var(--font-sans)",
        fontSize: "12px",
        fontWeight: 600,
        border: `1px solid ${on ? p.color : "var(--border)"}`,
        background: on ? "color-mix(in srgb, " + p.color + " 14%, transparent)" : "transparent",
        color: on ? p.color : "var(--text-secondary)"
      }
    }, /*#__PURE__*/React.createElement(UIco, {
      n: p.icon,
      s: 14
    }), p.label);
  })), /*#__PURE__*/React.createElement("div", {
    style: {
      display: "grid",
      gridTemplateColumns: "minmax(440px, 1fr) 320px",
      gap: "18px",
      alignItems: "start"
    }
  }, /*#__PURE__*/React.createElement(Card, {
    style: {
      background: "var(--bg-1)",
      display: "flex",
      justifyContent: "center"
    }
  }, /*#__PURE__*/React.createElement(RingDial, {
    states: states,
    selected: sel,
    onSelect: setSel,
    size: 320
  })), /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      flexDirection: "column",
      gap: "12px"
    }
  }, /*#__PURE__*/React.createElement(Card, null, /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      alignItems: "center",
      gap: "9px",
      marginBottom: "8px"
    }
  }, /*#__PURE__*/React.createElement("span", {
    style: {
      width: "12px",
      height: "12px",
      borderRadius: "50%",
      background: ringColor(sel),
      boxShadow: `0 0 8px ${ringColor(sel)}`
    }
  }), /*#__PURE__*/React.createElement("span", {
    style: {
      fontSize: "15px",
      fontWeight: 700
    }
  }, "Ring ", sel), selInfo && uprov() && /*#__PURE__*/React.createElement(ProvenanceBadge, {
    origin: selInfo.prov,
    size: "sm",
    style: {
      marginLeft: "auto"
    }
  })), /*#__PURE__*/React.createElement("div", {
    style: {
      fontSize: "13.5px",
      fontWeight: 600,
      marginBottom: "5px"
    }
  }, selInfo ? selInfo.agent : RING_DESC[sel]), /*#__PURE__*/React.createElement("div", {
    style: {
      fontSize: "12px",
      color: "var(--text-secondary)",
      lineHeight: 1.5
    }
  }, selInfo ? selInfo.implies : "Couche disponible — aucun agent placé pour ce profil."), sel > maxRing && /*#__PURE__*/React.createElement("div", {
    style: {
      marginTop: "10px",
      fontFamily: "var(--font-mono)",
      fontSize: "10.5px",
      color: "var(--yellow)",
      display: "flex",
      alignItems: "center",
      gap: "6px"
    }
  }, /*#__PURE__*/React.createElement(UIco, {
    n: "lock",
    s: 12
  }), "verrouill\xE9 par le profil \xAB ", PROFILES[profile].label, " \xBB")), /*#__PURE__*/React.createElement(Card, null, /*#__PURE__*/React.createElement("div", {
    style: {
      fontFamily: "var(--font-mono)",
      fontSize: "10px",
      textTransform: "uppercase",
      letterSpacing: "0.5px",
      color: "var(--text-dim)",
      marginBottom: "9px"
    }
  }, "Agents plac\xE9s"), /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      flexDirection: "column",
      gap: "5px"
    }
  }, AGENT_RING.map(a => /*#__PURE__*/React.createElement("button", {
    key: a.ring,
    onClick: () => setSel(a.ring),
    style: {
      display: "flex",
      alignItems: "center",
      gap: "9px",
      padding: "5px 7px",
      borderRadius: "var(--radius-sm)",
      border: "none",
      cursor: "pointer",
      background: sel === a.ring ? "var(--bg-3)" : "transparent",
      textAlign: "left",
      width: "100%",
      fontFamily: "var(--font-sans)"
    }
  }, /*#__PURE__*/React.createElement("span", {
    style: {
      fontFamily: "var(--font-mono)",
      fontSize: "10px",
      color: "var(--text-dim)",
      width: "16px",
      flexShrink: 0
    }
  }, a.ring), /*#__PURE__*/React.createElement("span", {
    style: {
      width: "8px",
      height: "8px",
      borderRadius: "50%",
      background: ringColor(a.ring),
      flexShrink: 0,
      opacity: a.ring > maxRing ? 0.35 : 1
    }
  }), /*#__PURE__*/React.createElement("span", {
    style: {
      fontSize: "12px",
      color: a.ring > maxRing ? "var(--text-dim)" : "var(--text-secondary)"
    }
  }, a.agent))))))));
}
Object.assign(window, {
  SetupView,
  RingsView
});
})(); } catch (e) { __ds_ns.__errors.push({ path: "ui_kits/webhub/web-hub-setup.ref.jsx", error: String((e && e.message) || e) }); }

// ui_kits/webhub/tweaks-panel.jsx
try { (() => {
// @ds-adherence-ignore -- omelette starter scaffold (raw elements/hex/px by design)

/* BEGIN USAGE */
// tweaks-panel.jsx
// Reusable Tweaks shell + form-control helpers.
// Exports (to window): useTweaks, TweaksPanel, TweakSection, TweakRow, TweakSlider,
//   TweakToggle, TweakRadio, TweakSelect, TweakText, TweakNumber, TweakColor, TweakButton.
//
// Owns the host protocol (listens for __activate_edit_mode / __deactivate_edit_mode,
// posts __edit_mode_available / __edit_mode_set_keys / __edit_mode_dismissed) so
// individual prototypes don't re-roll it. Ships a consistent set of controls so you
// don't hand-draw <input type="range">, segmented radios, steppers, etc.
//
// Usage (in an HTML file that loads React + Babel):
//
//   const TWEAK_DEFAULTS = /*EDITMODE-BEGIN*/{
//     "primaryColor": "#D97757",
//     "palette": ["#D97757", "#29261b", "#f6f4ef"],
//     "fontSize": 16,
//     "density": "regular",
//     "dark": false
//   }/*EDITMODE-END*/;
//
//   function App() {
//     const [t, setTweak] = useTweaks(TWEAK_DEFAULTS);
//     return (
//       <div style={{ fontSize: t.fontSize, color: t.primaryColor }}>
//         Hello
//         <TweaksPanel>
//           <TweakSection label="Typography" />
//           <TweakSlider label="Font size" value={t.fontSize} min={10} max={32} unit="px"
//                        onChange={(v) => setTweak('fontSize', v)} />
//           <TweakRadio  label="Density" value={t.density}
//                        options={['compact', 'regular', 'comfy']}
//                        onChange={(v) => setTweak('density', v)} />
//           <TweakSection label="Theme" />
//           <TweakColor  label="Primary" value={t.primaryColor}
//                        options={['#D97757', '#2A6FDB', '#1F8A5B', '#7A5AE0']}
//                        onChange={(v) => setTweak('primaryColor', v)} />
//           <TweakColor  label="Palette" value={t.palette}
//                        options={[['#D97757', '#29261b', '#f6f4ef'],
//                                  ['#475569', '#0f172a', '#f1f5f9']]}
//                        onChange={(v) => setTweak('palette', v)} />
//           <TweakToggle label="Dark mode" value={t.dark}
//                        onChange={(v) => setTweak('dark', v)} />
//         </TweaksPanel>
//       </div>
//     );
//   }
//
// TweakRadio is the segmented control for 2–3 short options (auto-falls-back to
// TweakSelect past ~16/~10 chars per label); reach for TweakSelect directly when
// options are many or long. For color tweaks always curate 3-4 options rather than
// a free picker; an option can also be a whole 2–5 color palette (the stored value
// is the array). The Tweak* controls are a floor, not a ceiling — build custom
// controls inside the panel if a tweak calls for UI they don't cover.
/* END USAGE */
// ─────────────────────────────────────────────────────────────────────────────

const __TWEAKS_STYLE = `
  .twk-panel{position:fixed;right:16px;bottom:16px;z-index:2147483646;width:280px;
    max-height:calc(100vh - 32px);display:flex;flex-direction:column;
    transform:scale(var(--dc-inv-zoom,1));transform-origin:bottom right;
    background:rgba(250,249,247,.78);color:#29261b;
    -webkit-backdrop-filter:blur(24px) saturate(160%);backdrop-filter:blur(24px) saturate(160%);
    border:.5px solid rgba(255,255,255,.6);border-radius:14px;
    box-shadow:0 1px 0 rgba(255,255,255,.5) inset,0 12px 40px rgba(0,0,0,.18);
    font:11.5px/1.4 ui-sans-serif,system-ui,-apple-system,sans-serif;overflow:hidden}
  .twk-hd{display:flex;align-items:center;justify-content:space-between;
    padding:10px 8px 10px 14px;cursor:move;user-select:none}
  .twk-hd b{font-size:12px;font-weight:600;letter-spacing:.01em}
  .twk-x{appearance:none;border:0;background:transparent;color:rgba(41,38,27,.55);
    width:22px;height:22px;border-radius:6px;cursor:default;font-size:13px;line-height:1}
  .twk-x:hover{background:rgba(0,0,0,.06);color:#29261b}
  .twk-body{padding:2px 14px 14px;display:flex;flex-direction:column;gap:10px;
    overflow-y:auto;overflow-x:hidden;min-height:0;
    scrollbar-width:thin;scrollbar-color:rgba(0,0,0,.15) transparent}
  .twk-body::-webkit-scrollbar{width:8px}
  .twk-body::-webkit-scrollbar-track{background:transparent;margin:2px}
  .twk-body::-webkit-scrollbar-thumb{background:rgba(0,0,0,.15);border-radius:4px;
    border:2px solid transparent;background-clip:content-box}
  .twk-body::-webkit-scrollbar-thumb:hover{background:rgba(0,0,0,.25);
    border:2px solid transparent;background-clip:content-box}
  .twk-row{display:flex;flex-direction:column;gap:5px}
  .twk-row-h{flex-direction:row;align-items:center;justify-content:space-between;gap:10px}
  .twk-lbl{display:flex;justify-content:space-between;align-items:baseline;
    color:rgba(41,38,27,.72)}
  .twk-lbl>span:first-child{font-weight:500}
  .twk-val{color:rgba(41,38,27,.5);font-variant-numeric:tabular-nums}

  .twk-sect{font-size:10px;font-weight:600;letter-spacing:.06em;text-transform:uppercase;
    color:rgba(41,38,27,.45);padding:10px 0 0}
  .twk-sect:first-child{padding-top:0}

  .twk-field{appearance:none;box-sizing:border-box;width:100%;min-width:0;height:26px;padding:0 8px;
    border:.5px solid rgba(0,0,0,.1);border-radius:7px;
    background:rgba(255,255,255,.6);color:inherit;font:inherit;outline:none}
  .twk-field:focus{border-color:rgba(0,0,0,.25);background:rgba(255,255,255,.85)}
  select.twk-field{padding-right:22px;
    background-image:url("data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' width='10' height='6' viewBox='0 0 10 6'><path fill='rgba(0,0,0,.5)' d='M0 0h10L5 6z'/></svg>");
    background-repeat:no-repeat;background-position:right 8px center}

  .twk-slider{appearance:none;-webkit-appearance:none;width:100%;height:4px;margin:6px 0;
    border-radius:999px;background:rgba(0,0,0,.12);outline:none}
  .twk-slider::-webkit-slider-thumb{-webkit-appearance:none;appearance:none;
    width:14px;height:14px;border-radius:50%;background:#fff;
    border:.5px solid rgba(0,0,0,.12);box-shadow:0 1px 3px rgba(0,0,0,.2);cursor:default}
  .twk-slider::-moz-range-thumb{width:14px;height:14px;border-radius:50%;
    background:#fff;border:.5px solid rgba(0,0,0,.12);box-shadow:0 1px 3px rgba(0,0,0,.2);cursor:default}

  .twk-seg{position:relative;display:flex;padding:2px;border-radius:8px;
    background:rgba(0,0,0,.06);user-select:none}
  .twk-seg-thumb{position:absolute;top:2px;bottom:2px;border-radius:6px;
    background:rgba(255,255,255,.9);box-shadow:0 1px 2px rgba(0,0,0,.12);
    transition:left .15s cubic-bezier(.3,.7,.4,1),width .15s}
  .twk-seg.dragging .twk-seg-thumb{transition:none}
  .twk-seg button{appearance:none;position:relative;z-index:1;flex:1;border:0;
    background:transparent;color:inherit;font:inherit;font-weight:500;min-height:22px;
    border-radius:6px;cursor:default;padding:4px 6px;line-height:1.2;
    overflow-wrap:anywhere}

  .twk-toggle{position:relative;width:32px;height:18px;border:0;border-radius:999px;
    background:rgba(0,0,0,.15);transition:background .15s;cursor:default;padding:0}
  .twk-toggle[data-on="1"]{background:#34c759}
  .twk-toggle i{position:absolute;top:2px;left:2px;width:14px;height:14px;border-radius:50%;
    background:#fff;box-shadow:0 1px 2px rgba(0,0,0,.25);transition:transform .15s}
  .twk-toggle[data-on="1"] i{transform:translateX(14px)}

  .twk-num{display:flex;align-items:center;box-sizing:border-box;min-width:0;height:26px;padding:0 0 0 8px;
    border:.5px solid rgba(0,0,0,.1);border-radius:7px;background:rgba(255,255,255,.6)}
  .twk-num-lbl{font-weight:500;color:rgba(41,38,27,.6);cursor:ew-resize;
    user-select:none;padding-right:8px}
  .twk-num input{flex:1;min-width:0;height:100%;border:0;background:transparent;
    font:inherit;font-variant-numeric:tabular-nums;text-align:right;padding:0 8px 0 0;
    outline:none;color:inherit;-moz-appearance:textfield}
  .twk-num input::-webkit-inner-spin-button,.twk-num input::-webkit-outer-spin-button{
    -webkit-appearance:none;margin:0}
  .twk-num-unit{padding-right:8px;color:rgba(41,38,27,.45)}

  .twk-btn{appearance:none;height:26px;padding:0 12px;border:0;border-radius:7px;
    background:rgba(0,0,0,.78);color:#fff;font:inherit;font-weight:500;cursor:default}
  .twk-btn:hover{background:rgba(0,0,0,.88)}
  .twk-btn.secondary{background:rgba(0,0,0,.06);color:inherit}
  .twk-btn.secondary:hover{background:rgba(0,0,0,.1)}

  .twk-swatch{appearance:none;-webkit-appearance:none;width:56px;height:22px;
    border:.5px solid rgba(0,0,0,.1);border-radius:6px;padding:0;cursor:default;
    background:transparent;flex-shrink:0}
  .twk-swatch::-webkit-color-swatch-wrapper{padding:0}
  .twk-swatch::-webkit-color-swatch{border:0;border-radius:5.5px}
  .twk-swatch::-moz-color-swatch{border:0;border-radius:5.5px}

  .twk-chips{display:flex;gap:6px}
  .twk-chip{position:relative;appearance:none;flex:1;min-width:0;height:46px;
    padding:0;border:0;border-radius:6px;overflow:hidden;cursor:default;
    box-shadow:0 0 0 .5px rgba(0,0,0,.12),0 1px 2px rgba(0,0,0,.06);
    transition:transform .12s cubic-bezier(.3,.7,.4,1),box-shadow .12s}
  .twk-chip:hover{transform:translateY(-1px);
    box-shadow:0 0 0 .5px rgba(0,0,0,.18),0 4px 10px rgba(0,0,0,.12)}
  .twk-chip[data-on="1"]{box-shadow:0 0 0 1.5px rgba(0,0,0,.85),
    0 2px 6px rgba(0,0,0,.15)}
  .twk-chip>span{position:absolute;top:0;bottom:0;right:0;width:34%;
    display:flex;flex-direction:column;box-shadow:-1px 0 0 rgba(0,0,0,.1)}
  .twk-chip>span>i{flex:1;box-shadow:0 -1px 0 rgba(0,0,0,.1)}
  .twk-chip>span>i:first-child{box-shadow:none}
  .twk-chip svg{position:absolute;top:6px;left:6px;width:13px;height:13px;
    filter:drop-shadow(0 1px 1px rgba(0,0,0,.3))}
`;

// ── useTweaks ───────────────────────────────────────────────────────────────
// Single source of truth for tweak values. setTweak persists via the host
// (__edit_mode_set_keys → host rewrites the EDITMODE block on disk).
function useTweaks(defaults) {
  const [values, setValues] = React.useState(defaults);
  // Accepts either setTweak('key', value) or setTweak({ key: value, ... }) so a
  // useState-style call doesn't write a "[object Object]" key into the persisted
  // JSON block.
  const setTweak = React.useCallback((keyOrEdits, val) => {
    const edits = typeof keyOrEdits === 'object' && keyOrEdits !== null ? keyOrEdits : {
      [keyOrEdits]: val
    };
    setValues(prev => ({
      ...prev,
      ...edits
    }));
    window.parent.postMessage({
      type: '__edit_mode_set_keys',
      edits
    }, '*');
    // Same-window signal so in-page listeners (deck-stage rail thumbnails)
    // can react — the parent message only reaches the host, not peers.
    window.dispatchEvent(new CustomEvent('tweakchange', {
      detail: edits
    }));
  }, []);
  return [values, setTweak];
}

// ── TweaksPanel ─────────────────────────────────────────────────────────────
// Floating shell. Registers the protocol listener BEFORE announcing
// availability — if the announce ran first, the host's activate could land
// before our handler exists and the toolbar toggle would silently no-op.
// The close button posts __edit_mode_dismissed so the host's toolbar toggle
// flips off in lockstep; the host echoes __deactivate_edit_mode back which
// is what actually hides the panel.
function TweaksPanel({
  title = 'Tweaks',
  children
}) {
  const [open, setOpen] = React.useState(false);
  const dragRef = React.useRef(null);
  const offsetRef = React.useRef({
    x: 16,
    y: 16
  });
  const PAD = 16;
  const clampToViewport = React.useCallback(() => {
    const panel = dragRef.current;
    if (!panel) return;
    const w = panel.offsetWidth,
      h = panel.offsetHeight;
    const maxRight = Math.max(PAD, window.innerWidth - w - PAD);
    const maxBottom = Math.max(PAD, window.innerHeight - h - PAD);
    offsetRef.current = {
      x: Math.min(maxRight, Math.max(PAD, offsetRef.current.x)),
      y: Math.min(maxBottom, Math.max(PAD, offsetRef.current.y))
    };
    panel.style.right = offsetRef.current.x + 'px';
    panel.style.bottom = offsetRef.current.y + 'px';
  }, []);
  React.useEffect(() => {
    if (!open) return;
    clampToViewport();
    if (typeof ResizeObserver === 'undefined') {
      window.addEventListener('resize', clampToViewport);
      return () => window.removeEventListener('resize', clampToViewport);
    }
    const ro = new ResizeObserver(clampToViewport);
    ro.observe(document.documentElement);
    return () => ro.disconnect();
  }, [open, clampToViewport]);
  React.useEffect(() => {
    const onMsg = e => {
      const t = e?.data?.type;
      if (t === '__activate_edit_mode') setOpen(true);else if (t === '__deactivate_edit_mode') setOpen(false);
    };
    window.addEventListener('message', onMsg);
    window.parent.postMessage({
      type: '__edit_mode_available'
    }, '*');
    return () => window.removeEventListener('message', onMsg);
  }, []);
  const dismiss = () => {
    setOpen(false);
    window.parent.postMessage({
      type: '__edit_mode_dismissed'
    }, '*');
  };
  const onDragStart = e => {
    const panel = dragRef.current;
    if (!panel) return;
    const r = panel.getBoundingClientRect();
    const sx = e.clientX,
      sy = e.clientY;
    const startRight = window.innerWidth - r.right;
    const startBottom = window.innerHeight - r.bottom;
    const move = ev => {
      offsetRef.current = {
        x: startRight - (ev.clientX - sx),
        y: startBottom - (ev.clientY - sy)
      };
      clampToViewport();
    };
    const up = () => {
      window.removeEventListener('mousemove', move);
      window.removeEventListener('mouseup', up);
    };
    window.addEventListener('mousemove', move);
    window.addEventListener('mouseup', up);
  };
  if (!open) return null;
  return /*#__PURE__*/React.createElement(React.Fragment, null, /*#__PURE__*/React.createElement("style", null, __TWEAKS_STYLE), /*#__PURE__*/React.createElement("div", {
    ref: dragRef,
    className: "twk-panel",
    "data-omelette-chrome": "",
    style: {
      right: offsetRef.current.x,
      bottom: offsetRef.current.y
    }
  }, /*#__PURE__*/React.createElement("div", {
    className: "twk-hd",
    onMouseDown: onDragStart
  }, /*#__PURE__*/React.createElement("b", null, title), /*#__PURE__*/React.createElement("button", {
    className: "twk-x",
    "aria-label": "Close tweaks",
    onMouseDown: e => e.stopPropagation(),
    onClick: dismiss
  }, "\u2715")), /*#__PURE__*/React.createElement("div", {
    className: "twk-body"
  }, children)));
}

// ── Layout helpers ──────────────────────────────────────────────────────────

function TweakSection({
  label,
  children
}) {
  return /*#__PURE__*/React.createElement(React.Fragment, null, /*#__PURE__*/React.createElement("div", {
    className: "twk-sect"
  }, label), children);
}
function TweakRow({
  label,
  value,
  children,
  inline = false
}) {
  return /*#__PURE__*/React.createElement("div", {
    className: inline ? 'twk-row twk-row-h' : 'twk-row'
  }, /*#__PURE__*/React.createElement("div", {
    className: "twk-lbl"
  }, /*#__PURE__*/React.createElement("span", null, label), value != null && /*#__PURE__*/React.createElement("span", {
    className: "twk-val"
  }, value)), children);
}

// ── Controls ────────────────────────────────────────────────────────────────

function TweakSlider({
  label,
  value,
  min = 0,
  max = 100,
  step = 1,
  unit = '',
  onChange
}) {
  return /*#__PURE__*/React.createElement(TweakRow, {
    label: label,
    value: `${value}${unit}`
  }, /*#__PURE__*/React.createElement("input", {
    type: "range",
    className: "twk-slider",
    min: min,
    max: max,
    step: step,
    value: value,
    onChange: e => onChange(Number(e.target.value))
  }));
}
function TweakToggle({
  label,
  value,
  onChange
}) {
  return /*#__PURE__*/React.createElement("div", {
    className: "twk-row twk-row-h"
  }, /*#__PURE__*/React.createElement("div", {
    className: "twk-lbl"
  }, /*#__PURE__*/React.createElement("span", null, label)), /*#__PURE__*/React.createElement("button", {
    type: "button",
    className: "twk-toggle",
    "data-on": value ? '1' : '0',
    role: "switch",
    "aria-checked": !!value,
    onClick: () => onChange(!value)
  }, /*#__PURE__*/React.createElement("i", null)));
}
function TweakRadio({
  label,
  value,
  options,
  onChange
}) {
  const trackRef = React.useRef(null);
  const [dragging, setDragging] = React.useState(false);
  // The active value is read by pointer-move handlers attached for the lifetime
  // of a drag — ref it so a stale closure doesn't fire onChange for every move.
  const valueRef = React.useRef(value);
  valueRef.current = value;

  // Segments wrap mid-word once per-segment width runs out. The track is
  // ~248px (280 panel − 28 body pad − 4 seg pad), each button loses 12px
  // to its own padding, and 11.5px system-ui averages ~6.3px/char — so 2
  // options fit ~16 chars each, 3 fit ~10. Past that (or >3 options), fall
  // back to a dropdown rather than wrap.
  const labelLen = o => String(typeof o === 'object' ? o.label : o).length;
  const maxLen = options.reduce((m, o) => Math.max(m, labelLen(o)), 0);
  const fitsAsSegments = maxLen <= ({
    2: 16,
    3: 10
  }[options.length] ?? 0);
  if (!fitsAsSegments) {
    // <select> emits strings — map back to the original option value so the
    // fallback stays type-preserving (numbers, booleans) like the segment path.
    const resolve = s => {
      const m = options.find(o => String(typeof o === 'object' ? o.value : o) === s);
      return m === undefined ? s : typeof m === 'object' ? m.value : m;
    };
    return /*#__PURE__*/React.createElement(TweakSelect, {
      label: label,
      value: value,
      options: options,
      onChange: s => onChange(resolve(s))
    });
  }
  const opts = options.map(o => typeof o === 'object' ? o : {
    value: o,
    label: o
  });
  const idx = Math.max(0, opts.findIndex(o => o.value === value));
  const n = opts.length;
  const segAt = clientX => {
    const r = trackRef.current.getBoundingClientRect();
    const inner = r.width - 4;
    const i = Math.floor((clientX - r.left - 2) / inner * n);
    return opts[Math.max(0, Math.min(n - 1, i))].value;
  };
  const onPointerDown = e => {
    setDragging(true);
    const v0 = segAt(e.clientX);
    if (v0 !== valueRef.current) onChange(v0);
    const move = ev => {
      if (!trackRef.current) return;
      const v = segAt(ev.clientX);
      if (v !== valueRef.current) onChange(v);
    };
    const up = () => {
      setDragging(false);
      window.removeEventListener('pointermove', move);
      window.removeEventListener('pointerup', up);
    };
    window.addEventListener('pointermove', move);
    window.addEventListener('pointerup', up);
  };
  return /*#__PURE__*/React.createElement(TweakRow, {
    label: label
  }, /*#__PURE__*/React.createElement("div", {
    ref: trackRef,
    role: "radiogroup",
    onPointerDown: onPointerDown,
    className: dragging ? 'twk-seg dragging' : 'twk-seg'
  }, /*#__PURE__*/React.createElement("div", {
    className: "twk-seg-thumb",
    style: {
      left: `calc(2px + ${idx} * (100% - 4px) / ${n})`,
      width: `calc((100% - 4px) / ${n})`
    }
  }), opts.map(o => /*#__PURE__*/React.createElement("button", {
    key: o.value,
    type: "button",
    role: "radio",
    "aria-checked": o.value === value
  }, o.label))));
}
function TweakSelect({
  label,
  value,
  options,
  onChange
}) {
  return /*#__PURE__*/React.createElement(TweakRow, {
    label: label
  }, /*#__PURE__*/React.createElement("select", {
    className: "twk-field",
    value: value,
    onChange: e => onChange(e.target.value)
  }, options.map(o => {
    const v = typeof o === 'object' ? o.value : o;
    const l = typeof o === 'object' ? o.label : o;
    return /*#__PURE__*/React.createElement("option", {
      key: v,
      value: v
    }, l);
  })));
}
function TweakText({
  label,
  value,
  placeholder,
  onChange
}) {
  return /*#__PURE__*/React.createElement(TweakRow, {
    label: label
  }, /*#__PURE__*/React.createElement("input", {
    className: "twk-field",
    type: "text",
    value: value,
    placeholder: placeholder,
    onChange: e => onChange(e.target.value)
  }));
}
function TweakNumber({
  label,
  value,
  min,
  max,
  step = 1,
  unit = '',
  onChange
}) {
  const clamp = n => {
    if (min != null && n < min) return min;
    if (max != null && n > max) return max;
    return n;
  };
  const startRef = React.useRef({
    x: 0,
    val: 0
  });
  const onScrubStart = e => {
    e.preventDefault();
    startRef.current = {
      x: e.clientX,
      val: value
    };
    const decimals = (String(step).split('.')[1] || '').length;
    const move = ev => {
      const dx = ev.clientX - startRef.current.x;
      const raw = startRef.current.val + dx * step;
      const snapped = Math.round(raw / step) * step;
      onChange(clamp(Number(snapped.toFixed(decimals))));
    };
    const up = () => {
      window.removeEventListener('pointermove', move);
      window.removeEventListener('pointerup', up);
    };
    window.addEventListener('pointermove', move);
    window.addEventListener('pointerup', up);
  };
  return /*#__PURE__*/React.createElement("div", {
    className: "twk-num"
  }, /*#__PURE__*/React.createElement("span", {
    className: "twk-num-lbl",
    onPointerDown: onScrubStart
  }, label), /*#__PURE__*/React.createElement("input", {
    type: "number",
    value: value,
    min: min,
    max: max,
    step: step,
    onChange: e => onChange(clamp(Number(e.target.value)))
  }), unit && /*#__PURE__*/React.createElement("span", {
    className: "twk-num-unit"
  }, unit));
}

// Relative-luminance contrast pick — checkmarks drawn over a swatch need to
// read on both #111 and #fafafa without per-option configuration. Hex input
// only (#rgb / #rrggbb); named or rgb()/hsl() colors fall through to "light".
function __twkIsLight(hex) {
  const h = String(hex).replace('#', '');
  const x = h.length === 3 ? h.replace(/./g, c => c + c) : h.padEnd(6, '0');
  const n = parseInt(x.slice(0, 6), 16);
  if (Number.isNaN(n)) return true;
  const r = n >> 16 & 255,
    g = n >> 8 & 255,
    b = n & 255;
  return r * 299 + g * 587 + b * 114 > 148000;
}
const __TwkCheck = ({
  light
}) => /*#__PURE__*/React.createElement("svg", {
  viewBox: "0 0 14 14",
  "aria-hidden": "true"
}, /*#__PURE__*/React.createElement("path", {
  d: "M3 7.2 5.8 10 11 4.2",
  fill: "none",
  strokeWidth: "2.2",
  strokeLinecap: "round",
  strokeLinejoin: "round",
  stroke: light ? 'rgba(0,0,0,.78)' : '#fff'
}));

// TweakColor — curated color/palette picker. Each option is either a single
// hex string or an array of 1-5 hex strings; the card adapts — a lone color
// renders solid, a palette renders colors[0] as the hero (left ~2/3) with the
// rest stacked in a sharp column on the right. onChange emits the
// option in the shape it was passed (string stays string, array stays array).
// Without options it falls back to the native color input for back-compat.
function TweakColor({
  label,
  value,
  options,
  onChange
}) {
  if (!options || !options.length) {
    return /*#__PURE__*/React.createElement("div", {
      className: "twk-row twk-row-h"
    }, /*#__PURE__*/React.createElement("div", {
      className: "twk-lbl"
    }, /*#__PURE__*/React.createElement("span", null, label)), /*#__PURE__*/React.createElement("input", {
      type: "color",
      className: "twk-swatch",
      value: value,
      onChange: e => onChange(e.target.value)
    }));
  }
  // Native <input type=color> emits lowercase hex per the HTML spec, so
  // compare case-insensitively. String() guards JSON.stringify(undefined),
  // which returns the primitive undefined (no .toLowerCase).
  const key = o => String(JSON.stringify(o)).toLowerCase();
  const cur = key(value);
  return /*#__PURE__*/React.createElement(TweakRow, {
    label: label
  }, /*#__PURE__*/React.createElement("div", {
    className: "twk-chips",
    role: "radiogroup"
  }, options.map((o, i) => {
    const colors = Array.isArray(o) ? o : [o];
    const [hero, ...rest] = colors;
    const sup = rest.slice(0, 4);
    const on = key(o) === cur;
    return /*#__PURE__*/React.createElement("button", {
      key: i,
      type: "button",
      className: "twk-chip",
      role: "radio",
      "aria-checked": on,
      "data-on": on ? '1' : '0',
      "aria-label": colors.join(', '),
      title: colors.join(' · '),
      style: {
        background: hero
      },
      onClick: () => onChange(o)
    }, sup.length > 0 && /*#__PURE__*/React.createElement("span", null, sup.map((c, j) => /*#__PURE__*/React.createElement("i", {
      key: j,
      style: {
        background: c
      }
    }))), on && /*#__PURE__*/React.createElement(__TwkCheck, {
      light: __twkIsLight(hero)
    }));
  })));
}
function TweakButton({
  label,
  onClick,
  secondary = false
}) {
  return /*#__PURE__*/React.createElement("button", {
    type: "button",
    className: secondary ? 'twk-btn secondary' : 'twk-btn',
    onClick: onClick
  }, label);
}
Object.assign(window, {
  useTweaks,
  TweaksPanel,
  TweakSection,
  TweakRow,
  TweakSlider,
  TweakToggle,
  TweakRadio,
  TweakSelect,
  TweakText,
  TweakNumber,
  TweakColor,
  TweakButton
});
})(); } catch (e) { __ds_ns.__errors.push({ path: "ui_kits/webhub/tweaks-panel.jsx", error: String((e && e.message) || e) }); }

__ds_ns.Button = __ds_scope.Button;

__ds_ns.Card = __ds_scope.Card;

__ds_ns.Badge = __ds_scope.Badge;

__ds_ns.StatusPill = __ds_scope.StatusPill;

__ds_ns.Select = __ds_scope.Select;

__ds_ns.TextInput = __ds_scope.TextInput;

__ds_ns.CapStep = __ds_scope.CapStep;

__ds_ns.ModuleCard = __ds_scope.ModuleCard;

__ds_ns.RingMeter = __ds_scope.RingMeter;

__ds_ns.PowerSlider = __ds_scope.PowerSlider;

__ds_ns.ProvenanceBadge = __ds_scope.ProvenanceBadge;

__ds_ns.SovereigntyGauge = __ds_scope.SovereigntyGauge;

})();
