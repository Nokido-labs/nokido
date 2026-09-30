# Architecture Collaboration Multi-LLM via Nokido MCP

Date : 2026-04-28
Status : DESIGN - à implémenter

## Vision

Nokido comme hub de connaissance partagée :
- Claude Desktop (toi) : orchestrateur principal, Ring 0 admin
- Gemini CLI : agent Ring 0 collab, accès complet en lecture + sandbox write
- Roo-Cline / Cline (VSCode) : agent dev Ring 1, lecture + write code
- Claude Code (VSCode) : agent dev Ring 1, lecture + write code
- Gemini Code Assist (VSCode) : agent code Ring 2, lecture seule
- GitHub Copilot (VSCode) : agent code Ring 2, accès partiel

## Ce qui manque actuellement (le gap)

Le tool `query` expose SQL brut mais :
1. Pas de résumé "contexte Nokido" pour onboarding rapide d'un agent
2. Pas de tool dédié "lire la mémoire" avec permissions par rôle
3. Pas de point d'entrée unique "qui suis-je dans Nokido, quel est le projet ?"

## Nouveaux tools à créer

### Tool 1 : `Nokido:memory` (NOUVEAU)

Accès lecture à la mémoire Nokido par catégorie.
PAS de SQL brut — API sémantique sécurisée.

Actions :
  - context     : résumé du projet en cours (ADR + rules + intention courante)
  - rules       : system_rules par tag
  - adr         : adr_records (toutes ou filtré par status/tag)
  - instructions: instruction_library (system prompts agents)
  - providers   : provider_scores + fleet_heartbeats
  - tasks       : agent_tasks récentes (limit)
  - search      : recherche sémantique dans rag_chunks (utilise FTS)
  - status      : état système (inspector_log + network_log récent)

Droits par rôle :
  - Ring 0 (Claude, Gemini) : toutes les actions
  - Ring 1 (Cline, Roo)    : context, rules, adr, search, providers, tasks
  - Ring 2 (Copilot, etc.) : context, search uniquement

### Tool 2 : `Nokido:memory action=context` — "briefing agent"

Retourne un résumé structuré pour onboarder un agent en 1 appel :

```json
{
  "project": "Nokido Sovereign Hub v18.5",
  "owner": "user",
  "active_sprint": "Sprint Alpha Bibliography Worker (16.5h)",
  "current_focus": "forge_biblio_core.py alpha2 completed, starting alpha3",
  "recent_adr": ["ADR-015: EventBus PULL mode", "ADR-016: Hash chain MD5"],
  "key_rules": ["AST check obligatoire", "pas de write >50 lignes", "backup avant modif critique"],
  "active_agents": ["CLAUDE (orchestrateur)", "GEMINI (collab Ring 0)"],
  "providers_up": ["mistral", "groq", "gpt4o_github", "gemini"],
  "memory_size": {"rag_chunks": 100561, "adr": 16, "rules": 45}
}
```

### Tool 3 : `Nokido:memory action=search` — recherche sémantique unifiée

Cherche dans rag_chunks + adr_records + system_rules + commit_intel en 1 appel.
Utilise FTS (rag_chunks_fts) pour vitesse + cosine similarity pour pertinence.

Utile pour Cline/Roo : "cherche comment Nokido gère les imports circulaires" → trouvera
les ADR + les lessons_learned + les commits pertinents.

## Modes de collaboration VSCode possibles

### Mode A : MCP Server Nokido dans VSCode (DÉJÀ POSSIBLE)

Roo-Cline et Cline ont déjà un token et une config MCP vers le hub.
Il suffit d'ajouter `Nokido:memory` dans le registre pour qu'ils y aient accès.

### Mode B : Workspace partagé Nokido = source de vérité

Le repo Nokido est la source de vérité.
- Claude (Desktop) : sprint + architecture
- Cline/Roo (VSCode) : implémentation code dans les fichiers
- Les 2 agents voient le même filesystem + même RAG via le hub

**Flow collab type** :
1. Claude (Desktop) définit l'architecture + écrit le spec (docs/)
2. Cline (VSCode) lit le spec via `Nokido:memory action=context` + lit les fichiers
3. Cline implémente le code dans app/ + tests/
4. Claude review via `Nokido:read` + valide
5. Git commit avec AST guard + vectorisation RAG auto

### Mode C : Task delegation via Nokido:task

Claude assigne via `Nokido:task action=assign agent=CLINE description=...`
Cline claim + implémente + retourne `Nokido:task action=result`
Claude review le résultat.

Ce mode est DÉJÀ en place (105 tâches dans agent_tasks).

### Mode D : Gemini Code Assist côté Cloud (nouveau)

Gemini Code Assist dans VSCode peut utiliser le contexte du workspace.
Si on expose le RAG via un endpoint HTTP GET simple (lecture seule), Copilot et
Gemini Code Assist peuvent l'indexer comme source de contexte supplémentaire.

Mais attention : ces agents ne passent PAS par le hub → pas de traçabilité.
À considérer uniquement pour la lecture de la documentation publique (docs/).

## Plan d'implémentation

### Phase 1 (30min) : Tool `Nokido:memory` dans forge_mcp_registry.py

```python
async def handle_memory(self, args, agent, ring):
    action = args.get("action", "context")
    
    if action == "context":
        return await self._memory_context(agent, ring)
    
    if action == "rules":
        return await self._memory_rules(args.get("tag"), ring)
    
    if action == "adr":
        return await self._memory_adr(args.get("status"), ring)
    
    if action == "search":
        query = args.get("query", "")
        return await self._memory_search(query, ring)
    
    if action == "instructions" and ring <= 1:
        agent_id = args.get("agent_id")
        return await self._memory_instructions(agent_id, ring)
    
    if action == "status" and ring == 0:
        return await self._memory_status(ring)
```

### Phase 2 (15min) : Droits par rôle dans _RIGHTS MCPSecurity

```python
_RIGHTS = {
    "laforge":  {"*": ["*"]},
    "cline":    {"read": ["*"], "write": ["app/","tests/","docs/","sandbox/"],
                 "run": ["python"], "memory": ["context","rules","adr","search","tasks"]},
    "ollama":   {"read": ["*"], "memory": ["context","search"],
                 "write": ["sandbox/","docs/"]},
    "external": {"memory": ["context"]},
}
```

### Phase 3 (optionnel) : Endpoint HTTP GET /api/context (lecture seule, no auth)

Pour Gemini Code Assist / Copilot qui ne passent pas par MCP :
GET http://127.0.0.1:8766/api/context → JSON briefing projet
GET http://127.0.0.1:8766/api/docs/{filename} → contenu docs/
Pas d'auth car localhost only + lecture seule + pas de secrets.

## Bénéfices attendus

1. **Onboarding instantané** : un agent qui démarre lit `memory action=context` et
   comprend immédiatement le projet, les règles, l'état du sprint

2. **Contexte partagé** : Claude et Cline travaillent sur la même base de connaissance
   sans se répéter → moins de tokens, moins de latence

3. **Traçabilité** : chaque accès à la mémoire est loggé dans network_log avec canal
   (GEMINI_OAUTH, CLINE_MCP, etc.) → debugging facilité

4. **Collaboration parallèle** : Claude architecture pendant que Cline code,
   les 2 partagent le même contexte Nokido via le hub

## Estimation effort

| Phase | Effort | Impact |
|-------|--------|--------|
| Tool memory (Phase 1) | 45min | Immédiat : tous les agents MCP ont accès |
| Droits par rôle (Phase 2) | 20min | Sécurité + collab structurée |
| Endpoint HTTP (Phase 3) | 30min | Copilot / Gemini Code Assist |
| **Total** | **~2h** | **Collaboration multi-LLM complète** |
