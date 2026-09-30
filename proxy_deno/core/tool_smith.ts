/**
 * tool_smith.ts — Phase G Forge d Outils JIT.
 *
 * Pipeline 3 phases :
 *   A. Drafting   : Gemini Flash sketch (rapide, low cost)
 *   B. Audit      : Claude Sonnet review via code_critic
 *   C. Sandbox    : (Phase G.5 future) Docker ephemeral test
 *
 * Si A+B PASS → injection catalogue Hub MCP via writeTool().
 * Sinon → retry avec feedback ou file pending_human_approval.
 */

import { auditGeneratedTool, type AuditResult, type ToolSpec } from "./code_critic.ts";

const ROOT = Deno.cwd().endsWith("proxy_deno")
  ? Deno.cwd().slice(0, -10)
  : Deno.cwd();
const PYTHON = Deno.env.get("LAFORGE_PYTHON") ??
  "%USERPROFILE%/miniforge3/python.exe";
const FORGE_DIR = `${ROOT}/nokido_persist/forged_tools`;

export interface ForgeReport {
  spec: ToolSpec;
  draft_code: string;
  audit: AuditResult;
  draft_provider: string;
  iterations: number;
  status: "approved" | "rejected" | "pending_approval" | "draft_failed";
  output_path?: string;
  ts: number;
}

// ── Phase A : Drafting via Gemini Flash ───────────────────────────────
async function draftTool(spec: ToolSpec, draftProvider = "gemini_flash"): Promise<string> {
  const prompt = `Tu es un FORGERON D OUTILS Nokido. Génère un micro-module ${spec.language}.

SPEC :
- nom : ${spec.name}
- description : ${spec.description}
- contexte : ${spec.context}
- input schema : ${JSON.stringify(spec.input_schema ?? {}, null, 2)}

CONTRAINTES :
- ${spec.language === "typescript" ? "Deno runtime, typed strict, exports default async function handler(input)" : "Python 3.14, async def handler(input: dict) -> dict"}
- try/catch obligatoire sur tous I/O
- AbortSignal.timeout(5000) pour fetch (TS) ou asyncio.timeout(5) (Python)
- Pas de secrets hardcoded, pas IPs
- Retourne dict/object résultat

Réponds UNIQUEMENT le code ${spec.language} (pas de markdown, pas de commentaires d intro).`;

  const escaped = JSON.stringify(prompt);
  const code = `
import sys, json
sys.path.insert(0, r"${ROOT.replace(/\\/g, "/")}/app")
from forge_llm_router import LLMRouter
import asyncio
async def go():
    router = LLMRouter()
    # LLMRouter.call(prompt, use_case, ...) is synchronous and returns a dict
    # {ok,text,provider,...}. The router selects the provider itself.
    r = router.call(${escaped})
    if isinstance(r, dict):
        return r.get("text", "") or ""
    return r.text if hasattr(r, 'text') else str(r)
print(asyncio.run(go()))
`;
  const cmd = new Deno.Command(PYTHON, {
    args: ["-c", code],
    stdout: "piped", stderr: "piped",
    env: { PYTHONIOENCODING: "utf-8", PYTHONUTF8: "1" },
  });
  const { stdout } = await cmd.output();
  const text = new TextDecoder().decode(stdout).trim();
  // Strip markdown fences si présents
  return text.replace(/^```(?:typescript|python|ts|py)?\n/, "").replace(/\n```$/, "");
}

// ── Phase D : Persistance + injection catalogue ───────────────────────
async function persistTool(spec: ToolSpec, code: string, audit: AuditResult): Promise<string> {
  await Deno.mkdir(FORGE_DIR, { recursive: true });
  const ext = spec.language === "typescript" ? "ts" : "py";
  const ts = Date.now();
  const fname = `${FORGE_DIR}/${spec.name}_${ts}.${ext}`;
  const meta = {
    spec, audit, ts,
    schema: "nokido.forged_tool.v1",
  };
  await Deno.writeTextFile(fname, code);
  await Deno.writeTextFile(fname.replace(/\.\w+$/, ".meta.json"),
    JSON.stringify(meta, null, 2));
  return fname;
}

async function anchorForgedTool(spec: ToolSpec, audit: AuditResult, path: string) {
  const escaped = JSON.stringify({
    problem: `Tool manquant : ${spec.name}`,
    solution: `Forgé JIT depuis spec. Audit score=${audit.score} provider=${audit.provider_used}. Path: ${path}`,
    example: `tool ${spec.name} (${spec.language}) — ${spec.description}`,
    domain: "tool_smithing",
  });
  const code = `
import sys
sys.path.insert(0, r"${ROOT.replace(/\\/g, "/")}/app")
from forge_self_correction import anchor_solution
import json
p = json.loads(${JSON.stringify(escaped)})
anchor_solution(**p)
print("OK")
`;
  try {
    const cmd = new Deno.Command(PYTHON, {
      args: ["-c", code],
      stdout: "piped", stderr: "piped",
      env: { PYTHONIOENCODING: "utf-8" },
    });
    await cmd.output();
  } catch (_e) { /* anchor best-effort */ }
}

// ── Public orchestrator ────────────────────────────────────────────────
export async function forgeTool(
  spec: ToolSpec,
  options: {
    draftProvider?: string;
    expertProvider?: string;
    maxIterations?: number;
    autoApproveScoreMin?: number;
    sandboxTest?: boolean;  // Phase G.5 future
  } = {}
): Promise<ForgeReport> {
  const draftProvider = options.draftProvider ?? "gemini_flash";
  const expertProvider = options.expertProvider ?? "claude_sonnet";
  const maxIter = options.maxIterations ?? 2;
  const minScore = options.autoApproveScoreMin ?? 75;
  const ts = Date.now();

  let draftCode = "";
  let lastAudit: AuditResult | null = null;
  let iteration = 0;

  for (iteration = 1; iteration <= maxIter; iteration++) {
    // Phase A — Drafting
    try {
      draftCode = await draftTool(spec, draftProvider);
    } catch (e) {
      return {
        spec, draft_code: "", iterations: iteration, ts,
        audit: { approved: false, score: 0, critique: `draft fail: ${e}`,
                 blockers: ["draft_failed"], warnings: [], schema_valid: false,
                 provider_used: draftProvider },
        draft_provider: draftProvider, status: "draft_failed",
      };
    }

    // Phase B — Audit
    lastAudit = await auditGeneratedTool(draftCode, spec, expertProvider);

    if (lastAudit.approved && lastAudit.score >= minScore) {
      // Phase C/D — persist + anchor (sandbox test = G.5 future)
      const outputPath = await persistTool(spec, draftCode, lastAudit);
      await anchorForgedTool(spec, lastAudit, outputPath);
      return {
        spec, draft_code: draftCode, audit: lastAudit,
        draft_provider: draftProvider, iterations: iteration,
        status: "approved", output_path: outputPath, ts,
      };
    }

    // Si REVISIONS non-vide, l audit a fourni du code patché → next iter use it
    if (lastAudit.revisions && lastAudit.revisions.length > 50) {
      draftCode = lastAudit.revisions;
      // Re-audit le revised code immédiat
      lastAudit = await auditGeneratedTool(draftCode, spec, expertProvider);
      if (lastAudit.approved && lastAudit.score >= minScore) {
        const outputPath = await persistTool(spec, draftCode, lastAudit);
        await anchorForgedTool(spec, lastAudit, outputPath);
        return {
          spec, draft_code: draftCode, audit: lastAudit,
          draft_provider: draftProvider, iterations: iteration,
          status: "approved", output_path: outputPath, ts,
        };
      }
    }
  }

  // Aucune itération approved → file pending humain
  const outputPath = lastAudit ? await persistTool(spec, draftCode, lastAudit) : undefined;
  return {
    spec, draft_code: draftCode,
    audit: lastAudit ?? { approved: false, score: 0, critique: "max_iter_reached",
                          blockers: [], warnings: [], schema_valid: false,
                          provider_used: expertProvider },
    draft_provider: draftProvider, iterations: maxIter,
    status: "pending_approval", output_path: outputPath, ts,
  };
}
