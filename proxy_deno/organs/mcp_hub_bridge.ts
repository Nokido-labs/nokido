import { bus, BloodCell } from "../core/nervous_system.ts";

/**
 * Organe Pont : Relaye les événements du Système Nerveux vers le Hub Nokido (Python).
 * Permet l'affichage dans le dashboard live.
 */

const HUB_URL = "http://127.0.0.1:7400/api/events/publish";
const ADMIN_TOKEN = Deno.env.get("ADMIN_TOKEN") || Deno.env.get("LAFORGE_ADMIN_TOKEN") || "";

bus.subscribe("system_monitor", async (cell: BloodCell) => {
  try {
    const response = await fetch(HUB_URL, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "Authorization": `Bearer ${ADMIN_TOKEN}`
      },
      body: JSON.stringify({
        topic: `system.deno.${cell.organName}`,
        kind: cell.status === "failed" ? "error" : (cell.status === "completed" ? "success" : "info"),
        agent: "DENO_PROXY",
        data: {
          jobId: cell.jobId,
          status: cell.status,
          organ: cell.organName,
          error: cell.error,
          result_preview: cell.result ? JSON.stringify(cell.result).slice(0, 100) : null
        },
        corr_id: cell.jobId,
        parent_id: cell.traceId
      })
    });

    if (!response.ok) {
      const text = await response.text();
      console.error(`[Bridge] ❌ Échec relais Hub : ${response.status} ${text}`);
    }
  } catch (err) {
    console.error(`[Bridge] ❌ Erreur connexion Hub : ${err instanceof Error ? err.message : String(err)}`);
  }
});

console.log("[Bridge] 🌉 Pont Système Nerveux -> Hub Nokido actif.");
