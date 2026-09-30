/**
 * supervisor.ts — LaForge-Master process supervisor
 *
 * Single Deno process replacing 17 NSSM services.
 * Manages dependencies, auto-restart with backoff, centralized logging,
 * resource-aware sleep of non-essential services.
 *
 * Control API: GET/POST :8765/supervisor/*
 * Install: nssm install LaForge-Master deno.exe run -A proxy_deno/core/supervisor.ts
 *
 * Author-Agent: CLAUDE
 */

import { join, resolve } from "https://deno.land/std/path/mod.ts";
import { ensureDir } from "https://deno.land/std@0.224.0/fs/mod.ts";

// ─────────────────────────────────────────────────────────────────────────────
// Constants
// ─────────────────────────────────────────────────────────────────────────────
const ROOT = resolve(Deno.cwd());
const LOG_DIR = join(ROOT, "logs", "supervisor");
const MINIFORGE = "%USERPROFILE%/miniforge3/python.exe";
const PY314 = "%USERPROFILE%/miniforge3/envs/laforge_py314/python.exe";
const DENO_EXE = "%USERPROFILE%/.deno/bin/deno.exe";
const PROXY_DIR = join(ROOT, "proxy_deno");
const LLAMA_EXE = "%USERPROFILE%/llama-vulkan/llama-server.exe";
const MODEL_7B = "D:/ollama/models/blobs/sha256-60e05f2100071479f596b964f89f510f057ce397ea22f2833a0cfe029bfc2463";
const DRAFT_1B = "D:/ollama/models/blobs/sha256-29d8c98fa6b098e200069bfb88b9508dc3e85586d20cba59f8dda9a808165104";
const CTRL_PORT = 8765;
const LOG_MAX_BYTES = 5 * 1024 * 1024; // 5 MB per service

const BACKOFF_MS = [1_000, 2_000, 4_000, 8_000, 16_000, 30_000];

// ─────────────────────────────────────────────────────────────────────────────
// Service definitions
// ─────────────────────────────────────────────────────────────────────────────
interface ServiceDef {
  name: string;
  cmd: string;
  args: string[];
  cwd: string;
  env?: Record<string, string>;
  deps?: number[];
  port?: number;
  essential: boolean;
  disabled?: boolean;
  // Provider type: cmd/args not used for spawn; use startCmd/stopCmd instead.
  // Process exits immediately after starting the real server (e.g. lms.exe).
  type?: "process" | "provider";
  startCmd?: string[];   // provider: command to start the server
  stopCmd?: string[];    // provider: command to stop the server
  llmPool?: boolean;     // true → mutually-exclusive LLM pool managed by supervisor
  neverSleep?: boolean;  // true → exempt from RAM-pressure homeostasis (lightweight services)
}

const SERVICES: ServiceDef[] = [
  // ── Tier 0: no deps ──────────────────────────────────────────────────────
  {
    name: "NokidoMCP",
    cmd: MINIFORGE,
    args: ["tools/nokido_hub.py"],
    cwd: ROOT,
    env: {
      PYTHONPATH: "%USERPROFILE%/miniforge3/Lib/site-packages",
      PYTHONHOME: "%USERPROFILE%/miniforge3",
      PYTHONIOENCODING: "utf-8",
    },
    port: 8766,
    essential: true,
  },
  {
    name: "NokidoOllama",
    cmd: "%USERPROFILE%/AppData/Local/Programs/Ollama/ollama.exe",
    args: ["serve"],
    cwd: "%USERPROFILE%/AppData/Local/Programs/Ollama",
    env: {
      OLLAMA_MODELS: "D:/ollama/models",
      OLLAMA_KEEP_ALIVE: "30s",
      OLLAMA_MAX_LOADED_MODELS: "1",
      OLLAMA_HOST: "127.0.0.1:11434",
    },
    port: 11434,
    essential: true,
  },
  {
    name: "NokidoNetcfgMCP",
    cmd: "%NOKIDO_WORKSPACE%/netcfg-agent-mcp/dist/netcfg-agent-mcp.exe",
    args: ["serve", "--transport", "http", "--host", "127.0.0.1", "--port", "8767", "--standalone"],
    cwd: "%NOKIDO_WORKSPACE%/netcfg-agent-mcp",
    port: 8767,
    essential: false,
    neverSleep: true,   // lightweight exe, needed for netcfg MCP tools
  },
  {
    name: "NokidoLlamaNative",
    cmd: LLAMA_EXE,
    args: [
      "-m", MODEL_7B,
      "-md", DRAFT_1B,
      "--host", "127.0.0.1", "--port", "8091",
      "-ngl", "99", "-ngld", "99",
      "-c", "32768", "-cd", "32768",
      "-b", "2048", "-ub", "512",
      "-ctk", "q8_0", "-ctv", "q8_0",
      "-fa", "auto",
      "--cache-prompt", "--cache-reuse", "256",
      "--context-shift", "--mlock",
      "--metrics", "--props", "--slots", "--jinja",
      "--reasoning", "auto",
      "-a", "qwen,qwen2.5-coder,laforge-coder",
      "--prio", "1", "--threads", "-1", "-np", "-1",
      "--draft-max", "16", "--draft-min", "4", "--draft-p-min", "0.65",
      "--webui-mcp-proxy",
      "--webui-config-file", join(ROOT, "data/llamacpp_webui_config.json"),
      "--path", join(ROOT, "data/llamacpp_webui_fr"),
      "--override-kv", "general.name=str:Qwen2.5-Coder-7B-Instruct-Q4_K_M",
    ],
    cwd: ROOT,
    port: 8091,
    essential: false,
    llmPool: true,
  },
  {
    name: "NokidoLlamaRouter",
    cmd: LLAMA_EXE,
    args: [
      "--models-dir", join(ROOT, "data/llm_models"),
      "--models-max", "2", "--models-autoload",
      "--host", "127.0.0.1", "--port", "8092",
      "-ngl", "99", "-c", "32768",
      "-ctk", "q8_0", "-ctv", "q8_0",
      "-fa", "auto",
      "--cache-prompt", "--cache-reuse", "256",
      "--context-shift", "--mlock",
      "--metrics", "--slots", "--jinja",
      "--reasoning", "auto",
      "--prio", "1", "--threads", "-1", "-np", "-1",
      "--webui-mcp-proxy",
      "--webui-config-file", join(ROOT, "data/llamacpp_webui_config.json"),
    ],
    cwd: ROOT,
    port: 8092,
    essential: false,
    llmPool: true,
  },
  {
    name: "NokidoLMStudio",
    cmd: "",   // provider type — cmd unused
    args: [],
    cwd: "%USERPROFILE%/.lmstudio",
    type: "provider",
    // llmster daemon: `lms daemon up` starts background process, `lms daemon down` stops it
    startCmd: ["%USERPROFILE%/.lmstudio/bin/lms.exe", "daemon", "up"],
    stopCmd:  ["%USERPROFILE%/.lmstudio/bin/lms.exe", "daemon", "down"],
    port: 1234,
    essential: false,
    llmPool: true,
  },

  // ── Tier 1: depends on hub :8766 ─────────────────────────────────────────
  {
    name: "NokidoDenoProxy",
    cmd: DENO_EXE,
    args: ["run", "--allow-net", "--allow-read", "--allow-write", "--allow-env", "--allow-run", "--no-check", "main.ts"],
    cwd: PROXY_DIR,
    env: { LAFORGE_PERSIST_DIR: join(ROOT, "nokido_persist") },
    deps: [8766],
    port: 8000,
    essential: true,
  },
  {
    name: "NokidoDenoWebHub",
    cmd: DENO_EXE,
    args: ["run", "--allow-net", "--allow-read", "--allow-write", "--allow-env", "--allow-run", "--no-check", "web_hub/main.ts"],
    cwd: PROXY_DIR,
    env: {
      LAFORGE_DENO_WEBHUB_PORT: "7401",
      LAFORGE_PERSIST_DIR: join(ROOT, "nokido_persist"),
      LAFORGE_PYTHON: MINIFORGE,
    },
    deps: [8766],
    port: 7401,
    essential: true,
  },
  {
    name: "NokidoDenoHubMCP",
    cmd: DENO_EXE,
    args: ["run", "--allow-net", "--allow-read", "--allow-env", "--no-check", "hub_mcp/main.ts"],
    cwd: PROXY_DIR,
    env: {
      LAFORGE_DENO_HUB_PORT: "8769",
      LAFORGE_PERSIST_DIR: join(ROOT, "nokido_persist"),
    },
    deps: [8766],
    port: 8769,
    essential: false,
  },
  {
    name: "NokidoWebHub",
    cmd: MINIFORGE,
    args: ["tools/nokido_web_hub.py", "--host", "127.0.0.1", "--port", "7400"],
    cwd: ROOT,
    env: { PYTHONNOUSERSITE: "1", PYTHONIOENCODING: "utf-8" },
    deps: [8766],
    port: 7400,
    essential: false,
    neverSleep: true,   // UI dashboard — must stay up, ~150MB footprint
  },
  {
    name: "NokidoOpenAIProxy",
    cmd: MINIFORGE,
    args: ["tools/forge_openai_proxy.py"],
    cwd: ROOT,
    env: { PYTHONIOENCODING: "utf-8" },
    deps: [8766],
    essential: false,
  },
  {
    name: "NokidoGeminiDaemon",
    cmd: PY314,
    args: ["tools/gemini_poll_daemon.py", "--mode", "active", "--interval", "30"],
    cwd: ROOT,
    env: { PYTHONNOUSERSITE: "1", PYTHONIOENCODING: "utf-8" },
    deps: [8766],
    essential: false,
  },
  {
    name: "NokidoGraph",
    cmd: PY314,
    args: ["app/forge_graph_explorer.py"],
    cwd: ROOT,
    env: { PYTHONNOUSERSITE: "1", PYTHONIOENCODING: "utf-8", PYTHONUTF8: "1" },
    deps: [8766],
    essential: false,
  },
  {
    name: "NokidoHebbian",
    cmd: PY314,
    args: ["app/forge_hebbian_linker.py", "--daemon"],
    cwd: ROOT,
    env: { PYTHONNOUSERSITE: "1", PYTHONIOENCODING: "utf-8" },
    deps: [8766],
    essential: false,
  },
  {
    name: "NokidoHomeostasis",
    cmd: PY314,
    args: ["app/forge_homeostasis_orchestrator.py", "--daemon"],
    cwd: ROOT,
    env: { PYTHONNOUSERSITE: "1", PYTHONIOENCODING: "utf-8" },
    deps: [8766],
    essential: false,
  },
  {
    name: "NokidoAutonomousLoops",
    cmd: PY314,
    args: ["app/forge_autonomous_loops.py", "--daemon", "--tick", "60"],
    cwd: ROOT,
    env: { PYTHONNOUSERSITE: "1", PYTHONIOENCODING: "utf-8", PYTHONUTF8: "1" },
    deps: [8766],
    essential: false,
  },
  {
    name: "NokidoRSSWatcher",
    cmd: PY314,
    args: ["app/forge_rss_watcher.py", "--daemon"],
    cwd: ROOT,
    env: { PYTHONNOUSERSITE: "1", PYTHONIOENCODING: "utf-8" },
    deps: [8766],
    essential: false,
  },
  {
    name: "NokidoCapture",
    cmd: MINIFORGE,
    args: ["-u", "-m", "cli_tail_capture", "--watch", "--interval", "15", "-v"],
    cwd: join(ROOT, "tools"),
    env: { PYTHONIOENCODING: "utf-8" },
    deps: [8766],
    essential: false,
  },
];

// ─────────────────────────────────────────────────────────────────────────────
// LLM pool — max 1 heavy LLM active besides Ollama (Radeon 780M UMA ~20GB shared)
const LLM_POOL_MAX = 1;

// ─────────────────────────────────────────────────────────────────────────────
// State
// ─────────────────────────────────────────────────────────────────────────────
type ServiceStatus = "stopped" | "starting" | "running" | "restarting" | "sleeping" | "disabled";

interface ServiceState {
  def: ServiceDef;
  status: ServiceStatus;
  proc: Deno.ChildProcess | null;
  pid: number | null;
  restartCount: number;
  lastStartMs: number;
  backoffIdx: number;
  logFile: Deno.FsFile | null;
}

const states = new Map<string, ServiceState>();

for (const def of SERVICES) {
  if (def.disabled) continue;
  // LLM pool members start sleeping — activated only via explicit /supervisor/llm/activate
  // Prevents loading 4-8GB models into RAM at boot with no active tasks.
  const initialStatus: ServiceStatus = def.llmPool ? "sleeping" : "stopped";
  states.set(def.name, {
    def,
    status: initialStatus,
    proc: null,
    pid: null,
    restartCount: 0,
    lastStartMs: 0,
    backoffIdx: 0,
    logFile: null,
  });
}

// ─────────────────────────────────────────────────────────────────────────────
// Helpers
// ─────────────────────────────────────────────────────────────────────────────
async function isPortOpen(port: number, timeoutMs = 800): Promise<boolean> {
  try {
    const conn = await Promise.race([
      Deno.connect({ hostname: "127.0.0.1", port }),
      new Promise<never>((_, rej) => setTimeout(() => rej(new Error("timeout")), timeoutMs)),
    ]);
    (conn as Deno.TcpConn).close();
    return true;
  } catch {
    return false;
  }
}

async function waitForPort(port: number, timeoutMs = 60_000): Promise<boolean> {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    if (await isPortOpen(port)) return true;
    await delay(500);
  }
  return false;
}

function delay(ms: number) {
  return new Promise<void>((r) => setTimeout(r, ms));
}

function ts() {
  return new Date().toISOString().replace("T", " ").slice(0, 23);
}

function log(msg: string) {
  console.log(`[${ts()}] [SUPERVISOR] ${msg}`);
}

async function openLog(name: string): Promise<Deno.FsFile> {
  const path = join(LOG_DIR, `${name}.log`);
  try {
    const info = await Deno.stat(path);
    if (info.size > LOG_MAX_BYTES) {
      // rotate: keep last half
      const content = await Deno.readTextFile(path);
      const half = content.slice(Math.floor(content.length / 2));
      await Deno.writeTextFile(path, `[ROTATED ${ts()}]\n` + half);
    }
  } catch { /* new file */ }
  return await Deno.open(path, { create: true, append: true, write: true });
}

async function pipeToLog(
  stream: ReadableStream<Uint8Array>,
  file: Deno.FsFile,
  name: string,
) {
  const reader = stream.getReader();
  const enc = new TextEncoder();
  const dec = new TextDecoder();
  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      const text = dec.decode(value);
      const lines = text
        .split("\n")
        .filter((l) => l.trim())
        .map((l) => `${ts()} ${l}\n`)
        .join("");
      if (lines) {
        await file.write(enc.encode(lines));
        // mirror first 120 chars to supervisor stdout
        console.log(`[${name}] ${text.trim().slice(0, 120)}`);
      }
    }
  } catch { /* process closed */ }
}

// ─────────────────────────────────────────────────────────────────────────────
// Service lifecycle
// ─────────────────────────────────────────────────────────────────────────────
/** Stop a provider-type service using its stopCmd. */
async function stopProvider(state: ServiceState) {
  const sc = state.def.stopCmd;
  if (!sc?.length) return;
  try {
    const { code } = await new Deno.Command(sc[0], { args: sc.slice(1), stdout: "piped", stderr: "piped" }).output();
    log(`${state.def.name}: stopCmd exit ${code}`);
  } catch (e) { log(`${state.def.name}: stopCmd error ${e}`); }
  state.proc = null; state.pid = null; state.status = "stopped";
}

/** Unload Ollama's currently-loaded model to free UMA VRAM before a llama-server starts. */
async function ollamaUnloadModels(): Promise<void> {
  // Ollama API: keep_alive=0s forces immediate unload of the active model.
  // We don't know the loaded model name, so we probe /api/tags and unload each.
  try {
    const tags = await fetch("http://127.0.0.1:11434/api/tags",
      { signal: AbortSignal.timeout(2000) });
    if (tags.ok) {
      const data = await tags.json() as { models?: { name: string }[] };
      for (const m of (data.models ?? [])) {
        try {
          const r = await fetch("http://127.0.0.1:11434/api/generate", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ model: m.name, keep_alive: "0s", prompt: "" }),
            signal: AbortSignal.timeout(3000),
          });
          if (r.ok) await r.body?.cancel();
          log(`[LLM-POOL] ollama unloaded model ${m.name}`);
        } catch { /* model may not be loaded — ok */ }
      }
    }
  } catch { /* Ollama not responding — skip */ }
  await delay(2000);  // allow GPU driver to release VRAM
}

/** Enforce LLM pool: sleep all pool members except `keepName`. */
async function enforcePool(keepName: string) {
  const pool = SERVICES.filter((s) => s.llmPool && s.name !== keepName);
  for (const def of pool) {
    const st = states.get(def.name);
    if (!st || st.status !== "running") continue;
    log(`[LLM-POOL] sleeping ${def.name} to free GPU for ${keepName}`);
    if (def.type === "provider") { await stopProvider(st); }
    else { try { st.proc?.kill("SIGTERM"); } catch { /* ok */ } }
    st.status = "sleeping";
  }
  // Unload Ollama VRAM — NokidoOllama is essential (no llmPool flag) so
  // enforcePool never stops it, but its loaded model occupies UMA memory
  // causing llama-server to OOM or crash on startup.
  await ollamaUnloadModels();
}

async function startService(state: ServiceState) {
  const { def } = state;
  if (state.status === "sleeping") return;

  // Wait for deps
  if (def.deps?.length) {
    log(`${def.name}: waiting for deps ${def.deps.join(",")}`);
    for (const port of def.deps) {
      const ok = await waitForPort(port, 90_000);
      if (!ok) {
        log(`${def.name}: dep :${port} never opened — aborting start`);
        return;
      }
    }
  }

  // Skip if port already open (external process or previous instance)
  if (def.port && await isPortOpen(def.port)) {
    log(`${def.name}: port :${def.port} already open — skipping start`);
    state.status = "running";
    return;
  }

  // LLM pool: enforce max before starting a heavy LLM
  if (def.llmPool) {
    const running = SERVICES.filter((s) => s.llmPool && s.name !== def.name)
      .filter((s) => states.get(s.name)?.status === "running");
    if (running.length >= LLM_POOL_MAX) await enforcePool(def.name);
  }

  state.status = "starting";
  state.lastStartMs = Date.now();

  // Provider type: use startCmd, then poll port for readiness
  if (def.type === "provider") {
    try {
      const sc = def.startCmd!;
      await new Deno.Command(sc[0], { args: sc.slice(1), stdout: "piped", stderr: "piped" }).output();
      // Poll port
      const up = def.port ? await waitForPort(def.port, 15_000) : true;
      if (up) {
        state.status = "running"; state.pid = null;
        log(`${def.name}: provider UP :${def.port}`);
      } else {
        log(`${def.name}: provider start timeout`);
        state.status = "stopped"; scheduleRestart(state);
      }
    } catch (e) {
      log(`${def.name}: provider startCmd failed — ${e}`);
      state.status = "stopped"; scheduleRestart(state);
    }
    return;
  }

  const envMerged = { ...Deno.env.toObject(), ...(def.env ?? {}) };

  try {
    const proc = new Deno.Command(def.cmd, {
      args: def.args,
      cwd: def.cwd,
      env: envMerged,
      stdout: "piped",
      stderr: "piped",
    }).spawn();

    state.proc = proc;
    state.pid = proc.pid;
    state.status = "running";
    log(`${def.name}: started PID ${proc.pid}`);

    // Open log file
    const lf = await openLog(def.name);
    state.logFile = lf;

    // Pipe stdout+stderr to log (non-blocking)
    pipeToLog(proc.stdout, lf, def.name);
    pipeToLog(proc.stderr, lf, def.name);

    // Watch for exit
    proc.status.then((s) => {
      const elapsed = Math.round((Date.now() - state.lastStartMs) / 1000);
      log(`${def.name}: exited code=${s.code} after ${elapsed}s (restart #${state.restartCount})`);
      try { lf.close(); } catch { /* already closed */ }
      state.logFile = null;
      state.proc = null;
      state.pid = null;
      // "sleeping" = kill volontaire homeostasis, "stopped" = stop manuel
      // Dans les deux cas on ne reschedule pas — startService() sera appelé explicitement
      if (state.status !== "sleeping" && state.status !== "stopped") {
        scheduleRestart(state);
      }
    });
  } catch (e) {
    log(`${def.name}: launch failed — ${e}`);
    state.status = "stopped";
    scheduleRestart(state);
  }
}

function scheduleRestart(state: ServiceState) {
  const ms = BACKOFF_MS[Math.min(state.backoffIdx, BACKOFF_MS.length - 1)];
  state.backoffIdx = Math.min(state.backoffIdx + 1, BACKOFF_MS.length - 1);
  state.restartCount++;
  state.status = "restarting";
  log(`${state.def.name}: restart in ${ms}ms (attempt ${state.restartCount})`);
  setTimeout(async () => {
    if (state.status === "sleeping") return;
    await startService(state);
  }, ms);
}

function resetBackoff(state: ServiceState) {
  // Called when service ran >30s (healthy run)
  if (Date.now() - state.lastStartMs > 30_000) {
    state.backoffIdx = 0;
  }
}

// ─────────────────────────────────────────────────────────────────────────────
// Resource monitor
// ─────────────────────────────────────────────────────────────────────────────
async function getMemUsagePct(): Promise<number> {
  try {
    const cmd = new Deno.Command("powershell", {
      args: ["-NoProfile", "-Command",
        "(Get-CimInstance Win32_OperatingSystem | Select -Expand FreePhysicalMemory) / " +
        "(Get-CimInstance Win32_ComputerSystem | Select -Expand TotalPhysicalMemory) * 100"
      ],
      stdout: "piped", stderr: "piped",
    });
    const { stdout } = await cmd.output();
    const free = parseFloat(new TextDecoder().decode(stdout).trim());
    return 100 - free; // used %
  } catch {
    return 0;
  }
}

// RAM thresholds — Radeon 780M UMA takes ~2GB from 16GB shared RAM.
// With Ollama loaded (~4-6GB) + Windows (~4GB), baseline is ~65-75%.
// 85% was too aggressive; raise to 92% (sleep) / 85% (wake).
const RAM_SLEEP_PCT = 92;   // sleep non-essential when RAM > this
const RAM_WAKE_PCT  = 85;   // wake sleeping services when RAM < this

async function resourceLoop() {
  while (true) {
    await delay(60_000);
    const memPct = await getMemUsagePct();
    if (memPct > RAM_SLEEP_PCT) {
      log(`RAM ${memPct.toFixed(1)}% > ${RAM_SLEEP_PCT}% — sleeping non-essential services`);
      for (const [, state] of states) {
        // Grace period 5min : ne pas endormir un service qui vient de démarrer
        // neverSleep: exempt UI and lightweight MCP servers from RAM pressure
        const uptime = Date.now() - state.lastStartMs;
        if (!state.def.essential && !state.def.neverSleep
            && state.status === "running" && state.proc
            && uptime > 5 * 60_000) {
          log(`Sleeping ${state.def.name} (uptime ${Math.round(uptime/1000)}s)`);
          state.proc.kill("SIGTERM");
          state.status = "sleeping";
        }
      }
    } else if (memPct < RAM_WAKE_PCT) {
      // Wake sleeping non-essential — but NEVER auto-wake llmPool members.
      // LLM models (4-8GB each) must be activated explicitly via /supervisor/llm/activate.
      for (const [, state] of states) {
        if (!state.def.essential && !state.def.llmPool && state.status === "sleeping") {
          log(`Waking ${state.def.name} (RAM now ${memPct.toFixed(1)}%)`);
          state.status = "stopped";
          state.backoffIdx = 0;
          startService(state);
        }
      }
    }
    // Reset backoff for long-running services
    for (const [, state] of states) {
      if (state.status === "running") resetBackoff(state);
    }
  }
}

// ─────────────────────────────────────────────────────────────────────────────
// Control API :8765
// ─────────────────────────────────────────────────────────────────────────────
function jsonResp(data: unknown, status = 200) {
  return new Response(JSON.stringify(data, null, 2), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

async function handleCtrl(req: Request): Promise<Response> {
  const url = new URL(req.url);
  const p = url.pathname;

  // LLM pool: status + activate
  if (p === "/supervisor/llm/pool" && req.method === "GET") {
    const pool = SERVICES.filter((s) => s.llmPool).map((s) => ({
      name: s.name, port: s.port, type: s.type ?? "process",
      status: states.get(s.name)?.status ?? "unknown",
    }));
    return jsonResp({ pool, max_active: LLM_POOL_MAX });
  }

  if (p.startsWith("/supervisor/llm/activate/") && req.method === "POST") {
    const name = p.replace("/supervisor/llm/activate/", "");
    const state = states.get(name);
    if (!state?.def.llmPool) return jsonResp({ error: "not in llm pool" }, 404);
    await enforcePool(name);
    state.status = "stopped"; state.backoffIdx = 0;
    startService(state);
    return jsonResp({ ok: true, activating: name });
  }

  if (p === "/supervisor/status") {
    const result: Record<string, unknown> = {};
    for (const [name, state] of states) {
      result[name] = {
        status: state.status,
        pid: state.pid,
        restarts: state.restartCount,
        port: state.def.port,
        essential: state.def.essential,
        uptime_s: state.lastStartMs > 0 ? Math.round((Date.now() - state.lastStartMs) / 1000) : null,
      };
    }
    return jsonResp({ ts: ts(), services: result });
  }

  const m = p.match(/^\/supervisor\/(restart|sleep|wake)\/(.+)$/);
  if (m && (req.method === "POST" || req.method === "GET")) {
    const [, action, name] = m;
    const state = states.get(name);
    if (!state) return jsonResp({ error: "unknown service" }, 404);

    if (action === "restart") {
      if (state.proc) state.proc.kill("SIGTERM");
      state.status = "stopped";
      state.backoffIdx = 0;
      await startService(state);
      return jsonResp({ ok: true, action: "restart", name });
    }
    if (action === "sleep") {
      if (state.proc) state.proc.kill("SIGTERM");
      state.status = "sleeping";
      return jsonResp({ ok: true, action: "sleep", name });
    }
    if (action === "wake") {
      if (state.status === "sleeping") {
        state.status = "stopped";
        state.backoffIdx = 0;
        // Petit délai pour laisser le port FIN_WAIT expirer après kill SIGTERM
        await delay(600);
        await startService(state);
      }
      return jsonResp({ ok: true, action: "wake", name });
    }
  }

  if (p === "/supervisor/logs" && req.method === "GET") {
    const name = url.searchParams.get("name");
    if (!name) return jsonResp({ error: "?name= required" }, 400);
    const logPath = join(LOG_DIR, `${name}.log`);
    try {
      const content = await Deno.readTextFile(logPath);
      const lines = content.split("\n").slice(-200).join("\n");
      return new Response(lines, { headers: { "Content-Type": "text/plain; charset=utf-8" } });
    } catch {
      return jsonResp({ error: "log not found" }, 404);
    }
  }

  return new Response("404", { status: 404 });
}

// ─────────────────────────────────────────────────────────────────────────────
// Graceful shutdown
// ─────────────────────────────────────────────────────────────────────────────
async function shutdown() {
  log("Shutting down all services...");
  const kills: Promise<void>[] = [];
  for (const [name, state] of states) {
    if (state.proc) {
      log(`Sending SIGTERM to ${name} PID ${state.pid}`);
      try { state.proc.kill("SIGTERM"); } catch { /* already dead */ }
      kills.push(state.proc.status.then(() => {}).catch(() => {}));
    }
  }
  await Promise.race([Promise.all(kills), delay(8_000)]);
  log("Shutdown complete.");
  Deno.exit(0);
}

// ─────────────────────────────────────────────────────────────────────────────
// Main
// ─────────────────────────────────────────────────────────────────────────────
async function main() {
  await ensureDir(LOG_DIR);
  log(`LaForge-Master supervisor starting — ${SERVICES.filter(s => !s.disabled).length} services`);
  log(`LOG_DIR=${LOG_DIR}`);
  log(`CTRL=:${CTRL_PORT}`);

  // Start control API
  Deno.serve({ port: CTRL_PORT, hostname: "127.0.0.1" }, handleCtrl);
  log(`Control API: http://127.0.0.1:${CTRL_PORT}/supervisor/status`);

  // Start resource monitor
  resourceLoop().catch((e) => log(`resourceLoop error: ${e}`));

  // Start services (tier 0 first, dep-based services will wait internally)
  for (const [, state] of states) {
    // Fire all in parallel; each waits for its own deps internally
    startService(state).catch((e) => log(`${state.def.name} start error: ${e}`));
    // Small stagger to avoid log flood
    await delay(200);
  }

  // SIGINT handler (Windows-compatible)
  try {
    Deno.addSignalListener("SIGINT", () => { shutdown(); });
  } catch { /* signal not supported on this platform */ }

  // Keep main alive
  await new Promise<void>(() => {});
}

main();
