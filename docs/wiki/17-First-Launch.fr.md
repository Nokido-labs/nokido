---
type: guide
title: 17 — Premier lancement
status: draft
resource: repo://docs/wiki/17-First-Launch.fr.md
generated: {by: forge_wiki_modules@INCONNU, at: 2026-09-22T13:02:47+00:00}
empreinte: INCONNUE
---

# 17 — Premier lancement

<!-- revu-le: 2026-09-29 -->
> Mise à jour : 2026-09-29

> 🌐 [English](17-First-Launch.md) · **Français**

Tu viens d'installer Nokido. Cette page t'accompagne sur les **10 premières minutes** : démarrer le hub, configurer ton premier provider LLM via l'UI web, faire ton premier appel.

## ✅ Vérification prérequis

```bash
# Hub répond
curl http://localhost:8766/health
# {"status":"ok","version":"18.3","ts":"..."}

# Vault fonctionne
nokido-secrets status
# Keyring: OK
# Coffre machine (1): ['FORGE_MCP_TOKEN']
# ...
```

Si quelque chose manque, retourne à [01 — Installation](01-Installation.fr.md).

## 🌐 Étape 1 — Ouvrir l'UI admin

```
http://127.0.0.1:8766/admin/providers
```

Tu vois un tableau des slots de providers LLM (39 au 2026-09-29). Certains sont **locaux** (Ollama, llama.cpp, LM Studio — pas besoin de clé). Le reste sont des providers **cloud** avec quotas.

Le badge sous la colonne "Status" de chaque provider t'indique :

- `✓ key present` → vault a la clé API, prêt à l'emploi.
- `✗ no key` → provider cloud, clé manquante. Clique "🔑 Set key".
- `n/a` → provider local, pas de clé requise.

## 🔑 Étape 2 — Ajouter ton premier provider free-tier

Recommandé pour démarrer : **Groq** (free tier, ultra-rapide).

1. Va sur <https://console.groq.com/keys> → génère une clé API.
2. Dans l'UI admin Nokido, trouve la ligne `groq` → clique **🔑 Set key**.
3. Colle la clé dans le champ password → clique **Save to vault**.

La clé est stockée chiffrée dans ton vault machine — **jamais dans `.env`**, jamais affichée dans les logs. Toast de confirmation en bas-droite : `Saved GROQ_API_KEY → vault (***xx1z)`.

Répète pour n'importe lequel de ces providers free-tier (chacun indépendant) :

| Provider | Console |
|---|---|
| Groq | <https://console.groq.com> |
| Cerebras | <https://cloud.cerebras.ai> |
| Google Gemini | <https://aistudio.google.com/apikey> |
| Cohere | <https://dashboard.cohere.com/api-keys> |
| GitHub Models | <https://github.com/settings/tokens> |
| NVIDIA NIM | <https://build.nvidia.com> |
| SambaNova | <https://cloud.sambanova.ai> |
| OpenRouter | <https://openrouter.ai/keys> |

Les quotas bougent avec les fournisseurs : lire le quota courant de chaque slot dans
`/admin/providers`, pas ici. Tu n'as pas besoin de tous — un seul suffit pour démarrer.
(Mistral est un slot `paid_api` dans le registre de Nokido ; HuggingFace et Cloudflare
n'ont plus de slot.)

## ▶️ Étape 3 — Tester ton provider

Dans l'UI admin, clique **▶ Test** à côté de ton provider. Le toast affiche :

```
✓ groq: ok
```

Si tu vois `✗ groq: no key in vault for GROQ_API_KEY` — la clé ne s'est pas sauvée. Réessaye, attention aux espaces de fin/début.

## 💬 Étape 4 — Premier appel depuis un script

```python
import requests

# Le hub refuse un appel anonyme (401) : passer le jeton et le nom d'un agent
HEAD = {"Authorization": "Bearer <FORGE_TOKEN_...>", "X-Agent-Name": "CLAUDE",
        "Accept": "application/json, text/event-stream"}

resp = requests.post("http://localhost:8766/mcp", headers=HEAD, json={
    "jsonrpc": "2.0", "id": 1,
    "method": "tools/call",
    "params": {
        "name": "ask",
        "arguments": {
            "provider": "groq",     # ou "auto" pour la cascade
            "message": "Explique RAG en 3 lignes."
        }
    }
}).json()

print(resp["result"]["content"][0]["text"])
```

Tu dois obtenir une réponse Groq en moins d'une seconde.

## 🔌 Étape 5 — Câbler ton client MCP favori

Maintenant connecte ton agent quotidien :

- **[Claude Desktop](04-MCP-Clients-Setup.fr.md#claude-desktop)** — bridge STDIO, config JSON.
- **[Gemini CLI](04-MCP-Clients-Setup.fr.md#gemini-cli)** — HTTP Bearer + hooks optionnels.
- **[Codex CLI](04-MCP-Clients-Setup.fr.md#codex-cli)** — HTTP Bearer + whitelist tools.
- **[Cline (VS Code)](04-MCP-Clients-Setup.fr.md#cline-vs-code-extension)** — bridges STDIO × 2 modes (Plan / Act).

Chaque client a son **bearer token dédié** pour que le hub sache quel agent parle et applique le bon ring RBAC.

## 🧠 Étape 6 — Tirer un modèle local (recommandé)

Local-first signifie que la cascade doit préférer local avant cloud. Tire un modèle codeur solide :

```bash
# Via Docker compose
docker exec laforge-ollama ollama pull qwen2.5-coder:latest

# Ou ollama natif
ollama pull qwen2.5-coder:latest
```

Maintenant quand tu fais `ask(provider="auto", ...)`, la cascade peut utiliser les slots locaux (`ollama_local`, `lmstudio_native`) partout où la chaîne du cas d'usage les liste — ex. la chaîne `code` — et retombe sur les slots cloud sinon (voir [05 — Providers LLM](05-LLM-Providers.fr.md)).

## 🎨 Étape 7 — Ouvrir le TUI

```bash
python tools/nokido_tui.py
```

Un pane par agent plus dix vues commutables. Appuie `F1` pour l'aide, `F3` pour faire défiler les vues, `Ctrl+K` pour basculer le pane RAG.

Voir [09 — Référence TUI](09-TUI-Reference.fr.md) pour les 23 commandes slash.

## 🛡️ Étape 8 — Vérifier les defaults sécurité

```bash
# Hub bind localhost uniquement (pas 0.0.0.0)
netstat -an | grep 8766
# Doit afficher : 127.0.0.1:8766

# Vault contient tes tokens (pas de leak .env)
nokido-secrets status
# Coffre machine (14+): [...]

# Hook pre-commit Gitleaks présent
ls .githooks/pre-commit
```

Si tu vois bind sur `0.0.0.0`, édite `docker-compose.yml` ou ton script de lancement — Nokido ne doit jamais être sur une interface non-localhost sans wrap TLS + auth (Tailscale, WireGuard).

## 🎚️ Étape 9 — Optionnel : comptes sandbox

Pour isolation par-tâche (les tools `run` / `orchestrate` exécutent sous identités sandbox) :

```powershell
# Windows (admin)
.\install.ps1 -WithSandboxUsers
```

```bash
# Linux / macOS (sudo)
WITH_SANDBOX_USERS=1 sudo -E bash install.sh
```

Provisionne :

- `LaForgeSbxOnline` / `laforge-sandbox-online` — sandbox AVEC egress réseau (appels cloud autorisés sous cette identité).
- `LaForgeSbxOffline` / `laforge-sandbox-offline` — sandbox sans réseau (firewall block outbound).
- `LaForgeTrustedRunners` / `laforge-trusted` — groupe d'utilisateurs autorisés à exécuter `trusted_script` via le hub.

Recommandé pour tout setup qui exécute du code LLM-généré (boucle SWE-bench, autonomie `orchestrate`).

## 🚦 Étape 10 — Inspecter ce qui s'est passé

```bash
# Trafic MCP récent (chaque appel loggé) -- network_log est dans la base principale du hub
sqlite3 <base du hub> \
  "SELECT ts, agent, tool, status FROM network_log
   ORDER BY ts DESC LIMIT 10"

# Ce qui a été ancré (anchor_solution / anchor_error) : le fichier des leçons, pas un
# balayage SQL de rag_chunks (des dizaines de Go : un filtre sans index lit tout)
tail -20 logs/lessons_learned.md

# État des secrets
nokido-secrets status
```

L'UI web `/forge/network` et `/forge/rag` montre les mêmes données visuellement.

## ✅ Tu es prêt

Tu as maintenant :

- Hub qui tourne, vault peuplé, au moins un provider configuré.
- Garde secret pre-commit actif.
- Routage cascade : local → cloud free → (optionnel) cloud payant.
- Audit log : chaque appel tracé dans `network_log`.
- (Optionnel) Comptes sandbox provisionnés.

Suite :

- **Usage quotidien** → [02 — Démarrage rapide](02-Quick-Start.fr.md) pour workflows courants.
- **Skills custom** → `docs/skills/nokido/SKILL.md`.
- **Approfondir** → [12 — Pile cognitive AMI](12-AMI-Cognitive-Stack.fr.md).
- **Quand bloqué** → [14 — Troubleshooting](14-Troubleshooting.fr.md).

## 🎁 Astuces

- **Tester la cascade** : ajoute 2 clés (ex. Groq + Cerebras), puis pousse le quota Groq à 100 % via le tester UI — regarde la cascade basculer automatiquement sur Cerebras.
- **Sauvegarde ton vault** : `data/machine_vault.dat` (Windows) ou ton export Keychain (macOS) sont à sauvegarder. Si tu les perds → tu dois ressaisir chaque clé API.
- **Ne partage pas `Nokido.env`** : même si les secrets ne sont plus dedans, le fichier peut contenir des configs non-sensibles (URLs, préférences modèles) qui mentionnent des endpoints internes.

Bienvenue dans Nokido.
