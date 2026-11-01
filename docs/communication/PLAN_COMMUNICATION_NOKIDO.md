# Plan de communication et lancement — Nokido

**Date :** 2026-10-23 · **Consigné par :** ANTIGRAVITY · **Rapatrié par :** CLAUDE, sur GO owner.
**Statut : À REPRENDRE PLUS TARD.** Consigne owner : « enregistre ça pour plus tard ». L'original disait « Validé / En attente d'exécution » : aucune validation n'a eu lieu.
**Préalables liés :** `docs/communication/AUDIT_CRITIQUES_EXTERNES_20261023.md` (signaux de surface, frontière de sécurité, profil léger à mesurer).
**À vérifier avant usage :** nom de commande `pipx run …` (le paquet publié est `nokido-agent`), noms d'images Docker, exigences de Smithery et des registres.

---

## 1. Principe

Pas de jargon biologique en vitrine. Présenter la douleur technique résolue.

> « Nokido est une passerelle de contrôle et de mémoire unifiée pour vos CLI d'agents (Claude Code, Cline, Gemini CLI…) : gouvernance déterministe, persistance locale cross-CLI, protection des ressources de la machine. »

## 2. Canaux

### A. Registres MCP
1. Smithery.ai (`smithery.yaml`).
2. `registry.modelcontextprotocol.io` (rebond Glama, PulseMCP, mcp.directory).
3. Cline MCP Marketplace (issue GitHub + `llms-install.md` à la racine).
4. Docker MCP Registry.

### B. Communautés
| Canal | Angle |
|---|---|
| Show HN | hub MCP local-first et mémoire partagée ; déclaré / observé / vérifié ; un agent ne réécrit pas sa gouvernance |
| r/mcp, r/MCPservers | passerelle de contrôle cross-CLI |
| r/LocalLLaMA | protection RAM/VRAM, anti-boucle d'outils |
| r/ClaudeAI | continuité de mémoire entre sessions et outils |
| r/selfhosted | zéro télémétrie, coffre natif de l'OS, AGPLv3 |

### C. Francophone et souverain
LinuxFr.org (AGPLv3, 100 % hors ligne à **prouver**), Korben.info, OW2 / IA frugale.

## 3. Prérequis avant publication
- [ ] Démo terminal < 30 s : décision dans Claude Code → SSoT → second CLI qui la retrouve ; action interdite bloquée.
- [ ] Installation < 2 min mesurée sur machine vierge.
- [ ] FAQ de différenciation (LiteLLM, Mem0 / Letta).

## 4. Phasage
0. Registres, démo, test d'installation.
1. r/mcp, r/selfhosted, LinuxFr.
2. Show HN (milieu de semaine), r/LocalLLaMA, r/ClaudeAI.
3. Korben, OW2, réseaux IA frugale.
