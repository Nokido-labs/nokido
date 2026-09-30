# Fiche de sortie — Veille V1 « Observabilité agentique / OTel GenAI » (2026-09-23)

Contrat : PATTERN → DÉJÀ DANS NOKIDO → GAP → EXPÉRIENCE MINIMALE → NR → DÉCISION. Cette fiche PROPOSE.

## 1. Patterns (`source LIKE 'watch:observabilite:%'`, spécifications complètes ingérées : 75 + 89 + 49 chunks)

| Pattern | Source primaire |
|---|---|
| Spans normés : `gen_ai.invoke_agent` (client / interne), `gen_ai.execute_tool`, appels modèle ; attribut `gen_ai.operation.name` | OTel semantic-conventions-genai : `gen-ai-agent-spans.md`, `gen-ai-spans.md` |
| Métriques normées : `gen_ai.client.operation.duration`, `gen_ai.client.token.usage` ; `gen_ai.response.finish_reasons` | `gen-ai-metrics.md` |
| UN trace_id parent → spans enfants (agent → LLM → outil → worker) : la causalité est un ARBRE, pas des journaux juxtaposés | OTel GenAI + blog 2026 |

## 2. Ce que Nokido possède DÉJÀ (`introspect`)

- `app/forge_trace_spine.py` : « contrat de provenance des traces — l'étape qui doit précéder toute centralisation » ;
  **0 import statique** (5 mentions). 0 import ≠ mort (un module peut être invoqué par chemin) : état INCONNU, à
  instruire avec son LOG.
- Transient Spine (M2M v1.4.1, canal `transient`) : `source_call_id` (tool_use_id), `content_fingerprint`, `correlation_id` = la SESSION, `provenance(session, depth, parent)`.
- Journaux séparés (switch `journaux`, 23/09) : `token_usage`, `inspector_log`, `conversation_log`.
- `sandbox/a2a.log` : journal privé avec `agent`/`request_id`/`task_id` (constat 17/09 : 0 preuve de provenance ACP/A2A).

## 3. Gaps

1. **Pas de trace_id propagé de bout en bout** : `correlation_id` = session, pas objectif/tâche ; un appel LLM, un tool-call MCP, un job et une écriture DB ne se rattachent pas à UN arbre.
2. `provenance.parent` existe dans le canal transient mais la propagation au travers de `run_job`, du hub et des workers n'est pas démontrée.
3. Journaux (`token_usage`, `inspector_log`) sans correspondance avec les noms/attributs OTel ⇒ pas d'export standard.
4. `forge_trace_spine` : aucun import statique ; s'il n'est pas non plus invoqué par chemin, contrat écrit non câblé
   (motif « garde sans émetteur ») — à ÉTABLIR, pas à supposer.

## 4. Expérience minimale proposée

Mesurer AVANT de construire : pour UNE action réelle (un `run_job` de veille), lister les identifiants présents à chaque
étape (hook PreToolUse → hub `run` → job → écriture DB → notification) et marquer où la causalité se perd.
Livrable : table étape × identifiant (présent / absent / fabriqué). Aucune dépendance OTel ajoutée à ce stade.

## 5. NR candidat

`test_trace_parent_propage_nr` : un `run_job` lancé avec un parent connu écrit ce parent dans sa fiche de job ET dans
sa notification de fin (chemin réel, `.json` du job) — échoue aujourd'hui si la propagation n'existe pas.

## 6. Décision attendue (owner)

- [ ] Instruire `forge_trace_spine` (pourquoi 0 import ? LOG ?) avant toute brique neuve.
- [ ] Autoriser la mesure §4 (lecture seule).
- [ ] Alignement des noms sur OTel GenAI : après la mesure, pas avant.
