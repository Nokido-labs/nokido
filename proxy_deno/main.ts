import { processLLMIntent } from "./core/brain.ts";
import "./core/vault.ts";
import {
  initPersistence,
  shutdownPersistence,
  getState,
  setState,
  vaultSet,
  vaultGet,
  vaultResolve,
  vaultDelete,
  vaultSize,
  vaultCheckpoint,
  brainSnapshot,
  PERSIST_PATHS,
} from "./core/persistence.ts";
import { forgeTool } from "./core/tool_smith.ts";
import { auditGeneratedTool } from "./core/code_critic.ts";
import "./organs/kidney_monitor.ts";
import "./organs/wasm_motor.ts";
import "./organs/mcp_hub_bridge.ts";
import "./organs/hub_forwarder.ts";
import { getJobStatus } from "./organs/kidney_monitor.ts";

/**
 * Point d'entrée du Proxy Nokido Deno
 */

// organe exegol_gatekeeper retire lors du nettoyage de surface : import rendu
// optionnel pour ne pas crash-looper le proxy si le fichier est absent
// (restaurable par l'owner au besoin — cf separation des composants specialises).
try {
  await import("./organs/exegol_gatekeeper.ts");
} catch (_e) {
  console.warn("[proxy] organe exegol_gatekeeper absent — demarrage sans cet organe");
}

await initPersistence();

// Shutdown propre : flush WAL + brain snapshot avant exit
const _shutdown = async () => {
  await shutdownPersistence();
  Deno.exit(0);
};
Deno.addSignalListener("SIGINT", _shutdown);
try { Deno.addSignalListener("SIGTERM", _shutdown); } catch (_) { /* SIGTERM unsupported on Windows */ }

// SECURITY 2026-05-02 : bind explicit, default 127.0.0.1.
// Override via env LAFORGE_PROXY_BIND_HOST=100.x.y.z (Tailscale IP) or 0.0.0.0 (LAN, NOT recommended).
const BIND_HOST = Deno.env.get("LAFORGE_PROXY_BIND_HOST") ?? "127.0.0.1";
const BIND_PORT = parseInt(Deno.env.get("LAFORGE_PROXY_PORT") ?? "8000", 10);
const PROXY_TOKEN = Deno.env.get("LAFORGE_PROXY_TOKEN") ?? "";  // empty = dev mode no auth

console.log(`🚀 Proxy Nokido (Deno) démarré sur ${BIND_HOST}:${BIND_PORT}`);
if (!PROXY_TOKEN) {
  console.warn("[SECURITY] LAFORGE_PROXY_TOKEN env not set — /intent endpoint UNAUTHENTICATED. Set bearer token for production.");
}

Deno.serve({ port: BIND_PORT, hostname: BIND_HOST }, async (req) => {
  const url = new URL(req.url);

  // Endpoint de statut (pour le suivi des JobIDs)
  if (url.pathname === "/status" && req.method === "GET") {
    const jobId = url.searchParams.get("jobId");
    if (!jobId) return new Response("Missing jobId", { status: 400 });

    const status = getJobStatus(jobId);
    return new Response(JSON.stringify(status || { error: "Job not found" }), {
      headers: { "Content-Type": "application/json" }
    });
  }

  // Endpoint principal (Routage des intentions) — Phase 1.1 hardened
  if (url.pathname === "/intent" && req.method === "POST") {
    // SECURITY 2026-05-02 : bearer auth required when LAFORGE_PROXY_TOKEN is set.
    if (PROXY_TOKEN) {
      const auth = req.headers.get("Authorization") ?? "";
      const stripped = auth.startsWith("Bearer ") ? auth.slice(7) : "";
      // Constant-time-ish compare (best-effort in JS)
      let mismatch = stripped.length !== PROXY_TOKEN.length ? 1 : 0;
      for (let i = 0; i < Math.min(stripped.length, PROXY_TOKEN.length); i++) {
        mismatch |= stripped.charCodeAt(i) ^ PROXY_TOKEN.charCodeAt(i);
      }
      if (mismatch !== 0) {
        return new Response(JSON.stringify({ error: "unauthorized" }), {
          status: 401,
          headers: { "Content-Type": "application/json" }
        });
      }
    }
    const startedAt = Date.now();
    const agent = req.headers.get("X-Agent-Name") ?? "anonymous";
    const traceId = req.headers.get("X-Trace-Id") ?? crypto.randomUUID();
    try {
      const payload = await req.json();
      console.log(`[Gatekeeper] /intent IN agent=${agent} trace=${traceId} size=${JSON.stringify(payload).length}`);
      const response = await processLLMIntent(payload);
      const dt = Date.now() - startedAt;
      const status = (response as any)?.isError ? "REJECTED" : "ACCEPTED";
      console.log(`[Gatekeeper] /intent ${status} agent=${agent} trace=${traceId} dt=${dt}ms`);
      return new Response(JSON.stringify(response), {
        headers: {
          "Content-Type": "application/json",
          "X-Trace-Id": traceId,
        }
      });
    } catch (err) {
      const dt = Date.now() - startedAt;
      // `err` est de type unknown : sans ce garde, un throw non-Error journalise
      // "undefined" et l'incident devient illisible.
      const errMsg = err instanceof Error ? err.message : String(err);
      console.error(`[Gatekeeper] /intent ERROR agent=${agent} trace=${traceId} dt=${dt}ms err=${errMsg}`);
      return new Response(JSON.stringify({ isError: true, error: errMsg, traceId }), {
        status: 500,
        headers: {
          "Content-Type": "application/json",
          "X-Trace-Id": traceId,
        }
      });
    }
  }

  // ─── Nervous System Event Bus ─────────────────────────────────────
  if (url.pathname === "/event" && req.method === "POST") {
    try {
      const body = await req.json();
      const { bus } = await import("./core/nervous_system.ts");
      bus.publish({
        kind: body.kind ?? "alert",
        source: body.source ?? "hub",
        payload: body.payload ?? body,
        ts: Date.now(),
      });
      return new Response(JSON.stringify({ ok: true }), {
        headers: { "Content-Type": "application/json" },
      });
    } catch (err) {
      return new Response(JSON.stringify({ ok: false, error: (err as Error).message }), {
        status: 500, headers: { "Content-Type": "application/json" },
      });
    }
  }

  // ─── Persistence API ────────────────────────────────────────────────
  if (url.pathname === "/api/persist/state" && req.method === "GET") {
    return new Response(JSON.stringify(getState()), {
      headers: { "Content-Type": "application/json" },
    });
  }

  // ─── KILL SWITCH SÉMANTIQUE ────────────────────────────────────
  // POST = trigger (PARANOID + lock + network_kill=true)
  // DELETE = release (network_kill=false, lock + level préservés)
  if (url.pathname === "/api/persist/kill_switch" && req.method === "POST") {
    try {
      const body = await req.json().catch(() => ({}));
      const reason = body.reason ?? "human emergency via UI";
      // Use Python forge_opsec.trigger_kill_switch via subprocess
      const cmd = new Deno.Command("%USERPROFILE%/miniforge3/python.exe", {
        args: ["-c", `
import sys, json
sys.path.insert(0, r"%NOKIDO_WORKSPACE%/LaForge/app")
from forge_opsec import trigger_kill_switch
print(json.dumps(trigger_kill_switch(${JSON.stringify(reason)}), ensure_ascii=False))
`],
        stdout: "piped", stderr: "piped",
        env: { PYTHONIOENCODING: "utf-8", PYTHONUTF8: "1" },
      });
      const { stdout } = await cmd.output();
      const result = JSON.parse(new TextDecoder().decode(stdout).trim() || "{}");
      console.log(`🛑 [KILL_SWITCH] TRIGGERED reason="${reason}"`);
      return new Response(JSON.stringify(result), {
        headers: { "Content-Type": "application/json" },
      });
    } catch (err) {
      return new Response(JSON.stringify({ ok: false, error: String(err) }), {
        status: 500,
        headers: { "Content-Type": "application/json" },
      });
    }
  }

  if (url.pathname === "/api/persist/kill_switch" && req.method === "DELETE") {
    try {
      const body = await req.json().catch(() => ({}));
      const reason = body.reason ?? "human release via UI";
      const setBy = body.set_by ?? "human_ui";
      const cmd = new Deno.Command("%USERPROFILE%/miniforge3/python.exe", {
        args: ["-c", `
import sys, json
sys.path.insert(0, r"%NOKIDO_WORKSPACE%/LaForge/app")
from forge_opsec import release_kill_switch
print(json.dumps(release_kill_switch(set_by=${JSON.stringify(setBy)}, reason=${JSON.stringify(reason)}), ensure_ascii=False))
`],
        stdout: "piped", stderr: "piped",
        env: { PYTHONIOENCODING: "utf-8", PYTHONUTF8: "1" },
      });
      const { stdout } = await cmd.output();
      const result = JSON.parse(new TextDecoder().decode(stdout).trim() || "{}");
      console.log(`✅ [KILL_SWITCH] RELEASED by="${setBy}"`);
      return new Response(JSON.stringify(result), {
        headers: { "Content-Type": "application/json" },
      });
    } catch (err) {
      return new Response(JSON.stringify({ ok: false, error: String(err) }), {
        status: 500,
        headers: { "Content-Type": "application/json" },
      });
    }
  }

  if (url.pathname === "/api/persist/state" && req.method === "POST") {
    try {
      const body = await req.json();
      const next = await setState({
        opsec_level: body.opsec_level ?? undefined,
        human_locked: typeof body.human_locked === "boolean" ? body.human_locked : undefined,
        last_change_by: body.set_by ?? "api",
        last_reason: body.reason ?? "",
      });
      return new Response(JSON.stringify({ ok: true, state: next }), {
        headers: { "Content-Type": "application/json" },
      });
    } catch (err) {
      return new Response(JSON.stringify({ ok: false, error: String(err) }), {
        status: 500,
        headers: { "Content-Type": "application/json" },
      });
    }
  }

  if (url.pathname === "/api/persist/vault" && req.method === "POST") {
    try {
      const body = await req.json();
      // body : { op: "set"|"get"|"resolve"|"del", alias?, real?, mission?, text? }
      const op = body.op;
      if (op === "set") {
        await vaultSet(body.alias, body.real, body.mission ?? "default");
        return new Response(JSON.stringify({ ok: true, size: vaultSize() }));
      }
      if (op === "get") {
        return new Response(JSON.stringify(vaultGet(body.alias) ?? null));
      }
      if (op === "resolve") {
        return new Response(JSON.stringify({ resolved: vaultResolve(body.text ?? "") }));
      }
      if (op === "del") {
        await vaultDelete(body.alias);
        return new Response(JSON.stringify({ ok: true, size: vaultSize() }));
      }
      return new Response(JSON.stringify({ ok: false, error: "unknown op" }), { status: 400 });
    } catch (err) {
      return new Response(JSON.stringify({ ok: false, error: String(err) }), { status: 500 });
    }
  }

  if (url.pathname === "/api/persist/checkpoint" && req.method === "POST") {
    try {
      await vaultCheckpoint();
      const snap = await brainSnapshot();
      return new Response(JSON.stringify({ ok: true, brain_snapshot: snap, vault_size: vaultSize() }));
    } catch (err) {
      return new Response(JSON.stringify({ ok: false, error: String(err) }), { status: 500 });
    }
  }

  // ─── PHASE G — Tool Smithing JIT ────────────────────────────────
  // POST /api/forge/tool — pipeline complet draft + audit + persist
  // body: { spec: ToolSpec, draftProvider?, expertProvider?, maxIterations?, autoApproveScoreMin? }
  if (url.pathname === "/api/forge/tool" && req.method === "POST") {
    try {
      const body = await req.json();
      const report = await forgeTool(body.spec, {
        draftProvider: body.draftProvider,
        expertProvider: body.expertProvider,
        maxIterations: body.maxIterations,
        autoApproveScoreMin: body.autoApproveScoreMin,
      });
      console.log(`🛠 [forge] ${report.spec.name} → ${report.status} (score=${report.audit.score})`);
      return new Response(JSON.stringify(report, null, 2), {
        headers: { "Content-Type": "application/json" },
      });
    } catch (err) {
      return new Response(JSON.stringify({ ok: false, error: String(err) }), {
        status: 500,
        headers: { "Content-Type": "application/json" },
      });
    }
  }

  // POST /api/forge/audit — audit standalone (sans drafting)
  // body: { code: string, spec: ToolSpec, expertProvider? }
  if (url.pathname === "/api/forge/audit" && req.method === "POST") {
    try {
      const body = await req.json();
      const audit = await auditGeneratedTool(
        body.code, body.spec, body.expertProvider ?? "claude_sonnet"
      );
      return new Response(JSON.stringify(audit, null, 2), {
        headers: { "Content-Type": "application/json" },
      });
    } catch (err) {
      return new Response(JSON.stringify({ ok: false, error: String(err) }), {
        status: 500,
        headers: { "Content-Type": "application/json" },
      });
    }
  }

  // GET /api/forge/list — liste tools forgés (read forged_tools/)
  if (url.pathname === "/api/forge/list" && req.method === "GET") {
    try {
      const dir = `${PERSIST_PATHS.dir}/forged_tools`;
      const entries: Array<{ file: string; meta?: object }> = [];
      try {
        for await (const e of Deno.readDir(dir)) {
          if (e.isFile && e.name.endsWith(".meta.json")) {
            const meta = JSON.parse(await Deno.readTextFile(`${dir}/${e.name}`));
            entries.push({ file: e.name, meta });
          }
        }
      } catch (_e) { /* dir absent */ }
      return new Response(JSON.stringify({ count: entries.length, tools: entries }), {
        headers: { "Content-Type": "application/json" },
      });
    } catch (err) {
      return new Response(JSON.stringify({ ok: false, error: String(err) }), {
        status: 500,
        headers: { "Content-Type": "application/json" },
      });
    }
  }

  if (url.pathname === "/api/persist/info" && req.method === "GET") {
    return new Response(JSON.stringify({
      paths: PERSIST_PATHS,
      vault_size: vaultSize(),
      state: getState(),
    }), {
      headers: { "Content-Type": "application/json" },
    });
  }

  return new Response("Nokido Proxy Active", { status: 200 });
});
