/* Référence design (handoff) — NON compilé. Source canonique : composant du DS Nokido. */
/* Nokido Web Hub — Setup souverain & Rings (centralisés dans le hub).
   Scan machine · compromis souveraineté · profils de conf · tiers DB · modes de lancement
   · placement des agents sur les 11 rings. */
const { Card, Badge, StatusPill, Button, ProvenanceBadge, PowerSlider } = window.NokidoDesignSystem_bdc2ac;
const UIco = window.WIco || (({ n, s = 18 }) => <i data-lucide={n} style={{ width: s, height: s }} />);
const uprov = () => (window.__WH_TW ? window.__WH_TW.provenance !== false : true);

/* Helpers rings (locaux — les statics du composant bundlé ne sont pas garantis) */
const RING_DESC = ["Lois absolues", "Core Nokido", "TRUSTED humain", "Agents validés", "Agents externes", "RAG web", "Outils CI/CD", "SSH / réseau", "Monitoring", "Système hôte", "Corrections de Cap"];
function ringColor(i) {
  const stops = [[74,194,139],[45,212,191],[59,178,208],[119,74,255]];
  const t = i / 10, seg = t * (stops.length - 1), k = Math.min(stops.length - 2, Math.floor(seg)), f = seg - k;
  const c = stops[k].map((v, j) => Math.round(v + (stops[k + 1][j] - v) * f));
  return `rgb(${c[0]}, ${c[1]}, ${c[2]})`;
}

/* Dial des 11 rings (inline — miroir du composant DS RingMeter) */
function RingDial({ states = {}, selected = null, onSelect = null, size = 320 }) {
  const cx = size / 2, cy = size / 2, ringW = (size / 2 - 16) / 11;
  const radius = (i) => 16 + (i + 0.5) * ringW;
  const override = { alert: "var(--yellow)", block: "var(--red)", inactive: "var(--bg-4)" };
  return (
    <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`} style={{ flexShrink: 0 }}>
      <circle cx={cx} cy={cy} r={ringW * 0.6} fill={ringColor(0)} opacity={0.9} />
      {Array.from({ length: 11 }).map((_, i) => {
        const st = states[i] || "ok";
        const base = st === "ok" ? ringColor(i) : override[st];
        const on = selected === i;
        return (
          <circle key={i} cx={cx} cy={cy} r={radius(i)} fill="none" stroke={base}
            strokeWidth={on ? ringW * 0.95 : ringW * 0.7}
            opacity={st === "inactive" ? 0.4 : on ? 1 : 0.82}
            onClick={onSelect ? () => onSelect(i) : undefined}
            style={{ cursor: onSelect ? "pointer" : "default", filter: on ? `drop-shadow(0 0 6px ${base})` : "none",
              transition: "stroke-width var(--motion-base), opacity var(--motion-base)",
              animation: st === "alert" ? "laforge-pulse var(--pulse-period) infinite" : "none" }} />
        );
      })}
      <text x={cx} y={cy + 4} textAnchor="middle" fontFamily="var(--font-mono)" fontSize={size * 0.05} fontWeight="700" fill="var(--bg-0)">R0</text>
    </svg>
  );
}

function SubTitle({ children, hint }) {
  return (
    <div style={{ display: "flex", alignItems: "baseline", gap: "10px", margin: "0 0 12px" }}>
      <h2 style={{ margin: 0, fontSize: "13px", fontWeight: 700, textTransform: "uppercase", letterSpacing: "0.6px", color: "var(--text-secondary)" }}>{children}</h2>
      {hint && <span style={{ fontFamily: "var(--font-mono)", fontSize: "11px", color: "var(--text-dim)" }}>{hint}</span>}
    </div>
  );
}

/* ===== Profils de conf : presets de souveraineté ===== */
const PROFILES = {
  full_local:  { label: "Full local", icon: "house", power: 100, color: "var(--prov-local)", desc: "Tout sur la machine. Hors-ligne. Aucun connecteur cloud.", maxRing: 4 },
  souverain:   { label: "Local souverain + cloud", icon: "shield-check", power: 78, color: "var(--prov-local)", desc: "Local par défaut, cloud anonymisé au-delà d'un seuil.", maxRing: 6 },
  hybride:     { label: "Hybride", icon: "git-fork", power: 55, color: "var(--prov-hybrid)", desc: "Équilibre puissance/souveraineté, connecteurs branchés.", maxRing: 8 },
  dev:         { label: "Dev / paramétrable", icon: "terminal", power: 40, color: "var(--prov-remote)", desc: "Tout ouvert, rings configurables manuellement.", maxRing: 10 },
};

/* ===== Scan machine ===== */
const HW = [
  { label: "NPU", detail: "AMD XDNA · 16 TOPS", icon: "cpu", ok: true, note: "embeddings + petits LLM" },
  { label: "iGPU", detail: "Radeon 780M · DML", icon: "gpu", ok: true, note: "inférence accélérée" },
  { label: "RAM", detail: "32 Go", icon: "memory-stick", ok: true, note: "LLM ≤ 14B en local" },
  { label: "Disque", detail: "SSD 1 To · 420 Go libres", icon: "hard-drive", ok: true, note: "RAG + modèles" },
  { label: "Réseau", detail: "Connecté", icon: "wifi", ok: true, note: "cloud disponible (optionnel)" },
];
const LOCAL_MODELS = [
  { name: "mistral:7b", tier: "local", ok: true }, { name: "qwen2.5:14b", tier: "local", ok: true },
  { name: "bge-m3 (embed)", tier: "local", ok: true }, { name: "llama:70b", tier: "cloud", ok: false },
];

/* ===== Tiers DB vectorielle ===== */
const DB_TIERS = [
  { tier: "AMI World", dims: "4096d", kind: "multivectoriel", icon: "globe", color: "var(--purple)", desc: "Mode monde multivectoriel — contexte riche, raisonnement long." },
  { tier: "Code · hot", dims: "1024d", kind: "FAISS", icon: "code", color: "var(--blue)", desc: "Tier chaud : code & artefacts récents, recherche FAISS rapide." },
  { tier: "RAG · cold", dims: "FTS", kind: "rerank RRF", icon: "snowflake", color: "var(--cyan)", desc: "Tier froid : full-text search + reranking (RRF) sur l'archive." },
];

/* ===== Modes de lancement ===== */
const LAUNCH = [
  { id: "tui", label: "TUI · PTY", icon: "square-terminal", desc: "Terminal interactif avec pseudo-TTY", prov: "local" },
  { id: "chat", label: "Chat LLM connecté", icon: "message-square", desc: "Dialogue multi-fournisseurs", prov: "hybrid" },
  { id: "ia_local", label: "Nokido IA locale", icon: "cpu", desc: "Agent souverain, 100% machine", prov: "local" },
  { id: "base", label: "Interface de base", icon: "layout-grid", desc: "Le hub complet (recommandé)", prov: "local" },
];

function SetupView() {
  const [profile, setProfile] = React.useState("souverain");
  const [power, setPower] = React.useState(PROFILES.souverain.power);
  const [launch, setLaunch] = React.useState("base");
  const pick = (k) => { setProfile(k); setPower(PROFILES[k].power); };

  return (
    <div style={{ maxWidth: "1080px", margin: "0 auto", display: "flex", flexDirection: "column", gap: "26px" }}>
      <div>
        <SubTitle hint="ce qui peut tourner en local vis-à-vis des modules installés">1 · Scan machine</SubTitle>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(190px, 1fr))", gap: "10px" }}>
          {HW.map((h) => (
            <Card key={h.label}>
              <div style={{ display: "flex", alignItems: "center", gap: "9px" }}>
                <span style={{ display: "inline-flex", alignItems: "center", justifyContent: "center", width: "34px", height: "34px", borderRadius: "var(--radius-sm)",
                  background: "var(--tint-green)", color: "var(--prov-local)" }}><UIco n={h.icon} s={17} /></span>
                <div style={{ flex: 1 }}>
                  <div style={{ fontSize: "13px", fontWeight: 700 }}>{h.label}</div>
                  <div style={{ fontFamily: "var(--font-mono)", fontSize: "10px", color: "var(--text-dim)" }}>{h.detail}</div>
                </div>
                <UIco n="check" s={15} />
              </div>
              <div style={{ fontSize: "11px", color: "var(--text-secondary)", marginTop: "8px" }}>{h.note}</div>
            </Card>
          ))}
        </div>
        <div style={{ display: "flex", flexWrap: "wrap", gap: "7px", marginTop: "10px" }}>
          {LOCAL_MODELS.map((m) => (
            <span key={m.name} style={{ display: "inline-flex", alignItems: "center", gap: "6px", padding: "4px 10px", borderRadius: "var(--radius-pill)",
              fontFamily: "var(--font-mono)", fontSize: "11px", border: `1px solid ${m.ok ? "var(--prov-local)" : "var(--border)"}`,
              color: m.ok ? "var(--prov-local)" : "var(--text-dim)", background: m.ok ? "var(--prov-local-tint)" : "transparent" }}>
              <UIco n={m.ok ? "check" : "cloud"} s={12} />{m.name}
            </span>
          ))}
        </div>
      </div>

      <div>
        <SubTitle hint="confidentialité ↔ puissance ↔ cloud">2 · Compromis de souveraineté</SubTitle>
        <PowerSlider value={power} onChange={setPower} />
      </div>

      <div>
        <SubTitle hint="conf optimisée selon tes critères">3 · Profil de configuration</SubTitle>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(230px, 1fr))", gap: "11px" }}>
          {Object.entries(PROFILES).map(([k, p]) => {
            const on = profile === k;
            return (
              <button key={k} onClick={() => pick(k)} style={{ textAlign: "left", padding: "14px", borderRadius: "var(--radius-md)", cursor: "pointer",
                background: on ? "var(--bg-2)" : "var(--bg-1)", border: `1.5px solid ${on ? p.color : "var(--border)"}`,
                boxShadow: on ? `0 0 0 1px ${p.color}, 0 0 16px color-mix(in srgb, ${p.color} 16%, transparent)` : "none",
                color: "var(--text-primary)", fontFamily: "var(--font-sans)", transition: "all var(--motion-base)" }}>
                <div style={{ display: "flex", alignItems: "center", gap: "9px", marginBottom: "7px" }}>
                  <span style={{ color: p.color }}><UIco n={p.icon} s={18} /></span>
                  <span style={{ fontSize: "14px", fontWeight: 700 }}>{p.label}</span>
                  <span style={{ marginLeft: "auto", color: on ? p.color : "var(--text-disabled)" }}><UIco n={on ? "check-circle-2" : "circle"} s={17} /></span>
                </div>
                <div style={{ fontSize: "11.5px", color: "var(--text-secondary)", lineHeight: 1.45 }}>{p.desc}</div>
                <div style={{ marginTop: "9px", fontFamily: "var(--font-mono)", fontSize: "10px", color: "var(--text-dim)" }}>jusqu'au ring {p.maxRing} · {p.power}% local</div>
              </button>
            );
          })}
        </div>
      </div>

      <div>
        <SubTitle hint="deux modèles d'embeddings + tier froid">4 · DB vectorielle multi-tiers</SubTitle>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(260px, 1fr))", gap: "11px" }}>
          {DB_TIERS.map((d) => (
            <Card key={d.tier}>
              <div style={{ display: "flex", alignItems: "center", gap: "9px", marginBottom: "8px" }}>
                <span style={{ display: "inline-flex", alignItems: "center", justifyContent: "center", width: "34px", height: "34px", borderRadius: "var(--radius-sm)",
                  background: `color-mix(in srgb, ${d.color} 16%, transparent)`, color: d.color }}><UIco n={d.icon} s={17} /></span>
                <div>
                  <div style={{ fontSize: "13.5px", fontWeight: 700 }}>{d.tier}</div>
                  <div style={{ fontFamily: "var(--font-mono)", fontSize: "10px", color: d.color }}>{d.dims} · {d.kind}</div>
                </div>
              </div>
              <div style={{ fontSize: "11.5px", color: "var(--text-secondary)", lineHeight: 1.45 }}>{d.desc}</div>
            </Card>
          ))}
        </div>
      </div>

      <div>
        <SubTitle hint="selon le contrôle souhaité">5 · Mode de lancement</SubTitle>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))", gap: "11px" }}>
          {LAUNCH.map((l) => {
            const on = launch === l.id;
            return (
              <button key={l.id} onClick={() => setLaunch(l.id)} style={{ textAlign: "left", padding: "13px", borderRadius: "var(--radius-md)", cursor: "pointer",
                background: on ? "var(--bg-3)" : "var(--bg-2)", border: `1px solid ${on ? "var(--purple)" : "var(--border)"}`, color: "var(--text-primary)", fontFamily: "var(--font-sans)" }}>
                <div style={{ display: "flex", alignItems: "center", gap: "9px" }}>
                  <span style={{ color: "var(--purple)" }}><UIco n={l.icon} s={17} /></span>
                  <span style={{ fontSize: "13.5px", fontWeight: 700 }}>{l.label}</span>
                </div>
                <div style={{ fontSize: "11px", color: "var(--text-secondary)", margin: "6px 0 8px" }}>{l.desc}</div>
                {uprov() && <ProvenanceBadge origin={l.prov} size="sm" />}
              </button>
            );
          })}
        </div>
      </div>

      <div style={{ display: "flex", gap: "10px", paddingTop: "6px", borderTop: "1px solid var(--border-subtle)" }}>
        <Button variant="primary" size="lg" icon={<UIco n="rocket" s={16} />}>Lancer Nokido</Button>
        <Button variant="ghost" size="lg" icon={<UIco n="share-2" s={15} />} onClick={() => window.__WH_GO && window.__WH_GO("rings")}>Voir le placement sur les rings</Button>
      </div>
    </div>
  );
}

/* ===== Rings : placement des agents ===== */
const AGENT_RING = [
  { ring: 0, agent: "Lois fondatrices", implies: "Immuables. Aucun agent ne peut les modifier.", prov: "local" },
  { ring: 1, agent: "Cœur Nokido", implies: "Orchestrateur souverain. Confiance maximale.", prov: "local" },
  { ring: 2, agent: "Toi (humain TRUSTED)", implies: "Validation finale, révocation, kill switch.", prov: "local" },
  { ring: 3, agent: "Agents validés", implies: "Exécutent sans confirmation dans leur périmètre.", prov: "local" },
  { ring: 4, agent: "Agents externes", implies: "Sandbox, confirmation requise pour agir.", prov: "hybrid" },
  { ring: 5, agent: "RAG web", implies: "Lecture seule, sources distantes anonymisées.", prov: "hybrid" },
  { ring: 8, agent: "Monitoring", implies: "Observe, n'agit pas. Lecture des organes.", prov: "local" },
  { ring: 9, agent: "Système hôte", implies: "Accès OS — le ring le plus surveillé.", prov: "remote" },
];

function RingsView() {
  const [sel, setSel] = React.useState(2);
  const [profile, setProfile] = React.useState("souverain");
  const maxRing = PROFILES[profile].maxRing;
  const states = {};
  for (let i = 0; i <= 10; i++) states[i] = i > maxRing ? "inactive" : "ok";
  if (sel === 9) states[9] = "alert";
  const selInfo = AGENT_RING.find((a) => a.ring === sel);

  return (
    <div style={{ maxWidth: "1080px", margin: "0 auto" }}>
      <SubTitle hint="sur quelle couche placer un agent — et ce que ça implique">Placement sur les 11 rings</SubTitle>

      <div style={{ display: "flex", gap: "7px", flexWrap: "wrap", marginBottom: "16px" }}>
        {Object.entries(PROFILES).map(([k, p]) => {
          const on = profile === k;
          return (
            <button key={k} onClick={() => setProfile(k)} style={{ display: "inline-flex", alignItems: "center", gap: "6px", padding: "6px 12px", borderRadius: "var(--radius-pill)",
              cursor: "pointer", fontFamily: "var(--font-sans)", fontSize: "12px", fontWeight: 600,
              border: `1px solid ${on ? p.color : "var(--border)"}`, background: on ? "color-mix(in srgb, " + p.color + " 14%, transparent)" : "transparent",
              color: on ? p.color : "var(--text-secondary)" }}>
              <UIco n={p.icon} s={14} />{p.label}
            </button>
          );
        })}
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "minmax(440px, 1fr) 320px", gap: "18px", alignItems: "start" }}>
        <Card style={{ background: "var(--bg-1)", display: "flex", justifyContent: "center" }}>
          <RingDial states={states} selected={sel} onSelect={setSel} size={320} />
        </Card>

        <div style={{ display: "flex", flexDirection: "column", gap: "12px" }}>
          <Card>
            <div style={{ display: "flex", alignItems: "center", gap: "9px", marginBottom: "8px" }}>
              <span style={{ width: "12px", height: "12px", borderRadius: "50%", background: ringColor(sel), boxShadow: `0 0 8px ${ringColor(sel)}` }} />
              <span style={{ fontSize: "15px", fontWeight: 700 }}>Ring {sel}</span>
              {selInfo && uprov() && <ProvenanceBadge origin={selInfo.prov} size="sm" style={{ marginLeft: "auto" }} />}
            </div>
            <div style={{ fontSize: "13.5px", fontWeight: 600, marginBottom: "5px" }}>{selInfo ? selInfo.agent : RING_DESC[sel]}</div>
            <div style={{ fontSize: "12px", color: "var(--text-secondary)", lineHeight: 1.5 }}>
              {selInfo ? selInfo.implies : "Couche disponible — aucun agent placé pour ce profil."}
            </div>
            {sel > maxRing && (
              <div style={{ marginTop: "10px", fontFamily: "var(--font-mono)", fontSize: "10.5px", color: "var(--yellow)", display: "flex", alignItems: "center", gap: "6px" }}>
                <UIco n="lock" s={12} />verrouillé par le profil « {PROFILES[profile].label} »
              </div>
            )}
          </Card>

          <Card>
            <div style={{ fontFamily: "var(--font-mono)", fontSize: "10px", textTransform: "uppercase", letterSpacing: "0.5px", color: "var(--text-dim)", marginBottom: "9px" }}>Agents placés</div>
            <div style={{ display: "flex", flexDirection: "column", gap: "5px" }}>
              {AGENT_RING.map((a) => (
                <button key={a.ring} onClick={() => setSel(a.ring)} style={{ display: "flex", alignItems: "center", gap: "9px", padding: "5px 7px", borderRadius: "var(--radius-sm)",
                  border: "none", cursor: "pointer", background: sel === a.ring ? "var(--bg-3)" : "transparent", textAlign: "left", width: "100%", fontFamily: "var(--font-sans)" }}>
                  <span style={{ fontFamily: "var(--font-mono)", fontSize: "10px", color: "var(--text-dim)", width: "16px", flexShrink: 0 }}>{a.ring}</span>
                  <span style={{ width: "8px", height: "8px", borderRadius: "50%", background: ringColor(a.ring), flexShrink: 0, opacity: a.ring > maxRing ? 0.35 : 1 }} />
                  <span style={{ fontSize: "12px", color: a.ring > maxRing ? "var(--text-dim)" : "var(--text-secondary)" }}>{a.agent}</span>
                </button>
              ))}
            </div>
          </Card>
        </div>
      </div>
    </div>
  );
}

Object.assign(window, { SetupView, RingsView });
