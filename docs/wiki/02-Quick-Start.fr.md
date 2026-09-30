---
type: guide
title: 02 — Démarrage rapide
status: draft
resource: repo://docs/wiki/02-Quick-Start.fr.md
generated: {by: forge_wiki_modules@INCONNU, at: 2026-09-22T13:02:47+00:00}
empreinte: INCONNUE
---

# 02 — Démarrage rapide

<!-- revu-le: 2026-09-29 -->
> Mise à jour : 2026-09-29

> 🌐 [English](02-Quick-Start.md) · **Français**

Après l'[installation](01-Installation.fr.md), cette page parcourt les **30 premières minutes** d'utilisation de Nokido.

## 🚦 Vérifier que le hub tourne

```bash
curl http://localhost:8766/health
# {"status":"ok","version":"18.3","ts":"..."}
```

Si tu obtiens `Connection refused` :

- Docker : `docker compose -f docker/nokido/docker-compose.yml ps`
- Natif : `nokido-hub` (ou `python -m tools.nokido_hub`)
- Windows NSSM : `nssm status LaForge-Master`

## 🔑 Configurer ton premier provider LLM

Nokido stocke les clés API dans un **vault** (DPAPI sur Windows, Keychain sur macOS, libsecret sur Linux). Jamais dans `.env` committé à git.

Ouvre l'admin web :

```
http://127.0.0.1:8766/admin/providers
```

Tu verras les providers configurés. Choisis-en un (ex. Groq — généreux free tier), clique "🔑 Set key", colle ta clé API, clique "Save to vault". Fait — Nokido routera vers Groq quand pertinent.

Alternative CLI :

```bash
nokido-vault set -k GROQ_API_KEY
# (colle la clé, entrée)
nokido-secrets status     # vérif
```

## 🎯 Ton premier appel

```python
import requests, json

# Le hub refuse un appel anonyme (401) : chaque appel porte le jeton et le nom d'un agent
# (voir 04 — Configuration clients MCP ; `tools/forge_mcp_json_sync.py --emit-headers <AGENT>`).
HEAD = {"Authorization": "Bearer <FORGE_TOKEN_...>", "X-Agent-Name": "CLAUDE",
        "Accept": "application/json, text/event-stream"}

resp = requests.post("http://localhost:8766/mcp", headers=HEAD, json={
    "jsonrpc": "2.0", "id": 1,
    "method": "tools/call",
    "params": {
        "name": "ask",
        "arguments": {
            "provider": "groq",     # ou "auto" pour la cascade
            "message": "Explique le pattern RAG en 3 lignes.",
        }
    }
}).json()

print(resp["result"]["content"][0]["text"])
```

Le hub :

1. Récupère la clé `groq` depuis le vault.
2. Route via `forge_llm_router.call_cascade` (failover auto).
3. Log l'appel dans `network_log` pour la télémétrie.
4. Renvoie la réponse.

## 🔌 Câbler un client CLI

Nokido parle **MCP** (Model Context Protocol). Choisis ton client préféré :

- [Claude Desktop](04-MCP-Clients-Setup.fr.md#claude-desktop)
- [Claude Code](04-MCP-Clients-Setup.fr.md#claude-code)
- [Gemini CLI](04-MCP-Clients-Setup.fr.md#gemini-cli)
- [Codex CLI](04-MCP-Clients-Setup.fr.md#codex-cli)
- [Cline (VS Code)](04-MCP-Clients-Setup.fr.md#cline)

Ou écris un client custom : la [Référence API hub](06-Hub-API-Reference.fr.md) documente les tools (read, run, query, rag, ask, orchestrate, etc.) — la liste exacte dépend du ring de l'agent (`tools/list`).

## 🧠 Utiliser le stack local d'abord

Nokido priorise l'inférence locale. Deux manières :

### Via Ollama (recommandé pour démarrer)

```bash
# Via Docker compose
docker exec laforge-ollama ollama pull qwen2.5-coder:latest

# Ou ollama natif
ollama pull qwen2.5-coder:latest
```

Puis `ask` avec `provider="ollama_local"`.

### Via llama.cpp (plus rapide, plus de contrôle)

`llama-server` sur :8091 avec `qwen2.5-coder:7b-instruct-q4_K_M`. Voir [docs/llamacpp_setup.md](../llamacpp_setup.md). Le service supervisé `NokidoLlamaNative` est **coupé par défaut** (`disabled = true` dans `proxy_deno/core/services.toml`) : l'activer pour cette voie.

## 🎨 Tester le TUI

```bash
python tools/nokido_tui.py
```

(`nokido-cli` est le client terminal simple, pas le TUI.)

Un pane par agent (Claude, Gemini, Codex, Cline, Master) plus des vues à bascule (RAG, services, tâches, santé, événements...). Raccourcis :

- `Tab` — pane suivant
- `Ctrl+B` — broadcast
- `Ctrl+K` — toggle pane RAG
- `Ctrl+U` — filtrer unread
- `F1` — modal aide

Référence complète : [09 — Référence TUI](09-TUI-Reference.fr.md).

## 📂 Exemples de workflows

### Interroger le RAG avant le cloud

```python
# Cherche d'abord
resp = requests.post("http://localhost:8766/mcp", headers=HEAD, json={
    "method": "tools/call",
    "params": {"name": "rag", "arguments": {
        "action": "search", "topic": "BGE-M3 embedding", "limit": 5}}
}).json()

# Puis ask (provider="auto" inclut contexte RAG si rag_context=True)
resp2 = requests.post("http://localhost:8766/mcp", headers=HEAD, json={
    "method": "tools/call",
    "params": {"name": "ask", "arguments": {
        "provider": "auto", "message": "Comment BGE-M3 diffère de sentence-bert?",
        "rag_context": True}}
}).json()
```

### Déporter une tâche longue à un daemon

```python
# Route admin : elle exige un Bearer ADMIN (tout autre -> 401)
ADMIN = {"Authorization": "Bearer <jeton admin>"}

# Soumet job, récupère un id -- le script doit vivre dans le dépôt (ou C:/tmp)
resp = requests.post("http://localhost:8766/admin/run_job", headers=ADMIN, json={
    "script": "tools/forge_humaneval_runner.py",
    "script_args": "--provider mistral --max 164",
    "online": True,          # provider cloud -> réseau nécessaire
    "lane": "bench",         # couloir anti-saturation
}).json()
job_id = resp["job_id"]      # "etat": "ACCEPTED" -- accepté n'est pas produit

# Poll status (l'état réel, réconcilié)
status = requests.get(f"http://localhost:8766/admin/job/{job_id}", headers=ADMIN).json()
```

Tu n'as pas à attendre le résultat dans ta session interactive.

### Utiliser `orchestrate` pour du raisonnement multi-étapes

```python
resp = requests.post("http://localhost:8766/mcp", headers=HEAD, json={
    "method": "tools/call",
    "params": {"name": "orchestrate", "arguments": {
        "task": "Trouve tous les modules forge_*.py avec complexité cyclomatique > 10, "
                "liste-les triés par complexité, propose refactor pour le top 3.",
        "max_iter": 6,
    }}
}).json()
```

Le hub orchestre la boucle LLM côté serveur. Ton client ne porte pas la chain-of-thought en contexte.

## ⚠️ Pièges courants

- **`Unauthorized`** — ton client n'envoie pas `Authorization: Bearer <token>` + `X-Agent-Name: <agent>`. Voir [04 — Configuration clients MCP](04-MCP-Clients-Setup.fr.md).
- **`ring 2 > max 0`** — tu as tenté `query` (SQL brut) qui requiert ring 0. Utilise `rag` (search sémantique) à la place. C'est la [règle #1](07-Security-Model.fr.md#3-rbac-6-anneaux-forge_integritypyintegrityring).
- **Réponse vide** — la clé du provider est absente ou quota épuisé. Check `/admin/providers`.

## 🚀 Prochaines étapes

- Ajuster les priorités cascade dans `app/forge_provider_specs.py`.
- Ajouter des tools custom via `tools/forge_*.py` (voir [CONTRIBUTING](../../CONTRIBUTING.md)).
- Lire le [Manifeste](../../MANIFESTO.md) pour le *pourquoi* derrière Nokido.
- Configurer un second client pour voir l'orchestration multi-agent (Claude + Gemini).
