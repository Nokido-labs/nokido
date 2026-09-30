/**
 * code_critic.ts — Dual-Model Peer Review pour Tool Smithing.
 *
 * Phase G.2 : auditGeneratedTool() reçoit code TS/Python généré par
 * draft LLM (Gemini Flash), retourne verdict APPROVED|REVISIONS|REJECTED.
 *
 * Critères :
 *   1. OPSEC — pas de secrets en dur, pas IPs hardcoded, pas eval/exec
 *   2. ARCHITECTURE — typage strict, schema JSON valide
 *   3. DISJONCTEUR — try/catch + timeouts présents
 *   4. ANTI-MCP-BLINDNESS — input_schema bien formé
 *
 * Délègue LLM call à Python forge_llm_router via subprocess
 * (provider: claude_sonnet pour rigueur logique).
 */

export interface AuditResult {
  approved: boolean;
  score: number;            // 0-100
  critique: string;
  revisions?: string;       // code patché si petits ajustements
  blockers: string[];       // raisons rejet
  warnings: string[];       // non-bloquants
  schema_valid: boolean;    // input_schema parse OK ?
  provider_used: string;    // claude_sonnet | claude_opus | etc.
}

export interface ToolSpec {
  name: string;
  description: string;
  language: "typescript" | "python";
  context: string;
  input_schema?: object;
}

const ROOT = Deno.cwd().endsWith("proxy_deno")
  ? Deno.cwd().slice(0, -10)
  : Deno.cwd();
const PYTHON = Deno.env.get("LAFORGE_PYTHON") ??
  "%USERPROFILE%/miniforge3/python.exe";

// ── Pre-validation locale (sans appel LLM) ────────────────────────────
function localOpsecScan(code: string): { blockers: string[]; warnings: string[] } {
  const blockers: string[] = [];
  const warnings: string[] = [];

  // Hardcoded secrets (token/key/password literal)
  if (/(["'])(?:sk-|ghp_|xoxb-|api[_-]?key)\s*[:=]\s*["'][^"']{20,}/i.test(code)) {
    blockers.push("hardcoded API token/key detected");
  }
  // IP literal hardcoded (sauf localhost)
  const ipMatches = code.match(/\b(?!127\.0\.0\.1|0\.0\.0\.0|localhost)(?:\d{1,3}\.){3}\d{1,3}\b/g);
  if (ipMatches && ipMatches.length > 0) {
    blockers.push(`hardcoded IP(s): ${ipMatches.slice(0, 3).join(",")}`);
  }
  // eval / exec / Function constructor
  if (/\b(?:eval|exec|new\s+Function)\s*\(/i.test(code)) {
    blockers.push("eval/exec/Function constructor detected — code injection risk");
  }
  // Shell injection patterns
  if (/(?:os\.system|subprocess\.\w+\(.+shell\s*=\s*True)/.test(code)) {
    blockers.push("shell=True or os.system — command injection risk");
  }
  // Pas de try/catch en TS
  if (code.includes("await fetch(") && !code.includes("try")) {
    warnings.push("await fetch sans try/catch — circuit breaker manquant");
  }
  // Pas de timeout sur fetch
  if (code.includes("await fetch(") && !code.includes("AbortSignal.timeout")) {
    warnings.push("fetch sans AbortSignal.timeout — risque hang");
  }
  return { blockers, warnings };
}

function validateInputSchema(schema: unknown): boolean {
  if (!schema || typeof schema !== "object") return false;
  const s = schema as Record<string, unknown>;
  if (s.type !== "object") return false;
  if (typeof s.properties !== "object") return false;
  // Check required field exists & is array
  if (s.required !== undefined && !Array.isArray(s.required)) return false;
  return true;
}

// ── LLM critic call (via Python forge_llm_router) ─────────────────────
async function callExpertLLM(prompt: string, provider = "claude_sonnet"): Promise<string> {
  const escapedPrompt = JSON.stringify(prompt);
  const code = `
import sys, json
sys.path.insert(0, r"${ROOT.replace(/\\/g, "/")}/app")
from forge_llm_router import LLMRouter
router = LLMRouter()
import asyncio
async def go():
    # LLMRouter.call(prompt, use_case, ...) is synchronous and returns a dict
    # {ok,text,provider,...}. The router selects the provider itself.
    r = router.call(${escapedPrompt}, system="You are a senior code auditor. Reply ONLY with valid JSON.")
    if isinstance(r, dict):
        return r.get("text", "") or ""
    return r.text if hasattr(r, 'text') else str(r)
print(asyncio.run(go()))
`;
  try {
    const cmd = new Deno.Command(PYTHON, {
      args: ["-c", code],
      stdout: "piped", stderr: "piped",
      env: { PYTHONIOENCODING: "utf-8", PYTHONUTF8: "1" },
    });
    const { stdout } = await cmd.output();
    return new TextDecoder().decode(stdout).trim();
  } catch (e) {
    throw new Error(`LLM critic call failed: ${e}`);
  }
}

// ── Public API ────────────────────────────────────────────────────────
export async function auditGeneratedTool(
  toolCode: string,
  spec: ToolSpec,
  expertProvider = "claude_sonnet"
): Promise<AuditResult> {
  // Phase 1 : local pre-scan (instantané, économe)
  const local = localOpsecScan(toolCode);
  const schemaOK = spec.input_schema ? validateInputSchema(spec.input_schema) : false;
  if (!schemaOK) local.blockers.push("input_schema missing or invalid (anti-MCP-blindness)");

  // Si blockers locaux → reject sans appel LLM (économie tokens)
  if (local.blockers.length > 0) {
    return {
      approved: false,
      score: 0,
      critique: "REJECTED par scan local OPSEC pré-LLM",
      blockers: local.blockers,
      warnings: local.warnings,
      schema_valid: schemaOK,
      provider_used: "local_scan",
    };
  }

  // Phase 2 : audit LLM expert
  const auditPrompt = `TU ES L AUDITEUR DE SÉCURITÉ DE NOKIDO.
Analyse ce code généré par une IA subalterne (forge tool).

CRITÈRES :
1. OPSEC — secrets/IPs/credentials hardcoded ? injections ?
2. ARCHITECTURE — typage strict ? structure cohérente ?
3. DISJONCTEUR — try/catch + AbortSignal.timeout sur appels réseau ?
4. ROBUSTESSE — edge cases (null, empty, malformed input) gérés ?
5. PERFORMANCE — Python 3.14 asyncio.taskgroup utilisé si pertinent ?

CONTEXTE TOOL :
- nom : ${spec.name}
- description : ${spec.description}
- langage : ${spec.language}
- contexte : ${spec.context}

CODE :
\`\`\`${spec.language}
${toolCode}
\`\`\`

Réponds UNIQUEMENT JSON valide (pas de markdown) :
{"approved": bool, "score": 0-100, "critique": "résumé court",
 "blockers": ["liste raisons rejet"], "warnings": ["non-bloquants"],
 "revisions": "code patché optionnel"}`;

  let llmResponse: string;
  try {
    llmResponse = await callExpertLLM(auditPrompt, expertProvider);
  } catch (e) {
    return {
      approved: false,
      score: 0,
      critique: `LLM critic failed: ${e}`,
      blockers: ["llm_audit_unavailable"],
      warnings: local.warnings,
      schema_valid: schemaOK,
      provider_used: expertProvider,
    };
  }

  // Parse LLM JSON response (tolérant aux backticks/markdown)
  const jsonMatch = llmResponse.match(/\{[\s\S]*\}/);
  let parsed: Partial<AuditResult> = {};
  try {
    parsed = JSON.parse(jsonMatch ? jsonMatch[0] : llmResponse);
  } catch (_e) {
    parsed = {
      approved: false,
      score: 0,
      critique: `LLM response not parseable: ${llmResponse.slice(0, 200)}`,
      blockers: ["llm_response_invalid"],
    };
  }

  // Merge local + LLM verdicts
  return {
    approved: Boolean(parsed.approved) && local.blockers.length === 0,
    score: typeof parsed.score === "number" ? parsed.score : 0,
    critique: parsed.critique || "no critique returned",
    revisions: parsed.revisions,
    blockers: [...local.blockers, ...(parsed.blockers ?? [])],
    warnings: [...local.warnings, ...(parsed.warnings ?? [])],
    schema_valid: schemaOK,
    provider_used: expertProvider,
  };
}
