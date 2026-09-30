/**
 * web_hub/main.ts — Deno port webhub PUBLIC layer (Phase B.1).
 *
 * Port :7401 (parallèle au Python :7400 — switch quand validé).
 *
 * Endpoints portés :
 *   GET  /health
 *   GET  /api/opsec/status
 *   POST /api/opsec/set
 *   POST /api/opsec/lock
 *   GET  /api/opsec/audit
 *   GET  /api/anatomy/state
 *   GET  /anatomy           (HTML view)
 *   GET  /api/events/history
 *   POST /api/events/publish
 *
 * Stratégie : lit state.json miroir + SQLite direct (read-only),
 * délègue mutations OPSEC à Python helper via subprocess.
 */
import { join, resolve } from "https://deno.land/std/path/mod.ts";

// ──────────────────────────────────────────────────────────────────────
// Config
// ──────────────────────────────────────────────────────────────────────
const PORT = parseInt(Deno.env.get("LAFORGE_DENO_WEBHUB_PORT") ?? "7401", 10);
const VERSION = "deno-0.1.0";
const ROOT = resolve(Deno.cwd(), "..");
const PERSIST_DIR = Deno.env.get("LAFORGE_PERSIST_DIR") ?? join(ROOT, "nokido_persist");
const STATE_FILE = join(PERSIST_DIR, "state.json");
const RAG_DB = join(ROOT, "RAG", "embeddings.db");
const ANATOMY_HTML = join(ROOT, "app", "web_hub", "anatomy.html");
const PYTHON = Deno.env.get("LAFORGE_PYTHON") ??
  "%USERPROFILE%/miniforge3/python.exe";

console.log(`🧬 [DenoWebHub] starting on :${PORT}`);
console.log(`  ROOT=${ROOT}`);
console.log(`  PERSIST=${PERSIST_DIR}`);

// ──────────────────────────────────────────────────────────────────────
// Helpers
// ──────────────────────────────────────────────────────────────────────
function jsonResp(data: unknown, status = 200): Response {
  return new Response(JSON.stringify(data), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

async function readState(): Promise<Record<string, unknown> | null> {
  try {
    const raw = await Deno.readTextFile(STATE_FILE);
    return JSON.parse(raw);
  } catch (_e) {
    return null;
  }
}

/** Subprocess call à Python helper (forge_opsec.py module CLI). */
async function callPython(modulePath: string, args: string[]): Promise<{ ok: boolean; out: string; err: string }> {
  try {
    const cmd = new Deno.Command(PYTHON, {
      args: [modulePath, ...args],
      cwd: ROOT,
      stdout: "piped",
      stderr: "piped",
      env: { PYTHONIOENCODING: "utf-8", PYTHONPATH: join(ROOT, "app") },
    });
    const { code, stdout, stderr } = await cmd.output();
    return {
      ok: code === 0,
      out: new TextDecoder().decode(stdout),
      err: new TextDecoder().decode(stderr),
    };
  } catch (e) {
    return { ok: false, out: "", err: String(e) };
  }
}

/** Invoke Python forge_opsec via inline -c (mutations + audit). */
async function callOpsec(action: string, params: Record<string, unknown>): Promise<unknown> {
  const code = `
import sys, json
sys.path.insert(0, r"${join(ROOT, "app").replace(/\\/g, "/")}")
from forge_opsec import set_opsec_level, set_human_lock, status, audit_log
action = "${action}"
params = json.loads(${JSON.stringify(JSON.stringify(params))})
if action == "set_level":
    r = set_opsec_level(params["level"], set_by="deno_webhub", reason=params.get("reason",""), lock=params.get("lock"), force=True)
elif action == "set_lock":
    r = set_human_lock(bool(params["locked"]), set_by="deno_webhub", reason=params.get("reason",""))
elif action == "status":
    r = status()
elif action == "audit":
    r = {"log": audit_log(int(params.get("limit", 20)))}
else:
    r = {"error": "unknown action"}
print(json.dumps(r, ensure_ascii=False))
`;
  const proc = new Deno.Command(PYTHON, {
    args: ["-c", code],
    cwd: ROOT,
    stdout: "piped",
    stderr: "piped",
    env: { PYTHONIOENCODING: "utf-8" },
  }).spawn();
  const tid = setTimeout(() => { try { proc.kill(); } catch (_) {} }, 10_000);
  const { stdout, stderr } = await proc.output();
  clearTimeout(tid);
  const out = new TextDecoder().decode(stdout).trim();
  if (!out) return { ok: false, error: new TextDecoder().decode(stderr).slice(0, 200) };
  try {
    return JSON.parse(out);
  } catch (_e) {
    return { ok: false, error: "parse_failed", raw: out.slice(0, 200) };
  }
}

/** Anatomy state via Python (subprocess JSON). */
async function getAnatomyState(window: number): Promise<unknown> {
  const code = `
import sys, json
sys.path.insert(0, r"${join(ROOT, "app").replace(/\\/g, "/")}")
from forge_anatomy_state import get_anatomy_state
print(json.dumps(get_anatomy_state(window_seconds=${window}), ensure_ascii=False, default=str))
`;
  const proc = new Deno.Command(PYTHON, {
    args: ["-c", code],
    cwd: ROOT,
    stdout: "piped",
    stderr: "piped",
    env: { PYTHONIOENCODING: "utf-8" },
  }).spawn();
  const tid = setTimeout(() => { try { proc.kill(); } catch (_) {} }, 10_000);
  const { stdout } = await proc.output();
  clearTimeout(tid);
  const out = new TextDecoder().decode(stdout).trim();
  try {
    return JSON.parse(out);
  } catch (_e) {
    return { error: "anatomy_state_parse_failed" };
  }
}

// ──────────────────────────────────────────────────────────────────────
// In-memory event bus (replaces Python SSE + history)
// ──────────────────────────────────────────────────────────────────────
type Event = { ts: number; channel: string; payload: unknown; source: string };
const eventLog: Event[] = [];
const EVENT_LIMIT = 1000;

function publishEvent(channel: string, payload: unknown, source = "anonymous") {
  const evt: Event = { ts: Date.now() / 1000, channel, payload, source };
  eventLog.push(evt);
  if (eventLog.length > EVENT_LIMIT) eventLog.shift();
  return evt;
}

// ──────────────────────────────────────────────────────────────────────
// Routes
// ──────────────────────────────────────────────────────────────────────
async function handleRequest(req: Request): Promise<Response> {
  const url = new URL(req.url);
  const path = url.pathname;
  const method = req.method;

  // ─── /health ──────────────────────────────────────────────────────
  if (path === "/health") {
    return jsonResp({
      status: "ok",
      version: VERSION,
      port: PORT,
      backend: "deno",
      hub_port: 8766,
    });
  }

  // ─── /api/opsec/* ────────────────────────────────────────────────
  if (path === "/api/opsec/status" && method === "GET") {
    // Fast path : read state.json mirror
    const state = await readState();
    if (state) {
      return jsonResp({
        current_level: state.opsec_level,
        level_int: state.level_int,
        human_locked: state.human_locked,
        last_change_by: state.last_change_by,
        last_change_ts: state.last_change_ts,
        source: "state.json mirror",
      });
    }
    // Fallback : Python full status
    return jsonResp(await callOpsec("status", {}));
  }

  if (path === "/api/opsec/set" && method === "POST") {
    try {
      const body = await req.json();
      const result = await callOpsec("set_level", {
        level: body.level,
        reason: body.reason ?? "",
        lock: body.lock,
      });
      return jsonResp(result);
    } catch (e) {
      return jsonResp({ error: String(e) }, 500);
    }
  }

  if (path === "/api/opsec/lock" && method === "POST") {
    try {
      const body = await req.json();
      const result = await callOpsec("set_lock", {
        locked: body.locked,
        reason: body.reason ?? "",
      });
      return jsonResp(result);
    } catch (e) {
      return jsonResp({ error: String(e) }, 500);
    }
  }

  if (path === "/api/opsec/audit" && method === "GET") {
    const limit = parseInt(url.searchParams.get("limit") ?? "20", 10);
    return jsonResp(await callOpsec("audit", { limit }));
  }

  // ─── /api/anatomy/* ──────────────────────────────────────────────
  if (path === "/api/anatomy/state" && method === "GET") {
    const window = parseInt(url.searchParams.get("window") ?? "60", 10);
    const data = await getAnatomyState(window);
    return jsonResp(data);
  }

  if (path === "/anatomy" && method === "GET") {
    try {
      const html = await Deno.readTextFile(ANATOMY_HTML);
      return new Response(html, { headers: { "Content-Type": "text/html; charset=utf-8" } });
    } catch (e) {
      return new Response(`anatomy.html missing: ${e}`, { status: 500 });
    }
  }

  // ─── /api/events/* ────────────────────────────────────────────────
  if (path === "/api/events/history" && method === "GET") {
    const limit = parseInt(url.searchParams.get("limit") ?? "100", 10);
    const channel = url.searchParams.get("channel");
    let events = eventLog;
    if (channel) events = events.filter((e) => e.channel === channel);
    return jsonResp({ events: events.slice(-limit), count: events.length });
  }

  if (path === "/api/events/publish" && method === "POST") {
    try {
      const body = await req.json();
      const evt = publishEvent(body.channel ?? "default", body.payload ?? {}, body.source ?? "deno_webhub");
      return jsonResp({ ok: true, event: evt });
    } catch (e) {
      return jsonResp({ ok: false, error: String(e) }, 400);
    }
  }

  if (path === "/api/events/stats" && method === "GET") {
    const byChannel: Record<string, number> = {};
    for (const e of eventLog) byChannel[e.channel] = (byChannel[e.channel] ?? 0) + 1;
    return jsonResp({
      total: eventLog.length,
      by_channel: byChannel,
      limit: EVENT_LIMIT,
    });
  }

  // ─── /api/wasm/run ────────────────────────────────────────────────
  // POST body: {wasm_b64?: string, wasm_url?: string, func?: string, args?: number[]}
  // Exécution native Deno WebAssembly — zéro subprocess, démarrage µs.
  if (path === "/api/wasm/run" && method === "POST") {
    const t0 = Date.now();
    try {
      const body = await req.json() as Record<string, unknown>;
      const funcName = (body.func as string) ?? "run";
      const args: number[] = Array.isArray(body.args) ? body.args as number[] : [];
      const MAX_SIZE = 4 * 1024 * 1024;

      let wasmBytes: Uint8Array;
      if (typeof body.wasm_b64 === "string") {
        const binary = atob(body.wasm_b64);
        wasmBytes = new Uint8Array(binary.length);
        for (let i = 0; i < binary.length; i++) wasmBytes[i] = binary.charCodeAt(i);
      } else if (typeof body.wasm_url === "string") {
        const resp = await fetch(body.wasm_url as string, { signal: AbortSignal.timeout(10_000) });
        if (!resp.ok) return jsonResp({ ok: false, error: `wasm_url fetch ${resp.status}` }, 400);
        wasmBytes = new Uint8Array(await resp.arrayBuffer());
      } else {
        return jsonResp({ ok: false, error: "wasm_b64 ou wasm_url requis" }, 400);
      }

      if (wasmBytes.length > MAX_SIZE)
        return jsonResp({ ok: false, error: `trop grand: ${wasmBytes.length} bytes` }, 400);

      const { instance } = await WebAssembly.instantiate(wasmBytes as BufferSource, {
        env: {
          memory: new WebAssembly.Memory({ initial: 1 }),
          abort: () => { throw new Error("WASM abort()"); },
        },
      });

      const fn = (instance.exports as Record<string, unknown>)[funcName];
      if (typeof fn !== "function") {
        const exports = Object.keys(instance.exports).join(", ");
        return jsonResp({ ok: false, error: `'${funcName}' not exported. Available: ${exports}` }, 400);
      }

      const result = fn(...args);
      return jsonResp({ ok: true, return_value: result ?? null,
                        duration_ms: Date.now() - t0, func: funcName });
    } catch (e) {
      return jsonResp({ ok: false, error: String(e), duration_ms: Date.now() - t0 }, 500);
    }
  }

  // ─── /api/wasm/health ─────────────────────────────────────────────
  if (path === "/api/wasm/health" && method === "GET") {
    return jsonResp({ ok: true, backend: "deno-native-wasm", startup_us: "<10",
                      max_size_mb: 4, version: VERSION });
  }

  // ─── Root ─────────────────────────────────────────────────────────
  if (path === "/") {
    return new Response(
      `Nokido Deno WebHub :${PORT} — endpoints :\n` +
        `  GET  /health\n` +
        `  GET  /api/opsec/{status,audit}  POST /api/opsec/{set,lock}\n` +
        `  GET  /api/anatomy/state         GET  /anatomy\n` +
        `  GET  /api/events/{history,stats} POST /api/events/publish\n` +
        `  POST /api/wasm/run              GET  /api/wasm/health\n`,
      { headers: { "Content-Type": "text/plain; charset=utf-8" } }
    );
  }

  return new Response("404 Not Found", { status: 404 });
}

// ──────────────────────────────────────────────────────────────────────
// Server
// ──────────────────────────────────────────────────────────────────────
Deno.serve({ port: PORT, hostname: "127.0.0.1" }, async (req) => {
  const start = Date.now();
  const url = new URL(req.url);
  try {
    const resp = await handleRequest(req);
    const dt = Date.now() - start;
    console.log(`[${req.method}] ${url.pathname} ${resp.status} ${dt}ms`);
    return resp;
  } catch (e) {
    console.error(`[ERR] ${url.pathname} ${e}`);
    return jsonResp({ error: String(e) }, 500);
  }
});
