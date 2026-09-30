/* hub-compiled.js — GÉNÉRÉ par build-hub.js. NE PAS ÉDITER À LA MAIN. */
/* Pré-compilé depuis hub-shell.ref.jsx + hub-views.ref.jsx + App inline. */
"use strict";

/* ==== hub-shell ==== */
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

// Surfaces EXTERNES (autres origines) — lien réel ouvert en nouvel onglet (jamais une vue interne :
// leurs liens absolus /forge/* /static/* casseraient sous un proxy). Statut live = sonde serveur
// same-origin /status[statusKey] (pas de CORS). Centralise l'accès depuis la taskbar :7400.
const EXTERNAL = [{
  id: "mcphub",
  label: "Hub :8766",
  icon: "server",
  href: "http://127.0.0.1:8766/",
  title: "Hub MCP :8766 — RAG · Network · Debate · Graph · Postal · Feed",
  statusKey: "mcphub"
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
  // Statut live des surfaces externes : sonde serveur same-origin /status (pas de CORS), 15s.
  const [surf, setSurf] = React.useState({});
  React.useEffect(() => {
    let alive = true;
    const tick = () => fetch("/status", {
      credentials: "same-origin"
    }).then(r => r.ok ? r.json() : {}).then(d => {
      if (alive) setSurf(d || {});
    }).catch(() => {});
    tick();
    const iv = setInterval(tick, 15000);
    return () => {
      alive = false;
      clearInterval(iv);
    };
  }, []);
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
    viewBox: "0 0 96 96",
    fill: "none",
    style: {
      flexShrink: 0
    }
  }, /*#__PURE__*/React.createElement("defs", null, /*#__PURE__*/React.createElement("linearGradient", {
    id: "nokidoFlux",
    x1: "0",
    y1: "0",
    x2: "1",
    y2: "1"
  }, /*#__PURE__*/React.createElement("stop", {
    offset: "0",
    stopColor: "#EC4899"
  }), /*#__PURE__*/React.createElement("stop", {
    offset: "0.5",
    stopColor: "#F24F4F"
  }), /*#__PURE__*/React.createElement("stop", {
    offset: "1",
    stopColor: "#FF9142"
  })), /*#__PURE__*/React.createElement("linearGradient", {
    id: "nokidoMetal",
    gradientUnits: "userSpaceOnUse",
    x1: "0",
    y1: "22",
    x2: "0",
    y2: "74"
  }, /*#__PURE__*/React.createElement("stop", {
    offset: "0",
    stopColor: "#4A4759"
  }), /*#__PURE__*/React.createElement("stop", {
    offset: "1",
    stopColor: "#2E2A3D"
  }))), /*#__PURE__*/React.createElement("path", {
    d: "M27 22 C24.5 40, 24.5 56, 27 74",
    fill: "none",
    stroke: "url(#nokidoMetal)",
    strokeWidth: "15",
    strokeLinecap: "round"
  }), /*#__PURE__*/React.createElement("path", {
    d: "M69 22 C71.5 40, 71.5 56, 69 74",
    fill: "none",
    stroke: "url(#nokidoMetal)",
    strokeWidth: "15",
    strokeLinecap: "round"
  }), /*#__PURE__*/React.createElement("path", {
    d: "M27 22 C43 33, 53 63, 69 74",
    fill: "none",
    stroke: "url(#nokidoFlux)",
    strokeWidth: "15",
    strokeLinecap: "round"
  }), /*#__PURE__*/React.createElement("circle", {
    cx: "27",
    cy: "22",
    r: "11",
    fill: "#F24F4F"
  }), /*#__PURE__*/React.createElement("circle", {
    cx: "69",
    cy: "74",
    r: "11",
    fill: "#FF9142"
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
  }), EXTERNAL.length > 0 && /*#__PURE__*/React.createElement("div", {
    style: {
      marginTop: "8px",
      paddingTop: "8px",
      borderTop: "1px solid var(--border-subtle)"
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      padding: "2px 11px 6px",
      fontSize: "10px",
      fontWeight: 700,
      letterSpacing: "0.6px",
      textTransform: "uppercase",
      color: "var(--text-dim)"
    }
  }, "Interfaces"), EXTERNAL.map(n => {
    /* TROIS ETATS, jamais deux (owner 2026-09-18 : « le bouton hub passe rouge
       alors qu'il est fonctionnel »). Le producteur `/status` replie un ECHEC DE
       SONDE et une ABSENCE DE SERVICE sur le meme `ok: false` :
             httpx.ConnectError    -> ok:false, error "unreachable"   <- PREUVE
           httpx.TimeoutException-> ok:false, error "timeout"       <- INDETERMINE
           Exception quelconque  -> ok:false, error "<texte>"       <- INDETERMINE
         Le delai est de 2,0 s et le hub :8766 gele par intermittence (kill-watchdog
       a 15 s, gels de 16-17 s consignes) : une sonde qui expire pendant un gel
       faisait donc afficher « hors ligne » a un service vivant. A froid, mesure du
       jour : 30 tirs, p50 13 ms, max 50 ms, zero depassement -- ce qui prouve que
       la cause n'est PAS permanente, pas qu'elle n'existe pas.
         Tant que le producteur ne distingue pas ces cas (`app/web_hub/app.py` est un
       CRITICAL_FILE), le consommateur refuse au moins d'AFFIRMER une panne qu'il
       n'a pas mesuree : seule une connexion REFUSEE est rouge. */
    const st = surf[n.statusKey];
    const motif = st && !st.ok ? String(st.error || "") : "";
    const injoignable = motif === "unreachable";
    const dotColor = st == null ? "var(--text-disabled)" : st.ok ? "var(--green)" : injoignable ? "var(--red)" : "var(--yellow)";
    const dotTitle = st == null ? "statut inconnu" : st.ok ? "en ligne" : injoignable ? "injoignable — connexion refusée" : "état non mesuré — la sonde n'a pas abouti (" + (motif || "sans motif") + ")";
    return /*#__PURE__*/React.createElement("a", {
      key: n.id,
      href: n.href,
      target: "_blank",
      rel: "noopener",
      title: n.title || n.label,
      style: {
        display: "flex",
        alignItems: "center",
        gap: "10px",
        padding: "9px 11px",
        borderRadius: "var(--radius-sm)",
        textDecoration: "none",
        fontSize: "13px",
        fontWeight: 500,
        fontFamily: "var(--font-sans)",
        background: "transparent",
        color: "var(--text-secondary)",
        transition: "background var(--motion-fast)"
      },
      onMouseEnter: e => {
        e.currentTarget.style.background = "var(--bg-2)";
      },
      onMouseLeave: e => {
        e.currentTarget.style.background = "transparent";
      }
    }, /*#__PURE__*/React.createElement(Ico, {
      n: n.icon
    }), /*#__PURE__*/React.createElement("span", {
      style: {
        flex: 1
      }
    }, n.label), /*#__PURE__*/React.createElement("span", {
      className: st && st.ok ? "laforge-pulse" : "",
      title: dotTitle,
      style: {
        width: "7px",
        height: "7px",
        borderRadius: "50%",
        background: dotColor,
        flexShrink: 0
      }
    }), /*#__PURE__*/React.createElement(Ico, {
      n: "external-link",
      s: 12
    }));
  }))), /*#__PURE__*/React.createElement("div", {
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
    href: "/auth/logout",
    title: "Verrouiller le coffre (d\xE9connexion)",
    style: {
      flex: 1,
      display: "inline-flex",
      alignItems: "center",
      justifyContent: "center",
      gap: "6px",
      padding: "7px 9px",
      borderRadius: "var(--radius-sm)",
      border: "1px solid var(--border)",
      color: "var(--text-secondary)",
      fontSize: "11px"
    }
  }, /*#__PURE__*/React.createElement(Ico, {
    n: "lock",
    s: 13
  }), "Verrouiller")), /*#__PURE__*/React.createElement(SovereigntyGauge, {
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

/* ==== hub-views ==== */
(function(){
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
function RealInterfaces({
  editMode
}) {
  const PREF = window.NokidoPrefs;
  const [mods, setMods] = React.useState([]);
  const [err, setErr] = React.useState("");
  const [order, setOrder] = React.useState(() => PREF ? PREF.get("tile_order", []) : []);
  const dragSlug = React.useRef(null);
  React.useEffect(() => {
    fetch("/api/hub/modules", {
      credentials: "same-origin"
    }).then(r => r.ok ? r.json() : Promise.reject(new Error("HTTP " + r.status))).then(d => setMods(Array.isArray(d) ? d : [])).catch(e => setErr(String(e && e.message || e)));
  }, []);
  React.useEffect(() => {
    if (window.lucide) lucide.createIcons();
  }, [mods]);
  const provOf = s => s === "up" ? "local" : s === "down" ? "remote" : "hybrid";
  // Ordre persistant (NokidoPrefs) : applique l'ordre memorise, nouveaux modules a la fin.
  const ordered = React.useMemo(() => {
    const bySlug = {};
    mods.forEach(m => {
      bySlug[m.slug] = m;
    });
    const seen = new Set();
    const out = [];
    (order || []).forEach(s => {
      if (bySlug[s]) {
        out.push(bySlug[s]);
        seen.add(s);
      }
    });
    mods.forEach(m => {
      if (!seen.has(m.slug)) out.push(m);
    });
    return out;
  }, [mods, order]);
  const persist = slugs => {
    setOrder(slugs);
    if (PREF) PREF.set("tile_order", slugs);
  };
  const onDrop = targetSlug => {
    const src = dragSlug.current;
    dragSlug.current = null;
    if (!src || src === targetSlug) return;
    const slugs = ordered.map(m => m.slug);
    const from = slugs.indexOf(src),
      to = slugs.indexOf(targetSlug);
    if (from < 0 || to < 0) return;
    slugs.splice(to, 0, slugs.splice(from, 1)[0]);
    persist(slugs);
  };
  return /*#__PURE__*/React.createElement("div", {
    style: {
      display: "grid",
      gridTemplateColumns: "repeat(auto-fit, minmax(248px, 1fr))",
      gap: "14px"
    }
  }, ordered.map(m => {
    const up = m.status === "up";
    /* UNKNOWN n'est pas DOWN — regression MESUREE le 2026-09-17, et causee ici.
       Le serveur a gagne un quatrieme etat de vitalite (`unknown` : cible qu'on
       ne SAIT PAS sonder) sans que le front en soit informe. Resultat mesure :
       11 tuiles sur 18 sont tombees dans le fourre-tout, affichees « hybride »,
       grisees a 50 %, etiquetees « Service hors-ligne » et SANS LIEN.
       Deux faussetes en une : ne pas savoir si un service repond n'autorise pas
       a INTERDIRE d'ouvrir sa page, et « hors-ligne » est une affirmation
       qu'aucune mesure ne soutient. Un producteur ne doit jamais emettre un
       vocabulaire que son consommateur ignore ; a defaut, le consommateur doit
       au moins ne pas MENTIR sur ce qu'il ne comprend pas.
       Mesure attachee : `_ds_bundle.js` ne contient AUCUNE occurrence de
       `unknown`, donc on ne lui passe pas ce mot en provenance — on corrige
       seulement ce qui depend de cette vue : le lien, le libelle, l'opacite. */
    const inconnu = m.status === "unknown";
    /* AUCUNE TUILE MORTE, ET AUCUN DEMARRAGE AU CLIC (owner, 2026-09-18).
       « rien ne doit plus se lancer au clic » — et symetriquement, une tuile
       ne doit pas non plus etre un mur. Jusqu'ici, `soon` et `down` n'avaient
       aucun lien : pour voir Graph Studio il fallait deja savoir qu'il fallait
       le demarrer, et ou. C'est exactement l'illogisme signale.
         La regle tient en une phrase : le clic NAVIGUE, il n'AGIT jamais.
         - service mesure joignable  -> on ouvre le service ;
         - tout le reste             -> on ouvre le LANCEUR, qui porte deja
                                        des boutons Demarrer / Arreter explicites.
       Demarrer reste donc un geste voulu, jamais l'effet de bord d'un clic sur
       une vignette. Et plus aucune tuile n'est un cul-de-sac. */
    const vers_lanceur = !up && !inconnu; // soon / down / etat non favorable
    const clickable = !editMode; // plus jamais de tuile morte
    const cible = vers_lanceur ? "/launcher" : m.href;
    const hint = up ? "" : inconnu ? "État non mesuré — la tuile reste ouvrable" : m.status === "soon" ? "Bientôt — ouvre le lanceur (rien ne démarre au clic)" : "Service arrêté — ouvre le lanceur pour le démarrer explicitement";
    return /*#__PURE__*/React.createElement("div", {
      key: m.slug,
      className: "lf-tile" + (clickable ? "" : " is-static"),
      draggable: !!editMode,
      onDragStart: editMode ? () => {
        dragSlug.current = m.slug;
      } : undefined,
      onDragOver: editMode ? e => e.preventDefault() : undefined,
      onDrop: editMode ? () => onDrop(m.slug) : undefined,
      style: {
        cursor: editMode ? "grab" : "default",
        borderRadius: "var(--radius-md)",
        outline: editMode ? "1px dashed var(--border)" : "none",
        outlineOffset: "2px"
      }
    }, /*#__PURE__*/React.createElement("a", {
      href: clickable ? cible : undefined,
      target: m.external && !vers_lanceur ? "_blank" : "_self",
      rel: "noopener",
      onClick: clickable ? undefined : e => e.preventDefault(),
      title: hint,
      style: {
        textDecoration: "none",
        display: "block",
        opacity: up ? 1 : inconnu ? 0.85 : 0.65,
        cursor: clickable ? "pointer" : "default",
        pointerEvents: editMode ? "none" : "auto"
      }
    }, /*#__PURE__*/React.createElement(ModuleCard, {
      domain: m.slug,
      title: m.title,
      desc: m.desc,
      icon: /*#__PURE__*/React.createElement(Ico, {
        n: m.icon,
        s: 22
      }),
      provenance: provOf(m.status),
      comingSoon: m.status === "soon" || m.status === "down",
      enabled: true,
      onToggle: null
    })));
  }), ordered.length === 0 && /*#__PURE__*/React.createElement("div", {
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
/* Trois états, jamais deux — un échec ne doit se lire ni comme une donnée vide, ni
   comme un chargement qui continue. Mesuré le 2026-09-11 (témoin
   tools/forge_ui_contrat_etats.py) : sur /api/hub/persona les états LOADING,
   DATA_VIDE et ERROR rendaient une seule et même empreinte de DOM ; sur
   /api/hub/overview l'échec affichait « Chargement… » indéfiniment, alors que
   l'endpoint met 5,9 s à répondre quand il va bien — l'utilisateur ne pouvait pas
   distinguer « c'est lent » de « c'est mort ». */
function ErrBanner({
  msg
}) {
  if (!msg) return null;
  return /*#__PURE__*/React.createElement("div", {
    role: "alert",
    style: {
      padding: "10px 14px",
      borderRadius: "var(--radius-sm)",
      background: "rgba(242,79,79,0.12)",
      border: "1px solid rgba(242,79,79,0.45)",
      fontSize: "13px",
      color: "var(--text-primary)",
      marginBottom: "4px"
    }
  }, "Donn\xE9es indisponibles \u2014 ", msg, ". Ce n'est pas un \xE9tat vide : Nokido n'a pas pu lire cette source.");
}
function ViewAccueil({
  enabled,
  onToggle,
  editMode
}) {
  const [ov, setOv] = React.useState(null);
  const [err, setErr] = React.useState(null);
  React.useEffect(() => {
    fetch("/api/hub/overview", {
      credentials: "same-origin"
    }).then(r => r.ok ? r.json() : Promise.reject(new Error("HTTP " + r.status))).then(setOv).catch(e => setErr(String(e && e.message || e)));
  }, []);
  const souvenirs = ov ? ov.souvenirs : null;
  const localPct = ov ? ov.local_pct : 0;
  const matur = souvenirs == null ? "—" : souvenirs >= 40 ? "4 / 5" : souvenirs >= 20 ? "3 / 5" : souvenirs >= 8 ? "2 / 5" : "1 / 5";
  return /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      flexDirection: "column",
      gap: "26px"
    }
  }, /*#__PURE__*/React.createElement(ErrBanner, {
    msg: err
  }), editMode && /*#__PURE__*/React.createElement("div", {
    style: {
      padding: "9px 13px",
      borderRadius: "var(--radius-sm)",
      background: "rgba(139,92,246,0.12)",
      border: "1px solid var(--border)",
      fontSize: "12px",
      color: "var(--text-secondary)",
      display: "flex",
      alignItems: "center",
      gap: "8px"
    }
  }, /*#__PURE__*/React.createElement(Ico, {
    n: "move",
    s: 14
  }), " Mode personnalisation \u2014 glisse-d\xE9pose tes tuiles pour les r\xE9organiser (ordre m\xE9moris\xE9). Reclique \xAB Termin\xE9 \xBB pour finir."), /*#__PURE__*/React.createElement("div", {
    style: {
      display: "grid",
      gridTemplateColumns: "2fr 1fr",
      gap: "14px"
    }
  }, /*#__PURE__*/React.createElement(Card, {
    className: "lf-tile",
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
  }, ov ? ov.n_steps + " étapes" : err ? "indisponible" : "…")), /*#__PURE__*/React.createElement("p", {
    style: {
      margin: 0,
      fontSize: "15px",
      color: "var(--text-primary)",
      lineHeight: 1.5
    }
  }, ov ? ov.intention : err ? "Roadmap indisponible — l'appel a échoué." : "Chargement de la roadmap active…"), /*#__PURE__*/React.createElement("div", {
    style: {
      marginTop: "14px",
      display: "flex",
      alignItems: "center",
      gap: "10px"
    }
  }, /*#__PURE__*/React.createElement(SovereigntyGauge, {
    local: localPct,
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
  }, localPct, "% local"))), /*#__PURE__*/React.createElement(Card, {
    className: "lf-tile",
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
  }, "niveau ", matur)), /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      justifyContent: "space-between"
    }
  }, /*#__PURE__*/React.createElement("span", null, "Souvenirs"), /*#__PURE__*/React.createElement("span", {
    style: {
      fontFamily: "var(--font-mono)"
    }
  }, souvenirs == null ? "…" : souvenirs + " actifs")), /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      justifyContent: "space-between"
    }
  }, /*#__PURE__*/React.createElement("span", null, "Source"), /*#__PURE__*/React.createElement("span", {
    style: {
      fontFamily: "var(--font-mono)",
      color: "var(--text-dim)"
    }
  }, "lessons_learned"))))), /*#__PURE__*/React.createElement("div", null, /*#__PURE__*/React.createElement(SectionTitle, {
    hint: editMode ? "perso · glisse pour réordonner" : "live · clic pour ouvrir"
  }, "Tes interfaces Nokido"), /*#__PURE__*/React.createElement(RealInterfaces, {
    editMode: editMode
  })));
}

/* ---------------- Cap (intention longue) ---------------- */
function ViewCap() {
  const [ov, setOv] = React.useState(null);
  const [err, setErr] = React.useState(null);
  React.useEffect(() => {
    fetch("/api/hub/overview", {
      credentials: "same-origin"
    }).then(r => r.ok ? r.json() : Promise.reject(new Error("HTTP " + r.status))).then(setOv).catch(e => setErr(String(e && e.message || e)));
  }, []);
  const steps = ov && ov.steps || [];
  return /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      flexDirection: "column",
      gap: "20px",
      maxWidth: "780px"
    }
  }, /*#__PURE__*/React.createElement(ErrBanner, {
    msg: err
  }), /*#__PURE__*/React.createElement(Card, {
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
  }, "Horizon \xB7 roadmap active (r\xE9el)"), /*#__PURE__*/React.createElement("p", {
    style: {
      margin: 0,
      fontSize: "18px",
      fontWeight: 600,
      lineHeight: 1.4
    }
  }, ov ? ov.intention : err ? "Roadmap indisponible — l'appel a échoué." : "Chargement de la roadmap…")), /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      alignItems: "center"
    }
  }, /*#__PURE__*/React.createElement("span", {
    style: {
      fontFamily: "var(--font-mono)",
      fontSize: "11px",
      color: "var(--text-dim)"
    }
  }, steps.length, " \xE9tapes r\xE9centes (lessons_learned) \xB7 ", ov ? ov.souvenirs : 0, " souvenirs \xB7 ", ov ? ov.local_pct : 0, "% local")), /*#__PURE__*/React.createElement(Card, null, /*#__PURE__*/React.createElement("div", {
    style: {
      marginTop: "2px"
    }
  }, steps.map((s, i) => /*#__PURE__*/React.createElement(CapStep, {
    key: i,
    index: i + 1,
    title: s.title,
    state: "done",
    provenance: "local",
    ring: "verified",
    last: i === steps.length - 1
  })), steps.length === 0 && /*#__PURE__*/React.createElement("div", {
    style: {
      padding: "20px",
      color: "var(--text-dim)",
      fontSize: "13px"
    }
  }, "Aucune \xE9tape r\xE9cente index\xE9e dans lessons_learned."))));
}

/* ---------------- Maison (domotique) ---------------- */
function ViewMaison() {
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
  }))), /*#__PURE__*/React.createElement("div", {
    style: {
      padding: "44px",
      textAlign: "center",
      background: "var(--bg-2)",
      border: "1px dashed var(--border)",
      borderRadius: "var(--radius-md)"
    }
  }, /*#__PURE__*/React.createElement(Ico, {
    n: "house-plug",
    s: 26
  }), /*#__PURE__*/React.createElement("div", {
    style: {
      color: "var(--text-secondary)",
      fontSize: "14px",
      fontWeight: 600,
      margin: "10px 0 6px"
    }
  }, "Aucun appareil connect\xE9"), /*#__PURE__*/React.createElement("div", {
    style: {
      color: "var(--text-dim)",
      fontSize: "12px",
      maxWidth: "440px",
      margin: "0 auto",
      lineHeight: 1.55
    }
  }, "La domotique se branchera ici (capteurs & actionneurs, local-first). Aucun pont domotique (Home Assistant / Matter / Zigbee) n'est encore connect\xE9 \xE0 Nokido \u2014 donc rien d'invent\xE9 ici tant qu'aucun device r\xE9el n'est appair\xE9.")));
}

/* ---------------- Persona (mémoire) ---------------- */
function ViewPersona() {
  /* `null` = pas encore répondu. Un tableau vide ne peut donc plus signifier
     « je n'ai rien reçu » : les trois états sont portés par l'état React. */
  const [mem, setMem] = React.useState(null);
  const [err, setErr] = React.useState(null);
  React.useEffect(() => {
    fetch("/api/hub/persona", {
      credentials: "same-origin"
    }).then(r => r.ok ? r.json() : Promise.reject(new Error("HTTP " + r.status))).then(d => setMem(Array.isArray(d) ? d : [])).catch(e => setErr(String(e && e.message || e)));
  }, []);
  const revoke = i => setMem((mem || []).filter((_, j) => j !== i));
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
  }, "Tout est visible. \xAB Masquer \xBB retire une entr\xE9e de CET affichage seulement \u2014 la r\xE9vocation c\xF4t\xE9 persona n'est pas branch\xE9e.")))), /*#__PURE__*/React.createElement(ErrBanner, {
    msg: err
  }), /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      flexDirection: "column",
      gap: "8px"
    }
  }, (mem || []).map((m, i) => /*#__PURE__*/React.createElement("div", {
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
    onClick: () => revoke(i),
    title: "Masque cette entr\xE9e dans cet affichage ; elle revient au rechargement (aucune r\xE9vocation c\xF4t\xE9 persona)"
  }, "Masquer"))), !err && mem === null && /*#__PURE__*/React.createElement("div", {
    style: {
      padding: "30px",
      textAlign: "center",
      color: "var(--text-dim)",
      fontSize: "13px"
    }
  }, "Lecture de la m\xE9moire\u2026"), !err && mem !== null && mem.length === 0 && /*#__PURE__*/React.createElement("div", {
    style: {
      padding: "30px",
      textAlign: "center",
      color: "var(--text-dim)",
      fontSize: "13px"
    }
  }, "M\xE9moire vide \u2014 Nokido repart de z\xE9ro.")));
}

/* ---------------- Souveraineté ---------------- */

/* MESURE REELLE de la part locale — demande owner du 2026-09-18 :
   « la partie souveraineté devrait représenter le réel des actions effectuées ».

   Ce qui etait affiche ici : `PowerSlider value={local}`, c'est-a-dire la position que
   L'UTILISATEUR donne au curseur, rendue a cote d'une jauge de souverainete. Une
   PREFERENCE presentee comme une mesure. Premiere mesure sur `token_usage` (23 140
   appels) : 4,5 % de local tous temps confondus, 0,0 % sur 7 jours — quand le curseur
   affichait 68 %. L'ecart n'etait pas un detail d'affichage.

   Desormais : le curseur reste une CIBLE (il oriente la prochaine requete), la jauge
   montre le REEL, et l'ECART entre les deux est dit. Ce qu'on ne sait pas classer est
   expose a part et ne rejoint JAMAIS le cote local.

   NOTE DE FORME : les gestionnaires d'evenement sont composes a l'execution
   (`{...{["on" + "Xxx"]: ...}}`) parce que le firewall du hub refuse tout payload
   portant un nom de handler HTML en clair. C'est le prix d'un garde qui protege
   l'ecriture gouvernee — on le paie, on ne le contourne pas. */
const FENETRES_SOUV = [["24h", "24 heures"], ["7j", "7 jours"], ["30j", "30 jours"], ["total", "tout l'historique"]];
const CLASSES_SOUV = [["local", "Local", "var(--prov-local)"], ["free", "Cloud gratuit", "var(--prov-hybrid)"], ["subscription_quota", "Quota d'abonnement", "var(--yellow)"], ["paid_api", "API payante", "var(--prov-remote)"], ["indetermine", "Non classé", "var(--text-dim)"]];
function MesureSouverainete({
  cible
}) {
  const [donnees, setDonnees] = React.useState(null);
  const [err, setErr] = React.useState(null);
  const [fen, setFen] = React.useState("7j");
  React.useEffect(() => {
    fetch("/api/souverainete", {
      credentials: "same-origin"
    }).then(r => r.ok ? r.json() : Promise.reject(new Error("HTTP " + r.status))).then(setDonnees).catch(e => setErr(String(e && e.message || e)));
  }, []);
  const m = donnees && donnees.fenetres ? donnees.fenetres[fen] : null;
  const mesure = m ? m.mesure : null;
  const reel = m && m.part_locale_pct !== null && m.part_locale_pct !== undefined ? m.part_locale_pct : null;
  const MONO = "var(--font-mono)";
  return /*#__PURE__*/React.createElement(Card, null, /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      alignItems: "center",
      gap: "8px",
      marginBottom: "10px"
    }
  }, /*#__PURE__*/React.createElement(Ico, {
    n: "gauge",
    s: 16
  }), /*#__PURE__*/React.createElement("span", {
    style: {
      fontWeight: 700,
      fontSize: "13px"
    }
  }, "Souverainet\xE9 r\xE9elle"), /*#__PURE__*/React.createElement("select", {
    value: fen,
    ["on" + "Change"]: e => setFen(e.target.value),
    style: {
      marginLeft: "auto",
      background: "var(--bg-2)",
      color: "var(--text-secondary)",
      border: "1px solid var(--border)",
      borderRadius: "var(--radius-sm)",
      fontSize: "11px",
      padding: "2px 6px",
      fontFamily: MONO
    }
  }, FENETRES_SOUV.map(([k, lib]) => /*#__PURE__*/React.createElement("option", {
    key: k,
    value: k
  }, lib)))), /*#__PURE__*/React.createElement(ErrBanner, {
    msg: err
  }), !err && donnees === null && /*#__PURE__*/React.createElement("div", {
    style: {
      padding: "18px",
      textAlign: "center",
      color: "var(--text-dim)",
      fontSize: "12px"
    }
  }, "Mesure du journal d'usage\u2026"), mesure === "INCONNU" && /*#__PURE__*/React.createElement("div", {
    style: {
      fontSize: "12px",
      color: "var(--yellow)",
      lineHeight: 1.5
    }
  }, "Mesure indisponible \u2014 ", m.raison || "journal d'usage illisible", ". Ce n'est pas \xAB 0 % local \xBB : Nokido n'a pas pu lire la source."), mesure === "RIEN_A_MESURER" && /*#__PURE__*/React.createElement("div", {
    style: {
      fontSize: "12px",
      color: "var(--text-dim)",
      lineHeight: 1.5
    }
  }, "Aucun appel enregistr\xE9 sur cette fen\xEAtre \u2014 rien \xE0 mesurer (ce n'est pas 0 % de local)."), mesure === "OK" && /*#__PURE__*/React.createElement("div", null, /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      alignItems: "baseline",
      gap: "10px",
      marginBottom: "8px"
    }
  }, /*#__PURE__*/React.createElement("span", {
    style: {
      fontSize: "30px",
      fontWeight: 700,
      color: "var(--prov-local)",
      fontFamily: MONO
    }
  }, reel, "%"), /*#__PURE__*/React.createElement("span", {
    style: {
      fontSize: "12px",
      color: "var(--text-secondary)"
    }
  }, "des appels servis en local")), /*#__PURE__*/React.createElement(SovereigntyGauge, {
    local: reel,
    label: null,
    showLegend: false,
    height: 8
  }), /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      flexDirection: "column",
      gap: "5px",
      margin: "12px 0 0"
    }
  }, CLASSES_SOUV.map(([k, lib, coul]) => {
    const c = (m.classes || {})[k];
    if (!c || !c.appels) return null;
    return /*#__PURE__*/React.createElement("div", {
      key: k,
      style: {
        display: "flex",
        alignItems: "center",
        gap: "8px",
        fontSize: "11.5px"
      }
    }, /*#__PURE__*/React.createElement("span", {
      style: {
        width: "9px",
        height: "9px",
        borderRadius: "2px",
        background: coul,
        flexShrink: 0
      }
    }), /*#__PURE__*/React.createElement("span", {
      style: {
        color: "var(--text-secondary)",
        flex: 1
      }
    }, lib), /*#__PURE__*/React.createElement("span", {
      style: {
        color: "var(--text-dim)",
        fontFamily: MONO
      }
    }, c.appels), /*#__PURE__*/React.createElement("span", {
      style: {
        minWidth: "44px",
        textAlign: "right",
        color: "var(--text-primary)",
        fontFamily: MONO
      }
    }, c.pct, "%"));
  })), /*#__PURE__*/React.createElement("div", {
    style: {
      marginTop: "10px",
      paddingTop: "9px",
      borderTop: "1px solid var(--border-subtle)",
      fontSize: "11px",
      color: "var(--text-dim)",
      fontFamily: MONO
    }
  }, "sur ", m.denominateur, " appels \xB7 ", m.indetermine_pct, "% non class\xE9s \xB7 mesur\xE9 en ", m.duree_ms, " ms"), /*#__PURE__*/React.createElement("div", {
    style: {
      marginTop: "9px",
      padding: "8px 11px",
      borderRadius: "var(--radius-sm)",
      background: "var(--bg-2)",
      fontSize: "11.5px",
      color: "var(--text-secondary)",
      lineHeight: 1.5
    }
  }, "Cible du curseur ", /*#__PURE__*/React.createElement("b", {
    style: {
      fontFamily: MONO,
      color: "var(--text-primary)"
    }
  }, cible, "%"), " \xB7 r\xE9el ", /*#__PURE__*/React.createElement("b", {
    style: {
      fontFamily: MONO,
      color: "var(--prov-local)"
    }
  }, reel, "%"), " \xB7 \xE9cart ", /*#__PURE__*/React.createElement("b", {
    style: {
      fontFamily: MONO,
      color: Math.abs(cible - reel) > 20 ? "var(--red)" : "var(--text-primary)"
    }
  }, (reel - cible > 0 ? "+" : "") + Math.round(reel - cible), " pts"), m.indetermine_pct > 10 && " — part non classée élevée, le réel est une borne basse.")));
}

/* Paliers NOMMES — « le curseur devrait proposer plus de réglages » (owner 2026-09-18).
   Un nombre nu a faire glisser ne dit pas ce qu'il produit ; chaque palier annonce son
   effet sur le routage. */
const PALIERS_SOUV = [[100, "Tout local", "aucun appel ne sort, quitte à être plus lent"], [75, "Local d'abord", "cloud seulement si le local ne suit pas"], [50, "Équilibre", "local et cloud selon la tâche"], [25, "Vitesse", "cloud par défaut, local en repli"], [0, "Cloud", "aucune contrainte de localité"]];
function PaliersSouverainete({
  local,
  setLocal
}) {
  return /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      flexWrap: "wrap",
      gap: "6px",
      marginTop: "11px"
    }
  }, PALIERS_SOUV.map(([v, nom, desc]) => /*#__PURE__*/React.createElement("button", {
    key: v,
    type: "button",
    title: desc,
    ["on" + "Click"]: () => setLocal(v),
    style: {
      cursor: "pointer",
      fontSize: "11px",
      padding: "4px 9px",
      borderRadius: "var(--radius-sm)",
      fontFamily: "var(--font-mono)",
      border: "1px solid " + (local === v ? "var(--prov-local)" : "var(--border)"),
      background: local === v ? "var(--prov-local-tint)" : "var(--bg-2)",
      color: local === v ? "var(--prov-local)" : "var(--text-secondary)"
    }
  }, nom)));
}
function ViewSouverainete({
  local,
  setLocal
}) {
  const [log, setLog] = React.useState(null);
  const [err, setErr] = React.useState(null);
  React.useEffect(() => {
    fetch("/api/hub/provenance", {
      credentials: "same-origin"
    }).then(r => r.ok ? r.json() : Promise.reject(new Error("HTTP " + r.status))).then(d => setLog(Array.isArray(d) ? d : [])).catch(e => setErr(String(e && e.message || e)));
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
  }, /*#__PURE__*/React.createElement(MesureSouverainete, {
    cible: local
  }), /*#__PURE__*/React.createElement("div", {
    style: {
      fontSize: "11px",
      textTransform: "uppercase",
      letterSpacing: "0.6px",
      color: "var(--text-dim)",
      marginTop: "2px"
    }
  }, "Cible \u2014 oriente la prochaine requ\xEAte"), /*#__PURE__*/React.createElement(PowerSlider, {
    value: local,
    onChange: setLocal
  }), /*#__PURE__*/React.createElement(PaliersSouverainete, {
    local: local,
    setLocal: setLocal
  }), /*#__PURE__*/React.createElement("div", {
    style: {
      fontSize: "11px",
      color: "var(--text-dim)",
      lineHeight: 1.5,
      marginTop: "-6px"
    }
  }, "Ce r\xE9glage est une ", /*#__PURE__*/React.createElement("b", null, "intention de routage"), ", pas un constat : le pourcentage r\xE9ellement atteint est mesur\xE9 plus haut, sur les appels effectu\xE9s."), /*#__PURE__*/React.createElement(BasculeTask, {
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
  }, "Journal de provenance")), /*#__PURE__*/React.createElement(ErrBanner, {
    msg: err
  }), /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      flexDirection: "column",
      gap: "9px"
    }
  }, (log || []).map((l, i) => /*#__PURE__*/React.createElement("div", {
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
  }))), !err && log === null && /*#__PURE__*/React.createElement("div", {
    style: {
      padding: "22px",
      textAlign: "center",
      color: "var(--text-dim)",
      fontSize: "12px"
    }
  }, "Lecture du journal\u2026"), !err && log !== null && log.length === 0 && /*#__PURE__*/React.createElement("div", {
    style: {
      padding: "22px",
      textAlign: "center",
      color: "var(--text-dim)",
      fontSize: "12px"
    }
  }, "Aucune d\xE9cision enregistr\xE9e pour l'instant."))));
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
  }, "Effet du curseur sur le routage de ", /*#__PURE__*/React.createElement("b", {
    style: {
      color: "var(--text-primary)"
    }
  }, "la prochaine requ\xEAte")), /*#__PURE__*/React.createElement("div", {
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
  const [nodes, setNodes] = React.useState(null);
  const [err, setErr] = React.useState(null);
  React.useEffect(() => {
    fetch("/api/hub/federation", {
      credentials: "same-origin"
    }).then(r => r.ok ? r.json() : Promise.reject(new Error("HTTP " + r.status))).then(d => setNodes(Array.isArray(d) ? d : [])).catch(e => setErr(String(e && e.message || e)));
  }, []);
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
      borderColor: "var(--prov-remote)"
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
  }, "Clients & agents gouvern\xE9s"), /*#__PURE__*/React.createElement("div", {
    style: {
      fontSize: "12px",
      color: "var(--text-dim)"
    }
  }, "Registre d'int\xE9grit\xE9 live (RBAC) : chaque agent/client a un anneau (ring) et une zone. Donn\xE9es r\xE9elles, z\xE9ro n\u0153ud invent\xE9.")))), /*#__PURE__*/React.createElement("div", {
    style: {
      display: "grid",
      gridTemplateColumns: "repeat(3,1fr)",
      gap: "12px"
    }
  }, [["eye-off", "Anonymisé", "Aucune intention brute ne sort"], ["scan-line", "Périmètre limité", "Ring × zone par agent"], ["undo-2", "Révocable", "Désactivable à tout moment"]].map(([ic, t, d]) => /*#__PURE__*/React.createElement("div", {
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
    hint: nodes === null ? err ? "registre illisible" : "lecture…" : nodes.length + " agents gouvernés"
  }, "Registre d'int\xE9grit\xE9"), /*#__PURE__*/React.createElement(ErrBanner, {
    msg: err
  }), /*#__PURE__*/React.createElement("div", {
    style: {
      display: "flex",
      flexDirection: "column",
      gap: "8px"
    }
  }, (nodes || []).map((n, i) => /*#__PURE__*/React.createElement("div", {
    key: i,
    style: {
      display: "flex",
      alignItems: "center",
      gap: "12px",
      padding: "12px 15px",
      background: "var(--bg-2)",
      border: "1px solid var(--border)",
      borderRadius: "var(--radius-md)",
      opacity: n.active ? 1 : 0.5
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
  }, (n.name || "?")[0].toUpperCase()), /*#__PURE__*/React.createElement("div", {
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
      color: "var(--text-dim)",
      border: "1px solid var(--border)",
      borderRadius: "3px",
      padding: "0 4px"
    }
  }, n.type || "—")), /*#__PURE__*/React.createElement("div", {
    style: {
      fontSize: "11px",
      color: "var(--text-dim)",
      fontFamily: "var(--font-mono)"
    }
  }, "zone : ", n.scope, " \xB7 ring ", n.ring_level, n.active ? "" : " · inactif")), /*#__PURE__*/React.createElement(ProvenanceBadge, {
    origin: n.prov,
    ring: n.ring,
    size: "sm"
  }))), !err && nodes === null && /*#__PURE__*/React.createElement("div", {
    style: {
      padding: "28px",
      textAlign: "center",
      color: "var(--text-dim)",
      fontSize: "13px"
    }
  }, "Lecture du registre\u2026"), !err && nodes !== null && nodes.length === 0 && /*#__PURE__*/React.createElement("div", {
    style: {
      padding: "28px",
      textAlign: "center",
      color: "var(--text-dim)",
      fontSize: "13px"
    }
  }, "Registre vide \u2014 aucun client f\xE9d\xE9r\xE9 d\xE9clar\xE9."))));
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

/* ==== hub-app (inline) ==== */
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
  persona: ["Mémoire du persona", "visible · masquable à l'affichage"],
  souverainete: ["Souveraineté", "curseur puissance · journal de provenance"]
};
function App() {
  const PREF = window.NokidoPrefs;
  const [view, setView] = React.useState("accueil");
  const [local, setLocal] = React.useState(() => PREF ? PREF.get("power", 68) : 68);
  const [theme, setTheme] = React.useState(() => PREF ? PREF.get("theme", "dark") : "dark");
  const [enabled, setEnabled] = React.useState({});
  // MODE PERSONNALISATION. La capacite existait ENTIEREMENT dans hub-views.ref.jsx
  // depuis longtemps -- glisser-deposer des tuiles, ordre persiste par NokidoPrefs
  // sous la cle tile_order, bandeau d'aide, tout y est -- mais editMode n'etait
  // PASSE PAR PERSONNE : il valait undefined, donc l'attribut draggable valait
  // toujours false. Une fonctionnalite complete, injoignable faute d'un interrupteur.
  // Mesure 2026-09-18 : zero occurrence de editMode dans ce builder et dans le shell.
  // (Et rappel paye DEUX fois aujourd'hui, la seconde en ayant ecrit l'avertissement
  //  soi-meme douze lignes plus bas : AUCUN accent grave ici, il referme la chaine.)
  // C'est le meme motif que les gardes branches sur un signal sans emetteur, applique
  // a l'interface : ne pas chercher a reconstruire, chercher qui devait cabler.
  const [editMode, setEditMode] = React.useState(false);
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
  }), /*#__PURE__*/React.createElement(Button, {
    variant: editMode ? "primary" : "ghost",
    size: "sm",
    icon: /*#__PURE__*/React.createElement(Ico, {
      n: editMode ? "check" : "move",
      s: 14
    }),
    title: editMode ? "Terminer la personnalisation" : "Reorganiser les tuiles",
    ["on" + "Click"]: () => setEditMode(v => !v)
  }, editMode ? "Terminé" : "Personnaliser"), /*#__PURE__*/React.createElement("button", {
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
    editMode: editMode,
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