/* Référence design (handoff) — NON compilé. Source canonique : composant du DS Nokido. */
/* Nokido Web Hub — écrans ouverts par les puces & tuiles :
   Network Graph (forge/network), MCP Lab (skills), CTF Reports, Status JSON, Épistémique. */
const { Card, Badge, StatusPill, Button, ProvenanceBadge, TextInput } = window.NokidoDesignSystem_bdc2ac;
const XIco = window.WIco || (({ n, s = 18 }) => <i data-lucide={n} style={{ width: s, height: s }} />);
const provShow = () => (window.__WH_TW ? window.__WH_TW.provenance !== false : true);

/* ============================ Network Graph ============================ */
const NET_NODES = [
  { id: "brain", label: "Cerveau", group: "core", prov: "local", x: 0.50, y: 0.46, r: 26 },
  { id: "router", label: "Routeur", group: "core", prov: "local", x: 0.50, y: 0.74, r: 18 },
  { id: "rag", label: "RAG", group: "memory", prov: "local", x: 0.24, y: 0.34, r: 18 },
  { id: "mem", label: "Mémoire", group: "memory", prov: "local", x: 0.18, y: 0.60, r: 15 },
  { id: "mcp", label: "MCP", group: "tools", prov: "hybrid", x: 0.74, y: 0.30, r: 18 },
  { id: "skills", label: "Skills", group: "tools", prov: "hybrid", x: 0.86, y: 0.52, r: 15 },
  { id: "ollama", label: "Ollama", group: "compute", prov: "local", x: 0.40, y: 0.18, r: 16 },
  { id: "cloud", label: "Cloud", group: "compute", prov: "remote", x: 0.66, y: 0.84, r: 16 },
  { id: "vision", label: "Vision", group: "perception", prov: "local", x: 0.78, y: 0.70, r: 13 },
  { id: "audio", label: "Audio", group: "perception", prov: "local", x: 0.30, y: 0.84, r: 13 },
];
const NET_EDGES = [
  ["brain", "router"], ["brain", "rag"], ["brain", "ollama"], ["brain", "mcp"],
  ["rag", "mem"], ["router", "cloud"], ["router", "mcp"], ["mcp", "skills"],
  ["router", "vision"], ["router", "audio"], ["brain", "mem"], ["mcp", "cloud"],
];
const NET_COLOR = { local: "var(--prov-local)", hybrid: "var(--prov-hybrid)", remote: "var(--prov-remote)" };
const NET_RAW = { local: "#4AC28B", hybrid: "#2DD4BF", remote: "#774AFF" };

function NetworkView() {
  const W = 760, H = 460;
  const [sel, setSel] = React.useState("brain");
  const [t, setT] = React.useState(0);
  React.useEffect(() => {
    if (window.__WH_TW && window.__WH_TW.motion === false) return;
    let raf, start = performance.now();
    const loop = (now) => { setT((now - start) / 1000); raf = requestAnimationFrame(loop); };
    raf = requestAnimationFrame(loop);
    return () => cancelAnimationFrame(raf);
  }, []);
  const pos = (n) => ({ x: n.x * W, y: n.y * H });
  const node = (id) => NET_NODES.find((n) => n.id === id);
  const selNode = node(sel);
  const neighbours = NET_EDGES.filter((e) => e.includes(sel)).map((e) => e[0] === sel ? e[1] : e[0]);

  return (
    <div style={{ maxWidth: "1100px", margin: "0 auto" }}>
      <div style={{ display: "flex", alignItems: "baseline", gap: "10px", marginBottom: "14px" }}>
        <h2 style={{ margin: 0, fontSize: "13px", fontWeight: 700, textTransform: "uppercase", letterSpacing: "0.6px", color: "var(--text-secondary)" }}>Network Graph</h2>
        <span style={{ fontFamily: "var(--font-mono)", fontSize: "11px", color: "var(--text-dim)" }}>forge/network · {NET_NODES.length} nœuds · {NET_EDGES.length} liens</span>
        <div style={{ marginLeft: "auto", display: "flex", gap: "12px", fontFamily: "var(--font-mono)", fontSize: "10.5px" }}>
          <span style={{ color: "var(--prov-local)" }}>● local</span>
          <span style={{ color: "var(--prov-hybrid)" }}>● hybride</span>
          <span style={{ color: "var(--prov-remote)" }}>● distant</span>
        </div>
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "1fr 280px", gap: "14px", alignItems: "stretch" }}>
        <Card style={{ padding: 0, overflow: "hidden", background: "var(--bg-1)" }}>
          <svg viewBox={`0 0 ${W} ${H}`} style={{ width: "100%", display: "block", background: "radial-gradient(ellipse at 50% 40%, color-mix(in srgb, var(--purple) 7%, transparent), transparent 70%)" }}>
            {/* edges */}
            {NET_EDGES.map(([a, b], i) => {
              const pa = pos(node(a)), pb = pos(node(b));
              const active = sel === a || sel === b;
              const dash = 60, off = (-(t * 40) % dash);
              return (
                <g key={i}>
                  <line x1={pa.x} y1={pa.y} x2={pb.x} y2={pb.y} stroke={active ? "var(--purple)" : "var(--border)"} strokeWidth={active ? 2 : 1.2} opacity={active ? 0.9 : 0.5} />
                  {active && <line x1={pa.x} y1={pa.y} x2={pb.x} y2={pb.y} stroke={NET_RAW[node(b).prov]} strokeWidth={2.5} strokeLinecap="round" strokeDasharray={`6 ${dash - 6}`} strokeDashoffset={off} opacity={0.9} />}
                </g>
              );
            })}
            {/* nodes */}
            {NET_NODES.map((n) => {
              const p = pos(n); const on = sel === n.id; const near = neighbours.includes(n.id);
              const pulse = 1 + (window.__WH_TW && window.__WH_TW.motion === false ? 0 : Math.sin(t * 2 + n.x * 6) * 0.06);
              return (
                <g key={n.id} onClick={() => setSel(n.id)} style={{ cursor: "pointer" }}>
                  <circle cx={p.x} cy={p.y} r={n.r * pulse + (on ? 7 : 0)} fill={NET_RAW[n.prov]} opacity={on ? 0.22 : near ? 0.14 : 0.08} />
                  <circle cx={p.x} cy={p.y} r={n.r * pulse} fill="var(--bg-2)" stroke={NET_RAW[n.prov]} strokeWidth={on ? 3 : near ? 2 : 1.5} />
                  <circle cx={p.x} cy={p.y} r={n.r * pulse * 0.4} fill={NET_RAW[n.prov]} opacity={0.85} />
                  <text x={p.x} y={p.y + n.r * pulse + 13} textAnchor="middle" fontSize="11" fontFamily="var(--font-mono)" fill={on ? "var(--text-primary)" : "var(--text-secondary)"} fontWeight={on ? 700 : 500}>{n.label}</text>
                </g>
              );
            })}
          </svg>
        </Card>

        {/* inspector */}
        <Card>
          <div style={{ display: "flex", alignItems: "center", gap: "9px", marginBottom: "12px" }}>
            <span style={{ width: "12px", height: "12px", borderRadius: "50%", background: NET_COLOR[selNode.prov], boxShadow: `0 0 8px ${NET_COLOR[selNode.prov]}` }} />
            <span style={{ fontSize: "16px", fontWeight: 700 }}>{selNode.label}</span>
          </div>
          {provShow() && <ProvenanceBadge origin={selNode.prov} size="sm" />}
          <div style={{ marginTop: "14px", display: "flex", flexDirection: "column", gap: "8px", fontFamily: "var(--font-mono)", fontSize: "11px", color: "var(--text-dim)" }}>
            <div style={{ display: "flex", justifyContent: "space-between" }}><span>node.id</span><span style={{ color: "var(--text-secondary)" }}>{selNode.id}</span></div>
            <div style={{ display: "flex", justifyContent: "space-between" }}><span>groupe</span><span style={{ color: "var(--text-secondary)" }}>{selNode.group}</span></div>
            <div style={{ display: "flex", justifyContent: "space-between" }}><span>liens</span><span style={{ color: "var(--text-secondary)" }}>{neighbours.length}</span></div>
          </div>
          <div style={{ marginTop: "14px", paddingTop: "12px", borderTop: "1px solid var(--border-subtle)" }}>
            <div style={{ fontFamily: "var(--font-mono)", fontSize: "10px", textTransform: "uppercase", letterSpacing: "0.5px", color: "var(--text-dim)", marginBottom: "8px" }}>Connecté à</div>
            <div style={{ display: "flex", flexWrap: "wrap", gap: "6px" }}>
              {neighbours.map((id) => (
                <button key={id} onClick={() => setSel(id)} style={{ display: "inline-flex", alignItems: "center", gap: "5px", padding: "3px 9px", borderRadius: "var(--radius-pill)",
                  border: "1px solid var(--border)", background: "transparent", color: "var(--text-secondary)", fontSize: "11px", fontFamily: "var(--font-mono)", cursor: "pointer" }}>
                  <span style={{ width: "6px", height: "6px", borderRadius: "50%", background: NET_COLOR[node(id).prov] }} />{node(id).label}
                </button>
              ))}
            </div>
          </div>
        </Card>
      </div>
    </div>
  );
}

/* ============================ MCP Lab (skills) ============================ */
const SKILLS = [
  { name: "web.fetch", cat: "Réseau", prov: "remote", ring: "verified", desc: "Récupère une URL (anonymisé)", calls: 142 },
  { name: "fs.read", cat: "Système", prov: "local", ring: "gold", desc: "Lecture fichier local", calls: 980 },
  { name: "rag.search", cat: "Mémoire", prov: "local", ring: "gold", desc: "Recherche sémantique locale", calls: 411 },
  { name: "shell.run", cat: "Système", prov: "local", ring: "verified", desc: "Commande sandboxée", calls: 67 },
  { name: "vision.ocr", cat: "Perception", prov: "local", ring: "draft", desc: "OCR d'image locale", calls: 23 },
  { name: "cloud.ask", cat: "LLM", prov: "remote", ring: "verified", desc: "Délègue au cloud (anonymisé)", calls: 88 },
];
function McpLabView() {
  const [sel, setSel] = React.useState(SKILLS[1]);
  const [q, setQ] = React.useState("");
  const [out, setOut] = React.useState(null);
  const list = SKILLS.filter((s) => s.name.includes(q.toLowerCase()) || s.cat.toLowerCase().includes(q.toLowerCase()));
  const invoke = () => setOut({ ok: true, skill: sel.name, prov: sel.prov, ms: 40 + Math.floor(Math.random() * 600), ring: sel.ring });
  return (
    <div style={{ maxWidth: "1000px", margin: "0 auto" }}>
      <div style={{ display: "flex", alignItems: "baseline", gap: "10px", marginBottom: "14px" }}>
        <h2 style={{ margin: 0, fontSize: "13px", fontWeight: 700, textTransform: "uppercase", letterSpacing: "0.6px", color: "var(--text-secondary)" }}>MCP Lab</h2>
        <span style={{ fontFamily: "var(--font-mono)", fontSize: "11px", color: "var(--text-dim)" }}>marketplace de skills · endpoint :8766</span>
      </div>
      <div style={{ display: "grid", gridTemplateColumns: "1fr 340px", gap: "14px", alignItems: "start" }}>
        <div>
          <div style={{ marginBottom: "10px" }}><TextInput placeholder="Filtrer les skills…" icon={<XIco n="search" s={15} />} value={q} onChange={(e) => setQ(e.target.value)} /></div>
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "10px" }}>
            {list.map((s) => {
              const on = sel.name === s.name;
              return (
                <button key={s.name} onClick={() => { setSel(s); setOut(null); }} style={{ textAlign: "left", padding: "13px", borderRadius: "var(--radius-md)", cursor: "pointer",
                  background: on ? "var(--bg-3)" : "var(--bg-2)", border: `1px solid ${on ? "var(--purple)" : "var(--border)"}`, color: "var(--text-primary)" }}>
                  <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                    <span style={{ fontFamily: "var(--font-mono)", fontSize: "13px", fontWeight: 700 }}>{s.name}</span>
                    <Badge color="dim" mono>{s.cat}</Badge>
                  </div>
                  <div style={{ fontSize: "11.5px", color: "var(--text-secondary)", margin: "5px 0 9px" }}>{s.desc}</div>
                  <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
                    {provShow() && <ProvenanceBadge origin={s.prov} ring={s.ring} size="sm" />}
                    <span style={{ marginLeft: "auto", fontFamily: "var(--font-mono)", fontSize: "10px", color: "var(--text-dim)" }}>{s.calls} appels</span>
                  </div>
                </button>
              );
            })}
          </div>
        </div>
        {/* console */}
        <Card>
          <div style={{ fontFamily: "var(--font-mono)", fontSize: "10px", textTransform: "uppercase", letterSpacing: "0.5px", color: "var(--text-dim)", marginBottom: "10px" }}>Invoke</div>
          <div style={{ fontFamily: "var(--font-mono)", fontSize: "14px", fontWeight: 700, marginBottom: "6px" }}>{sel.name}</div>
          {provShow() && <ProvenanceBadge origin={sel.prov} ring={sel.ring} size="sm" />}
          <div style={{ marginTop: "12px" }}><TextInput multiline rows={3} placeholder={`{ "arg": "valeur" }`} value="" onChange={() => {}} /></div>
          <Button variant="primary" size="md" icon={<XIco n="play" s={14} />} style={{ width: "100%", marginTop: "10px" }} onClick={invoke}>Exécuter</Button>
          {out && (
            <pre style={{ marginTop: "12px", marginBottom: 0, background: "var(--bg-0)", border: "1px solid var(--border-subtle)", borderRadius: "var(--radius-sm)", padding: "11px",
              fontSize: "11px", fontFamily: "var(--font-mono)", color: "var(--text-secondary)", whiteSpace: "pre-wrap" }}>
{JSON.stringify(out, null, 2)}
            </pre>
          )}
        </Card>
      </div>
    </div>
  );
}

/* ============================ CTF Reports ============================ */
const REPORTS = [
  { id: "LF-2026-0042", title: "Recon réseau interne", state: "or", date: "08/06", prov: "local", ring: "gold" },
  { id: "LF-2026-0041", title: "Audit dépendances RAG", state: "vérifié", date: "07/06", prov: "local", ring: "verified" },
  { id: "LF-2026-0039", title: "Test exfiltration (sandbox)", state: "brouillon", date: "05/06", prov: "hybrid", ring: "draft" },
  { id: "LF-2026-0036", title: "Cartographie CVE", state: "vérifié", date: "02/06", prov: "local", ring: "verified" },
];
function ReportsView() {
  return (
    <div style={{ maxWidth: "860px", margin: "0 auto" }}>
      <div style={{ display: "flex", alignItems: "baseline", gap: "10px", marginBottom: "14px" }}>
        <h2 style={{ margin: 0, fontSize: "13px", fontWeight: 700, textTransform: "uppercase", letterSpacing: "0.6px", color: "var(--text-secondary)" }}>CTF Reports</h2>
        <span style={{ fontFamily: "var(--font-mono)", fontSize: "11px", color: "var(--text-dim)" }}>rapports & traces · /reports/</span>
        <Badge color="dim" mono style={{ marginLeft: "auto" }}>EXT</Badge>
      </div>
      <div style={{ display: "flex", flexDirection: "column", gap: "8px" }}>
        {REPORTS.map((r) => (
          <div key={r.id} style={{ display: "flex", alignItems: "center", gap: "13px", padding: "13px 16px", background: "var(--bg-2)", border: "1px solid var(--border)", borderRadius: "var(--radius-md)" }}>
            <span style={{ display: "inline-flex", alignItems: "center", justifyContent: "center", width: "34px", height: "34px", borderRadius: "var(--radius-sm)",
              background: "var(--tint-red)", color: "var(--red)", flexShrink: 0 }}><XIco n="flag" s={16} /></span>
            <div style={{ flex: 1, minWidth: 0 }}>
              <div style={{ fontSize: "13.5px", fontWeight: 600 }}>{r.title}</div>
              <div style={{ fontFamily: "var(--font-mono)", fontSize: "10.5px", color: "var(--text-dim)" }}>{r.id} · {r.date}</div>
            </div>
            {provShow() && <ProvenanceBadge origin={r.prov} ring={r.ring} size="sm" />}
            <Button variant="ghost" size="sm" icon={<XIco n="arrow-up-right" s={13} />}>Ouvrir</Button>
          </div>
        ))}
      </div>
    </div>
  );
}

/* ============================ Status JSON ============================ */
function StatusView() {
  const status = {
    node: "souverain-0", ring: 0, version: "18.3", uptime_s: 8064,
    sovereignty: { local_pct: 68, opsec: "STANDARD", kill_switch: false },
    services: { brain_worker: "running", web_hub: "running", hub_mcp: "running", rag_indexer: "running", swarm: "stale", deno_edge: "stopped" },
    rag: { documents: 128, chunks: 3412, model: "bge-m3", dims: 1024 },
  };
  const color = (v) => typeof v === "boolean" ? (v ? "var(--green)" : "var(--red)")
    : v === "running" ? "var(--green)" : v === "stale" ? "var(--yellow)" : v === "stopped" ? "var(--text-dim)"
    : typeof v === "number" ? "var(--cyan)" : "var(--orange)";
  const render = (obj, depth = 0) => Object.entries(obj).map(([k, v]) => {
    const isObj = v && typeof v === "object";
    return (
      <div key={k} style={{ paddingLeft: depth * 16 }}>
        <span style={{ color: "var(--purple)" }}>"{k}"</span><span style={{ color: "var(--text-dim)" }}>: </span>
        {isObj ? <span style={{ color: "var(--text-dim)" }}>{Array.isArray(v) ? "[" : "{"}</span>
          : <span style={{ color: color(v) }}>{JSON.stringify(v)}</span>}
        {isObj && <div>{render(v, depth + 1)}</div>}
        {isObj && <span style={{ color: "var(--text-dim)", paddingLeft: depth * 16 }}>{Array.isArray(v) ? "]" : "}"}</span>}
      </div>
    );
  });
  return (
    <div style={{ maxWidth: "720px", margin: "0 auto" }}>
      <div style={{ display: "flex", alignItems: "baseline", gap: "10px", marginBottom: "14px" }}>
        <h2 style={{ margin: 0, fontSize: "13px", fontWeight: 700, textTransform: "uppercase", letterSpacing: "0.6px", color: "var(--text-secondary)" }}>Status JSON</h2>
        <span style={{ fontFamily: "var(--font-mono)", fontSize: "11px", color: "var(--text-dim)" }}>GET /status.json</span>
        <StatusPill status="up" pulse style={{ marginLeft: "auto" }}>200 OK</StatusPill>
      </div>
      <Card style={{ background: "var(--bg-1)" }}>
        <pre style={{ margin: 0, fontFamily: "var(--font-mono)", fontSize: "12px", lineHeight: 1.7, overflow: "auto" }}>
          <span style={{ color: "var(--text-dim)" }}>{"{"}</span>
          {render(status, 1)}
          <span style={{ color: "var(--text-dim)" }}>{"}"}</span>
        </pre>
      </Card>
    </div>
  );
}

Object.assign(window, { NetworkView, McpLabView, ReportsView, StatusView, PipelineView, SwarmView, DebateView });

/* ============================ Swarm (essaim d'agents) ============================ */
const AGENTS = [
  { id: "archiviste", label: "Archiviste-Paléographe", role: "Archives & paléographie", prov: "local", state: "active", load: 0.74 },
  { id: "cryptographe", label: "Cryptographe", role: "Chiffrement & analyse", prov: "local", state: "active", load: 0.61 },
  { id: "cartographe", label: "Géomaticien-Cartographe", role: "SIG & cartographie", prov: "hybrid", state: "alive", load: 0.33 },
  { id: "graphiste", label: "Graphiste-DA", role: "Direction artistique", prov: "local", state: "idle", load: 0.08 },
  { id: "libraire", label: "Libraire-Bibliographe", role: "Recherche bibliographique", prov: "local", state: "active", load: 0.52 },
  { id: "sociologue", label: "Sociologue-Démographe", role: "Analyse sociale", prov: "remote", state: "alive", load: 0.27 },
];
const A_STATE = { active: { c: "var(--green)", t: "active" }, alive: { c: "var(--cyan)", t: "alive" }, idle: { c: "var(--text-dim)", t: "idle" } };
function SwarmView() {
  const [tasks] = React.useState(34);
  const active = AGENTS.filter((a) => a.state === "active").length;
  return (
    <div style={{ maxWidth: "1000px", margin: "0 auto" }}>
      <div style={{ display: "flex", alignItems: "baseline", gap: "10px", marginBottom: "14px" }}>
        <h2 style={{ margin: 0, fontSize: "13px", fontWeight: 700, textTransform: "uppercase", letterSpacing: "0.6px", color: "var(--text-secondary)" }}>Swarm</h2>
        <span style={{ fontFamily: "var(--font-mono)", fontSize: "11px", color: "var(--text-dim)" }}>essaim d'agents · {active} actifs · {tasks} tâches en silo</span>
        {provShow() && <ProvenanceBadge origin="hybrid" detail="orchestration locale" size="sm" style={{ marginLeft: "auto" }} />}
      </div>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(300px, 1fr))", gap: "12px" }}>
        {AGENTS.map((a) => {
          const st = A_STATE[a.state];
          return (
            <Card key={a.id}>
              <div style={{ display: "flex", alignItems: "flex-start", gap: "11px" }}>
                <span style={{ display: "inline-flex", alignItems: "center", justifyContent: "center", width: "40px", height: "40px", borderRadius: "var(--radius-sm)",
                  background: "var(--tint-purple)", color: "var(--purple)", flexShrink: 0 }}><XIco n="bot" s={20} /></span>
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={{ fontSize: "14px", fontWeight: 700 }}>{a.label}</div>
                  <div style={{ fontSize: "11.5px", color: "var(--text-dim)" }}>{a.role}</div>
                </div>
                <span className={a.state !== "idle" ? "laforge-pulse" : ""} style={{ width: "10px", height: "10px", borderRadius: "50%", background: st.c, boxShadow: `0 0 8px ${st.c}`, flexShrink: 0, marginTop: "5px" }} />
              </div>
              <div style={{ marginTop: "12px", display: "flex", alignItems: "center", gap: "10px" }}>
                <div style={{ flex: 1, height: "5px", borderRadius: "3px", background: "var(--bg-4)", overflow: "hidden" }}>
                  <div style={{ width: `${Math.round(a.load * 100)}%`, height: "100%", background: st.c }} />
                </div>
                <span style={{ fontFamily: "var(--font-mono)", fontSize: "10px", color: "var(--text-dim)" }}>{Math.round(a.load * 100)}%</span>
                {provShow() && <ProvenanceBadge origin={a.prov} size="sm" />}
              </div>
            </Card>
          );
        })}
      </div>
    </div>
  );
}

/* ============================ LLM Debate ============================ */
const DEBATE = [
  { model: "ollama:mistral", prov: "local", side: "Pour", text: "Rester 100% local : la confidentialité prime, le NPU suffit pour 90% des requêtes.", ring: "verified" },
  { model: "groq:llama-70b", prov: "remote", side: "Contre", text: "Le cloud apporte une puissance que le local n'atteint pas sur les longues roadmaps.", ring: "verified" },
  { model: "ollama:qwen", prov: "local", side: "Nuance", text: "Hybride adaptatif : local par défaut, cloud anonymisé uniquement au-delà d'un seuil de complexité.", ring: "gold" },
];
function DebateView() {
  const [round] = React.useState(2);
  const sideColor = { Pour: "var(--green)", Contre: "var(--red)", Nuance: "var(--cyan)" };
  return (
    <div style={{ maxWidth: "840px", margin: "0 auto" }}>
      <div style={{ display: "flex", alignItems: "baseline", gap: "10px", marginBottom: "14px" }}>
        <h2 style={{ margin: 0, fontSize: "13px", fontWeight: 700, textTransform: "uppercase", letterSpacing: "0.6px", color: "var(--text-secondary)" }}>LLM Debate</h2>
        <span style={{ fontFamily: "var(--font-mono)", fontSize: "11px", color: "var(--text-dim)" }}>débat multi-modèles · round {round}/3</span>
      </div>
      <Card style={{ background: "var(--bg-1)", marginBottom: "14px" }}>
        <div style={{ fontSize: "11px", textTransform: "uppercase", letterSpacing: "0.5px", color: "var(--text-dim)", marginBottom: "5px" }}>Motion</div>
        <p style={{ margin: 0, fontSize: "15px", fontWeight: 600, lineHeight: 1.4 }}>« Nokido devrait-il rester strictement local, ou déléguer au cloud quand c'est plus performant ? »</p>
      </Card>
      <div style={{ display: "flex", flexDirection: "column", gap: "12px" }}>
        {DEBATE.map((d, i) => (
          <div key={i} style={{ display: "flex", gap: "12px" }}>
            <span style={{ display: "inline-flex", alignItems: "center", justifyContent: "center", width: "38px", height: "38px", borderRadius: "var(--radius-sm)", flexShrink: 0,
              background: `color-mix(in srgb, ${d.prov === "remote" ? "var(--prov-remote)" : "var(--prov-local)"} 16%, transparent)`, color: d.prov === "remote" ? "var(--prov-remote)" : "var(--prov-local)" }}><XIco n="message-circle" s={18} /></span>
            <Card style={{ flex: 1 }}>
              <div style={{ display: "flex", alignItems: "center", gap: "8px", marginBottom: "7px" }}>
                <span style={{ fontFamily: "var(--font-mono)", fontSize: "12px", fontWeight: 700 }}>{d.model}</span>
                <span style={{ fontFamily: "var(--font-mono)", fontSize: "9px", fontWeight: 700, color: sideColor[d.side], border: `1px solid ${sideColor[d.side]}`, borderRadius: "4px", padding: "1px 6px" }}>{d.side}</span>
                {provShow() && <ProvenanceBadge origin={d.prov} ring={d.ring} size="sm" style={{ marginLeft: "auto" }} />}
              </div>
              <p style={{ margin: 0, fontSize: "13px", color: "var(--text-secondary)", lineHeight: 1.5 }}>{d.text}</p>
            </Card>
          </div>
        ))}
      </div>
      <Card style={{ marginTop: "14px", background: "var(--bg-1)", display: "flex", alignItems: "center", gap: "10px" }}>
        <XIco n="gavel" s={16} />
        <span style={{ fontSize: "12.5px", color: "var(--text-secondary)" }}>Synthèse de l'arbitre : <b style={{ color: "var(--cyan)" }}>hybride adaptatif</b> retenu — anneau</span>
        <span style={{ marginLeft: "auto" }}><Badge color="yellow" variant="outline">Or</Badge></span>
      </Card>
    </div>
  );
}

/* ============================ Pipeline souverain (CI) ============================ */
function PipelineView() {
  // Gate PRIMAIRE = local (gratuit, hors quota) ; fallback = cloud (manuel, workflow_dispatch).
  const LOCAL_GATE = [
    { name: "pre-commit · secret-scan", desc: "gitleaks local au commit", state: "pass", ring: "gold", ms: 420 },
    { name: "tools/ci_local.py", desc: "pre-push : ruff + bandit + AST", state: "pass", ring: "gold", ms: 3100 },
    { name: "pytest (sélection)", desc: "tests unitaires rapides", state: "pass", ring: "verified", ms: 8800 },
    { name: "ci-selfhosted.yml", desc: "runner local gratuit", state: "running", ring: "verified", ms: null },
  ];
  const CLOUD_FALLBACK = [
    { name: "ci.yml", desc: "matrice 3-OS (portabilité)", trigger: "workflow_dispatch" },
    { name: "eco-shield.yml", desc: "ruff + bandit cross-OS", trigger: "workflow_dispatch" },
    { name: "gitleaks.yml", desc: "scan secrets profond", trigger: "workflow_dispatch" },
    { name: "docker-publish.yml", desc: "image OCI", trigger: "release" },
    { name: "release.yml", desc: "publication miroir public", trigger: "tag v*" },
    { name: "cla.yml", desc: "contributor agreement", trigger: "pull_request" },
  ];
  const STATE = {
    pass: { c: "var(--green)", i: "check", t: "ok" },
    running: { c: "var(--cyan)", i: "loader", t: "en cours" },
    fail: { c: "var(--red)", i: "x", t: "échec" },
  };
  const FLOW = [
    { label: "commit", icon: "git-commit-horizontal", prov: "local" },
    { label: "pre-commit", icon: "shield-check", prov: "local" },
    { label: "pre-push", icon: "terminal", prov: "local" },
    { label: "self-hosted", icon: "server", prov: "local" },
    { label: "merge", icon: "git-merge", prov: "local" },
    { label: "cloud (manuel)", icon: "cloud", prov: "remote" },
  ];
  const provC = { local: "var(--prov-local)", remote: "var(--prov-remote)" };

  return (
    <div style={{ maxWidth: "1040px", margin: "0 auto" }}>
      <div style={{ display: "flex", alignItems: "baseline", gap: "10px", marginBottom: "14px" }}>
        <h2 style={{ margin: 0, fontSize: "13px", fontWeight: 700, textTransform: "uppercase", letterSpacing: "0.6px", color: "var(--text-secondary)" }}>Pipeline souverain</h2>
        <span style={{ fontFamily: "var(--font-mono)", fontSize: "11px", color: "var(--text-dim)" }}>gate local d'abord · cloud en dernier recours</span>
        {provShow() && <ProvenanceBadge origin="local" detail="hors quota Actions" size="sm" style={{ marginLeft: "auto" }} />}
      </div>

      {/* Flux du pipeline */}
      <Card style={{ background: "var(--bg-1)", marginBottom: "16px" }}>
        <div style={{ display: "flex", alignItems: "center", gap: "4px", flexWrap: "wrap" }}>
          {FLOW.map((f, i) => (
            <React.Fragment key={f.label}>
              <div style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: "6px", minWidth: "82px" }}>
                <span style={{ display: "inline-flex", alignItems: "center", justifyContent: "center", width: "38px", height: "38px", borderRadius: "var(--radius-sm)",
                  background: `color-mix(in srgb, ${provC[f.prov]} 16%, transparent)`, color: provC[f.prov], border: `1px solid ${provC[f.prov]}` }}><XIco n={f.icon} s={18} /></span>
                <span style={{ fontFamily: "var(--font-mono)", fontSize: "10px", color: "var(--text-secondary)", textAlign: "center" }}>{f.label}</span>
              </div>
              {i < FLOW.length - 1 && (
                <span style={{ flex: 1, minWidth: "16px", height: "2px", borderRadius: "2px",
                  background: FLOW[i + 1].prov === "remote" ? "repeating-linear-gradient(90deg, var(--prov-remote) 0 5px, transparent 5px 10px)" : "var(--prov-local)", opacity: 0.6 }} />
              )}
            </React.Fragment>
          ))}
        </div>
      </Card>

      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "14px", alignItems: "start" }}>
        {/* Gate local */}
        <Card style={{ borderColor: "var(--prov-local)", boxShadow: "var(--prov-local-glow)" }}>
          <div style={{ display: "flex", alignItems: "center", gap: "8px", marginBottom: "4px" }}>
            <XIco n="shield-check" s={16} /><span style={{ fontWeight: 700, fontSize: "14px" }}>Gate primaire · LOCAL</span>
            <Badge color="green" mono style={{ marginLeft: "auto" }}>Gratuit</Badge>
          </div>
          <div style={{ fontSize: "11.5px", color: "var(--text-dim)", marginBottom: "12px" }}>Tourne sur ta machine / runner self-hosted. Bloquant.</div>
          <div style={{ display: "flex", flexDirection: "column", gap: "8px" }}>
            {LOCAL_GATE.map((c) => {
              const st = STATE[c.state];
              return (
                <div key={c.name} style={{ display: "flex", alignItems: "center", gap: "11px", padding: "10px 12px", background: "var(--bg-2)", border: "1px solid var(--border)", borderRadius: "var(--radius-sm)" }}>
                  <span className={c.state === "running" ? "laforge-pulse" : ""} style={{ display: "inline-flex", alignItems: "center", justifyContent: "center", width: "22px", height: "22px",
                    borderRadius: "50%", background: `color-mix(in srgb, ${st.c} 16%, transparent)`, color: st.c, flexShrink: 0 }}><XIco n={st.i} s={13} /></span>
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <div style={{ fontFamily: "var(--font-mono)", fontSize: "12px", fontWeight: 600 }}>{c.name}</div>
                    <div style={{ fontSize: "10.5px", color: "var(--text-dim)" }}>{c.desc}</div>
                  </div>
                  <span style={{ fontFamily: "var(--font-mono)", fontSize: "10px", color: "var(--text-dim)" }}>{c.ms ? `${c.ms}ms` : "…"}</span>
                  {provShow() && <span style={{ width: "9px", height: "9px", borderRadius: "50%", background: c.ring === "gold" ? "var(--ring-gold)" : "var(--ring-verified)", boxShadow: `0 0 6px ${c.ring === "gold" ? "var(--ring-gold)" : "var(--ring-verified)"}` }} />}
                </div>
              );
            })}
          </div>
        </Card>

        {/* Fallback cloud */}
        <Card>
          <div style={{ display: "flex", alignItems: "center", gap: "8px", marginBottom: "4px" }}>
            <XIco n="cloud" s={16} /><span style={{ fontWeight: 700, fontSize: "14px" }}>Fallback cloud · MANUEL</span>
            <Badge color="purple" mono style={{ marginLeft: "auto" }}>À la demande</Badge>
          </div>
          <div style={{ fontSize: "11.5px", color: "var(--text-dim)", marginBottom: "12px" }}>GitHub-hosted = quota payant. <span style={{ fontFamily: "var(--font-mono)" }}>workflow_dispatch</span> seulement.</div>
          <div style={{ display: "flex", flexDirection: "column", gap: "8px" }}>
            {CLOUD_FALLBACK.map((w) => (
              <div key={w.name} style={{ display: "flex", alignItems: "center", gap: "11px", padding: "10px 12px", background: "var(--bg-1)", border: "1px solid var(--border-subtle)", borderRadius: "var(--radius-sm)", opacity: 0.92 }}>
                <span style={{ display: "inline-flex", alignItems: "center", justifyContent: "center", width: "22px", height: "22px", borderRadius: "50%",
                  background: "var(--prov-remote-tint)", color: "var(--prov-remote)", flexShrink: 0 }}><XIco n="circle-pause" s={13} /></span>
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={{ fontFamily: "var(--font-mono)", fontSize: "12px", fontWeight: 600 }}>{w.name}</div>
                  <div style={{ fontSize: "10.5px", color: "var(--text-dim)" }}>{w.desc}</div>
                </div>
                <span style={{ fontFamily: "var(--font-mono)", fontSize: "9px", color: "var(--prov-remote)", border: "1px solid var(--prov-remote)", borderRadius: "4px", padding: "1px 5px" }}>{w.trigger}</span>
              </div>
            ))}
          </div>
          <div style={{ marginTop: "12px", display: "flex", alignItems: "center", gap: "8px", fontSize: "11px", color: "var(--text-dim)" }}>
            <XIco n="info" s={13} /><span>Lancé avant un miroir/release public, ou pour valider la portabilité cross-OS.</span>
          </div>
        </Card>
      </div>
    </div>
  );
}
