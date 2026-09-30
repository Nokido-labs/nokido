/* Référence design (handoff) — NON compilé. Source canonique : composant du DS Nokido. */
/* Nokido Hub — coquille : sidebar souveraine + topbar avec jauge & persona */
const { SovereigntyGauge, Badge, ProvenanceBadge } = window.NokidoDesignSystem_bdc2ac;

const NAV = [
  { id: "accueil", label: "Accueil", icon: "layout-grid" },
  { id: "cap", label: "Intention longue", icon: "target" },
  { id: "federation", label: "Fédération", icon: "share-2" },
  { id: "maison", label: "Maison", icon: "house" },
  { id: "persona", label: "Mémoire persona", icon: "brain" },
  { id: "souverainete", label: "Souveraineté", icon: "shield-check" },
];

// Surfaces EXTERNES (autres origines) — lien réel ouvert en nouvel onglet (jamais une vue interne :
// leurs liens absolus /forge/* /static/* casseraient sous un proxy). Statut live = sonde serveur
// same-origin /status[statusKey] (pas de CORS). Centralise l'accès depuis la taskbar :7400.
const EXTERNAL = [
  { id: "mcphub", label: "Hub :8766", icon: "server", href: "http://127.0.0.1:8766/",
    title: "Hub MCP :8766 — RAG · Network · Debate · Graph · Postal · Feed", statusKey: "mcphub" },
];

function _pascal(n) {
  return String(n).split("-").map((p) => p.charAt(0).toUpperCase() + p.slice(1)).join("");
}
// SVG natif (React-safe) : evite que React ecrase le <svg> de lucide.createIcons.
function Ico({ n, s = 18 }) {
  const html = React.useMemo(() => {
    try {
      const ch = window.lucide && window.lucide.icons && window.lucide.icons[_pascal(n)];
      if (!Array.isArray(ch)) return "";
      const inner = ch.map((x) => {
        const tag = x[0], attrs = x[1] || {};
        const a = Object.keys(attrs).map((k) => k + '="' + String(attrs[k]).replace(/"/g, "&quot;") + '"').join(" ");
        return "<" + tag + " " + a + "/>";
      }).join("");
      return '<svg xmlns="http://www.w3.org/2000/svg" width="' + s + '" height="' + s +
        '" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">' + inner + "</svg>";
    } catch (e) { return ""; }
  }, [n, s]);
  return <span style={{ display: "inline-flex", alignItems: "center", justifyContent: "center", width: s, height: s }}
               dangerouslySetInnerHTML={{ __html: html }} />;
}

function HubSidebar({ active, onNav, local }) {
  // Statut live des surfaces externes : sonde serveur same-origin /status (pas de CORS), 15s.
  const [surf, setSurf] = React.useState({});
  React.useEffect(() => {
    let alive = true;
    const tick = () => fetch("/status", { credentials: "same-origin" })
      .then((r) => (r.ok ? r.json() : {}))
      .then((d) => { if (alive) setSurf(d || {}); })
      .catch(() => {});
    tick();
    const iv = setInterval(tick, 15000);
    return () => { alive = false; clearInterval(iv); };
  }, []);
  return (
    <aside style={{
      width: "var(--sidebar-w)", background: "var(--bg-1)", borderRight: "1px solid var(--border-subtle)",
      display: "flex", flexDirection: "column", flexShrink: 0,
    }}>
      <div style={{ display: "flex", alignItems: "center", gap: "8px", padding: "14px 16px",
        borderBottom: "1px solid var(--border-subtle)" }}>
        {/* Marque NOKIDO (2026-09-18). Ce qui etait dessine ici jusqu'a ce jour
            etait l'enclume, le marteau et l'eclair de LaForge -- l'ancien nom --
            affiches juste a cote du mot « Nokido ». Le dessin de la marque
            existait deja et etait servi comme favicon : c'est le meme trace qui
            est repris ici, pour qu'il n'y ait qu'UNE marque et qu'elle soit la
            bonne. Les identifiants de degrade sont prefixes `nokido` : `lfBolt`
            etait a la fois un reste de l'ancien nom et un nom trop general pour
            un document qui porte plusieurs SVG. */}
        <svg width="26" height="26" viewBox="0 0 96 96" fill="none" style={{ flexShrink: 0 }}>
          <defs>
            <linearGradient id="nokidoFlux" x1="0" y1="0" x2="1" y2="1">
              <stop offset="0" stopColor="#EC4899" />
              <stop offset="0.5" stopColor="#F24F4F" />
              <stop offset="1" stopColor="#FF9142" />
            </linearGradient>
            <linearGradient id="nokidoMetal" gradientUnits="userSpaceOnUse" x1="0" y1="22" x2="0" y2="74">
              <stop offset="0" stopColor="#4A4759" />
              <stop offset="1" stopColor="#2E2A3D" />
            </linearGradient>
          </defs>
          <path d="M27 22 C24.5 40, 24.5 56, 27 74" fill="none" stroke="url(#nokidoMetal)" strokeWidth="15" strokeLinecap="round" />
          <path d="M69 22 C71.5 40, 71.5 56, 69 74" fill="none" stroke="url(#nokidoMetal)" strokeWidth="15" strokeLinecap="round" />
          <path d="M27 22 C43 33, 53 63, 69 74" fill="none" stroke="url(#nokidoFlux)" strokeWidth="15" strokeLinecap="round" />
          <circle cx="27" cy="22" r="11" fill="#F24F4F" />
          <circle cx="69" cy="74" r="11" fill="#FF9142" />
        </svg>
        <span style={{ fontWeight: 700, fontSize: "15px", letterSpacing: "0.4px" }}>Nokido</span>
        <span className="laforge-pulse" style={{ marginLeft: "auto", width: "7px", height: "7px",
          borderRadius: "50%", background: "var(--green)" }} />
      </div>

      <nav style={{ padding: "10px 8px", display: "flex", flexDirection: "column", gap: "2px" }}>
        {NAV.map((n) => {
          const on = active === n.id;
          return (
            <button key={n.id} onClick={() => onNav(n.id)} style={{
              display: "flex", alignItems: "center", gap: "10px", padding: "9px 11px",
              borderRadius: "var(--radius-sm)", border: "none", cursor: "pointer", textAlign: "left",
              fontSize: "13px", fontWeight: on ? 600 : 500, fontFamily: "var(--font-sans)",
              background: on ? "var(--bg-3)" : "transparent",
              color: on ? "var(--text-primary)" : "var(--text-secondary)",
              boxShadow: on ? "inset 3px 0 0 var(--purple)" : "none",
              transition: "background var(--motion-fast)",
            }}
            onMouseEnter={(e) => { if (!on) e.currentTarget.style.background = "var(--bg-2)"; }}
            onMouseLeave={(e) => { if (!on) e.currentTarget.style.background = "transparent"; }}>
              <Ico n={n.icon} />{n.label}
            </button>
          );
        })}

        {EXTERNAL.length > 0 && (
          <div style={{ marginTop: "8px", paddingTop: "8px", borderTop: "1px solid var(--border-subtle)" }}>
            <div style={{ padding: "2px 11px 6px", fontSize: "10px", fontWeight: 700, letterSpacing: "0.6px",
              textTransform: "uppercase", color: "var(--text-dim)" }}>Interfaces</div>
            {EXTERNAL.map((n) => {
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
              const dotColor = st == null ? "var(--text-disabled)"
                : st.ok ? "var(--green)" : injoignable ? "var(--red)" : "var(--yellow)";
              const dotTitle = st == null ? "statut inconnu"
                : st.ok ? "en ligne"
                : injoignable ? "injoignable — connexion refusée"
                : "état non mesuré — la sonde n'a pas abouti (" + (motif || "sans motif") + ")";
              return (
                <a key={n.id} href={n.href} target="_blank" rel="noopener" title={n.title || n.label} style={{
                  display: "flex", alignItems: "center", gap: "10px", padding: "9px 11px",
                  borderRadius: "var(--radius-sm)", textDecoration: "none",
                  fontSize: "13px", fontWeight: 500, fontFamily: "var(--font-sans)",
                  background: "transparent", color: "var(--text-secondary)",
                  transition: "background var(--motion-fast)",
                }}
                onMouseEnter={(e) => { e.currentTarget.style.background = "var(--bg-2)"; }}
                onMouseLeave={(e) => { e.currentTarget.style.background = "transparent"; }}>
                  <Ico n={n.icon} />
                  <span style={{ flex: 1 }}>{n.label}</span>
                  <span className={st && st.ok ? "laforge-pulse" : ""} title={dotTitle} style={{ width: "7px",
                    height: "7px", borderRadius: "50%", background: dotColor, flexShrink: 0 }} />
                  <Ico n="external-link" s={12} />
                </a>
              );
            })}
          </div>
        )}
      </nav>

      <div style={{ marginTop: "auto", padding: "14px", borderTop: "1px solid var(--border-subtle)" }}>
        <div style={{ display: "flex", gap: "6px", marginBottom: "12px" }}>
          <a href="/auth/logout" title="Verrouiller le coffre (déconnexion)" style={{ flex: 1, display: "inline-flex", alignItems: "center", justifyContent: "center", gap: "6px",
            padding: "7px 9px", borderRadius: "var(--radius-sm)", border: "1px solid var(--border)", color: "var(--text-secondary)", fontSize: "11px" }}>
            <Ico n="lock" s={13} />Verrouiller</a>
        </div>
        <SovereigntyGauge local={local} showLegend={false} height={8} />
        <div style={{ marginTop: "12px", display: "flex", alignItems: "center", gap: "8px" }}>
          <span style={{ width: "26px", height: "26px", borderRadius: "50%", background: "var(--purple-dim)",
            display: "flex", alignItems: "center", justifyContent: "center", fontSize: "11px", fontWeight: 700 }}>N</span>
          <div style={{ lineHeight: 1.2 }}>
            <div style={{ fontSize: "12px", fontWeight: 600 }}>user</div>
            <div style={{ fontFamily: "var(--font-mono)", fontSize: "9.5px", color: "var(--text-dim)" }}>Ring 0 · nœud souverain</div>
          </div>
        </div>
      </div>
    </aside>
  );
}

function HubTopbar({ title, subtitle, right }) {
  return (
    <header style={{
      height: "var(--topbar-h)", borderBottom: "1px solid var(--border-subtle)", background: "var(--bg-1)",
      display: "flex", alignItems: "center", padding: "0 22px", gap: "14px", flexShrink: 0,
    }}>
      <div>
        <div style={{ fontSize: "15px", fontWeight: 700, lineHeight: 1.1 }}>{title}</div>
        {subtitle && <div style={{ fontSize: "11px", color: "var(--text-dim)", fontFamily: "var(--font-mono)" }}>{subtitle}</div>}
      </div>
      <div style={{ marginLeft: "auto", display: "flex", alignItems: "center", gap: "10px" }}>{right}</div>
    </header>
  );
}

window.HubSidebar = HubSidebar;
window.HubTopbar = HubTopbar;
window.HubIco = Ico;
