# CLOUD_PROVIDERS.md — Stratégie LLM cloud Nokido

*Mis à jour : 2026-04-16 | Branche : alpha*

## 🎯 Providers configurés

| Provider | Statut | Coût | Modèles |
|----------|:------:|:----:|---------|
| **Ollama local** | ✅ | Gratuit (local) | qwen2.5, llama3.2, etc. |
| **Gemini** | ✅ | Gratuit (free tier généreux) | gemini-2.5-flash (défaut), gemini-1.5-pro |
| **OpenRouter** | ✅ | **Gratuit** (free tier illimité) | 29 modèles `:free` |
| ~~DeepSeek~~ | ❌ | Payant | Compte vide, non utilisé |
| ~~Anthropic~~ | ❌ | Payant | Pas de clé |
| ~~OpenAI~~ | ❌ | Payant | Pas de clé |

## 🆓 Modèles gratuits OpenRouter (sélection)

Compte free tier illimité (`limit: None, remaining: None`). Chaque modèle peut être
rate-limited individuellement → cascade automatique sur plusieurs.

### Recommandés (testés OK)

| Modèle | Contexte | Force |
|--------|---------:|-------|
| `openrouter/openai/gpt-oss-120b:free` | 131K | **Top pick** — 120B params, généraliste fort |
| `openrouter/openai/gpt-oss-20b:free` | 131K | Plus rapide, moins fort |
| `openrouter/z-ai/glm-4.5-air:free` | 131K | Multi-langue, raisonnement |
| `openrouter/qwen/qwen3-coder:free` | 262K | **Code** (souvent rate-limit) |
| `openrouter/google/gemma-4-31b-it:free` | 262K | Long contexte, instructions |

### Long contexte (262K+)

| Modèle | Contexte | Notes |
|--------|---------:|-------|
| `qwen/qwen3-coder:free` | 262K | Code |
| `google/gemma-4-31b-it:free` | 262K | Général |
| `nvidia/nemotron-3-super-120b-a12b:free` | 262K | MoE |
| `qwen/qwen3-next-80b-a3b-instruct:free` | 262K | Général |

## ⚙ Configuration Nokido.env

```bash
# Provider primaire (priorité 1) : Ollama local
LITELLM_MODEL=ollama/qwen2.5
LITELLM_API_BASE=http://localhost:11434

# Cloud fallback (cle valide, free tier)
GEMINI_API_KEY=AQ.Ab8RN...
GEMINI_MODEL=gemini-2.5-flash
OPENROUTER_API_KEY=sk-or-v1...
```

## 🔀 Stratégie cascade (recommandée)

L'idéal : tenter Ollama local d'abord, puis cascade cloud sur erreur/timeout.

```
1. ollama/qwen2.5             (local, <1s, gratuit)
2. gemini/gemini-2.5-flash    (cloud, ~2s, gratuit, ~15 RPM free tier)
3. openrouter/openai/gpt-oss-120b:free  (cloud, ~3s, gratuit, rate-limit aléatoire)
4. openrouter/z-ai/glm-4.5-air:free     (fallback cloud)
```

Le `forge_litellm_bridge` actuel fait : Ollama → LiteLLM (un seul provider).
Pour activer la cascade multi-cloud, voir `forge_llm_router.py` (Ring 8).

## 🛡 Sécurité cloud (sovereign_mapper)

Tous les appels cloud passent automatiquement par `forge_sovereign_mapper` :
- **Anonymisation** des IP / MAC / credentials avant envoi
- **Désanonymisation** des alias dans la réponse
- **Persistance SQLite** : `recon_silo/recon_data/sovereign_mapper.db`

Vérification : si tu envoies `localhost` dans un prompt cloud, le LLM voit
`@@host_001@@` et la réponse repasse en clair côté local.

## 📊 Limites observées

| Provider | Rate limit | Limite contexte |
|----------|-----------|-----------------|
| Gemini free tier | ~15 req/min, ~1M tokens/jour | 1M tokens (Pro), 128K (Flash) |
| OpenRouter free | "few requests/min" partagé entre tous les `:free` | varie par modèle |
| Ollama local | Limité par GPU/CPU | 32K (qwen2.5), 128K (qwen2.5-1m) |

## 🐛 Cas observés

### `forge_litellm_connector.py` Gemini erreur silencieuse
`'NoneType' object has no attribute 'strip'` → quand Gemini retourne 503, le
connector ne gère pas le None et fallback Ollama. **À fixer** plus tard.

### Fix `api_base` provider-aware (commit `b03348b`)
Avant : `api_base=localhost:11434` était passé à TOUS les providers → 404 cloud.
Après : seulement passé pour `ollama/lm_studio/vllm/litellm`.

### Doublon `OPENROUTEUR` / `OPENROUTER`
Orthographe historique `OPENROUTEUR` conservée pour compat. Préférer
`OPENROUTER_API_KEY` pour les nouveaux usages.

## 🔗 Liens

- OpenRouter free models : https://openrouter.ai/models?fmt=cards&supported_parameters=tools&order=newest&context_length=131000&pricing=0
- Google AI Studio (Gemini) : https://aistudio.google.com/
- LiteLLM providers : https://docs.litellm.ai/docs/providers
