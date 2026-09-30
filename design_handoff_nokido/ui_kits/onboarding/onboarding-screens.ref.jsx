/* Référence design (handoff) — NON compilé. Source canonique : composant du DS Nokido. */
/* Nokido — Onboarding souverain (mobile). Étapes : accueil → niveau local/cloud
   → allocation de puissance → activation des sections → récap. */
const { Button, PowerSlider, SovereigntyGauge, ProvenanceBadge, Badge } = window.NokidoDesignSystem_bdc2ac;

function OIco({ n, s = 20 }) { return <i data-lucide={n} style={{ width: s, height: s }} />; }

const STEP_COUNT = 5;

function Progress({ step }) {
  return (
    <div style={{ display: "flex", gap: "6px", padding: "0 4px" }}>
      {Array.from({ length: STEP_COUNT }).map((_, i) => (
        <div key={i} style={{
          flex: 1, height: "4px", borderRadius: "var(--radius-pill)",
          background: i <= step ? "var(--purple)" : "var(--bg-3)",
          transition: "background var(--motion-base)",
        }} />
      ))}
    </div>
  );
}

function Screen({ children, footer }) {
  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100%", background: "var(--bg-0)", color: "var(--text-primary)" }}>
      <div style={{ flex: 1, overflowY: "auto", padding: "8px 22px 16px" }}>{children}</div>
      <div style={{ padding: "12px 22px calc(12px + env(safe-area-inset-bottom))", borderTop: "1px solid var(--border-subtle)", background: "var(--bg-1)" }}>{footer}</div>
    </div>
  );
}

function Eyebrow({ children }) {
  return <div style={{ fontFamily: "var(--font-mono)", fontSize: "11px", letterSpacing: "0.5px", color: "var(--purple)", textTransform: "uppercase", marginBottom: "8px" }}>{children}</div>;
}
function Title({ children }) {
  return <h1 style={{ margin: "0 0 10px", fontSize: "26px", fontWeight: 700, lineHeight: 1.2, letterSpacing: "-0.01em" }}>{children}</h1>;
}
function Lede({ children }) {
  return <p style={{ margin: "0 0 18px", fontSize: "14px", color: "var(--text-secondary)", lineHeight: 1.55 }}>{children}</p>;
}

/* 0 — Accueil */
function S0({ onNext }) {
  return (
    <Screen footer={<Button variant="primary" size="lg" style={{ width: "100%" }} onClick={onNext} iconRight={<OIco n="arrow-right" s={16} />}>Commencer</Button>}>
      <div style={{ display: "flex", flexDirection: "column", alignItems: "center", textAlign: "center", paddingTop: "60px" }}>
        <div style={{ width: "78px", height: "78px", borderRadius: "22px", background: "var(--tint-purple)",
          display: "flex", alignItems: "center", justifyContent: "center", fontSize: "40px", color: "var(--purple)",
          boxShadow: "var(--shadow-glow)", marginBottom: "22px" }}>⚡</div>
        <Title>Bienvenue dans Nokido</Title>
        <Lede>Ton hub personnel d'IA et de services. <b style={{ color: "var(--prov-local)" }}>Local d'abord</b> : ton intention reste sur ta machine, sauf autorisation explicite.</Lede>
        <div style={{ display: "flex", flexDirection: "column", gap: "10px", width: "100%", marginTop: "8px" }}>
          {[["shield-check", "Souverain", "Ton calcul, ta machine"], ["git-fork", "Fédéré", "Un nœud parmi 8 milliards"], ["sliders-horizontal", "Composable", "Ton app, tes règles"]].map(([ic, t, d]) => (
            <div key={t} style={{ display: "flex", alignItems: "center", gap: "12px", padding: "12px 14px", background: "var(--bg-2)", border: "1px solid var(--border)", borderRadius: "var(--radius-md)", textAlign: "left" }}>
              <span style={{ display: "inline-flex", alignItems: "center", justifyContent: "center", width: "34px", height: "34px", borderRadius: "var(--radius-sm)", background: "var(--tint-purple)", color: "var(--purple)" }}><OIco n={ic} s={17} /></span>
              <div><div style={{ fontSize: "13px", fontWeight: 600 }}>{t}</div><div style={{ fontSize: "11.5px", color: "var(--text-dim)" }}>{d}</div></div>
            </div>
          ))}
        </div>
      </div>
    </Screen>
  );
}

/* 1 — Niveau local / cloud */
function S1({ onNext, onBack, level, setLevel }) {
  const opts = [
    { id: "local", icon: "house", color: "var(--prov-local)", title: "Tout local", desc: "100 % sur ta machine. Hors-ligne possible. Confidentialité maximale.", tag: "SOUVERAIN" },
    { id: "hybrid", icon: "git-fork", color: "var(--prov-hybrid)", title: "Hybride", desc: "Local par défaut, cloud en renfort pour les tâches lourdes — anonymisé.", tag: "RECOMMANDÉ" },
    { id: "cloud", icon: "cloud", color: "var(--prov-remote)", title: "Cloud d'abord", desc: "Plus de puissance, plus de coût. Externe et réversible à tout moment.", tag: "DISTANT" },
  ];
  return (
    <Screen footer={
      <div style={{ display: "flex", gap: "10px" }}>
        <Button variant="ghost" size="lg" onClick={onBack} icon={<OIco n="arrow-left" s={16} />}>Retour</Button>
        <Button variant="primary" size="lg" style={{ flex: 1 }} onClick={onNext}>Continuer</Button>
      </div>}>
      <Eyebrow>Étape 1 · Souveraineté</Eyebrow>
      <Title>Où vit ton calcul ?</Title>
      <Lede>Tu pourras l'ajuster à tout moment — c'est un curseur, pas un choix définitif.</Lede>
      <div style={{ display: "flex", flexDirection: "column", gap: "11px" }}>
        {opts.map((o) => {
          const on = level === o.id;
          return (
            <button key={o.id} onClick={() => setLevel(o.id)} style={{
              display: "flex", gap: "13px", textAlign: "left", padding: "15px", cursor: "pointer",
              borderRadius: "var(--radius-md)", background: on ? "var(--bg-2)" : "var(--bg-1)",
              border: `1.5px solid ${on ? o.color : "var(--border)"}`,
              boxShadow: on ? `0 0 0 1px ${o.color}, 0 0 18px color-mix(in srgb, ${o.color} 18%, transparent)` : "none",
              fontFamily: "var(--font-sans)", color: "var(--text-primary)", transition: "all var(--motion-base)",
            }}>
              <span style={{ display: "inline-flex", alignItems: "center", justifyContent: "center", width: "42px", height: "42px", flexShrink: 0,
                borderRadius: "var(--radius-sm)", background: `color-mix(in srgb, ${o.color} 16%, transparent)`, color: o.color }}><OIco n={o.icon} s={21} /></span>
              <div style={{ flex: 1 }}>
                <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
                  <span style={{ fontSize: "15px", fontWeight: 700 }}>{o.title}</span>
                  <span style={{ fontFamily: "var(--font-mono)", fontSize: "9px", fontWeight: 700, letterSpacing: "0.3px", color: o.color, border: `1px solid ${o.color}`, borderRadius: "4px", padding: "1px 5px" }}>{o.tag}</span>
                </div>
                <div style={{ fontSize: "12px", color: "var(--text-secondary)", lineHeight: 1.45, marginTop: "4px" }}>{o.desc}</div>
              </div>
              <span style={{ alignSelf: "center", color: on ? o.color : "var(--text-disabled)" }}><OIco n={on ? "check-circle-2" : "circle"} s={20} /></span>
            </button>
          );
        })}
      </div>
    </Screen>
  );
}

/* 2 — Allocation de puissance */
function S2({ onNext, onBack, power, setPower }) {
  return (
    <Screen footer={
      <div style={{ display: "flex", gap: "10px" }}>
        <Button variant="ghost" size="lg" onClick={onBack} icon={<OIco n="arrow-left" s={16} />}>Retour</Button>
        <Button variant="primary" size="lg" style={{ flex: 1 }} onClick={onNext}>Continuer</Button>
      </div>}>
      <Eyebrow>Étape 2 · Puissance</Eyebrow>
      <Title>Puissance allouée</Title>
      <Lede>Plus tu alloues de puissance locale, plus Nokido reste souverain tout en restant rapide. Le compromis se lit en direct.</Lede>
      <PowerSlider value={power} onChange={setPower} />
      <div style={{ marginTop: "16px", padding: "13px 15px", background: "var(--prov-local-tint)", border: "1px solid var(--border-subtle)", borderRadius: "var(--radius-md)", display: "flex", gap: "10px" }}>
        <span style={{ color: "var(--prov-local)" }}><OIco n="info" s={17} /></span>
        <div style={{ fontSize: "12px", color: "var(--text-secondary)", lineHeight: 1.5 }}>
          Cascade : <b style={{ color: "var(--prov-local)" }}>NPU → iGPU → Ollama local</b> → cloud en dernier recours. Ta machine traite {power}% des requêtes.
        </div>
      </div>
    </Screen>
  );
}

/* 3 — Activer les sections */
function S3({ onNext, onBack, enabled, toggle }) {
  const mods = [
    { id: "sante", domain: "sante", icon: "heart-pulse", title: "Santé", note: "local forcé" },
    { id: "domotique", domain: "domotique", icon: "house", title: "Domotique", note: "local-first" },
    { id: "transport", domain: "transport", icon: "route", title: "Transport", note: "temps réel" },
    { id: "finance", domain: "finance", icon: "wallet", title: "Finance", note: "traçable" },
    { id: "creation", domain: "creation", icon: "sparkles", title: "Création", note: "atelier" },
    { id: "dev", domain: "dev", icon: "terminal", title: "Dev", note: "skills & MCP" },
  ];
  const count = mods.filter((m) => enabled[m.id]).length;
  return (
    <Screen footer={
      <div style={{ display: "flex", gap: "10px" }}>
        <Button variant="ghost" size="lg" onClick={onBack} icon={<OIco n="arrow-left" s={16} />}>Retour</Button>
        <Button variant="primary" size="lg" style={{ flex: 1 }} onClick={onNext}>Activer {count} section{count > 1 ? "s" : ""}</Button>
      </div>}>
      <Eyebrow>Étape 3 · Sections</Eyebrow>
      <Title>Compose ton app</Title>
      <Lede>Active tes premières sections. Tu pourras en ajouter, réorganiser ou masquer plus tard.</Lede>
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "10px" }}>
        {mods.map((m) => {
          const on = !!enabled[m.id];
          const accent = `var(--domain-${m.domain})`;
          return (
            <button key={m.id} onClick={() => toggle(m.id)} style={{
              position: "relative", textAlign: "left", padding: "13px", cursor: "pointer",
              borderRadius: "var(--radius-md)", background: on ? "var(--bg-2)" : "var(--bg-1)",
              border: `1px solid ${on ? accent : "var(--border)"}`, fontFamily: "var(--font-sans)",
              color: "var(--text-primary)", overflow: "hidden", transition: "all var(--motion-base)",
            }}>
              <div style={{ position: "absolute", left: 0, top: 0, bottom: 0, width: "3px", background: on ? accent : "transparent" }} />
              <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
                <span style={{ display: "inline-flex", alignItems: "center", justifyContent: "center", width: "34px", height: "34px",
                  borderRadius: "var(--radius-sm)", background: `color-mix(in srgb, ${accent} 16%, transparent)`, color: accent }}><OIco n={m.icon} s={17} /></span>
                <span style={{ color: on ? accent : "var(--text-disabled)" }}><OIco n={on ? "check-circle-2" : "circle"} s={18} /></span>
              </div>
              <div style={{ fontSize: "13.5px", fontWeight: 700, marginTop: "9px" }}>{m.title}</div>
              <div style={{ fontFamily: "var(--font-mono)", fontSize: "10px", color: "var(--text-dim)" }}>{m.note}</div>
            </button>
          );
        })}
      </div>
    </Screen>
  );
}

/* 4 — Récap */
function S4({ onBack, onDone, level, power, enabled }) {
  const labels = { local: "Tout local", hybrid: "Hybride", cloud: "Cloud d'abord" };
  const origin = level === "cloud" ? "remote" : level === "hybrid" ? "hybrid" : "local";
  const count = Object.values(enabled).filter(Boolean).length;
  return (
    <Screen footer={
      <div style={{ display: "flex", gap: "10px" }}>
        <Button variant="ghost" size="lg" onClick={onBack} icon={<OIco n="arrow-left" s={16} />}>Retour</Button>
        <Button variant="success" size="lg" style={{ flex: 1 }} onClick={onDone} iconRight={<OIco n="arrow-right" s={16} />}>Entrer dans le hub</Button>
      </div>}>
      <div style={{ display: "flex", flexDirection: "column", alignItems: "center", textAlign: "center", paddingTop: "20px" }}>
        <div style={{ width: "64px", height: "64px", borderRadius: "50%", background: "var(--tint-green)", color: "var(--prov-local)",
          display: "flex", alignItems: "center", justifyContent: "center", marginBottom: "16px", boxShadow: "var(--prov-local-glow)" }}><OIco n="check" s={30} /></div>
        <Title>Ton nœud est prêt</Title>
        <Lede>Voici ta configuration souveraine. Tout reste modifiable à tout moment.</Lede>
      </div>
      <div style={{ display: "flex", flexDirection: "column", gap: "10px" }}>
        <Row label="Niveau" value={labels[level]} right={<ProvenanceBadge origin={origin} size="sm" />} />
        <Row label="Puissance locale" value={`${power}%`} right={<SovereigntyGauge local={power} label={null} showLegend={false} height={6} style={{ width: "90px" }} />} />
        <Row label="Sections actives" value={`${count} activée${count > 1 ? "s" : ""}`} right={<Badge color="purple" mono>{count}</Badge>} />
      </div>
    </Screen>
  );
}
function Row({ label, value, right }) {
  return (
    <div style={{ display: "flex", alignItems: "center", gap: "12px", padding: "13px 15px", background: "var(--bg-2)", border: "1px solid var(--border)", borderRadius: "var(--radius-md)" }}>
      <div style={{ flex: 1 }}>
        <div style={{ fontFamily: "var(--font-mono)", fontSize: "10px", textTransform: "uppercase", letterSpacing: "0.5px", color: "var(--text-dim)" }}>{label}</div>
        <div style={{ fontSize: "14px", fontWeight: 600, marginTop: "2px" }}>{value}</div>
      </div>
      {right}
    </div>
  );
}

Object.assign(window, { OnbProgress: Progress, OnbS0: S0, OnbS1: S1, OnbS2: S2, OnbS3: S3, OnbS4: S4 });
