---
type: guide
title: 05 — Providers LLM
status: draft
resource: repo://docs/wiki/05-LLM-Providers.fr.md
generated: {by: forge_wiki_modules@INCONNU, at: 2026-09-22T13:02:47+00:00}
empreinte: INCONNUE
---

# 05 — Providers LLM

<!-- revu-le: 2026-09-29 -->
> Mise à jour : 2026-09-29

> 🌐 [English](05-LLM-Providers.md) · **Français**

Nokido route vers **29 providers** (3 locaux + 26 cloud) via cascade prioritaire. Chacun a un tier, un quota, une liste de capacités, et une clé API stockée en vault.

## 🖥️ UI admin web

Ouvre <http://127.0.0.1:8766/admin/providers> après [installation](01-Installation.fr.md).

La page affiche chaque provider avec :

- **Tier** : `local` (gratuit, infini) / `free` (cloud free-tier) / `subscription_quota` / `paid_api`.
- **Capabilities** : chat, code, reasoning, vision, long_context, tool_call, rag, multimodal, thinking.
- **Context window** size.
- **Statut quota** : appels/mois, appels/jour, % utilisé.
- **Vault key** : nom env-var canonique (ex. `GROQ_API_KEY`).
- **Status** : ✓ key present / ✗ no key / n/a (local).

Par ligne :

- 🔑 **Set key** — colle clé API dans input password → POST `/api/providers/<name>/key` → `forge_secrets.set_secret()` → vault DPAPI / Keychain / libsecret.
- ▶ **Test** — hit endpoint health du provider via `forge_provider_watcher` si dispo.
- ✗ **Remove** — `vault_delete(<key>)`, invalide le cache.

Filtres en haut : par nom (substring), par tier, "only missing keys".

## 🎯 Tier 0 — Local (gratuit, infini)

| Provider | Engine | Port | Notes |
|---|---|---|---|
| `ollama_local` | Ollama | :11434 | Tire modèles via `ollama pull`. Défaut : `qwen2.5-coder:latest`. |
| `llamacpp_local` | llama.cpp `llama-server` | :8091 | OpenAI-compat. Son service supervisé `NokidoLlamaNative` est **coupé par défaut** (`services.toml`). |
| `lmstudio_native` | LM Studio | :1234 | Chargement modèle manuel via UI LM Studio. |
| `ollama_mimo_v2` | Ollama | :11434 | Second slot Ollama local. |

Aucune clé API requise pour local. Le hub probe les ports au démarrage.

## 🔑 Tier 0.5 — CLI OAuth (abonnement, aucune clé API)

Providers qui pilotent un CLI tiers déjà authentifié (OAuth dans le profil user) —
**zéro clé API**, le quota = l'abonnement. Spawn `<cli> -p "<prompt>"`, sortie texte,
`SemanticFirewall` pre/post **auto** (Golden Rule #4). Exécutés en contexte du user
(auth dans `~/`), donc `USERPROFILE`/`HOME` pointés sur le user réel (le hub tourne SYSTEM).

Trois slots au 2026-09-29 (tier `subscription_quota`) : `claude_agent_sdk`, `claude_cli`
(ancien `claude -p`, même pool de quota que l'Agent SDK) et `gemini_cli` (`gemini -p`,
quota gratuit Google AI Studio). L'ancien slot `copilot_cli` n'existe plus.

## ⚡ Tier 1 — Cloud free (quotas généreux)

24 slots free-tier au 2026-09-29, dont : `groq`, `gemini_flash`, `gemini_flash_lite`,
`cohere_command_r`, `cohere_command_r_plus`, `sambanova`, `sambanova_llama_405b`, la famille
GitHub Models (`github_gpt41_mini`, `github_gpt4o_mini`, `github_codestral`,
`github_llama_70b`, `github_deepseek_v3`), la famille OpenRouter gratuite
(`openrouter_qwen_coder`, `openrouter_gpt_oss`, ...), `cerebras`, `nvidia_nim`.

Quotas et modèles bougent avec les fournisseurs : la liste **vivante**, avec quota, clé et
statut de chaque slot, est `/admin/providers` ; la source est
`app/forge_provider_specs.py::PROVIDER_SPECS`. Ne pas reprendre un quota de cette page dans une décision.

## 💵 Tier 2 — Payant / opt-in

Désactivés par défaut — activer explicitement par appel.

Huit slots `paid_api` au 2026-09-29 : `claude`, `openai`, `mistral_large`, `mistral_small`,
`xai_grok3`, `xai_grok3_mini`, `deepseek`, `perplexity`.

## 🔀 Moteur de routage

La cascade est configurée dans `app/forge_provider_specs.py::PROVIDER_SPECS` et consommée par `app/forge_llm_router.py::USE_CASE_CHAINS`.

Quand tu appelles `ask(provider="auto", ...)`, le router :

1. Détecte le *use_case* depuis le prompt (heuristique + `forge_dt_router`).
2. Construit une chaîne cascade pour ce use_case (local → free → payant).
3. Pour chaque provider :
   - Skip si quota > 80% (`forge_provider_quota.should_skip`).
   - Skip si pas de clé en vault.
   - Skip si `is_available()` retourne False.
   - Sinon appel `ask()` et retourne sur succès.
4. Si tout échoue, retourne l'enveloppe cascade-dégradée.

Tu peux forcer un provider avec `ask(provider="groq", ...)`.

## 🧠 Use cases

`USE_CASE_CHAINS` (dans `app/forge_llm_router.py`) comptait **17 cas d'usage** au
2026-09-29 : `speed`, `sentinel`, `inspect`, `collab`, `mesh`, `reasoning`, `debate`,
`strategy`, `context`, `synthesis`, `code`, `mermaid`, `eu`, `general`, `orchestration`,
`tool_call`, `agent_code`. Chacun pointe une chaîne ordonnée de slots — ex. `code`
commence par `lmstudio_native`, `openrouter_qwen_coder`, `mistral_small` ; `reasoning` par
`nvidia_nemotron_super`, `openrouter_free`, `gemini_pro`. Lire le dict lui-même pour les
chaînes courantes : cette page ne les recopie plus.

Ajuste selon tes priorités en éditant `PROVIDER_SPECS` ou `USE_CASE_CHAINS`.

## 📊 Tracking quota

`forge_provider_quota.py` enregistre chaque appel dans `embeddings.db.token_usage` :

- `usage_this_month(provider) → {calls, tokens, cost_usd}`
- `quota_status(provider) → {pct_calls, pct_tokens, ok}`
- `should_skip(provider, threshold=0.8) → bool`

L'UI web montre ces données. Le routeur cascade respecte `should_skip()` automatiquement.

## 🔐 Pourquoi le vault et pas `.env` ?

`.env` est un fichier plat qui se commit par accident, se copie cross-hosts, est lisible par tout process. Le vault :

- Chiffré au repos par l'OS (DPAPI / Keychain / libsecret).
- A une API cache + invalidation (`forge_secrets.invalidate_cache`).
- Est lisible par les comptes locaux sur Windows (machine-scope DPAPI) — nécessaire aux comptes sandbox `LaForgeSbxOnline` / `LaForgeSbxOffline` — **sauf les noms réservés** (jeton maître, secrets JWT...), que seul SYSTEM lit, au coffre réservé (durcissement du coffre 2b, 2026-09-28).
- A un CLI : `nokido-vault test|list|get|set|del`.
- A un diagnostic : `nokido-secrets status`.

Si tu as absolument besoin d'un fallback `.env` (CI), la chaîne fonctionne toujours : `get_secret()` lit le coffre réservé (noms réservés seulement) → coffre machine → WCM → `Nokido.env` → `os.environ`.

## 🧰 Ajouter un provider custom

1. Ajouter une spec à `app/forge_provider_specs.py::PROVIDER_SPECS` :

   ```python
   "my_custom": {
       "tier": "paid_api",
       "cost_usd_per_1m_in": 5.0, "cost_usd_per_1m_out": 15.0,
       "context": 200000,
       "capabilities": ["chat", "code", "reasoning"],
       "notes": "Provider interne via Tailscale.",
   }
   ```

2. Implémenter la classe provider sous `app/forge_provider_<vendor>.py` avec méthode `ask()`.

3. Registrer le mapping vault key dans `app/forge_provider_admin.py::PROVIDER_VAULT_KEY`.

4. Redémarrer le hub. Le nouveau provider apparaît dans l'UI web.

## 📡 Observer le trafic

```bash
# Appels récents par agent -- `network_log` vit dans la base principale du hub (forge_db_path.db_path())
sqlite3 <base du hub> \
  "SELECT agent, tool, COUNT(*) FROM network_log WHERE ts > datetime('now','-1 hour') GROUP BY agent, tool"

# État des secrets
nokido-secrets status
```

État de quota par provider : `/admin/providers`, ou `forge_provider_quota.quota_status(<provider>)`.

La pane RAG du TUI (Ctrl+K) montre aussi les appels récents.
