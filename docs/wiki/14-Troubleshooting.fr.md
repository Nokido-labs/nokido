---
type: guide
title: 14 — Troubleshooting
status: draft
resource: repo://docs/wiki/14-Troubleshooting.fr.md
generated: {by: forge_wiki_modules@INCONNU, at: 2026-09-22T13:02:47+00:00}
empreinte: INCONNUE
---

# 14 — Troubleshooting

<!-- revu-le: 2026-08-21 -->
> Mise à jour : 2026-08-21

> 🌐 [English](14-Troubleshooting.md) · **Français**

Problèmes courants et solutions. Si ton problème n'est pas listé, ouvre une issue GitHub avec template *Bug report* — inclure OS, branche, commit SHA, repro minimal.

## 🌐 Hub & réseau

### Le hub ne démarre pas

```bash
curl http://localhost:8766/health
# curl: (7) Failed to connect to localhost port 8766
```

**Debug :**
1. Process tourne ?
   - Docker : `docker compose -f docker/nokido/docker-compose.yml ps`
   - Windows NSSM : `nssm status LaForge-Master`
   - Linux/macOS systemd : `systemctl status laforge-master`
   - Natif : check si `python -m tools.nokido_hub` toujours alive.
2. Port pris par autre chose ?
   - Windows : `Get-NetTCPConnection -LocalPort 8766 -State Listen`
   - Linux/macOS : `lsof -i :8766` ou `ss -tnlp | grep 8766`
3. Log boot :
   - Docker : `docker compose logs laforge-hub --tail=100`
   - Natif : `tail -100 logs/laforge-hub.log`

### `Unauthorized` 401 sur `/mcp`

Le hub retourne 401 quand :
- Header `Authorization` manquant.
- Bearer ne match aucune valeur dans `_AGENT_TOKENS` (vault-backed).
- Token roté mais client pas redémarré.

**Fix :**
```bash
nokido-secrets status | grep FORGE_TOKEN
# Vérifie + force-reload agent token dans config client (Codex/Gemini/...)
# puis restart client.

# Dernier recours : régénérer
nokido-vault set -k FORGE_TOKEN_CODEX
```

### `Origin not allowed` 403

Hub valide `Origin` per spec MCP. Autorisé par défaut : `http://127.0.0.1*`, `http://localhost*`, `app://`, `null`. Si client envoie autre, soit set `Origin: app://my-client` dans config client, soit édite `tools/nokido_hub.py::mcp_post`.

## 🔌 Câblage client MCP

### Client montre 0 tools

Usually issue config client-side. Test direct via curl :
```bash
curl -s -X POST http://127.0.0.1:8766/mcp \
  -H 'Content-Type: application/json' \
  -H 'Authorization: Bearer <YOUR_TOKEN>' \
  -H 'X-Agent-Name: <YOUR_AGENT>' \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}'
```

Si ça renvoie 25 tools, le hub OK. Le client n'envoie pas les bons headers, ou cache une vieille session.

**Codex CLI spécifique** : traite `enabled_tools` *absent* comme **whitelist vide**. Toujours lister explicitement dans `~/.codex/config.toml`.

### Client renvoie `Method not found` -32601

Soit :
- Champ `method` mal écrit. Doit être `tools/call` (avec slash).
- Tool name pas dans registry. Check `tools/nokido_hub.py::_AGENT_RING[YOUR_AGENT]`.

## 💾 RAG & vault

### `database is locked` SQLite

Cause courante : process Python stale qui hold le WAL lock.

```bash
lsof RAG/embeddings.db        # Linux/macOS
handle.exe RAG\embeddings.db  # Windows (Sysinternals)
kill <PID>
sqlite3 RAG/embeddings.db "PRAGMA wal_checkpoint(TRUNCATE);"
```

### Vault retourne `None` pour key connue

```bash
nokido-secrets status
```

Si key apparaît dans *Dans .env seulement*, vault l'a pas mais .env fallback marche. Migrer :
```bash
KEY_VALUE=$(python -c "from forge_secrets import _dotenv; print(_dotenv('YOUR_KEY') or '')")
nokido-vault set -k YOUR_KEY <<< "$KEY_VALUE"
```

### `keyring.errors.NoKeyringError` sur Linux

Manque libsecret ou daemon keyring.
```bash
sudo apt install libsecret-1-0 gnome-keyring
# OU headless : pip install keyrings.alt (fallback file-based)
```

## 🤖 Providers LLM

### Provider retourne vide / erreur

Ouvre <http://127.0.0.1:8766/admin/providers>. Check :
- Clé présente dans vault ? (badge ✓ vert).
- Quota épuisé ? (% orange/rouge).
- `forge_provider_watcher` l'a marqué unhealthy ?

Si quota 100%, cascade skip ce provider — tu dois voir l'appel routé vers le suivant auto.

### `litellm` échoue sur provider connu OK

Drift version `litellm` peut casser providers spécifiques.
```bash
pip show litellm
# litellm 1.40.0+ requis
```

## 🐳 Docker

### Container `laforge-hub` restart en boucle

```bash
docker compose logs laforge-hub --tail=200
```

Causes :
- `Nokido.env` manquant ou format bad.
- Port 8766 déjà bound sur host → swap mapping dans `docker-compose.yml` (ex. `"18766:8766"`).
- Hub crashed sur migration RAG/embeddings.db — check `LAFORGE_DB_MIGRATE=1` env.

### Modèle Ollama not found

```bash
docker exec laforge-ollama ollama list
# (empty)
docker exec laforge-ollama ollama pull qwen2.5-coder:latest
```

### Build échoue sur `faiss-cpu`

Wheels `faiss-cpu` pickys sur glibc + numpy versions. Dockerfile pin Python 3.12 spécifiquement.

## 🪟 Windows-spécifique

### `nssm restart LaForgeMCP` crash le hub

Don't restart `LaForgeMCP` direct — owned exclusively par `LaForge-Master` (supervisor service). Restart supervisor :
```powershell
nssm restart LaForge-Master
```

### `PowerShell : The term '<X>' is not recognized`

PowerShell 7+ requis. Check : `$PSVersionTable.PSVersion`. Doit être 7+.

Si tu vois ça avec `LAFORGE_PYTHON` — c'est pas une commande, c'est une constante dans CLAUDE.md. Replace par path absolu : `~/miniforge3/python.exe`.

### Long path errors

```powershell
New-ItemProperty -Path "HKLM:\SYSTEM\CurrentControlSet\Control\FileSystem" `
    -Name "LongPathsEnabled" -Value 1 -PropertyType DWORD -Force
```

Reboot.

## 🍎 macOS-spécifique

### `xcrun: error: invalid active developer path`
```bash
xcode-select --install
```

### `keyring.errors.PasswordSetError`
```bash
security unlock-keychain ~/Library/Keychains/login.keychain-db
```

## 🐧 Linux-spécifique

### `libsecret` not found runtime

Après `apt install libsecret-1-0`, may need running keyring daemon :
```bash
ps aux | grep -E "gnome-keyring|kwallet"
```

Si rien : start `gnome-keyring-daemon` (GNOME) ou `kwalletd5` (KDE). Headless : `keyrings.alt`.

### CUDA wheels mismatch driver
```
RuntimeError: CUDA error: no kernel image is available...
```
```bash
pip install torch==2.4.0 --extra-index-url https://download.pytorch.org/whl/cu121
```

## 📊 RAG / embeddings

### Rebuild embeddings hangs

Daemon `forge_embed_auto_trigger.py` embed par batches 200.

> ⚠ **Embedder déplacé (2026-06-03)** — l'embedder VIVANT = **`NokidoLlamaEmbed`
> :8099** (BGE-M3 Q8_0 GGUF, llama.cpp GPU/CPU). Les services `brain_worker` :5557
> ONNX sont **désactivés** (OOM 'bad allocation'). Tout `embed()` route via
> `forge_embed_router` → :8099.

Si hang, tester l'embedder :8099 :
```bash
curl http://127.0.0.1:8099/v1/embeddings -H "Content-Type: application/json" \
     -d '{"input":"ping"}'        # attendu : un embedding 1024 floats
nssm start NokidoLlamaEmbed       # restart si down (ou via superviseur :8765)
```

### RAG search retourne vide

```python
from forge_rag_engine import RAGEngine
rag = RAGEngine()
results = rag.search("your query", k=5)
```

Si vide :
- Index FAISS stale → rebuild : `python tools/forge_rebuild_local.py`.
- Query match rien → essaye FTS5 raw (ring 0 SQL).
- BGE-M3 scores sous seuil → lower threshold `forge_rag_engine.py::DEFAULT_SCORE_MIN`.

## 🧠 LLM / agent

### `forge_semantic_firewall` bloque prompt légitime

```python
from forge_semantic_firewall import get_firewall
fw = get_firewall()
pf = fw.pre_flight(your_prompt, context="", ring=2)
print(pf.reason if not pf.ok else "OK")
```

Faux positifs courants :
- Négation française (`ne … pas`) trigger certains patterns injection.
- Code avec keywords `system` / `assistant` / `tool`.

Ajuster seuils `app/forge_prompt_guard.py::DETECTION_THRESHOLD` ou ajouter prompt à `app/forge_semantic_firewall.py::ALLOWLIST_PATTERNS`.

### Cascade échoue pour tous providers

Check :
1. Toutes clés en vault ? `nokido-secrets status`.
2. Provider online ? `curl https://api.groq.com/health`.
3. Ollama local up ? `curl http://localhost:11434/api/tags`.
4. Quotas tous épuisés ?

## 🛠️ TUI

### TUI montre "no agent connected" partout

Heartbeat agent manquant. Check :
```bash
ls -lt sandbox/*.heartbeat
```

Si vide, restart hub. Si fichiers existent mais TUI les voit pas, check `LAFORGE_ROOT` env var match repo path.

### TUI keybinds marchent pas

Terminal swallow les keys. Try :
- **Windows Terminal** (pas legacy cmd.exe) sur Win.
- **iTerm2** (pas Terminal.app) sur macOS.
- Linux : terminfo capabilities `kf1`-`kf12`.

## 🔁 Reset général

Last resort : wipe state, garde code.

```bash
# Stop tout
docker compose down -v       # ⚠ remove volumes !
# ou
nssm stop LaForge-Master

# Wipe runtime (GARDE source)
rm -rf sandbox/* logs/* RAG/embeddings.db

# Re-init
bash install.sh
python tools/forge_db_bootstrap.py

# Start fresh
docker compose --profile core up -d
```

## 📞 Toujours bloqué ?

- Ouvre issue GitHub avec template *Bug report*.
- Signalement privé GitHub (onglet *Security* → *Report a vulnerability*) pour les bugs de sécurité.
- Check [FAQ](16-FAQ.fr.md) et [Glossaire](15-Glossary.fr.md).
