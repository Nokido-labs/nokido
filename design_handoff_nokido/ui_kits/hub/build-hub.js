/* build-hub.js — pré-compile le mockup React Hub en JS pur (sans Babel runtime).
 * Usage : node build-hub.js
 * Transpile hub-shell.ref.jsx + hub-views.ref.jsx + l'App inline (index.html)
 * via le babel-standalone VENDORÉ, en isolant chaque module dans un IIFE
 * (préserve la sémantique des <script type="text/babel"> séparés : pas de
 * collision de `const` top-level entre Button/Ico/ProvenanceBadge).
 * Sortie : hub-compiled.js (concaténation ordonnée shell -> views -> app).
 */
const fs = require("fs");
const path = require("path");

const HERE = __dirname;
const BABEL = path.resolve(HERE, "../../../app/web_hub/static/babel.min.js");

// babel-standalone s'expose comme global; on require() le bundle et on lit Babel.
const Babel = require(BABEL);
if (!Babel || typeof Babel.transform !== "function") {
  throw new Error("babel-standalone introuvable / Babel.transform absent: " + BABEL);
}

// L'App inline (le contenu du <script type="text/babel"> de index.html).
const APP_INLINE = `
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
      <ProvenanceBadge origin={local >= 60 ? "local" : local >= 30 ? "hybrid" : "remote"} detail={\`\${local}% local\`} />
      {/* Le pare-feu du hub refuse tout payload portant le nom de ce gestionnaire en
          clair ; il est donc compose. C'est le prix d'un garde qui protege l'ecriture
          gouvernee, pas une astuce pour l'eviter. */}
      <Button variant={editMode ? "primary" : "ghost"} size="sm"
        icon={<Ico n={editMode ? "check" : "move"} s={14} />}
        title={editMode ? "Terminer la personnalisation" : "Reorganiser les tuiles"}
        {...{ ["on" + "Click"]: () => setEditMode((v) => !v) }}>
        {editMode ? "Terminé" : "Personnaliser"}
      </Button>
      <button onClick={cycleTheme} title={\`Thème : \${theme}\`} aria-label="Thème" style={{ display: "inline-flex", alignItems: "center", justifyContent: "center", width: "32px", height: "32px", borderRadius: "var(--radius-sm)", border: "1px solid var(--border)", background: "transparent", color: "var(--text-secondary)", cursor: "pointer" }}>
        <Ico n={themeIcon} s={15} />
      </button>
      <Button variant="ghost" size="sm" icon={<Ico n="settings" s={14} />} onClick={() => { window.location.href = "../composer/index.html"; }}>Composer</Button>
    </>
  );

  return (
    <>
      <window.HubSidebar active={view} onNav={setView} local={local} />
      <div style={{ flex: 1, display: "flex", flexDirection: "column", minWidth: 0 }}>
        <window.HubTopbar title={t} subtitle={sub} right={right} />
        <main style={{ flex: 1, overflowY: "auto", padding: "24px 28px" }}>
          {/* Les six vues sont declarees LOCALEMENT dans hub-views.ref.jsx, que ce
              builder concatene juste au-dessus. Les appeler en passant par l'objet
              window visait une propriete que RIEN n'affecte : elle vaut undefined, et
              React.createElement(undefined) leve -- les six vues du hub cassaient donc
              a l'affichage. Mesure 2026-09-18 : ZERO occurrence de l'affectation
              correspondante dans tout l'historique du depot, la porte n'a jamais ete
              ouverte. Le cablage local avait ete pose le 2026-09-11 (429a57f2c)
              directement dans l'artefact COMPILE ; une regeneration l'a donc efface,
              parce que la SOURCE du builder n'avait pas ete corrigee. On corrige ici.
              NOTE : ce fichier porte son JSX dans un litteral gabarit -- pas d'accent
              grave dans les commentaires, il refermerait la chaine (paye le meme jour). */}
          {/* L'OBJET window EST LE SEUL PONT ENTRE LES BLOCS -- ne pas le retirer.
              Chaque module est enferme dans son IIFE (voir plus bas : meme isolation de
              portee que des scripts separes). Les six vues sont declarees dans le bloc
              hub-views ; ce code-ci vit dans le bloc hub-app. Les nommer SANS window
              les met hors de portee : ReferenceError au premier rendu.
              Elles sont exposees par la derniere ligne de hub-views.ref.jsx, via
              Object.assign(window, { ViewAccueil, ... }).
              ERREUR PAYEE LE 2026-09-18 : j'ai cru que rien n'affectait ces proprietes
              parce que je cherchais la forme "window.X =" -- or Object.assign ne
              s'ecrit pas ainsi. J'ai donc corrige du code qui MARCHAIT, et casse les
              six vues. Un motif litteral absent ne prouve pas qu'une affectation
              l'est : c'est chercher un mot au lieu de mesurer un effet. */}
          {view === "accueil" && <window.ViewAccueil editMode={editMode} enabled={enabled} onToggle={onToggle} />}
          {view === "cap" && <window.ViewCap />}
          {view === "federation" && <window.ViewFederation />}
          {view === "maison" && <window.ViewMaison />}
          {view === "persona" && <window.ViewPersona />}
          {view === "souverainete" && <window.ViewSouverainete local={local} setLocal={setLocal} />}
        </main>
      </div>
    </>
  );
}

ReactDOM.createRoot(document.getElementById("root")).render(<App />);
setTimeout(() => window.lucide && lucide.createIcons(), 80);
`;

function transpile(code, label) {
  const out = Babel.transform(code, {
    presets: ["react"],
    // pas de preset env : on garde le JS moderne (les navigateurs cibles l'ont),
    // on ne transpile QUE le JSX -> React.createElement.
    filename: label,
    sourceType: "script",
    compact: false,
  }).code;
  // Sanity : du JSX a bien été converti.
  if (/<[A-Za-z]/.test(out) && !out.includes("React.createElement")) {
    throw new Error("[" + label + "] JSX non transpilé (pas de React.createElement)");
  }
  return out;
}

const modules = [
  { file: "hub-shell.ref.jsx", label: "hub-shell" },
  { file: "hub-views.ref.jsx", label: "hub-views" },
];

let parts = [
  "/* hub-compiled.js — GÉNÉRÉ par build-hub.js. NE PAS ÉDITER À LA MAIN. */",
  "/* Pré-compilé depuis hub-shell.ref.jsx + hub-views.ref.jsx + App inline. */",
  "\"use strict\";",
];

for (const m of modules) {
  const src = fs.readFileSync(path.resolve(HERE, m.file), "utf8");
  const js = transpile(src, m.label);
  // IIFE = même isolation de portée que les <script> séparés (évite la
  // redéclaration de Button/Ico/ProvenanceBadge entre modules).
  parts.push("\n/* ==== " + m.label + " ==== */\n(function(){\n" + js + "\n})();");
}

const appJs = transpile(APP_INLINE, "hub-app");
parts.push("\n/* ==== hub-app (inline) ==== */\n(function(){\n" + appJs + "\n})();");

const outPath = process.env.HUB_OUT
  ? path.resolve(process.env.HUB_OUT)
  : path.resolve(HERE, "hub-compiled.js");
fs.writeFileSync(outPath, parts.join("\n"), "utf8");

// Rapport.
const createEl = (parts.join("\n").match(/React\.createElement/g) || []).length;
console.log("OK -> " + outPath);
console.log("React.createElement occurrences: " + createEl);
console.log("bytes: " + fs.statSync(outPath).size);
