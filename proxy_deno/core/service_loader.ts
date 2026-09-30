/**
 * service_loader.ts — load the declarative service registry (services.toml)
 * for the Nokido supervisor.
 *
 * Step 1 of the portable-supervisor migration (docs/portable_supervisor_plan.md).
 * loadServices() returns the ServiceDef[] parsed from services.toml, or null
 * on ANY error so the supervisor can fall back to its in-code array — editing
 * services.toml therefore cannot brick the boot path.
 *
 * Self-test:  deno run --allow-read proxy_deno/core/service_loader.ts
 */

import { parse } from "https://deno.land/std@0.224.0/toml/mod.ts";
import { fromFileUrl } from "https://deno.land/std@0.224.0/path/mod.ts";

export interface ServiceDef {
  name: string;
  wave: number;
  cmd: string;
  args: string[];
  cwd: string;
  env?: Record<string, string>;
  deps?: number[];
  port?: number;
  essential: boolean;
  disabled?: boolean;
  type?: "process" | "provider";
  startCmd?: string[];
  stopCmd?: string[];
  llmPool?: boolean;
  neverSleep?: boolean;
  /**
   * Route the service through forge_runas_launcher.py instead of spawning the
   * cmd directly. Three modes :
   *   - "sandbox-online"  : run as LaForgeSbxOnline (loopback + outbound OK)
   *   - "sandbox-offline" : run as LaForgeSbxOffline (loopback only, no net)
   *   - "interactive"     : run in the active console user session via
   *                         WTSQueryUserToken (needs GUI desktop — Playwright
   *                         Firefox, OAuth browser flows). Caller process
   *                         (supervisor / NSSM) needs SeTcbPrivilege
   *                         (LocalSystem has it by default).
   * All three wrap the child in a Job Object with KILL_ON_JOB_CLOSE so a
   * supervisor restart cleans up children deterministically.
   */
  runAs?: "sandbox-online" | "sandbox-offline" | "interactive";
  /**
   * Path (relative to ROOT) to a JSON heartbeat file the service writes.
   * Thresholds depend on heartbeat_tier (default "normal"). Convention
   * JSON: {service, ts, iter, stats, health}. See docs/heartbeat_schema.md.
   */
  heartbeat?: string;
  /**
   * Heartbeat reactivity tier (Phase 6 régulation hydraulique multi-échelle).
   * - "fast"   poll 5s,  degraded 30s,  restart 90s   (services critiques RT)
   * - "normal" poll 30s, degraded 300s, restart 600s  (default)
   * - "slow"   poll 60s, degraded 1800s, restart 3600s (long-cycle daemons 6h/12h)
   * Économise des reads pour les loops lents ; durcit la détection pour les RT.
   */
  heartbeat_tier?: "fast" | "normal" | "slow";
  /**
   * CONTRAT DE SANTE APPLICATIVE (2026-09-11). Chemin HTTP a interroger sur
   * `port` pour savoir si l'APPLICATION repond -- pas seulement si le socket
   * accepte. Sans ce champ, le service est HEALTH_UNKNOWN : un etat DIT, qui
   * ne se range jamais du cote sain.
   *
   * Defaut mesure ce jour-la : NokidoWebHub a tenu :7400 en LISTENING plus de
   * cinq heures avec /health en TIMEOUT, et le superviseur le declarait
   * `running` sur le seul `isPortOpen()`. TRANSPORT_UP n'est pas APPLICATION_UP.
   *
   * Il n'existe AUCUN chemin universel -- mesure du 2026-08-18 :
   *   :7400 /health=200  :7474 /health=401 mais /=200  :7500 /health=404 mais /=200
   * D'ou un chemin PAR SERVICE, jamais une sonde unique imposee a tous.
   */
  health_path?: string;
}

function resolveVars(s: string, vars: Record<string, string>): string {
  return s.replace(/\$\{(\w+)\}/g, (_m, k) => vars[k] ?? `\${${k}}`);
}

/**
 * Load services.toml. `runtimeVars` (e.g. absolute ROOT/PROXY_DIR computed by
 * the supervisor) override the toml [vars] table. Returns null on any failure.
 */
// Cache par empreinte (mtime+taille) — POURQUOI, mesure 2026-07-29.
// `readTextFileSync` + `parse` sur 58 Ko de TOML est SYNCHRONE : ca bloque
// l'event loop Deno ENTIERE. Or le superviseur rappelle loadServices() avant
// CHAQUE wake/restart ("def refreshed from toml before wake"), et le cycle
// circadien en declenche 9 d'affilee. Pendant ces rafales, aucun `await` ne
// progresse : les lectures de heartbeat depassaient 1 s et 22 services sur 26
// restaient `never_read` — un capteur aveugle, donc AUCUNE autoregulation.
// L'intention d'origine (relire le toml pour prendre les editions a chaud) est
// conservee : on garde un statSync (quelques microsecondes) et on ne relit +
// reparse QUE si le fichier a change.
let _cacheEmpreinte = "";
let _cacheServices: ServiceDef[] | null = null;

export function loadServices(
  tomlPath: string,
  runtimeVars: Record<string, string> = {},
): ServiceDef[] | null {
  try {
    const _st = Deno.statSync(tomlPath);
    const _empreinte = [
      tomlPath,
      _st.mtime?.getTime() ?? 0,
      _st.size,
      JSON.stringify(runtimeVars),
    ].join("|");
    if (_empreinte === _cacheEmpreinte && _cacheServices) {
      return _cacheServices;
    }
    const raw = Deno.readTextFileSync(tomlPath);
    // deno-lint-ignore no-explicit-any
    const doc = parse(raw) as any;
    const vars: Record<string, string> = {
      ...(doc.vars ?? {}),
      ...runtimeVars,
    };
    const rv = (x: unknown) => resolveVars(String(x ?? ""), vars);

    const out: ServiceDef[] = [];
    for (const s of (doc.service ?? [])) {
      const svc: ServiceDef = {
        name: String(s.name),
        wave: Number(s.wave),
        cmd: rv(s.cmd),
        args: Array.isArray(s.args) ? s.args.map(rv) : [],
        cwd: rv(s.cwd ?? "."),
        essential: Boolean(s.essential),
      };
      if (s.env && typeof s.env === "object") {
        svc.env = {};
        for (const [k, v] of Object.entries(s.env)) svc.env[k] = rv(v);
      }
      if (Array.isArray(s.deps)) svc.deps = s.deps.map(Number);
      if (s.port != null) svc.port = Number(s.port);
      if (s.disabled) svc.disabled = true;
      if (s.type === "provider" || s.type === "process") svc.type = s.type;
      if (Array.isArray(s.startCmd)) svc.startCmd = s.startCmd.map(rv);
      if (Array.isArray(s.stopCmd)) svc.stopCmd = s.stopCmd.map(rv);
      if (s.llmPool) svc.llmPool = true;
      if (s.neverSleep) svc.neverSleep = true;
      if (
        s.runAs === "sandbox-online" || s.runAs === "sandbox-offline" ||
        s.runAs === "interactive"
      ) {
        svc.runAs = s.runAs;
      }
      if (typeof s.health_path === "string" && s.health_path.length > 0) {
        svc.health_path = s.health_path;
      }
      if (typeof s.heartbeat === "string" && s.heartbeat.length > 0) {
        svc.heartbeat = rv(s.heartbeat);
      }
      if (
        s.heartbeat_tier === "fast" || s.heartbeat_tier === "normal" ||
        s.heartbeat_tier === "slow"
      ) {
        svc.heartbeat_tier = s.heartbeat_tier;
      }

      if (!svc.name || !Number.isFinite(svc.wave)) {
        throw new Error(`invalid service entry: ${JSON.stringify(s.name)}`);
      }
      if (!svc.cmd && svc.type !== "provider") {
        throw new Error(`service ${svc.name}: empty cmd`);
      }
      out.push(svc);
    }
    if (out.length === 0) throw new Error("no [[service]] entries");
    _cacheEmpreinte = _empreinte;
    _cacheServices = out;
    return out;
  } catch (e) {
    console.error(
      `[supervisor] services.toml load failed -> in-code fallback: ${e}`,
    );
    return null;
  }
}

/** Default path: services.toml next to this module. */
export function defaultTomlPath(): string {
  return fromFileUrl(new URL("./services.toml", import.meta.url));
}

// ── self-test ──────────────────────────────────────────────────────────
if (import.meta.main) {
  const svcs = loadServices(defaultTomlPath(), {
    ROOT: ".",
    PROXY_DIR: "./proxy_deno",
  });
  if (!svcs) {
    console.error("FAIL: loader returned null");
    Deno.exit(1);
  }
  console.log(`OK: ${svcs.length} services loaded`);
  for (const s of svcs) {
    const flags = [
      s.disabled ? "disabled" : "",
      s.llmPool ? "llmPool" : "",
      s.type === "provider" ? "provider" : "",
    ].filter(Boolean).join(",");
    console.log(
      `  w${s.wave} ${s.name.padEnd(24)} port=${s.port ?? "-"} ` +
        `${flags}  cmd=${s.cmd.slice(0, 40)}`,
    );
  }
}
