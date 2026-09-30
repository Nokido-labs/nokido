# USAGE.md — Référence développeur Nokido

<!-- ports-arretes -->
> ⚠️ **Ports arrêtés cités dans cette page** (note ajoutée le 2026-08-30 ; le corps ci-dessous n'a pas été réécrit) :
>
> - `brain_worker :5557` est **arrete depuis le 2026-06-03** (OOM ONNX BGE-M3) — l'embedder vivant est `:8099` (BGE-M3 GGUF llama.cpp).


> Référence technique pour tout dev travaillant sur ou avec Nokido.
> Pour l'architecture générale : voir [README.md](../README.md). Pour les règles LLM : voir [CLAUDE.md](../CLAUDE.md).

---

## Sommaire

1. [Prérequis](#1-prérequis)
2. [Démarrage des services](#2-démarrage-des-services)
3. [Hub MCP — Référence tools](#3-hub-mcp--référence-tools)
4. [Providers LLM — table complète](#4-providers-llm--table-complète)
5. [RAG — patterns de requête](#5-rag--patterns-de-requête)
6. [ZMQ brain_worker](#6-zmq-brain_worker)
7. [Anneaux de sécurité (RBAC)](#7-anneaux-de-sécurité-rbac)
8. [Orchestration agentique](#8-orchestration-agentique)
9. [Intégration MCP (Claude / Cline / Gemini)](#9-intégration-mcp-claude--cline--gemini)
10. [NSSM — gestion des services Windows](#10-nssm--gestion-des-services-windows)
11. [Contrainte Python (LAFORGE_PYTHON)](#11-contrainte-python-nokido_python)
12. [Skills marketplace](#12-skills-marketplace)
13. [Patterns de session (start / end)](#13-patterns-de-session-start--end)

---

## 1. Prérequis

| Outil | Version | Rôle |
|-------|---------|------|
| Python miniforge3 | 3.12 | Runtime Nokido — **jamais `python` brut** |
| Ollama | latest | LLM local :11434 |
| llama.cpp (llama-server) | latest | Provider prioritaire :8091 (Vulkan) |
| Deno | 2.x | Système nerveux TypeScript :7401 |
| NSSM | 2.24+ | Gestionnaire services Windows |
| Git | any | Versioning + hooks |

---

## 2. Démarrage des services

```powershell
# Via supervisor LaForge-Master (méthode canonique)
nssm restart NokidoMaster

# Vérification
curl http://localhost:8766/health
curl http://localhost:8765/status
```

**Ne jamais** faire `nssm restart LaForgeMCP` directement — LaForge-Master est propriétaire exclusif du port 8766.

Services démarrés par LaForge-Master :

| Service NSSM | Port | Script |
|---|---|---|
| LaForgeMCP | 8766 | `tools/nokido_hub.py` |
| brain_worker | 5557 ZMQ | `app/brain_worker.py` |
| llamacpp_native | 8091 | `tools/forge_services_launcher.py` |
| NetcfgMCP | 8767 | `netcfg-agent-mcp.exe` |

Daemons Python autonomes (nohup séparé) :

```powershell
# Embed auto-trigger (~48k chunks/h BGE-M3 NPU)
~\miniforge3\python.exe tools\forge_embed_auto_trigger.py

# Compaction RAG (30min cycle)
~\miniforge3\python.exe tools\forge_auto_compact.py

# Evolution autonome (heartbeats 10min + lessons 30min)
~\miniforge3\python.exe tools\forge_auto_evolution_loop.py

# Polling Gemini CLI
~\miniforge3\python.exe tools\gemini_poll_daemon.py
```

---

## 3. Hub MCP — Référence tools

**Endpoint :** `POST http://localhost:8766/mcp`

```json
{
  "method": "tools/call",
  "params": {
    "name": "<tool>",
    "arguments": { ... }
  }
}
```

**Auth :** header `Authorization: Bearer <FORGE_MCP_TOKEN>`. Si `FORGE_MCP_TOKEN` vide → requêtes localhost acceptées sans token.

### Table des tools

| Tool | Ring min | Description |
|------|----------|-------------|
| `ask` | 3 | Appel LLM — `provider`, `prompt`/`message`, `max_tokens` |
| `run` | 3 | Shell/Python/Git/GitHub — `action`, `code`/`commands` |
| `read` | 3 | Lire fichier/logs — `action=file\|tail_logs\|stub`, `path` |
| `write` | 0 | Écrire fichier — `path`, `content` (Ring 0 obligatoire) |
| `query` | 2 | SQL sur `rag_chunks`/`agent_messages` — `sql` |
| `rag` | 3 | Index/search RAG — `action=index\|search`, `query` |
| `hub` | 3 | État hub — `action=get_mode\|set_mode\|poll\|notify\|list_providers\|search_recent` |
| `task` | 3 | Queue tâches — `action=assign\|claim\|result\|status`, `task_id` |
| `event` | 2 | EventBus — `action=publish\|history`, `topic` |
| `bundle` | 2 | Batch de calls primitifs en un round-trip |
| `plan` | 2 | GOAP planner — `goal`, décompose en étapes JSON-RPC |
| `orchestrate` | 2 | Boucle agentique llama.cpp Qwen-7B — `task`, `tools[]`, `max_iter` |
| `react_orchestrate` | 2 | Boucle ReAct Ollama qwen3:8b — `task`, `max_iter` |
| `loop_orchestrate` | 2 | Boucle GOAP autonome — `pattern`, `max_steps` |
| `route_task` | 3 | Route vers provider gratuit optimal — `task`, `use_case` |
| `route_dt` | 2 | Decision Tree router — prédit provider, `task` |
| `research_agent` | 3 | SearXNG + Groq → RAG zero-token — `query` |
| `biblio` | 3 | Bibliographie — `action=extract\|search\|list\|promote\|reject\|pin` |
| `crawl` | 1 | Crawl URL Markdown (Crawl4AI) — `url` |
| `skill` | 3 | Skills DB — `action=list\|load\|search\|ingest`, `name` |
| `web_search` | 3 | Recherche web SearXNG — `query` |
| `auto_test` | 1 | Lance pytest sur un module — `path` |
| `trigger_autonomous_evolution` | 1 | Déclenche boucle évolution — `intent` |
| `auto_ingest` | 2 | Hot-folder `data/rag_files/` — `action=scan\|start\|stop\|status` |
| `cross_platform_fs` | 2 | FS cross-platform (Win/WSL) |
| `manage_forge_lifecycle` | 1 | Lifecycle services — start/stop/restart |
| `netcfg_*` | 2 | 9 tools réseau (topology, ping, audit, terminal…) |

### Exemples

```python
import requests

BASE = "http://localhost:8766/mcp"

def hub_call(tool, args):
    r = requests.post(BASE, json={
        "method": "tools/call",
        "params": {"name": tool, "arguments": args}
    })
    return r.json().get("result")  # toujours .get(), jamais ["result"]

# Appel LLM local
hub_call("ask", {"provider": "llamacpp_local", "prompt": "Explique FAISS en 2 lignes"})

# Requête RAG SQL
hub_call("query", {"sql": "SELECT source, substr(text,1,200) FROM rag_chunks WHERE domain='nokido_code' LIMIT 5"})

# Lancer un shell
hub_call("run", {"action": "shell", "commands": ["git status", "git log --oneline -5"]})

# Notifier Gemini
hub_call("hub", {"action": "notify", "to": "gemini", "message": "Tâche X terminée"})
```

---

## 4. Providers LLM — table complète

### Locaux (ring 3 — zéro cloud)

| Provider | Port | Modèle | Latence | Note |
|----------|------|--------|---------|------|
| `llamacpp_local` | 8091 | Qwen2.5-Coder-7B Vulkan | ~300ms | **Prioritaire** — speculative decoding, --mlock, KV q8 |
| `lmstudio_native` | 1234 | local-model (OpenAI-compat) | ~200ms | Backup local |
| `ollama_local` | 11434 | qwen2.5-coder:7b-instruct-q4_K_M | ~400ms | Fallback ultime |

### Cloud gratuits (ring 8)

| Provider | Modèles | RPM | Latence | Use-case |
|----------|---------|-----|---------|----------|
| `gemini_flash` | gemini-2.5-flash | 15 | 800ms | Inspection R4, 1M ctx |
| `gemini_pro` | gemini-2.5-pro | 2 | 2s | Raisonnement complexe |
| `gemini_flash_lite` | gemini-2.5-flash-lite | 10 | 600ms | Léger, 250K ctx |
| `gemini_gemma` | gemma-3-27b-it | 30 | 700ms | Open-weight |
| `groq_fast` | llama-3.1-8b / 3.3-70b | 30 | 200ms | **Mode collab** 250+ t/s |
| `groq_mixtral` | mixtral-8x7b | 30 | 300ms | MoE rapide |
| `mistral_small` | mistral-small-latest | 30 | 900ms | Souverain EU |
| `mistral_large` | mistral-large-latest | 5 | 1.5s | Raisonnement EU |
| `github_gpt41_mini` | gpt-4.1-mini | 15 | 1s | 128K ctx, général |
| `github_deepseek_v3` | DeepSeek-V3-0324 | 10 | 900ms | **Top gratuit** |
| `github_codestral` | Codestral-2501 | 10 | 1.4s | Code dédié, 256K ctx |
| `github_llama_70b` | Llama-3.3-70B | 10 | 1.4s | Raisonnement |
| `sambanova_llama_405b` | Llama-3.1-405B | 10 | 2.2s | Raisonnement lourd |
| `openrouter_gpt_oss` | gpt-oss-120b:free | 20 | 1.5s | 131K ctx |
| `cohere_command_r` | command-r-08-2024 | 20 | 1.2s | RAG optimisé |
| `hf_qwen_coder` | Qwen2.5-Coder-32B | 10 | 2s | Code cloud lourd |

> Voir `hub_call("hub", {"action": "list_providers"})` pour la liste live avec état circuit-breaker.

### Use-cases câblés (`route_task`)

`speed` · `collab` · `debate` · `code` · `mermaid` · `sentinel` · `inspect` · `context` · `reasoning` · `eu` · `mesh` · `general` · `synthesis` · `strategy` · `orchestration` · `tool_call`

```python
# Route automatique selon use-case
hub_call("route_task", {"task": "Analyse ce code Python", "use_case": "code"})
```

---

## 5. RAG — patterns de requête

### FTS5 (BM25 — recherche mots-clés)

```sql
-- Anti-dup avant création module
SELECT bm25(rag_fts) as rank, source, substr(text,1,200)
FROM rag_fts
WHERE rag_fts MATCH 'Luhn OR "credit card" OR PII'
ORDER BY rank LIMIT 10;
```

### Semantic search via tool `rag`

```python
hub_call("rag", {"action": "search", "query": "comment router un LLM selon le use-case"})
```

### Preflight avant nouveau module

```python
import sys
sys.path.insert(0, r"~\Script python IA\Nokido\app")
from forge_self_correction import preflight_check_verbose

v = preflight_check_verbose("détection Luhn PII", "")
# Si tier <= 2 ET score > 0.5 → étendre l'existant, pas créer un doublon
for r in v['results'][:5]:
    print(f"[{r['score']:.2f}] {r['source']}: {r['preview'][:150]}")
```

### Ancrage solution/erreur

```python
from forge_self_correction import anchor_solution, anchor_error

anchor_solution(
    problem="Choix format embedding storage",
    solution="BLOB float32 binaire 1024D, _decode_embedding_blob() gère les 2 formats",
    example="struct.pack('1024f', *vec)",
    domain="rag"
)

anchor_error(
    error_msg="ZMQ REQ socket bloqué après timeout",
    context="forge_embed_auto_trigger.py — socket REQ état invalide",
    solution="Drain: RCVTIMEO=1000ms → recv() → RCVTIMEO=-1",
    domain="systeme"
)
```

### Distribution actuelle des chunks

| Domain | Chunks |
|--------|--------|
| gitingest | 341 783 |
| llm_routing | 60 247 |
| nokido_code | 30 610 |
| gitingest_litellm | 28 950 |
| conv | 11 927 |
| general | 11 438 |

---

## 6. ZMQ brain_worker

**Socket :** `tcp://localhost:5557` — DEALER ou REQ + msgpack.

```python
import zmq, msgpack, time

ctx = zmq.Context()
sock = ctx.socket(zmq.REQ)
sock.connect("tcp://localhost:5557")

# SUBMIT
sock.send(msgpack.packb(
    {"cmd": "submit", "type": "embed", "texts": ["texte1", "texte2"]},
    use_bin_type=True
))
if not sock.poll(10_000):
    raise TimeoutError("submit timeout")
rep = msgpack.unpackb(sock.recv(), raw=False)
task_id = rep["task_id"]  # clé = "task_id", pas "result"

# POLL
for _ in range(120):
    sock.send(msgpack.packb({"cmd": "check", "task_id": task_id}, use_bin_type=True))
    if not sock.poll(5_000):
        raise TimeoutError("check timeout")
    res = msgpack.unpackb(sock.recv(), raw=False)
    if res.get("status") == "completed":  # "completed", pas "done"
        vecs = res.get("data", {}).get("vecs", [])  # clé "data", pas "result"
        break
    time.sleep(1)
```

**Drain socket REQ après timeout :**
```python
sock.setsockopt(zmq.RCVTIMEO, 1000)
try:
    sock.recv()
except Exception:
    pass
sock.setsockopt(zmq.RCVTIMEO, -1)
```

**Throughput :** ~48 000 chunks/heure. Sub-batch recommandé : 20 textes/submit.

---

## 7. Anneaux de sécurité (RBAC)

| Ring | Nom | Modules | Accès |
|------|-----|---------|-------|
| 0 | MASTER | `forge_integrity.py` | Commandes système, `write` tool |
| 1 | TRUSTED | `forge_semantic_firewall.py` | auto_test, crawl, trigger_evolution |
| 2 | DEV | `forge_sovereign_membrane.py` | query, event, orchestrate, bundle, plan |
| 3 | COLLAB | `forge_prompt_guard.py` | ask, run, read, rag, hub, task, skill |
| 4 | UNTRUSTED | `forge_silo_fragmenter.py::NoiseGuardian` | web_search public uniquement |

### Firewall pre/post flight

```python
from forge_semantic_firewall import get_firewall

fw = get_firewall()
pf = fw.pre_flight(prompt, ring=2, provider="mistral")
# pf.safe_task = prompt avec IPs/tokens redactés
# pf.mapping = {"<IP_0>": "localhost", ...}

response = call_cloud(pf.safe_task)
pfr = fw.post_flight(response, task=prompt, session_id="sess_01")
clean = fw.restore(response, pf.mapping)
```

### Membrane souveraine (données structurées)

```python
from forge_sovereign_membrane import SovereignMembrane

membrane = SovereignMembrane(mission_id="audit_20260512")
wrapped = membrane.wrap(config_dict)
# wrapped.content = config avec alias HMAC persistants par mission
response = cloud_call(wrapped.content)
clean = membrane.unwrap(response)
```

---

## 8. Orchestration agentique

### Mode simple — `orchestrate` (llama.cpp Qwen-7B, :8091)

```python
hub_call("orchestrate", {
    "task": "Cherche dans le RAG si un module de détection Luhn existe, puis crée-en un s'il n'existe pas",
    "tools": ["query", "rag", "read", "write"],
    "max_iter": 10
})
```

### Mode ReAct — `react_orchestrate` (Ollama qwen3:8b)

```python
hub_call("react_orchestrate", {
    "task": "Analyse les 5 dernières leçons et propose des améliorations",
    "max_iter": 8
})
```

### GOAP — `plan` puis exécution manuelle

```python
plan = hub_call("plan", {"goal": "Ingérer le repo github.com/foo/bar dans le RAG"})
# → liste d'étapes JSON-RPC ordonnées
for step in plan["steps"]:
    hub_call(step["tool"], step["args"])
```

### Task queue — pattern assign/claim

```python
# Assign (producteur)
hub_call("task", {
    "action": "assign",
    "task_id": "embed_new_docs",
    "task_type": "embed",
    "payload": {"paths": ["docs/new.md"]}
})

# Claim + result (consommateur)
t = hub_call("task", {"action": "claim", "agent": "agt_embedder"})
hub_call("task", {"action": "result", "task_id": t["task_id"], "status": "done"})
```

---

## 9. Intégration MCP (Claude / Cline / Gemini)

### Claude Desktop (STDIO)

`%APPDATA%\Claude\claude_desktop_config.json` :

```json
{
  "mcpServers": {
    "laforge": {
      "command": "~/miniforge3/python.exe",
      "args": ["~/Script python IA/Nokido/tools/nokido_stdio_bridge.py"]
    }
  }
}
```

### Cline (Nokido_Plan / Nokido_Act)

Même pattern STDIO — voir `cline_mcp_settings.json` dans le projet.

### Gemini CLI (HTTP Bearer)

```bash
# Bearer = FORGE_MCP_TOKEN (vide = pas de token nécessaire en local)
export LAFORGE_HUB=http://localhost:8766
```

Gemini accède aux 24 tools exposés via `forge_mcp_registry.py` ring ≥ 8.

### Polling Gemini ↔ Claude via EventBus

```python
# Claude notifie Gemini
hub_call("hub", {"action": "notify", "to": "gemini", "message": "Tâche X prête"})

# Gemini poll inbox
hub_call("hub", {"action": "poll"})  # retourne agent_messages non lus
```

---

## 10. NSSM — gestion des services Windows

```powershell
# Statut de tous les services Nokido
nssm status NokidoMaster
nssm status LaForgeMCP
nssm status NokidoNetcfg

# Restart propre (TOUJOURS via Master)
nssm restart NokidoMaster

# Logs d'un service
Get-Content "~\Script python IA\Nokido\logs\nokido_hub.log" -Tail 50

# Vérifier qu'aucun process Python orphelin n'occupe :8766
netstat -ano | findstr :8766
```

Liste des services NSSM actifs : voir `proxy_deno/core/services.toml`, la declaration
qui fait autorite. (Le lien pointait vers un `SERVICES.md` qui n'a jamais existe.)

---

## 11. Contrainte Python (LAFORGE_PYTHON)

```
LAFORGE_PYTHON = ~\miniforge3\python.exe
```

- **Jamais** `python`, `python3`, ou `py` brut — charge le mauvais env, casse anyio/FAISS/ONNX.
- Pour pytest : `PYTHONNOUSERSITE=1 ~\miniforge3\python.exe -m pytest`
- Dans le code Nokido : `from forge_python_bin import LAFORGE_PYTHON, run_python`
- Hub `run action=python` : déjà sain (utilise `os.sys.executable` du hub).

---

## 12. Skills marketplace

```python
# Lister les skills disponibles
hub_call("skill", {"action": "list"})

# Charger un skill par nom
hub_call("skill", {"action": "load", "name": "forge-anatomy"})

# Recherche sémantique
hub_call("skill", {"action": "search", "query": "debugging systematic"})

# Ingérer un nouveau skill depuis fichier
hub_call("skill", {"action": "ingest", "name": "mon-skill"})
```

Skills clés existants : `forge-anatomy`, `forge-systematic-debugging`, `forge-tdd`, `nokido`, `laforge-ops`, `netcfg-agent`, `forge-veille-approfondie`, `forge-veille-rapide`.

---

## 13. Patterns de session (start / end)

### Début de session

```python
import sys
sys.path.insert(0, r"~\Script python IA\Nokido\app")
from forge_self_correction import read_lessons, preflight_check_verbose

print(read_lessons(3000))  # leçons récentes
v = preflight_check_verbose("<domaine de la tâche>", "")
print(f"Tier: {v['tier']} — {len(v['results'])} matches")
```

### Fin de session

```python
from forge_self_correction import session_summary

session_summary(
    commits=["abc1234 feat: ...", "def5678 fix: ..."],
    tests="X/Y passés",
    notes="Décisions importantes à retenir"
)
```

### Vérifier que tout est pushé

```bash
git log --oneline origin/alpha..alpha  # vide = tout est pushé
```

---

*Mis à jour 2026-05-12 — stats : 324 modules app, 312 tool scripts, 535k chunks RAG, 28 providers, 26+ hub tools.*
