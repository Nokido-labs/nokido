# Nokido MCP Inspector — design figé

**Date** : 2026-04-27 19:25 UTC
**Auteur** : Claude (lecture seule — design only)
**Statut** : DOC-ONLY, attend validation utilisateur avant implémentation
**Cible** : `app/web_hub/mcp_inspector.py` + `app/web_hub/mcp_inspector.html`
**Mount** : `/inspector` sous le hub web FastAPI existant

## 1. Objectif

Outil de debug MCP intégré au web_hub Nokido, équivalent fonctionnel de
`@modelcontextprotocol/inspector` mais adapté à l'archi à 2 transports :

- **stdio** via `tools/mcp_stdio_bridge.py` (ce que voit Claude Desktop)
- **streamable_http** via `http://127.0.0.1:8766/mcp` (ce que voit Claude.ai web)

Pas d'endpoint SSE dédié — le streamable HTTP gère le canal serveur→client.

## 2. Périmètre

### Inclus
- Lister les outils par transport (`tools/list`)
- Invoquer un outil avec args JSON (`tools/call`)
- Diff payload byte-à-byte entre les 2 transports
- Tail live multiplex : `mcp_audit.log` + `mcp_bridge.log` + EventBus
- Status global : NSSM, /health, latence Groq, taille logs

### Exclus
- Pas de mock client custom
- Pas de stockage persistant (RAM only)
- Pas de WebSocket (SSE pour live, polling pour reste)
- Pas d'invocation JSON-RPC arbitraire (allowlist 14 outils)


## 3. Architecture

### Backend `app/web_hub/mcp_inspector.py` (~370 lignes)

**Pattern** : module avec `router = APIRouter()` mountable via
`app.include_router(router, prefix="/inspector", tags=["inspector"])`,
même pattern que `app/ctf_reports/views.py` et `app/netcfg/views.py`.

**Endpoints** :

| Méthode | Route | Rôle |
|---|---|---|
| GET | `/inspector/` | Page HTML 4-onglets |
| GET | `/inspector/api/tools/{transport}` | Liste outils via `tools/list` |
| POST | `/inspector/api/invoke` | `{transport, tool, args}` -> exec + retour req+resp+lat |
| POST | `/inspector/api/diff` | Diff parallèle 2 transports |
| GET | `/inspector/api/health` | NSSM + /health + log sizes + provider ping |
| GET | `/inspector/api/tap` | SSE multiplex hub + bridge + event bus |

**Auth** : middleware AuthMiddleware existant. Aucun bypass.

**Sécurité** :
- Bind via le hub (déjà 127.0.0.1)
- Pas de bypass SecretGuard
- Args JSON validés (max 64 KB, profondeur max 10)
- Outils en allowlist : 14 outils Nokido composites uniquement
- Pas de méthodes RPC arbitraires (rpc.discover etc.)

### Clients transport

**`_StdioClient`** (~100 L)
- `subprocess.Popen` `tools/mcp_stdio_bridge.py` à la demande
- Pipes stdin/stdout/stderr, write/read JSON-RPC ligne par ligne
- Timeout 30s, cleanup terminate+kill en finally
- 1 sec de surcoût par call (acceptable pour debug)

**`_StreamableHttpClient`** (~50 L)
- `httpx.AsyncClient` POST sur `http://127.0.0.1:8766/mcp`
- Headers `Content-Type: application/json`,
  `Accept: application/json, text/event-stream`
- Si Content-Type SSE -> lit jusqu'au dernier `data: {...}`
- Bearer token optionnel (FORGE_MCP_TOKEN env)

### Frontend `app/web_hub/mcp_inspector.html` (~400 L)

Vanilla HTML+JS, Tailwind CDN (autorisé par CSP), 0 build, pattern
identique à `forge_feed.html`.

**4 onglets** (radio + display:none) :
1. **Invoke** : transport + outil + args JSON + bouton -> req/resp/lat
2. **Diff** : outil + args + "Run on both" -> 2 colonnes diff colorisé
3. **Live Tap** : EventSource SSE, filtre source, regex, max 1000 rolling
4. **Health** : refresh 5s, NSSM + /health + Groq + log sizes


## 4. Contrats d'API détaillés

### `POST /inspector/api/invoke`

```json
// Request
{
  "transport": "stdio" | "streamable_http",
  "tool": "ask",
  "args": {"provider": "groq", "message": "test", "max_tokens": 5}
}

// Response 200
{
  "ok": true,
  "transport": "stdio",
  "tool": "ask",
  "request_payload": {"jsonrpc":"2.0","id":1,"method":"tools/call",...},
  "response_payload": {"jsonrpc":"2.0","id":1,"result":{...}},
  "latency_ms": 487.2,
  "timestamp": "2026-04-27T19:30:00.000Z"
}

// Response 400 args invalides / tool hors allowlist
{"ok": false, "error": "tool 'rpc.discover' not in allowlist"}

// Response 504 timeout
{"ok": false, "error": "transport timeout (30s)", "elapsed_ms": 30001}
```

### `POST /inspector/api/diff`

```json
{
  "ok": true,
  "stdio": { ...même schéma que invoke... },
  "streamable_http": { ... },
  "request_diff": null | {"lines": [...]},
  "response_diff": null | {"lines": [...]},
  "structural_match": true | false,
  "value_match": true | false
}
```

### `GET /inspector/api/tap` (SSE)

```
event: hub
data: {"ts":"19:30:01","src":"hub","method":"tools/call","tool":"ask","lat":487}

event: bridge
data: {"ts":"19:30:02","src":"bridge","direction":"in",...}

event: bus
data: {"ts":"19:30:03","src":"event","topic":"tool.task.start",...}

:ping  (heartbeat 15s)
```

## 5. Lignes rouges

- AUCUN bypass SecretGuard
- AUCUNE méthode JSON-RPC arbitraire (allowlist stricte 14 outils)
- AUCUN log persistant des invocations (privacy : args potentiellement sensibles)
- AUCUNE exposition au-delà 127.0.0.1
- AUCUNE modification du protocole MCP (strict client mode)

## 6. Plan d'exécution séquentiel

```
[1] Sauvegardes forensiques                   FAIT (inspector-20260427-192500)
[2] Design figé (ce document)                 FAIT
[3] Backend mcp_inspector.py                  EN COURS
[4] Frontend mcp_inspector.html               APRES
[5] Mount dans app/web_hub/app.py             APRES
[6] Smoke test (3 endpoints)                  APRES
[7] auto_test py_compile                      APRES
[8] MAJ transfer.txt + map.md                 APRES
```

## 7. Estimations

| Item | Lignes | Durée | Risque |
|---|---|---|---|
| Backend Python | ~370 | 1.5h | Faible |
| Frontend HTML/JS | ~380 | 2h | Moyen |
| Tests + smoke | ~60 | 30min | Faible |
| **Total** | **~810** | **4h** | Faible-Moyen |

## 8. Risques identifiés

**R1 — Spawn bridge stdio.** Chaque call stdio crée un Popen frais.
Sur Windows : `creationflags=CREATE_NO_WINDOW` pour éviter flash cmd.
Cleanup `terminate()` + `wait(2)` + `kill()` en finally.

**R2 — Bridge WT a ligne 348 commentée.** L'inspector verra le bridge
TEL QUEL en prod (sans log SQLite). C'est cohérent avec ce qu'on veut
tester (le réel, pas le théorique).

**R3 — Latence stdio.** ~1s spawn par call. Pour le tab Diff, parallèle
via `asyncio.gather` -> 1s total au lieu de 2s.

**R4 — Tap multiplex.** 3 sources timing différents. Pattern :
1 task asyncio par source -> queue commune -> consumer SSE.
Cap 1000 events queue, drop si plein.

## 9. Sauvegardes

```
sandbox/backups/inspector-20260427-192500/
├── MANIFEST.txt
├── app.py            (web_hub/app.py avant mount)
└── __init__.py       (web_hub/__init__.py)
```

Restauration en 1 commande si rollback.

---

**Fin de mcp_inspector_design.md**
