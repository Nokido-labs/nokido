# Roadmap — Singularité Technique Nokido

**Version** : 2026-05-02 post-Kill-Switch
**Statut** : Phase G (au-delà de Phase F PEP 684)

Cycle complet : **Savoir → Savoir-Faire → Faire-Savoir → Évoluer**.
Nokido passe d automate à entité apprenante qui sculpte ses propres
capacités.

---

## 🔁 Cycle "Savoir / Savoir-Faire / Faire-Savoir"

| Étape | Module Nokido actuel | Évolution cible |
|---|---|---|
| **Savoir** (Observation) | `forge_anatomy_state` 19 organes + `forge_novelty_search` (Stanley/Lehman) | Détecte situation inédite → trigger branche évolution |
| **Savoir-Faire** (Exécution) | `forge_dispatchers` (23 dispatchers) + `forge_trajectory` JSON-RPC | Si tool manque → branch Tool Smithing |
| **Faire-Savoir** (Documentation) | `forge_self_correction.anchor_solution` + `lessons_learned.md` | Auto-générer Markdown spec de chaque tool forgé → indexé RAG FAISS pour rappel session future |
| **Évoluer** (Auto-amélioration) | (manquant) | Pipeline Phase G ci-dessous |

---

## 🛠️ Phase G — Tool Smithing JIT (Just-In-Time tool generation)

### G.1 — Détection lacune

```python
# Dans forge_dispatchers, hook quand dispatch retourne tool_not_found
async def _on_missing_tool(intent: dict) -> dict:
    # 1. Query forge_novelty_search : situation déjà rencontrée ?
    novelty = await observe_intent(intent)
    if novelty.confidence > 0.7:
        # Inédit → propose forge tool
        return {"action": "trigger_tool_smithing", "spec": derive_spec(intent)}
    return {"action": "fallback", "tool": novelty.closest_match}
```

### G.2 — Génération via tree-sitter

Utiliser `tree-sitter` (Phase 3) pour générer un micro-module :

```typescript
// proxy_deno/utils/tool_smith.ts
import Parser from "npm:tree-sitter";
import Python from "npm:tree-sitter-python";
import TypeScript from "npm:tree-sitter-typescript";

export async function smithTool(spec: ToolSpec): Promise<string> {
    // 1. Generate skeleton (TS preferred, Python fallback)
    const code = await generateFromSpec(spec, "typescript");
    // 2. Parse for syntax validation
    const parser = new Parser();
    parser.setLanguage(TypeScript);
    const tree = parser.parse(code);
    if (tree.rootNode.hasError()) throw new Error("syntax invalid");
    return code;
}
```

### G.3 — Sandbox test

Avant injection au catalogue, run dans Deno isolated worker :

```typescript
const worker = new Worker(import.meta.resolve("./tool_sandbox.ts"), {
    type: "module",
    deno: { permissions: { net: false, read: false, write: false, run: false } }
});
worker.postMessage({ code, testCases: spec.acceptance });
```

### G.4 — Injection catalogue + validation MCP critique

```typescript
// Dans hub_mcp/main.ts
function injectForgedTool(name: string, schema: object, handler: Function) {
    // CRITIQUE : avant cloud call avec ce nouveau tool, vérifier schema dans payload
    TOOL_CATALOG.push({ name, description: `[FORGED] ${schema.description}`,
                        inputSchema: schema, _forged: true });
    HANDLERS.set(name, handler);
    // Audit RAG (Faire-Savoir)
    anchorSolution({
        problem: `Tool manquant : ${name}`,
        solution: `Forgé JIT depuis spec ${JSON.stringify(spec)}`,
        domain: "tool_smithing"
    });
}
```

**Règle d or** : `preFlightCloudCheck()` doit valider que tool forgé est
présent dans payload tools[] envoyé au cloud LLM. Sinon LLM ne saura
pas l utiliser → cycle cassé.

---

## 🔄 Phase H — Self-Refinement multi-LLM

Pipeline 3 phases pour chaque tool forgé :

```
[Phase A] Esquisse rapide
  → agt_gemini_flash (1M ctx, low cost)
  → produit code initial brut

[Phase B] Audit expert
  → agt_claude_sonnet ou agt_deepseek_v3
  → review : sécu / perf / no-GIL Phase 6 PEP 684 / fuites mémoire
  → retourne diff suggéré

[Phase C] Validation
  → run sandbox tests acceptance (G.3)
  → si PASS : injection catalogue (G.4)
  → si FAIL : retour Phase A avec feedback critique
```

**Implementation** : nouveau dispatcher `_smith_tool` dans `forge_dispatchers` :

```python
async def _smith_tool(params):
    spec = params["spec"]
    # Phase A
    sketch = await llm_call("gemini_flash", build_smith_prompt_a(spec))
    # Phase B (parallèle 2 reviewers)
    reviews = await asyncio.gather(
        llm_call("claude_sonnet", build_review_prompt(sketch, "security")),
        llm_call("deepseek_v3", build_review_prompt(sketch, "performance"))
    )
    refined = merge_review_diffs(sketch, reviews)
    # Phase C
    test_result = await sandbox_test(refined, spec.acceptance)
    if test_result.passed:
        inject_to_catalog(spec.name, refined)
        return {"ok": True, "tool": spec.name}
    return {"ok": False, "iterate": True, "feedback": test_result.failures}
```

---

## 📊 Tableau de bord Évolution Autonome

| Couche | Module existant | Rôle évolution |
|---|---|---|
| **Analyse besoin** | `forge_novelty_search` + `forge_motivation` (cortisol) | Décide création branche tool |
| **Architecture** | `tree-sitter` (npm:@dprint) | Structure code généré |
| **Génération** | `forge_llm_router.call_cascade` (multi-LLM) | Sketch + review |
| **Sandbox test** | Deno Worker isolé | Validation pré-injection |
| **Validation MCP** | `preFlightCloudCheck()` (Phase B.2) | Garantit tool dans payload cloud |
| **Mémoire** | `forge_rag_engine` FAISS + `forge_hebbian_linker` | Enregistre tool pour Savoir-faire futur |
| **Audit** | `anchor_solution(domain="tool_smithing")` | Trace dans `lessons_learned.md` |
| **Visualisation** | TUI v3 (Phase I) — arborescence vivante | Voir croissance intellectuelle live |

---

## 🌳 Phase I — TUI v3 visualisation arborescence

Étendre `tools/nokido_tui.py` pour ajouter pane "EVOLUTION_TREE" :

```
╭─ EVOLUTION TREE ──────────────────────────╮
│ root                                       │
│ ├─ 🛠 binary_disasm_v1 (forged 2026-05-02)│
│ │   ├─ 🔧 elf_parser (forged ↑)           │
│ │   └─ ✅ pe_parser (forged ↑)            │
│ ├─ 🛠 log_xml_parser (forged 2026-05-02)  │
│ └─ 🌱 [forging] iso_extractor...          │
╰────────────────────────────────────────────╯
```

Source data : SQL query sur `rag_chunks` WHERE domain='tool_smithing'
+ relations parent/child via Hebbian links.

Refresh live via SSE depuis proxy_deno :8000 `/api/events?channel=tool_forge`.

---

---

## 🐳 Phase G.5 — Docker ephemeral test container

Ajout au pipeline pour vrai test fonctionnel (au-delà sandbox Deno
Worker — qui ne peut pas tester un script Python par exemple).

### Architecture

```
forge_tool() draft + audit OK
   ↓
spawnEphemeralContainer(toolCode, spec.acceptance)
   ├─ docker run --rm --network none --memory 256m --cpus 0.5
   │     --read-only --tmpfs /tmp \
   │     -v /sandbox/tool.ts:/app/tool.ts:ro \
   │     deno:alpine deno test --allow-read /app/tool.ts
   ↓
verdict (passed/failed/timeout 30s)
```

### Image base

| Lang | Image | Taille |
|---|---|---|
| TypeScript/Deno | `denoland/deno:alpine` | ~50 MB |
| Python 3.14 | `python:3.14-slim` | ~120 MB |

### Tests générés automatiquement

LLM critic (Phase B) doit générer aussi 3-5 cas de test :
- Happy path (input valide)
- Edge cases (null, empty, max size)
- Adversarial (malformed input → expect graceful error)

### Résultats container

```typescript
interface SandboxResult {
  passed: boolean;
  test_cases_run: number;
  test_cases_failed: number;
  stdout: string;       // tronqué 5 KB
  stderr: string;       // tronqué 5 KB
  duration_ms: number;
  exit_code: number;
  resource_usage: { memory_peak_mb: number; cpu_seconds: number };
}
```

### Sécurité container

Garde-fous obligatoires :
- `--network none` — zéro accès réseau (test pur fonctionnel)
- `--read-only` + `--tmpfs /tmp` — pas d écriture filesystem hôte
- `--memory 256m --cpus 0.5` — limites strictes
- `--security-opt no-new-privileges`
- Container détruit (`--rm`) après run
- Timeout 30s max
- User non-root (`USER 1000`)

### Implémentation TS

```typescript
// proxy_deno/core/sandbox_docker.ts
export async function dockerSandboxTest(
  code: string,
  language: "typescript" | "python",
  testCases: TestCase[],
  timeoutSec = 30
): Promise<SandboxResult> {
  const tmpDir = await Deno.makeTempDir();
  const ext = language === "typescript" ? "ts" : "py";
  await Deno.writeTextFile(`${tmpDir}/tool.${ext}`, code);
  await Deno.writeTextFile(`${tmpDir}/test.${ext}`, generateTestRunner(testCases, language));

  const image = language === "typescript"
    ? "denoland/deno:alpine"
    : "python:3.14-slim";
  const cmd = language === "typescript"
    ? ["deno", "test", "--allow-read", "/app/test.ts"]
    : ["python", "/app/test.py"];

  const docker = new Deno.Command("docker", {
    args: ["run", "--rm",
      "--network", "none",
      "--memory", "256m",
      "--cpus", "0.5",
      "--read-only",
      "--tmpfs", "/tmp",
      "--security-opt", "no-new-privileges",
      "--user", "1000",
      "-v", `${tmpDir}:/app:ro`,
      image,
      ...cmd,
    ],
    stdout: "piped", stderr: "piped",
    signal: AbortSignal.timeout(timeoutSec * 1000),
  });

  const { code: exit, stdout, stderr } = await docker.output();
  await Deno.remove(tmpDir, { recursive: true });
  return parseTestOutput(exit, stdout, stderr);
}
```

### Intégration dans tool_smith

```typescript
// Après audit approved :
if (options.sandboxTest && audit.approved) {
  const sandbox = await dockerSandboxTest(
    draftCode, spec.language, spec.test_cases ?? [], 30
  );
  if (!sandbox.passed) {
    // Re-audit avec feedback test failures
    spec.context += `\n\nSANDBOX FAILED: ${sandbox.stderr.slice(0, 500)}`;
    continue; // next iteration
  }
}
```

### Quand activer

- Phase G MVP (livré aujourd hui) : audit local + LLM only, **pas Docker**
- Phase G.5 (cette section) : à activer après Phase B.4 stable
- Trigger : >5 tools forgés sans Docker → bench false-positive rate audit
  LLM seul. Si >20% bugs prod-injection → ajouter Docker layer.

---

## 🚦 Trigger Phase G/H/I

**Pas avant** :
1. Phase B.3 (UI/SSE) finie ✅ Kill Switch livré
2. Phase B.4 (Hono refactor) — modulaire pour faciliter inject
3. Phase C (daemons → Deno) — runtime stable
4. forge_skill_policy pour audit tool forgé avant inject

**Trigger** :
- Stack stable 11 services 7+ jours sans crash
- Au moins 1 cas réel de "tool manquant" rencontré + documenté
- Bench multi-LLM dispatch operational (3 LLMs simultanés)

---

## 🛡️ OPSEC + Centaure pour Tool Smithing

⚠ Code généré par LLM cloud = risque injection. Garde-fous :

1. **Sandbox isolation** Deno Worker (no net/read/write/run)
2. **Validation tree-sitter** : reject si syntax errors
3. **forge_skill_policy.audit_plugin** étendu pour scan code généré
4. **Human approval** : si OPSEC=PARANOID + lock, tool forgé en file
   d attente "pending_human_approval" → notification dashboard
5. **Rollback** : chaque tool injecté est versionné, revert possible
6. **Kill Switch sémantique** (livré aujourd hui) coupe outbound cloud
   si tool comportement erratique détecté

---

## 📈 Métriques succès

- **Vélocité tool smithing** : nb tools forgés/semaine (cible : 3-5)
- **Taux validation Phase C** : % tools qui passent sandbox (cible : >70%)
- **Réutilisation RAG** : % tools forgés ré-utilisés > 1 fois (cible : >50%)
- **Sécurité** : 0 tool forgé déclenche `forge_skill_policy.BLOCK`
- **Latence smithing complet** : <60s (Phase A 10s + B 30s + C 20s)

---

## 🎯 Première itération concrète

**Use case test** : "parser de log Stormshield IPS proprietaire (format X)".

Chaîne :
1. user : `@nokido parse ce log` (format inconnu)
2. `forge_novelty_search` détecte format inédit (>0.8 novelty)
3. Trigger Phase G : Gemini Flash sketch parser TS
4. Phase H : Claude review (sécu + edge cases)
5. Phase C sandbox : test sur 10 lignes échantillon
6. Si PASS : inject `parse_stormshield_log` dans TOOL_CATALOG Deno
7. Anchor RAG : "Tool parse_stormshield_log forgé 2026-05-XX"
8. user re-demande → tool dispo, parse réussit
9. TUI EVOLUTION_TREE affiche nouveau noeud

**Acceptance globale** : 1 cycle Singularité complet exécuté de bout en bout.
