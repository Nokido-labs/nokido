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
import { dirname, fromFileUrl } from "https://deno.land/std@0.224.0/path/mod.ts";

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
  /**
   * JOURNAL SANS PIPE (2026-10-01). Service Python lance par tools/forge_logboot.py : il ecrit
   * lui-meme son journal horodate, et le superviseur ne le pipe PAS. Le pool bloquant de Deno est
   * plafonne a 4 x coeurs logiques (16 -> 64) et chaque pipe d'enfant y immobilise un thread :
   * 114 lectures pour 64 threads mesurees, 51 journaux sur 56 livres par paquets. Ignore -- et dit
   * dans le journal du superviseur -- pour une commande non Python.
   */
  logboot?: boolean;
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
// CHEMINS MACHINE (2026-10-08). Mesure sur VM neuve (Windows, Linux, macOS ; run 37816375828) : 0 des 60 services
// actifs ne tournait, parce que le dist publie `[vars]` avec des chemins generises (`%USERPROFILE%/...`) que rien ne
// developpait (`launch failed -- NotFound`, puis 33 services en attente du hub). `${ROOT}/config/vars.local.toml`,
// ecrit par `nokido-doctor --ecrire-vars` et jamais versionne, porte les chemins de CETTE machine et passe par-dessus
// `[vars]` ; `%NOM%` est developpe depuis l'environnement ; un chemin reste non resolu est DIT au journal au lieu
// d'etre lance a l'aveugle dix fois. Sans le fichier, le poste de reference est inchange.
function _varsLocales(root: string): { vars: Record<string, string>; empreinte: string } {
  const p = `${root}/config/vars.local.toml`;
  try {
    const st = Deno.statSync(p);
    // deno-lint-ignore no-explicit-any
    const doc = parse(Deno.readTextFileSync(p)) as any;
    return { vars: doc.vars ?? {}, empreinte: `${st.mtime?.getTime() ?? 0}:${st.size}` };
  } catch (e) {
    if (e instanceof Deno.errors.NotFound) return { vars: {}, empreinte: "absent" };
    console.error(`[supervisor] ${p} ILLISIBLE (${e}) : chemins machine ignores`);
    return { vars: {}, empreinte: "illisible" };
  }
}

// `%NOKIDO_ROOT%` / `%NOKIDO_WORKSPACE%` (forme generisee du dist pour la racine et le dossier de travail) se
// deduisent de la racine quand l'environnement ne les donne pas (2e mesure VM du 08/10 : un cwd `%NOKIDO_ROOT%`).
function _defautsEnv(root?: string): Record<string, string> {
  return root ? { NOKIDO_ROOT: root, NOKIDO_WORKSPACE: dirname(root) } : {};
}

function _developperEnv(v: string, defauts: Record<string, string> = {}): string {
  return v.replace(/%([A-Za-z_][A-Za-z0-9_]*)%/g, (m, n) => {
    const val = Deno.env.get(n) ?? defauts[n] ?? (n === "USERPROFILE" ? Deno.env.get("HOME") : undefined);
    return val ? val : m;
  });
}

function _fusionner(
  base: Record<string, unknown>,
  locales: Record<string, string>,
  runtimeVars: Record<string, string>,
  defauts: Record<string, string>,
): Record<string, string> {
  const vars: Record<string, string> = {};
  for (const [k, v] of Object.entries({ ...base, ...locales, ...runtimeVars })) {
    vars[k] = _developperEnv(String(v), defauts);
  }
  return vars;
}

/** Les [vars] telles que le chargeur les applique : services.toml, puis config/vars.local.toml, puis les variables
 *  d'execution, `%NOM%` developpe. Le superviseur y prend l'interpreteur de ses lanceurs runAs (2e mesure VM du
 *  08/10 : le litteral du poste de reference faisait echouer les 10 services runAs ailleurs que sur lui).
 *  Rend null si le TOML est illisible : l'appelant garde son repli. */
export function resoudreVars(
  tomlPath: string,
  runtimeVars: Record<string, string> = {},
): Record<string, string> | null {
  try {
    // deno-lint-ignore no-explicit-any
    const doc = parse(Deno.readTextFileSync(tomlPath)) as any;
    const locales = _varsLocales(runtimeVars.ROOT ?? ".").vars;
    return _fusionner(doc.vars ?? {}, locales, runtimeVars, _defautsEnv(runtimeVars.ROOT));
  } catch {
    return null;
  }
}

const _RE_NON_RESOLU = /%[A-Za-z_][A-Za-z0-9_]*%/;
const _RE_ABSOLU = /^([A-Za-z]:[\\/]|\/)/;

// Un chemin absent est prouve par NotFound ; tout autre refus (droits, verrou) laisse le doute : on ne desactive
// rien sur un « je n'ai pas pu regarder » (UNKNOWN n'est pas NO).
function _absent(p: string): boolean {
  try {
    Deno.statSync(p);
    return false;
  } catch (e) {
    return e instanceof Deno.errors.NotFound;
  }
}

let _cacheEmpreinte = "";
let _cacheServices: ServiceDef[] | null = null;

export function loadServices(
  tomlPath: string,
  runtimeVars: Record<string, string> = {},
): ServiceDef[] | null {
  try {
    const _locales = _varsLocales(runtimeVars.ROOT ?? ".");
    const _st = Deno.statSync(tomlPath);
    const _empreinte = [
      tomlPath,
      _st.mtime?.getTime() ?? 0,
      _st.size,
      JSON.stringify(runtimeVars),
      _locales.empreinte,
    ].join("|");
    if (_empreinte === _cacheEmpreinte && _cacheServices) {
      return _cacheServices;
    }
    const raw = Deno.readTextFileSync(tomlPath);
    // deno-lint-ignore no-explicit-any
    const doc = parse(raw) as any;
    const _defauts = _defautsEnv(runtimeVars.ROOT);
    const vars = _fusionner(doc.vars ?? {}, _locales.vars, runtimeVars, _defauts);
    const rv = (x: unknown) => _developperEnv(resolveVars(String(x ?? ""), vars), _defauts);

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
      // `propre_au_poste` (owner 2026-10-08) : un service propre au poste de reference (son runner CI) ne demarre
      // pas sur une machine ou son dossier ou son executable absolu n'existe pas -- dit, jamais compte en echec.
      if (s.propre_au_poste === true && !svc.disabled) {
        const manque = [svc.cwd, svc.cmd].find((p) => _RE_ABSOLU.test(p) && _absent(p));
        if (manque) {
          svc.disabled = true;
          console.error(
            `[supervisor] ${svc.name} : propre au poste de reference (${manque} absent ici) -- non demarre, sans echec`,
          );
        }
      }
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
      if (s.logboot === true) svc.logboot = true;
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
    const _nonResolus = out.filter((s) =>
      !s.disabled && _RE_NON_RESOLU.test([s.cmd, s.cwd ?? "", ...s.args].join(" "))
    );
    if (_nonResolus.length) {
      console.error(
        `[supervisor] chemins NON RESOLUS pour ${_nonResolus.length} service(s) actif(s) : ` +
          _nonResolus.slice(0, 12).map((s) => s.name).join(", ") +
          (_nonResolus.length > 12 ? " ..." : "") +
          " -- `nokido-doctor --ecrire-vars` ecrit les chemins de cette machine (config/vars.local.toml)",
      );
    }
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
