/* Nokido Hub — App (source canonique EDITABLE ; pre-compile via C:/tmp/precompile_hub.js).
   Extrait de l'ancien <script type="text/babel"> inline d'index.html pour rester editable.
   Sert les vraies vues (window.View*). Composer -> mode personnalisation (tuiles repositionnables). */
const { ProvenanceBadge, Button } = window.NokidoDesignSystem_bdc2ac;
const Ico = window.HubIco;

const TITLES = {
  accueil: ["Accueil", "ton hub personnel · local par défaut"],
  cap: ["Intention longue", "le cap → jalons → 112 étapes"],
  federation: ["Fédération", "exposer son hub d'IA · garde-fous souverains"],
  maison: ["Maison", "domotique · local-first absolu"],
  persona: ["Mémoire du persona", "visible · masquable à l'affichage"],
  souverainete: ["Souveraineté", "curseur puissance · journal de provenance"],
};

function App() {
  const PREF = window.NokidoPrefs;
  const [view, setView] = React.useState("accueil");
  const [local, setLocal] = React.useState(() => PREF ? PREF.get("power", 68) : 68);
  const [theme, setTheme] = React.useState(() => PREF ? PREF.get("theme", "dark") : "dark");
  const [enabled, setEnabled] = React.useState({});
  const [editMode, setEditMode] = React.useState(false);
  const onToggle = (d, v) => setEnabled((e) => ({ ...e, [d]: v }));

  React.useEffect(() => { if (PREF) PREF.set("power", local); }, [local]);

  const cycleTheme = () => { const next = PREF ? PREF.cycleTheme() : theme; setTheme(next); };
  const themeIcon = { dark: "moon", light: "sun", auto: "monitor" }[theme] || "moon";

  React.useEffect(() => {
    if (window.lucide) lucide.createIcons();
  });

  const [t, sub] = TITLES[view];
  const right = (
    <>
      <ProvenanceBadge origin={local >= 60 ? "local" : local >= 30 ? "hybrid" : "remote"} detail={`${local}% local`} />
      <button onClick={cycleTheme} title={`Thème : ${theme}`} aria-label="Thème" style={{ display: "inline-flex", alignItems: "center", justifyContent: "center", width: "32px", height: "32px", borderRadius: "var(--radius-sm)", border: "1px solid var(--border)", background: "transparent", color: "var(--text-secondary)", cursor: "pointer" }}>
        <Ico n={themeIcon} s={15} />
      </button>
      <Button variant="ghost" size="sm" icon={<Ico n={editMode ? "check" : "settings"} s={14} />} onClick={() => setEditMode((e) => !e)} title="Personnaliser l'interface (réorganiser les tuiles)">{editMode ? "Terminé" : "Composer"}</Button>
    </>
  );

  return (
    <>
      <window.HubSidebar active={view} onNav={setView} local={local} />
      <div style={{ flex: 1, display: "flex", flexDirection: "column", minWidth: 0 }}>
        <window.HubTopbar title={t} subtitle={sub} right={right} />
        <main style={{ flex: 1, overflowY: "auto", padding: "24px 28px" }}>
          {view === "accueil" && <ViewAccueil enabled={enabled} onToggle={onToggle} editMode={editMode} />}
          {view === "cap" && <ViewCap />}
          {view === "federation" && <ViewFederation />}
          {view === "maison" && <ViewMaison />}
          {view === "persona" && <ViewPersona />}
          {view === "souverainete" && <ViewSouverainete local={local} setLocal={setLocal} />}
        </main>
      </div>
    </>
  );
}

ReactDOM.createRoot(document.getElementById("root")).render(<App />);
setTimeout(() => window.lucide && lucide.createIcons(), 80);
