/**
 * supervisor.ts — LaForge-Master process supervisor (V2 - Physiologique)
 *
 * Single Deno process replacing 17 NSSM services.
 * Implémente le Séquençage de Boot en Vagues Physiologiques.
 *
 * Install: nssm install LaForge-Master deno.exe run -A proxy_deno/core/supervisor.ts
 */

import { join, resolve } from "https://deno.land/std/path/mod.ts";
import { ensureDir } from "https://deno.land/std@0.224.0/fs/mod.ts";
import {
  defaultTomlPath,
  loadServices,
  resoudreVars,
  type ServiceDef,
} from "./service_loader.ts";
import { memUsagePct, totalRamKo } from "./platform.ts";

const ROOT = resolve(Deno.cwd());
const LOG_DIR = join(ROOT, "logs", "supervisor");

// Phase 28+ (2026-05-25) — load Nokido.env au boot. Sans ca, FORGE_MCP_TOKEN/
// LAFORGE_JWT_SECRET dans la session PS user ne se propagent PAS au service
// NSSM. Les vars chargees ici sont automatiquement propagees aux enfants via
// envMerged = { ...Deno.env.toObject(), ... } dans startService().
function _loadDotEnv(path: string): number {
  try {
    const text = Deno.readTextFileSync(path);
    let n = 0;
    for (const raw of text.split(/\r?\n/)) {
      const line = raw.trim();
      if (!line || line.startsWith("#") || !line.includes("=")) continue;
      const eq = line.indexOf("=");
      const key = line.slice(0, eq).trim();
      let val = line.slice(eq + 1).trim();
      if ((val.startsWith('"') && val.endsWith('"')) ||
          (val.startsWith("'") && val.endsWith("'"))) {
        val = val.slice(1, -1);
      }
      if (!key || Deno.env.get(key) !== undefined) continue;
      Deno.env.set(key, val);
      n++;
    }
    return n;
  } catch {
    return 0;
  }
}
const _N_ENV_LOADED = _loadDotEnv(join(ROOT, "Nokido.env"));
// L'interpreteur des lanceurs runAs, et LAFORGE_PYTHON transmis aux services : la variable PYTHON RESOLUE
// (services.toml, puis config/vars.local.toml, `%NOM%` developpe). 2e mesure sur VM neuve (08/10) : ce litteral du
// poste de reference faisait echouer les 10 services runAs partout ailleurs. Sur le poste de reference PYTHON vaut
// exactement ce litteral (verifie) : comportement inchange. Repli : le litteral, si le TOML est illisible.
const _MINIFORGE_REPLI = "%USERPROFILE%/miniforge3/python.exe";
const MINIFORGE = resoudreVars(defaultTomlPath(), { ROOT })?.PYTHON || _MINIFORGE_REPLI;

// Phase 38 (2026-05-27) — load DPAPI vault tokens into Deno.env so that
// supervisor + spawned services share the same source of truth (the
// machine-wide vault). Nokido.env stays optional / legacy fallback.
// Fail-open: si vault indisponible, on garde ce que _loadDotEnv a charge.
/**
 * En-tetes d'identite du SUPERVISEUR pour ses appels au hub.
 *
 * ANALOGIE ANATOMIQUE, et ce n'est pas une image : chaque cellule porte son
 * PROPRE marqueur (CMH-I), elle n'emprunte pas celui d'une voisine, et celle
 * qui n'en exprime aucun se fait eliminer. Ici de meme -- AUCUN organe
 * n'authentifie pour un autre. Ce qui est central, c'est la VERIFICATION (le
 * videur, ganglion du corps), jamais l'emission d'identite.
 *
 * Le superviseur est le TRONC CEREBRAL : il regule le cycle veille/sommeil des
 * organes (spawn, arret, differe). Declare ring 1 au registre vivant, comme
 * TDR_SENTINEL -- un organe qui REGULE les autres agit au niveau des vitaux,
 * sans etre ring 0, qui reste l'owner.
 *
 * Ordre des jetons, et il compte :
 *   1. FORGE_TOKEN_SUPERVISOR : son marqueur PROPRE ;
 *   2. FORGE_MCP_TOKEN : repli transitoire, le badge du corps entier. Il
 *      fonctionne, mais rend l'organe indiscernable dans le journal -- la
 *      chaine d'appel cesse d'etre remontable, ce qui est exactement ce que
 *      cette phase construit. A retirer des que le jeton propre est seme.
 *
 * Le NOM est pose dans les deux cas : sans jeton apparie il ne donne aucun
 * droit (plancher anti-spoof du videur), mais il rend la trace LISIBLE.
 * Nommer n'est pas autoriser -- c'est la distinction que la phase C etablit.
 */
function _hubAuthHeaders(): Record<string, string> {
  const h: Record<string, string> = { "LaForge-Agent-Name": "SUPERVISOR" };
  const propre = Deno.env.get("FORGE_TOKEN_SUPERVISOR") ?? "";
  const master = Deno.env.get("FORGE_MCP_TOKEN") ?? "";
  const token = propre || master;
  // AUTH-2 (2026-09-24) : sans marqueur propre, le repli sur le maitre s'annonce MASTER.
  // Il prenait le nom SUPERVISOR et en heritait le ring : 490 appels comptes en usurpation.
  if (!propre && master) h["LaForge-Agent-Name"] = "MASTER";
  if (token) h["authorization"] = `Bearer ${token}`;
  return h;
}

// PREUVE DPoP ADOSSEE AU TPM pour les appels d'ADMINISTRATION du hub (2026-09-24).
// Operation sensible -> garantie forte : le hub verifie que la preuve est signee par la
// cle TPM de SUPERVISOR dont l'empreinte est ENREGISTREE au registre. Une preuve par
// requete (jti unique) : jamais partagee entre deux appels. Echec -> aucun en-tete, et le
// hub decide (observation, ou refus en mode applique) ; le superviseur ne s'arrete pas.
// BORNE DE TEMPS (2026-09-24, regression mesuree le jour meme) : sans `signal`, un CLI
// qui ne rend pas la main suspendait `await ... .output()` POUR TOUJOURS -- et avec lui
// les deux appels admin de NREM1 (audit de regulation, snapshot memoire), SANS la moindre
// ligne de journal : 0 appel en 35 min apres deux declenchements. « Le superviseur ne
// s'arrete pas » etait ecrit ici sans etre vrai. Delai depasse -> processus tue, aucune
// preuve, et l'appel part quand meme : c'est le hub qui decide.
const _PREUVE_TPM_DELAI_MS = 10_000;

// SANS PIPE (2026-09-24, cause mesuree) : sous Windows, chaque pipe d'enfant lu par Deno
// immobilise un thread du pool BLOQUANT tant qu'il attend ; ce superviseur a ~67 enfants
// pipes, 82 threads contre 17-18 pour un Deno sans enfant -- le pool est plein, et toute
// E/S asynchrone qui y passe (lecture de pipe, ecriture de fichier) attend indefiniment.
// `.output()` sur ce CLI n'aboutissait donc jamais. Le CLI ecrit sa preuve dans un fichier
// (`--sortie`), on attend la FIN du process (`status` n'occupe pas le pool) et on lit en
// SYNCHRONE. Fichier supprime aussitot : la preuve est a usage unique (jti).
async function _preuveDpopTpm(methode: string, url: string): Promise<string> {
  const t0 = Date.now();
  const sortie = join(ROOT, "sandbox", `dpop_${crypto.randomUUID()}.tmp`);
  try {
    const st = await new Deno.Command(MINIFORGE, {
      args: [join(ROOT, "tools", "forge_dpop_tpm_cli.py"), "--agent", "SUPERVISOR",
             "--htm", methode, "--htu", url, "--sortie", sortie],
      stdin: "null", stdout: "null", stderr: "null",
      signal: AbortSignal.timeout(_PREUVE_TPM_DELAI_MS),
    }).spawn().status;
    if (st.code !== 0) {
      const duree = Date.now() - t0;
      let cause = `code ${st.code}`;
      if (duree >= _PREUVE_TPM_DELAI_MS - 50) cause = `delai depasse (${duree} ms)`;
      else {
        try { cause = Deno.readTextFileSync(sortie + ".err").trim().slice(0, 160); } catch { /* motif absent : le code suffit */ }
      }
      log(`[auth] preuve TPM indisponible : ${cause}`);
      return "";
    }
    return Deno.readTextFileSync(sortie).trim();
  } catch (e) {
    log(`[auth] preuve TPM impossible apres ${Date.now() - t0} ms : ${(e as Error).message}`);
    return "";
  } finally {
    for (const f of [sortie, sortie + ".err"]) {
      try { Deno.removeSync(f); } catch { /* absent : rien a nettoyer */ }
    }
  }
}

async function _entetesAdminAvecPreuve(methode: string, chemin: string): Promise<Record<string, string>> {
  const h: Record<string, string> = { "content-type": "application/json", ..._hubAuthHeaders() };
  const preuve = await _preuveDpopTpm(methode, "http://127.0.0.1:8766" + chemin);
  if (preuve) h["dpop"] = preuve;
  return h;
}

function _loadVaultToEnv(): number {
  const keys = [
    "FORGE_MCP_TOKEN",
    "LAFORGE_SUPERVISOR_TOKEN",
    "LAFORGE_JWT_SECRET",
    "HUB_JWT_SECRET",
    // 2026-09-02 : marqueur PROPRE du superviseur. Chaque organe porte le sien,
    // il n'emprunte pas celui d'un autre -- surtout pas le master, qui le rend
    // indiscernable dans le journal.
    //
    // (La note precedente disait « absent du coffre pour l'instant ». PERIME :
    // mesure du 2026-09-02, le hub reconnait ce credential et le superviseur
    // sort bien en `bearer_derive` au journal d'autorisation. Un commentaire
    // qui survit a la realite qu'il decrit envoie chercher un probleme resolu.)
    "FORGE_TOKEN_SUPERVISOR",
    // Marqueur propre de DenoHubMCP. Il ne pouvait PAS l'obtenir seul :
    // `main.ts` lit `Nokido.env`, or ce fichier ne porte aucun `FORGE_TOKEN_*`
    // (mesure du jour : zero), et Deno n'a pas d'acces au coffre DPAPI. Sans
    // cette ligne, son recablage restait lettre morte et le service continuait
    // a relayer les appels sous le passe-partout.
    "FORGE_TOKEN_DENOHUBMCP",
    "LAFORGE_ADMIN_TOKEN",  // 2026-05-27: requis par app/web_hub/auth.py (port 7400)
  ];
  // BILAN DIT (coffre, etape F, 2026-09-28) : ce chargeur taisait ses echecs (stderr
  // jete, retour 0) -- le jeton du registre NSSM les masquait. Une fois ces valeurs
  // retirees de NSSM, un echec muet laisserait le superviseur SANS jeton. Il rend donc
  // les NOMS charges, les NOMS absents et la CAUSE d'un echec (type d'exception) --
  // jamais une valeur.
  _VAULT_BILAN.charges = [];
  _VAULT_BILAN.absents = [];
  _VAULT_BILAN.erreur = null;
  try {
    const py = `
import sys, json
sys.path.insert(0, r"${join(ROOT, "app").replaceAll("\\", "/")}")
try:
    from forge_secrets import get_secret
except Exception as e:
    print(json.dumps({"valeurs": {}, "erreur": "import forge_secrets: " + type(e).__name__})); sys.exit(0)
out, err = {}, None
for k in ${JSON.stringify(keys)}:
    try:
        v = get_secret(k)
    except Exception as e:
        v, err = None, "get_secret: " + type(e).__name__
    if v: out[k] = v
print(json.dumps({"valeurs": out, "erreur": err}))
`;
    const result = new Deno.Command(MINIFORGE, {
      args: ["-c", py],
      stdout: "piped", stderr: "null",
    }).outputSync();
    if (!result.success) {
      _VAULT_BILAN.erreur = `auxiliaire python en echec (code ${result.code})`;
      _VAULT_BILAN.absents = [...keys];
      return 0;
    }
    const text = new TextDecoder().decode(result.stdout).trim();
    const data = text ? JSON.parse(text) : { valeurs: {}, erreur: "sortie vide" };
    const valeurs = (data && typeof data.valeurs === "object" && data.valeurs) ? data.valeurs : {};
    _VAULT_BILAN.erreur = data?.erreur ?? null;
    let n = 0;
    for (const k of keys) {
      const v = valeurs[k];
      if (typeof v !== "string" || !v) {
        _VAULT_BILAN.absents.push(k);
        continue;
      }
      _VAULT_BILAN.charges.push(k);
      // Override only if env was loaded from legacy .env (we re-establish vault
      // as authoritative). Skip if value already matches (idempotent).
      if (Deno.env.get(k) === v) continue;
      Deno.env.set(k, v);
      n++;
    }
    return n;
  } catch (e) {
    _VAULT_BILAN.erreur = `chargeur en echec (${(e as Error)?.name ?? "erreur"})`;
    return 0;
  }
}
const _VAULT_BILAN: { charges: string[]; absents: string[]; erreur: string | null } =
  { charges: [], absents: [], erreur: null };
const _N_VAULT_LOADED = _loadVaultToEnv();
const PY314 = "%USERPROFILE%/miniforge3/envs/laforge_py314/python.exe";
const PY312_RYZEN = "%USERPROFILE%/miniforge3/envs/ryzen-ai-final/python.exe";
const DENO_EXE = "%USERPROFILE%/.deno/bin/deno.exe";
const PROXY_DIR = join(ROOT, "proxy_deno");
const LLAMA_EXE = "%USERPROFILE%/llama-vulkan/llama-server.exe";
const MODEL_7B =
  "D:/ollama/models/blobs/sha256-60e05f2100071479f596b964f89f510f057ce397ea22f2833a0cfe029bfc2463";
const DRAFT_1B =
  "D:/ollama/models/blobs/sha256-29d8c98fa6b098e200069bfb88b9508dc3e85586d20cba59f8dda9a808165104";
const CTRL_PORT = 8765;
const LOG_MAX_BYTES = 5 * 1024 * 1024;
const BACKOFF_MS = [1_000, 2_000, 4_000, 8_000, 16_000, 30_000];
// RCA 2026-05-24 BSOD 0x119 — cap absolu sur restart loop.
// Au-dela de 10 restarts en 1h, le service entre en quarantine 1h
// (impossible de spawn meme avec backoff fini). Empeche un service qui
// crashe < 5s a chaque demarrage de saturer le driver GPU partage.
const MAX_RESTARTS_PER_HOUR = 10;
const QUARANTINE_MS = 60 * 60 * 1000;
// Gating GPU avant spawn (anti-saturation Radeon iGPU). Si gpu_pct > seuil,
// differer le spawn d'un service non-essentiel. Source: forge_resource_manager
// snapshot via hub :8766 /resource/snapshot ; fail-open si hub HS.
const GPU_SATURATION_PCT = 90;
const GPU_GATE_DEFER_MS = 30_000;

// ── ANTI DOUBLE-SPAWN (mesure 2026-07-29) ──────────────────────────────────
// startService() est appelé depuis douze sites, dont plusieurs en fire-and-forget
// (wave-starter, reload, auto-reconcile, watcher de heartbeat). Deux appels peuvent
// donc courir pour le MÊME service et franchir ENSEMBLE l'attente des deps, qui dure
// jusqu'à 90 s — au bout, deux process. Mesuré sur NokidoEpistemicSoif : deux
// `demarrage` à 09:01:35 (PID 11928 et 22312). La course PRÉEXISTE (déjà deux le
// 27-07 à 20:46:19) ; elle restait invisible tant que les deux tentatives échouaient
// ensemble sur `aborting start`, donnant 0 instance au lieu de 2.
// Le verrou EXPIRE (120 s > les 90 s d'attente) : aucun blocage permanent possible,
// même si un chemin omettait de le rendre.
const _START_INFLIGHT_MS = 120_000;
const _startInflight = new Map<string, number>();
// Heartbeat reader (Phase 3 — autodiagnostic).
// Phase 6 (2026-05-24) — 3 tiers de reactivite hydraulique pour ne pas
// imposer 300/600s a tous (trop loose pour services critiques RT, trop
// agressif pour daemons longs cycles 6h/12h).
//   fast   = critique RT : poll 5s,  degraded 30s,  restart 90s
//   normal = default     : poll 30s, degraded 300s, restart 600s
//   slow   = long cycle  : poll 60s, degraded 1800s, restart 3600s
// Le tier est lu depuis def.heartbeat_tier (default "normal"). 1 loop
// par tier => isolation, le slow ne ralentit pas le fast.
interface HeartbeatTier {
  poll_ms: number;
  stale_degraded_s: number;
  stale_restart_s: number;
}
const HEARTBEAT_TIERS: Record<"fast" | "normal" | "slow", HeartbeatTier> = {
  fast: { poll_ms: 5_000, stale_degraded_s: 30, stale_restart_s: 90 },
  normal: { poll_ms: 30_000, stale_degraded_s: 300, stale_restart_s: 600 },
  slow: { poll_ms: 60_000, stale_degraded_s: 1800, stale_restart_s: 3600 },
};
function tierFor(def: ServiceDef): HeartbeatTier {
  return HEARTBEAT_TIERS[def.heartbeat_tier ?? "normal"];
}
// Circuit breaker rapide (Phase 6 reflexe spinal). Si un service exit
// QUICK_FAIL_COUNT fois consecutivement en moins de QUICK_FAIL_THRESHOLD_S
// chacune, on declenche une quarantine immediate de QUICK_QUARANTINE_MS
// (pas attendre le cap 10/h). Cible : daemon qui boucle exit 2 en < 5s.
const QUICK_FAIL_THRESHOLD_MS = 30_000;
const QUICK_FAIL_COUNT = 3;
const QUICK_QUARANTINE_MS = 5 * 60 * 1000;

// ServiceDef is imported from ./service_loader.ts

// In-code fallback registry: used only if services.toml fails to load.
const SERVICES_FALLBACK: ServiceDef[] = [
  // ── VAGUE 1 : Tronc Cérébral (Réseau & Hub Principal) ──────────────
  {
    name: "NokidoMCP", // Le noyau Python (8766)
    wave: 1,
    cmd: MINIFORGE,
    args: ["tools/nokido_hub.py"],
    cwd: ROOT,
    env: {
      PYTHONPATH: "%USERPROFILE%/miniforge3/Lib/site-packages",
      PYTHONHOME: "%USERPROFILE%/miniforge3",
      PYTHONIOENCODING: "utf-8",
      // Route run/orchestrate code execution through the low-priv sandbox
      // (LaForgeSbx* users). Set to "0" to disable. See forge_sandbox_exec.
      SANDBOX_EXEC: "1",
    },
    port: 8766,
    essential: true,
    neverSleep: true,
  },
  {
    name: "NokidoOllama", // LLM vital local
    wave: 1,
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
    // Lazy proxy — toujours UP sur :8767, wake NetcfgMCP réel sur :8768 à la demande
    name: "NokidoNetcfgProxy",
    wave: 1,
    cmd: DENO_EXE,
    args: ["run", "-A", "--no-check", "proxy_deno/organs/netcfg_lazy_proxy.ts"],
    cwd: ROOT,
    port: 8767,
    essential: true,
    neverSleep: true,
  },
  {
    // Serveur réel sur :8768. Service NORMAL (persistant) : `disabled:true`
    // l'excluait de la map `states`, donc l'API /supervisor/wake ne pouvait
    // PAS le réveiller (404) -> le lazy-proxy bouclait en "wake timeout" et
    // re-spawnait le onefile 129MB en boucle (churn disque 22 MB/s).
    name: "NokidoNetcfgMCP",
    wave: 1,
    cmd: MINIFORGE,
    args: [
      "-m",
      "netcfg_mcp",
      "serve",
      "--transport",
      "http",
      "--host",
      "127.0.0.1",
      "--port",
      "8768",
      "--standalone",
    ],
    cwd: "%NOKIDO_WORKSPACE%/netcfg-agent-mcp",
    port: 8768,
    essential: true,
  },

  // ── VAGUE 2 : Hémisphère Gauche (Système Nerveux Deno) ─────────────
  {
    name: "NokidoDenoProxy",
    wave: 2,
    cmd: DENO_EXE,
    args: [
      "run",
      "--allow-net",
      "--allow-read",
      "--allow-write",
      "--allow-env",
      "--allow-run",
      "--no-check",
      "main.ts",
    ],
    cwd: PROXY_DIR,
    env: { LAFORGE_PERSIST_DIR: join(ROOT, "nokido_persist") },
    deps: [8766],
    port: 8000,
    essential: true,
  },
  {
    name: "NokidoDenoHubMCP",
    wave: 2,
    cmd: DENO_EXE,
    args: [
      "run",
      "--allow-net",
      "--allow-read",
      "--allow-env",
      "--no-check",
      "hub_mcp/main.ts",
    ],
    cwd: PROXY_DIR,
    env: {
      LAFORGE_DENO_HUB_PORT: "8769",
      LAFORGE_PERSIST_DIR: join(ROOT, "nokido_persist"),
    },
    deps: [8766],
    port: 8769,
    essential: false,
  },

  // ── VAGUE 3 : Sondes Vitales & Cervelet (Isolation matérielle) ─────
  {
    name: "NokidoHomeostasis", // Resource Manager Daemon
    wave: 3,
    cmd: PY314,
    args: ["app/forge_homeostasis_orchestrator.py", "--daemon"],
    cwd: ROOT,
    env: { PYTHONNOUSERSITE: "1", PYTHONIOENCODING: "utf-8" },
    deps: [8766],
    essential: false,
  },
  {
    name: "NokidoBrainWorker", // Le Cervelet ZMQ (Isolé Python 3.12 NPU)
    wave: 3,
    cmd: PY312_RYZEN,
    args: ["app/brain_worker.py"],
    cwd: ROOT,
    env: { PYTHONIOENCODING: "utf-8" },
    port: 5557,
    essential: false,
  },

  // ── VAGUE 4 : Cortex Cognitif (Python 3.14 & Heavy LLMs) ───────────
  {
    name: "NokidoHebbian",
    wave: 4,
    cmd: PY314,
    args: ["app/forge_hebbian_linker.py", "--daemon"],
    cwd: ROOT,
    env: { PYTHONNOUSERSITE: "1", PYTHONIOENCODING: "utf-8" },
    deps: [8766, 8000],
    essential: false,
  },
  {
    name: "NokidoGraph",
    wave: 4,
    cmd: PY314,
    args: ["app/forge_graph_explorer.py"],
    cwd: ROOT,
    env: { PYTHONNOUSERSITE: "1", PYTHONIOENCODING: "utf-8", PYTHONUTF8: "1" },
    deps: [8766, 8000],
    essential: false,
  },
  {
    name: "NokidoGeminiDaemon",
    wave: 4,
    cmd: PY314,
    args: [
      "tools/gemini_poll_daemon.py",
      "--mode",
      "active",
      "--interval",
      "30",
    ],
    cwd: ROOT,
    env: {
      PYTHONNOUSERSITE: "1",
      PYTHONIOENCODING: "utf-8",
      NODE_OPTIONS: "--max-old-space-size=2048",
    },
    deps: [8766],
    essential: false,
  },
  {
    name: "NokidoMultiLLMDaemon",
    wave: 4,
    cmd: MINIFORGE,
    args: ["tools/multi_llm_daemon.py"],
    cwd: ROOT,
    env: { PYTHONNOUSERSITE: "1", PYTHONIOENCODING: "utf-8" },
    deps: [8766],
    essential: false,
  },
  {
    name: "NokidoIngestDaemon",
    wave: 4,
    cmd: MINIFORGE,
    args: ["app/forge_ingestion_pipeline.py", "--daemon", "--interval", "300"],
    cwd: ROOT,
    env: { PYTHONNOUSERSITE: "1", PYTHONIOENCODING: "utf-8" },
    deps: [8766],
    essential: false,
  },
  {
    // Backfill chunks rag_chunks.embedding NULL via brain_worker ZMQ :5557.
    // disabled: trop gourmand en ressources -- réactiver en retirant
    // `disabled` quand on veut relancer la vectorisation.
    name: "NokidoEmbedTrigger",
    wave: 4,
    cmd: MINIFORGE,
    args: ["tools/forge_embed_auto_trigger.py"],
    cwd: ROOT,
    env: { PYTHONNOUSERSITE: "1", PYTHONIOENCODING: "utf-8" },
    deps: [5557],
    essential: false,
    disabled: true,
  },
  {
    name: "NokidoAutonomousLoops",
    wave: 4,
    cmd: PY314,
    args: ["app/forge_autonomous_loops.py", "--daemon", "--tick", "60"],
    cwd: ROOT,
    env: { PYTHONNOUSERSITE: "1", PYTHONIOENCODING: "utf-8", PYTHONUTF8: "1" },
    deps: [8766],
    essential: false,
  },
  {
    name: "NokidoLlamaNative",
    wave: 4,
    cmd: LLAMA_EXE,
    args: [
      "-m",
      MODEL_7B,
      "-md",
      DRAFT_1B,
      "--host",
      "127.0.0.1",
      "--port",
      "8091",
      "-ngl",
      "99",
      "-ngld",
      "99",
      "-c",
      "32768",
      "-cd",
      "32768",
      "-b",
      "2048",
      "-ub",
      "512",
      "-ctk",
      "q8_0",
      "-ctv",
      "q8_0",
      "-fa",
      "auto",
      "--cache-prompt",
      "--cache-reuse",
      "256",
      "--context-shift",
      "--metrics",
      "--props",
      "--slots",
      "--jinja",
      "--reasoning",
      "auto",
      "-a",
      "qwen,qwen2.5-coder,laforge-coder",
      "--prio",
      "1",
      "--threads",
      "-1",
      "-np",
      "-1",
      "--draft-max",
      "16",
      "--draft-min",
      "4",
      "--draft-p-min",
      "0.65",
      "--webui-mcp-proxy",
      "--webui-config-file",
      join(ROOT, "data/llamacpp_webui_config.json"),
      "--path",
      join(ROOT, "data/llamacpp_webui_fr"),
      "--override-kv",
      "general.name=str:Qwen2.5-Coder-7B-Instruct-Q4_K_M",
    ],
    cwd: ROOT,
    port: 8091,
    essential: false,
    llmPool: true,
  },
  {
    name: "NokidoLlamaRouter",
    wave: 4,
    cmd: LLAMA_EXE,
    args: [
      "--models-dir",
      join(ROOT, "data/llm_models"),
      "--models-max",
      "2",
      "--models-autoload",
      "--host",
      "127.0.0.1",
      "--port",
      "8092",
      "-ngl",
      "99",
      "-c",
      "32768",
      "-ctk",
      "q8_0",
      "-ctv",
      "q8_0",
      "-fa",
      "auto",
      "--cache-prompt",
      "--cache-reuse",
      "256",
      "--context-shift",
      "--metrics",
      "--slots",
      "--jinja",
      "--reasoning",
      "auto",
      "--prio",
      "1",
      "--threads",
      "-1",
      "-np",
      "-1",
      "--webui-mcp-proxy",
      "--webui-config-file",
      join(ROOT, "data/llamacpp_webui_config.json"),
    ],
    cwd: ROOT,
    port: 8092,
    essential: false,
    llmPool: true,
  },
  {
    name: "NokidoLMStudio",
    wave: 4,
    type: "provider",
    cmd: "",
    args: [],
    cwd: "%USERPROFILE%/.lmstudio",
    startCmd: ["%USERPROFILE%/.lmstudio/bin/lms.exe", "daemon", "up"],
    stopCmd: ["%USERPROFILE%/.lmstudio/bin/lms.exe", "daemon", "down"],
    port: 1234,
    essential: false,
    llmPool: true,
  },

  // ── VAGUE 5 : Interface & Capteurs (Ouvre les yeux) ────────────────
  {
    name: "NokidoDenoWebHub",
    wave: 5,
    cmd: DENO_EXE,
    args: [
      "run",
      "--allow-net",
      "--allow-read",
      "--allow-write",
      "--allow-env",
      "--allow-run",
      "--no-check",
      "web_hub/main.ts",
    ],
    cwd: PROXY_DIR,
    env: {
      LAFORGE_DENO_WEBHUB_PORT: "7401",
      LAFORGE_PERSIST_DIR: join(ROOT, "nokido_persist"),
      LAFORGE_PYTHON: MINIFORGE,
    },
    deps: [8766, 8000],
    port: 7401,
    essential: true,
  },
  {
    name: "NokidoWebHub",
    wave: 5,
    cmd: MINIFORGE,
    args: ["tools/nokido_web_hub.py", "--host", "127.0.0.1", "--port", "7400"],
    cwd: ROOT,
    env: { PYTHONNOUSERSITE: "1", PYTHONIOENCODING: "utf-8" },
    deps: [8766],
    port: 7400,
    essential: false,
    neverSleep: true,
  },
  {
    name: "NokidoOpenAIProxy",
    wave: 5,
    cmd: MINIFORGE,
    args: ["tools/forge_openai_proxy.py"],
    cwd: ROOT,
    env: { PYTHONIOENCODING: "utf-8" },
    deps: [8766],
    essential: false,
  },
  {
    name: "NokidoRSSWatcher",
    wave: 5,
    cmd: PY314,
    args: ["app/forge_rss_watcher.py", "--daemon"],
    cwd: ROOT,
    env: { PYTHONNOUSERSITE: "1", PYTHONIOENCODING: "utf-8" },
    deps: [8766],
    essential: false,
  },
  {
    name: "NokidoCapture",
    wave: 5,
    cmd: MINIFORGE,
    args: ["-u", "-m", "cli_tail_capture", "--watch", "--interval", "15", "-v"],
    cwd: join(ROOT, "tools"),
    env: { PYTHONIOENCODING: "utf-8" },
    deps: [8766],
    essential: false,
  },
  {
    name: "NokidoNetcfgUI",
    wave: 5,
    cmd: MINIFORGE,
    args: [
      "%NOKIDO_WORKSPACE%/netcfg-agent-web/demo/serve_ui.py",
      "--host", "127.0.0.1",
      "--port", "7500",
    ],
    cwd: "%NOKIDO_WORKSPACE%/netcfg-agent-web",
    env: { PYTHONIOENCODING: "utf-8" },
    deps: [8766],
    port: 7500,
    essential: false,
  },
];

// Declarative registry from services.toml; falls back to the in-code array
// above on any parse/load error -> editing services.toml cannot brick boot.
// `let` (pas const) -> /supervisor/reload peut rebinder apres re-parse toml.
let SERVICES: ServiceDef[] =
  loadServices(defaultTomlPath(), { ROOT, PROXY_DIR }) ?? SERVICES_FALLBACK;

const LLM_POOL_MAX = 1;

type ServiceStatus =
  | "stopped"
  | "starting"
  | "running"
  // 2026-09-11 : le process VIT et le port ECOUTE, mais l'application ne
  // repond pas. Cet etat n'existait pas, et son absence obligeait a choisir
  // entre deux mensonges -- `running` (ce qui a laisse :7400 mort et repute
  // vivant cinq heures) ou `stopped` (faux, le process tourne). Le terme est
  // celui deja employe par `HeartbeatSnapshot.health`.
  | "degraded"
  | "restarting"
  | "sleeping"
  | "disabled"
  | "quarantine";

interface HeartbeatSnapshot {
  ts: number; // unix seconds (from JSON .ts)
  read_ts: number; // unix seconds when supervisor read the file
  file_mtime_s: number; // file mtime fallback if JSON has no ts
  stale_s: number; // read_ts - effective_ts
  health: "ok" | "degraded" | "crit" | "stale"; // computed (degrades from .health if stale)
  raw: Record<string, unknown>; // full parsed JSON (truncated to ~2 KB)
}

interface ServiceState {
  def: ServiceDef;
  status: ServiceStatus;
  proc: Deno.ChildProcess | null;
  pid: number | null;
  restartCount: number;
  lastStartMs: number;
  backoffIdx: number;
  logFile: Deno.FsFile | null;
  // crash-loop quarantine — RCA 2026-05-24 BSOD 0x119 :
  // NokidoQuotaAlertDaemon a boucle 20min sur exit 2 < 1500ms et noye le
  // driver GPU AMD (TDR cascade). Cap absolu en plus du backoff exponentiel.
  restartHistory: number[];
  quarantineUntilMs: number;
  // Phase 3 autodiagnostic — dernier heartbeat lu (null si pas configure
  // ou pas encore scrute).
  heartbeat: HeartbeatSnapshot | null;
  // Phase 6 reflexe spinal — compteur d exits rapides consecutifs (reset
  // sur un run > QUICK_FAIL_THRESHOLD_MS).
  quickFailCount: number;
}

const states = new Map<string, ServiceState>();

for (const def of SERVICES) {
  if (def.disabled) continue;
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
    restartHistory: [],
    quarantineUntilMs: 0,
    heartbeat: null,
    quickFailCount: 0,
  });
}

async function isPortOpen(port: number, timeoutMs = 800): Promise<boolean> {
  try {
    const conn = await Promise.race([
      Deno.connect({ hostname: "127.0.0.1", port }),
      new Promise<never>((_, rej) =>
        setTimeout(() => rej(new Error("timeout")), timeoutMs)
      ),
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

/**
 * QUATRE NIVEAUX DE VITALITE, jamais synonymes (2026-09-11) :
 *
 *     PROCESS_ALIVE  ->  TRANSPORT_UP  ->  APPLICATION_UP  ->  FUNCTIONAL
 *
 * `isPortOpen` ne prouve que le DEUXIEME. Mesure du jour : NokidoWebHub a tenu
 * :7400 en LISTENING pendant plus de cinq heures avec /health, /, /hub et
 * /auth/login tous en TIMEOUT -- et le superviseur le declarait `running`.
 *
 * HEALTH_UNKNOWN est le troisieme etat, et il est indispensable : 32 services
 * declarent un port sans contrat de sante. Les ranger d'office du cote sain
 * serait exactement la faute que la constitution semantique interdit -- on
 * classe par liste BLANCHE, n'est sain que ce qui est PROUVE sain.
 */
const HEALTH_UNKNOWN = "health_unknown" as const;
type Vitalite = "app_up" | "app_down" | typeof HEALTH_UNKNOWN;

/**
 * L'APPLICATION derriere le port repond-elle ?
 *
 * Un 4xx compte VIVANT : le service a compris la requete et l'a refusee, donc
 * il tourne. Seuls l'absence de reponse et le 5xx disent qu'il est casse. Meme
 * regle que `forge_ui_manifest._app_repond`, cote Python -- ne pas diverger :
 * un 401 lu comme une mort ferait tuer en boucle un service parfaitement sain.
 */
async function appHealthy(
  port: number,
  healthPath: string | undefined,
  timeoutMs = 4_000,
): Promise<Vitalite> {
  if (!healthPath) return HEALTH_UNKNOWN;
  const ctrl = new AbortController();
  const t = setTimeout(() => ctrl.abort(), timeoutMs);
  try {
    const r = await fetch(`http://127.0.0.1:${port}${healthPath}`, {
      signal: ctrl.signal,
      redirect: "manual",
    });
    // Le corps doit etre consomme, sinon la connexion fuit -- et ce sont
    // precisement des sockets en CLOSE_WAIT qu'on a mesures sur :7400.
    await r.body?.cancel();
    return r.status >= 500 ? "app_down" : "app_up";
  } catch {
    return "app_down"; // timeout, connexion refusee, reset : pas de reponse
  } finally {
    clearTimeout(t);
  }
}

/**
 * Attend que l'APPLICATION reponde, pas seulement que le socket ouvre.
 *
 * Sans contrat de sante on ne peut rien attendre de plus que le port : on rend
 * alors HEALTH_UNKNOWN, et l'appelant DIT qu'il n'a pas pu juger.
 */
async function waitForHealthy(
  port: number,
  healthPath: string | undefined,
  timeoutMs = 60_000,
): Promise<Vitalite> {
  const deadline = Date.now() + timeoutMs;
  if (!await waitForPort(port, timeoutMs)) return "app_down";
  if (!healthPath) return HEALTH_UNKNOWN;
  while (Date.now() < deadline) {
    if (await appHealthy(port, healthPath) === "app_up") return "app_up";
    await delay(1_000);
  }
  return "app_down";
}

function delay(ms: number) {
  return new Promise<void>((r) => setTimeout(r, ms));
}
const _ANSI = /\[[0-9;]*[A-Za-z]/g; // codes couleur ANSI -> strip des logs

function ts() {
  // Heure LOCALE (pas UTC/toISOString) : aligne le ts de capture du supervisor
  // sur le ts interne des enfants Python (qui logguent en local) -> UNE seule
  // horloge dans les logs. Avant : 10:38 (UTC) vs 12:38 (Paris) = +2h trompeur.
  const d = new Date();
  const p = (n: number, l = 2) => String(n).padStart(l, "0");
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ` +
    `${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}.${p(d.getMilliseconds(), 3)}`;
}
function log(msg: string) {
  console.log(`[${ts()}] [SUPERVISOR] ${msg}`);
}

// E/S SYNCHRONES (2026-10-01) : `openLog` et `pipeToLog` etaient asynchrones, donc
// servis par le pool BLOQUANT de Deno -- sature par les pipes des enfants (un thread
// par pipe lu, cf. ligne ~107 et _preuveDpopTpm). Mesure du jour : 53 services en
// marche, AUCUN journal de service ecrit depuis > 10 min, 47 muets depuis > 1 h,
// tous figes entre 11:04 et 11:14 juste apres le redemarrage de la pile, pendant que
// le journal du superviseur (console.log, synchrone) continuait. Meme palliatif que
// l'etat circadien (2364685fd) : les ecritures de journal ne passent plus par le pool.
async function openLog(name: string): Promise<Deno.FsFile> {
  const path = join(LOG_DIR, `${name}.log`);
  try {
    const info = Deno.statSync(path);
    if (info.size > LOG_MAX_BYTES) {
      // FUITE FIX (2026-06-11) : NE PAS readTextFile (un log firehosé à 47GB lu en
      // entier = OOM machine au spawn = la cause des reboots qui OOMaient).
      // >500MB = firehose -> reset sec. Sinon garde la fin via seek (pas tout en RAM).
      if (info.size > 500_000_000) {
        Deno.truncateSync(path, 0);
      } else {
        const KEEP = Math.min(LOG_MAX_BYTES, 2_000_000);
        const fr = Deno.openSync(path, { read: true });
        fr.seekSync(info.size - KEEP, Deno.SeekMode.Start);
        const buf = new Uint8Array(KEEP);
        fr.readSync(buf);
        fr.close();
        Deno.writeFileSync(path, buf);
      }
    }
  } catch { /* new file */ }
  return Deno.openSync(path, { create: true, append: true, write: true });
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
      const lines = text.split("\n").filter((l) => l.trim()).map((l) =>
        `${ts()} ${l.replace(_ANSI, "")}\n`
      ).join("");
      if (lines) {
        // writeSync (hors pool bloquant, cf. openLog) ; il peut ecrire PARTIELLEMENT :
        // on boucle jusqu'au dernier octet plutot que de perdre la fin d'une ligne.
        const data = enc.encode(lines);
        let off = 0;
        while (off < data.length) off += file.writeSync(data.subarray(off));
        // FUITE FIX (2026-06-11) : NE PLUS console.log chaque chunk de chaque service.
        // Ça réécrivait tout l'output enfant dans le stdout du superviseur, que NSSM ne
        // draine pas assez vite -> buffer mémoire UNBOUNDED (~0.25GB/s observé si un
        // service firehose son stdout -> OOM machine 15GB+). L'output est DÉJÀ persisté
        // dans ${name}.log (file.write ci-dessus) = ce console.log était redondant.
      }
    }
  } catch (e) {
    // OBSERVABILITE FIX (2026-07-27) : ce catch etait MUET. Une seule ecriture
    // en echec tuait le pipe DEFINITIVEMENT — le service continuait de tourner
    // mais ne journalisait plus jamais, sans un mot nulle part. Mesure du jour :
    // logs par service TOUS geles a 12:25:17 (NokidoMCP derniere ligne 12:24:23)
    // pendant que la stack tournait — 5h de cecite, decouverte par hasard. On ne
    // peut pas diagnostiquer un service muet dont le silence est lui-meme
    // silencieux. Le superviseur, lui, ecrit toujours : c'est le seul endroit ou
    // cette panne peut etre vue.
    log(`${name}: pipeToLog INTERROMPU (le service ne journalise plus) — ${e}`);
  }
}

// JOURNAL SANS PIPE (2026-10-01). Sous Windows, chaque pipe d'enfant lu par Deno immobilise un
// thread du pool BLOQUANT, plafonne a 4 x coeurs logiques (16 -> 64). Mesure du jour : 57 enfants,
// 114 lectures pour 64 threads, 83 threads au superviseur contre 17-19 a un Deno sans enfant, et
// 5 journaux sur 56 livres en direct -- le reste par PAQUETS (pair MCP : 4 min 30 de retard).
// Un service `logboot = true` ecrit lui-meme son journal via tools/forge_logboot.py (horodatage par
// ligne ; dup2 + SetStdHandle : ses sous-process aussi) et il est lance SANS pipe. L'amorceur tourne
// sous L'INTERPRETEUR DU SERVICE ; un service runAs est enveloppe AU NIVEAU DU LANCEUR, sous le
// compte du superviseur qui a le droit d'ecrire logs/supervisor. Commande non Python : ignore, et dit.
const LOGBOOT = join(ROOT, "tools/forge_logboot.py");
const _EST_PYTHON = /(^|[\\/])python[0-9.]*(\.exe)?$/i;

function _argsLogboot(
  def: { name: string; runAs?: string; logboot?: boolean },
  cmd: string,
  args: string[],
): { cmd: string; args: string[]; journal: string } | null {
  if (!def.logboot) return null;
  const journal = join(LOG_DIR, `${def.name}.log`);
  if (def.runAs) {
    // args = [forge_runas_launcher.py, runAs, cmd du service, ...] sous MINIFORGE : on enveloppe le lanceur.
    return { cmd, args: [LOGBOOT, "--journal", journal, "--", ...args], journal };
  }
  if (!_EST_PYTHON.test(cmd)) {
    log(`${def.name}: logboot IGNORE -- commande non Python (${cmd}) ; journal par pipe`);
    return null;
  }
  // Drapeaux d'interpreteur (-u, -X utf8, -W ...) AVANT l'amorceur : ils s'appliquent au process.
  const drapeaux: string[] = [];
  let i = 0;
  while (i < args.length && args[i].startsWith("-") && args[i] !== "-m") {
    drapeaux.push(args[i]);
    if ((args[i] === "-X" || args[i] === "-W") && i + 1 < args.length) drapeaux.push(args[++i]);
    i++;
  }
  return { cmd, args: [...drapeaux, LOGBOOT, "--journal", journal, "--", ...args.slice(i)], journal };
}

async function stopProvider(state: ServiceState) {
  const sc = state.def.stopCmd;
  if (!sc?.length) return;
  try {
    const { code } = await new Deno.Command(sc[0], {
      args: sc.slice(1),
      stdout: "piped",
      stderr: "piped",
    }).output();
    log(`${state.def.name}: stopCmd exit ${code}`);
  } catch (e) {
    log(`${state.def.name}: stopCmd error ${e}`);
  }
  state.proc = null;
  state.pid = null;
  state.status = "stopped";
}

async function ollamaUnloadModels(): Promise<void> {
  try {
    const tags = await fetch("http://127.0.0.1:11434/api/tags", {
      signal: AbortSignal.timeout(2000),
    });
    if (tags.ok) {
      const data = await tags.json() as { models?: { name: string }[] };
      for (const m of (data.models ?? [])) {
        try {
          const r = await fetch("http://127.0.0.1:11434/api/generate", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              model: m.name,
              keep_alive: "0s",
              prompt: "",
            }),
            signal: AbortSignal.timeout(3000),
          });
          if (r.ok) await r.body?.cancel();
          log(`[LLM-POOL] ollama unloaded model ${m.name}`);
        } catch {}
      }
    }
  } catch {}
  await delay(2000);
}

async function enforcePool(keepName: string) {
  const pool = SERVICES.filter((s) => s.llmPool && s.name !== keepName);
  for (const def of pool) {
    const st = states.get(def.name);
    if (!st || st.status !== "running") continue;
    log(`[LLM-POOL] sleeping ${def.name} to free GPU for ${keepName}`);
    if (def.type === "provider") await stopProvider(st);
    else {try {
        st.proc?.kill("SIGTERM");
      } catch {}}
    st.status = "sleeping";
  }
  await ollamaUnloadModels();
}

// Auto-guérison zombie-port (2026-06-11) : trouve/tue le détenteur orphelin d'un port avant
// respawn. Le superviseur tourne en SYSTEM -> peut tuer un orphelin SYSTEM (ce que user non
// élevé ne peut pas). Parade GÉNÉRIQUE au crash-loop "port already in use" (ex OpenAIProxy :7777).
async function _portHolderPid(port: number): Promise<number | null> {
  try {
    const out = new TextDecoder().decode(
      (await new Deno.Command("netstat", { args: ["-ano", "-p", "TCP"], stdout: "piped", stderr: "null" }).output()).stdout,
    );
    for (const line of out.split("\n")) {
      if (line.includes(`:${port} `) && line.includes("LISTENING")) {
        const pid = parseInt((line.trim().split(/\s+/).pop() || ""), 10);
        if (pid && pid !== Deno.pid) return pid;
      }
    }
  } catch (_e) { /* netstat indispo */ }
  return null;
}

async function _killPid(pid: number): Promise<boolean> {
  try {
    await new Deno.Command("taskkill", { args: ["/F", "/PID", String(pid)], stdout: "null", stderr: "null" }).output();
    log(`auto-heal: killed orphan PID ${pid}`);
    return true;
  } catch (e) {
    log(`_killPid(${pid}) failed: ${e}`);
    return false;
  }
}

// Port de dépendance -> drapeau d'intention. MÊME vocabulaire que le reste de
// l'organisme (docker.wanted / llama.wanted / embed.wanted / rerank.wanted /
// snn.wanted), lu par forge_resource_manager (épargne) et par
// forge_llama_keeper._piliers_on_demand (rallumage).
const DEP_INTENT: Record<number, string> = {
  8099: "embed.wanted",
  8100: "rerank.wanted",
  8091: "llama.wanted",
  8080: "llama.wanted",
  1234: "lmstudio.wanted",
};

/**
 * Déclare que le corps VEUT la dépendance fermée qui bloque un service.
 *
 * Circularité mesurée le 2026-08-10 : depuis que les piliers RAG vivent on-demand
 * (`disabled = true` + rallumage sur intention), un service qui déclare
 * `deps: [8099, 8100]` ne démarre pas tant que ces ports sont fermés — et ne peut
 * donc PAS poser lui-même l'intention qui les rallumerait. NokidoEpistemicSoif
 * restait ainsi indéfiniment en defer, à réessayer dans le vide : le defer du
 * 2026-07-29 l'empêche d'être abandonnée, mais personne n'ouvrait la porte.
 *
 * Le superviseur est le seul à SAVOIR qu'un service voulu attend un port précis.
 * C'est donc à lui de le déclarer. Best-effort : un échec d'écriture est journalisé
 * et ne bloque rien — l'intention est un signal, pas un verrou.
 */
async function declareDepWanted(port: number, who: string): Promise<void> {
  const flag = DEP_INTENT[port];
  if (!flag) return; // port sans pilier on-demand (ex :8766 hub, :6333 qdrant)
  try {
    await Deno.writeTextFile(
      join(ROOT, "sandbox", flag),
      String(Date.now() / 1000),
    );
    log(`${who}: intention ${flag} posée (dep :${port} fermée) — le keeper peut rallumer`);
  } catch (e) {
    log(`${who}: intention ${flag} NON posée (${e}) — la dep :${port} restera fermée`);
  }
}

async function startService(state: ServiceState) {
  const { def } = state;
  if (state.status === "sleeping") return;
  // DEJA EN COURS (2026-09-24, mesure) : apres la relance de 18:58, 21 services ont ete
  // demarres DEUX fois et 17 avaient leurs DEUX instances vivantes (meme parent deno,
  // RAM comparable). Cause : `auto-reconcile` lance les services encore « stopped »
  // pendant que la boucle de vagues les demarre a son tour ; le garde « en vol » est
  // efface des le spawn, et le second appel lancait un NOUVEAU process en ecrasant
  // `state.proc` -- le premier devenait un ORPHELIN que plus rien n'arrete (double
  // execution de taches, purges concurrentes, RAM qui monte au fil des relances).
  // Les relances VOLONTAIRES passent le statut a stopped/restarting avant l'appel.
  if (state.status === "running" && state.proc) {
    log(`${def.name}: deja en cours (PID ${state.pid}) — skip (un second demarrage orphelinerait le premier)`);
    return;
  }

  const _inflightAt = _startInflight.get(def.name) ?? 0;
  if (Date.now() - _inflightAt < _START_INFLIGHT_MS) {
    log(`${def.name}: demarrage deja en vol — skip (anti double-spawn)`);
    return;
  }
  _startInflight.set(def.name, Date.now());

  if (def.deps?.length) {
    log(`${def.name}: waiting for deps ${def.deps.join(",")}`);
    for (const port of def.deps) {
      const ok = await waitForPort(port, 90_000);
      if (!ok) {
        // Une dep qui n'a pas ouvert en 90 s est une condition TRANSITOIRE, pas un
        // état définitif. Le `return` sec abandonnait le service jusqu'au prochain
        // boot COMPLET du superviseur — alors que le refus du resource gate, vingt
        // lignes plus bas, défère proprement depuis toujours. Mesure 2026-07-29 :
        // NokidoEpistemicSoif abandonnée à 08:17:38 sur `dep :8099 never opened`
        // (les piliers RAG étaient eux-mêmes bloqués par une embolie de cortisol) ;
        // ses trois deps écoutaient à 08:22 et plus aucune tentative n'a eu lieu —
        // elle serait restée morte sans réveil manuel.
        // Déclarer AVANT de différer : sans intention posée, le keeper ne rallumera
        // jamais un pilier on-demand et le defer réessaierait dans le vide.
        await declareDepWanted(port, def.name);
        log(`${def.name}: dep :${port} not open yet — defer (no crash count)`);
        scheduleDefer(state);
        return;
      }
    }
  }

  if (def.port && await isPortOpen(def.port)) {
    const holder = await _portHolderPid(def.port);
    // SANTE APPLICATIVE AVANT TOUT (2026-09-11). Le port ouvert ne dit que
    // TRANSPORT_UP. On interroge le contrat du service AVANT de decider, et
    // l'etat inconnu reste inconnu : il ne bascule pas vers `running`.
    const vitalite = await appHealthy(def.port, def.health_path);
    const mort = vitalite === "app_down";
    if (mort) {
      log(
        `${def.name}: :${def.port} LISTENING mais ${def.health_path} ne repond ` +
          `pas -- APPLICATION_DOWN (transport != application)`,
      );
    }
    // `restartCount > 0` NE PEUT PLUS gouverner seul la reprise du port : ce
    // compteur repart a ZERO quand le superviseur lui-meme redemarre, et un
    // zombie deja en place au boot etait alors ADOPTE comme sain. Mesure du
    // jour : superviseur ne a 10:05:19, web_hub fige depuis 15:13:49, repris
    // par personne pendant plus de cinq heures.
    if (holder && (mort || state.restartCount > 0)) {
      // RESTART + port tenu = détenteur STALE (zombie/orphelin : le service devrait être down).
      // AUTO-GUÉRISON : kill avant respawn (sinon crash-loop "address already in use" éternel).
      log(`${def.name}: :${def.port} tenu par PID ${holder} au restart #${state.restartCount} -> kill stale avant respawn`);
      await _killPid(holder);
      await delay(800);
      if (await isPortOpen(def.port)) {
        log(`${def.name}: :${def.port} toujours tenu après kill — skip`);
        state.status = "running";
        return;
      }
      // port libéré -> tombe vers le spawn normal (pas de return)
    } else if (mort) {
      // Detenteur ILLISIBLE (netstat muet) ET application morte : on ne peut
      // ni guerir ni certifier. On le DIT, au lieu de declarer `running` : un
      // UNKNOWN range du cote sain est exactement ce qui a laisse ce service
      // mort et repute vivant pendant cinq heures.
      log(
        `${def.name}: :${def.port} APPLICATION_DOWN et detenteur illisible ` +
          `-- ni guerison ni certification possibles`,
      );
      state.status = "degraded";
      return;
    } else {
      log(
        `${def.name}: port :${def.port} already open (sante=${vitalite}) ` +
          `— skipping start`,
      );
      // HEALTH_UNKNOWN n'est PAS app_up : sans contrat declare on adopte le
      // service faute de mieux, mais le journal NOMME ce qu'on n'a pas su voir
      // — 32 services portes sont dans ce cas, et leur silence n'est pas une
      // bonne nouvelle.
      if (vitalite === HEALTH_UNKNOWN) {
        log(
          `${def.name}: aucun health_path declare — vitalite applicative NON ` +
            `MESUREE (la declarer dans services.toml pour qu'elle soit jugee)`,
        );
      }
      state.status = "running";
      return;
    }
  }

  if (def.llmPool) {
    const running = SERVICES.filter((s) => s.llmPool && s.name !== def.name)
      .filter((s) => states.get(s.name)?.status === "running");
    if (running.length >= LLM_POOL_MAX) await enforcePool(def.name);
  }

  /**
 * En-tetes d'identite du SUPERVISEUR pour ses appels au hub.
 *
 * ANALOGIE ANATOMIQUE, et ce n'est pas une image : chaque cellule porte son
 * PROPRE marqueur (CMH-I), elle n'emprunte pas celui d'une voisine, et celle
 * qui n'en exprime aucun est eliminee. Ici c'est pareil -- aucun organe
 * n'authentifie pour un autre. Ce qui est central, c'est la VERIFICATION (le
 * videur, ganglion du corps), jamais l'emission d'identite.
 *
 * Le superviseur est le TRONC CEREBRAL : il regule le cycle veille/sommeil des
 * organes (spawn, arret, differe). Il est declare ring 1 au registre vivant,
 * comme TDR_SENTINEL -- un organe qui REGULE les autres agit au niveau des
 * vitaux, sans etre ring 0, qui reste l'owner.
 *
 * Ordre des jetons, et il compte :
 *   1. FORGE_TOKEN_SUPERVISOR -- son marqueur PROPRE ;
 *   2. FORGE_MCP_TOKEN -- repli transitoire, le badge du corps entier. Il
 *      fonctionne, mais rend l'organe indiscernable dans le journal : la
 *      chaine d'appel cesse d'etre remontable, ce qui est exactement ce que
 *      cette phase construit. A retirer des que le jeton propre est seme.
 *
 * Le NOM est pose dans les deux cas : sans jeton apparie il ne donne aucun
 * droit (plancher anti-spoof du videur), mais il rend la trace LISIBLE. Nommer
 * n'est pas autoriser -- c'est precisement la distinction que la phase C etablit.
 */
// (`_hubAuthHeaders` est definie au niveau MODULE, plus haut : le type-check a
//  montre qu'ici elle n'etait visible que du gate de ressource, pas des sondes
//  de telemetrie -- TS2304 sur deux sites. Un parse-check ne l'aurait pas vu.)

// Resource manager gate — query hub :8766 /api/resource/should_spawn.
  // Fail-open: hub down or non-2xx → allow spawn (preserves current behavior).
  // Skipped for essential services (always start, even under pressure).
  if (!def.essential) {
    try {
      const gateUrl =
        `http://127.0.0.1:8766/api/resource/should_spawn?name=${encodeURIComponent(def.name)}`;
      // S'IDENTIFIER. Mesure du 2026-09-02 : ce gate etait le plus gros flux
      // ANONYME du hub -- 423 appels observes, tous sans identite, alors que le
      // superviseur porte deja un Bearer sur /admin/run_job et
      // /api/maintenance/gc, deux routes bien plus sensibles. Le mecanisme
      // existait, il n'etait simplement pas applique ici : la provenance
      // (deno.exe, PID) etait connue, l'identite non -- et une provenance
      // n'authentifie personne.
      // `if (token)` conserve : sans jeton en environnement, on retombe
      // exactement sur le comportement d'avant plutot que d'envoyer un
      // en-tete vide qui se ferait refuser.
      const gr = await fetch(gateUrl, {
        signal: AbortSignal.timeout(1500),
        headers: _hubAuthHeaders(),
      });
      // AUTHZ_DENIED n'est PAS un hub en panne -- et les confondre desarme le
      // frein en silence. Mesure du 2026-09-02 : ce gate ne testait que
      // `gr.ok`, donc un 401 tombait dans la meme branche qu'un hub injoignable
      // et le service demarrait quand meme. Sous pression RAM/GPU, le
      // throttling aurait disparu sans une seule alerte, precisement au moment
      // ou l'on croyait proteger le corps. Trois etats, jamais deux :
      //   2xx   -> verdict du gate (autorise ou throttle)
      //   401/3 -> REFUS D'ACCES : anomalie de configuration, on differe
      //   autre -> gate INDISPONIBLE : fail-open, mais dit a voix haute
      if (gr.status === 401 || gr.status === 403) {
        log(
          `${def.name}: resource gate AUTHZ_DENIED (HTTP ${gr.status}) - defer. ` +
            `Ce n'est PAS une panne du hub : le superviseur n'est pas autorise a ` +
            `interroger le gate. Corriger son identite de service, ne pas ignorer.`,
        );
        scheduleDefer(state);
        return;
      }
      if (!gr.ok) {
        log(
          `${def.name}: resource gate indisponible (HTTP ${gr.status}) - fail-open ` +
            `assume, le frein de ressource ne s'applique pas a ce demarrage.`,
        );
      }
      if (gr.ok) {
        const gj = await gr.json();
        if (gj.should_spawn === false) {
          log(
            `${def.name}: resource gate refused (${gj.reason ?? "throttled"}) — defer (no crash count)`,
          );
          scheduleDefer(state);
          return;
        }
      }
    } catch {
      /* fail-open */
    }
  }

  state.status = "starting";
  state.lastStartMs = Date.now();
  // Point de non-retour : le spawn suit sans attente longue. On rend le verrou pour
  // ne pas bloquer un restart légitime demandé juste après.
  _startInflight.delete(def.name);

  if (def.type === "provider") {
    try {
      const sc = def.startCmd!;
      await new Deno.Command(sc[0], {
        args: sc.slice(1),
        stdout: "piped",
        stderr: "piped",
      }).output();
      const up = def.port ? await waitForPort(def.port, 15_000) : true;
      if (up) {
        state.status = "running";
        state.pid = null;
        log(`${def.name}: provider UP :${def.port}`);
      } else {
        log(`${def.name}: provider start timeout`);
        state.status = "stopped";
        scheduleRestart(state);
      }
    } catch (e) {
      log(`${def.name}: provider startCmd failed — ${e}`);
      state.status = "stopped";
      scheduleRestart(state);
    }
    return;
  }

  // runAs: de-privilege the service by routing it through the sandbox
  // launcher. forge_runas_launcher.py spawns the real cmd as the LaForgeSbx*
  // low-priv user inside a Job Object with KILL_ON_JOB_CLOSE, so a supervisor
  // restart/shutdown can never leave a sandboxed orphan. The launcher inherits
  // this process's stdio + cwd + env and propagates them to the sandboxed
  // child (see app/forge_sandbox_exec.py::spawn_as_sandbox_jobbed).
  let spawnCmd = def.cmd;
  let spawnArgs = def.args;
  if (def.runAs) {
    spawnCmd = MINIFORGE;
    spawnArgs = [
      join(ROOT, "tools/forge_runas_launcher.py"),
      def.runAs,
      def.cmd,
      ...def.args,
    ];
    log(`${def.name}: runAs=${def.runAs} — via sandbox launcher`);
  }

  // JOURNAL SANS PIPE (2026-10-01) : voir _argsLogboot.
  const sansPipe = _argsLogboot(def, spawnCmd, spawnArgs);
  if (sansPipe) {
    spawnCmd = sansPipe.cmd;
    spawnArgs = sansPipe.args;
    log(`${def.name}: journal SANS PIPE (forge_logboot) -> ${sansPipe.journal}`);
  }

  const envMerged = { ...Deno.env.toObject(), ...(def.env ?? {}) };
  try {
    const proc = new Deno.Command(spawnCmd, {
      args: spawnArgs,
      cwd: def.cwd,
      env: envMerged,
      stdout: sansPipe ? "null" : "piped",
      stderr: sansPipe ? "null" : "piped",
    }).spawn();
    state.proc = proc;
    state.pid = proc.pid;
    state.status = "running";
    log(`${def.name}: started PID ${proc.pid}`);

    // UN SPAWN REUSSI N'EST PAS UN DEMARRAGE REUSSI (2026-09-11). On confirme
    // la sante APPLICATIVE apres coup -- sans bloquer : le boot se fait en
    // vagues, et attendre 90 s par service serait une regression de demarrage.
    // Le verdict arrive donc en differe et CORRIGE le statut optimiste.
    if (def.port) {
      const nePas = proc.pid;
      waitForHealthy(def.port, def.health_path, 90_000)
        .then((v) => {
          // Garde de generation : si ce process a ete remplace entre-temps,
          // son verdict tardif ne doit PAS ecraser l'etat du successeur.
          if (state.pid !== nePas) return;
          if (v === "app_down") {
            state.status = "degraded";
            log(
              `${def.name}: PID ${nePas} demarre mais ${def.health_path} muet ` +
                `apres 90 s — APPLICATION_DOWN (le spawn a reussi, pas le service)`,
            );
          } else if (v === HEALTH_UNKNOWN) {
            log(
              `${def.name}: demarre — vitalite applicative NON MESUREE ` +
                `(aucun health_path declare)`,
            );
          } else {
            log(`${def.name}: APPLICATION_UP sur ${def.health_path}`);
          }
        })
        .catch((e) => {
          // Une sonde qui echoue ne doit jamais tuer le demarrage -- mais elle
          // ne doit pas se taire non plus : un `catch` vide fabrique un angle
          // mort de plus, et c'est un angle mort qui vient de couter cinq
          // heures. On DIT que la vitalite n'a pas pu etre mesuree, ce qui
          // n'est pas la meme chose que de la declarer bonne.
          log(
            `${def.name}: sonde de sante INTERROMPUE (${e?.name ?? e}) — ` +
              `vitalite applicative NON MESUREE, statut laisse tel quel`,
          );
        });
    }
    // Sans pipe, le service tient lui-meme son journal : Deno ne l'ouvre pas.
    const lf = sansPipe ? null : await openLog(def.name);
    state.logFile = lf;
    // On GARDE les promesses : sans elles, `lf.close()` ci-dessous fermait le handle
    // pendant que ces deux boucles drainaient encore les pipes -> `BadResource: Bad
    // resource ID` -> pipeToLog mourait, et le service ne journalisait PLUS JAMAIS.
    // Mesure 2026-07-27 : tous les logs de service figes au meme instant (12:25:17),
    // juste avant une vague de POST /supervisor/sleep a 12:26:11 -- une mise en
    // sommeil groupee fermait tous les handles d'un coup, en pleine ecriture.
    const drained = lf
      ? Promise.allSettled([
        pipeToLog(proc.stdout, lf, def.name),
        pipeToLog(proc.stderr, lf, def.name),
      ])
      : Promise.resolve([]);

    proc.status.then(async (s) => {
      const elapsedMs = Date.now() - state.lastStartMs;
      const elapsed = Math.round(elapsedMs / 1000);
      log(
        `${def.name}: exited code=${s.code} after ${elapsed}s (restart #${state.restartCount})`,
      );
      // Laisser les deux drains finir AVANT de fermer : c'est tout le correctif.
      // Les dernieres lignes d'un service qui meurt sont justement celles qui
      // disent POURQUOI il est mort.
      try {
        await drained;
      } catch { /* les rejets sont deja absorbes par allSettled */ }
      try {
        lf?.close();
      } catch {}
      // Garde de generation (RCA doom-loop 2026-07-03) : si CE process a ete
      // REMPLACE (restart explicite -> state.proc pointe deja le successeur),
      // son exit asynchrone ne doit NI nettoyer l'etat NI re-scheduler.
      // Sinon : l'exit du tue clobber state.proc du vivant + scheduleRestart
      // arme une boucle kill/respawn infinie (metronome 95s, flotte down).
      if (state.proc !== proc) {
        log(`${def.name}: exit d'une generation remplacee — ignore (no reschedule)`);
        return;
      }
      // Phase 6 reflexe spinal : track exits rapides consecutifs.
      if (elapsedMs < QUICK_FAIL_THRESHOLD_MS) {
        state.quickFailCount++;
      } else {
        state.quickFailCount = 0;
      }
      state.logFile = null;
      state.proc = null;
      state.pid = null;
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
  const now = Date.now();
  // Phase 6 reflexe spinal — circuit breaker rapide. Si QUICK_FAIL_COUNT
  // exits consecutifs en < QUICK_FAIL_THRESHOLD_MS chacun => quarantine
  // immediate QUICK_QUARANTINE_MS. Empeche un daemon qui exit instantanement
  // (lock PID stale, manque dep) de saturer le supervisor avec des spawns.
  if (state.quickFailCount >= QUICK_FAIL_COUNT) {
    state.status = "quarantine";
    state.quarantineUntilMs = now + QUICK_QUARANTINE_MS;
    log(
      `${state.def.name}: QUICK-FAIL QUARANTINE — ${state.quickFailCount} exits < ${
        QUICK_FAIL_THRESHOLD_MS / 1000
      }s. Released in ${Math.round(QUICK_QUARANTINE_MS / 60000)}min.`,
    );
    setTimeout(() => {
      if (state.status === "quarantine") {
        log(`${state.def.name}: quick-fail quarantine released, status -> stopped`);
        state.status = "stopped";
        state.backoffIdx = 0;
        state.quickFailCount = 0;
      }
    }, QUICK_QUARANTINE_MS);
    return;
  }
  // Quarantine cap : > MAX_RESTARTS_PER_HOUR en 1h => quarantine QUARANTINE_MS.
  state.restartHistory.push(now);
  state.restartHistory = state.restartHistory.filter((t) =>
    now - t < 60 * 60 * 1000
  );
  if (state.restartHistory.length > MAX_RESTARTS_PER_HOUR) {
    state.status = "quarantine";
    state.quarantineUntilMs = now + QUARANTINE_MS;
    log(
      `${state.def.name}: QUARANTINE — ${state.restartHistory.length} restarts in 1h (cap ${MAX_RESTARTS_PER_HOUR}). Released in ${
        Math.round(QUARANTINE_MS / 60000)
      }min.`,
    );
    setTimeout(() => {
      if (state.status === "quarantine") {
        log(`${state.def.name}: quarantine released, status -> stopped`);
        state.status = "stopped";
        state.backoffIdx = 0;
        state.restartHistory = [];
      }
    }, QUARANTINE_MS);
    return;
  }
  const ms = BACKOFF_MS[Math.min(state.backoffIdx, BACKOFF_MS.length - 1)];
  state.backoffIdx = Math.min(state.backoffIdx + 1, BACKOFF_MS.length - 1);
  state.restartCount++;
  state.status = "restarting";
  log(`${state.def.name}: restart in ${ms}ms (attempt ${state.restartCount})`);
  setTimeout(async () => {
    if (state.status === "sleeping" || state.status === "quarantine") return;
    // Gating GPU : avant spawn non-essentiel, query snapshot hub :8766.
    if (!state.def.essential) {
      const gpu = await fetchGpuPct();
      if (gpu !== null && gpu > GPU_SATURATION_PCT) {
        log(
          `${state.def.name}: GPU saturated (${
            gpu.toFixed(0)
          }%) — defer ${GPU_GATE_DEFER_MS}ms`,
        );
        scheduleDefer(state);
        return;
      }
    }
    await startService(state);
  }, ms);
}

// Resource/GPU gate DEFER — le service n'a NI demarre NI crashe : la pression
// ressource (throttle hub, GPU sature) le fait juste patienter. NE compte PAS
// comme un restart : pas de restartHistory.push, pas de restartCount++, pas de
// backoff. Sinon une rafale de throttle au boot (TDR iGPU, thundering-herd)
// brule le budget cap MAX_RESTARTS_PER_HOUR en minutes => QUARANTINE 1h de
// toute la flotte alors que rien n'a crashe. RCA 2026-06-13 cascade ~351s.
function scheduleDefer(state: ServiceState, ms = GPU_GATE_DEFER_MS) {
  // Une reprise est programmée : le démarrage n'est plus « en vol ». On rend le
  // verrou, sinon la reprise à +30 s se heurterait à son propre marquage.
  _startInflight.delete(state.def.name);
  if (state.status === "sleeping" || state.status === "quarantine") return;
  state.status = "restarting"; // transient : evite double-spawn par le wave-starter
  setTimeout(async () => {
    if (state.status === "sleeping" || state.status === "quarantine") return;
    await startService(state);
  }, ms);
}

// Best-effort GPU usage via hub :8766 /api/swarm/health. Fail-open : si hub
// HS, snapshot incomplet ou status 429 (saturation), retourne null => spawn
// autorise (sinon poule/oeuf au boot quand hub n'est pas encore up).
// Note : /api/swarm/health renvoie 200 si node peut accepter, 429 si sature.
async function fetchGpuPct(): Promise<number | null> {
  try {
    const ctrl = new AbortController();
    const tm = setTimeout(() => ctrl.abort(), 1500);
    const r = await fetch("http://127.0.0.1:8766/api/swarm/health", {
      signal: ctrl.signal,
      headers: _hubAuthHeaders(),
    });
    clearTimeout(tm);
    // 200 et 429 sont tous deux des reponses valides avec body telemetry
    // AUTHZ_DENIED n'est pas une absence de telemetrie : rendre `null` sur un
    // 401 ferait perdre le signal GPU en silence, exactement comme le gate de
    // should_spawn perdait son frein. On rend toujours `null` (le contrat de
    // cette fonction), mais on le DIT.
    if (r.status === 401 || r.status === 403) {
      log(
        `[telemetry] swarm/health AUTHZ_DENIED (HTTP ${r.status}) - signal GPU ` +
          `indisponible par REFUS D'ACCES, pas par absence de mesure.`,
      );
      return null;
    }
    if (r.status !== 200 && r.status !== 429) return null;
    const j = await r.json();
    const g = j?.telemetry?.gpu_pct;
    return typeof g === "number" ? g : null;
  } catch {
    return null;
  }
}

function resetBackoff(state: ServiceState) {
  if (Date.now() - state.lastStartMs > 30_000) state.backoffIdx = 0;
}

async function getMemUsagePct(): Promise<number> {
  // OS-specific impl lives in platform.ts (step 2 — portable supervisor).
  return await memUsagePct();
}

const RAM_SLEEP_PCT = 88;
// Hystérésis + réveil étalé (WAKE_BATCH/cycle) = anti-flap.
// RCA 2026-06-01 : RAM réelle 72-84% collait à l'ancien wake=78 → réveil des ~9
// non-essentiels d'un coup → re-spike RAM → re-sleep → oscillation 2min.
//
// DELESTAGE PAR COUT (2026-10-01). Mesure du jour (journal du superviseur, 15:54:52) :
// « RAM 90.5% > 88% » puis 43 « Sleeping » d'un coup — noeud sinusal, sentinelle,
// boite noire, coagulation, soif, executeurs : la regulation ENTIERE eteinte pour une
// pression venue d'ailleurs (navigateur, fuite de handles mtkbtsvc ; RSS de l'embedder
// stable). Puis 27 services encore endormis a 81,5 % : le reveil n'avait lieu que sous
// 72 %, seuil que ce poste (base 65-80 %) n'atteint presque jamais. Deux defauts :
//  1. on endormait sans ORDRE ni GAIN : vingt organes de 20-60 Mo rendent moins qu'un
//     seul gros consommateur. Desormais les plus gros d'abord (RSS lu dans le MEME
//     tasklist que la vitalite), au plus DELESTAGE_MAX_PAR_CYCLE, jusqu'a RAM_CIBLE_PCT ;
//     sous RAM_CRITIQUE_PCT, un service dont le gain n'est pas PROUVE (RSS illisible)
//     ou est derisoire (< DELESTAGE_GAIN_MIN_KO) n'est PAS endormi — et c'est DIT.
//  2. on reveillait trop tard et a l'aveugle : desormais sous RAM_WAKE_PCT, les moins
//     couteux d'abord, et seulement si la RAM estimee apres reveil reste sous la cible.
// L'anti-flap de 2026-06-01 tient : reveil borne par cycle ET par cout estime.
// NR : tests/nr/test_delestage_ram_par_cout_nr.py.
const RAM_WAKE_PCT = 82;
const WAKE_BATCH = 2;
const RAM_CRITIQUE_PCT = 94;
// Ni le delestage ne descend plus bas, ni le reveil ne monte plus haut.
const RAM_CIBLE_PCT = 84;
const DELESTAGE_MAX_PAR_CYCLE = 3;
const DELESTAGE_GAIN_MIN_KO = 64 * 1024;
// Cout PRESUME d'un reveil quand le RSS du service n'a jamais ete lu.
const RSS_INCONNU_KO = 150 * 1024;
// RSS (Ko) par PID, relu a chaque passage de vitalite ; RSS au moment de l'endormissement.
let _rssKoParPid = new Map<number, number>();
const _rssKoAuSommeil = new Map<string, number>();
let _pressionMuette = 0;
// Services qui touchent le GPU/iGPU/NPU. Lors d'un TDR detecte ou GPU > 95%,
// sleep ces services 10min pour laisser le driver Radeon recuperer. RCA
// 2026-05-24 BSOD : driver TDR cascade non attrape => video_scheduler crash.
const GPU_TOUCHING_SERVICES = new Set([
  "NokidoOllama",
  "NokidoLlamaNative",
  "NokidoLlamaEmbed",
  "NokidoLlamaReranker",
  "NokidoLlamaRouter",
  "NokidoLlamaPython",
  // "NokidoBrainWorker" retire 2026-07-23 : embedder NPU XDNA (VitisAI EP), ne touche PAS l'iGPU 780M -> pas de quarantine GPU
  "NokidoBrainWorkerRust",
  "NokidoLMStudio",
]);
let _lastGpuQuarantineMs = 0;
const GPU_QUARANTINE_COOLDOWN_MS = 10 * 60_000;

async function fetchTelemetry(): Promise<
  { gpu_pct: number | null; tdr_recent: number } | null
> {
  try {
    const ctrl = new AbortController();
    const tm = setTimeout(() => ctrl.abort(), 1500);
    const r = await fetch("http://127.0.0.1:8766/api/swarm/health", {
      signal: ctrl.signal,
      headers: _hubAuthHeaders(),
    });
    clearTimeout(tm);
    if (r.status === 401 || r.status === 403) {
      log(
        `[telemetry] swarm/health AUTHZ_DENIED (HTTP ${r.status}) - snapshot ` +
          `indisponible par REFUS D'ACCES, pas par absence de mesure.`,
      );
      return null;
    }
    if (r.status !== 200 && r.status !== 429) return null;
    const j = await r.json();
    return {
      gpu_pct: typeof j?.telemetry?.gpu_pct === "number"
        ? j.telemetry.gpu_pct
        : null,
      tdr_recent: typeof j?.telemetry?.tdr_recent === "number"
        ? j.telemetry.tdr_recent
        : 0,
    };
  } catch {
    return null;
  }
}

/** PID réellement vivants sur la machine, en UN appel. `null` si on n'a pas pu voir. */
async function livingPids(): Promise<Set<number> | null> {
  try {
    // SYNCHRONE (2026-09-24). `.output()` asynchrone lit le pipe sur le pool
    // bloquant ; sature par les enfants (un thread par pipe lu), la promesse ne
    // se resolvait JAMAIS : un seul passage de vitalite en 18 min, deux PID morts
    // gardes `running`, donc jamais relances. `outputSync` lit sur le fil
    // principal (tasklist ~0,2 s par minute) — meme forme que le coffre au boot.
    const out = new Deno.Command("tasklist", {
      args: ["/NH", "/FO", "CSV"],
      stdout: "piped",
      stderr: "null",
    }).outputSync();
    const alive = new Set<number>();
    const rss = new Map<number, number>();
    for (const line of new TextDecoder().decode(out.stdout).split("\n")) {
      // CSV tasklist : "Image","PID","Session","Session#","Mem"
      const cols = line.split('","');
      if (cols.length > 1) {
        const p = Number(cols[1]);
        if (p) alive.add(p);
        // "12 345 K" / "12 345 Ko" (separateur de milliers selon la langue) : on ne
        // garde que les chiffres ; rien de lisible = pas d'entree (INCONNU, pas 0).
        const ko = cols.length > 4 ? Number(cols[4].replace(/[^0-9]/g, "")) : 0;
        if (p && ko > 0) rss.set(p, ko);
      }
    }
    if (alive.size > 10) _rssKoParPid = rss;
    // GARDE : un tasklist qui echoue rend une liste vide, ce qui se lirait comme
    // « tous les services sont morts » et declencherait 52 respawns. Distinguer
    // « rien trouve » de « je n'ai pas pu voir » — leçon payee plusieurs fois.
    return alive.size > 10 ? alive : null;
  } catch {
    return null;
  }
}

let _passagesVitalite = 0;
let _vitaliteIllisible = 0;

async function resourceLoop() {
  while (true) {
    await delay(60_000);

    // SONDE DE VITALITE REELLE (2026-07-27). Le superviseur se fiait a
    // `proc.status` pour apprendre la mort d'un enfant. Mesure du jour : il a
    // affiche `running` sur des PID INEXISTANTS (16164, 8748, 3504), `restarts`
    // fige, aucune ligne `exited`, donc AUCUN respawn — un service pouvait mourir
    // et le corps continuait de le croire debout. Une promesse qui ne se resout
    // pas ne leve aucune alarme : il faut aller REGARDER, pas attendre d'etre
    // prevenu. Un seul `tasklist` couvre les 52 services.
    const alive = await livingPids();
    // POULS DE BOUCLE (2026-09-24). Sans lui, une boucle figee et une boucle saine
    // sans mort a signaler ecrivent la MEME chose : rien. Et un tasklist en echec
    // (null) se lisait comme « aucun mort ». Un passage sur 10 est dit, et chaque
    // serie d'illisibles aussi.
    _passagesVitalite++;
    if (!alive) {
      _vitaliteIllisible++;
      if (_vitaliteIllisible % 10 === 1) {
        log(
          `vitalite: tasklist ILLISIBLE (x${_vitaliteIllisible}) — morts ` +
            `silencieuses NON detectables, ce n'est pas « aucun mort »`,
        );
      }
    } else if (_passagesVitalite % 10 === 0) {
      log(`vitalite: passage #${_passagesVitalite}, ${alive.size} PID vus`);
    }
    if (alive) {
      for (const [nom, st] of states) {
        if (st.status === "running" && st.pid && !alive.has(st.pid)) {
          log(
            `${nom}: PID ${st.pid} INTROUVABLE alors que status=running — ` +
              `mort silencieuse detectee, respawn`,
          );
          st.status = "stopped";
          st.proc = null;
          st.pid = null;
          scheduleRestart(st);
        }
      }
    }

    const memPct = await getMemUsagePct();
    const totalKo = totalRamKo();
    if (memPct > RAM_SLEEP_PCT) {
      log(
        `RAM ${
          memPct.toFixed(1)
        }% > ${RAM_SLEEP_PCT}% — sleeping non-essential services`,
      );
      const candidats = [...states.values()].filter((state) =>
        !state.def.essential && !state.def.neverSleep &&
        state.status === "running" && state.proc &&
        Date.now() - state.lastStartMs > 5 * 60_000
      ).map((state) => ({
        state,
        ko: state.pid ? (_rssKoParPid.get(state.pid) ?? null) : null,
      })).sort((a, b) => (b.ko ?? -1) - (a.ko ?? -1));
      const critique = memPct > RAM_CRITIQUE_PCT;
      let pct = memPct;
      let endormis = 0;
      let ecartes = 0;
      let ecartesKo = 0;
      for (const { state, ko } of candidats) {
        if (endormis >= DELESTAGE_MAX_PAR_CYCLE || pct <= RAM_CIBLE_PCT) break;
        if (!critique && (ko === null || ko < DELESTAGE_GAIN_MIN_KO)) {
          ecartes++;
          ecartesKo += ko ?? 0;
          continue;
        }
        const uptime = Date.now() - state.lastStartMs;
        log(
          `Sleeping ${state.def.name} (uptime ${Math.round(uptime / 1000)}s, ` +
            `rss ${ko === null ? "ILLISIBLE" : Math.round(ko / 1024) + " Mo"})`,
        );
        if (ko !== null) _rssKoAuSommeil.set(state.def.name, ko);
        state.proc?.kill("SIGTERM");
        state.status = "sleeping";
        endormis++;
        if (totalKo && ko) pct -= (ko / totalKo) * 100;
      }
      if (endormis > 0) {
        _pressionMuette = 0;
      } else if (_pressionMuette++ % 10 === 0) {
        // Pression HORS de ce que Nokido peut rendre : endormir vingt organes de 30 Mo
        // ne soulage pas la machine et eteint la regulation. Dit, pas tu (1 cycle / 10).
        log(
          `RAM ${memPct.toFixed(1)}% : rien endormi — ${ecartes} service(s) a gain ` +
            `derisoire ou illisible (${Math.round(ecartesKo / 1024)} Mo lus au total) ; ` +
            `pression hors de portee du delestage sous ${RAM_CRITIQUE_PCT}%`,
        );
      }
    } else if (memPct < RAM_WAKE_PCT) {
      _pressionMuette = 0;
      // Réveil ÉTALÉ : au plus WAKE_BATCH services par cycle (60s), les MOINS couteux
      // d'abord, et seulement si la RAM estimee apres reveil reste sous RAM_CIBLE_PCT.
      // Réveiller les ~9 non-essentiels d'un coup re-spike la RAM > seuil sleep → flap.
      const dormeurs = [...states.values()].filter((s) => s.status === "sleeping")
        .sort((a, b) =>
          (_rssKoAuSommeil.get(a.def.name) ?? RSS_INCONNU_KO) -
          (_rssKoAuSommeil.get(b.def.name) ?? RSS_INCONNU_KO)
        );
      let pct = memPct;
      let woken = 0;
      for (const state of dormeurs) {
        if (woken >= WAKE_BATCH) break;
        const cout = _rssKoAuSommeil.get(state.def.name) ?? RSS_INCONNU_KO;
        // RAM totale illisible : impossible d'estimer, un seul reveil par cycle.
        const tropCher = totalKo
          ? pct + (cout / totalKo) * 100 > RAM_CIBLE_PCT
          : woken >= 1;
        if (tropCher) break;
        // GELE = JAMAIS REVEILLE PAR LA RAM (2026-09-24). Un service `disabled`
        // endormi par la regulation se rallumait des que la RAM redescendait :
        // le gel d'un ecrivain RAG (QdrantSync) ne tenait qu'au hasard du seuil.
        // Un service gele ne revient que par INTENTION (/service/start).
        if (
          !state.def.essential && !state.def.llmPool && !state.def.disabled &&
          state.status === "sleeping"
        ) {
          log(`Waking ${state.def.name} (RAM now ${pct.toFixed(1)}%, ` +
            `cout presume ${Math.round(cout / 1024)} Mo)`);
          state.status = "stopped";
          state.backoffIdx = 0;
          startService(state);
          woken++;
          if (totalKo) pct += (cout / totalKo) * 100;
        }
      }
    }
    // Degradation gracieuse GPU : TDR detecte OU saturation soutenue => sleep
    // services GPU-touchers pendant cooldown. Non-essentiels uniquement
    // (ollama est essential = jamais sleep meme en TDR ; cap VRAM via env).
    const tele = await fetchTelemetry();
    const now = Date.now();
    if (tele && now - _lastGpuQuarantineMs > GPU_QUARANTINE_COOLDOWN_MS) {
      const tdr = tele.tdr_recent;
      const gpu = tele.gpu_pct ?? 0;
      if (tdr >= 1 || gpu > 95) {
        log(
          `GPU pressure (tdr=${tdr} gpu=${
            gpu.toFixed(0)
          }%) — sleeping GPU-touching non-essentials 10min`,
        );
        _lastGpuQuarantineMs = now;
        for (const [name, state] of states) {
          if (
            !state.def.essential &&
            GPU_TOUCHING_SERVICES.has(name) &&
            state.status === "running" && state.proc
          ) {
            log(`GPU quarantine sleep ${name}`);
            const ko = state.pid ? _rssKoParPid.get(state.pid) : undefined;
            if (ko) _rssKoAuSommeil.set(name, ko);
            state.proc.kill("SIGTERM");
            state.status = "sleeping";
          }
        }
      }
    }
    for (const [, state] of states) {
      if (state.status === "running") resetBackoff(state);
    }
  }
}

// ───────────────────────────────────────────────────────────────────────────
// CIRCADIAN — rythme physiologique (mapping corps -> daemons Nokido)
// 6 phases quotidiennes : AURORE/JOUR/CREPUSCULE/NREM1/NREM3/REM.
// Voir app/forge_circadian.py pour la grammaire complete (Phase enum +
// PHASE_PROGRAM Python). Cette section est l'EXECUTEUR cote supervisor :
// detecte la phase courante chaque minute, restart les services mappes
// si pas firee depuis >= 20h. Pas de schtasks Windows (fragile, admin
// requis). Pas de cron Linux. Le supervisor tourne deja 24/7 = il
// orchestre tout naturellement.
// ───────────────────────────────────────────────────────────────────────────

type Phase = "AURORE" | "JOUR" | "CREPUSCULE" | "NREM1" | "NREM3" | "REM";

interface PhaseAction {
  service: string;          // nom du service supervisor a restart
  organ: string;            // analogie biomimetique
  why: string;              // raison physiologique
}

// Cartographie corps -> phases Nokido. Restart cible des seuls services
// pertinents pour la phase (evite restart cascade systemique).
const PHASE_PROGRAM: Record<Phase, PhaseAction[]> = {
  AURORE: [
    { service: "NokidoWatchdog", organ: "surrenales",
      why: "cortisol release - reveil services critiques" },
  ],
  JOUR: [
    { service: "NokidoIngestDaemon", organ: "estomac",
      why: "absorption documents, ingest URL/files" },
    { service: "NokidoAutonomousLoops", organ: "cortex_associatif",
      why: "agents traitent task queue" },
  ],
  // CREPUSCULE vide depuis le 2026-09-21 -- decision owner, option B.
  //
  // Cette phase reveillait `NokidoAutoCompact`, qui n'etait declare dans AUCUN
  // services.toml : 7 des 8 services du programme l'etaient, lui seul manquait.
  // Le constat figurait DEJA en commentaire plus bas dans ce fichier, depuis le
  // cutover du 2026-07-09, sans avoir jamais ete solde.
  //
  // CE QUI A TRANCHE : `tools/forge_auto_compact.py` fait un
  // `DELETE FROM rag_chunks` sur `RAG/embeddings.db`, la base de 25 Go --
  // operation que le module qualifie lui-meme d'IRREVERSIBLE. Le declarer
  // aurait ajoute un ecrivain AUTOMATIQUE et QUOTIDIEN au verrou RAG, a rebours
  // du P0 du 2026-09-19 dont le critere est que cette base CESSE de recevoir.
  //
  // L'outil reste invocable A LA MAIN, avec son `--dry-run` qui ne mute rien :
  // on retire un DECLENCHEMENT, pas une capacite. Le jumeau Python
  // `app/forge_circadian.py` a ete retire dans le MEME commit -- c'est ce
  // fichier-ci qui s'execute, et corriger l'autre seul n'aurait rien change.
  CREPUSCULE: [],
  NREM1: [
    { service: "NokidoMemoryConsolidator", organ: "hippocampe",
      why: "distillation traces high-value -> experiences" },
  ],
  NREM3: [
    { service: "NokidoOfflineTrainer", organ: "cortex_visuel_v1",
      why: "batch replay sur execution_traces, train 6 nets AMI" },
    { service: "NokidoNightTrainer", organ: "cortex_temporal",
      why: "LoRA fine-tune des modeles locaux" },
  ],
  REM: [
    { service: "NokidoSelfPatcher", organ: "systeme_glymphatique",
      why: "detecte+patch lessons recurrentes" },
    { service: "NokidoAutonomousLoops", organ: "systeme_immunitaire_b",
      why: "scan heartbeats, restart degrades, proposals" },
  ],
};

// Fenetres horaires (heure locale). Note : NREM1 traverse minuit.
function currentPhase(now: Date = new Date()): Phase {
  const h = now.getHours();
  if (h >= 6 && h < 9) return "AURORE";
  if (h >= 9 && h < 18) return "JOUR";
  if (h >= 18 && h < 22) return "CREPUSCULE";
  if (h >= 22 || h < 2) return "NREM1";
  if (h >= 2 && h < 4) return "NREM3";
  return "REM"; // 04:00-06:00
}

// Persistence dette physiologique
const CIRCADIAN_STATE_PATH = join(ROOT, "sandbox", "circadian_state.json");
const circadianLastFired = new Map<Phase, number>();
let circadianEnabled = true;
const CIRCADIAN_PHASES: Phase[] = ["AURORE", "JOUR", "CREPUSCULE", "NREM1", "NREM3", "REM"];

// Rattrapage d'une fenetre MANQUEE (2026-09-05). `currentPhase()` seule ne tire
// qu'AU MOMENT de la fenetre : un superviseur redemarre a 02h05 saute NREM1
// (22h-2h) pour la journee entiere, et rien ne le reprend. Mesure du 05/09 :
// NREM1 a 39 h et CREPUSCULE a 43 h pendant que NREM3 (02:03) et REM (04:00)
// venaient de tirer -- deux fenetres perdues au redemarrage de la nuit.
// Le cout n'est pas theorique : NREM1 porte l'EMETTEUR du snapshot memoire
// (cf. le bloc `phase === "NREM1"` de firePhase). Sans lui le snapshot perime,
// `_backlog_pending_qualifie()` rend INCONNU, et la strategie C_consolidation
// de `arbitrer_pression()` devient STRUCTURELLEMENT inatteignable -- le coder
// ne peut plus jamais ceder sa RAM a un embedder affame.
// `sleep_debt` de circadianStatus() voyait deja ce retard ; personne n'agissait.
const CIRCADIAN_CATCHUP_H = 28;  // > un cycle complet rate, pas un simple retard

/** La phase la plus en retard, ou null. Une phase JAMAIS tiree n'est pas un
 *  retard mesure (etat vierge = INCONNU) : on ne rattrape que ce qu'on a date. */
function phaseEnRetard(): { phase: Phase; hours: number } | null {
  let pire: { phase: Phase; hours: number } | null = null;
  for (const p of CIRCADIAN_PHASES) {
    const ts = circadianLastFired.get(p);
    if (!ts) continue;
    const h = (Date.now() / 1000 - ts) / 3600;
    if (h >= CIRCADIAN_CATCHUP_H && (!pire || h > pire.hours)) pire = { phase: p, hours: h };
  }
  return pire;
}

// ETAT CIRCADIEN (2026-09-24, mesure) : `Deno.writeTextFile` avait TRONQUE le fichier puis
// attendu indefiniment le pool bloquant sature (cf. _preuveDpopTpm) -- fichier a 0 octet,
// et `firePhase` suspendu avant ses appels NREM1 (route de declenchement en delai depasse,
// meme pour CREPUSCULE a 0 action). Deux corrections :
//   - ecriture SYNCHRONE et ATOMIQUE (fichier temporaire puis renommage) : ni attente du
//     pool, ni fichier vide si le process meurt au milieu ;
//   - un etat ILLISIBLE n'est PAS un etat vierge. Le lire comme « jamais tire » mettait
//     toutes les phases en dette et declenchait des rattrapages en serie. Absent = vierge ;
//     illisible = INCONNU -> dette NEUTRALISEE (dernier tir pose a maintenant), et dit.
async function loadCircadianState(): Promise<void> {
  let txt: string;
  try {
    txt = Deno.readTextFileSync(CIRCADIAN_STATE_PATH);
  } catch (_e) {
    return; // fichier inexistant = etat vierge
  }
  try {
    const obj = JSON.parse(txt);
    for (const [p, ts] of Object.entries(obj.last_fired ?? {})) {
      circadianLastFired.set(p as Phase, Number(ts));
    }
  } catch (e) {
    const maintenant = Date.now() / 1000;
    for (const p of Object.keys(PHASE_PROGRAM)) circadianLastFired.set(p as Phase, maintenant);
    log(`[circadian] etat ILLISIBLE (${(e as Error).message.slice(0, 80)}) -- traite comme INCONNU : ` +
        `dette neutralisee, aucune phase rattrapee sur la foi d'un fichier vide`);
  }
}

async function saveCircadianState(): Promise<void> {
  const obj = {
    last_fired: Object.fromEntries(circadianLastFired),
    saved_at: Date.now() / 1000,
  };
  try {
    Deno.mkdirSync(join(ROOT, "sandbox"), { recursive: true });
    const tmp = CIRCADIAN_STATE_PATH + ".tmp";
    Deno.writeTextFileSync(tmp, JSON.stringify(obj, null, 2));
    Deno.renameSync(tmp, CIRCADIAN_STATE_PATH);
  } catch (e) { log(`[circadian] state save: ${(e as Error).message}`); }
}

// Seuil : si le service tourne deja depuis < SKIP_IF_RUNNING_MS, on saute
// le restart - le cycle en cours doit pouvoir finir (offline_trainer
// complet ~50min, NMLP+JEPA+H-JEPA passent en LATE phase).
const CIRCADIAN_SKIP_IF_RUNNING_MS = 90 * 60_000; // 90 min

async function firePhase(phase: Phase): Promise<{ phase: Phase; results: unknown[] }> {
  const actions = PHASE_PROGRAM[phase];
  const results: unknown[] = [];
  log(`[circadian] FIRE phase=${phase} actions=${actions.length} organs=${actions.map(a=>a.organ).join(",")}`);
  for (const act of actions) {
    const state = states.get(act.service);
    if (!state) {
      // TROIS ETATS, JAMAIS DEUX (2026-09-20). `states` ne contient PAS les services
      // `disabled` (cf. `if (def.disabled) continue` au peuplement) : un service
      // ETEINT PAR CHOIX et un service QUI N'EXISTE PAS rendaient donc le meme
      // `unknown service`. C'est DISABLED_BY_POLICY confondu avec
      // RESOURCE_UNAVAILABLE -- envoyer quelqu'un reparer une DECISION.
      // Mesure du jour : 6 des 8 services du programme sont disabled depuis le
      // cutover du 2026-07-09, et NokidoAutoCompact n'est declare NULLE PART.
      // Seul le second est un defaut.
      const def = SERVICES.find((s) => s.name === act.service);
      if (!def) {
        results.push({ service: act.service, organ: act.organ,
          error: "service non declare dans services.toml" });
      } else {
        // Abstention DECLAREE : le corps se retient, il n'echoue pas.
        results.push({ service: act.service, organ: act.organ,
          abstention: "disabled par politique", disabled: true });
      }
      continue;
    }
    // SKIP si deja running depuis moins de 90 min : ne pas tuer un cycle
    // en cours (sinon le trainer ne complete jamais le world_model trio).
    const uptimeMs = state.lastStartMs > 0 ? Date.now() - state.lastStartMs : 0;
    if (state.status === "running" && uptimeMs < CIRCADIAN_SKIP_IF_RUNNING_MS) {
      log(`[circadian] SKIP ${act.service} - running since ${Math.round(uptimeMs/60000)}min < 90min cap`);
      results.push({ service: act.service, organ: act.organ,
        skipped: true, uptime_min: Math.round(uptimeMs/60000) });
      continue;
    }
    try {
      if (state.proc) state.proc.kill("SIGTERM");
      state.status = "stopped";
      state.backoffIdx = 0;
      await startService(state);
      results.push({ service: act.service, organ: act.organ, why: act.why, ok: true });
    } catch (e) {
      results.push({ service: act.service, organ: act.organ, error: (e as Error).message });
    }
  }
  // Une phase ne se solde pas parce qu'on l'a PARCOURUE, mais parce que ses actions
  // ont ABOUTI. Ce contrat etait deja arrete -- et commente dans ces termes memes --
  // cote Python (`forge_circadian.fire_phase`), protege par deux NR ; il manquait
  // ICI, sur le chemin qui s'execute reellement, `fire_phase` n'etant appele nulle
  // part en Python. Le correctif avait ete applique au jumeau mort.
  // Sans cette condition la dette restait a zero quoi qu'il arrive, donc `sleepDebt`
  // (> 48 h) ne pouvait JAMAIS se declencher : l'instrument rendait « sain » PARCE
  // QU'il ne regardait pas l'echec. Une abstention (`disabled`) n'est PAS un echec.
  const echecs = results.filter((r) => {
    const o = r as { error?: string; ok?: boolean };
    return o.error !== undefined || o.ok === false;
  });
  if (echecs.length > 0) {
    log(`[circadian] phase=${phase} NON soldee - ${echecs.length}/${results.length} action(s) en echec (la dette est CONSERVEE)`);
  } else {
    circadianLastFired.set(phase, Date.now() / 1000);
    await saveCircadianState();
  }
  // NREM1 (2026-07-25) — reconsolidation de la CARTE DE SOI pendant le sommeil leger.
  // NREM1 est la phase de consolidation hippocampique : le corps y rejoue ce qu'il a
  // appris de lui-meme. Ici : quel module est supervise, cable, invoque, ou que plus
  // rien ne tient (zone morte). Sans ce rappel periodique, l'audit reste une PHOTO
  // prise un jour donne et diverge en silence a chaque module ajoute ou debranche.
  // Le resultat alimente le RAG (un chunk par organe) + le cache lu par les cartes
  // de module et par l'atlas de proprioception. Fire-and-forget, fail-safe.
  if (phase === "NREM1") {
    // 2026-09-02 : ce site lisait le MAITRE en direct alors que
    // `_hubAuthHeaders()` existait deja -- un recablage a moitie, ou les
    // chemins ordinaires portaient le marqueur propre pendant que les appels
    // PRIVILEGIES (lancer un job) gardaient le passe-partout. Le journal du
    // hub lisait alors `bearer_maitre` sans pouvoir dire quel organe agissait.
    const headers: Record<string, string> = {
      "content-type": "application/json",
      ..._hubAuthHeaders(),
    };
    (async () => {
      try {
        const script = join(ROOT, "tools", "forge_body_regulation_audit.py");
        const headers = await _entetesAdminAvecPreuve("POST", "/admin/run_job");
        const r = await fetch("http://127.0.0.1:8766/admin/run_job", {
          method: "POST",
          headers,
          body: JSON.stringify({ script, online: false }),
          signal: AbortSignal.timeout(30_000), // detache : on n'attend QUE l'accuse
        });
        const j = await r.json().catch(() => ({}));
        log(`[circadian] proprioception audit job=${j.job_id ?? "?"} ok=${j.ok}`);
      } catch (e) {
        log(`[circadian] proprioception audit fail: ${(e as Error).message}`);
      }
    })();

    // EMETTEUR du snapshot de disponibilite memoire (2026-09-02).
    // `forge_resource_manager` decide sur le backlog vectoriel QUALIFIE
    // (PENDING seul, 124 659) et non sur `embedding IS NULL` (751 305, qui
    // melange 626 646 chunks refuses pour toujours). Ce calcul coute ~12 s :
    // il ne peut pas vivre sur le chemin chaud du regulateur, qui lit un
    // fichier en ~7 ms. Sans CE lancement, le snapshot perime et l'arbitre
    // bascule en INCONNU -- le motif « garde branche sur un signal que
    // personne n'emet », deja paye ici (frein d'insuline jamais declenche,
    // `llama.wanted` sans poseur pendant 73 arrets).
    (async () => {
      try {
        const script = join(ROOT, "tools", "forge_memory_snapshot_refresh.py");
        const headers = await _entetesAdminAvecPreuve("POST", "/admin/run_job");
        const r = await fetch("http://127.0.0.1:8766/admin/run_job", {
          method: "POST",
          headers,
          body: JSON.stringify({ script, online: false }),
          signal: AbortSignal.timeout(30_000), // detache : on n'attend QUE l'accuse
        });
        const j = await r.json().catch(() => ({}));
        log(`[circadian] snapshot memoire job=${j.job_id ?? "?"} ok=${j.ok}`);
      } catch (e) {
        log(`[circadian] snapshot memoire fail: ${(e as Error).message}`);
      }
    })();

    // Fraicheur des observateurs de capacite (2026-09-02, tour 0). Quatre
    // instruments existaient (crosswalk, execution_trace, reachability_ledger,
    // ratchet) et rendaient des verdicts honnetes, mais AUCUN cycle ne les
    // rejouait : matrices figees 17 jours, ratchet INDETERMINE par peremption.
    // Ce rejeu est une OBSERVATION : INDETERMINE n'est ni PASS ni FAIL et ne
    // solde ni n'echoue rien. Le circadien ne devient pas un gatekeeper.
    // Via /mcp (verbe run_job) et non /admin/run_job : seule cette voie passe
    // par forge_job_runner et honore la lane (anti-saturation du 2026-08-30).
    (async () => {
      try {
        const script = join(ROOT, "tools", "forge_capability_freshness.py");
        const r = await fetch("http://127.0.0.1:8766/mcp", {
          method: "POST",
          headers,
          body: JSON.stringify({
            jsonrpc: "2.0", id: 1, method: "tools/call",
            params: { name: "run", arguments: {
              action: "run_job", script, lane: "audit_capacites",
              explanation: "circadien NREM1 : rejeu des observateurs de capacite",
            } },
          }),
          signal: AbortSignal.timeout(30_000), // detache : on n'attend QUE l'accuse
        });
        // AUTHZ_DENIED n'est PAS SERVICE_DEAD. Un 401/403 dit que le rejeu n'a
        // PAS eu lieu alors que le hub va tres bien : le confondre avec une
        // panne rendrait la boucle muette exactement quand elle cesse de servir,
        // et les matrices revieilliraient sans que rien ne le dise.
        if (r.status === 401 || r.status === 403) {
          log(`[circadian] capability freshness AUTHZ_DENIED (${r.status}) -- ` +
              `le rejeu n'a PAS eu lieu ; hub joignable, marqueur du superviseur refuse`);
          return;
        }
        const j = await r.json().catch(() => ({}));
        const res = (j as { result?: unknown }).result ?? j;
        log(`[circadian] capability freshness accuse=${JSON.stringify(res).slice(0, 160)}`);
      } catch (e) {
        log(`[circadian] capability freshness INJOIGNABLE (panne, pas refus): ${(e as Error).message}`);
      }
    })();
  }

  // Phase 11 (2026-05-24) — glymphatic GC pendant NREM3 (sommeil profond).
  // Inspire systeme glymphatique : pendant le sommeil profond, le LCR lave
  // les toxines (beta-amyloides). Equivalent SQLite VACUUM + rotate logs +
  // clear caches. Fire-and-forget, fail-safe.
  if (phase === "NREM3") {
    // Meme correction qu'en NREM1 : le GC de maintenance est un appel
    // privilegie, il doit se presenter sous l'identite du superviseur.
    // 2026-09-24 : route gardee par `_admin_tok_ok` -> preuve TPM EXIGEE des que
    // LAFORGE_ADMIN_TPM_ENFORCE=1. Mesure du jour : cet appel partait SANS preuve
    // (INVERIFIABLE, 17:01:09) ; arme tel quel, le GC glymphatique aurait pris 401.
    (async () => {
      try {
        const headers = await _entetesAdminAvecPreuve("POST", "/api/maintenance/gc");
        const r = await fetch("http://127.0.0.1:8766/api/maintenance/gc", {
          method: "POST",
          headers,
          body: "{}",
          signal: AbortSignal.timeout(180_000), // VACUUM gros DB peut prendre 60-120s
        });
        const j = await r.json().catch(() => ({}));
        log(`[circadian] glymphatic GC ok=${j.ok} duration_s=${j.duration_s ?? "?"}`);
      } catch (e) {
        log(`[circadian] glymphatic GC fail: ${(e as Error).message}`);
      }
    })();
  }
  return { phase, results };
}

async function circadianLoop(): Promise<void> {
  await loadCircadianState();
  log("[circadian] loop started (60s tick, phase-fire si debt >= 20h)");
  while (true) {
    await delay(60_000);
    if (!circadianEnabled) continue;
    const phase = currentPhase();
    const lastTs = circadianLastFired.get(phase) ?? 0;
    const hoursSince = (Date.now() / 1000 - lastTs) / 3600;
    if (hoursSince >= 20) {
      try {
        await firePhase(phase);
      } catch (e) {
        log(`[circadian] fire error: ${(e as Error).message}`);
      }
      continue;
    }
    // Rien a tirer pour la phase courante : reprendre la fenetre manquee.
    // UNE SEULE par tick (60 s), donc jamais de rafale de redemarrages.
    const retard = phaseEnRetard();
    if (retard) {
      // LE RATTRAPAGE ATTEND SES DEPENDANCES (defaut MESURE le 2026-09-05, dans
      // l'heure suivant la mise en service du rattrapage lui-meme).
      //
      // Le premier CATCHUP a tire NREM1 a 15:49:31 ; 33 s plus tard le journal
      // montrait « dep :8766 not open yet — defer » sur QUATORZE services. Le hub
      // n'ecoutait pas encore, donc le POST vers /admin/run_job du bloc NREM1
      // n'avait personne au bout : la phase a ete marquee TIREE, et l'emetteur du
      // snapshot memoire -- la raison d'etre de ce rattrapage -- n'a rien produit.
      //
      // Le defaut est structurel, pas accidentel : au demarrage la dette est
      // MAXIMALE et le hub pas encore la, donc le rattrapage se declenche
      // systematiquement au pire moment. Pire, `firePhase` horodate la phase, ce
      // qui SOLDE la dette sans avoir rendu le service -- le retard disparait des
      // compteurs alors que le travail n'a pas eu lieu (`REQUESTED != ACHIEVED`).
      //
      // On reutilise `isPortOpen`, deja employe par le gestionnaire de deps ; le
      // rattrapage n'est pas urgent a la minute pres, il peut attendre un tick.
      const hubPret = await isPortOpen(8766);
      if (!hubPret) {
        log(`[circadian] CATCHUP differe phase=${retard.phase} ` +
            `debt=${retard.hours.toFixed(1)}h — hub :8766 pas encore ouvert`);
        continue;
      }
      log(`[circadian] CATCHUP phase=${retard.phase} debt=${retard.hours.toFixed(1)}h ` +
          `(fenetre manquee, phase courante=${phase})`);
      try {
        await firePhase(retard.phase);
      } catch (e) {
        log(`[circadian] catchup error: ${(e as Error).message}`);
      }
    }
  }
}

function circadianStatus(): Record<string, unknown> {
  const phase = currentPhase();
  const debtHours: Record<string, number> = {};
  const lastFired: Record<string, number | null> = {};
  for (const p of CIRCADIAN_PHASES) {
    const ts = circadianLastFired.get(p);
    debtHours[p] = ts ? Number(((Date.now() / 1000 - ts) / 3600).toFixed(1)) : Infinity;
    lastFired[p] = ts ?? null;
  }
  const sleepDebt = (debtHours.NREM1 > 48) || (debtHours.NREM3 > 48);
  return {
    enabled: circadianEnabled,
    active_phase: phase,
    active_organs: PHASE_PROGRAM[phase].map(a => a.organ),
    sleep_debt: sleepDebt,
    debt_hours: debtHours,
    last_fired: lastFired,
  };
}

// ───────────────────────────────────────────────────────────────────────────

function jsonResp(data: unknown, status = 200) {
  return new Response(JSON.stringify(data, null, 2), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

// Phase 23A (2026-05-24) — auth Bearer cote supervisor :8765. Critique
// Plan-securite : hub :8766 verifiait mais Deno re-verifie pas =
// `curl http://127.0.0.1:8765/supervisor/shutdown` cascade kill 40+ services.
// Compare timing-safe (subtle.timingSafeEqual via TextEncoder + manuelle).
// 2026-09-02 : les deux sources sont SEPAREES pour que le repli se voie.
// Ce jeton garde des routes qui tuent 40+ services ; l'accepter EN ENTREE sous
// la forme du passe-partout signifie que tout porteur du maitre -- c'est-a-dire
// tout organe qui n'a pas encore son marqueur propre -- peut declencher un
// shutdown en cascade. Le repli n'est pas retire ici : le retirer sans avoir
// provisionne `LAFORGE_SUPERVISOR_TOKEN` couperait l'acces owner, et c'est un
// arbitrage, pas une correction. Il est en revanche ANNONCE au demarrage --
// une faiblesse qu'on connait vaut mieux qu'une faiblesse qu'on suppose fermee.
const _SUPERVISOR_TOKEN_PROPRE = Deno.env.get("LAFORGE_SUPERVISOR_TOKEN") ?? "";
const _SUPERVISOR_TOKEN = _SUPERVISOR_TOKEN_PROPRE
  || (Deno.env.get("FORGE_MCP_TOKEN") ?? "");
const _SUPERVISOR_NO_AUTH = Deno.env.get("LAFORGE_NO_AUTH") === "1";
if (!_SUPERVISOR_TOKEN_PROPRE && _SUPERVISOR_TOKEN) {
  console.error(
    "[supervisor] AUTH D'ENTREE au jeton MAITRE (LAFORGE_SUPERVISOR_TOKEN " +
    "absent) : tout porteur du passe-partout peut atteindre les routes " +
    "mutantes de :8765, shutdown compris. Provisionner un jeton propre ferme " +
    "ce chemin.",
  );
} else if (!_SUPERVISOR_TOKEN) {
  console.error(
    "[supervisor] AUCUN jeton d'entree configure : les routes mutantes de " +
    ":8765 dependent entierement de LAFORGE_NO_AUTH (actuellement " +
    (_SUPERVISOR_NO_AUTH ? "1 = OUVERT" : "absent = ferme") + ").",
  );
}

function _timing_safe_equal(a: string, b: string): boolean {
  if (a.length !== b.length) return false;
  let diff = 0;
  for (let i = 0; i < a.length; i++) diff |= a.charCodeAt(i) ^ b.charCodeAt(i);
  return diff === 0;
}

function _supervisor_auth_ok(req: Request): boolean {
  // Endpoints read-only autorises sans auth (status pour TUI/monitoring legitimes)
  const url = new URL(req.url);
  const p = url.pathname;
  if (p === "/supervisor/status" && req.method === "GET") return true;
  if (p === "/supervisor/logs" && req.method === "GET") return true;
  if (p === "/supervisor/circadian/status" && req.method === "GET") return true;
  if (p === "/supervisor/llm/pool" && req.method === "GET") return true;
  // Reste = mutations -> require auth
  let tok = req.headers.get("authorization") ?? "";
  if (tok.toLowerCase().startsWith("bearer ")) tok = tok.slice(7).trim();
  else tok = tok.trim();
  if (!_SUPERVISOR_TOKEN) {
    return _SUPERVISOR_NO_AUTH;  // fallback flag explicite seulement
  }
  return _timing_safe_equal(tok, _SUPERVISOR_TOKEN);
}

// Phase 29 step 2 (2026-05-25) — extract W3C traceparent header. Format
// "version-traceid-parentid-flags". Si invalide ou absent : génère.
function _extractTrace(req: Request): { traceId: string; parentId: string } {
  const tp = req.headers.get("traceparent");
  if (tp) {
    const parts = tp.split("-");
    if (parts.length === 4 && parts[1].length === 32 && parts[2].length === 16) {
      return { traceId: parts[1], parentId: parts[2] };
    }
  }
  const tid = crypto.randomUUID().replace(/-/g, "");
  const pid = crypto.randomUUID().replace(/-/g, "").slice(0, 16);
  return { traceId: tid, parentId: pid };
}

// JOURNAL DES ORDRES (2026-09-24, question owner : « via l'authentification tu devrais avoir
// un tracage plus fin ? »). Les ordres mutants (sleep/wake/start/fire...) n'arrivent qu'avec
// UN jeton partage : impossible de dire QUI a endormi ou reveille un service (mesure du jour :
// 9 services endormis toutes les ~5 min, reveilleur inconnu). On inscrit, sans rien changer a
// l'autorisation : le nom DECLARE par l'appelant (declare n'est pas prouve -- etiquete comme
// tel), QUEL secret a ete presente (jamais sa valeur) et le traceparent. Ecriture SYNCHRONE :
// les E/S asynchrones attendent le pool bloquant sature (cf. _preuveDpopTpm).
const _JOURNAL_ORDRES = join(ROOT, "sandbox", "supervisor_ordres.jsonl");

function _journalOrdre(req: Request, chemin: string, traceId: string) {
  try {
    let tok = req.headers.get("authorization") ?? "";
    tok = tok.toLowerCase().startsWith("bearer ") ? tok.slice(7).trim() : tok.trim();
    const maitre = Deno.env.get("FORGE_MCP_TOKEN") ?? "";
    const secret = !tok ? "aucun"
      : (_SUPERVISOR_TOKEN && _timing_safe_equal(tok, _SUPERVISOR_TOKEN)) ? "supervisor"
      : (maitre && _timing_safe_equal(tok, maitre)) ? "maitre" : "autre";
    const ligne = JSON.stringify({
      ts: new Date().toISOString(), methode: req.method, chemin,
      agent_declare: req.headers.get("laforge-agent-name") ?? "?",
      secret_presente: secret, traceparent: traceId.slice(0, 16),
    }) + "\n";
    Deno.writeTextFileSync(_JOURNAL_ORDRES, ligne, { append: true });
  } catch (_e) { /* un journal ne bloque jamais un ordre */ }
}

async function handleCtrl(req: Request): Promise<Response> {
  // HOST VALIDE (2026-09-24, classe CVE-2026-48710). Deno construit `req.url` avec
  // l'en-tete Host : un Host forge ("127.0.0.1:8765/supervisor/status?x=") REECRIVAIT
  // la route -- mesure : la reponse servie etait celle de /supervisor/status. Aucun
  // contournement d'auth mesure (garde et routage lisent le meme chemin), mais la
  // route servie ne doit jamais dependre d'un en-tete choisi par le client. Le
  // superviseur n'ecoute que la boucle locale : tout autre Host est refuse en 400,
  // AVANT que l'URL ne soit construite.
  const hotesCtrl = new Set([
    `127.0.0.1:${CTRL_PORT}`,
    `localhost:${CTRL_PORT}`,
    `[::1]:${CTRL_PORT}`,
  ]);
  if (!hotesCtrl.has((req.headers.get("host") ?? "").toLowerCase())) {
    return jsonResp({ error: "bad_host" }, 400);
  }
  const url = new URL(req.url);
  const p = url.pathname;
  // Phase 23A gate global pour /supervisor/* mutations
  if (p.startsWith("/supervisor/") && !_supervisor_auth_ok(req)) {
    return jsonResp({ error: "unauthorized", path: p }, 401);
  }
  // Phase 29 step 2 — trace context cross-process Python <-> Deno
  const { traceId, parentId } = _extractTrace(req);
  if (p.startsWith("/supervisor/") && req.method !== "GET") {
    log(
      `[trace ${traceId.slice(0, 8)}] ${req.method} ${p} parent=${
        parentId.slice(0, 8)
      }`,
    );
    _journalOrdre(req, p, traceId);
  }

  if (p === "/supervisor/llm/pool" && req.method === "GET") {
    const pool = SERVICES.filter((s) => s.llmPool).map((s) => ({
      name: s.name,
      port: s.port,
      type: s.type ?? "process",
      status: states.get(s.name)?.status ?? "unknown",
    }));
    return jsonResp({ pool, max_active: LLM_POOL_MAX });
  }

  if (p.startsWith("/supervisor/llm/activate/") && req.method === "POST") {
    const name = p.replace("/supervisor/llm/activate/", "");
    const state = states.get(name);
    if (!state?.def.llmPool) return jsonResp({ error: "not in llm pool" }, 404);
    await enforcePool(name);
    state.status = "stopped";
    state.backoffIdx = 0;
    startService(state);
    return jsonResp({ ok: true, activating: name });
  }

  // Generic service start: pour services hors llmPool (NokidoWatchAgent,
  // NokidoOpenAIProxy, etc). Auth Bearer LAFORGE_SUPERVISOR_TOKEN identique
  // a llm/activate. Evite Start-Process manuel cote user.
  if (p.startsWith("/supervisor/service/start/") && req.method === "POST") {
    const name = p.replace("/supervisor/service/start/", "");
    let state = states.get(name);
    if (!state) {
      // Service on-demand (disabled=true dans services.toml) : pas instancie
      // dans `states` au boot (cf. for-loop L643 `if (def.disabled) continue`).
      // Le reveil = charger le def depuis SERVICES + creer le state a la volee.
      // Fix wake-disabled 2026-06-03 (SearXNG/etc renvoyaient 404 a la demande).
      const def = SERVICES.find((s) => s.name === name);
      if (!def) return jsonResp({ error: "unknown service", name }, 404);
      states.set(name, {
        def,
        status: "stopped",
        proc: null,
        pid: null,
        restartCount: 0,
        lastStartMs: 0,
        backoffIdx: 0,
        logFile: null,
        restartHistory: [],
        quarantineUntilMs: 0,
        heartbeat: null,
        quickFailCount: 0,
      });
      state = states.get(name)!;
      log(`[service/start] reveil on-demand "${name}" (disabled -> state cree)`);
    }
    if (state.status === "running") return jsonResp({ ok: true, already_running: name });
    state.status = "stopped";
    state.backoffIdx = 0;
    startService(state);
    return jsonResp({ ok: true, starting: name });
  }

  // Generic service stop: utile pour kill propre via supervisor (au lieu
  // de tasklist + taskkill). Stoppe le process + marque state pour eviter
  // restart auto immediat.
  if (p.startsWith("/supervisor/service/stop/") && req.method === "POST") {
    const name = p.replace("/supervisor/service/stop/", "");
    let state = states.get(name);
    if (!state) {
      // Symetrique du reveil on-demand ci-dessus. Un service `disabled=true`
      // n'est jamais instancie dans `states` au boot, si bien que /stop rendait
      // 404 "unknown service" sur un service pourtant DECLARE dans la SSoT.
      // MESURE 2026-08-19 : 31 des 85 services declares sont disabled, et ce
      // sont les PLUS gourmands -- tout le pool Llama, LM Studio, BrainWorker,
      // Searxng. Nokido savait donc les ALLUMER (fix wake-disabled du
      // 2026-06-03) et jamais les ETEINDRE : le seul geste qui rend de la
      // memoire etait le seul non couvert, et l'autoregulation restait aveugle
      // sur 36 % de sa propre surface. Un regulateur qui ne peut pas relacher
      // ne regule pas, il accumule.
      const def = SERVICES.find((s) => s.name === name);
      if (!def) return jsonResp({ error: "unknown service", name }, 404);
      states.set(name, {
        def,
        status: "stopped",
        proc: null,
        pid: null,
        restartCount: 0,
        lastStartMs: 0,
        backoffIdx: 0,
        logFile: null,
        restartHistory: [],
        quarantineUntilMs: 0,
        heartbeat: null,
        quickFailCount: 0,
      });
      state = states.get(name)!;
      log(`[service/stop] "${name}" on-demand (disabled -> state cree, stopped)`);
      // On NOMME l'absence de process tenu plutot que de rendre un `ok` muet :
      // un appelant qui lit "stopped" en deduit de la memoire rendue, et une
      // regulation qui croit avoir libere autorise la suite.
      return jsonResp({
        ok: true,
        stopped: name,
        held_process: false,
        note:
          "service on-demand : marque stopped (ne sera pas relance au prochain " +
          "tick) ; AUCUN process n'etait tenu par le superviseur, donc rien " +
          "n'a ete tue ici -- si le binaire tourne, il a ete lance hors " +
          "supervision et releve de son keeper",
      });
    }
    const held = !!state.proc;
    if (state.proc) {
      try { state.proc.kill("SIGTERM"); } catch (_) {}
    }
    state.status = "stopped";
    return jsonResp({ ok: true, stopped: name, held_process: held });
  }

  // CIRCADIAN endpoints
  if (p === "/supervisor/circadian/status" && req.method === "GET") {
    return jsonResp(circadianStatus());
  }
  if (p === "/supervisor/circadian/enable" && req.method === "POST") {
    circadianEnabled = true;
    return jsonResp({ ok: true, enabled: true });
  }
  if (p === "/supervisor/circadian/disable" && req.method === "POST") {
    circadianEnabled = false;
    return jsonResp({ ok: true, enabled: false });
  }
  const cm = p.match(/^\/supervisor\/circadian\/fire\/(AURORE|JOUR|CREPUSCULE|NREM1|NREM3|REM)$/);
  if (cm && req.method === "POST") {
    const r = await firePhase(cm[1] as Phase);
    return jsonResp(r);
  }

  if (p === "/supervisor/status") {
    const result: Record<string, unknown> = {};
    for (const [name, state] of states) {
      const entry: Record<string, unknown> = {
        status: state.status,
        wave: state.def.wave,
        pid: state.pid,
        restarts: state.restartCount,
        port: state.def.port,
        essential: state.def.essential,
        uptime_s: state.lastStartMs > 0
          ? Math.round((Date.now() - state.lastStartMs) / 1000)
          : null,
      };
      if (state.def.heartbeat) {
        entry.heartbeat_path = state.def.heartbeat;
        if (state.heartbeat) {
          entry.heartbeat = {
            ts: state.heartbeat.ts,
            stale_s: state.heartbeat.stale_s,
            health: state.heartbeat.health,
            raw: state.heartbeat.raw,
          };
        } else {
          entry.heartbeat = { health: "never_read" };
        }
      }
      result[name] = entry;
    }
    return jsonResp({ ts: ts(), services: result });
  }

  // Phase 2 patch 1+2 (2026-05-29) : re-read services.toml BEFORE every
  // restart/wake. Resout bug "restart utilise cmd cached" qui forcait
  // sequence sleep+reload+wake en 3 calls. Maintenant : 1 restart suffit.
  const m = p.match(/^\/supervisor\/(restart|sleep|wake)\/(.+)$/);
  if (m && (req.method === "POST" || req.method === "GET")) {
    const [, action, name] = m;
    const state = states.get(name);
    if (!state) return jsonResp({ error: "unknown service" }, 404);

    // Refresh state.def from services.toml on restart/wake so any edit
    // (cmd, args, env, port, runAs) lands without /supervisor/reload first.
    let defRefreshed = false;
    if (action === "restart" || action === "wake") {
      try {
        const fresh = loadServices(defaultTomlPath(), { ROOT, PROXY_DIR });
        if (fresh) {
          SERVICES = fresh;
          const freshDef = fresh.find((d) => d.name === name);
          if (freshDef) {
            state.def = freshDef;
            defRefreshed = true;
            log(`${name}: def refreshed from toml before ${action}`);
          }
        }
      } catch (e) {
        log(`${name}: toml refresh failed before ${action}: ${e}`);
      }
    }

    if (action === "restart") {
      if (state.proc) {
        try { state.proc.kill("SIGTERM"); } catch (_) {}
      }
      state.status = "stopped";
      state.backoffIdx = 0;
      // Explicit user intent = fresh start : clear quarantine + quick-fail
      // counters so a fixed-code restart isn't blocked by a stale cooldown.
      state.quickFailCount = 0;
      state.quarantineUntilMs = 0;
      await startService(state);
      return jsonResp({ ok: true, action: "restart", name, def_refreshed: defRefreshed });
    }
    if (action === "sleep") {
      if (state.proc) {
        try { state.proc.kill("SIGTERM"); } catch (_) {}
      }
      state.status = "sleeping";
      return jsonResp({ ok: true, action: "sleep", name });
    }
    if (action === "wake") {
      if (state.status === "sleeping" || state.status === "quarantine") {
        state.status = "stopped";
        state.backoffIdx = 0;
        state.quickFailCount = 0;
        state.quarantineUntilMs = 0;
        await delay(600);
        await startService(state);
      }
      return jsonResp({ ok: true, action: "wake", name, def_refreshed: defRefreshed });
    }
  }

  if (p === "/supervisor/logs" && req.method === "GET") {
    const name = url.searchParams.get("name");
    if (!name) return jsonResp({ error: "?name= required" }, 400);
    const logPath = join(LOG_DIR, `${name}.log`);
    try {
      const content = await Deno.readTextFile(logPath);
      const lines = content.split("\n").slice(-200).join("\n");
      return new Response(lines, {
        headers: { "Content-Type": "text/plain; charset=utf-8" },
      });
    } catch {
      return jsonResp({ error: "log not found" }, 404);
    }
  }

  // Hot-reload services.toml — V2 (additive + refresh-when-idle) :
  //   - re-parse services.toml ; si erreur, garde SERVICES en place
  //   - pour chaque def nouvelle (name absent de states map) : enregistre +
  //     spawn via startService (respecte def.disabled)
  //   - pour chaque def existante dont l'instance est IDLE (stopped|sleeping
  //     |quarantine|failed) : refresh state.def avec le def frais (cmd, args,
  //     env, runAs, port, …). Permet d'éditer un service down et lui faire
  //     repick le nouveau def au prochain wake — sans restart supervisor.
  //   - les services RUNNING|STARTING|RESTARTING|STOPPING gardent leur def
  //     bake-in : muter en pleine vie crée du drift (logs reflètent l'ancien
  //     spawn, restart utiliserait le nouveau = confusion).
  //   - ne stop PAS les services retires de toml (manuel via /supervisor/shutdown
  //     ou edit + restart supervisor) -> evite drop accidentel sur typo
  if (p === "/supervisor/reload" && req.method === "POST") {
    const fresh = loadServices(defaultTomlPath(), { ROOT, PROXY_DIR });
    if (!fresh) {
      return jsonResp({ ok: false, error: "loadServices returned null (parse error)" }, 500);
    }
    SERVICES = fresh;
    // Phase 2 patch 2bis (2026-05-29) : ?force=running update aussi les
    // services en cours. Default = idle-only (preserve behavior precedent).
    const forceRunning = url.searchParams.get("force") === "running";
    const added: string[] = [];
    const skipped_disabled: string[] = [];
    const refreshed: string[] = [];
    const kept_running: string[] = [];
    const running_refreshed: string[] = [];
    const IDLE_STATUSES = new Set<ServiceStatus>([
      "stopped", "sleeping", "quarantine", "disabled",
    ]);
    for (const def of fresh) {
      const existing = states.get(def.name);
      if (existing) {
        if (IDLE_STATUSES.has(existing.status)) {
          existing.def = def;
          refreshed.push(def.name);
        } else if (forceRunning) {
          // Refresh def for next restart -- doesn't disrupt current process.
          existing.def = def;
          running_refreshed.push(def.name);
        } else {
          kept_running.push(def.name);
        }
        continue;
      }
      if (def.disabled) {
        skipped_disabled.push(def.name);
        continue;
      }
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
        restartHistory: [],
        quarantineUntilMs: 0,
        heartbeat: null,
        quickFailCount: 0,
      });
      added.push(def.name);
    }
    // Spawn les ajouts en parallele (ne bloque pas la response HTTP)
    for (const name of added) {
      const st = states.get(name);
      if (st) startService(st).catch((e) => log(`reload spawn ${name}: ${e}`));
    }
    log(`reload: added=${added.length} refreshed=${refreshed.length} running_refreshed=${running_refreshed.length} kept_running=${kept_running.length} skipped_disabled=${skipped_disabled.length}`);
    return jsonResp({
      ok: true,
      added,
      refreshed,
      running_refreshed,
      kept_running_count: kept_running.length,
      skipped_disabled,
      total: fresh.length,
      force_running: forceRunning,
    });
  }

  // Graceful shutdown over HTTP — triggers the existing reverse-wave routine.
  // Respond first, then fire shutdown so the client gets the ack before the
  // process tears itself down.
  if (p === "/supervisor/shutdown" && req.method === "POST") {
    log("HTTP shutdown requested via /supervisor/shutdown");
    setTimeout(() => {
      shutdown();
    }, 100);
    return jsonResp({ ok: true, action: "shutdown" });
  }

  return new Response("404", { status: 404 });
}

// ─────────────────────────────────────────────────────────────────────────
// Heartbeat reader — Phase 3 autodiagnostic (2026-05-24)
// Pour chaque service avec def.heartbeat configure, lit le fichier toutes
// HEARTBEAT_POLL_MS, calcule stale_s, derive health, et si le service est
// running mais stale > HEARTBEAT_STALE_RESTART_S => SIGTERM + scheduleRestart
// (le PID vit mais le code est fige). Fail-safe : toute exception parser /
// IO est silencieuse, le snapshot stale precedent reste expose.
// ─────────────────────────────────────────────────────────────────────────
// Services dont l'absence de heartbeat a deja ete signalee (anti-spam du poll).
const _hbNotFoundVus = new Set<string>();
// Idem pour les lectures qui BLOQUENT (cause suspectee du gel d'un tier entier).
const _hbTimeoutVus = new Set<string>();
// Et pour celles qui ABOUTISSENT mais anormalement lentes : c'est la mesure qui
// designera l'engorgement, une lecture locale coutant ~5 ms.
const _hbLentVus = new Set<string>();
// Organes pour lesquels on s'est ABSTENU de relancer parce qu'ils declaraient un
// travail en cours. Set = on le dit UNE fois par organe, pas a chaque tour de boucle.
const _travailDeclareVus = new Set<string>();

function readOneHeartbeat(
  state: ServiceState,
  tier: HeartbeatTier,
): HeartbeatSnapshot | null {
  if (!state.def.heartbeat) return null;
  const path = join(ROOT, state.def.heartbeat);
  let mtime_s = 0;
  try {
    const st = Deno.statSync(path);
    if (st.mtime) mtime_s = Math.floor(st.mtime.getTime() / 1000);
  } catch (e) {
    // « pas pu lire » n'est PAS « rien a lire ». Ce catch rendait le meme null
    // pour un fichier ABSENT et pour un acces REFUSE / chemin mal resolu, et son
    // commentaire presupposait l'absence. Mesure 2026-07-26 : 9 services running
    // restaient `never_read` alors que leur heartbeat existait et etait FRAIS
    // (chain_executor 5.8s, cowork 0.2s), repartis sur les trois tiers — donc
    // pas une boucle morte, et rien dans les logs pour le dire. On journalise
    // desormais tout ce qui n'est PAS une absence : diagnostic seul, le
    // comportement (return null) est inchange.
    // 2026-07-29 : 21 services running sur 26 restent `never_read` alors que leur
    // fichier existe et est FRAIS (verifie sur disque a la seconde), et qu'aucune
    // ligne ILLISIBLE n'est journalisee — donc ce catch part en NotFound sur un
    // fichier present. Le chemin resolu est la seule inconnue : on l'imprime. UNE
    // fois par service, sinon un poll 5s noie le journal.
    if (!(e instanceof Deno.errors.NotFound)) {
      log(
        `${state.def.name}: heartbeat ILLISIBLE ${state.def.heartbeat} — ${
          (e as Error)?.name ?? "?"
        }: ${(e as Error)?.message ?? e}`,
      );
    } else if (!_hbNotFoundVus.has(state.def.name)) {
      _hbNotFoundVus.add(state.def.name);
      log(
        `${state.def.name}: heartbeat INTROUVABLE — declare="${state.def.heartbeat}" resolu="${path}" (ROOT="${ROOT}")`,
      );
    }
    return null; // absent, ou illisible (journalise ci-dessus)
  }
  let raw: Record<string, unknown> = {};
  let ts_field = 0;
  let health_field: "ok" | "degraded" | "crit" = "ok";
  try {
    const text = Deno.readTextFileSync(path);
    raw = JSON.parse(text);
    if (typeof raw.ts === "number") ts_field = raw.ts;
    if (
      raw.health === "ok" || raw.health === "degraded" || raw.health === "crit"
    ) {
      health_field = raw.health;
    }
  } catch {
    // file exists but is unparseable — keep mtime + raw={}
  }
  const effective_ts = ts_field > 0 ? ts_field : mtime_s;
  const now_s = Math.floor(Date.now() / 1000);
  const stale_s = Math.max(0, now_s - effective_ts);
  let health: HeartbeatSnapshot["health"] = health_field;
  if (stale_s >= tier.stale_restart_s) health = "stale";
  else if (stale_s >= tier.stale_degraded_s) {
    health = health_field === "ok" ? "degraded" : health_field;
  }
  return {
    ts: effective_ts,
    read_ts: now_s,
    file_mtime_s: mtime_s,
    stale_s,
    health,
    raw,
  };
}

// 1 loop par tier — isolation. Slow tier (60s poll) ne bloque pas fast (5s).
// Le superviseur surveille ses services, mais PERSONNE ne surveillait ses propres
// boucles de fond. Un `.catch(log)` journalise puis laisse mourir la boucle : le
// corps continue de tourner SANS ce capteur, en silence, jusqu'au prochain reboot.
// Mesure 2026-07-29 : `resourceLoop error: PermissionDenied` present sur 15 boots
// distincts — autant de sessions ou la regulation des ressources n'a plus rien
// mesure. Meme classe de panne que les services fantomes qu'il detecte chez les
// autres. On relance donc avec un recul croissant plafonne, au lieu de perdre le
// capteur. Une boucle qui rend la main sans exception est aussi une anomalie : on
// la relance et on le dit.
function superviseBoucle(nom: string, fabrique: () => Promise<void>): void {
  const relancer = async () => {
    let recul_ms = 5_000;
    for (;;) {
      try {
        await fabrique();
        log(`${nom}: boucle terminee sans erreur — relance dans ${recul_ms / 1000}s`);
      } catch (e) {
        log(`${nom} error: ${e} — relance dans ${recul_ms / 1000}s`);
      }
      await delay(recul_ms);
      recul_ms = Math.min(recul_ms * 2, 60_000);
    }
  };
  void relancer();
}

async function heartbeatLoopForTier(tierName: "fast" | "normal" | "slow") {
  const tier = HEARTBEAT_TIERS[tierName];
  while (true) {
    for (const [, state] of states) {
      if (!state.def.heartbeat) continue;
      if ((state.def.heartbeat_tier ?? "normal") !== tierName) continue;
      // Phase 12 fix : un service en sleeping/stopped/quarantine n'a pas a
      // publier de heartbeat (il ne tourne pas). Ne pas marquer stale.
      // Clear le snapshot existant pour eviter affichage trompeur.
      if (state.status !== "running") {
        state.heartbeat = null;
        continue;
      }
      try {
        // Un `await` qui ne revient JAMAIS ne leve rien et ne journalise rien : la
        // boucle du tier reste bloquee sur ce service et tous les SUIVANTS ne sont
        // plus jamais lus. Mesure 2026-07-29 : 22 services running restaient
        // `never_read` avec des fichiers frais, zero exception, zero ligne de log —
        // et seuls les 4 services du tier `fast` (le plus court) etaient servis.
        // Une lecture de heartbeat est une operation de quelques ms : au-dela d'une
        // seconde, on abandonne CE service et on passe au suivant, plutot que de
        // perdre le capteur entier. Le blocage devient visible au lieu d'etre mut.
        // Borne mesuree le 2026-07-29. A 1s elle abandonnait TOUTES les lectures :
        // « lent » devenait « jamais ». Les memes fichiers se lisent en 0,1-6,4 ms
        // hors Deno (mediane 4,7 ms, disque local, ROOT verifie correct) — donc ce
        // qui traine n'est ni le stockage ni le chemin, mais la file d'operations
        // asynchrones du superviseur. On laisse la lecture aboutir (10s, tres
        // au-dessus du reel) tout en gardant le garde-fou anti-gel, et on MESURE :
        // toute lecture au-dela de 200 ms est anormale et se journalise une fois.
        const _t0 = Date.now();
        const snap = readOneHeartbeat(state, tier);
        const _dt = Date.now() - _t0;
        if (_dt > 200 && !_hbLentVus.has(state.def.name)) {
          _hbLentVus.add(state.def.name);
          log(
            `${state.def.name}: lecture heartbeat LENTE ${_dt}ms (${state.def.heartbeat}, tier=${tierName}) — attendu ~5ms`,
          );
        }
        if (snap) {
          state.heartbeat = snap;
          if (
            snap.stale_s >= tier.stale_restart_s &&
            state.status === "running" && state.proc &&
            // Garde de generation HEARTBEAT (RCA tueur #2, 2026-07-03) : ne
            // tuer que si le beat STALE a ete ecrit APRES le spawn de CE
            // process. Un enfant frais herite du beat vieillissant de son
            // predecesseur mort -> sans cette garde il est condamne avant
            // d'avoir ecrit son premier beat (warmup > stale_restart_s) :
            // kill a spawn+90s, quickFail++, quarantine, flotte down
            // (metronome observe 12:34-12:43). Le cas "ne beat jamais"
            // (vrai boot fige) reste couvert par le probe HTTP P1.1
            // (6x20s) et le kill-watchdog interne du hub (60s).
            snap.ts >= Math.floor(state.lastStartMs / 1000)
          ) {
            // UN CYCLE LONG N'EST PAS UNE MORT (arbitrage owner 2026-09-03).
            // Le pouls atteste de la PERFUSION, jamais de l'achevement d'un cycle :
            // `heartbeat != work completed`. Un organe qui DECLARE un travail en
            // cours (forge_heartbeat.Cadence) n'est pas fige, il est occupe — un
            // crawl de quatre minutes se lisait « process frozen » et coutait une
            // relance, alors que rien n'etait casse.
            //
            // On s'abstient, mais on ne se TAIT pas : l'absence de progres pendant
            // un travail declare est une anomalie a QUALIFIER (consommation,
            // progression, changement d'etat) — c'est le role du diagnostic, pas
            // celui d'un reflexe qui tue. Le superviseur constate ; il n'instruit pas.
            const _hbRaw = (snap.raw ?? {}) as Record<string, unknown>;
            const _enTravail = _hbRaw.travail_en_cours === true;
            // DUREE REELLE du travail, et non celle qu'annonce le fichier. Un process
            // GELE n'ecrit plus : son dernier beat porte un `travail_depuis_s` FIGE,
            // vieux de `stale_s`. La somme des deux est la seule mesure honnete.
            const _declare = typeof _hbRaw.travail_depuis_s === "number"
              ? _hbRaw.travail_depuis_s
              : 0;
            const _depuis = _declare + snap.stale_s;
            // PLAFOND DE L'EXEMPTION. Sans lui, `travail_en_cours` ferait d'un organe
            // gele un organe IMMORTEL : il se bloque, n'ecrit plus, son drapeau reste
            // a true, et plus personne ne le releve. On aurait echange un faux positif
            // (relance abusive d'un crawl long) contre un faux negatif (blocage
            // definitif jamais detecte) -- le second est pire, parce qu'il est MUET.
            // Le plafond est large a dessein : il ne cherche pas a juger un travail
            // long, seulement a ce qu'une exemption ne soit jamais eternelle. Derive
            // du tier (x4) plutot que declare par service : un champ de plus
            // demanderait de toucher ServiceDef ET le loader TOML, pour un reglage
            // dont aucun organe n'a encore montre le besoin. Le jour ou un travail
            // legitime le depasse, le journal le nommera avant qu'on l'ajoute.
            const _plafond = 4 * tier.stale_restart_s;
            if (_enTravail && _depuis < _plafond) {
              if (!_travailDeclareVus.has(state.def.name)) {
                _travailDeclareVus.add(state.def.name);
                log(
                  `${state.def.name}: beat stale ${snap.stale_s}s MAIS l'organe declare un travail en cours depuis ${_depuis}s (plafond ${_plafond}s) — pas de relance, un cycle long n'est pas une mort (a qualifier par le diagnostic si le progres ne repart pas)`,
                );
              }
            } else {
              _travailDeclareVus.delete(state.def.name);
              if (_enTravail) {
                log(
                  `${state.def.name}: travail declare depuis ${_depuis}s > plafond ${_plafond}s — l'exemption NE COUVRE PLUS. Un travail qui n'aboutit jamais n'est plus un travail : relance`,
                );
              }
              log(
                `${state.def.name}: heartbeat stale ${snap.stale_s}s >= ${tier.stale_restart_s}s (tier=${tierName}) — process frozen, restarting`,
              );
              try {
                state.proc.kill("SIGTERM");
              } catch { /* already dead */ }
              state.status = "stopped";
              state.backoffIdx = 0;
              scheduleRestart(state);
            }
          }
        }
      } catch { /* never crash the loop */ }
    }
    await delay(tier.poll_ms);
  }
}

// ─────────────────────────────────────────────────────────────────────────
// Health surface + probe HTTP actif du hub (P1.1 + P1.3, 2026-06-03)
// P1.1 : un service peut etre "running" (PID vif, port BOUND) mais WEDGE —
//   event loop fige -> /health ne repond plus. isPortOpen ment alors ("up").
//   On PROBE /health ; N echecs consecutifs (status=running) => restart.
//   Conservateur : 6 x 20s = ~2min de KO (> warmup rag 7GB) avant d'agir.
// P1.3 : ecrit sandbox/health.json chaque tick -> etat machine-lisible par
//   TOUT contexte (sandbox / user) MEME hub down (incident 2026-06-03 :
//   aucun etat lisible sans parser les logs a la main).
// ─────────────────────────────────────────────────────────────────────────
async function probeHttp(url: string, timeoutMs = 4000): Promise<boolean> {
  try {
    const ctl = new AbortController();
    const t = setTimeout(() => ctl.abort(), timeoutMs);
    const r = await fetch(url, { signal: ctl.signal });
    clearTimeout(t);
    try {
      await r.body?.cancel();
    } catch { /* noop */ }
    return r.ok;
  } catch {
    return false;
  }
}

let _hubHealthFails = 0;
const HUB_HEALTH_RESTART_THRESHOLD = 6; // 6 x 20s ~= 2min wedge (> warmup)
let _lastDegradedKey = ""; // pour alerter UNIQUEMENT sur transition (pas de spam)
let _degradedTicks = 0;
const AUTO_RECONCILE_AFTER = 3; // 3 x 20s = 60s d'essentiels dégradés -> auto-heal

// --- Supervision PERIODIQUE du contrat de sante applicatif ------------------
// Le correctif du 2026-09-11 ne mesurait la sante applicative QU'AU DEMARRAGE.
// Resultat lisible dans le journal du jour : `APPLICATION_DOWN = 0` pendant que
// le portail :7400 etait mort a l'usage depuis des heures. Un capteur qui ne
// regarde qu'une fois ne dit rien de la vie du service -- il dit seulement
// qu'il est NE vivant.
//
// Pas de second surveillant : cette supervision vit dans la boucle de sante qui
// existe deja (tick 20 s, sonde deja un /health, publie deja la surface). Deux
// autorites sur le meme etat valent moins qu'une.
//
// UN ECHEC N'EST PAS UNE MORT (STALE != DEAD) : il faut N ticks consecutifs,
// comme le hub exige deja 6 echecs avant de conclure au wedge.
const APP_DOWN_TICKS_AVANT_DEGRADED = 3; // 3 x 20 s = 60 s
const APP_SONDE_BUDGET_MS = 8_000; // ceinture : voir plus bas
const _appDownStreak = new Map<string, number>();

async function healthSurfaceLoop() {
  const HEALTH_FILE = join(ROOT, "sandbox", "health.json");
  while (true) {
    let hubHealthy = true;
    try {
      const hub = states.get("NokidoMCP");
      if (hub && hub.status === "running") {
        hubHealthy = await probeHttp("http://127.0.0.1:8766/health");
        if (!hubHealthy) {
          _hubHealthFails++;
          log(
            `⚠ NokidoMCP /health KO (${_hubHealthFails}/${HUB_HEALTH_RESTART_THRESHOLD}) — port up mais wedgé ?`,
          );
          if (_hubHealthFails >= HUB_HEALTH_RESTART_THRESHOLD && hub.proc) {
            log(`NokidoMCP wedgé confirmé (${_hubHealthFails}x) — SIGTERM + restart`);
            try {
              hub.proc.kill("SIGTERM");
            } catch { /* already dead */ }
            hub.status = "stopped";
            hub.backoffIdx = 0;
            scheduleRestart(hub);
            _hubHealthFails = 0;
          }
        } else {
          _hubHealthFails = 0;
        }
      }
    } catch (e) {
      log(`healthSurfaceLoop probe error: ${e}`);
    }
    // --- CONTRAT APPLICATIF, tous services confondus -----------------------
    // Aucun nom de service en dur : c'est le TOML qui declare `health_path`.
    // Un service qui n'en declare pas n'est pas surveille ici, et il n'est pas
    // non plus repute sain : il est NON MESURE, et il le reste.
    try {
      // NEUTRALISE le 2026-09-12 -- sur MESURE, pas sur soupcon.
      //
      // Ce bloc n'a jamais ete exerce de la nuit : NokidoWebHub est le seul
      // service declarant un health_path, et il etait `stopped`, donc la liste
      // restait vide. La PREMIERE fois qu'un porteur a ete sonde (start de
      // NokidoWebHub a 00:07:43), healthSurfaceLoop s'est arretee : ts et
      // mtime de health.json figes sur 6 releves espaces de 15 s, alors que le
      // tick est de 20 s. Le superviseur, lui, vivait (pid 3052, :8765 en
      // LISTENING, stderr vide, aucune exception).
      //
      // Consequence pendant ce temps : plus de sonde /health sur le hub, plus
      // d'auto-reconcile. Une flotte sans surveillance coute plus qu'un
      // diagnostic differe -- on rend la surveillance d'abord.
      //
      // Liste vide = le bloc ne fait rien et la boucle respire. Le reste du
      // code est laisse INTACT : il documente le contrat a reparer, et le
      // rendre a nouveau actif tiendra en une ligne, une fois la cause
      // etablie. Piste a instruire a froid : `appHealthy` fait
      // `await r.body?.cancel()` APRES la reponse du fetch, donc hors de la
      // portee de son AbortController -- une attente qui n'est plus bornee.
      const porteurs = [...states.values()].filter(() => false);
      const sonder = Promise.all(porteurs.map(async (s) => {
        try {
          return [s, await appHealthy(s.def.port!, s.def.health_path)] as const;
        } catch (e) {
          // Une sonde qui echoue n'est pas un service mort : c'est une mesure
          // absente. Trois etats, jamais deux.
          log(`${s.def.name}: sonde applicative ILLISIBLE (${e}) -- NON MESUREE`);
          return [s, HEALTH_UNKNOWN] as const;
        }
      }));
      // CEINTURE ANTI-GEL (incident 2026-07-29) : un `await` qui ne revient
      // jamais ne leve rien et ne journalise rien -- il fige la boucle entiere
      // et tous les services suivants cessent d'etre lus, en silence. On borne
      // le tour de sondes ; au-dela, ce tick ne conclut RIEN, et il le dit.
      const mesures = await Promise.race([
        sonder,
        delay(APP_SONDE_BUDGET_MS).then(() => null),
      ]);
      if (mesures === null) {
        log(
          `sondes applicatives non revenues en ${APP_SONDE_BUDGET_MS}ms ` +
            `(${porteurs.length} porteur(s)) -- tick NON CONCLUANT, aucun etat change`,
        );
      } else {
        for (const [st, vitalite] of mesures) {
          if (vitalite === HEALTH_UNKNOWN) {
            _appDownStreak.delete(st.def.name);
            continue; // ni sain, ni mort : on ne touche a rien
          }
          if (vitalite === "app_up") {
            if (st.status === "degraded") {
              log(
                `${st.def.name}: APPLICATION_UP retrouve -- ${st.def.health_path} repond`,
              );
              st.status = "running";
            }
            _appDownStreak.delete(st.def.name);
            continue;
          }
          const n = (_appDownStreak.get(st.def.name) ?? 0) + 1;
          _appDownStreak.set(st.def.name, n);
          if (n >= APP_DOWN_TICKS_AVANT_DEGRADED && st.status === "running") {
            // Le superviseur CONSTATE ; il n'instruit pas et ne tue pas ici.
            // C'est precisement le mode de panne qui restait invisible : le
            // port repond, le process vit, l'application est figee.
            st.status = "degraded";
            log(
              `${st.def.name}: APPLICATION_DOWN confirme (${n} ticks) -- ` +
                `port ${st.def.port} OUVERT mais ${st.def.health_path} muet. ` +
                `Etat degraded ; AUCUN redemarrage automatique.`,
            );
          }
        }
      }
    } catch (e) {
      log(`healthSurfaceLoop contrat applicatif: ${e}`);
    }
    // P1.3 — surface santé hub-indépendante.
    try {
      const svc: Record<string, unknown> = {};
      const degradedEssential: string[] = [];
      for (const [name, st] of states) {
        svc[name] = {
          status: st.status,
          wave: st.def.wave ?? 1,
          port: st.def.port ?? null,
          essential: !!st.def.essential,
          restarts: st.restartCount ?? 0,
        };
        if (st.def.essential && st.status !== "running") degradedEssential.push(name);
      }
      // Alerte PUSH sur TRANSITION (les 18 down de l'incident etaient invisibles
      // jusqu'au whoami). 'sleeping'/'disabled' ne comptent pas comme degrade.
      const _dkey = degradedEssential.slice().sort().join(",");
      if (_dkey !== _lastDegradedKey) {
        if (degradedEssential.length) {
          log(`⚠ ESSENTIELS DÉGRADÉS (${degradedEssential.length}): ${degradedEssential.join(", ")}`);
        } else if (_lastDegradedKey) {
          log(`✅ essentiels rétablis`);
        }
        _lastDegradedKey = _dkey;
      }
      // Auto-heal de la cascade boot-flap : si des essentiels restent dégradés
      // ET le hub est sain, relancer les services wave 2-6 STOPPÉS (jamais
      // disabled/sleeping/quarantine/starting -> respecte le crash-loop guard)
      // après N ticks. Plus de reconcile manuel (incident 2026-06-03).
      if (hubHealthy && degradedEssential.length) {
        _degradedTicks++;
        if (_degradedTicks >= AUTO_RECONCILE_AFTER) {
          const toStart = [...states.values()].filter((s) =>
            (s.def.wave ?? 1) >= 2 && !s.def.disabled && s.status === "stopped"
          ).sort((a, b) => (a.def.wave ?? 1) - (b.def.wave ?? 1));
          if (toStart.length) {
            log(
              `🔧 auto-reconcile: ${toStart.length} service(s) stoppé(s) ` +
                `(essentiels dégradés ${_degradedTicks} ticks) → startService`,
            );
            for (const st of toStart) {
              startService(st).catch((e) => log(`auto-reconcile ${st.def.name}: ${e}`));
            }
          }
          _degradedTicks = 0;
        }
      } else {
        _degradedTicks = 0;
      }
      const snap = {
        ts: Math.floor(Date.now() / 1000),
        hub_healthy: hubHealthy,
        hub_health_fails: _hubHealthFails,
        degraded_essential: degradedEssential,
        degraded_count: [...states.values()].filter(
          (s) => s.status !== "running" && s.status !== "sleeping" && !s.def.disabled,
        ).length,
        services: svc,
      };
      // Ecriture ATOMIQUE (tmp + rename) : evite le 0-octet + le hang sur sharing-lock
      // Windows si un lecteur tient health.json ouvert (la loop se figeait sur longue
      // uptime, health.json 0 octet — incident 2026-07-01). rename = instantane, jamais
      // de fichier tronque visible ; un echec de replace est catch + retente au tick suivant.
      const _hjTmp = HEALTH_FILE + ".tmp";
      await Deno.writeTextFile(_hjTmp, JSON.stringify(snap, null, 2));
      await Deno.rename(_hjTmp, HEALTH_FILE);
    } catch (e) {
      log(`healthSurfaceLoop write error: ${e}`);
    }
    await delay(20000);
  }
}

let _shuttingDown = false;

async function shutdown() {
  if (_shuttingDown) return;
  _shuttingDown = true;
  log("Graceful shutdown — reverse-wave sequence (5→1)");

  const maxWave = Math.max(...SERVICES.map((s) => s.wave || 1));

  for (let w = maxWave; w >= 1; w--) {
    const waveStates = Array.from(states.values()).filter(
      (s) => (s.def.wave || 1) === w && s.proc,
    );
    if (!waveStates.length) continue;

    log(`Wave ${w}: SIGTERM → ${waveStates.map((s) => s.def.name).join(", ")}`);
    for (const state of waveStates) {
      try { state.proc!.kill("SIGTERM"); } catch { /* already dead */ }
    }

    // Wait up to 6 s; SIGKILL stragglers
    await Promise.race([
      Promise.all(waveStates.map((s) => s.proc!.status.catch(() => {}))),
      delay(6_000),
    ]);
    for (const state of waveStates) {
      if (state.proc) {
        try {
          state.proc.kill("SIGKILL");
          log(`${state.def.name}: SIGKILL (no exit in 6s)`);
        } catch { /* already reaped */ }
      }
    }
    await delay(150);
  }

  log("Shutdown complete.");
  Deno.exit(0);
}

async function main() {
  await ensureDir(LOG_DIR);
  log(
    `LaForge-Master supervisor starting — ${
      SERVICES.filter((s) => !s.disabled).length
    } services`,
  );
  log(`LOG_DIR=${LOG_DIR}`);
  log(`CTRL=:${CTRL_PORT}`);
  log(`Nokido.env: ${_N_ENV_LOADED} vars chargees`);
  // Bilan du COFFRE (noms seulement) : apres le retrait des secrets du registre NSSM
  // (etape F), c'est la SEULE source des jetons du superviseur.
  log(`coffre: ${_VAULT_BILAN.charges.length} secret(s) charge(s) [${_VAULT_BILAN.charges.join(", ")}]` +
    (_VAULT_BILAN.absents.length ? ` ; ABSENTS [${_VAULT_BILAN.absents.join(", ")}]` : "") +
    (_VAULT_BILAN.erreur ? ` ; ERREUR ${_VAULT_BILAN.erreur}` : "") +
    ` (${_N_VAULT_LOADED} valeur(s) posee(s) ou corrigee(s))`);
  if (!_VAULT_BILAN.charges.includes("LAFORGE_SUPERVISOR_TOKEN")) {
    console.error("[supervisor] ALERTE : LAFORGE_SUPERVISOR_TOKEN NON charge depuis le coffre -- " +
      "sans lui (et sans NSSM) toute mutation sera refusee. Verifier le coffre reserve.");
  }

  // Single-instance guard : si un superviseur VIVANT possède déjà :8765, cette
  // instance est un doublon (restart-collision). Sortir PROPREMENT (exit 0)
  // AVANT pid_gc / orphan_reaper / waves — un doublon ne doit RIEN toucher.
  // Sinon il crashait uncaught sur le bind Deno.serve (AddrInUse os 10048) APRÈS
  // avoir déjà exécuté pid_gc+reaper → la boucle de waves ne se déroulait jamais
  // sur l'instance survivante (incident cascade 2026-06-03).
  if (await isPortOpen(CTRL_PORT)) {
    log(
      `⛔ CTRL_PORT :${CTRL_PORT} déjà détenu par un superviseur vivant — ` +
        `instance doublon, sortie propre (exit 0, pas de double-boot).`,
    );
    Deno.exit(0);
  }

  // PID GC: nettoyer les pidfiles stales AVANT tout spawn (incident 2026-05-25).
  // Sandbox a accumule 14 .pid files orphelins (PIDs morts depuis avril) qui
  // bloquaient les daemons sur "Another instance already running". Le script
  // valide via psutil.cmdline match — pas seulement OpenProcess (false positive
  // sur PIDs recycles inaccessibles).
  try {
    const pidGcStart = Date.now();
    const pidGc = await new Deno.Command(MINIFORGE, {
      args: [join(ROOT, "tools/forge_pid_gc.py")],
      stdout: "piped",
      stderr: "piped",
    }).output();
    const summary = new TextDecoder().decode(pidGc.stdout)
      .trim().split("\n").filter((l) => l.startsWith("Total:")).pop() ?? "ok";
    log(`PID GC (${Date.now() - pidGcStart}ms): ${summary}`);
  } catch (e) {
    log(`PID GC failed (continuing): ${e}`);
  }

  // Orphan reaper : tue les daemons orphelins d'un superviseur precedent AVANT
  // les vagues. Les services non-runAs sont spawnes sans Job Object (cf spawn
  // plus bas) -> si ce superviseur est mort sans graceful shutdown (nssm stop
  // Windows ne fire pas toujours le SIGTERM listener), ses enfants survivent et
  // s'accumulent a chaque restart (incident coma 2026-06-02 : homeostasis x2,
  // multi_llm x3 -> pression -> coma). Reaper = table rase a chaque boot.
  // DRY-RUN tant que "--arm" absent : on observe les candidats dans CE log au
  // prochain boot, puis on ajoute "--arm". Cf tools/forge_orphan_reaper.py.
  try {
    const reapStart = Date.now();
    const reap = await new Deno.Command(MINIFORGE, {
      args: [join(ROOT, "tools/forge_orphan_reaper.py")], // + "--arm" apres validation
      stdout: "piped",
      stderr: "piped",
    }).output();
    const summary = new TextDecoder().decode(reap.stdout)
      .trim().split("\n").filter((l) => l.includes("orphan_reaper[")).pop() ?? "ok";
    log(`Orphan reaper (${Date.now() - reapStart}ms): ${summary}`);
  } catch (e) {
    log(`Orphan reaper failed (continuing): ${e}`);
  }

  // Race-safe : une autre instance peut avoir gagné le bind entre le guard
  // ci-dessus et ici. AddrInUse → sortie propre (PAS un crash uncaught), pour
  // que l'instance survivante poursuive son boot sans perturbation.
  try {
    Deno.serve({ port: CTRL_PORT, hostname: "127.0.0.1" }, handleCtrl);
  } catch (e) {
    log(
      `⛔ Bind CTRL_PORT :${CTRL_PORT} échoué (${e}) — autre superviseur a ` +
        `gagné la course; sortie propre.`,
    );
    Deno.exit(0);
  }
  log(`Control API: http://127.0.0.1:${CTRL_PORT}/supervisor/status`);

  superviseBoucle("resourceLoop", resourceLoop);
  superviseBoucle("circadianLoop", circadianLoop);
  superviseBoucle("hbLoop fast", () => heartbeatLoopForTier("fast"));
  superviseBoucle("hbLoop normal", () => heartbeatLoopForTier("normal"));
  superviseBoucle("hbLoop slow", () => heartbeatLoopForTier("slow"));
  superviseBoucle("healthSurfaceLoop", healthSurfaceLoop);

  // ── SEQUENÇAGE DE BOOT EN VAGUES ──────────────────────────────────────
  const maxWave = Math.max(...SERVICES.map((s) => s.wave || 1));
  for (let w = 1; w <= maxWave; w++) {
    log(`🌊 Démarrage Vague Physiologique ${w} ...`);
    const waveServices = Array.from(states.values()).filter((s) =>
      (s.def.wave || 1) === w
    );

    // Démarre la vague en parallèle. startService gère déjà l'attente des `deps`
    // Boot-spike RCA : vague 3 = BrainWorker BGE-M3 (~4 GB) ; vague 4 = ~10
    // daemons python. Lancés en rafale (100ms) ils s'empilent sur le rag_warmup
    // du hub (lecture embeddings.db ~7 GB) → pic RAM/NVMe/CPU au démarrage.
    // On étale les vagues lourdes pour aplatir le pic (boot plus long, peak bas).
    const heavyWave = w >= 3;
    const intraDelay = heavyWave ? 1500 : 100;
    for (const state of waveServices) {
      startService(state).catch((e) =>
        log(`${state.def.name} start error: ${e}`)
      );
      await delay(intraDelay);
    }

    // Attendre que la vague se stabilise (plus long après les vagues lourdes
    // pour laisser le warmup hub finir avant le flood suivant).
    await delay(heavyWave ? 8000 : 3000);
    log(`✅ Vague ${w} stabilisée.`);
  }

  try {
    Deno.addSignalListener("SIGINT", () => {
      shutdown();
    });
  } catch {}
  try {
    Deno.addSignalListener("SIGTERM", () => {
      shutdown();
    });
  } catch {}

  await new Promise<void>(() => {});
}

main();
