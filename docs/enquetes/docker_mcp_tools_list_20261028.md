# Où le hub construit tools/list et comment y brancher le catalogue Docker préfixé `docker_`

Date : 2026-10-28

## Où tools/list est construit (file:line)
- **HTTP MCP endpoint** : `tools/nokido_hub.py:3485-3494`
  - Méthode `tools/list` -> retourne `get_registry().get_tool_list(ring=ring, agent=agent_hdr)` habillé par `_habiller_tl(...)`
- **Registre MCP** : `app/forge_mcp_registry.py`
  - `get_tool_list(self, ring: int = 4, agent: str = "UNKNOWN")` (ligne ~1555) : construit `visible = [t for t in self._all_tools() if ...]` puis applique scope/redteam/compact
  - `_all_tools()` (ligne ~1766) : `self._inject_explanation_field(self._raw_tool_catalog() + self._forge_dynamic_catalog())` puis `_inject_annotations`
  - `list_docker_tools()` (ligne ~3008) : interroge `get_supervisor().list_tools(force=force)` et renvoie outils préfixés `docker_*` (tolérant si gateway down) — **pas branché dans tools/list actuellement**
- **Proxy Docker** : `app/forge_mcp_registry.py:2989-3007` gère `docker_*` via `_handle_docker_proxy` (dispatch) mais **pas d'injection dans le catalogue tools/list**

## Comment y brancher le catalogue préfixé `docker_` SANS éditer forge_mcp_registry.py
**Objectif** : exposer le catalogue Docker préfixé `docker_` dans `tools/list` sans modifier `app/forge_mcp_registry.py` (réclamé par CLAUDE_HEADLESS).

Approches possibles (sans toucher au fichier réclamé) :
1. **Hook/monkeypatch** au niveau du registre/hub au démarrage
   - Dans `tools/nokido_hub.py`, après import du registre, monkeypatcher `ToolRegistry.get_tool_list` ou `ToolRegistry._all_tools` pour ajouter les outils docker depuis le cache (`catalogue_en_cache()` depuis `forge_docker_supervisor`) sans appeler le gateway/ensure_daemon.
   - Avantage : pas d'édition de `forge_mcp_registry.py`. Risque : fragile si API change.
2. **Extension via forge_tool_forger / catalogue dynamique** 
   - Le catalogue dynamique ajoute `forge_call_dynamic`, `forge_list_dynamic_tools`, `dyn_*` via `_forge_dynamic_catalog()`. On pourrait ajouter un générateur de `docker_*` dynamiques basé sur le cache, mais `get_tool_list` autorise déjà `dyn_*` pour ring<=2 ; pour les autres rings il faut vérifier la logique. De plus ça changerait le namespace (dyn_ vs docker_).
3. **Middleware/patch au niveau hub** 
   - Dans `tools/nokido_hub.py` handler `tools/list`, après récupération de `get_tool_list(...)`, injecter les outils docker depuis le cache si absents. Nécessite d'accéder au registre/supervisor.
4. **Fichier de patch externe appliqué au chargement** 
   - Utiliser `sitecustomize.py` ou importer un module `nokido_docker_catalog_patch` qui monkeypatche au moment opportun.

**Recommandation concrète (sans éditer forge_mcp_registry.py)** :
- Ajouter un module `app/forge_docker_catalog_patch.py` qui, à l'import, monkeypatche `ToolRegistry.get_tool_list` pour :
  - appeler la méthode originale
  - si le résultat ne contient pas d'outils `docker_*` et que le cache est `FRAIS`/disponible, lire via `forge_docker_supervisor.catalogue_en_cache()` (SANS spawn/ensure_daemon) et injecter des entrées `{"name": f"docker_{n}", "description": ..., "inputSchema": ...}` avec le même format que `_all_tools()` (ajouter `explanation` si manquant via `_inject_explanation_field` si accessible, sinon l'ajouter minimalement)
  - respecter le filtrage ring/agent existant (ne pas contourner les règles)
- Importer ce module depuis `tools/nokido_hub.py` au démarrage (près de l'initialisation) ou depuis `app/nokido_hub_boot.py` s'il existe. Vérifier où le hub importe le registre.

**Vérification nécessaire** :
- S'assurer que `forge_docker_supervisor.catalogue_en_cache()` est importable sans effet de bord
- Le cache est écrit uniquement après `list_tools()` réussi (pas au spawn) - conforme à "lister ne doit JAMAIS réveiller Docker"
- `ensure_daemon` n'est appelé que dans `spawn_gateway_stdio()` appelé par `_jsonrpc()` appelé par `list_tools()`/`call_tool()` - donc lecture du cache ne déclenche rien

**Fichiers concernés** :
- `app/forge_docker_supervisor.py` (modifié) - ajout cache
- `tests/nr/test_docker_catalogue_cache_nr.py` (créé) - tests NR
- `app/forge_docker_catalog_patch.py` (à créer si on branche) - patch sans éditer registre
- `docs/enquetes/docker_mcp_tools_list_20261028.md` (ce document)
