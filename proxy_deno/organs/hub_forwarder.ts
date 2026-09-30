import { bus, BloodCell } from "../core/nervous_system.ts";

/**
 * Hub Forwarder — route default_executor cells vers hub MCP :8766.
 * Fallback pour tout tool call non géré par wasm_organ ou exegol_organ.
 */

const HUB_MCP = "http://127.0.0.1:8766/mcp";
const HUB_TOKEN = Deno.env.get("FORGE_MCP_TOKEN") || "";

bus.subscribe("default_executor", async (cell: BloodCell) => {
  const payload = cell.payload as Record<string, unknown>;
  const toolName = (payload?.tool_name as string) || (payload?.name as string) || "run";
  const args = (payload?.arguments as Record<string, unknown>) || payload || {};

  try {
    const resp = await fetch(HUB_MCP, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        ...(HUB_TOKEN ? { Authorization: `Bearer ${HUB_TOKEN}` } : {}),
      },
      body: JSON.stringify({
        method: "tools/call",
        params: { name: toolName, arguments: args },
        _deno_job_id: cell.jobId,
        _deno_trace_id: cell.traceId,
      }),
    });

    if (resp.ok) {
      const data = await resp.json();
      cell.status = "completed";
      cell.result = data;
    } else {
      const text = await resp.text();
      cell.status = "failed";
      cell.error = `Hub ${resp.status}: ${text.slice(0, 200)}`;
    }
  } catch (err: unknown) {
    cell.status = "failed";
    cell.error = `Hub unreachable: ${(err as Error).message}`;
  }

  bus.pump({ ...cell, organName: "system_monitor" });
});

console.log("[HubForwarder] 🔀 default_executor → Hub :8766 actif.");
