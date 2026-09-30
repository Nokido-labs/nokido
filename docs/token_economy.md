# Economie de tokens — Tuning CLI LLM (Claude / Gemini / Cline)

Chaque token depense doit produire de la valeur.

## Regles strictes

1. **Jamais Bash direct** — `mcp__laforge-sovereign-hub__run` action=shell ou PowerShell. Bash = bypass hub = chaos env.
2. **Jamais Agent() / sous-agents** pour RAG/recherche — `mcp__laforge-sovereign-hub__*` direct.
3. **Read avec offset/limit** — Grep d abord, Read cible. Economie : 80%.
4. **Batch appels independants** — 1 message = N tool calls paralleles.
5. **Caveman mode** — `/caveman` debut session. -75% output, -46% input.
6. **gemini_flash pour long-contexte** — 1M ctx, 800ms. Pas pour exploit (ring 8 firewall).
7. **orchestrate pour pipelines** — 1 call remplace 5-10 tool calls manuels.
8. **read_lessons une seule fois** par session.
9. **anchor_solution apres chaque bloc** — ~200 tokens investis = 2000+ economies futures.
10. **Pas de commentaires code** sauf WHY non-obvious.

## Signaux d alarme

| Signal | Remede |
|---|---|
| Read entier > 300 lignes | Grep d abord |
| 3+ Bash consecutifs | Batch shell |
| Agent() pour RAG | hub__query direct |
| Re-explication en fin de reponse | Supprimer |
| Poll supervisor boucle | Start-Sleep + check unique |

## Providers par use-case

| Cas | Provider |
|---|---|
| Code | `llamacpp_local` / `ollama_local` (ring 3) |
| Long-contexte | `antigravity_pro` / `claude_sonnet` |
| Raisonnement | `antigravity_pro` / `claude_opus` |
| Pipeline agentic | `orchestrate` (Qwen2.5-Coder) |
| Exploit/securite | `ollama_local` uniquement (firewall cloud) |

> [!IMPORTANT]
> **Règle d'Allocation Quota CODEX & Décommissionnement GEMINI** :
> 1. **Gemini supprimé** : Le provider Gemini n'existe plus dans l'écosystème et est définitivement remplacé par Antigravity (AGY). Les tâches ou routings ne doivent plus jamais cibler Gemini.
> 2. **Protection Quota CODEX** : Codex disposant d'un free-tier très restreint, **il est strictement interdit de lui envoyer des tâches lourdes** (comme des pipelines UI complexes ou des moulinettes sur codebases complètes). Ces tâches lourdes doivent être routées exclusivement vers `ANTIGRAVITY` ou `CLAUDE`.

## Forge Token Meter (Monitoring temps-réel par CLI)

Pour suivre en direct la consommation métabolique de chaque agent (CLAUDE, ANTIGRAVITY, CODEX...), Nokido dispose d'un compteur 100% déterministe (zéro appel cloud) :

- **Attribution par Agent** : L'intercepteur `forge_agent_proxy.py` capture automatiquement le contexte (`ActorContext` ou variable d'environnement `AGENT_NAME` / `X-Agent-Name`) pour attribuer chaque token consommé à l'agent réel.
- **CLI Dédié** : Exécuter `python tools/forge_token_meter.py [--agent NOM] [--hours N]` pour afficher le tableau ASCII des dépenses en USD et tokens.
- **Exposition Hub** : L'action `whoami` du Hub (`gy whoami` ou `after_model_hook`) inclut désormais le bloc `token_usage` avec le cumul en direct des appels, tokens prompt/complétion et coût total en USD.
