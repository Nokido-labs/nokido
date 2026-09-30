/* pre-compiled (node+babel), no in-browser Babel */
(function(){
/* Référence design (handoff) — NON compilé. Source canonique : composant du DS Nokido. */
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
function _pascal(n) {
  return String(n).split("-").map(p => p.charAt(0).toUpperCase() + p.slice(1)).join("");
}
// SVG natif (React-safe) : evite que React ecrase le <svg> de lucide.createIcons.
function Ico({
  n,
  s = 18
}) {
  const html = React.useMemo(() => {
    try {
      const ch = window.lucide && window.lucide.icons && window.lucide.icons[_pascal(n)];
      if (!Array.isArray(ch)) return "";
      const inner = ch.map(x => {
        const tag = x[0],
          attrs = x[1] || {};
        const a = Object.keys(attrs).map(k => k + '="' + String(attrs[k]).replace(/"/g, "&quot;") + '"').join(" ");
        return "<" + tag + " " + a + "/>";
      }).join("");
      return '<svg xmlns="http://www.w3.org/2000/svg" width="' + s + '" height="' + s + '" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">' + inner + "</svg>";
    } catch (e) {
      return "";
    }
  }, [n, s]);
  return /*#__PURE__*/React.createElement("span", {
    style: {
      display: "inline-flex",
      alignItems: "center",
      justifyContent: "center",
      width: s,
      height: s
    },
    dangerouslySetInnerHTML: {
      __html: html
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
})();
(function(){
function _extends() { return _extends = Object.assign ? Object.assign.bind() : function (n) { for (var e = 1; e < arguments.length; e++) { var t = arguments[e]; for (var r in t) ({}).hasOwnProperty.call(t, r) && (n[r] = t[r]); } return n; }, _extends.apply(null, arguments); }
/* Référence design (handoff) — NON compilé. Source canonique : composant du DS Nokido. */
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

/* Grille fictive retiree. L'Accueil charge tes VRAIES interfaces Nokido (SERVICES
   live) via GET /api/hub/modules — chaque tuile = lien reel + statut up/down. */
function RealInterfaces() {
  const [mods, setMods] = React.useState([]);
  const [err, setErr] = React.useState("");
  React.useEffect(() => {
    fetch("/api/hub/modules", {
      credentials: "same-origin"
    }).then(r => r.ok ? r.json() : Promise.reject(new Error("HTTP " + r.status))).then(d => setMods(Array.isArray(d) ? d : [])).catch(e => setErr(String(e && e.message || e)));
  }, []);
  React.useEffect(() => {
    if (window.lucide) lucide.createIcons();
  }, [mods]);
  /* Doctrine live-only 21/08 : la provenance vient du contrat (external),
     JAMAIS du statut (l'ancien mapping up->local etait une etiquette inventee).
     L'etat 4 modes vient de l'enveloppe mesuree (state/checked/probe_ms). */
  const stateOf = m => m.state || (m.status === "up" ? "live" : m.status === "down" ? "offline" : "soon");
  const tipOf = m => {
    const st = stateOf(m);
    const ms = m.probe_ms != null ? " · " + m.probe_ms + " ms" : "";
    const src = m.checked ? "mesuré" : "présumé";
    return st + ms + " · " + src + (m.ts ? " · " + new Date(m.ts * 1000).toLocaleTimeString() : "");
  };
  return /*#__PURE__*/React.createElement("div", {
    style: {
      display: "grid",
      gridTemplateColumns: "repeat(auto-fit, minmax(248px, 1fr))",
      gap: "14px"
    }
  }, mods.map(m => /*#__PURE__*/React.createElement("a", {
    key: m.slug,
    href: m.href,
    target: m.external ? "_blank" : "_self",
    rel: "noopener",
    title: tipOf(m),
    style: {
      textDecoration: "none",
      opacity: stateOf(m) === "offline" || stateOf(m) === "error" ? 0.5 : 1
    }
  }, /*#__PURE__*/React.createElement(ModuleCard, {
    domain: m.slug,
    title: m.title,
    desc: m.desc,
    icon: /*#__PURE__*/React.createElement(Ico, {
      n: m.icon,
      s: 22
    }),
    provenance: m.external ? "remote" : "local",
    comingSoon: stateOf(m) === "soon",
    enabled: true,
    onToggle: null
  }))), mods.length === 0 && /*#__PURE__*/React.createElement("div", {
    style: {
      padding: "20px",
      color: err ? "var(--red)" : "var(--text-dim)",
      fontFamily: "var(--font-mono)",
      fontSize: "12px"
    }
  }, err ? "Erreur /api/hub/modules : " + err : "chargement des interfaces…"));
}
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
    hint: "live \xB7 clic pour ouvrir"
  }, "Tes interfaces Nokido"), /*#__PURE__*/React.createElement(RealInterfaces, null)));
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
  const [mem, setMem] = React.useState([]);
  React.useEffect(() => {
    fetch("/api/hub/persona", {
      credentials: "same-origin"
    }).then(r => r.ok ? r.json() : []).then(d => setMem(Array.isArray(d) ? d : [])).catch(() => setMem([]));
  }, []);
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
  const [log, setLog] = React.useState([]);
  React.useEffect(() => {
    fetch("/api/hub/provenance", {
      credentials: "same-origin"
    }).then(r => r.ok ? r.json() : []).then(d => setLog(Array.isArray(d) ? d : [])).catch(() => setLog([]));
  }, []);
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
})();
(function(){
const {
  ProvenanceBadge,
  Button
} = window.NokidoDesignSystem_bdc2ac;
const Ico = window.HubIco;
const TITLES = {
  accueil: ["Accueil", "ton hub personnel · local par défaut"],
  cap: ["Intention longue", "le cap → jalons → 112 étapes"],
  federation: ["Fédération", "exposer son hub d'IA · garde-fous souverains"],
  maison: ["Maison", "domotique · local-first absolu"],
  persona: ["Mémoire du persona", "visible · éditable · révocable"],
  souverainete: ["Souveraineté", "curseur puissance · journal de provenance"]
};
function App() {
  const PREF = window.NokidoPrefs;
  const [view, setView] = React.useState("accueil");
  const [local, setLocal] = React.useState(() => PREF ? PREF.get("power", 68) : 68);
  const [theme, setTheme] = React.useState(() => PREF ? PREF.get("theme", "dark") : "dark");
  const [enabled, setEnabled] = React.useState({});
  const onToggle = (d, v) => setEnabled(e => ({
    ...e,
    [d]: v
  }));
  React.useEffect(() => {
    if (PREF) PREF.set("power", local);
  }, [local]);
  const cycleTheme = () => {
    const next = PREF ? PREF.cycleTheme() : theme;
    setTheme(next);
  };
  const themeIcon = {
    dark: "moon",
    light: "sun",
    auto: "monitor"
  }[theme] || "moon";
  React.useEffect(() => {
    if (window.lucide) lucide.createIcons();
  });
  const [t, sub] = TITLES[view];
  const right = /*#__PURE__*/React.createElement(React.Fragment, null, /*#__PURE__*/React.createElement(ProvenanceBadge, {
    origin: local >= 60 ? "local" : local >= 30 ? "hybrid" : "remote",
    detail: `${local}% local`
  }), /*#__PURE__*/React.createElement("button", {
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
  }, /*#__PURE__*/React.createElement(Ico, {
    n: themeIcon,
    s: 15
  })), /*#__PURE__*/React.createElement(Button, {
    variant: "ghost",
    size: "sm",
    icon: /*#__PURE__*/React.createElement(Ico, {
      n: "settings",
      s: 14
    }),
    onClick: () => {
      window.location.href = "../composer/index.html";
    }
  }, "Composer"));
  return /*#__PURE__*/React.createElement(React.Fragment, null, /*#__PURE__*/React.createElement(window.HubSidebar, {
    active: view,
    onNav: setView,
    local: local
  }), /*#__PURE__*/React.createElement("div", {
    style: {
      flex: 1,
      display: "flex",
      flexDirection: "column",
      minWidth: 0
    }
  }, /*#__PURE__*/React.createElement(window.HubTopbar, {
    title: t,
    subtitle: sub,
    right: right
  }), /*#__PURE__*/React.createElement("main", {
    style: {
      flex: 1,
      overflowY: "auto",
      padding: "24px 28px"
    }
  }, view === "accueil" && /*#__PURE__*/React.createElement(window.ViewAccueil, {
    enabled: enabled,
    onToggle: onToggle
  }), view === "cap" && /*#__PURE__*/React.createElement(window.ViewCap, null), view === "federation" && /*#__PURE__*/React.createElement(window.ViewFederation, null), view === "maison" && /*#__PURE__*/React.createElement(window.ViewMaison, null), view === "persona" && /*#__PURE__*/React.createElement(window.ViewPersona, null), view === "souverainete" && /*#__PURE__*/React.createElement(window.ViewSouverainete, {
    local: local,
    setLocal: setLocal
  }))));
}
ReactDOM.createRoot(document.getElementById("root")).render(/*#__PURE__*/React.createElement(App, null));
setTimeout(() => window.lucide && lucide.createIcons(), 80);
})();
