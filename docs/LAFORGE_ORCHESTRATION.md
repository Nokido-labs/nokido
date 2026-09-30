# Nokido Orchestration — Architecture MCP multi-LLM

Document factuel d'architecture orchestration Nokido au 2026-04-24.
Co-ecrit Claude + Gemini (review factuelle). Sources : code repo Nokido alpha,
commits `8a8396f` (orchestration) et `d96f611` (json shadowing fix).

## 1. Vue d'ensemble

Nokido est un hub d'orchestration multi-LLM qui permet a des clients heterogenes
(Claude Desktop en local, Gemini CLI a distance, futurs Cline/GPT) de piloter les
memes outils via le protocole Model Context Protocol (MCP).

Trois canaux d'acces coexistent :

- **MCP STDIO** : Claude Desktop charge `tools/nokido_mcp_server.py` comme
  sous-processus et communique via stdin/stdout. Latence typique tool_call <10ms
  intra-process.
- **MCP HTTP Bearer** : tout LLM externe appelle `http://127.0.0.1:8766/mcp` avec
  header `Authorization: Bearer <FORGE_MCP_TOKEN>`. Meme interface JSON-RPC 2.0,
  meme liste de tools, meme semantique.
- **MCP STDIO video-gen** : serveur dedie `netcfg-agent/tools/video/mcp_server.py`
  pour les generateurs video (CogVideoX, SVD), utilise par Claude Desktop
  directement.

Un quatrieme serveur specialise expose les capacites netcfg-agent via
`netcfg-agent/tools/mcp_http_server.py` sur port 8767 avec son propre Bearer token.

## 2. Schema architecture

```text
Clients LLM
+------------------+        +------------------+
| Claude Desktop   |        | Gemini CLI       |
| (MCP STDIO)      |        | (HTTP Bearer)    |
+--------+---------+        +---------+--------+
         |                            |
         | stdin/stdout               | POST /mcp + Bearer token
         v                            v
+------------------+        +-----------------------------+
| nokido_mcp_     |        | Hub Nokido :8766           |
| server.py        |        | nokido_hub.py v17.04-RT    |
| 13 tools         |        | 13 tools, listChanged=true  |
+--------+---------+        +---------+-------------------+
         |                            |
         +------+   +-----------------+
                |   |
                v   v
    +-------------------------------------+
    | _tool_call(name, args, ring)        |
    | + hub_middleware validate_mcp_body  |
    | + nokido_core ring guard           |
    +-----+---------------------+---------+
          |                     |
          v                     v
+------------------+   +-------------------------+
| forge_silo_      |   | forge_runner.spawn()    |
| engine           |   | - code base64 via env   |
| 7 SiloDomain     |   | - Popen DETACHED        |
| MODEL_MAP Ollama |   | - live_bridge mmap IPC  |
+--------+---------+   +-------------+-----------+
         |                           |
         v                           v
+------------------+      +-------------------------+
| Ollama :11434    |      | Process detache Python  |
| laforge-qwen     |      | ST_RUN -> ST_OK/ST_ERR  |
+------------------+      +-------------------------+

         forge_llm_router cascades (USE_CASE_CHAINS)
         speed/collab/debate/code/mermaid/sentinel/inspect/reasoning
         github_models -> openrouter -> hf -> llamacpp -> ollama

         RAG SQLite (embeddings.db, 14942 chunks)
         Partage par TOUS les agents via index_result / query

+---------------------------------------+
| netcfg-agent-mcp :8767                |
| mcp_http_server.py                    |
| 8 tools, proxies vers netcfg :7500    |
+---------------------------------------+
```

## 3. Tools exposes

### 3.1 Hub Nokido (port 8766) - 13 tools

| Tool | Description | Latence | Async ? | Commentaire |
|:---|:---|:---|:---|:---|
| `read` | Lecture fichier ou tail_logs | <50ms | Sync | Ring 0-4 |
| `write` | Ecriture atomique + AST guard .py | <100ms | Sync | Ring 0-2 seulement |
| `query` | SQL RAG sur embeddings.db | 30-300ms | Sync | Mutations reservees Ring 0 |
| `run` | Multiplexeur (github/python/atlas/snapshot/hub_*) | Variable | Mixed | `python` supporte `async:` prefix |
| `get_mode` | Mode collab + statuts agents | <20ms | Sync | bridge_state.json |
| `set_mode` | Change mode (AUTO/CLINE/CHEF/DEBAT/PING) | <20ms | Sync | Ring 0-1 |
| `notify` | Envoie message a l'autre agent | <10ms | Sync | Pending notifications |
| `poll` | Lit + vide notifications | <10ms | Sync | Consommation one-shot |
| `index_result` | Injecte resultat dans RAG | 100-500ms | Sync | Embeddings calcules |
| `search_recent` | Historique agent_tasks | <100ms | Sync | Filtre topic optionnel |
| `auto_test` | py_compile fichier .py | <500ms | Sync | Auto-retry sur erreur |
| `trigger_autonomous_evolution` | Decomposition silos fire-forget | <100ms ack, 1-60s job | **Async** | Retourne task_id |
| `task_status` | Statut task_id + JSON resultat | <20ms | Sync | Charge orch_*.json si OK |

### 3.2 netcfg-agent-mcp (port 8767) - 8 tools

| Tool | Description | Latence |
|:---|:---|:---|
| `audit_network` | Audit drift global (15 switches demo) | 40-80ms |
| `list_switches` | Inventaire filtrable (role, vendor) | 20-50ms |
| `preview_switch` | Commandes CLI remediation par shape_id | 30-100ms |
| `topology` | Export mermaid/d2/drawio | 30-80ms |
| `vendor_knowledge` | RAG vendor CLI (407 chunks, 5 vendors) | 40-150ms |
| `get_dashboard` | Stats globales parc | 200-400ms |
| `hosts_list` | Hosts filtrable par kind | 20-50ms |
| `generate_visio` | VSDX blank ou custom | 20-50ms |

Vendors couverts dans la RAG vendor_cli : Huawei VRP, HP Comware, HP ProCurve,
Aruba AOS-CX, Netgear ProSafe. 10 scenarios par vendor (vlan, trunk, lacp, bpdu,
dhcp, stp, etc.).

### 3.3 video-gen (STDIO) - 2 tools

| Tool | Description | Latence |
|:---|:---|:---|
| `cogvideox_text_to_video` | Texte -> video 6s (49 frames 8fps) | 2-5 min |
| `svd_image_to_video` | Image -> video 2s (25 frames) | 1-3 min |

## 4. Patterns d'orchestration

### PATTERN A : Claude pilote (MCP STDIO)

Claude Desktop charge directement `nokido_mcp_server.py` comme sous-processus.
Latence minimale, pas d'auth externe (le Ring est resolu par l'agent name local).

Cas d'usage : edition de code, refactor, lecture/ecriture de fichiers, test rapide.

### PATTERN B : Gemini pilote (HTTP Bearer)

Gemini CLI est configure dans `~/.gemini/settings.json` avec `url` pointant sur
`http://127.0.0.1:8766/mcp` et `Authorization: Bearer <token>`. Token = SHA256 hex
64 caracteres lu depuis `Nokido.env` (variable `FORGE_MCP_TOKEN`).

Cas d'usage : tache longue exploratoire, generation doc massive, analyse de parc
reseau.

### PATTERN C : Nokido auto-pilote (fire-and-forget)

Un LLM appelle `trigger_autonomous_evolution(intention, domains, max_silos)`.
Retour immediat avec `task_id:orch_xxx` en <100ms (apres warmup). Le silo engine
decompose l'intention en domaines (parmi les 7 SiloDomain : code, security,
strategy, synthesis, recon, exploit, doc), assigne chacun au meilleur modele via
`MODEL_MAP`, execute en parallele dans un process detache via
`forge_runner.spawn()`.

Le LLM poll ensuite via `task_status(task_id)` jusqu'a status=OK. Le JSON complet
(synthesis + silos + rag_indexed) est charge depuis `sandbox/orch_<tid>.json`.

Cas d'usage : tache complexe a plusieurs angles (doc + audit + recommandations).

### PATTERN D : Collaboration Claude <-> Gemini

Les deux agents partagent :
- La meme RAG SQLite `RAG/embeddings.db`
- Les notifications via `notify` + `poll` (round-robin entre agents enregistres)
- Les resultats indexes via `index_result` visibles par tous

Exemple concret valide (session 2026-04-24) : Claude a patche 5 fichiers, Gemini
a valide via enchainement de 3 tool calls netcfg, Claude a fait le commit, Gemini
a produit la doc (avec review factuelle par Claude pour corriger les
hallucinations).

**Regle d'or du pattern D** : toute doc produite par un agent sans lecture
prealable du code source via `read` doit etre reviewer factuellement par un autre
agent avec acces au code. Les LLMs halluciner des details techniques plausibles
quand ils n'ont pas le contexte exact.

## 5. Workflow fire-and-forget detaille

### Step 1 : Client invoque

```bash
curl -X POST http://127.0.0.1:8766/mcp \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $FORGE_MCP_TOKEN" \
  -d '{
    "jsonrpc": "2.0",
    "id": 1,
    "method": "tools/call",
    "params": {
      "name": "trigger_autonomous_evolution",
      "arguments": {
        "intention": "Audit VLANs critiques et propose un plan de remediation",
        "domains": ["security", "doc"],
        "max_silos": 2
      }
    }
  }'
```

Reponse (94ms apres warmup) :

```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "result": {
    "content": [{
      "type": "text",
      "text": "task_id:orch_3658532a02d — orchestration lancee en background. Poll via task_status(orch_3658532a02d)."
    }],
    "isError": false
  }
}
```

### Step 2 : Architecture interne du spawn

`trigger_autonomous_evolution` serialise l'intention en JSON, l'encode base64,
construit un script Python qui :

1. Importe `forge_silo_engine.get_silo_engine()`
2. Appelle `evolve(intention, hint_domains, noise)` (coroutine asyncio)
3. Serialise le resultat (task_id, intention, duration, synthesis, silos[])
4. Importe `live_bridge.bridge` et appelle `task_set(tid, ST_OK, result, dur_ms)`
5. Ecrit le JSON complet dans `sandbox/orch_<tid>.json`

Ce script est passe a `forge_runner.spawn()` qui :

- Alloue un slot mmap via `bridge.task_new(prefix)`
- Lance `Popen(python, "-c", runner, creationflags=DETACHED_PROCESS)` avec code
  en variable d'environnement `_LAFORGE_CODE` (base64)
- Demarre un thread daemon watchdog pour timeout (defaut 600s)
- Retourne immediatement le `task_id`

### Step 3 : Polling

```bash
curl -X POST http://127.0.0.1:8766/mcp \
  -H "Authorization: Bearer $FORGE_MCP_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "jsonrpc": "2.0", "id": 2,
    "method": "tools/call",
    "params": {
      "name": "task_status",
      "arguments": {"task_id": "orch_3658532a02d"}
    }
  }'
```

Retour typique en cours :
```
task_id=orch_3658532a02d
status=RUNNING
(tache en cours, relancer task_status plus tard)
```

Retour final :
```
task_id=orch_3658532a02d
status=OK
result_preview=OK
duration=7969ms

=== Resultat complet (orchestration) ===
{"task_id": "silo_20260424_024911_128bcb", "intention": "...", "duration": 1.23,
 "rag_indexed": true, "synthesis": "...", "silos": [...]}
```

## 6. Configuration MCP Gemini CLI

Fichier `~/.gemini/settings.json` :

```json
{
  "mcpServers": {
    "laforge-sovereign-hub": {
      "url": "http://127.0.0.1:8766/mcp",
      "headers": {
        "Authorization": "Bearer <FORGE_MCP_TOKEN_64HEX>",
        "X-Agent-Name": "GEMINI"
      },
      "timeout": 30000
    },
    "netcfg-agent-mcp": {
      "httpUrl": "http://127.0.0.1:8767/mcp",
      "headers": {
        "Authorization": "Bearer <NETCFG_MCP_TOKEN_64HEX>",
        "X-Agent-Name": "GEMINI"
      }
    },
    "video-gen": {
      "command": "C:/Users/.../python.exe",
      "args": ["C:/.../netcfg-agent/tools/video/mcp_server.py"]
    }
  }
}
```

Token format : SHA256 hex 64 caracteres, stocke dans `Nokido.env`
(FORGE_MCP_TOKEN) et `netcfg-agent/LaForge.env` (NETCFG_MCP_TOKEN).

Generation d'un nouveau token :
`python -c "import secrets; print(secrets.token_hex(32))"`

## 7. Exemples curl et Python

### Audit reseau

```bash
TOKEN=$(grep NETCFG_MCP_TOKEN netcfg-agent/LaForge.env | cut -d'=' -f2)
curl -X POST http://127.0.0.1:8767/mcp \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/call",
       "params":{"name":"audit_network","arguments":{}}}'
```

### Query RAG (Python)

```python
import requests
import os

TOKEN = os.environ["FORGE_MCP_TOKEN"]

def rag_search(keyword, limit=5):
    payload = {
        "jsonrpc": "2.0", "id": 1, "method": "tools/call",
        "params": {
            "name": "query",
            "arguments": {
                "sql": f"SELECT id, substr(text,1,200) FROM rag_chunks "
                       f"WHERE text LIKE '%{keyword}%' LIMIT {limit}"
            }
        }
    }
    r = requests.post(
        "http://127.0.0.1:8766/mcp",
        headers={
            "Authorization": f"Bearer {TOKEN}",
            "Accept": "application/json, text/event-stream",
        },
        json=payload,
        timeout=5,
    )
    return r.json()["result"]["content"][0]["text"]

print(rag_search("trunk vlan aruba"))
```

### Fire-forget avec polling (Python)

```python
import time
import requests

def wait_for_task(tid, poll_every=2, max_s=120):
    for _ in range(max_s // poll_every):
        r = requests.post(
            "http://127.0.0.1:8766/mcp",
            headers={
                "Authorization": f"Bearer {TOKEN}",
                "Accept": "application/json",
            },
            json={
                "jsonrpc": "2.0", "id": 1,
                "method": "tools/call",
                "params": {
                    "name": "task_status",
                    "arguments": {"task_id": tid},
                },
            },
        ).json()
        txt = r["result"]["content"][0]["text"]
        if "status=OK" in txt:
            return txt
        if "status=ERROR" in txt or "status=TIMEOUT" in txt:
            raise RuntimeError(txt)
        time.sleep(poll_every)
    raise TimeoutError(f"{tid} pas resolu apres {max_s}s")
```

## 8. Limitations et TODO

### Limitations actuelles

- **Auth monotoken** : un seul Bearer token par serveur, pas de RBAC granulaire.
  Tous les clients authentifies ont les memes droits Ring (defini par IP/name).
- **Pas de streaming WebSocket** : les LLMs clients doivent poll `task_status`
  toutes les 2s. Pas de push server-sent-events pour les progres intermediaires
  des silos.
- **Timeout fixe** : `forge_runner.spawn(timeout_s=600)` = 10 minutes max par
  silo. Pour des taches plus longues, il faut invoquer plusieurs fois ou passer
  en mode chef avec ressources dediees.
- **RAG non-vectorise cote lecture** : `query` fait du SQL texte LIKE, pas de
  recherche semantique. Pour le semantic search il faut passer par `rag.query()`
  en code interne.
- **Silos paralleles serialises si Ollama** : Ollama local ne gere qu'un seul
  prompt a la fois sur un modele. Les silos ciblant le meme modele sont executes
  en sequence.
- **Tendance hallucinatoire des LLMs** : les LLMs produisent des docs
  superficiellement plausibles mais factuellement fausses quand on ne leur donne
  pas acces prealable au code via `read`. Le pattern D (review croisee) est la
  mitigation.

### Bugs fixes lors de la session 2026-04-24

- **`bridge` undefined** dans `forge_runner.status()` : le module importait
  `bridge` uniquement localement dans `spawn()`, ce qui faisait planter
  `status()` avec `NameError`. Fix : import top-level dans `app/forge_runner.py`
  (commit `8a8396f`).
- **`json` shadowing** dans `nokido_hub._tool_call()` : 3 `import json`
  redondants dans des sub-actions de `run` faisaient apparaitre `json` comme
  variable locale pour toute la fonction, faisant planter `query` avec
  `UnboundLocalError`. Fix : retrait des imports redondants (commit `d96f611`).
- **Middleware `validate_mcp_body`** refusait `tools/list` car il exigeait
  `params.name` meme sur les methodes qui n'en ont pas. Fix : validation
  conditionnelle a `method == "tools/call"` (commit `8a8396f`).
- **`web.json_response`** utilise au lieu de `JSONResponse` (aiohttp vs
  Starlette) causait `NameError` capture par except generique et
  `"JSON invalide"` systematique. Fix inclus dans `8a8396f`.
- **Ring TUI bloquait** `trigger_autonomous_evolution` et `task_status` car ils
  n'etaient pas dans `_RING_CAPS[0]`. Fix : ajout de 9 tools dans rings 0/1,
  7 dans ring 2. Inclus dans `8a8396f`.

### Roadmap

- WebSocket pour streaming progres silos -> client
- RBAC par scope (read-only, netcfg-only, orchestration-only)
- Rotation automatique des tokens Bearer (TTL)
- Support MCP `resources/` et `prompts/` en plus de `tools/`
- Cache RAG embeddings en RAM pour reduction latence `query`

## 9. References code

Fichiers cles :

- `tools/nokido_hub.py` : serveur HTTP Hub sur port 8766, `_tool_call()` router.
- `tools/nokido_mcp_server.py` : serveur MCP STDIO pour Claude Desktop.
- `tools/hub_middleware.py` : validation JSON-RPC, `_ALLOWED_TOOLS`, sanitize.
- `app/forge_runner.py` : `spawn()` fire-forget + `status()` via mmap bridge.
- `app/forge_silo_engine.py` : decomposition silos, 7 SiloDomain, MODEL_MAP
  Ollama, `evolve_sync`/`evolve` coroutines.
- `app/forge_llm_router.py` : `USE_CASE_CHAINS` (speed/collab/debate/code/
  mermaid/sentinel/inspect/reasoning/eu/free/general), 20+ providers.
- `app/live_bridge.py` : mmap IPC entre Hub et processes detaches (task_new,
  task_get, task_set).
- `app/nokido_core.py` : `_RING_CAPS`, is_tool_allowed, prompts library.
- `netcfg-agent/tools/mcp_http_server.py` : serveur MCP :8767, 8 tools, proxies
  vers netcfg-agent REST :7500.

Donnees :

- `RAG/embeddings.db` : SQLite avec tables `rag_chunks` (14942 entries au
  2026-04-24), `event_log`, `agent_tasks` (historique), `rag_snapshots`.
- `sandbox/orch_<tid>.json` : resultat complet par tache orchestration.
- `sandbox/hub_live.log` : trace temps reel des tool_calls Hub.

---

Co-ecrit : Gemini CLI (draft initial 11.8 KB, stocke en
`LAFORGE_ORCHESTRATION_gemini_draft_*.md`) + Claude (review factuelle +
corrections). Commits de reference : `8a8396f`, `d96f611` sur branche alpha
Nokido.

Date : 2026-04-24.
