/* Référence design (handoff) — NON compilé. Source canonique : composant du DS Nokido. */
/* Nokido Web Hub — écrans réels supplémentaires modernisés :
   Launcher (modules), Anatomie Live (organes & flux), RAG Dashboard. */
const { Card, Badge, StatusPill, Button, ProvenanceBadge, TextInput } = window.NokidoDesignSystem_bdc2ac;
const SIco = window.WIco || (({ n, s = 18 }) => <i data-lucide={n} style={{ width: s, height: s }} />);
const showProv = () => (window.__WH_TW ? window.__WH_TW.provenance !== false : true);

/* ====================== Launcher ====================== */
const MODULES0 = [
  { mod: "brain_worker", title: "Brain Worker", desc: "Cœur de raisonnement", status: "running", pid: 4821, port: null, uptime: "2 h 14", prov: "local" },
  { mod: "web_hub", title: "Web Hub", desc: "Portail :7400", status: "running", pid: 4822, port: 7400, uptime: "2 h 14", prov: "local" },
  { mod: "hub_mcp", title: "Hub MCP", desc: "Endpoint :8766", status: "running", pid: 4830, port: 8766, uptime: "2 h 13", prov: "local" },
  { mod: "rag_indexer", title: "RAG Indexer", desc: "Embeddings bge-m3", status: "running", pid: 4901, port: null, uptime: "1 h 58", prov: "local" },
  { mod: "swarm", title: "Swarm", desc: "Essaim d'agents", status: "stale", pid: 5012, port: null, uptime: "—", prov: "hybrid" },
  { mod: "deno_edge", title: "Deno Edge", desc: "Runtime :7401", status: "stopped", pid: null, port: 7401, uptime: "—", prov: "remote" },
];
const ST = {
  running: { label: "running", color: "var(--green)", bg: "rgba(74,194,139,0.12)" },
  stopped: { label: "stopped", color: "var(--text-dim)", bg: "rgba(110,106,130,0.12)" },
  stale: { label: "stale", color: "var(--red)", bg: "rgba(242,79,79,0.12)" },
};
function Launcher() {
  const [mods, setMods] = React.useState(MODULES0);
  const [logs, setLogs] = React.useState({});
  const set = (mod, patch) => setMods((m) => m.map((x) => x.mod === mod ? { ...x, ...patch } : x));
  const start = (mod) => set(mod, { status: "running", pid: 5000 + Math.floor(Math.random() * 900), uptime: "0 s" });
  const stop = (mod) => set(mod, { status: "stopped", pid: null, uptime: "—" });
  const toggleLog = (mod) => setLogs((l) => ({ ...l, [mod]: !l[mod] }));
  return (
    <div style={{ maxWidth: "1000px", margin: "0 auto" }}>
      <div style={{ display: "flex", alignItems: "baseline", gap: "10px", marginBottom: "16px" }}>
        <h2 style={{ margin: 0, fontSize: "13px", fontWeight: 700, textTransform: "uppercase", letterSpacing: "0.6px", color: "var(--text-secondary)" }}>Modules</h2>
        <span style={{ fontFamily: "var(--font-mono)", fontSize: "11px", color: "var(--text-dim)" }}>{mods.filter((m) => m.status === "running").length}/{mods.length} actifs · refresh 3s</span>
      </div>
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "12px" }}>
        {mods.map((m) => {
          const st = ST[m.status];
          return (
            <Card key={m.mod}>
              <div style={{ display: "flex", alignItems: "flex-start", justifyContent: "space-between", gap: "10px" }}>
                <div>
                  <div style={{ fontSize: "15px", fontWeight: 700 }}>{m.title}</div>
                  <div style={{ fontSize: "12px", color: "var(--text-dim)" }}>{m.desc}</div>
                </div>
                <span style={{ fontFamily: "var(--font-mono)", fontSize: "10px", fontWeight: 700, textTransform: "uppercase", letterSpacing: "0.4px",
                  color: st.color, background: st.bg, padding: "3px 9px", borderRadius: "var(--radius-pill)" }}>{st.label}</span>
              </div>
              <div style={{ marginTop: "8px", display: "flex", gap: "10px", alignItems: "center", fontFamily: "var(--font-mono)", fontSize: "11px", color: "var(--text-dim)" }}>
                {m.pid && <span>pid {m.pid}</span>}{m.port && <span>:{m.port}</span>}{m.uptime !== "—" && <span>up {m.uptime}</span>}
                {showProv() && <ProvenanceBadge origin={m.prov} size="sm" style={{ marginLeft: "auto" }} />}
              </div>
              <div style={{ marginTop: "12px", display: "flex", gap: "6px", flexWrap: "wrap" }}>
                <Button variant="success" size="sm" disabled={m.status === "running"} onClick={() => start(m.mod)}>Start</Button>
                <Button variant="danger" size="sm" disabled={m.status === "stopped"} onClick={() => stop(m.mod)}>Stop</Button>
                <Button variant="ghost" size="sm" icon={<SIco n="scroll-text" s={13} />} onClick={() => toggleLog(m.mod)}>Logs</Button>
                <Button variant="ghost" size="sm" icon={<SIco n="radio" s={13} />}>Live</Button>
              </div>
              {logs[m.mod] && (
                <pre style={{ marginTop: "10px", marginBottom: 0, background: "var(--bg-0)", border: "1px solid var(--border-subtle)", borderRadius: "var(--radius-sm)",
                  padding: "10px", fontSize: "10.5px", color: "var(--text-secondary)", fontFamily: "var(--font-mono)", maxHeight: "120px", overflow: "auto", whiteSpace: "pre-wrap" }}>
{`[${m.mod}] booting ring 0…
[${m.mod}] bind ${m.port ? ":" + m.port : "ipc"} ok
[${m.mod}] health=${m.status} provenance=${m.prov}
[${m.mod}] heartbeat 200 OK`}
                </pre>
              )}
            </Card>
          );
        })}
      </div>
    </div>
  );
}

/* ====================== Anatomie Live ====================== */
const OPSEC = { PARANOID: "var(--green)", STANDARD: "var(--cyan)", CTF: "var(--yellow)" };
const HEALTH = { active: "var(--green)", alive: "var(--cyan)", idle: "var(--text-dim)", dead: "var(--red)" };
const ORGANS = {
  "Système nerveux": [
    { label: "Cerveau souverain", module: "brain_worker", health: "active", act: 0.92 },
    { label: "Orchestrateur", module: "forge_orchestrator", health: "active", act: 0.78 },
  ],
  "Mémoire": [
    { label: "RAG / embeddings", module: "rag_indexer", health: "alive", act: 0.54 },
    { label: "Historique", module: "session_store", health: "idle", act: 0.12 },
  ],
  "Perception": [
    { label: "Vision (VLM)", module: "perception_vlm", health: "idle", act: 0.08 },
    { label: "Audio", module: "audio_in", health: "dead", act: 0 },
  ],
  "Routage & action": [
    { label: "Cascade routeur", module: "router", health: "active", act: 0.86 },
    { label: "Outils MCP", module: "mcp_server", health: "alive", act: 0.41 },
  ],
  "Intégrité": [
    { label: "Anneaux", module: "integrity_rings", health: "alive", act: 0.33 },
    { label: "Sécurité OPSEC", module: "security", health: "active", act: 0.7 },
  ],
};
function Anatomy() {
  const [opsec, setOpsec] = React.useState("STANDARD");
  const [killed, setKilled] = React.useState(false);
  const kill = () => { setKilled(true); setOpsec("PARANOID"); };
  const stat = (l, v, c) => (
    <div style={{ padding: "8px 14px", background: "var(--bg-2)", border: "1px solid var(--border)", borderRadius: "var(--radius-sm)" }}>
      <div style={{ fontSize: "10px", textTransform: "uppercase", letterSpacing: "0.4px", color: "var(--text-dim)" }}>{l}</div>
      <div style={{ fontFamily: "var(--font-mono)", fontSize: "15px", fontWeight: 700, color: c || "var(--text-primary)" }}>{v}</div>
    </div>
  );
  return (
    <div style={{ maxWidth: "1000px", margin: "0 auto" }}>
      {killed && (
        <div style={{ marginBottom: "14px", padding: "11px 15px", borderRadius: "var(--radius-md)", background: "rgba(242,79,79,0.12)",
          border: "1px solid var(--red)", color: "var(--red)", fontSize: "13px", fontWeight: 600, display: "flex", alignItems: "center", gap: "9px" }}>
          <SIco n="octagon-alert" s={17} />Kill switch activé — tous les outbounds cloud coupés, OPSEC forcé PARANOID, lock humain requis.
        </div>
      )}
      <div style={{ display: "flex", alignItems: "center", gap: "10px", flexWrap: "wrap", marginBottom: "18px" }}>
        {stat("msgs / 60s", "142", "var(--purple)")}
        {stat("RAG / 60s", "18", "var(--green)")}
        {stat("services", "5 / 6", "var(--blue)")}
        <div style={{ padding: "8px 14px", background: "var(--bg-2)", border: `1px solid ${OPSEC[opsec]}`, borderRadius: "var(--radius-sm)" }}>
          <div style={{ fontSize: "10px", textTransform: "uppercase", letterSpacing: "0.4px", color: "var(--text-dim)" }}>OPSEC</div>
          <div style={{ fontFamily: "var(--font-mono)", fontSize: "15px", fontWeight: 700, color: OPSEC[opsec] }}>{opsec}</div>
        </div>
        <button onClick={kill} disabled={killed} style={{ marginLeft: "auto", display: "inline-flex", alignItems: "center", gap: "7px",
          background: killed ? "var(--bg-3)" : "var(--red)", color: killed ? "var(--text-dim)" : "#fff", border: "none", borderRadius: "var(--radius-sm)",
          padding: "10px 16px", fontWeight: 700, fontSize: "13px", cursor: killed ? "not-allowed" : "pointer", boxShadow: killed ? "none" : "0 0 14px rgba(242,79,79,0.4)" }}>
          <SIco n="octagon-x" s={16} />KILL SWITCH
        </button>
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(300px, 1fr))", gap: "14px" }}>
        {Object.entries(ORGANS).map(([system, organs]) => (
          <Card key={system}>
            <div style={{ fontFamily: "var(--font-mono)", fontSize: "10px", textTransform: "uppercase", letterSpacing: "0.6px", color: "var(--text-dim)", marginBottom: "10px" }}>{system}</div>
            <div style={{ display: "flex", flexDirection: "column", gap: "10px" }}>
              {organs.map((o) => {
                const dead = killed && o.module === "mcp_server";
                const health = dead ? "idle" : o.health;
                const act = dead ? 0.05 : o.act;
                return (
                  <div key={o.module} style={{ display: "flex", alignItems: "center", gap: "11px" }}>
                    <span className={health === "active" || health === "alive" ? "laforge-pulse" : ""} style={{ width: "10px", height: "10px", borderRadius: "50%",
                      background: HEALTH[health], boxShadow: `0 0 8px ${HEALTH[health]}`, flexShrink: 0 }} />
                    <div style={{ flex: 1, minWidth: 0 }}>
                      <div style={{ fontSize: "13px", fontWeight: 600 }}>{o.label}</div>
                      <div style={{ fontFamily: "var(--font-mono)", fontSize: "10px", color: "var(--text-dim)" }}>{o.module}</div>
                    </div>
                    <div style={{ width: "56px", height: "5px", borderRadius: "3px", background: "var(--bg-4)", overflow: "hidden", flexShrink: 0 }}>
                      <div style={{ width: `${Math.round(act * 100)}%`, height: "100%", background: HEALTH[health], transition: "width var(--motion-base)" }} />
                    </div>
                  </div>
                );
              })}
            </div>
          </Card>
        ))}
      </div>
    </div>
  );
}

/* ====================== RAG Dashboard ====================== */
const CHUNKS = [
  { title: "Bilan sanguin — mars", domain: "sante", ring: "gold", n: 12 },
  { title: "Budget mensuel 2026", domain: "finance", ring: "verified", n: 8 },
  { title: "Notes projet Nokido", domain: "dev", ring: "verified", n: 41 },
  { title: "Recettes & courses", domain: "achat", ring: "draft", n: 5 },
];
function Rag() {
  const [q, setQ] = React.useState("");
  const stat = (l, v, c) => (
    <Card style={{ flex: 1 }}>
      <div style={{ fontSize: "10px", textTransform: "uppercase", letterSpacing: "0.4px", color: "var(--text-dim)" }}>{l}</div>
      <div style={{ fontFamily: "var(--font-mono)", fontSize: "20px", fontWeight: 700, color: c || "var(--text-primary)", marginTop: "3px" }}>{v}</div>
    </Card>
  );
  return (
    <div style={{ maxWidth: "880px", margin: "0 auto", display: "flex", flexDirection: "column", gap: "16px" }}>
      <div style={{ display: "flex", gap: "12px" }}>
        {stat("Documents", "128", "var(--purple)")}{stat("Chunks", "3 412", "var(--blue)")}
        {stat("Modèle", "bge-m3", "var(--green)")}{stat("Dimensions", "1024", "var(--cyan)")}
      </div>
      <div style={{ display: "flex", gap: "8px", alignItems: "flex-end" }}>
        <div style={{ flex: 1 }}><TextInput label="Recherche sémantique (locale)" placeholder="Ex : mes dépenses de santé…" icon={<SIco n="search" s={15} />} value={q} onChange={(e) => setQ(e.target.value)} /></div>
        <Button variant="primary" size="lg" icon={<SIco n="sparkles" s={15} />}>Chercher</Button>
      </div>
      <Card style={{ background: "var(--bg-1)", display: "flex", alignItems: "center", gap: "10px" }}>
        <SIco n="download" s={16} /><span style={{ fontSize: "12.5px", color: "var(--text-secondary)" }}>Ingestion centralisée via <span style={{ fontFamily: "var(--font-mono)", color: "var(--text-dim)" }}>/api/ingest</span> — URL ou texte, indexé en local.</span>
        {showProv() && <ProvenanceBadge origin="local" size="sm" style={{ marginLeft: "auto" }} />}
      </Card>
      <div>
        <div style={{ fontFamily: "var(--font-mono)", fontSize: "10px", textTransform: "uppercase", letterSpacing: "0.6px", color: "var(--text-dim)", margin: "4px 0 8px" }}>Documents récents</div>
        <div style={{ display: "flex", flexDirection: "column", gap: "8px" }}>
          {CHUNKS.map((c) => (
            <div key={c.title} style={{ display: "flex", alignItems: "center", gap: "12px", padding: "12px 15px", background: "var(--bg-2)", border: "1px solid var(--border)", borderRadius: "var(--radius-md)" }}>
              <span style={{ display: "inline-flex", alignItems: "center", justifyContent: "center", width: "32px", height: "32px", borderRadius: "var(--radius-sm)",
                background: `color-mix(in srgb, var(--domain-${c.domain}) 16%, transparent)`, color: `var(--domain-${c.domain})`, flexShrink: 0 }}><SIco n="file-text" s={16} /></span>
              <div style={{ flex: 1, minWidth: 0 }}>
                <div style={{ fontSize: "13px", fontWeight: 600 }}>{c.title}</div>
                <div style={{ fontFamily: "var(--font-mono)", fontSize: "10px", color: "var(--text-dim)" }}>{c.n} chunks · domaine {c.domain}</div>
              </div>
              {showProv() && <ProvenanceBadge origin="local" ring={c.ring} size="sm" />}
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

Object.assign(window, { LauncherView: Launcher, AnatomyView: Anatomy, RagView: Rag });
