# Backlog Architecture Nokido — post sprint α biblio

Date : 2026-04-28

> **[2026-08-21] provider_capability_audit — matrice par TRANSITION** (analyse externe
> endossée owner, corrigée par mesure). Étendre `forge_provider_reachability` (qui déclare
> déjà ses non-mesurés) en matrice provider × {key, endpoint (UA!), model_serving
> (GET /models), router_slot, chain, tool_call, agent, swarm} avec verdict par nœud —
> jamais « dans PROVIDERS donc dispo ». Job local 0-token. Faits établis le 21/08 :
> **Cerebras n'a JAMAIS été câblé au routeur** (`git log -S` vide — pas une régression)
> **et son compte rend 402** (recharger avant de câbler, sinon slot mort) ; Groq est
> **vivant** dans le routeur (whoami) — sa panne bench = empreinte urllib bannie par
> Cloudflare (403 code 1010), corrigée par User-Agent ; slots router `hf_llama`/HF = 402
> crédits. Pièges à encoder : UA anti-CF, modèles via GET /models (jamais en dur),
> trust score périmé si succès non comptés.

## SPRINT α BIBLIO (EN COURS)
Reste : α3 worker loop + α6a Tool MCP + α6b CLI

---

## P1 — Prompt Caching Claude (forge_agent_proxy.py)
3 lignes. cache_control: ephemeral sur system prompt.
ROI : -78% tokens input sur les sessions longues.
Effort : 30min.

## P2 — Vue "Actions Réflexes" dans le hub
Dashboard simple filtré sur les agents INTERNAL_HUB, INSPECTOR, post-commit.
Colonne channel=INTERNAL_HUB dans network_log déjà remplie.
Afficher : ts | action | latency | status | résumé.
Effort : 2h (page HTML dans nokido_hub.py).

## P3 — Throttle du poll Gemini CLI (gemini_poll_daemon)
GEMINI null = 27 appels/session = keepalive OK mais bruyant.
Passer de poll toutes Xs à poll toutes 30s quand inactif.
Ou filtrer définitivement du network_log (déjà partiellement filtré).
Effort : 30min.

## P4 — Pre-fetch session init (mcp_stdio_bridge.py)
Au "initialized", déclencher build_proactive_system() silencieusement.
Résultat : contexte RAG prêt avant la 1ère question.
Effort : 1h.

## P5 — Watchdog fichiers NSSM (watchdog Python)
Modif .py sans commit → re-vectorisation auto.
Manque actuellement (post-commit couvre commit, pas save direct).
Effort : 2h.

## P6 — Moindre privilège : break-glass LAFORGE_AGENT_OVERRIDE
Override agent write-paths avec expiry 1h + audit log immuable.
Effort : 1h.

## P7 — forge_spike_router branché au hub (grid neuronal)
Remplacer features CTF par features message entrant.
Entraîner sur network_log 60K+ entrées.
Routing LLM/tool par SNN au lieu de keyword matching.
Effort : 1 sprint dédié (8h).

## P8 — Tokens _AGENT_TOKENS vers keyring (sécurité)
Sortir les tokens Bearer du code source nokido_hub.py.
Effort : 1h.

## AUDIT SÉCURITÉ COMPLET
Quand l'archi est stable et fonctionnelle.
