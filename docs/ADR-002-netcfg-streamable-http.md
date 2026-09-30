# ADR-002 : Migration netcfg-agent-mcp SSE → Streamable HTTP

**Date** : 2026-04-27  
**Statut** : PLANIFIÉ — deadline mi-2026  
**Auteur** : Claude (session 5)

## Contexte

`netcfg-agent-mcp` v0.1.1/0.1.3 tourne en HTTP+SSE (spec MCP 2024-11-05).  
La spec MCP 2025-03-26 déprécie HTTP+SSE et le remplace par Streamable HTTP.  
La deadline de fin de support SSE est mi-2026.

## Décision

Migrer `netcfg-agent-mcp` vers Streamable HTTP avant juin 2026.

## Plan d'action

1. **Mettre à jour `netcfg_mcp/server.py`** — remplacer `SSEServerTransport` par `StreamableHTTP`
2. **Endpoint unique `/mcp`** — POST pour requêtes, GET optionnel pour notifications SSE
3. **Session ID** — ajouter `Mcp-Session-Id` header (spec 2025-03-26)
4. **Origin validation** — déjà fait dans le hub, à porter dans netcfg
5. **Test de compatibilité** — Claude Desktop supporte Streamable HTTP depuis 2025-03

## Impact

- `claude_desktop_config.json` : type `streamable-http` déjà configuré ✅
- Token Bearer : inchangé ✅  
- Les 9 tools : inchangés ✅

## Risque

Faible — l'interface HTTP est déjà correcte, seul le transport change.

## Référence

- spec MCP 2025-03-26 : https://modelcontextprotocol.io/specification/2025-03-26/basic/transports
- commit session 5 : netcfg tourne en standalone HTTP sur :8767
