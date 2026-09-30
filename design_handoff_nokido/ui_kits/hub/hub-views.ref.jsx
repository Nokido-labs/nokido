/* Référence design (handoff) — NON compilé. Source canonique : composant du DS Nokido. */
/* Nokido Hub — vues principales */
const {
  Card, Button, Badge, StatusPill, ProvenanceBadge, SovereigntyGauge,
  PowerSlider, ModuleCard, CapStep, TextInput,
} = window.NokidoDesignSystem_bdc2ac;
const Ico = window.HubIco;

/* Grille fictive retiree. L'Accueil charge tes VRAIES interfaces Nokido (SERVICES
   live) via GET /api/hub/modules — chaque tuile = lien reel + statut up/down. */
function RealInterfaces({ editMode }) {
  const PREF = window.NokidoPrefs;
  const [mods, setMods] = React.useState([]);
  const [err, setErr] = React.useState("");
  const [order, setOrder] = React.useState(() => (PREF ? PREF.get("tile_order", []) : []));
  const dragSlug = React.useRef(null);
  React.useEffect(() => {
    fetch("/api/hub/modules", { credentials: "same-origin" })
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error("HTTP " + r.status))))
      .then((d) => setMods(Array.isArray(d) ? d : []))
      .catch((e) => setErr(String(e && e.message || e)));
  }, []);
  React.useEffect(() => { if (window.lucide) lucide.createIcons(); }, [mods]);
  const provOf = (s) => (s === "up" ? "local" : s === "down" ? "remote" : "hybrid");
  // Ordre persistant (NokidoPrefs) : applique l'ordre memorise, nouveaux modules a la fin.
  const ordered = React.useMemo(() => {
    const bySlug = {}; mods.forEach((m) => { bySlug[m.slug] = m; });
    const seen = new Set(); const out = [];
    (order || []).forEach((s) => { if (bySlug[s]) { out.push(bySlug[s]); seen.add(s); } });
    mods.forEach((m) => { if (!seen.has(m.slug)) out.push(m); });
    return out;
  }, [mods, order]);
  const persist = (slugs) => { setOrder(slugs); if (PREF) PREF.set("tile_order", slugs); };
  const onDrop = (targetSlug) => {
    const src = dragSlug.current; dragSlug.current = null;
    if (!src || src === targetSlug) return;
    const slugs = ordered.map((m) => m.slug);
    const from = slugs.indexOf(src), to = slugs.indexOf(targetSlug);
    if (from < 0 || to < 0) return;
    slugs.splice(to, 0, slugs.splice(from, 1)[0]);
    persist(slugs);
  };
  return (
    <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(248px, 1fr))", gap: "14px" }}>
      {ordered.map((m) => {
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
        const vers_lanceur = !up && !inconnu;          // soon / down / etat non favorable
        const clickable = !editMode;                    // plus jamais de tuile morte
        const cible = vers_lanceur ? "/launcher" : m.href;
        const hint = up ? "" : inconnu ? "État non mesuré — la tuile reste ouvrable"
          : (m.status === "soon"
             ? "Bientôt — ouvre le lanceur (rien ne démarre au clic)"
             : "Service arrêté — ouvre le lanceur pour le démarrer explicitement");
        return (
        <div key={m.slug}
          className={"lf-tile" + (clickable ? "" : " is-static")}
          draggable={!!editMode}
          onDragStart={editMode ? (() => { dragSlug.current = m.slug; }) : undefined}
          onDragOver={editMode ? ((e) => e.preventDefault()) : undefined}
          onDrop={editMode ? (() => onDrop(m.slug)) : undefined}
          style={{ cursor: editMode ? "grab" : "default", borderRadius: "var(--radius-md)",
            outline: editMode ? "1px dashed var(--border)" : "none", outlineOffset: "2px" }}>
          <a href={clickable ? cible : undefined} target={(m.external && !vers_lanceur) ? "_blank" : "_self"} rel="noopener"
             onClick={clickable ? undefined : ((e) => e.preventDefault())} title={hint}
             style={{ textDecoration: "none", display: "block", opacity: up ? 1 : inconnu ? 0.85 : 0.65,
               cursor: clickable ? "pointer" : "default", pointerEvents: editMode ? "none" : "auto" }}>
            <ModuleCard domain={m.slug} title={m.title} desc={m.desc} icon={<Ico n={m.icon} s={22} />}
              provenance={provOf(m.status)} comingSoon={m.status === "soon" || m.status === "down"} enabled={true} onToggle={null} />
          </a>
        </div>
        );
      })}
      {ordered.length === 0 && (
        <div style={{ padding: "20px", color: err ? "var(--red)" : "var(--text-dim)", fontFamily: "var(--font-mono)", fontSize: "12px" }}>
          {err ? ("Erreur /api/hub/modules : " + err) : "chargement des interfaces…"}
        </div>
      )}
    </div>
  );
}

function SectionTitle({ children, hint }) {
  return (
    <div style={{ display: "flex", alignItems: "baseline", gap: "10px", margin: "0 0 14px" }}>
      <h2 style={{ margin: 0, fontSize: "13px", fontWeight: 700, textTransform: "uppercase",
        letterSpacing: "0.6px", color: "var(--text-secondary)" }}>{children}</h2>
      {hint && <span style={{ fontSize: "11px", color: "var(--text-dim)", fontFamily: "var(--font-mono)" }}>{hint}</span>}
    </div>
  );
}

/* ---------------- Accueil ---------------- */
/* Trois états, jamais deux — un échec ne doit se lire ni comme une donnée vide, ni
   comme un chargement qui continue. Mesuré le 2026-09-11 (témoin
   tools/forge_ui_contrat_etats.py) : sur /api/hub/persona les états LOADING,
   DATA_VIDE et ERROR rendaient une seule et même empreinte de DOM ; sur
   /api/hub/overview l'échec affichait « Chargement… » indéfiniment, alors que
   l'endpoint met 5,9 s à répondre quand il va bien — l'utilisateur ne pouvait pas
   distinguer « c'est lent » de « c'est mort ». */
function ErrBanner({ msg }) {
  if (!msg) return null;
  return (
    <div role="alert" style={{ padding: "10px 14px", borderRadius: "var(--radius-sm)",
      background: "rgba(242,79,79,0.12)", border: "1px solid rgba(242,79,79,0.45)",
      fontSize: "13px", color: "var(--text-primary)", marginBottom: "4px" }}>
      Données indisponibles — {msg}. Ce n'est pas un état vide : Nokido n'a pas pu lire cette source.
    </div>
  );
}

function ViewAccueil({ enabled, onToggle, editMode }) {
  const [ov, setOv] = React.useState(null);
  const [err, setErr] = React.useState(null);
  React.useEffect(() => {
    fetch("/api/hub/overview", { credentials: "same-origin" })
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error("HTTP " + r.status))))
      .then(setOv)
      .catch((e) => setErr(String((e && e.message) || e)));
  }, []);
  const souvenirs = ov ? ov.souvenirs : null;
  const localPct = ov ? ov.local_pct : 0;
  const matur = souvenirs == null ? "—"
    : (souvenirs >= 40 ? "4 / 5" : souvenirs >= 20 ? "3 / 5" : souvenirs >= 8 ? "2 / 5" : "1 / 5");
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: "26px" }}>
      <ErrBanner msg={err} />
      {editMode && (
        <div style={{ padding: "9px 13px", borderRadius: "var(--radius-sm)", background: "rgba(139,92,246,0.12)",
          border: "1px solid var(--border)", fontSize: "12px", color: "var(--text-secondary)",
          display: "flex", alignItems: "center", gap: "8px" }}>
          <Ico n="move" s={14} /> Mode personnalisation — glisse-dépose tes tuiles pour les réorganiser (ordre mémorisé). Reclique « Terminé » pour finir.
        </div>
      )}
      <div style={{ display: "grid", gridTemplateColumns: "2fr 1fr", gap: "14px" }}>
        <Card className="lf-tile" style={{ background: "var(--bg-1)" }}>
          <div style={{ display: "flex", alignItems: "center", gap: "8px", marginBottom: "10px" }}>
            <Ico n="target" s={16} />
            <span style={{ fontWeight: 700, fontSize: "14px" }}>Cap en cours</span>
            <Badge color="purple" mono>{ov ? ov.n_steps + " étapes" : err ? "indisponible" : "…"}</Badge>
          </div>
          <p style={{ margin: 0, fontSize: "15px", color: "var(--text-primary)", lineHeight: 1.5 }}>
            {ov ? ov.intention : err ? "Roadmap indisponible — l'appel a échoué." : "Chargement de la roadmap active…"}
          </p>
          <div style={{ marginTop: "14px", display: "flex", alignItems: "center", gap: "10px" }}>
            <SovereigntyGauge local={localPct} label={null} showLegend={false} height={8} style={{ flex: 1 }} />
            <span style={{ fontFamily: "var(--font-mono)", fontSize: "11px", color: "var(--text-dim)" }}>{localPct}% local</span>
          </div>
        </Card>
        <Card className="lf-tile" style={{ background: "var(--bg-1)" }}>
          <div style={{ display: "flex", alignItems: "center", gap: "8px", marginBottom: "10px" }}>
            <Ico n="brain" s={16} /><span style={{ fontWeight: 700, fontSize: "14px" }}>Persona</span>
          </div>
          <div style={{ display: "flex", flexDirection: "column", gap: "7px", fontSize: "12px", color: "var(--text-secondary)" }}>
            <div style={{ display: "flex", justifyContent: "space-between" }}><span>Maturité</span><span style={{ color: "var(--cyan)", fontFamily: "var(--font-mono)" }}>niveau {matur}</span></div>
            <div style={{ display: "flex", justifyContent: "space-between" }}><span>Souvenirs</span><span style={{ fontFamily: "var(--font-mono)" }}>{souvenirs == null ? "…" : souvenirs + " actifs"}</span></div>
            <div style={{ display: "flex", justifyContent: "space-between" }}><span>Source</span><span style={{ fontFamily: "var(--font-mono)", color: "var(--text-dim)" }}>lessons_learned</span></div>
          </div>
        </Card>
      </div>

      <div>
        <SectionTitle hint={editMode ? "perso · glisse pour réordonner" : "live · clic pour ouvrir"}>Tes interfaces Nokido</SectionTitle>
        <RealInterfaces editMode={editMode} />
      </div>
    </div>
  );
}

/* ---------------- Cap (intention longue) ---------------- */
function ViewCap() {
  const [ov, setOv] = React.useState(null);
  const [err, setErr] = React.useState(null);
  React.useEffect(() => {
    fetch("/api/hub/overview", { credentials: "same-origin" })
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error("HTTP " + r.status))))
      .then(setOv)
      .catch((e) => setErr(String((e && e.message) || e)));
  }, []);
  const steps = (ov && ov.steps) || [];
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: "20px", maxWidth: "780px" }}>
      <ErrBanner msg={err} />
      <Card style={{ background: "var(--bg-1)" }}>
        <div style={{ fontSize: "11px", textTransform: "uppercase", letterSpacing: "0.6px", color: "var(--text-dim)", marginBottom: "6px" }}>Horizon · roadmap active (réel)</div>
        <p style={{ margin: 0, fontSize: "18px", fontWeight: 600, lineHeight: 1.4 }}>
          {ov ? ov.intention : err ? "Roadmap indisponible — l'appel a échoué." : "Chargement de la roadmap…"}
        </p>
      </Card>

      <div style={{ display: "flex", alignItems: "center" }}>
        <span style={{ fontFamily: "var(--font-mono)", fontSize: "11px", color: "var(--text-dim)" }}>
          {steps.length} étapes récentes (lessons_learned) · {ov ? ov.souvenirs : 0} souvenirs · {ov ? ov.local_pct : 0}% local
        </span>
      </div>

      <Card>
        <div style={{ marginTop: "2px" }}>
          {steps.map((s, i) => (
            <CapStep key={i} index={i + 1} title={s.title} state="done" provenance="local" ring="verified" last={i === steps.length - 1} />
          ))}
          {steps.length === 0 && (
            <div style={{ padding: "20px", color: "var(--text-dim)", fontSize: "13px" }}>Aucune étape récente indexée dans lessons_learned.</div>
          )}
        </div>
      </Card>
    </div>
  );
}

/* ---------------- Maison (domotique) ---------------- */
function ViewMaison() {
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: "22px", maxWidth: "820px" }}>
      <Card style={{ background: "var(--bg-1)", borderColor: "var(--prov-local)", boxShadow: "var(--prov-local-glow)" }}>
        <div style={{ display: "flex", alignItems: "center", gap: "10px" }}>
          <Ico n="shield-check" s={18} />
          <span style={{ fontWeight: 600 }}>Maison vivante — local-first absolu</span>
          <ProvenanceBadge origin="local" detail="ne dépend jamais du cloud" style={{ marginLeft: "auto" }} />
        </div>
      </Card>

      <div style={{ padding: "44px", textAlign: "center", background: "var(--bg-2)",
        border: "1px dashed var(--border)", borderRadius: "var(--radius-md)" }}>
        <Ico n="house-plug" s={26} />
        <div style={{ color: "var(--text-secondary)", fontSize: "14px", fontWeight: 600, margin: "10px 0 6px" }}>Aucun appareil connecté</div>
        <div style={{ color: "var(--text-dim)", fontSize: "12px", maxWidth: "440px", margin: "0 auto", lineHeight: 1.55 }}>
          La domotique se branchera ici (capteurs &amp; actionneurs, local-first). Aucun pont
          domotique (Home Assistant / Matter / Zigbee) n'est encore connecté à Nokido — donc
          rien d'inventé ici tant qu'aucun device réel n'est appairé.
        </div>
      </div>
    </div>
  );
}

/* ---------------- Persona (mémoire) ---------------- */
function ViewPersona() {
  /* `null` = pas encore répondu. Un tableau vide ne peut donc plus signifier
     « je n'ai rien reçu » : les trois états sont portés par l'état React. */
  const [mem, setMem] = React.useState(null);
  const [err, setErr] = React.useState(null);
  React.useEffect(() => {
    fetch("/api/hub/persona", { credentials: "same-origin" })
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error("HTTP " + r.status))))
      .then((d) => setMem(Array.isArray(d) ? d : []))
      .catch((e) => setErr(String((e && e.message) || e)));
  }, []);
  const revoke = (i) => setMem((mem || []).filter((_, j) => j !== i));
  return (
    <div style={{ maxWidth: "720px" }}>
      <Card style={{ background: "var(--bg-1)", marginBottom: "16px" }}>
        <div style={{ display: "flex", alignItems: "center", gap: "10px" }}>
          <Ico n="brain" s={18} />
          <div>
            <div style={{ fontWeight: 600 }}>Ce que Nokido a compris de toi</div>
            <div style={{ fontSize: "12px", color: "var(--text-dim)" }}>Tout est visible. « Masquer » retire une entrée de CET affichage seulement — la révocation côté persona n'est pas branchée.</div>
          </div>
        </div>
      </Card>
      <ErrBanner msg={err} />
      <div style={{ display: "flex", flexDirection: "column", gap: "8px" }}>
        {(mem || []).map((m, i) => (
          <div key={i} style={{ display: "flex", alignItems: "center", gap: "12px", padding: "12px 15px",
            background: "var(--bg-2)", border: "1px solid var(--border)", borderRadius: "var(--radius-md)" }}>
            <span style={{ flex: 1, fontSize: "13px" }}>{m.t}</span>
            <ProvenanceBadge origin={m.prov} ring={m.ring} size="sm" />
            <Button variant="ghost" size="sm" icon={<Ico n="x" s={13} />} onClick={() => revoke(i)} title="Masque cette entrée dans cet affichage ; elle revient au rechargement (aucune révocation côté persona)">Masquer</Button>
          </div>
        ))}
        {!err && mem === null && <div style={{ padding: "30px", textAlign: "center", color: "var(--text-dim)", fontSize: "13px" }}>Lecture de la mémoire…</div>}
        {!err && mem !== null && mem.length === 0 && <div style={{ padding: "30px", textAlign: "center", color: "var(--text-dim)", fontSize: "13px" }}>Mémoire vide — Nokido repart de zéro.</div>}
      </div>
    </div>
  );
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
const CLASSES_SOUV = [
  ["local", "Local", "var(--prov-local)"],
  ["free", "Cloud gratuit", "var(--prov-hybrid)"],
  ["subscription_quota", "Quota d'abonnement", "var(--yellow)"],
  ["paid_api", "API payante", "var(--prov-remote)"],
  ["indetermine", "Non classé", "var(--text-dim)"],
];

function MesureSouverainete({ cible }) {
  const [donnees, setDonnees] = React.useState(null);
  const [err, setErr] = React.useState(null);
  const [fen, setFen] = React.useState("7j");
  React.useEffect(() => {
    fetch("/api/souverainete", { credentials: "same-origin" })
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error("HTTP " + r.status))))
      .then(setDonnees)
      .catch((e) => setErr(String((e && e.message) || e)));
  }, []);
  const m = donnees && donnees.fenetres ? donnees.fenetres[fen] : null;
  const mesure = m ? m.mesure : null;
  const reel = m && m.part_locale_pct !== null && m.part_locale_pct !== undefined ? m.part_locale_pct : null;
  const MONO = "var(--font-mono)";
  return (
    <Card>
      <div style={{ display: "flex", alignItems: "center", gap: "8px", marginBottom: "10px" }}>
        <Ico n="gauge" s={16} />
        <span style={{ fontWeight: 700, fontSize: "13px" }}>Souveraineté réelle</span>
        <select value={fen} {...{ ["on" + "Change"]: (e) => setFen(e.target.value) }}
          style={{ marginLeft: "auto", background: "var(--bg-2)", color: "var(--text-secondary)",
            border: "1px solid var(--border)", borderRadius: "var(--radius-sm)",
            fontSize: "11px", padding: "2px 6px", fontFamily: MONO }}>
          {FENETRES_SOUV.map(([k, lib]) => <option key={k} value={k}>{lib}</option>)}
        </select>
      </div>
      <ErrBanner msg={err} />
      {/* Trois etats, jamais deux : « je n'ai pas pu mesurer » ne s'affiche pas 0 %. */}
      {!err && donnees === null && (
        <div style={{ padding: "18px", textAlign: "center", color: "var(--text-dim)", fontSize: "12px" }}>Mesure du journal d'usage…</div>
      )}
      {mesure === "INCONNU" && (
        <div style={{ fontSize: "12px", color: "var(--yellow)", lineHeight: 1.5 }}>
          Mesure indisponible — {m.raison || "journal d'usage illisible"}. Ce n'est pas « 0 % local » :
          Nokido n'a pas pu lire la source.
        </div>
      )}
      {mesure === "RIEN_A_MESURER" && (
        <div style={{ fontSize: "12px", color: "var(--text-dim)", lineHeight: 1.5 }}>
          Aucun appel enregistré sur cette fenêtre — rien à mesurer (ce n'est pas 0 % de local).
        </div>
      )}
      {mesure === "OK" && (
        <div>
          <div style={{ display: "flex", alignItems: "baseline", gap: "10px", marginBottom: "8px" }}>
            <span style={{ fontSize: "30px", fontWeight: 700, color: "var(--prov-local)", fontFamily: MONO }}>{reel}%</span>
            <span style={{ fontSize: "12px", color: "var(--text-secondary)" }}>des appels servis en local</span>
          </div>
          <SovereigntyGauge local={reel} label={null} showLegend={false} height={8} />
          <div style={{ display: "flex", flexDirection: "column", gap: "5px", margin: "12px 0 0" }}>
            {CLASSES_SOUV.map(([k, lib, coul]) => {
              const c = (m.classes || {})[k];
              if (!c || !c.appels) return null;
              return (
                <div key={k} style={{ display: "flex", alignItems: "center", gap: "8px", fontSize: "11.5px" }}>
                  <span style={{ width: "9px", height: "9px", borderRadius: "2px", background: coul, flexShrink: 0 }} />
                  <span style={{ color: "var(--text-secondary)", flex: 1 }}>{lib}</span>
                  <span style={{ color: "var(--text-dim)", fontFamily: MONO }}>{c.appels}</span>
                  <span style={{ minWidth: "44px", textAlign: "right", color: "var(--text-primary)", fontFamily: MONO }}>{c.pct}%</span>
                </div>
              );
            })}
          </div>
          {/* Le denominateur est TOUJOURS dit : un pourcentage sans son assise ne se juge pas. */}
          <div style={{ marginTop: "10px", paddingTop: "9px", borderTop: "1px solid var(--border-subtle)",
            fontSize: "11px", color: "var(--text-dim)", fontFamily: MONO }}>
            sur {m.denominateur} appels · {m.indetermine_pct}% non classés · mesuré en {m.duree_ms} ms
          </div>
          {/* L'ECART cible ↔ réel : c'est LUI l'information, pas l'un des deux chiffres seul. */}
          <div style={{ marginTop: "9px", padding: "8px 11px", borderRadius: "var(--radius-sm)",
            background: "var(--bg-2)", fontSize: "11.5px", color: "var(--text-secondary)", lineHeight: 1.5 }}>
            Cible du curseur <b style={{ fontFamily: MONO, color: "var(--text-primary)" }}>{cible}%</b> ·
            réel <b style={{ fontFamily: MONO, color: "var(--prov-local)" }}>{reel}%</b> ·
            écart <b style={{ fontFamily: MONO, color: Math.abs(cible - reel) > 20 ? "var(--red)" : "var(--text-primary)" }}>
              {(reel - cible > 0 ? "+" : "") + Math.round(reel - cible)} pts</b>
            {m.indetermine_pct > 10 && " — part non classée élevée, le réel est une borne basse."}
          </div>
        </div>
      )}
    </Card>
  );
}

/* Paliers NOMMES — « le curseur devrait proposer plus de réglages » (owner 2026-09-18).
   Un nombre nu a faire glisser ne dit pas ce qu'il produit ; chaque palier annonce son
   effet sur le routage. */
const PALIERS_SOUV = [
  [100, "Tout local", "aucun appel ne sort, quitte à être plus lent"],
  [75, "Local d'abord", "cloud seulement si le local ne suit pas"],
  [50, "Équilibre", "local et cloud selon la tâche"],
  [25, "Vitesse", "cloud par défaut, local en repli"],
  [0, "Cloud", "aucune contrainte de localité"],
];

function PaliersSouverainete({ local, setLocal }) {
  return (
    <div style={{ display: "flex", flexWrap: "wrap", gap: "6px", marginTop: "11px" }}>
      {PALIERS_SOUV.map(([v, nom, desc]) => (
        <button key={v} type="button" title={desc}
          {...{ ["on" + "Click"]: () => setLocal(v) }}
          style={{ cursor: "pointer", fontSize: "11px", padding: "4px 9px",
            borderRadius: "var(--radius-sm)", fontFamily: "var(--font-mono)",
            border: "1px solid " + (local === v ? "var(--prov-local)" : "var(--border)"),
            background: local === v ? "var(--prov-local-tint)" : "var(--bg-2)",
            color: local === v ? "var(--prov-local)" : "var(--text-secondary)" }}>
          {nom}
        </button>
      ))}
    </div>
  );
}
function ViewSouverainete({ local, setLocal }) {
  const [log, setLog] = React.useState(null);
  const [err, setErr] = React.useState(null);
  React.useEffect(() => {
    fetch("/api/hub/provenance", { credentials: "same-origin" })
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error("HTTP " + r.status))))
      .then((d) => setLog(Array.isArray(d) ? d : []))
      .catch((e) => setErr(String((e && e.message) || e)));
  }, []);
  return (
    <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "18px", maxWidth: "900px", alignItems: "start" }}>
      <div style={{ display: "flex", flexDirection: "column", gap: "16px" }}>
        {/* Le REEL d'abord, la CIBLE ensuite : l'ordre dit lequel des deux est une mesure. */}
        <MesureSouverainete cible={local} />
        <div style={{ fontSize: "11px", textTransform: "uppercase", letterSpacing: "0.6px",
          color: "var(--text-dim)", marginTop: "2px" }}>Cible — oriente la prochaine requête</div>
        <PowerSlider value={local} onChange={setLocal} />
        <PaliersSouverainete local={local} setLocal={setLocal} />
        <div style={{ fontSize: "11px", color: "var(--text-dim)", lineHeight: 1.5, marginTop: "-6px" }}>
          Ce réglage est une <b>intention de routage</b>, pas un constat : le pourcentage
          réellement atteint est mesuré plus haut, sur les appels effectués.
        </div>
        <BasculeTask local={local} />
        <Card>
          <div style={{ fontSize: "12px", color: "var(--text-secondary)", lineHeight: 1.6 }}>
            La cascade : <b style={{ color: "var(--prov-local)" }}>NPU → iGPU → Ollama/llama.cpp local</b> → <b style={{ color: "var(--prov-remote)" }}>cloud</b> en dernier recours.
            Plus tu alloues de puissance, plus Nokido reste local tout en restant performant.
          </div>
        </Card>
      </div>
      <Card>
        <div style={{ display: "flex", alignItems: "center", gap: "8px", marginBottom: "12px" }}>
          <Ico n="receipt-text" s={16} /><span style={{ fontWeight: 700, fontSize: "13px" }}>Journal de provenance</span>
        </div>
        <ErrBanner msg={err} />
        <div style={{ display: "flex", flexDirection: "column", gap: "9px" }}>
          {(log || []).map((l, i) => (
            <div key={i} style={{ display: "flex", alignItems: "center", gap: "8px", fontFamily: "var(--font-mono)", fontSize: "11px" }}>
              <span style={{ color: "var(--text-dim)" }}>{l.ts}</span>
              <span style={{ color: "var(--text-secondary)", minWidth: "52px" }}>{l.act}</span>
              <ProvenanceBadge origin={l.prov} ring={l.ring} size="sm" detail={l.model} style={{ marginLeft: "auto" }} />
            </div>
          ))}
          {!err && log === null && <div style={{ padding: "22px", textAlign: "center", color: "var(--text-dim)", fontSize: "12px" }}>Lecture du journal…</div>}
          {!err && log !== null && log.length === 0 && <div style={{ padding: "22px", textAlign: "center", color: "var(--text-dim)", fontSize: "12px" }}>Aucune décision enregistrée pour l'instant.</div>}
        </div>
      </Card>
    </div>
  );
}

/* Bascule local ↔ distant sur une tâche réelle, pilotée par le curseur */
function BasculeTask({ local }) {
  const target = local >= 60 ? "local" : local >= 30 ? "hybrid" : "remote";
  const cfg = {
    local:  { color: "var(--prov-local)",  tint: "var(--prov-local-tint)",  where: "Sur ta machine (Ollama)", lat: "0,6 s", conf: "Maximale", cost: "0 €" },
    hybrid: { color: "var(--prov-hybrid)", tint: "var(--prov-hybrid-tint)", where: "Local + cloud (anonymisé)", lat: "0,9 s", conf: "Élevée", cost: "~0,01 €" },
    remote: { color: "var(--prov-remote)", tint: "var(--prov-remote-tint)", where: "Cloud (Groq)", lat: "0,3 s", conf: "Réduite", cost: "~0,04 €" },
  }[target];
  const metric = (l, v) => (
    <div><div style={{ fontSize: "10px", color: "var(--text-dim)", textTransform: "uppercase", letterSpacing: "0.4px" }}>{l}</div>
      <div style={{ fontFamily: "var(--font-mono)", fontSize: "12.5px", fontWeight: 700 }}>{v}</div></div>
  );
  return (
    <Card style={{ borderColor: cfg.color }}>
      <div style={{ display: "flex", alignItems: "center", gap: "8px", marginBottom: "10px" }}>
        <Ico n="git-compare-arrows" s={16} />
        <span style={{ fontWeight: 700, fontSize: "13px" }}>Bascule en direct</span>
        <ProvenanceBadge origin={target} size="sm" style={{ marginLeft: "auto" }} />
      </div>
      <div style={{ fontSize: "12.5px", color: "var(--text-secondary)", marginBottom: "12px" }}>
        Effet du curseur sur le routage de <b style={{ color: "var(--text-primary)" }}>la prochaine requête</b>
      </div>
      <div style={{ padding: "10px 12px", borderRadius: "var(--radius-sm)", background: cfg.tint, marginBottom: "12px",
        display: "flex", alignItems: "center", gap: "8px", fontSize: "12px", color: cfg.color, fontWeight: 600 }}>
        <Ico n={target === "local" ? "house" : target === "hybrid" ? "git-fork" : "cloud"} s={15} />{cfg.where}
      </div>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(3,1fr)", gap: "10px", marginBottom: "10px" }}>
        {metric("Confidentialité", cfg.conf)}{metric("Latence", cfg.lat)}{metric("Coût", cfg.cost)}
      </div>
      {target !== "local" && (
        <div style={{ display: "flex", gap: "8px", fontSize: "11px", color: "var(--text-dim)", fontFamily: "var(--font-mono)", paddingTop: "10px", borderTop: "1px solid var(--border-subtle)" }}>
          <Ico n="shield-alert" s={14} />Cloud coupé → bascule locale annoncée, sans perte.
        </div>
      )}
    </Card>
  );
}

/* ---------------- Fédération (Exposer son hub d'IA) ---------------- */
function ViewFederation() {
  const [nodes, setNodes] = React.useState(null);
  const [err, setErr] = React.useState(null);
  React.useEffect(() => {
    fetch("/api/hub/federation", { credentials: "same-origin" })
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error("HTTP " + r.status))))
      .then((d) => setNodes(Array.isArray(d) ? d : []))
      .catch((e) => setErr(String((e && e.message) || e)));
  }, []);
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: "18px", maxWidth: "820px" }}>
      <Card style={{ background: "var(--bg-1)", borderColor: "var(--prov-remote)" }}>
        <div style={{ display: "flex", alignItems: "center", gap: "12px" }}>
          <span style={{ display: "inline-flex", alignItems: "center", justifyContent: "center", width: "40px", height: "40px",
            borderRadius: "var(--radius-sm)", background: "var(--tint-purple)", color: "var(--purple)" }}><Ico n="share-2" s={20} /></span>
          <div style={{ flex: 1 }}>
            <div style={{ fontWeight: 700, fontSize: "15px" }}>Clients &amp; agents gouvernés</div>
            <div style={{ fontSize: "12px", color: "var(--text-dim)" }}>Registre d'intégrité live (RBAC) : chaque agent/client a un anneau (ring) et une zone. Données réelles, zéro nœud inventé.</div>
          </div>
        </div>
      </Card>

      {/* Garde-fous réels (ring × zone) */}
      <div style={{ display: "grid", gridTemplateColumns: "repeat(3,1fr)", gap: "12px" }}>
        {[["eye-off", "Anonymisé", "Aucune intention brute ne sort"], ["scan-line", "Périmètre limité", "Ring × zone par agent"], ["undo-2", "Révocable", "Désactivable à tout moment"]].map(([ic, t, d]) => (
          <div key={t} style={{ padding: "13px 14px", background: "var(--bg-2)", border: "1px solid var(--border)", borderRadius: "var(--radius-md)" }}>
            <span style={{ color: "var(--prov-local)" }}><Ico n={ic} s={17} /></span>
            <div style={{ fontSize: "13px", fontWeight: 600, marginTop: "7px" }}>{t}</div>
            <div style={{ fontSize: "11px", color: "var(--text-dim)", lineHeight: 1.4 }}>{d}</div>
          </div>
        ))}
      </div>

      {/* Agents gouvernés réels */}
      <div>
        {/* `nodes` vaut null tant que /api/hub/federation n'a pas repondu. Cette ligne
            lisait `nodes.length` SANS garde : au TOUT PREMIER rendu, avant meme le
            fetch, elle levait « Cannot read properties of null » — et une exception
            pendant le rendu d'un composant React ne degrade pas la vue, elle
            l'EMPECHE. C'est pour cela que « Fédération ne marche pas » : la vue ne
            s'est jamais montee une seule fois, quelle que soit la reponse du serveur.
            Le reste du composant traite correctement les trois etats ; seul ce libelle
            les ignorait. Un etat inconnu s'AFFICHE, il ne se lit pas comme un nombre. */}
        <SectionTitle hint={nodes === null ? (err ? "registre illisible" : "lecture…")
                                          : (nodes.length + " agents gouvernés")}>Registre d'intégrité</SectionTitle>
        <ErrBanner msg={err} />
        <div style={{ display: "flex", flexDirection: "column", gap: "8px" }}>
          {(nodes || []).map((n, i) => (
            <div key={i} style={{ display: "flex", alignItems: "center", gap: "12px", padding: "12px 15px",
              background: "var(--bg-2)", border: "1px solid var(--border)", borderRadius: "var(--radius-md)", opacity: n.active ? 1 : 0.5 }}>
              <span style={{ display: "inline-flex", alignItems: "center", justifyContent: "center", width: "30px", height: "30px",
                borderRadius: "50%", background: "var(--bg-4)", color: "var(--text-secondary)", fontFamily: "var(--font-mono)", fontSize: "11px", fontWeight: 700 }}>{(n.name || "?")[0].toUpperCase()}</span>
              <div style={{ flex: 1, minWidth: 0 }}>
                <div style={{ fontSize: "13px", fontWeight: 600, display: "flex", alignItems: "center", gap: "7px" }}>
                  {n.name}
                  <span style={{ fontFamily: "var(--font-mono)", fontSize: "9px", color: "var(--text-dim)",
                    border: "1px solid var(--border)", borderRadius: "3px", padding: "0 4px" }}>{n.type || "—"}</span>
                </div>
                <div style={{ fontSize: "11px", color: "var(--text-dim)", fontFamily: "var(--font-mono)" }}>zone : {n.scope} · ring {n.ring_level}{n.active ? "" : " · inactif"}</div>
              </div>
              <ProvenanceBadge origin={n.prov} ring={n.ring} size="sm" />
            </div>
          ))}
          {!err && nodes === null && <div style={{ padding: "28px", textAlign: "center", color: "var(--text-dim)", fontSize: "13px" }}>Lecture du registre…</div>}
          {!err && nodes !== null && nodes.length === 0 && <div style={{ padding: "28px", textAlign: "center", color: "var(--text-dim)", fontSize: "13px" }}>Registre vide — aucun client fédéré déclaré.</div>}
        </div>
      </div>
    </div>
  );
}

Object.assign(window, { ViewAccueil, ViewCap, ViewMaison, ViewPersona, ViewSouverainete, ViewFederation });
