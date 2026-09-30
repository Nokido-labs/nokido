import { bus, BloodCell } from "../core/nervous_system.ts";
import { DB } from "https://deno.land/x/sqlite/mod.ts";
import { join } from "https://deno.land/std/path/mod.ts";

/**
 * Le Rein : Organe de monitoring et de filtrage.
 * Il assure que chaque événement est loggé et traçable via SQLite.
 */

// Chemin vers la base de données (dans le dossier data du projet)
const dbPath = join(Deno.cwd(), "..", "data", "nervous_system.db");
const db = new DB(dbPath);

// Initialisation de la table
db.execute(`
  CREATE TABLE IF NOT EXISTS jobs (
    jobId TEXT PRIMARY KEY,
    traceId TEXT,
    organName TEXT,
    payload TEXT,
    status TEXT,
    result TEXT,
    error TEXT,
    timestamp INTEGER
  )
`);

bus.subscribe("system_monitor", (cell: BloodCell) => {
  // 1. Archivage SQLite
  try {
    db.query(`
      INSERT OR REPLACE INTO jobs (jobId, traceId, organName, payload, status, result, error, timestamp)
      VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    `, [
      cell.jobId,
      cell.traceId,
      cell.organName,
      JSON.stringify(cell.payload || {}),
      cell.status,
      JSON.stringify(cell.result || {}),
      cell.error || null,
      cell.timestamp
    ]);
  } catch (err) {
    console.error(`[Rein] ❌ Erreur écriture SQLite : ${err instanceof Error ? err.message : String(err)}`);
  }

  // 2. Logging système
  const statusIcon = cell.status === "completed" ? "✅" : (cell.status === "failed" ? "❌" : "⏳");
  console.log(`[Rein] ${statusIcon} Job:${cell.jobId} | Origin:${cell.traceId} | Status:${cell.status}`);
  
  if (cell.error) {
    console.error(`[Rein] ⚠️ Erreur détectée pour Job:${cell.jobId} : ${cell.error}`);
  }
});

/**
 * Expose une fonction de consultation
 */
export function getJobStatus(jobId: string): BloodCell | undefined {
  const rows = db.query("SELECT * FROM jobs WHERE jobId = ?", [jobId]);
  if (rows.length === 0) return undefined;
  
  const [jId, tId, oName, pLoad, stat, res, err, ts] = rows[0] as any[];
  return {
    jobId: jId,
    traceId: tId,
    organName: oName,
    payload: JSON.parse(pLoad),
    status: stat as any,
    result: JSON.parse(res),
    error: err,
    timestamp: ts
  };
}
