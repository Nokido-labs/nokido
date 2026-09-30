# llama.cpp dans Nokido — guide branchement complet

<!-- ports-arretes -->
> ⚠️ **Ports arrêtés cités dans cette page** (note ajoutée le 2026-08-30 ; le corps ci-dessous n'a pas été réécrit) :
>
> - `brain_worker :5557` est **arrete depuis le 2026-06-03** (OOM ONNX BGE-M3) — l'embedder vivant est `:8099` (BGE-M3 GGUF llama.cpp).


**Date** : 2026-04-30
**Cible** : tout LLM/agent/humain qui veut utiliser llama.cpp local depuis Nokido ou un client externe (Claude Code / Codex / Cline / Cursor / LM Studio / Continue.dev / Gemini CLI).

---

## 0. Topologie actuelle (ports utilisés)

| Service | Port | Endpoint racine | Rôle |
|---|---|---|---|
| `llamacpp_native` (binaire ggerganov, Vulkan) | **8091** | `http://127.0.0.1:8091/` | UI chat native + API OpenAI-compat |
| `llamacpp_python` (`llama-cpp-python` server) | **8090** | `http://127.0.0.1:8090/v1/...` | API OpenAI-compat + Swagger `/docs` |
| `ollama` | 11434 | `http://127.0.0.1:11434/api/...` | 11 modèles, API natif Ollama |
| `lmstudio` | 1234 | `http://127.0.0.1:1234/v1/...` | (souvent down, optionnel) |
| `brain_worker` (ZMQ embeddings) | 5557 | `tcp://127.0.0.1:5557` | embeddings MiniLM, pas LLM |
| `hub MCP Nokido` | **8766** | `http://127.0.0.1:8766/mcp` | bridge JSON-RPC pour clients MCP |
| `web_hub portail` | 7400 | `http://127.0.0.1:7400/` | dashboard auth-protected |

**Règle** : un client MCP (Claude Code, Cline, Codex…) parle à `:8766`, jamais directement à `:8090`/`:8091`. Inversement, un client OpenAI-compat (LM Studio, Continue.dev, Cursor) parle à `:8090` ou `:8091`, jamais à `:8766`.

---

## 1. Démarrage llama.cpp

### 1.a — Binaire natif Vulkan (UI chat) sur :8091
```powershell
# Path binaire
$LLAMA = "~\llama-vulkan\llama-server.exe"
# Modèle (blob Ollama qwen2.5-coder réutilisé, 4.7 GB)
$MODEL = "~\.ollama\models\blobs\sha256-60e05f2100071479f596b964f89f510f057ce397ea22f2833a0cfe029bfc2463"

& $LLAMA -m $MODEL --host 127.0.0.1 --port 8091 -c 8192 -ngl 99 --jinja
```
- `-ngl 99` = offload max sur GPU Vulkan (Radeon 780M)
- `-c 8192` = contexte 8K
- `--jinja` = template chat Jinja (Qwen native)
- `-ngl 0` = CPU pur si tu veux comparer

### 1.b — `llama-cpp-python` server sur :8090 (API only)
Lancé via le services launcher Nokido :
```bash
LAFORGE_PYTHON tools/forge_services_launcher.py --only llamacpp_native
```
Config dans `Nokido.env` (déjà en place) :
```
LAFORGE_LLAMACPP_NATIVE_PORT=8090
LAFORGE_LLAMACPP_PORT=8090
LAFORGE_LLAMACPP_NATIVE_CTX=8192
LAFORGE_LLAMACPP_NATIVE_GPU=0
LAFORGE_LLAMACPP_NATIVE_CHAT=qwen
```

### 1.c — Vérification rapide
```bash
curl http://127.0.0.1:8090/v1/models
curl http://127.0.0.1:8091/v1/models
curl http://127.0.0.1:8091/   # UI HTML chat
```

---

## 2. UI chat (`:8091/`)

### Accès
Ouvre `http://127.0.0.1:8091/` dans Chrome/Firefox. UI chat native llama.cpp avec :
- conversations multiples
- sélection de paramètres (temperature, top_p, repeat_penalty)
- markdown rendu, code blocks
- export JSON par conversation

### Conversations — où elles vivent
Le binaire natif stocke les conversations en **`localStorage` du navigateur** (pas server-side). Donc :
- elles survivent au reboot de llama.cpp ✓
- elles sont **liées au navigateur + profil** (pas synchronisables entre browsers)
- elles sont effacées si tu vides les données du site

### Récupération (export/import)
**Méthode 1 — UI** : chaque conversation a un bouton menu → "Export JSON".

**Méthode 2 — DevTools** :
1. F12 sur `http://127.0.0.1:8091/`
2. Onglet `Application` → `Local Storage` → `http://127.0.0.1:8091`
3. Clé typique : `llama-cpp-server-conversations` ou `chat-history`
4. Clic droit → Copy value → coller dans un fichier `backup.json`

**Méthode 3 — script** :
```javascript
// Coller dans la console DevTools (F12 → Console)
const dump = {};
for (let i = 0; i < localStorage.length; i++) {
  const k = localStorage.key(i);
  dump[k] = localStorage.getItem(k);
}
copy(JSON.stringify(dump, null, 2));  // copié dans le presse-papier
```

### Restauration
Sur la machine cible, dans la console DevTools :
```javascript
const data = /* paste JSON */;
Object.entries(data).forEach(([k, v]) => localStorage.setItem(k, v));
location.reload();
```

---

## 3. Branchement clients MCP (passent par hub :8766)

Tous ces clients parlent au **hub Nokido** qui route ensuite vers le LLM (cloud cascade ou llamacpp local en fallback).

### 3.a — Claude Code (CLI)
Config NSSM `LaForgeMCP` déjà active. Le service tourne sur :8766. Aucune action additionnelle pour utiliser llama.cpp depuis Claude Code — le `forge_llm_router` cascade automatiquement.

### 3.b — Codex CLI
`docs/CODEX_MCP_CONFIG.md` (déjà existant) :
```toml
# ~/.codex/config.toml
[mcp_servers.nokido]
url = "http://127.0.0.1:8766/mcp"
bearer_token_env_var = "LAFORGE_CODEX_TOKEN"
enabled_tools = ["run", "query", "hub", "rag", "read", "biblio"]
startup_timeout_sec = 10
tool_timeout_sec = 60
enabled = true
```
Var d'env :
```powershell
$env:LAFORGE_CODEX_TOKEN = "<votre-token-vault-FORGE_TOKEN_CODEX>"  # voir forge_vault_seed_agent_tokens.py
```

### 3.c — Cline (VS Code extension)
Fichier `cline_mcp_settings.json` (path : `%APPDATA%\Code\User\globalStorage\saoudrizwan.claude-dev\settings\cline_mcp_settings.json`) :
```json
{
  "mcpServers": {
    "Nokido_Plan": {
      "transport": { "type": "streamable-http",
                     "url": "http://127.0.0.1:8766/mcp" },
      "headers": { "Authorization": "Bearer <FORGE_TOKEN_CLINE>",
                   "X-Agent-Name": "CLINE_PLAN" }
    },
    "Nokido_Act": {
      "transport": { "type": "streamable-http",
                     "url": "http://127.0.0.1:8766/mcp" },
      "headers": { "Authorization": "Bearer <FORGE_TOKEN_CLINE>",
                   "X-Agent-Name": "CLINE_ACT" }
    }
  }
}
```
Token : `FORGE_TOKEN_CLINE` dans `Nokido.env`.

### 3.d — Gemini CLI (HTTP Bearer)
```bash
gemini config set mcp.servers.nokido.url http://127.0.0.1:8766/mcp
gemini config set mcp.servers.nokido.token "$FORGE_TOKEN_GEMINI"
```
Ou éditer `~/.gemini/config.toml`. Token : `FORGE_TOKEN_GEMINI` dans `Nokido.env`.

### 3.e — Cursor / Windsurf
Settings → MCP servers → Add :
- name : `nokido`
- transport : `http`
- url : `http://127.0.0.1:8766/mcp`
- headers : `Authorization: Bearer <token>`

---

## 4. Branchement clients LLM **directs** (OpenAI-compat, sans MCP)

Pour les agents qui veulent juste un backend LLM, pas tout l'écosystème Nokido.

### 4.a — Cursor — custom OpenAI base URL
```
Settings → Models → Add Custom OpenAI Model
- Name        : llamacpp-local
- Base URL    : http://127.0.0.1:8091/v1
- API Key     : sk-anything (le serveur l'ignore)
- Model       : qwen
```

### 4.b — Continue.dev (VS Code) — `~/.continue/config.json`
```json
{
  "models": [
    {
      "title": "llama.cpp Vulkan local",
      "provider": "openai",
      "apiBase": "http://127.0.0.1:8091/v1",
      "model": "qwen",
      "apiKey": "none"
    },
    {
      "title": "llama-cpp-python local (API)",
      "provider": "openai",
      "apiBase": "http://127.0.0.1:8090/v1",
      "model": "qwen",
      "apiKey": "none"
    }
  ]
}
```

### 4.c — LM Studio — multi-backend
LM Studio (sur :1234 quand UP) peut être configuré pour avoir un backend OpenAI-compat externe pointant sur `:8090` ou `:8091`. Permet de tester un même prompt sur les 2 backends + compare.

### 4.d — Open WebUI (Docker) — UI ChatGPT-like multi-modèles
```bash
docker run -d -p 3000:8080 \
  -e OPENAI_API_BASE_URL=http://host.docker.internal:8091/v1 \
  -e OPENAI_API_KEY=lm-studio \
  -v open-webui:/app/backend/data \
  --name open-webui --restart always \
  ghcr.io/open-webui/open-webui:main
```
Puis `http://127.0.0.1:3000/`.

### 4.e — appel curl direct
```bash
curl http://127.0.0.1:8091/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "qwen",
    "messages": [{"role":"user","content":"Hello"}],
    "max_tokens": 200,
    "temperature": 0.7
  }'
```

---

## 5. Réglages avancés llama.cpp natif

| Flag | Effet | Recommandation |
|---|---|---|
| `-ngl 99` | offload couches GPU | Vulkan AMD 780M : commencer 99 (full GPU), réduire si OOM |
| `-c 8192` | contexte | 8K équilibré, monter à 32K si modèle le supporte |
| `-b 512` | batch size eval | 512 default, augmenter si VRAM |
| `--threads N` | threads CPU | défaut = nb cores physique |
| `--jinja` | template chat Jinja2 | **toujours activer** pour qwen/deepseek |
| `--chat-template "qwen"` | template explicite | si auto-détection rate |
| `--mlock` | locker en RAM | utile si swapping |
| `-fa` | flash attention | gain perf si modèle compatible |
| `--metrics` | endpoint Prometheus `/metrics` | pour monitoring |
| `--log-disable` | silence stdout | pour daemon |
| `--api-key XXX` | auth Bearer | sécurise si exposé hors localhost |

---

## 6. Réglages côté Nokido (`Nokido.env`)

```bash
# Quel port côté Python server (forge_services_launcher)
LAFORGE_LLAMACPP_NATIVE_PORT=8090
LAFORGE_LLAMACPP_PORT=8090

# Topologie llama-cpp-python
LAFORGE_LLAMACPP_NATIVE_CTX=8192
LAFORGE_LLAMACPP_NATIVE_GPU=0      # 0=CPU, 99=full GPU
LAFORGE_LLAMACPP_NATIVE_CHAT=qwen

# Topic extractor biblio (override pour utiliser llamacpp au lieu d'ollama)
# LAFORGE_TOPIC_HOST=http://127.0.0.1:8090
# LAFORGE_TOPIC_MODEL=qwen

# Routeur LLM cascade (USE_CASE_CHAINS dans forge_llm_router.py)
# llamacpp_local est en fin de toutes les chains -> fallback automatique cloud-épuisé
```

---

## 7. Récupération conversations multi-source

| Source | Stockage | Récupération | Format |
|---|---|---|---|
| llama.cpp natif `:8091` UI | localStorage navigateur | DevTools → Local Storage → copy | JSON |
| Nokido mailbox `agent_messages` | SQLite WAL `RAG/embeddings.db` | `SELECT * FROM agent_messages WHERE created_at >= '...' ORDER BY ts` | rows |
| Nokido `conversation_log` | SQLite (1328 rows) | `SELECT * FROM conversation_log` | rows |
| Nokido `shared_prompt_log` | SQLite (1678 rows) | `SELECT * FROM shared_prompt_log` | rows |
| Nokido `forge_collab` | `sandbox/collab/<topic>.md` | `Read sandbox/collab/<topic>.md` | markdown append-only |
| Hub audit `mcp_audit.log` | `logs/mcp_audit.log` | `tail -f logs/mcp_audit.log` | logfmt |
| Claude Code conversations | `.claude/projects/<workdir-hash>/*.jsonl` | direct read | JSONL |
| Codex conversations | `.codex/sessions/` | direct read | JSON |

### Export unifié recommandé pour archivage
```bash
# 1. dump SQLite agent_messages JSON
LAFORGE_PYTHON -c "
import sqlite3, json, sys
conn = sqlite3.connect('RAG/embeddings.db')
rows = conn.execute('SELECT * FROM agent_messages WHERE created_at >= date(\"now\", \"-7 days\")').fetchall()
cols = [c[0] for c in conn.execute('SELECT * FROM agent_messages LIMIT 0').description]
out = [dict(zip(cols, r)) for r in rows]
sys.stdout.write(json.dumps(out, indent=2, ensure_ascii=False))
" > sandbox/exports/agent_messages_7d.json

# 2. backup llama.cpp localStorage (manuel via DevTools)
# 3. snapshot collab
cp -r sandbox/collab sandbox/exports/collab_$(date +%Y%m%d)
```

---

## 8. Quand llama.cpp est-il appelé automatiquement ?

`app/forge_llm_router.py` USE_CASE_CHAINS — `llamacpp_local` est en fallback en queue de **toutes** les chains :
- speed, collab, debate, code, mermaid, sentinel, inspect, context, reasoning, eu, mesh, general

Donc dès que groq/gemini/mistral/openrouter/github_models retournent 429 ou erreur, le router cascade sur `llamacpp_local`. Aucune action manuelle.

**Quand llama.cpp est-il NON-appelé ?** Si toutes les chains précédant llamacpp_local répondent OK. Pour forcer llamacpp en priorité, il faudra implémenter la **roadmap_master_llamacpp.md** (endpoint `/master/llamacpp/chat` ring=-1).

---

## 9. Diagnostic en 3 commandes

```bash
# Stack health
LAFORGE_PYTHON tools/forge_services_launcher.py --status

# llama.cpp répond-il aux 2 backends ?
curl -s http://127.0.0.1:8090/v1/models | python -m json.tool
curl -s http://127.0.0.1:8091/v1/models | python -m json.tool

# Hub MCP répond-il ?
curl -s http://127.0.0.1:8766/health
```

---

## 10. Anti-pièges

1. **NE PAS** confondre les ports : `:8766` = hub MCP (JSON-RPC), `:8090/:8091` = llama.cpp (OpenAI-compat). Pas la même API.
2. **NE PAS** exposer `:8091` hors localhost sans `--api-key` (le binaire écoute par défaut sans auth).
3. **NE PAS** lancer 2 instances llama.cpp sur le même port — bind error 10048 garanti.
4. **`:8080` est SearXNG** chez nous, pas llama.cpp (vu plus tôt). Llama.cpp est sur 8090/8091.
5. **TOUJOURS** vérifier `--jinja` ou `--chat-template` pour le bon format de prompt — sans ça, qwen répond en mode raw completion (mauvaises perfs).

---

**FIN guide** — version 1.0, 2026-04-30. Aligné avec `roadmap_master_llamacpp.md` (Phase 0 = pré-requis llama.cpp opérationnel ✓ déjà fait).
