# Contexte par surface — 2026-11-09 (lecture seule)

| Surface | Mécanisme existant | Fichier:ligne | Où ça écrit | Lacune |
|---|---|---|---|---|
| CCR (contexte compacté) | observer context ledger | app/forge_mcp_registry.py:870 | sandbox/context_ledger.db | ILLISIBLE pour le reste |
| Relecture CCR | observer_relecture | app/forge_mcp_registry.py:3956 | sandbox/context_ledger.db | — |
| Run sortie | observer context ledger | app/forge_run_sortie.py:104 | sandbox/context_ledger.db | — |
| RAG search | retrieval router observer | app/forge_rag_engine.py:2359 | sandbox/router_observations.jsonl | — |
| Hub RAG search | retrieval router observer | app/forge_mcp_registry.py:8054 | sandbox/router_observations.jsonl | — |
| Authz shadow | observer trace | app/forge_authz_shadow.py:695 | journal authz | — |
| Task executor jugement | _juger_livraison | tools/forge_task_executor.py:3312 | sortie CLI | ILLISIBLE : pas d'écriture ledger prouvée |
| Stop attente passive | main hook | tools/hook_stop_attente_passive.py: (main) | ILLISIBLE | pas d'écriture prouvée |
| Claude inbox tick | main | tools/claude_inbox_tick.py: (main) | ILLISIBLE | pas d'écriture prouvée |
| Session provenance | module présent | tools/forge_session_provenance.py | ILLISIBLE (écriture non lue) | relecture 9/11 : le fichier EXISTE (le délégué l'a cherché dans app/) ; son point d'écriture reste à lire |

ILLISIBLE = aucune preuve lue pour ce point ; jamais « absent » sans preuve.

Relecture (Claude, 9/11) : `app/forge_run_sortie.py:104` vérifié (observer → context_ledger). Lacune
de la livraison : la table liste des observateurs, pas les SURFACES (Claude Code, AGY, OpenCode,
headless) ni, pour chacune, ce qui est servi à l'entrée et remonté à la sortie. Le ledger ne
comptait que 5 entrées au 9/11, aucune rattachée à une tâche déléguée : le « contexte servi » aux
exécutants ne s'y trace pas encore.