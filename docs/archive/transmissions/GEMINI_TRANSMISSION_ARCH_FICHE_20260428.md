# Fiche Technique Gemini CLI - Identité Ring 0
Date : 2026-04-28 (transmise via user depuis session Gemini CLI)
Statut : fiche reconstituée depuis rapport oral (fiches originales non écrites en filesystem)

## Identité

- **Modèle** : Gemini 2.5 Pro (confirmé via tool.ask response 10:06:16 : "Agent Gemini 2.5 Pro opérationnel")
- **Contexte** : 1M tokens input
- **Environnement** : Gemini CLI local, Windows
- **Bundle** : ~/AppData/Roaming/npm/node_modules/@google/gemini-cli/bundle/
- **Ring** : 0 (confirmé dans _resolve_ring via token GEMINI dans _AGENT_TOKENS)
- **Compte OAuth** : <your-gmail-oauth-account> (google_accounts.json)
- **Auth type** : oauth-personal (settings.json security.auth.selectedType)

## Différences vs Claude Desktop

| Aspect | Claude Desktop | Gemini CLI |
|--------|---------------|------------|
| Transport | STDIO bridge (mcp_stdio_bridge.py) | HTTP MCP direct (127.0.0.1:8766) |
| Auth | Bearer token CLAUDE dans _AGENT_TOKENS | Bearer token GEMINI dans _AGENT_TOKENS |
| Canal log | STDIO_CLAUDE | GEMINI_OAUTH |
| Accès filesystem | Via hub tools | Accès natif Node.js local |
| Modèle | claude-sonnet-4-6 ou opus | gemini-2.5-pro |
| OAuth scope (corrigé) | N/A | cloud-platform + userinfo.email + generativelanguage |

## Bug /auth diagnostiqué et corrigé (2026-04-28)

**Cause** : scope `generativelanguage.googleapis.com` ABSENT du bundle OAUTH_SCOPE  
**Patch Gemini** : injection dans chunk-UIBQS45C.js, WFCK2Z32.js, UGFPG7AM.js, GDRLBWZL.js  
**Correction Claude** : scope mal formé `.googleapis.com` en trop → corrigé vers `generativelanguage` seul  

**État** : bundles corrigés, prêt pour `/auth` après suppression oauth_creds.json

## Protocole d'appel MCP

```
POST http://127.0.0.1:8766/mcp
Authorization: Bearer 0ce30fa9... (token GEMINI)
X-Agent-Name: GEMINI
Content-Type: application/json

{"jsonrpc":"2.0","method":"tools/call","params":{"name":"<tool>","arguments":{...}}}
```

## Capacités Ring 0

Voir docs/GEMINI_CLI_NOUVELLES_REGLES.md pour règles communication complètes.
