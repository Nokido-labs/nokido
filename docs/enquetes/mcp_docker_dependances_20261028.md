# Enquête : dépendances MCP_DOCKER / mcp__MCP_DOCKER__ 
Date : 2026-10-28
Contexte : évaluer ce qui casse si l'on retire le serveur MCP `MCP_DOCKER` des clients.

## 1) Cartographie des références

| Fichier | Lignes | Nature | Impact si retrait |
|---|---|---|---|
| `tools/forge_bell.py` | 160-162 | Dispatch bell : agent `MCP_DOCKER`/`DOCKER_MCP` -> `notify` MCP "MCP_DOCKER task_id=..." | Perte du routage des tâches assignées à cet agent. Si plus utilisé, peu impactant. Remplaçable par un autre agent/route. |
| `tools/forge_rescue.py` | 163 | Référence dans contexte rescue | À vérifier usage effectif (lecture seule ici) |
| `tools/forge_trace_unifiee.py` | 42 | Mapping label "passerelle MCP docker" | Cosmétique/traçabilité, aucun effet fonctionnel |
| `tools/forge_vscode_mcp_sync.py` | 16 | Commentaire : préserve serveurs étrangers (video-gen, MCP_DOCKER...) | Comportement sync : doit continuer à ne pas toucher serveurs étrangers s'ils restent présents ailleurs ; si retiré des configs, pas d'effet |
| `app/forge_knowledge_concierge.py` | 71 | Source "fédération MCP externe" cite MCP_DOCKER/video-gen + tools | Métadonnées/description, pas de couplage dur |
| `app/forge_mcp_federation.py` | 5, 202 | But : expose serveurs MCP externes (MCP_DOCKER,...), message si absent | Module fédération : si MCP_DOCKER absent des configs scannées, il log/indique juste son absence. Retrait des configs clients => comportement attendu (rien à fédérer). |
| `tests/nr/test_mcp_json_sync_clients_http_nr.py` | 41,54,83 | Test : vérifie préservation de `MCP_DOCKER` dans config VS Code (`servers`) et qu'il n'est pas supprimé par sync | **Casse si test non mis à jour**. Le test s'attend explicitement à ce que `MCP_DOCKER` reste présent après sync. |
| `.agents/skills/forge-marketplace/SKILL.md` | 87,150 | Doc : marketplace #3 potentiel `MCP_DOCKER` gateway | Doc uniquement |
| `.agents/skills/forge-connectors/SKILL.md` | 163,186 | Doc : suggère `MCP_DOCKER` gateway comme alternative (GitHub/Bash) | Doc uniquement |
| `docs/skills/forge-marketplace/SKILL.md` | 91,154 | Idem (copie docs/) | Doc uniquement |
| `docs/skills/forge-connectors/SKILL.md` | 167,190 | Idem | Doc uniquement |
| `docs/external_tools_inventory.md` | 121 | Section catalogue MCP_DOCKER | Doc uniquement |
| `docs/gouvernance/PROFILS_CLI_CODEX_COPILOT_CLINE_20261024.md` | 25,27,45,72 | Profil CLI : `MCP_DOCKER` observé (accès Docker contournant hub), propose retrait pour Codex read-only | Doc/gouvernance |
| `docs/v13_6_orphan_inventory.md` | 232 | "Couvert par forge_search ou MCP_DOCKER searxng" | Doc uniquement |
| `seed/rag_chunks*.jsonl`, `seed/commit_intel.jsonl` | multiples | Historique/lessons/commits | Données historiques, aucun effet runtime |
| `.claude/settings*.json` / configs clients | (recherché) | Pas de match direct trouvé dans grep actuel | À vérifier si présents dans configs locales non versionnées |

## 2) État actuel : outils Docker dans le hub

Le hub expose déjà des outils Docker gouvernés (`nokido_docker_action`) avec politique stricte :
- `nokido_docker_action(argv, timeout?)` : actions Docker gouvernées via `forge_docker_agent` (contexte LaForgeTrusted). 
- Politique par défaut deny, lecture seule autorisée en général, lifecycle restreint aux conteneurs Nokido, run limité aux images whitelistées sans évasion hôte.

Voir schéma/usage dans AGENTS.md et outils MCP.

## 3) Remplacement proposé

| Cas d'usage observé | Remplacement | Notes |
|---|---|---|
| Tâches dispatchées via bell vers `MCP_DOCKER`/`DOCKER_MCP` | Router vers `nokido_docker_action` ou via `nokido_ensure_service` | `nokido_ensure_service(service, desired_state)` gère déjà lifecycle services Nokido (docker/searxng/hub/ollama/netcfg/webhub/graph/embed/lmstudio). Pour opérations Docker génériques gouvernées, utiliser `nokido_docker_action`. |
| Appels directs MCP_DOCKER depuis CLI | Passer par outils hub gouvernés | Éviter contournement hub (déjà noté comme "accès Docker en contournement du hub" dans gouvernance). |
| Catalogue MCP_DOCKER (Prisma/Stripe/Sentry/etc.) | Évaluer cas par cas | Si besoin, fédérer via `app/forge_mcp_federation.py` avec contrôles gouvernance ou remplacer par intégrations hub dédiées. |

## 4) Effets du retrait

- **Runtime** : Si aucun client n'utilise activement `MCP_DOCKER` et bell ne route plus vers lui, impact minimal. `forge_mcp_federation` se contentera de ne rien trouver.
- **Tests** : `tests/nr/test_mcp_json_sync_clients_http_nr.py` échouera car il affirme que `MCP_DOCKER` est préservé. À adapter si on retire officiellement le serveur.
- **Docs** : Beaucoup de docs mentionnent MCP_DOCKER comme option/marketplace - à mettre à jour pour refléter la voie hub gouvernée.
- **Sync configs** : `forge_vscode_mcp_sync` préserve serveurs étrangers par design - retrait effectif se fait dans les configs clients, pas dans le code sync.

## 5) Recommandation

1. **Vérifier usage réel** : grep dans logs/configs locaux non versionnés (.claude/settings.json hors dépôt, configs Codex/Gemini/Cline) pour confirmer s'il est encore actif.
2. **Si confirmé inutilisé** : 
   - Retirer des configs clients (Codex/Cline/VSCode/Gemini) 
   - Mettre à jour test NR pour ne plus exiger préservation
   - Nettoyer docs (ou marquer obsolète) 
   - Éventuellement retirer routing bell si plus de tâches vers cet agent
3. **Remplacer par voie hub** : documenter `nokido_docker_action` / `nokido_ensure_service` comme alternative gouvernée.

**Conclusion** : Retrait possible sans casse majeure côté code dépôt si configs clients mises à jour. Point bloquant principal est le test NR qui encode explicitement la préservation de `MCP_DOCKER`.
