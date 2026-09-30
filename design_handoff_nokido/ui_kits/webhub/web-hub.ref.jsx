/* Référence design (handoff) — NON compilé. Source canonique : composant du DS Nokido. */
/* Nokido — Web Hub modernisé : recréation du portail réel (:7400) avec le DS.
   Portail de services + Chat (ask) + Event Feed (audit), provenance partout. */
const { Card, Badge, StatusPill, Button, ProvenanceBadge, TextInput, Select } = window.NokidoDesignSystem_bdc2ac;
const WPREF = window.NokidoPrefs;

function WIco({ n, s = 18 }) { return <i data-lucide={n} style={{ width: s, height: s }} />; }

/* Tweaks partagés (lus par les vues ci-dessous). Mis à jour par <WebHub t={…}>. */
let TW = { accent: "#774AFF", density: "confort", provenance: true, quicklinks: true, mcpPanel: true, motion: true };
const pad = (comfy, compact) => (TW.density === "compact" ? compact : comfy);

/* Services réels du hub (dashboard.html) */
const SERVICES = [
  { slug: "chat", title: "Chat / Ask", desc: "Dialogue multi-fournisseurs", icon: "message-square", color: "purple", prov: "local", status: "up", target: "/sidebar" },
  { slug: "rag", title: "RAG Dashboard", desc: "Embeddings & recherche locale", icon: "database", color: "green", prov: "local", status: "up", target: "/rag" },
  { slug: "network", title: "Network Graph", desc: "Graphe de connaissances", icon: "share-2", color: "blue", prov: "local", status: "up", target: "/network" },
  { slug: "mcp_lab", title: "MCP Lab", desc: "Outils & serveurs MCP", icon: "blocks", color: "cyan", prov: "hybrid", status: "up", target: "/mcp_lab/" },
  { slug: "swarm", title: "Swarm", desc: "Essaim d'agents", icon: "boxes", color: "orange", prov: "hybrid", status: "up", target: "/swarm" },
  { slug: "debate", title: "LLM Debate", desc: "Débat contradictoire multi-modèles", icon: "messages-square", color: "pink", prov: "remote", status: "up", target: "/llm_debate" },
  { slug: "anatomy", title: "Anatomie Live", desc: "Organes & flux en temps réel", icon: "activity", color: "green", prov: "local", status: "up", target: "/anatomy" },
  { slug: "feed", title: "Event Feed", desc: "Journal d'audit (bus d'événements)", icon: "scroll-text", color: "yellow", prov: "local", status: "up", target: "/forge/feed" },
  { slug: "launcher", title: "Launcher", desc: "Pilotage des modules", icon: "rocket", color: "purple", prov: "local", status: "up", target: "/launcher" },
  { slug: "reports", title: "CTF Reports", desc: "Rapports & traces", icon: "flag", color: "red", prov: "local", status: "up", target: "/reports/", ext: true },
  { slug: "epistemic", title: "Épistémique", desc: "Incertitude & calibration", icon: "brain-circuit", color: "blue", prov: "hybrid", status: "warn", target: "/epistemic" },
  { slug: "setup", title: "Setup souverain", desc: "Scan machine, profils, tiers DB, lancement", icon: "sliders-horizontal", color: "purple", prov: "local", status: "up", target: "/setup" },
  { slug: "rings", title: "Rings", desc: "Placement des agents sur les 11 anneaux", icon: "target", color: "green", prov: "local", status: "up", target: "/rings" },
  { slug: "pipeline", title: "Pipeline souverain", desc: "CI local-first, cloud en fallback", icon: "git-pull-request", color: "green", prov: "local", status: "up", target: "/pipeline" },
  { slug: "recon", title: "Recon", desc: "Reconnaissance (non déployé)", icon: "radar", color: "cyan", prov: "local", coming: true, target: "/recon" },
];

const QUICK = [["Setup souverain", "setup"], ["Rings", "rings"], ["Launcher", "launcher"], ["Pipeline", "pipeline"], ["Swarm", "swarm"], ["LLM Debate", "debate"], ["MCP Lab", "mcp"], ["Network", "network"], ["RAG", "rag"], ["Status JSON", "status"]];
const GO = (v) => { if (window.__WH_GO) window.__WH_GO(v); };

const COLOR_VAR = { purple: "--purple", blue: "--blue", cyan: "--cyan", green: "--green", yellow: "--yellow", orange: "--orange", red: "--red", pink: "--pink" };
const SLUG_VIEW = { chat: "chat", rag: "rag", feed: "feed", launcher: "launcher", reports: "reports", epistemic: "epistemic", pipeline: "pipeline", swarm: "swarm", debate: "debate", network: "network", mcp_lab: "mcp", setup: "setup", rings: "rings" };

/* ---------------- Portail ---------------- */
function Portail() {
  return (
    <div style={{ maxWidth: "1180px", margin: "0 auto" }}>
      <div style={{ display: "flex", gap: "8px", flexWrap: "wrap", marginBottom: "18px", display: TW.quicklinks ? "flex" : "none" }}>
        {QUICK.map(([q, v]) => (
          <button key={q} onClick={() => GO(v)} style={{ padding: "6px 12px", border: "1px solid var(--border)", background: "transparent", cursor: "pointer",
            borderRadius: "var(--radius-sm)", color: "var(--text-secondary)", fontSize: "12.5px", fontFamily: "var(--font-sans)", transition: "all var(--motion-fast)" }}
            onMouseEnter={(e) => { e.currentTarget.style.borderColor = "var(--purple)"; e.currentTarget.style.color = "var(--purple)"; }}
            onMouseLeave={(e) => { e.currentTarget.style.borderColor = "var(--border)"; e.currentTarget.style.color = "var(--text-secondary)"; }}>{q}</button>
        ))}
      </div>

      <div style={{ display: "grid", gridTemplateColumns: `repeat(auto-fill, minmax(280px, 1fr))`, gap: pad("14px", "9px") }}>
        {SERVICES.map((s) => {
          const cvar = `var(${COLOR_VAR[s.color]})`;
          if (s.coming) {
            return (
              <div key={s.slug} style={{ position: "relative", padding: "18px", background: "var(--bg-1)", border: "1px solid var(--border-subtle)",
                borderRadius: "var(--radius-md)", opacity: 0.6 }}>
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start" }}>
                  <span style={{ display: "inline-flex", alignItems: "center", justifyContent: "center", width: "44px", height: "44px",
                    borderRadius: "var(--radius-sm)", background: `color-mix(in srgb, ${cvar} 12%, transparent)`, color: cvar, opacity: 0.5, marginBottom: "10px" }}><WIco n={s.icon} s={22} /></span>
                  <span style={{ width: "10px", height: "10px", borderRadius: "50%", background: "var(--text-disabled)" }} />
                </div>
                <h3 style={{ margin: 0, fontSize: "16px", fontWeight: 700, display: "flex", alignItems: "center", gap: "7px" }}>{s.title}
                  <Badge color="dim" mono>Bientôt</Badge></h3>
                <p style={{ margin: "4px 0 0", fontSize: "12.5px", color: "var(--text-dim)" }}>{s.desc}</p>
                <div style={{ marginTop: "14px", fontFamily: "var(--font-mono)", fontSize: "11px", color: "var(--text-disabled)" }}>{s.target} (non déployé)</div>
              </div>
            );
          }
          return (
            <a key={s.slug} href="#" onClick={(e) => { e.preventDefault(); GO(SLUG_VIEW[s.slug] || "portail"); }} style={{ display: "block", position: "relative", padding: "18px",
              background: "var(--bg-2)", border: "1px solid var(--border)", borderRadius: "var(--radius-md)", boxShadow: "var(--shadow-md)",
              textDecoration: "none", color: "var(--text-primary)", transition: "all var(--motion-base)" }}
              onMouseEnter={(e) => { e.currentTarget.style.background = "var(--bg-3)"; e.currentTarget.style.boxShadow = "var(--shadow-glow)"; }}
              onMouseLeave={(e) => { e.currentTarget.style.background = "var(--bg-2)"; e.currentTarget.style.boxShadow = "var(--shadow-md)"; }}>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start" }}>
                <span style={{ display: "inline-flex", alignItems: "center", justifyContent: "center", width: "44px", height: "44px",
                  borderRadius: "var(--radius-sm)", background: `color-mix(in srgb, ${cvar} 16%, transparent)`, color: cvar, marginBottom: "10px" }}><WIco n={s.icon} s={22} /></span>
                <span className="laforge-pulse" style={{ width: "10px", height: "10px", borderRadius: "50%",
                  background: s.status === "up" ? "var(--green)" : s.status === "warn" ? "var(--yellow)" : "var(--red)" }} />
              </div>
              <h3 style={{ margin: 0, fontSize: "16px", fontWeight: 700, display: "flex", alignItems: "center", gap: "7px" }}>{s.title}
                {s.ext && <Badge color="dim" mono>EXT</Badge>}</h3>
              <p style={{ margin: "4px 0 0", fontSize: "12.5px", color: "var(--text-secondary)" }}>{s.desc}</p>
              <div style={{ marginTop: "14px", display: "flex", alignItems: "center", gap: "8px" }}>
                {TW.provenance && <ProvenanceBadge origin={s.prov} size="sm" />}
                <span style={{ marginLeft: "auto", fontFamily: "var(--font-mono)", fontSize: "11px", color: "var(--text-dim)" }}>{s.target}</span>
              </div>
            </a>
          );
        })}
      </div>

      <div style={{ marginTop: "22px", padding: "14px 16px", border: "1px solid var(--border-subtle)", borderRadius: "var(--radius-md)",
        background: "var(--bg-1)", color: "var(--text-secondary)", fontSize: "12.5px", display: TW.mcpPanel ? "block" : "none" }}>
        MCP endpoint actif : <span style={{ fontFamily: "var(--font-mono)", color: "var(--text-dim)" }}>http://127.0.0.1:8766/mcp</span> ·
        Web Hub sur <span style={{ fontFamily: "var(--font-mono)", color: "var(--text-dim)" }}>:7400</span> ·
        Charte : <span style={{ fontFamily: "var(--font-mono)", color: "var(--purple)" }}>styles.css</span>
      </div>
    </div>
  );
}

/* ---------------- Chat (ask) ---------------- */
const PROVIDERS = [
  { v: "ollama", label: "Ollama (local)", prov: "local" },
  { v: "groq", label: "Groq", prov: "remote" },
  { v: "gemini", label: "Gemini", prov: "remote" },
  { v: "mistral", label: "Mistral", prov: "remote" },
];
function Chat() {
  const [provider, setProvider] = React.useState("ollama");
  const [input, setInput] = React.useState("");
  const [msgs, setMsgs] = React.useState([
    { role: "sys", text: "Nokido Hub v18.3 · Ring 0 · LF1.S.H.1.3.INT" },
    { role: "bot", text: "Bonjour. Je tourne en local par défaut — où veux-tu forger aujourd'hui ?", prov: "local", model: "ollama:mistral", lat: "418ms" },
  ]);
  const provOf = (p) => (PROVIDERS.find((x) => x.v === p) || PROVIDERS[0]).prov;
  const send = () => {
    const t = input.trim(); if (!t) return;
    const p = provOf(provider);
    setMsgs((m) => [...m, { role: "user", text: t }, { role: "bot", text: "(réponse simulée) — calcul " + (p === "local" ? "sur ta machine" : "délégué au cloud, anonymisé") + ".", prov: p, model: provider + (p === "local" ? ":mistral" : ":llama-70b"), lat: p === "local" ? "612ms" : "248ms" }]);
    setInput("");
  };
  const endRef = React.useRef(null);
  React.useEffect(() => { if (endRef.current) endRef.current.scrollTop = endRef.current.scrollHeight; });

  return (
    <div style={{ maxWidth: "720px", margin: "0 auto", height: "100%", display: "flex", flexDirection: "column", gap: "12px" }}>
      <div style={{ display: "flex", alignItems: "center", gap: "10px" }}>
        <span style={{ width: "8px", height: "8px", borderRadius: "50%", background: "var(--green)" }} className="laforge-pulse" />
        <span style={{ fontWeight: 700 }}>Chat</span>
        <div style={{ marginLeft: "auto", width: "180px" }}>
          <Select value={provider} onChange={(e) => setProvider(e.target.value)} options={PROVIDERS.map((p) => ({ value: p.v, label: p.label }))} />
        </div>
      </div>

      <div ref={endRef} style={{ flex: 1, overflowY: "auto", display: "flex", flexDirection: "column", gap: "10px", padding: "4px" }}>
        {msgs.map((m, i) => (
          <div key={i} style={{ alignSelf: m.role === "user" ? "flex-end" : m.role === "sys" ? "center" : "flex-start", maxWidth: m.role === "sys" ? "100%" : "86%" }}>
            <div style={{
              padding: m.role === "sys" ? "5px 10px" : "9px 13px", borderRadius: "var(--radius-md)", fontSize: m.role === "sys" ? "11px" : "13px", lineHeight: 1.55,
              fontFamily: m.role === "sys" ? "var(--font-mono)" : "var(--font-sans)",
              background: m.role === "user" ? "rgba(119,74,255,0.12)" : m.role === "sys" ? "var(--prov-local-tint)" : "var(--bg-2)",
              border: `1px solid ${m.role === "user" ? "rgba(119,74,255,0.3)" : m.role === "sys" ? "var(--border-subtle)" : "var(--border)"}`,
              color: m.role === "sys" ? "var(--text-dim)" : "var(--text-primary)", textAlign: m.role === "sys" ? "center" : "left",
            }}>{m.text}</div>
            {m.role === "bot" && m.prov && (
              <div style={{ marginTop: "5px" }}><ProvenanceBadge origin={m.prov} ring="verified" size="sm" detail={`${m.model} · ${m.lat}`} /></div>
            )}
          </div>
        ))}
      </div>

      <div style={{ display: "flex", gap: "8px", alignItems: "flex-end" }}>
        <div style={{ flex: 1 }}>
          <TextInput multiline rows={1} placeholder="Message à Nokido…" value={input}
            onChange={(e) => setInput(e.target.value)} />
        </div>
        <Button variant="primary" size="lg" onClick={send} icon={<WIco n="send-horizontal" s={16} />}>Envoyer</Button>
      </div>
      <div style={{ fontFamily: "var(--font-mono)", fontSize: "10px", color: "var(--text-dim)", textAlign: "center" }}>
        Header : LF1.S.H.1.3.INT · ingest centralisé via /api/ingest
      </div>
    </div>
  );
}

/* ---------------- Event Feed (audit) ---------------- */
const TOPIC_COLORS = { tool: "#ff7b72", rpc: "#79c0ff", silo: "#7ee787", skill: "#ffa657", debate: "#d2a8ff", agent: "#f2cc60", system: "#8b949e" };
const EVENTS = [
  { ts: "14:32:08", agent: "ROUTER", topic: "rpc.dispatch", data: '{"provider":"ollama","tokens":812}' },
  { ts: "14:32:08", agent: "BRAIN", topic: "silo.reason", data: '{"silo":"finance","depth":3}' },
  { ts: "14:32:07", agent: "ASK", topic: "tool.call", data: '{"name":"ask","local":true}' },
  { ts: "14:31:54", agent: "RAG", topic: "skill.ingest", data: '{"domain":"sante","tags":["bilan"]}' },
  { ts: "14:31:40", agent: "SWARM", topic: "agent.spawn", data: '{"role":"critic","ring":2}' },
  { ts: "14:30:12", agent: "DEBATE", topic: "debate.round", data: '{"models":["groq","mistral"],"round":2}' },
  { ts: "14:29:55", agent: "SYSTEM", topic: "system.health", data: '{"opsec":"STANDARD","up":true}' },
];
function Feed() {
  const [filter, setFilter] = React.useState("");
  const rows = EVENTS.filter((e) => !filter || (e.topic + e.agent).toLowerCase().includes(filter.toLowerCase()));
  return (
    <div style={{ maxWidth: "1000px", margin: "0 auto" }}>
      <div style={{ display: "flex", alignItems: "center", gap: "10px", marginBottom: "16px" }}>
        <div style={{ width: "280px" }}>
          <TextInput placeholder="Filtrer par topic / agent…" icon={<WIco n="filter" s={15} />} value={filter} onChange={(e) => setFilter(e.target.value)} />
        </div>
        <Badge color="green"><span className="laforge-pulse" style={{ display: "inline-block", width: "6px", height: "6px", borderRadius: "50%", background: "currentColor", marginRight: "5px" }} />Live · 2s</Badge>
        <span style={{ marginLeft: "auto", fontFamily: "var(--font-mono)", fontSize: "11px", color: "var(--text-dim)" }}>{rows.length} événements · bus d'audit</span>
      </div>
      <Card style={{ padding: 0, overflow: "hidden" }}>
        {rows.map((e, i) => {
          const pre = e.topic.split(".")[0];
          const tc = TOPIC_COLORS[pre] || "var(--text-dim)";
          return (
            <div key={i} style={{ display: "flex", gap: "14px", alignItems: "center", padding: "9px 14px",
              borderBottom: i < rows.length - 1 ? "1px solid var(--border-subtle)" : "none", fontFamily: "var(--font-mono)", fontSize: "12px" }}>
              <span style={{ color: "var(--text-dim)", minWidth: "62px" }}>{e.ts}</span>
              <span style={{ color: "var(--blue)", fontWeight: 700, minWidth: "72px" }}>{e.agent}</span>
              <span style={{ color: tc, fontWeight: 700, minWidth: "120px" }}>{e.topic}</span>
              <span style={{ color: "var(--text-secondary)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{e.data}</span>
            </div>
          );
        })}
        {rows.length === 0 && <div style={{ padding: "26px", textAlign: "center", color: "var(--text-dim)", fontSize: "12px" }}>Aucun événement correspondant.</div>}
      </Card>
    </div>
  );
}

function WebHub({ t }) {
  if (t) { TW = t; window.__WH_TW = t; }
  const [view, setView] = React.useState("portail");
  React.useEffect(() => { window.__WH_GO = setView; }, []);
  const [theme, setTheme] = React.useState(() => WPREF ? WPREF.get("theme", "dark") : "dark");
  React.useEffect(() => { if (window.lucide) lucide.createIcons(); });
  const cycleTheme = () => { const n = WPREF ? WPREF.cycleTheme() : theme; setTheme(n); };
  const themeIcon = { dark: "moon", light: "sun", auto: "monitor" }[theme] || "moon";

  const TABS = [["portail", "Portail", "layout-grid"], ["setup", "Setup", "sliders-horizontal"], ["rings", "Rings", "target"], ["chat", "Chat", "message-square"], ["launcher", "Launcher", "rocket"], ["anatomy", "Anatomie", "activity"], ["network", "Network", "share-2"], ["mcp", "MCP Lab", "blocks"], ["rag", "RAG", "database"], ["feed", "Feed", "scroll-text"]];

  return (
    <div style={{ height: "100vh", display: "flex", flexDirection: "column", background: "var(--bg-0)", color: "var(--text-primary)",
      ["--purple"]: TW.accent, ["--accent"]: TW.accent, ["--tint-purple"]: `color-mix(in srgb, ${TW.accent} 16%, transparent)` }}>
      {!TW.motion && <style>{`.laforge-pulse{animation:none !important;}`}</style>}
      {/* topbar */}
      <header style={{ display: "flex", alignItems: "center", gap: "14px", padding: "12px 22px", background: "var(--bg-1)", borderBottom: "1px solid var(--border-subtle)", flexShrink: 0 }}>
        <svg width="26" height="26" viewBox="0 0 64 64" fill="none" style={{ flexShrink: 0 }}>
          <defs><linearGradient id="whBolt" x1="26" y1="12" x2="40" y2="40" gradientUnits="userSpaceOnUse"><stop offset="0" stopColor="#FFE070" /><stop offset="1" stopColor="#FFC22D" /></linearGradient></defs>
          <g stroke="#15121F" strokeWidth="2.4" strokeLinejoin="round">
            <path d="M6 35 L20 31 H48 q4 0 4 3.5 Q52 39 47 39 H39 q-3 0 -4 3 l-1.5 3 H27 q-1 -3 -4 -3 H15 Q6 42 6 35 Z" fill="#9A90BC" />
            <path d="M28 45 h8 l-1.5 5 h-5 Z" fill="#6F6498" /><path d="M17 50 H47 l3 6 H14 Z" fill="#9A90BC" />
          </g>
          <g><rect x="4" y="29" width="23" height="5" rx="2.5" fill="#C77D4A" stroke="#15121F" strokeWidth="2.4" strokeLinejoin="round" />
            <rect x="25" y="21" width="11" height="21" rx="3" fill="#B7BCD2" stroke="#15121F" strokeWidth="2.4" strokeLinejoin="round" />
            <rect x="27.5" y="24" width="5.5" height="6" rx="1.5" fill="#D9DCE8" /></g>
          <path d="M31 41 L40 26 H34 L42 11 L30 28 H36 Z" fill="url(#whBolt)" stroke="#15121F" strokeWidth="2" strokeLinejoin="round" />
        </svg>
        <span style={{ fontWeight: 700, fontSize: "16px", letterSpacing: "0.3px" }}>Nokido Hub</span>
        <span style={{ fontFamily: "var(--font-mono)", fontSize: "11px", color: "var(--text-dim)", border: "1px solid var(--border)", borderRadius: "var(--radius-sm)", padding: "2px 8px" }}>v18.3</span>

        <nav style={{ display: "flex", gap: "4px", marginLeft: "12px" }}>
          {TABS.map(([id, label, icon]) => {
            const on = view === id;
            return (
              <button key={id} onClick={() => setView(id)} style={{ display: "inline-flex", alignItems: "center", gap: "7px", padding: "6px 12px",
                borderRadius: "var(--radius-sm)", border: "none", cursor: "pointer", fontFamily: "var(--font-sans)", fontSize: "13px", fontWeight: on ? 600 : 500,
                background: on ? "var(--bg-3)" : "transparent", color: on ? "var(--text-primary)" : "var(--text-secondary)" }}>
                <WIco n={icon} s={15} />{label}
              </button>
            );
          })}
        </nav>

        <div style={{ marginLeft: "auto", display: "flex", alignItems: "center", gap: "10px" }}>
          <button onClick={cycleTheme} title={`Thème : ${theme}`} aria-label="Thème" style={{ display: "inline-flex", alignItems: "center", justifyContent: "center", width: "32px", height: "32px", borderRadius: "var(--radius-sm)", border: "1px solid var(--border)", background: "transparent", color: "var(--text-secondary)", cursor: "pointer" }}>
            <WIco n={themeIcon} s={15} />
          </button>
          <a href="../login/index.html" title="Se déconnecter" aria-label="Se déconnecter" style={{ display: "inline-flex", alignItems: "center", gap: "7px", height: "32px", padding: "0 11px", borderRadius: "var(--radius-sm)", border: "1px solid var(--border)", background: "transparent", color: "var(--text-secondary)", textDecoration: "none", fontSize: "12.5px", fontFamily: "var(--font-sans)", transition: "all var(--motion-fast)" }}
            onMouseEnter={(e) => { e.currentTarget.style.borderColor = "var(--red)"; e.currentTarget.style.color = "var(--red)"; }}
            onMouseLeave={(e) => { e.currentTarget.style.borderColor = "var(--border)"; e.currentTarget.style.color = "var(--text-secondary)"; }}>
            <WIco n="log-out" s={14} />Déconnexion
          </a>
          <span style={{ fontFamily: "var(--font-mono)", fontSize: "11px", color: "var(--text-dim)" }}>Web Hub :7400</span>
        </div>
      </header>

      <main style={{ flex: 1, overflowY: "auto", padding: pad("24px 22px", "14px 16px") }}>
        {view === "portail" && <Portail />}
        {view === "setup" && <window.SetupView />}
        {view === "rings" && <window.RingsView />}
        {view === "chat" && <Chat />}
        {view === "launcher" && <window.LauncherView />}
        {view === "anatomy" && <window.AnatomyView />}
        {view === "rag" && <window.RagView />}
        {view === "feed" && <Feed />}
        {view === "network" && <window.NetworkView />}
        {view === "mcp" && <window.McpLabView />}
        {view === "reports" && <window.ReportsView />}
        {view === "status" && <window.StatusView />}
        {view === "pipeline" && <window.PipelineView />}
        {view === "swarm" && <window.SwarmView />}
        {view === "debate" && <window.DebateView />}
        {view === "epistemic" && <window.RagView />}
      </main>
    </div>
  );
}

Object.assign(window, { WebHub });
