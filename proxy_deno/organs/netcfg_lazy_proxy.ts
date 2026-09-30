/**
 * netcfg_lazy_proxy.ts — Wake-on-demand proxy pour NokidoNetcfgMCP
 *
 * Écoute sur :8767. Dès qu'une connexion arrive :
 *   1. Wake NokidoNetcfgMCP via supervisor API (port réel :8768)
 *   2. Attend que :8768 soit prêt (max 15s)
 *   3. Proxifie le trafic TCP bidirectionnel
 * Après IDLE_MS sans connexion → sleep NokidoNetcfgMCP.
 */

const LISTEN_PORT = 8767;
const BACKEND_PORT = 8768;
const SUPERVISOR_URL = "http://127.0.0.1:8765/supervisor";
const SERVICE_NAME = "NokidoNetcfgMCP";
const IDLE_MS = 5 * 60 * 1000; // 5 min
const WAKE_TIMEOUT_MS = 15_000;
const POLL_MS = 300;

let lastActivity = Date.now();
let backendAwake = false;

async function supervisorPost(action: string): Promise<boolean> {
  try {
    const r = await fetch(`${SUPERVISOR_URL}/${action}/${SERVICE_NAME}`, { method: "POST" });
    const j = await r.json();
    return j.ok === true;
  } catch { return false; }
}

async function isBackendReady(): Promise<boolean> {
  try {
    const conn = await Deno.connect({ hostname: "127.0.0.1", port: BACKEND_PORT });
    conn.close();
    return true;
  } catch { return false; }
}

async function wakeBackend(): Promise<boolean> {
  if (await isBackendReady()) { backendAwake = true; return true; }
  console.log(`[netcfg-proxy] waking ${SERVICE_NAME}…`);
  await supervisorPost("wake");
  const deadline = Date.now() + WAKE_TIMEOUT_MS;
  while (Date.now() < deadline) {
    await new Promise(r => setTimeout(r, POLL_MS));
    if (await isBackendReady()) { backendAwake = true; return true; }
  }
  console.error(`[netcfg-proxy] wake timeout`);
  return false;
}

async function pipe(src: Deno.Conn, dst: Deno.Conn) {
  try { await src.readable.pipeTo(dst.writable); } catch { /* closed */ }
}

async function handleConn(client: Deno.Conn) {
  lastActivity = Date.now();
  if (!await wakeBackend()) { client.close(); return; }
  try {
    const backend = await Deno.connect({ hostname: "127.0.0.1", port: BACKEND_PORT });
    lastActivity = Date.now();
    await Promise.all([pipe(client, backend), pipe(backend, client)]);
    lastActivity = Date.now();
  } catch { client.close(); }
}

// Idle watcher — sleep backend after IDLE_MS with 0 active connections
async function idleWatcher() {
  while (true) {
    await new Promise(r => setTimeout(r, 30_000));
    if (!backendAwake) continue;
    if (Date.now() - lastActivity > IDLE_MS) {
      console.log(`[netcfg-proxy] idle ${IDLE_MS / 60000}min — sleeping ${SERVICE_NAME}`);
      await supervisorPost("sleep");
      backendAwake = false;
      lastActivity = Date.now(); // reset to avoid immediate re-sleep
    }
  }
}

async function main() {
  const listener = Deno.listen({ hostname: "127.0.0.1", port: LISTEN_PORT });
  console.log(`[netcfg-proxy] lazy proxy :${LISTEN_PORT} → :${BACKEND_PORT} (idle ${IDLE_MS / 60000}min)`);
  idleWatcher();
  for await (const conn of listener) {
    handleConn(conn);
  }
}

main();
