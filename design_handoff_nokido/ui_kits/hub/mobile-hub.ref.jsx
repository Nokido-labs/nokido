/* Référence design (handoff) — NON compilé. Source canonique : composant du DS Nokido. */
/* Nokido — Hub mobile (glance). Colonne unique, onglets bas. Réutilise le DS. */
const { Card, ModuleCard, SovereigntyGauge, ProvenanceBadge, PowerSlider, CapStep, Badge } = window.NokidoDesignSystem_bdc2ac;
const PREF = window.NokidoPrefs; // util de persistance partagé

function MIco({ n, s = 20 }) { return <i data-lucide={n} style={{ width: s, height: s }} />; }

const MODS = [
  { domain: "sante", title: "Santé", desc: "Local forcé — confidentialité max", icon: "heart-pulse", provenance: "local", pinned: true },
  { domain: "domotique", title: "Maison", desc: "Local-first absolu", icon: "house", provenance: "local", pinned: true },
  { domain: "transport", title: "Transport", desc: "Trajets, temps réel", icon: "route", provenance: "hybrid" },
  { domain: "creation", title: "Création", desc: "Atelier génératif", icon: "sparkles", provenance: "hybrid" },
];

function Logo({ size = 26 }) {
  return (
    <svg width={size} height={size} viewBox="0 0 64 64" fill="none" style={{ flexShrink: 0 }}>
      <defs><linearGradient id="mbolt" x1="26" y1="12" x2="40" y2="40" gradientUnits="userSpaceOnUse"><stop offset="0" stopColor="#FFE070" /><stop offset="1" stopColor="#FFC22D" /></linearGradient></defs>
      <g stroke="#15121F" strokeWidth="2.4" strokeLinejoin="round">
        <path d="M6 35 L20 31 H48 q4 0 4 3.5 Q52 39 47 39 H39 q-3 0 -4 3 l-1.5 3 H27 q-1 -3 -4 -3 H15 Q6 42 6 35 Z" fill="#9A90BC" />
        <path d="M28 45 h8 l-1.5 5 h-5 Z" fill="#6F6498" /><path d="M17 50 H47 l3 6 H14 Z" fill="#9A90BC" />
      </g>
      <g><rect x="4" y="29" width="23" height="5" rx="2.5" fill="#C77D4A" stroke="#15121F" strokeWidth="2.4" strokeLinejoin="round" />
        <rect x="25" y="21" width="11" height="21" rx="3" fill="#B7BCD2" stroke="#15121F" strokeWidth="2.4" strokeLinejoin="round" />
        <rect x="27.5" y="24" width="5.5" height="6" rx="1.5" fill="#D9DCE8" /></g>
      <path d="M31 41 L40 26 H34 L42 11 L30 28 H36 Z" fill="url(#mbolt)" stroke="#15121F" strokeWidth="2" strokeLinejoin="round" />
    </svg>
  );
}

const TABS = [
  { id: "accueil", icon: "layout-grid", label: "Accueil" },
  { id: "cap", icon: "target", label: "Cap" },
  { id: "maison", icon: "house", label: "Maison" },
  { id: "souv", icon: "shield-check", label: "Souv." },
];

function MobileHub() {
  const [tab, setTab] = React.useState("accueil");
  const [power, setPower] = React.useState(() => PREF ? PREF.get("power", 68) : 68);
  React.useEffect(() => { if (PREF) PREF.set("power", power); }, [power]);
  React.useEffect(() => { if (window.lucide) lucide.createIcons(); });

  return (
    <div style={{ height: "100%", display: "flex", flexDirection: "column", background: "var(--bg-0)", color: "var(--text-primary)", paddingTop: "50px", boxSizing: "border-box" }}>
      {/* header */}
      <header style={{ display: "flex", alignItems: "center", gap: "9px", padding: "6px 18px 12px", borderBottom: "1px solid var(--border-subtle)" }}>
        <Logo />
        <span style={{ fontWeight: 700, fontSize: "15px", letterSpacing: "0.3px" }}>Nokido</span>
        <ProvenanceBadge origin={power >= 60 ? "local" : power >= 30 ? "hybrid" : "remote"} detail={`${power}%`} size="sm" style={{ marginLeft: "auto" }} />
        <a href="../login/index.html" style={{ color: "var(--text-dim)", display: "inline-flex" }}><MIco n="lock" s={17} /></a>
      </header>

      {/* content */}
      <div style={{ flex: 1, overflowY: "auto", padding: "16px 18px 18px" }}>
        {tab === "accueil" && (
          <div style={{ display: "flex", flexDirection: "column", gap: "14px" }}>
            <Card style={{ background: "var(--bg-1)" }}>
              <SovereigntyGauge local={power} />
            </Card>
            <Card style={{ background: "var(--bg-1)" }}>
              <div style={{ display: "flex", alignItems: "center", gap: "7px", marginBottom: "8px" }}>
                <MIco n="target" s={15} /><span style={{ fontWeight: 700, fontSize: "13px" }}>Cap en cours</span>
                <Badge color="purple" mono>jalon 4/9</Badge>
              </div>
              <div style={{ fontSize: "13.5px", lineHeight: 1.5 }}>Reprendre le contrôle de mes données de santé · maison 100 % local-first.</div>
            </Card>
            <div style={{ fontFamily: "var(--font-mono)", fontSize: "10px", textTransform: "uppercase", letterSpacing: "0.6px", color: "var(--text-dim)", marginTop: "2px" }}>Tes sections</div>
            {MODS.map((m) => <ModuleCard key={m.domain} {...m} icon={<MIco n={m.icon} s={22} />} />)}
          </div>
        )}

        {tab === "cap" && (
          <div>
            <Card style={{ background: "var(--bg-1)", marginBottom: "14px" }}>
              <div style={{ fontSize: "10px", textTransform: "uppercase", letterSpacing: "0.6px", color: "var(--text-dim)", marginBottom: "5px" }}>Horizon</div>
              <div style={{ fontSize: "15px", fontWeight: 600, lineHeight: 1.4 }}>Maison 100 % local-first d'ici l'automne.</div>
            </Card>
            <div>
              <CapStep index={1} title="Cartographier l'historique" state="done" provenance="local" ring="gold" />
              <CapStep index={2} title="Reconstituer le cap" state="done" provenance="local" ring="verified" />
              <CapStep index={3} title="Décomposer en 112 étapes" state="active" provenance="remote" ring="verified" />
              <CapStep index={4} title="Migrer la domotique" state="pending" ring="draft" last />
            </div>
          </div>
        )}

        {tab === "maison" && (
          <div style={{ display: "flex", flexDirection: "column", gap: "12px" }}>
            <Card style={{ background: "var(--bg-1)", borderColor: "var(--prov-local)" }}>
              <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
                <MIco n="shield-check" s={16} /><span style={{ fontWeight: 600, fontSize: "13px" }}>Maison vivante</span>
                <ProvenanceBadge origin="local" size="sm" style={{ marginLeft: "auto" }} />
              </div>
            </Card>
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "10px" }}>
              {[["sunrise", "Réveil", false], ["laptop", "Travail", true], ["clapperboard", "Cinéma", false], ["moon", "Nuit", false]].map(([ic, n, on]) => (
                <div key={n} style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: "7px", padding: "16px",
                  borderRadius: "var(--radius-md)", background: on ? "var(--tint-green)" : "var(--bg-2)",
                  border: `1px solid ${on ? "var(--prov-local)" : "var(--border)"}`, color: on ? "var(--prov-local)" : "var(--text-secondary)" }}>
                  <MIco n={ic} s={22} /><span style={{ fontSize: "12.5px", fontWeight: 600 }}>{n}</span>
                </div>
              ))}
            </div>
          </div>
        )}

        {tab === "souv" && (
          <div style={{ display: "flex", flexDirection: "column", gap: "14px" }}>
            <PowerSlider value={power} onChange={setPower} />
            <Card>
              <div style={{ fontSize: "12px", color: "var(--text-secondary)", lineHeight: 1.6 }}>
                <b style={{ color: "var(--prov-local)" }}>NPU → iGPU → local</b> → <b style={{ color: "var(--prov-remote)" }}>cloud</b> en dernier recours. Ta machine traite {power}% des requêtes.
              </div>
            </Card>
          </div>
        )}
      </div>

      {/* tab bar */}
      <nav style={{ display: "flex", borderTop: "1px solid var(--border-subtle)", background: "var(--bg-1)",
        paddingBottom: "calc(8px + env(safe-area-inset-bottom))", paddingTop: "8px" }}>
        {TABS.map((t) => {
          const on = tab === t.id;
          return (
            <button key={t.id} onClick={() => setTab(t.id)} style={{
              flex: 1, display: "flex", flexDirection: "column", alignItems: "center", gap: "3px", padding: "4px",
              minHeight: "48px", border: "none", background: "transparent", cursor: "pointer",
              color: on ? "var(--purple)" : "var(--text-dim)", fontFamily: "var(--font-sans)" }}>
              <MIco n={t.icon} s={20} /><span style={{ fontSize: "10px", fontWeight: on ? 700 : 500 }}>{t.label}</span>
            </button>
          );
        })}
      </nav>
    </div>
  );
}

Object.assign(window, { MobileHub });
