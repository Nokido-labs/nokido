/**
 * hub_mcp/main.ts — Deno port Hub MCP HTTP (Phase B.2).
 *
 * Port :8768 (parallèle au Python :8766 — switch quand validé).
 *
 * Endpoints critiques :
 *   GET  /health          — health check
 *   POST /mcp             — JSON-RPC 2.0 MCP entry point (tools/list, tools/call)
 *
 * Stratégie :
 * - Bearer auth multi-token (FORGE_MCP_TOKEN + FORGE_TOKEN_<AGENT>)
 * - tools/list : retourne le schema 16 tools (cohérent Python hub :8766)
 * - tools/call : delegate à Python via subprocess `forge_dispatchers` /
 *   `forge_trajectory.dispatch_intent` — Python reste source de vérité
 *   pour exécution.
 * - VALIDATION STRICTE : avant cloud (anthropic/openai), check tools
 *   array non-vide via Zod-style guard (commenté NOTE plus bas).
 */
import { join, resolve } from "https://deno.land/std/path/mod.ts";

// ──────────────────────────────────────────────────────────────────────
// Config
// ──────────────────────────────────────────────────────────────────────
const PORT = parseInt(Deno.env.get("LAFORGE_DENO_HUB_PORT") ?? "8769", 10);
const VERSION = "deno-mcp-0.1.0";
const ROOT = resolve(Deno.cwd(), "..");
const PYTHON = Deno.env.get("LAFORGE_PYTHON") ??
  "%USERPROFILE%/miniforge3/python.exe";

console.log(`🧬 [DenoHubMCP] starting on :${PORT}`);
console.log(`  ROOT=${ROOT}`);

// ──────────────────────────────────────────────────────────────────────
// Bearer token whitelist (read .env at startup)
// ──────────────────────────────────────────────────────────────────────
const TOKENS = new Map<string, string>();  // token → agent name
let MCP_PROXY_TOKEN = "";  // FORGE_MCP_TOKEN for forwarding to Python hub :8766
// Marqueur PROPRE de ce service, lu depuis Nokido.env comme les autres. Il lui
// faut sa variable : `MCP_PROXY_TOKEN` porte le MAITRE, et le confondre avec
// l'identite du service est precisement ce qui a rendu le recablage du
// 2026-09-02 sans effet (commentaire « marqueur propre d'abord », code qui
// prenait le maitre en premier -- le journal du hub continuait a lire
// `bearer_maitre` pour DENOHUBMCP).
let DENOHUBMCP_TOKEN = "";

async function loadTokens() {
  try {
    const envFile = join(ROOT, "Nokido.env");
    // Read as raw bytes, decode UTF-8 with replacement (Windows-1252 chars survive)
    const buf = await Deno.readFile(envFile);
    const raw = new TextDecoder("utf-8", { fatal: false }).decode(buf);
    let count = 0;
    for (const line of raw.split(/\r?\n/)) {
      const trimmed = line.trim();
      if (!trimmed || trimmed.startsWith("#")) continue;
      const eq = trimmed.indexOf("=");
      if (eq < 0) continue;
      const key = trimmed.slice(0, eq).trim();
      const valRaw = trimmed.slice(eq + 1).trim().replace(/^['"]|['"]$/g, "");
      if (key === "FORGE_MCP_TOKEN") {
        TOKENS.set(valRaw, "MCP_DEFAULT");
        MCP_PROXY_TOKEN = valRaw;
        count++;
      } else if (key.startsWith("FORGE_TOKEN_")) {
        const agent = key.slice("FORGE_TOKEN_".length);
        TOKENS.set(valRaw, agent);
        if (agent.toUpperCase() === "DENOHUBMCP") DENOHUBMCP_TOKEN = valRaw;
        count++;
      }
    }
    console.log(`🔒 [DenoHubMCP] loaded ${count} tokens (size=${TOKENS.size})`);
  } catch (e) {
    console.error(`[DenoHubMCP] token load failed: ${e}`);
  }
}

await loadTokens();

// ──────────────────────────────────────────────────────────────────────
// SSOT bootstrap: fetch live tool list from Python hub (ring=0 = all tools)
// Falls back silently to hardcoded TOOL_CATALOG if hub unreachable.
// ──────────────────────────────────────────────────────────────────────
async function refreshToolCatalog(): Promise<void> {
  // MARQUEUR PROPRE d'abord (2026-09-02). Ce service portait le jeton MAITRE,
  // qui est un passe-partout : son porteur peut se declarer n'importe quel
  // agent et heriter de son ring. `FORGE_TOKEN_DENOHUBMCP` a ete provisionne
  // au coffre ; le repli maitre subsiste mais le hub le DIT desormais
  // (via=bearer_maitre dans le journal d'autorisation).
  const token = DENOHUBMCP_TOKEN
    || Deno.env.get("FORGE_TOKEN_DENOHUBMCP")
    || MCP_PROXY_TOKEN
    || Deno.env.get("FORGE_MCP_TOKEN") || "";
  if (!token) return;
  try {
    const resp = await fetch("http://127.0.0.1:8766/mcp", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "Authorization": `Bearer ${token}`,
        // `X-Agent-Ring: 0` RETIRE le 2026-09-02. Il annoncait le ring de
        // l'owner alors que ce service est declare ring 4 au registre -- et
        // surtout AUCUN code ne le lisait : verifie, zero occurrence de
        // `Agent-Ring` dans tout le Python du depot. Ce n'etait donc pas une
        // escalade, mais un en-tete qui PROMETTAIT un privilege qu'il
        // n'obtenait pas. Le laisser, c'etait attendre que quelqu'un
        // l'implemente « pour bien faire » et transforme la decoration en
        // faille. Le ring vient du registre, jamais de l'appelant.
        "LaForge-Agent-Name": "DenoHubMCP",
        "X-Agent-Name": "DenoHubMCP",
      },
      body: JSON.stringify({ jsonrpc: "2.0", id: 1, method: "tools/list" }),
      signal: AbortSignal.timeout(5000),
    });
    if (!resp.ok) return;
    const data = await resp.json() as {result?: {tools?: unknown[]}};
    const tools = data?.result?.tools;
    if (Array.isArray(tools) && tools.length > 0) {
      TOOL_CATALOG = tools as typeof TOOL_CATALOG;
      console.log(`🔄 [DenoHubMCP] SSOT sync: ${tools.length} tools from Python :8766`);
    }
  } catch (e) {
    console.warn(`[DenoHubMCP] SSOT sync failed (fallback to hardcoded): ${String(e).slice(0, 80)}`);
  }
}

// refreshToolCatalog() est appele APRES la declaration de TOOL_CATALOG
// (apres le tableau hardcode, plus bas) — sinon TDZ: "Cannot access
// 'TOOL_CATALOG' before initialization" (le `let` reste en zone morte tant
// que la ligne du tableau n'a pas execute). Fix 2026-06-13: avant ce
// deplacement la SSOT sync echouait a CHAQUE boot -> catalogue MCP fige
// sur le hardcode au lieu du live Python :8766.

function authCheck(req: Request): { ok: boolean; agent: string } {
  const auth = req.headers.get("authorization") ?? "";
  const m = auth.match(/^Bearer\s+(.+)$/i);
  if (!m) return { ok: false, agent: "" };
  const token = m[1].trim();
  const agent = TOKENS.get(token);
  if (!agent) return { ok: false, agent: "" };
  return { ok: true, agent };
}

// ──────────────────────────────────────────────────────────────────────
// Tool catalog — SSOT: fetched from Python hub :8766 at startup.
// Hardcoded array below is FALLBACK only (Python hub unreachable).
// Refresh via refreshToolCatalog() — called once at boot, no periodic loop.
// ──────────────────────────────────────────────────────────────────────
let TOOL_CATALOG: Array<{name: string; description: string; inputSchema: unknown}> = [
  { name: "run", description: "Git/Python/Atlas/Snapshot/GitHub/Shell",
    inputSchema: {
      type: "object",
      properties: {
        action: { type: "string", enum: ["github", "python", "shell", "atlas_build", "save_situation", "atlas_get", "make_snapshot", "setup_check", "restart_claude", "audit_log", "worker_status"] },
        code: { type: "string" }
      },
      required: ["action"]
    }
  },
  { name: "read", description: "Lire fichier ou logs (stub/full/tail)",
    inputSchema: { type: "object", properties: { path: { type: "string" }, mode: { type: "string", enum: ["stub", "full", "tail"] }, n: { type: "integer" } }, required: ["path"] }
  },
  { name: "write", description: "Ecrire/editer fichier (Thread-safe, RING_0)",
    inputSchema: { type: "object", properties: { path: { type: "string" }, content: { type: "string" }, mode: { type: "string", enum: ["overwrite", "append", "patch"] } }, required: ["path", "content"] }
  },
  { name: "query", description: "SQL RAG ou semantic search",
    inputSchema: { type: "object", properties: { sql: { type: "string" }, semantic: { type: "string" }, limit: { type: "integer" } } }
  },
  { name: "web_search", description: "Recherche web SearXNG",
    inputSchema: { type: "object", properties: { q: { type: "string" }, n: { type: "integer" } }, required: ["q"] }
  },
  { name: "research_agent", description: "Agent recherche zero-token: SearXNG+Groq->RAG",
    inputSchema: { type: "object", properties: { query: { type: "string" }, depth: { type: "integer" } }, required: ["query"] }
  },
  { name: "route_task", description: "Route tache vers provider LLM gratuit (ollama/gemini/groq)",
    inputSchema: { type: "object", properties: { task: { type: "string" }, hint: { type: "string" } }, required: ["task"] }
  },
  { name: "ask", description: "RPC LLM: provider=claude|gemini|groq|ollama|gpt4o_github|gem",
    inputSchema: { type: "object", properties: { provider: { type: "string" }, prompt: { type: "string" }, system: { type: "string" } }, required: ["provider", "prompt"] }
  },
  { name: "hub", description: "Etat hub: action=get_mode|set_mode|poll|notify|list_providers",
    inputSchema: { type: "object", properties: { action: { type: "string" }, message: { type: "string" } }, required: ["action"] }
  },
  { name: "task", description: "Cycle tache: action=assign|claim|result|status",
    inputSchema: { type: "object", properties: { action: { type: "string" }, task_id: { type: "string" }, agent: { type: "string" }, payload: { type: "object" } }, required: ["action"] }
  },
  { name: "event", description: "EventBus: action=publish|history",
    inputSchema: { type: "object", properties: { action: { type: "string" }, channel: { type: "string" }, payload: {} }, required: ["action"] }
  },
  { name: "rag", description: "RAG: action=index|search",
    inputSchema: { type: "object", properties: { action: { type: "string" }, query: { type: "string" }, source: { type: "string" } }, required: ["action"] }
  },
  { name: "auto_test", description: "py_compile AST check fichier",
    inputSchema: { type: "object", properties: { path: { type: "string" } }, required: ["path"] }
  },
  { name: "trigger_autonomous_evolution", description: "Decompose intention en silos et execute en background",
    inputSchema: { type: "object", properties: { intention: { type: "string" }, ring: { type: "integer" } }, required: ["intention"] }
  },
  { name: "biblio", description: "Bibliography Worker: extract|search|list|promote|reject|pin",
    inputSchema: { type: "object", properties: { action: { type: "string" }, query: { type: "string" }, item_id: { type: "string" } }, required: ["action"] }
  },
  { name: "crawl", description: "Crawl URL (Crawl4AI/Markdown)",
    inputSchema: { type: "object", properties: { url: { type: "string" }, format: { type: "string" } }, required: ["url"] }
  }
];

// SSOT bootstrap (deplace ici, APRES la declaration de TOOL_CATALOG pour
// eviter la TDZ — cf note plus haut). Sync live le catalogue depuis le hub
// Python :8766 ; fallback silencieux sur le hardcode ci-dessus si hub HS.
await refreshToolCatalog();

// ──────────────────────────────────────────────────────────────────────
// Strict tools validation (Phase D.4 anti-MCP-blindness)
// ──────────────────────────────────────────────────────────────────────
function validateMcpRequest(body: unknown): { ok: boolean; reason?: string } {
  if (typeof body !== "object" || body === null) {
    return { ok: false, reason: "body must be JSON object" };
  }
  const b = body as Record<string, unknown>;
  if (b.jsonrpc !== "2.0") {
    return { ok: false, reason: "jsonrpc must be '2.0'" };
  }
  if (typeof b.method !== "string") {
    return { ok: false, reason: "method must be string" };
  }
  if (b.method === "tools/call") {
    const params = b.params as Record<string, unknown> | undefined;
    if (!params || typeof params !== "object") {
      return { ok: false, reason: "tools/call requires params object" };
    }
    if (typeof params.name !== "string" || !params.name) {
      return { ok: false, reason: "tools/call params.name required" };
    }
    const knownTool = TOOL_CATALOG.find((t) => t.name === params.name);
    if (!knownTool) {
      return { ok: false, reason: `unknown tool: ${params.name}` };
    }
  }
  return { ok: true };
}

// ──────────────────────────────────────────────────────────────────────
// Delegate tools/call to Python via subprocess
// ──────────────────────────────────────────────────────────────────────
// ── Cloud LLM tool validation (anti-MCP-blindness) ─────────────────────
// Phase B.2 critique : si tool=ask avec provider cloud, garantir que
// TOOL_CATALOG côté Deno est valide ET que Python hub :8766 réponde
// (sinon outbound LLM serait routé sans tools registered = chatbot passif).
const CLOUD_PROVIDERS = new Set(["claude", "gemini", "groq", "openai", "anthropic",
                                  "gpt4o_github", "github_models", "openrouter",
                                  "mistral", "xai", "hf"]);

async function preFlightCloudCheck(toolName: string, args: Record<string, unknown>): Promise<{ ok: boolean; reason?: string }> {
  // Validation tools catalog non-vide (anti-désync MCP)
  if (TOOL_CATALOG.length === 0) {
    return { ok: false, reason: "TOOL_CATALOG empty - cloud call would render LLM tool-blind" };
  }
  // KILL SWITCH SÉMANTIQUE check : lit state.json miroir
  // Si network_kill=true → reject TOUS outbounds (pas seulement cloud)
  try {
    const state = await Deno.readTextFile(
      Deno.env.get("LAFORGE_PERSIST_DIR") + "/state.json"
    ).then(JSON.parse).catch(() => null);
    if (state?.network_kill === true) {
      return {
        ok: false,
        reason: "🛑 KILL SWITCH ACTIVE - all outbounds blocked. Release via /api/persist/kill_switch DELETE."
      };
    }
  } catch (_e) {
    // fail-open : si state.json illisible, ne bloque pas (autres défenses prennent relais)
  }
  // Si tool=ask avec provider cloud, vérifier provider valide
  if (toolName === "ask") {
    const provider = String(args.provider ?? "").toLowerCase();
    if (CLOUD_PROVIDERS.has(provider)) {
      // Health check Python hub :8766 (fail fast si down)
      try {
        const r = await fetch("http://127.0.0.1:8766/health", {
          signal: AbortSignal.timeout(2000)
        });
        if (!r.ok) {
          return { ok: false, reason: `Python hub :8766 unhealthy (${r.status}) - blocking cloud call` };
        }
      } catch (e) {
        return { ok: false, reason: `Python hub :8766 unreachable - blocking cloud call: ${String(e).slice(0, 80)}` };
      }
    }
  }
  return { ok: true };
}

async function delegateToolCall(name: string, args: Record<string, unknown>, agent: string): Promise<unknown> {
  // Pre-flight cloud anti-blindness
  const pf = await preFlightCloudCheck(name, args);
  if (!pf.ok) {
    return { error: `pre_flight_blocked: ${pf.reason}` };
  }

  // CONFUSED DEPUTY, ferme le 2026-09-02. Ce chemin presentait le jeton MAITRE
  // en se declarant etre un AUTRE agent (`X-Agent-Name: agent`). Or le porteur
  // du maitre HERITE du ring de l'identite qu'il annonce -- mesure du jour :
  // maitre + « CLAUDE » rend ring 1, la ou un jeton derive retombe au plancher
  // anti-spoof. Tout appelant de ce service choisissait donc son ring.
  //
  // Desormais : ce service prouve la SIENNE avec son marqueur propre, et le
  // droit de DECLARER un autre nom vient du registre
  // (`agent_identities.json`, champ `delegation`), borne par
  // `ring_min_delegue`. Le videur le reconnait tout seul -- jeton d'un agent +
  // nom different = delegation, tracee `via=delegated:DENOHUBMCP`.
  //
  // Sans ce champ au registre, l'anti-spoof plafonne au lieu d'accorder : une
  // REGRESSION VISIBLE, preferable a une porte derobee silencieuse.
  const TOKEN_PROXY = DENOHUBMCP_TOKEN
    || Deno.env.get("FORGE_TOKEN_DENOHUBMCP")
    || MCP_PROXY_TOKEN
    || Deno.env.get("FORGE_MCP_TOKEN") || "";
  if (!TOKEN_PROXY) {
    return { error: "aucun credential : ni FORGE_TOKEN_DENOHUBMCP ni FORGE_MCP_TOKEN" };
  }
  if (!DENOHUBMCP_TOKEN && !Deno.env.get("FORGE_TOKEN_DENOHUBMCP")) {
    // Un repli sur le passe-partout doit s'entendre, sinon il devient l'etat
    // normal sans que personne ne l'ait decide.
    console.error(
      "[DenoHubMCP] REPLI sur le jeton MAITRE : FORGE_TOKEN_DENOHUBMCP absent " +
      "de Nokido.env. Les appels relayes porteront un passe-partout.",
    );
  }
  try {
    const resp = await fetch("http://127.0.0.1:8766/mcp", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "Authorization": `Bearer ${TOKEN_PROXY}`,
        "X-Agent-Name": agent,
        "X-Forwarded-By": "DenoHubMCP",
        "X-Tools-Catalog-Size": String(TOOL_CATALOG.length),  // anti-blindness audit
      },
      body: JSON.stringify({
        jsonrpc: "2.0",
        method: "tools/call",
        params: { name, arguments: args },
        id: 1
      }),
      signal: AbortSignal.timeout(60000),
    });
    if (!resp.ok) {
      return { error: `python_hub_status_${resp.status}` };
    }
    return await resp.json();
  } catch (e) {
    return { error: `delegate_failed: ${String(e)}` };
  }
}

// ──────────────────────────────────────────────────────────────────────
// MCP handlers
// ──────────────────────────────────────────────────────────────────────
async function handleMcp(req: Request): Promise<Response> {
  const auth = authCheck(req);
  if (!auth.ok) {
    return new Response(JSON.stringify({ jsonrpc: "2.0", error: { code: -32001, message: "Unauthorized" }, id: null }), {
      status: 401,
      headers: { "Content-Type": "application/json" },
    });
  }

  let body: unknown;
  try {
    body = await req.json();
  } catch (_e) {
    return new Response(JSON.stringify({ jsonrpc: "2.0", error: { code: -32700, message: "Parse error" }, id: null }), {
      status: 400,
      headers: { "Content-Type": "application/json" },
    });
  }

  const validation = validateMcpRequest(body);
  if (!validation.ok) {
    return new Response(JSON.stringify({ jsonrpc: "2.0", error: { code: -32600, message: validation.reason }, id: null }), {
      status: 400,
      headers: { "Content-Type": "application/json" },
    });
  }

  const b = body as { jsonrpc: string; method: string; params?: Record<string, unknown>; id?: number | string };

  // ─── tools/list ──────────────────────────────────────────────────
  if (b.method === "tools/list") {
    return new Response(JSON.stringify({
      jsonrpc: "2.0",
      id: b.id ?? 1,
      result: { tools: TOOL_CATALOG }
    }), { headers: { "Content-Type": "application/json" } });
  }

  // ─── tools/call ──────────────────────────────────────────────────
  if (b.method === "tools/call") {
    const params = b.params as { name: string; arguments?: Record<string, unknown> };
    const toolName = params.name;
    const toolArgs = params.arguments ?? {};
    const result = await delegateToolCall(toolName, toolArgs, auth.agent);
    // result already JSON-RPC formatted from Python hub
    if (typeof result === "object" && result !== null && "result" in result) {
      const r = result as { result: unknown };
      return new Response(JSON.stringify({ jsonrpc: "2.0", id: b.id ?? 1, result: r.result }),
        { headers: { "Content-Type": "application/json" } });
    }
    return new Response(JSON.stringify({ jsonrpc: "2.0", id: b.id ?? 1, result }),
      { headers: { "Content-Type": "application/json" } });
  }

  // ─── initialize (MCP handshake) ──────────────────────────────────
  if (b.method === "initialize") {
    return new Response(JSON.stringify({
      jsonrpc: "2.0",
      id: b.id ?? 1,
      result: {
        protocolVersion: "2024-11-05",
        capabilities: { tools: {} },
        serverInfo: { name: "LaForge-Hub-Deno", version: VERSION },
      }
    }), { headers: { "Content-Type": "application/json" } });
  }

  return new Response(JSON.stringify({
    jsonrpc: "2.0",
    error: { code: -32601, message: `method not found: ${b.method}` },
    id: b.id ?? null
  }), { status: 404, headers: { "Content-Type": "application/json" } });
}

// ──────────────────────────────────────────────────────────────────────
// Server
// ──────────────────────────────────────────────────────────────────────
Deno.serve({ port: PORT, hostname: "127.0.0.1" }, async (req) => {
  const url = new URL(req.url);
  const start = Date.now();

  if (url.pathname === "/health" && req.method === "GET") {
    return new Response(JSON.stringify({
      status: "ok",
      version: VERSION,
      port: PORT,
      backend: "deno",
      tools_count: TOOL_CATALOG.length,
      tokens_loaded: TOKENS.size,
    }), { headers: { "Content-Type": "application/json" } });
  }

  if (url.pathname === "/mcp" && req.method === "POST") {
    try {
      const resp = await handleMcp(req);
      const dt = Date.now() - start;
      console.log(`[POST] /mcp ${resp.status} ${dt}ms`);
      return resp;
    } catch (e) {
      console.error(`[ERR] /mcp ${e}`);
      return new Response(JSON.stringify({ jsonrpc: "2.0", error: { code: -32603, message: String(e) }, id: null }),
        { status: 500, headers: { "Content-Type": "application/json" } });
    }
  }

  if (url.pathname === "/") {
    return new Response(`Nokido Deno Hub MCP :${PORT}\n` +
      `  GET  /health\n` +
      `  POST /mcp  (Bearer auth, JSON-RPC 2.0)\n` +
      `  Tools: ${TOOL_CATALOG.length} (mirrors Python :8766)\n`,
      { headers: { "Content-Type": "text/plain; charset=utf-8" } });
  }

  return new Response("404 Not Found", { status: 404 });
});
