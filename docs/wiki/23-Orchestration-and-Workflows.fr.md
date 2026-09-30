---
type: guide
title: 23 — Orchestration & workflows
status: draft
resource: repo://docs/wiki/23-Orchestration-and-Workflows.fr.md
generated: {by: forge_wiki_modules@INCONNU, at: 2026-09-22T13:02:47+00:00}
empreinte: INCONNUE
---

# 23 — Orchestration & workflows

<!-- revu-le: 2026-08-30 -->
> Mise à jour : 2026-08-30

> 🌐 [English](23-Orchestration-and-Workflows.md) · **Français**

Comment Nokido exécute un travail en plusieurs étapes — ce qui existe aujourd'hui, et
l'**exécution durable**, désormais livrée sous le nom `forge_durable` (le patron
[Temporal](https://github.com/temporalio), entièrement local), avec aussi pour inspiration
[Mistral Workflows](https://docs.mistral.ai/studio-api/workflows/getting-started/overview).

---

## Ce qui existe aujourd'hui

Nokido possède déjà les *pièces* d'un moteur d'orchestration, réparties entre plusieurs modules :

| Primitive | Module | Rôle |
|---|---|---|
| **Boucle agentique (locale)** | hub `orchestrate` | Qwen2.5-Coder:7B (llama-server :8091) enchaîne les appels d'outils MCP jusqu'à `finish_reason=stop`. |
| **Planificateur GOAP** | `forge_goap_hub_bridge` | Chaînage avant en largeur (BFS) sur actions/buts + classement par intuition + réflexe doute→oracle. `execute_plan` est la clé de voûte (enregistre la trajectoire). |
| **Boucle d'événements** | `forge_event_stream` | Boucle en 6 étapes façon Manus, `PriorityQueue` asyncio, adaptateurs de providers. |
| **Silos parallèles** | `forge_orchestrator` | 7 `SiloDomain` tournent en parallèle (`parallel=True`). |
| **Lancer sans attendre** | `forge_runner` | Lancement détaché, IPC par mmap. |
| **Jobs détachés** | `run_job` / `job_status` | Les tâches longues (>70 s) tournent côté serveur et **survivent à un redémarrage du hub**. |
| **Workflows durables** | `forge_durable` (`DurableWorkflow`, `run_steps`) | **Étapes reprenables, en event-sourcing sur SQLite — rejeu au redémarrage, exactly-once par étape, relances par étape.** |
| **Reprise de chaîne après crash** | `forge_chain_executor` + `forge_durable.recover_chain_nodes` | Les nœuds laissés `running` par un crash sont remis en file en `retry_pending` (reprise) au lieu de rester bloqués. |
| **Observabilité en direct** | `forge_swarm_bus` + `/api/swarm/stream` | Flux d'événements SSE des sujets swarm/recon/orchestration. |
| **Historique des étapes** | `RAG/execution_traces.db` · `RAG/durable.db` | Chaque étape est persistée (état→action→état′, coût, succès / event-source durable). |
| **Relance / contre-pression** | disjoncteur de `forge_llm_router` + cooldown de `forge_llm_budget` | Relance par provider + gate budgétaire. |

---

## Exécution durable — LIVRÉE (`forge_durable`)

**Temporal** comme **Mistral Workflows** (qui tourne *sur* Temporal) résolvent le même
problème, que Nokido résout désormais **entièrement en local** :

> Un processus en plusieurs étapes qui **survit aux crashs et aux redémarrages**, et reprend
> à la dernière étape terminée au lieu de tout recommencer — sans rejouer les effets de bord.

`app/forge_durable.py` apporte cela SANS serveur temporal en Go (souverain, stdlib + SQLite) :

- **`DurableWorkflow(run_id).step(name, fn, ...)`** — le résultat de chaque étape est
  enregistré en event-sourcing dans `RAG/durable.db`. Après un crash ou un redémarrage,
  ré-instancier le même `run_id` **REJOUE** : les étapes terminées rendent leur résultat
  stocké (sautées, **exactly-once**), l'exécution reprend à la première étape inachevée.
  **Relances + backoff** par étape.
- **`run_steps(run_id, steps)`** — API d'adoption pour `orchestrate` / les déports ad hoc.
- **`recover_chain_nodes(conn_factory)`** — branché dans `forge_chain_executor.execute_pending` :
  un nœud laissé `running` par un crash (qu'`execute_pending` ne reprendrait jamais) est remis
  en file en `retry_pending`, dans la limite de `max_retries`. **Les chaînes résistent
  désormais aux crashs.**

Vérifié : crash → rejeu (étape terminée non ré-exécutée) → reprise → terminé ; récupération
de chaîne (périmé→relance, en cours conservé, épuisé→échec).

Un vrai `temporal server start-dev` (Go + SDK `temporalio`) reste une montée en gamme
optionnelle et lourde pour une durabilité distribuée multi-workers ; la version SQLite couvre
l'hôte unique.

---

## Primitives d'agents Mistral — déjà couvertes pour la plupart

Un tour de la documentation plus large de l'[API Agents/Studio de Mistral](https://docs.mistral.ai/studio-api/agents/introduction)
montre que Nokido a déjà des équivalents souverains de la plupart des primitives :

| Primitive Mistral | Équivalent Nokido | Statut |
|---|---|---|
| **Handoffs** (un agent appelle un agent, en chaîne) | `forge_handoff` (Agent + Transfer + `run_swarm`, HandoffRouter) | ✅ couvert |
| **Connectors** (serveurs MCP enregistrés, découverte d'outils à la demande) | registre MCP + namespace `forge.{cat}.{tool}` + recherche d'outils à la demande | ✅ couvert |
| **Outils intégrés** (exécution de code, recherche web, bibliothèque de documents) | `oracle_python_repl` · `web_egress` + SearXNG · RAG | ✅ couvert |
| **Judges** | `forge_scorecard` (6 axes déterministes, 0 LLM) | ✅ couvert |
| **Sorties structurées** | `forge_typed_task` (`format`=schéma d'Ollama, contraint par le moteur) | ✅ couvert |
| **État de conversation persistant** | `thread_id` (ask) + `execution_traces.db` | ◻ partiel |
| **Workflows / exécution durable** | `forge_durable` | ✅ **livré** |

## Feuille de route restante

`forge_durable` couvre le cœur (event-source + rejeu + relances). Reste à faire :

1. **Formaliser la séparation Workflow/Activity** dans `orchestrate` / GOAP : le plan est le
   workflow déterministe ; `run`, `ask`, `web_egress`, `oracle` sont des activités (utiliser `run_steps`).
2. Primitive **pause → signal** pour l'**approbation humaine** — elle sert la règle
   *« confirmer l'irréversible »* : un workflow se met en pause avant une activité destructrice,
   émet un `notify`, et reprend sur approbation.
3. **Requêtes par `run_id`** — exposer l'état vivant d'une exécution durable (le SSE de swarm_bus
   le fait déjà en partie).
4. **Purge** de `durable.db` via `forge_log_retention` (sinon croissance sans limite).

### Pourquoi c'est un différenciateur de souveraineté

Mistral Workflows repose sur un modèle **hybride** : *leur* orchestrateur (état, historique,
répartition) + *vos* workers — l'état de votre workflow **quitte votre machine**. Le
`forge_durable` de Nokido fait l'inverse : orchestrateur **et** workers **et** historique,
tout est **local** — une durabilité de niveau Temporal avec **zéro sortie d'état**.

---

## Voir aussi

- [03 — Aperçu architecture](03-Architecture.fr.md) · anatomie du hub
- [06 — Référence API hub](06-Hub-API-Reference.fr.md) · `orchestrate`, `run_job`, `task`
- [12 — Pile cognitive AMI](12-AMI-Cognitive-Stack.fr.md) · planificateur GOAP + intuition
- [`docs/EXEC_DOCTRINE.md`](../EXEC_DOCTRINE.md) · bannir les CLI headless du cœur de l'orchestration
- [`docs/ORCHESTRATION_REFERENCES.md`](../ORCHESTRATION_REFERENCES.md) · ce qui a été tiré de nomad/ray/temporal/extism

*Statut : **alpha** — l'exécution durable (`forge_durable`) est en service ; la feuille de
route restante (séparation workflow/activity, signaux d'approbation) est en cours.
Inspiration : Temporal, Mistral Workflows.*
