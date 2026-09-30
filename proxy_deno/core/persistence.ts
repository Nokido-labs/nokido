/**
 * persistence.ts — Hybrid RAM/Disk persistence layer for Nokido Deno proxy.
 *
 * Trois mécanismes :
 *  1. TokenVault     — WAL append-only (.jsonl) + checkpoint horaire
 *  2. StateStore     — state.json mis à jour à chaque mutation
 *  3. BrainSnapshot  — snapshot complet ramVectorStore toutes les 15min
 *
 * Cible : bind mount `nokido_persist/` (NTFS Windows natif, hors VHDX
 * → compatible VSS / Historique de fichiers).
 *
 * ENV :
 *  - LAFORGE_PERSIST_DIR  : default ../nokido_persist (relatif au CWD Deno)
 *  - LAFORGE_BRAIN_INTERVAL_MS : default 900_000 (15min)
 *  - LAFORGE_VAULT_CHECKPOINT_MS : default 3_600_000 (1h)
 */

import { join, resolve } from "https://deno.land/std/path/mod.ts";

// ──────────────────────────────────────────────────────────────────────
// Config
// ──────────────────────────────────────────────────────────────────────
const DEFAULT_DIR = resolve(Deno.cwd(), "..", "nokido_persist");
const PERSIST_DIR = Deno.env.get("LAFORGE_PERSIST_DIR") ?? DEFAULT_DIR;
const VAULT_WAL = join(PERSIST_DIR, "vault_wal.jsonl");
const VAULT_CKP = join(PERSIST_DIR, "vault_checkpoint.json");
const STATE_FILE = join(PERSIST_DIR, "state.json");
const SNAPSHOT_DIR = join(PERSIST_DIR, "snapshots");

const BRAIN_INTERVAL = parseInt(
  Deno.env.get("LAFORGE_BRAIN_INTERVAL_MS") ?? "900000",
  10,
);
const VAULT_CKP_INTERVAL = parseInt(
  Deno.env.get("LAFORGE_VAULT_CHECKPOINT_MS") ?? "3600000",
  10,
);

async function ensureDirs() {
  await Deno.mkdir(PERSIST_DIR, { recursive: true });
  await Deno.mkdir(SNAPSHOT_DIR, { recursive: true });
}

// ──────────────────────────────────────────────────────────────────────
// 1. TokenVault — alias HMAC (SovereignMembrane analog côté Deno)
// ──────────────────────────────────────────────────────────────────────
type VaultEntry = {
  alias: string;       // ex: VAULT_IP_8f4c
  real: string;        // ex: localhost
  mission: string;     // ex: recon_20260424
  ts: number;
};

const ramVault = new Map<string, VaultEntry>(); // alias → entry
let walAppendPromise: Promise<void> = Promise.resolve();

/**
 * Append-only WAL : chaque set s écrit sur disque AVANT retour.
 * Sérialisation : JSONL (une ligne JSON par mutation).
 * Op : "set" (ajoute), "del" (efface alias), "ckp" (marqueur checkpoint).
 */
async function walAppend(record: object): Promise<void> {
  // Chain-await pour garantir l ordre
  walAppendPromise = walAppendPromise.then(async () => {
    const line = JSON.stringify(record) + "\n";
    await Deno.writeTextFile(VAULT_WAL, line, { append: true });
  });
  return walAppendPromise;
}

export async function vaultSet(
  alias: string,
  real: string,
  mission: string,
): Promise<void> {
  const entry: VaultEntry = { alias, real, mission, ts: Date.now() };
  ramVault.set(alias, entry);
  await walAppend({ op: "set", ...entry });
}

export function vaultGet(alias: string): VaultEntry | undefined {
  return ramVault.get(alias);
}

export function vaultResolve(text: string): string {
  // Démasque tous les VAULT_* présents dans `text`
  let out = text;
  for (const [alias, entry] of ramVault) {
    if (out.includes(alias)) {
      out = out.replaceAll(alias, entry.real);
    }
  }
  return out;
}

export async function vaultDelete(alias: string): Promise<void> {
  if (ramVault.delete(alias)) {
    await walAppend({ op: "del", alias, ts: Date.now() });
  }
}

export function vaultSize(): number {
  return ramVault.size;
}

/** Reconstitue le vault en RAM depuis checkpoint + WAL. */
async function loadVault(): Promise<void> {
  ramVault.clear();

  // 1. Replay checkpoint
  try {
    const raw = await Deno.readTextFile(VAULT_CKP);
    const data = JSON.parse(raw) as VaultEntry[];
    for (const e of data) ramVault.set(e.alias, e);
    console.log(`🧬 [Persistence] Vault checkpoint chargé : ${data.length} entrées.`);
  } catch (_e) {
    // Pas de checkpoint, on part du WAL pur
  }

  // 2. Replay WAL (postérieur au checkpoint)
  try {
    const raw = await Deno.readTextFile(VAULT_WAL);
    let count = 0;
    for (const line of raw.split("\n")) {
      if (!line.trim()) continue;
      try {
        const rec = JSON.parse(line);
        if (rec.op === "set") {
          ramVault.set(rec.alias, { alias: rec.alias, real: rec.real, mission: rec.mission, ts: rec.ts });
          count++;
        } else if (rec.op === "del") {
          ramVault.delete(rec.alias);
        }
      } catch (_) {
        // Ligne corrompue, on saute
      }
    }
    console.log(`🧬 [Persistence] Vault WAL replay : ${count} mutations appliquées.`);
  } catch (_e) {
    // Pas de WAL → premier démarrage
  }

  console.log(`🧬 [Persistence] Vault prêt : ${ramVault.size} alias en RAM.`);
}

/** Compacte WAL → checkpoint. Tronque ensuite le WAL. */
export async function vaultCheckpoint(): Promise<void> {
  const snapshot = Array.from(ramVault.values());
  const tmp = VAULT_CKP + ".tmp";
  await Deno.writeTextFile(tmp, JSON.stringify(snapshot, null, 0));
  await Deno.rename(tmp, VAULT_CKP);
  // Truncate WAL
  await Deno.writeTextFile(VAULT_WAL, "");
  console.log(`💾 [Persistence] Vault checkpoint : ${snapshot.length} entrées, WAL tronqué.`);
}

// ──────────────────────────────────────────────────────────────────────
// 2. StateStore — OPSEC level + human_lock + meta
// ──────────────────────────────────────────────────────────────────────
type SystemState = {
  opsec_level: "CTF" | "STANDARD" | "PARANOID";
  human_locked: boolean;
  last_change_ts: number;
  last_change_by: string;
  last_reason: string;
  // extensible
  meta?: Record<string, unknown>;
};

let ramState: SystemState = {
  opsec_level: "PARANOID",
  human_locked: false,
  last_change_ts: 0,
  last_change_by: "default",
  last_reason: "boot defaults",
};

export function getState(): SystemState {
  return { ...ramState };
}

export async function setState(patch: Partial<SystemState>): Promise<SystemState> {
  ramState = { ...ramState, ...patch, last_change_ts: Date.now() };
  const tmp = STATE_FILE + ".tmp";
  await Deno.writeTextFile(tmp, JSON.stringify(ramState, null, 2));
  await Deno.rename(tmp, STATE_FILE);
  console.log(`💾 [Persistence] State persisté : level=${ramState.opsec_level} locked=${ramState.human_locked}`);
  return { ...ramState };
}

async function loadState(): Promise<void> {
  try {
    const raw = await Deno.readTextFile(STATE_FILE);
    const parsed = JSON.parse(raw) as SystemState;
    ramState = parsed;
    console.log(`🧬 [Persistence] State restauré : level=${parsed.opsec_level} locked=${parsed.human_locked}`);
  } catch (_e) {
    console.log(`🧬 [Persistence] Aucun state.json — démarrage avec defaults PARANOID.`);
    // Persiste les defaults pour qu'un crash futur retrouve cet état
    await setState({});
  }
}

// ──────────────────────────────────────────────────────────────────────
// 3. BrainSnapshot — vector store + métriques (frustration, élégance)
// ──────────────────────────────────────────────────────────────────────
type BrainSnapshot = {
  ts: number;
  vector_store: unknown;     // ramVectorStore (rempli par brain.ts via setBrainSource)
  metrics?: Record<string, unknown>;
};

let brainSource: () => BrainSnapshot | null = () => null;

/** Le module brain.ts enregistre ici son générateur de snapshot. */
export function setBrainSource(fn: () => BrainSnapshot | null) {
  brainSource = fn;
}

export async function brainSnapshot(): Promise<string | null> {
  const data = brainSource();
  if (!data) return null;
  const ts = Date.now();
  const fname = join(SNAPSHOT_DIR, `brain_${ts}.json`);
  const tmp = fname + ".tmp";
  await Deno.writeTextFile(tmp, JSON.stringify(data));
  await Deno.rename(tmp, fname);
  console.log(`💾 [Persistence] Brain snapshot écrit : ${fname}`);
  // Rotation : on garde les 10 derniers
  await rotateBrainSnapshots(10);
  return fname;
}

async function rotateBrainSnapshots(keep: number): Promise<void> {
  try {
    const files: { name: string; ts: number }[] = [];
    for await (const e of Deno.readDir(SNAPSHOT_DIR)) {
      if (e.isFile && e.name.startsWith("brain_") && e.name.endsWith(".json")) {
        const m = e.name.match(/brain_(\d+)\.json/);
        if (m) files.push({ name: e.name, ts: parseInt(m[1], 10) });
      }
    }
    files.sort((a, b) => b.ts - a.ts);
    for (const f of files.slice(keep)) {
      await Deno.remove(join(SNAPSHOT_DIR, f.name));
    }
  } catch (_e) {
    // best effort
  }
}

/** Restore le snapshot le plus récent. */
export async function loadLatestBrainSnapshot(): Promise<BrainSnapshot | null> {
  try {
    const files: { name: string; ts: number }[] = [];
    for await (const e of Deno.readDir(SNAPSHOT_DIR)) {
      if (e.isFile && e.name.startsWith("brain_") && e.name.endsWith(".json")) {
        const m = e.name.match(/brain_(\d+)\.json/);
        if (m) files.push({ name: e.name, ts: parseInt(m[1], 10) });
      }
    }
    if (!files.length) return null;
    files.sort((a, b) => b.ts - a.ts);
    const raw = await Deno.readTextFile(join(SNAPSHOT_DIR, files[0].name));
    const data = JSON.parse(raw) as BrainSnapshot;
    console.log(`🧬 [Persistence] Brain snapshot restauré : ${files[0].name} (ts=${data.ts})`);
    return data;
  } catch (_e) {
    return null;
  }
}

// ──────────────────────────────────────────────────────────────────────
// Bootstrap
// ──────────────────────────────────────────────────────────────────────
let initialized = false;
let timers: number[] = [];

export async function initPersistence(): Promise<void> {
  if (initialized) return;
  initialized = true;
  await ensureDirs();
  await loadState();
  await loadVault();

  // Timer brain snapshot
  const t1 = setInterval(() => {
    brainSnapshot().catch((e) => console.error(`[Persistence] brainSnapshot error : ${e}`));
  }, BRAIN_INTERVAL);
  timers.push(t1);

  // Timer vault checkpoint
  const t2 = setInterval(() => {
    vaultCheckpoint().catch((e) => console.error(`[Persistence] vaultCheckpoint error : ${e}`));
  }, VAULT_CKP_INTERVAL);
  timers.push(t2);

  console.log(`🧬 [Persistence] Initialisé. dir=${PERSIST_DIR} brain_interval=${BRAIN_INTERVAL}ms ckp=${VAULT_CKP_INTERVAL}ms`);
}

export async function shutdownPersistence(): Promise<void> {
  for (const t of timers) clearInterval(t);
  timers = [];
  // Flush final
  try {
    await vaultCheckpoint();
    await brainSnapshot();
  } catch (e) {
    console.error(`[Persistence] shutdown flush error : ${e}`);
  }
  console.log(`💾 [Persistence] Shutdown propre.`);
}

export const PERSIST_PATHS = {
  dir: PERSIST_DIR,
  vault_wal: VAULT_WAL,
  vault_ckp: VAULT_CKP,
  state: STATE_FILE,
  snapshots: SNAPSHOT_DIR,
};
