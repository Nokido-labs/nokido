# Connecteur Workflow Claude ↔ Nokido

Date : 2026-06-11 · **Statut : LE CONNECTEUR EXISTE DÉJÀ — rien à construire (anti-dup).**

## Deux orchestrateurs, complémentaires (ne pas confondre)

| | Workflow Claude (outil `Workflow`) | Orchestration SOUVERAINE Nokido |
|---|---|---|
| Quoi | fan-out d'agents Claude, déterministe (pipeline/parallel/loop), verify adversarial | swarm hub-native, local, zéro cloud |
| Modules | côté client (Claude Code) | `forge_spawn_swarm` (Map-Reduce: validator→DAG→workers→commit atomique), `orchestrate`, **`forge_durable_workflow`** (event-sourced, replay-on-restart) |
| Pilote | le client (l'agent principal) | le hub :8766 |
| Survit au restart | non (éphémère) | **oui** (durable_workflow replay) |

## Le connecteur = la couche MCP (déjà là, rien à coder)

Un agent de Workflow Claude PEUT appeler n'importe quel outil Nokido via ToolSearch
(« Workflow agents can reach all session-connected MCP tools ») :
- `mcp__laforge-sovereign-hub__rag` — RAG 1024D(code) / 4096D(world_model)
- `read` / `read_function_body` — lecture chirurgicale fenêtrée
- `run` (shell/python/**run_job** déporté) — exécution souveraine
- **`forge_spawn_swarm` / `orchestrate`** — DÉLÉGUER à la swarm souveraine

→ un agent de workflow parle à Nokido **sans nouveau code**. Le « connecteur » est
l'adaptateur MCP existant du hub.

## Quand utiliser quoi

- Tâche qui a besoin du RAG / code vectorisé / `run` souverain → l'agent de workflow
  charge + appelle les outils Nokido (ne PAS refaire en natif ce que Nokido sait).
- Orchestration qui doit **survivre au restart** (replay) → `forge_durable_workflow`
  (souverain), PAS le Workflow Claude (éphémère).
- Fan-out d'analyse/audit code pur → Workflow Claude (agents Read/Grep) ou `forge_spawn_swarm`.

## Pattern dans un script Workflow

```js
agent(
  'Cherche via mcp__laforge-sovereign-hub__rag dans le RAG Nokido, lis avec '
  + 'read_function_body, exécute via run. Pour déléguer une sous-tâche lourde à '
  + 'la swarm souveraine: forge_spawn_swarm.',
  { agentType: 'Explore' }
)
```

Le seul « build » nécessaire = ce doc + le réflexe de pointer les agents vers les outils
Nokido. Voir memory `roadmap_acp_intelligent_terminal` (exposer Nokido comme backend
agent via ACP, dual de MCP) pour le sens inverse (Nokido piloté par un host externe).
