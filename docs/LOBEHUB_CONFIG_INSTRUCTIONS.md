# LobeHub Desktop -> Nokido wiring (manual)

LobeHub Desktop v2.1.56 stocke ses providers et MCP servers **dans le cloud**
(`storageMode: "cloud"`, gateway `device-gateway.lobehub.com`). Il n'y a
**aucun fichier local** que l'on peut patcher pour injecter `mcpServers` ou
`aiProvider`. Tout doit passer par l'UI Settings, qui sync vers le cloud.

Ce document liste les valeurs exactes a coller dans l'UI.

## SOLUTION CONFIRMEE (2026-05-02) — chemin UI exact

Le menu MCP direct n'existe plus. MCP fusionne dans le systeme "Skills".

### Ajouter le Hub Nokido (MCP)

1. Settings -> Skills -> Skill Store
2. Onglet **Custom** -> bouton **Add custom skill**
   - Alternative : dans un chat, bouton "Tools" au-dessus de la barre de saisie -> "Add custom skill"
3. Cliquer **Import JSON config** en haut du formulaire
4. Coller :

```json
{
  "mcpServers": {
    "laforge": {
      "url": "http://127.0.0.1:8766/mcp",
      "type": "http"
    }
  }
}
```

5. **Import** -> les champs se pre-remplissent
6. Authentification :
   - **Auth type** : API Key
   - **API Key** : valeur de `FORGE_MCP_TOKEN` (Nokido.env)
7. **Test connection** -> doit lister les tools a droite si OK
8. **Install / Save**

### Activer le MCP par agent

Skills sont par-agent. Apres install :
1. Ouvrir parametres de l'agent
2. Skills -> trouver `nokido` -> toggle ON

### Provider OpenAI-compat (forge_openai_proxy :7777)

Settings -> Model Providers -> Add Custom Provider :
- baseURL : `http://127.0.0.1:7777/v1`
- API Key : **VIDE** (force `fetchOnClient=true`, sinon cloud LobeHub proxy le call et echoue sur localhost)
- Alternative : si UI exige cle non-vide, basculer toggle "Client-side fetch" / "Fetch on client" sur ON dans advanced

## Etat investigation

- **Config locale** : `~\AppData\Roaming\LobeHub\lobehub-settings.json`
  - Contenu : window size, locale, proxy, shortcuts, sync mode, encrypted tokens
  - **NE contient PAS** : providers, modeles, mcpServers
- **Local Storage leveldb** : `~\AppData\Roaming\LobeHub\Local Storage\leveldb\`
  - SWR cache + UI prefs uniquement (panel widths, page sizes, view modes)
- **Backup app settings** : `~\AppData\Roaming\LobeHub\lobehub-settings.json.bak.20260502-222456`
- **Conclusion** : Path B (configuration manuelle via UI) est la seule voie.

## 1. Custom AI Provider (OpenAI-compatible -> forge_openai_proxy :7777)

**Pre-requis** : `forge_openai_proxy` doit ecouter sur `127.0.0.1:7777`.

```powershell
# Demarrer le proxy si pas deja UP
& "~/miniforge3/python.exe" "~/Script python IA/Nokido/tools/forge_openai_proxy.py" --host 127.0.0.1 --port 7777
```

### Etapes UI

1. Ouvrir LobeHub Desktop -> **Settings** (Ctrl+,)
2. Sidebar -> **AI Provider** (ou "Modeles AI" / "Language Models")
3. Cliquer **Add Custom Provider** (ou icone "+" / "Custom OpenAI")
4. Remplir :

| Champ | Valeur |
|---|---|
| Provider Name | `Nokido Local` |
| Provider ID / slug | `laforge-local` |
| API Type | `OpenAI` (ou "OpenAI Compatible") |
| Base URL / API Endpoint | `http://127.0.0.1:7777/v1` |
| API Key | `laforge-local` (placeholder, le proxy n'exige pas de cle) |
| Models | (auto-fetch via `/v1/models`) ou ajouter manuellement : `nokido`, `laforge-router`, `qwen2.5-coder`, `deepseek-r1` |
| Stream | ON |
| Function Calling | ON |
| Vision | OFF (sauf si modele cloud route le supporte) |

5. **Save** -> tester en chat : selectionner provider `Nokido Local`,
   envoyer un "ping".

## 2. Custom MCP server (HTTP -> nokido_hub :8766)

Nokido expose son hub MCP en **HTTP Streamable** sur :
- URL : `http://127.0.0.1:8766/mcp`
- Auth : `Authorization: Bearer <TOKEN_FROM_ENV>`
- Token a recuperer dans `~\Script python IA\Nokido\LaForge.env`
  (cle `FORGE_TOKEN_CLAUDE`, fallback `FORGE_MCP_TOKEN`)

### Etapes UI

1. **Settings** -> sidebar **MCP** (ou "Plugins" / "Tools" / "Extensions")
2. Cliquer **Add MCP Server** (ou "Custom MCP" / "+")
3. Choisir transport : **HTTP** (PAS stdio)
4. Remplir :

| Champ | Valeur |
|---|---|
| Server Name | `nokido` |
| Display Name | `Nokido Sovereign Hub` |
| Transport / Type | `HTTP` (ou "Streamable HTTP" / "SSE" selon UI) |
| Endpoint / URL | `http://127.0.0.1:8766/mcp` |
| Headers | `Authorization: Bearer <TOKEN_FROM_ENV>` |
| Timeout (ms) | `30000` |
| Auto-start | ON |

5. **Save** -> verifier que la liste des tools apparait (13 tools attendus :
   `forge_query`, `forge_ingest`, `forge_handoff`, `forge_silo_run`, etc.)

### Si l'UI demande un JSON brut (paste raw)

```json
{
  "mcpServers": {
    "laforge": {
      "type": "http",
      "url": "http://127.0.0.1:8766/mcp",
      "headers": {
        "Authorization": "Bearer <TOKEN_FROM_ENV>"
      },
      "timeout": 30000
    }
  }
}
```

Remplacer `<TOKEN_FROM_ENV>` par la valeur de `FORGE_TOKEN_CLAUDE`
depuis `Nokido.env`. **Ne jamais commiter ce token.**

## 3. Verification

Apres save dans l'UI :

```powershell
# 1. Verifier que le hub repond
$tok = (Get-Content "~/Script python IA/Nokido/LaForge.env" |
        Select-String "^FORGE_TOKEN_CLAUDE=").ToString().Split("=")[1]
curl -H "Authorization: Bearer $tok" http://127.0.0.1:8766/mcp/tools

# 2. Verifier que le proxy OpenAI repond
curl http://127.0.0.1:7777/v1/models

# 3. Dans LobeHub : ouvrir un chat, verifier dropdown provider -> "Nokido Local",
#    verifier panel MCP tools -> "laforge" actif avec liste de tools.
```

## 4. Action utilisateur

**Open LobeHub Settings -> AI Provider (add custom OpenAI 7777) + MCP (add HTTP 8766/mcp with Bearer token from Nokido.env).**

Pas de redemarrage necessaire (cloud sync), la config se propage en live.

## 5. Punted / non-fait

- **Pas de patch de fichier local** : LobeHub Desktop sync les providers/MCP
  dans le cloud (`device-gateway.lobehub.com`). Aucun JSON local a editer.
- **Pas de tentative LevelDB write** : l'UI ne lit pas les providers depuis
  leveldb (uniquement UI prefs/SWR cache) -> brute-force inutile et risque
  corruption.
- **Migration auto-providers via API gateway LobeHub** : possible en theorie
  via une API REST `https://device-gateway.lobehub.com/...` mais (a) non
  documentee publiquement, (b) requiert le `accessToken` chiffre stocke
  dans `lobehub-settings.json::encryptedTokens` qu'il faudrait dechiffrer,
  (c) hors scope de cette tache.
