/* Référence design (handoff) — NON compilé. Source canonique : composant du DS Nokido. */
/* Nokido — Composer son app : l'utilisateur compose SA vue à partir des sections.
   Catalogue (gauche) → ta vue (droite) ; épingler, masquer, réordonner. */
const { Button, Badge, ModuleCard, ProvenanceBadge, SovereigntyGauge } = window.NokidoDesignSystem_bdc2ac;

function CIco({ n, s = 18 }) { return <i data-lucide={n} style={{ width: s, height: s }} />; }

const CATALOG = [
  { id: "sante", domain: "sante", title: "Santé", desc: "Suivi, rappels, données sensibles", icon: "heart-pulse", provenance: "local" },
  { id: "domotique", domain: "domotique", title: "Domotique", desc: "Hub maison, scènes, local-first", icon: "house", provenance: "local" },
  { id: "transport", domain: "transport", title: "Transport", desc: "Trajets, mobilité, temps réel", icon: "route", provenance: "hybrid" },
  { id: "finance", domain: "finance", title: "Finance", desc: "Comptes, budgets, traçabilité", icon: "wallet", provenance: "local" },
  { id: "loisir", domain: "loisir", title: "Loisir", desc: "Sorties, médias, agenda", icon: "compass", provenance: "hybrid" },
  { id: "achat", domain: "achat", title: "Achat", desc: "Comparaison neutre, suivi prix", icon: "shopping-cart", provenance: "remote" },
  { id: "creation", domain: "creation", title: "Création", desc: "Texte, image, son, code", icon: "sparkles", provenance: "hybrid" },
  { id: "dev", domain: "dev", title: "Dev", desc: "Code, automatisations, skills", icon: "terminal", provenance: "local" },
  { id: "travail", domain: "travail", title: "Travail", desc: "Focus, tâches, documents", icon: "briefcase", provenance: "local" },
  { id: "energie", domain: "energie", title: "Énergie", desc: "Conso, sobriété, pilotage", icon: "zap", provenance: "local" },
  { id: "famille", domain: "famille", title: "Famille", desc: "Agenda commun, partage", icon: "users", provenance: "hybrid" },
  { id: "voyage", domain: "voyage", title: "Voyage", desc: "Itinéraires, découverte", icon: "plane", provenance: "hybrid" },
];

function CatalogRow({ mod, onAdd }) {
  const accent = `var(--domain-${mod.domain})`;
  return (
    <div style={{ display: "flex", alignItems: "center", gap: "11px", padding: "9px 11px", background: "var(--bg-2)",
      border: "1px solid var(--border)", borderRadius: "var(--radius-sm)" }}>
      <span style={{ display: "inline-flex", alignItems: "center", justifyContent: "center", width: "32px", height: "32px",
        borderRadius: "var(--radius-sm)", background: `color-mix(in srgb, ${accent} 16%, transparent)`, color: accent, flexShrink: 0 }}><CIco n={mod.icon} s={17} /></span>
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ fontSize: "12.5px", fontWeight: 600 }}>{mod.title}</div>
        <div style={{ fontSize: "10.5px", color: "var(--text-dim)", whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>{mod.desc}</div>
      </div>
      <button onClick={() => onAdd(mod.id)} aria-label="Ajouter" style={{ display: "inline-flex", alignItems: "center", justifyContent: "center",
        width: "28px", height: "28px", borderRadius: "var(--radius-sm)", border: "1px solid var(--border)", background: "transparent",
        color: "var(--purple)", cursor: "pointer", flexShrink: 0 }}><CIco n="plus" s={16} /></button>
    </div>
  );
}

function ComposerApp() {
  const [active, setActive] = React.useState(["sante", "domotique", "transport", "creation"]);
  const [pinned, setPinned] = React.useState({ sante: true, domotique: true });

  React.useEffect(() => { if (window.lucide) lucide.createIcons(); });

  const byId = (id) => CATALOG.find((m) => m.id === id);
  const inCatalog = CATALOG.filter((m) => !active.includes(m.id));

  const add = (id) => setActive((a) => a.includes(id) ? a : [...a, id]);
  const remove = (id) => { setActive((a) => a.filter((x) => x !== id)); setPinned((p) => { const n = { ...p }; delete n[id]; return n; }); };
  const togglePin = (id) => setPinned((p) => ({ ...p, [id]: !p[id] }));
  const move = (id, dir) => setActive((a) => {
    const i = a.indexOf(id); const j = i + dir;
    if (j < 0 || j >= a.length) return a;
    const n = [...a]; [n[i], n[j]] = [n[j], n[i]]; return n;
  });

  // pinned first
  const ordered = [...active].sort((x, y) => (pinned[y] ? 1 : 0) - (pinned[x] ? 1 : 0));
  const localCount = active.filter((id) => byId(id).provenance === "local").length;
  const localPct = active.length ? Math.round((localCount / active.length) * 100) : 0;

  return (
    <div style={{ display: "grid", gridTemplateColumns: "300px 1fr", height: "100vh", background: "var(--bg-0)", color: "var(--text-primary)" }}>

      {/* Catalogue */}
      <aside style={{ background: "var(--bg-1)", borderRight: "1px solid var(--border-subtle)", display: "flex", flexDirection: "column", minHeight: 0 }}>
        <div style={{ padding: "16px 16px 12px", borderBottom: "1px solid var(--border-subtle)" }}>
          <div style={{ fontSize: "13px", fontWeight: 700 }}>Catalogue</div>
          <div style={{ fontSize: "11px", color: "var(--text-dim)" }}>{inCatalog.length} sections disponibles</div>
        </div>
        <div style={{ flex: 1, overflowY: "auto", padding: "12px", display: "flex", flexDirection: "column", gap: "8px" }}>
          {inCatalog.map((m) => <CatalogRow key={m.id} mod={m} onAdd={add} />)}
          {inCatalog.length === 0 && <div style={{ padding: "20px", textAlign: "center", color: "var(--text-dim)", fontSize: "12px" }}>Toutes les sections sont dans ta vue.</div>}
        </div>
      </aside>

      {/* Ta vue */}
      <main style={{ display: "flex", flexDirection: "column", minWidth: 0 }}>
        <header style={{ height: "var(--topbar-h)", borderBottom: "1px solid var(--border-subtle)", background: "var(--bg-1)",
          display: "flex", alignItems: "center", padding: "0 22px", gap: "12px", flexShrink: 0 }}>
          <div>
            <div style={{ fontSize: "15px", fontWeight: 700, lineHeight: 1.1 }}>Compose ton app</div>
            <div style={{ fontSize: "11px", color: "var(--text-dim)", fontFamily: "var(--font-mono)" }}>épingle · masque · réordonne tes sections</div>
          </div>
          <div style={{ marginLeft: "auto", display: "flex", alignItems: "center", gap: "12px" }}>
            <SovereigntyGauge local={localPct} label={null} showLegend={false} height={7} style={{ width: "120px" }} />
            <span style={{ fontFamily: "var(--font-mono)", fontSize: "11px", color: "var(--prov-local)" }}>{localPct}% local</span>
            <Button variant="primary" size="sm" icon={<CIco n="check" s={14} />}>Enregistrer</Button>
          </div>
        </header>

        <div style={{ flex: 1, overflowY: "auto", padding: "22px 24px" }}>
          <div style={{ display: "flex", alignItems: "baseline", gap: "10px", marginBottom: "14px" }}>
            <h2 style={{ margin: 0, fontSize: "13px", fontWeight: 700, textTransform: "uppercase", letterSpacing: "0.6px", color: "var(--text-secondary)" }}>Ta vue</h2>
            <span style={{ fontFamily: "var(--font-mono)", fontSize: "11px", color: "var(--text-dim)" }}>{active.length} sections · {Object.values(pinned).filter(Boolean).length} épinglées</span>
          </div>

          {active.length === 0 ? (
            <div style={{ padding: "50px", textAlign: "center", color: "var(--text-dim)", border: "1px dashed var(--border)", borderRadius: "var(--radius-md)" }}>
              <div style={{ marginBottom: "8px" }}><CIco n="layout-grid" s={26} /></div>
              Ajoute des sections depuis le catalogue pour composer ton app.
            </div>
          ) : (
            <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(232px, 1fr))", gap: "14px" }}>
              {ordered.map((id) => {
                const m = byId(id);
                return (
                  <div key={id} style={{ position: "relative" }}>
                    <ModuleCard domain={m.domain} title={m.title} desc={m.desc} icon={<CIco n={m.icon} s={22} />}
                      provenance={m.provenance} pinned={!!pinned[id]} />
                    {/* contrôles de composition */}
                    <div style={{ display: "flex", gap: "5px", marginTop: "8px" }}>
                      <CtrlBtn icon={pinned[id] ? "pin-off" : "pin"} label={pinned[id] ? "Désépingler" : "Épingler"} active={pinned[id]} onClick={() => togglePin(id)} />
                      <CtrlBtn icon="arrow-up" onClick={() => move(id, -1)} />
                      <CtrlBtn icon="arrow-down" onClick={() => move(id, 1)} />
                      <CtrlBtn icon="eye-off" label="Masquer" onClick={() => remove(id)} danger />
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </div>
      </main>
    </div>
  );
}

function CtrlBtn({ icon, label, onClick, active, danger }) {
  return (
    <button onClick={onClick} title={label} style={{
      display: "inline-flex", alignItems: "center", gap: "6px", padding: label ? "5px 9px" : "5px",
      borderRadius: "var(--radius-sm)", cursor: "pointer", fontFamily: "var(--font-sans)", fontSize: "11px",
      border: `1px solid ${active ? "var(--purple)" : "var(--border)"}`,
      background: active ? "var(--tint-purple)" : "transparent",
      color: danger ? "var(--text-secondary)" : active ? "var(--purple)" : "var(--text-secondary)",
    }}>
      <InlineIcon name={icon} />{label}
    </button>
  );
}

// Inline SVG icons (React-owned — never mutated by lucide.createIcons)
const ICON_PATHS = {
  pin: ["M12 17v5", "M9 10.76a2 2 0 0 1-1.11 1.79l-1.78.9A2 2 0 0 0 5 15.24V16a1 1 0 0 0 1 1h12a1 1 0 0 0 1-1v-.76a2 2 0 0 0-1.11-1.79l-1.78-.9A2 2 0 0 1 15 10.76V7a1 1 0 0 1 1-1 2 2 0 0 0 0-4H8a2 2 0 0 0 0 4 1 1 0 0 1 1 1z"],
  "pin-off": ["M12 17v5", "M15 9.34V7a1 1 0 0 1 1-1 2 2 0 0 0 0-4H7.89", "M9 9v1.76a2 2 0 0 1-1.11 1.79l-1.78.9A2 2 0 0 0 5 15.24V16a1 1 0 0 0 1 1h11", "m2 2 20 20"],
  "arrow-up": ["m5 12 7-7 7 7", "M12 19V5"],
  "arrow-down": ["M12 5v14", "m19 12-7 7-7-7"],
  "eye-off": ["M10.73 5.08A10.43 10.43 0 0 1 12 5c5 0 9 4 10 7a13.16 13.16 0 0 1-1.67 2.68", "M6.61 6.61A13.5 13.5 0 0 0 2 12c1 3 5 7 10 7a9.7 9.7 0 0 0 5.39-1.61", "M9.88 9.88a3 3 0 1 0 4.24 4.24", "m2 2 20 20"],
};
function InlineIcon({ name, size = 13 }) {
  const paths = ICON_PATHS[name] || [];
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" style={{ flexShrink: 0 }}>
      {paths.map((d, i) => <path key={i} d={d} />)}
    </svg>
  );
}

Object.assign(window, { ComposerApp });
