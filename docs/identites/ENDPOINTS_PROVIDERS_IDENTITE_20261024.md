# ENDPOINTS PROVIDERS IDENTITE - 2026-10-24

**Objectif (ordre owner 24/10)** : chaque endpoint via les providers devrait aussi porter son identité en plus de sa méthode de routage.  
**Cadre** : `docs/INTEROCEPTION_ENDPOINTS_PLAN.md` (« principal, rôle et route provider sont des axes distincts »)  
**Travail dans** : `nokido_worktrees/opencode_gptoss` (chemins relatifs pour le code)  
**Journaux vivants** : `%NOKIDO_ROOT%/logs/` (aucun fichier `*provider*/*ask*/*token*/*hub*` trouvé à l'instant de la sonde)

## 1) Registres de endpoints / providers joignables

- **Proxy / Registre exécutables** : `app/forge_agent_proxy.py` (`_PROVIDERS`, `get_provider`, `list_providers`, `fournisseurs_joignables`, `refresh_openrouter_free_slugs`). 
- **Routeur** : `app/forge_llm_router.py` (`PROVIDERS` avec slots, `USE_CASE_CHAINS`, `chaine_active`, `LLMRouter.call/call_cascade`, circuit-breaker, trust-score). 
- **Alias / mapping** : `app/forge_provider_alias.py` (mappe noms hub -> noms exécutables `ask()` ; `CLEF_REFUSEE`, `SANS_SOLDE`, `RETIRES`, `NOMS_TROMPEURS`). 
- **Passerelle ask** : `tools/nokido_hub.py` (endpoints HTTP/MCP, notamment `tools/call` avec `name:"ask"` visible dans code). 

**≈45 providers mentionnés dans la consigne / observés** : `cerebras`, `docker`, `glm`, `llamacpp`, `lmstudio`, `mistral_free`, `nvidia_nim`, `ollama`, `openrouter_free`, `sambanova`, `together_ai`, `groq`, `gemini` (+ variants: `gemini_flash_lite`, `gemini_gemma`, `gemini_cli`, `claude_*`, `xai/grok`, `hf`, `cohere`, `perplexity`, `mistral`, `openai`, `deepseek`, `pollinations`, `zai_*`, `parallax`, `llamaedge`, `wasm`, `nervous`, `swarm`, `agent`, `router`, `router_local`, `copilot_cli`, `codex_cli`).

## 2) Ce qui est enregistré AUJOURD'HUI (champ + source)

| Couche | Champs enregistrés | Source (fichier:ligne) | Remarques |
|---|---|---|---|
| **Contexte acteur/trace** | `trace_id` (ContextVar), `actor` {agent, principal, declared, ring, channel, transport, machine} via `set_actor/get_actor`, propagation headers/env/payload (`X-Agent-Name`, `X-Channel`, `X-Transport`, `LAFORGE_AGENT/CHANNEL/TRANSPORT/RING`) | `app/forge_trace_context.py:1-282` | Ne propage pas forcément aux frontières processus (ZMQ/subprocess/HTTP/cloud) sans sérialisation explicite. |
| **Appel provider (proxy)** | `provider.name`, `provider.model`, latence (`t0->end`), tokens (`_record_provider_call` utilise `count_text_tokens` + usage API si présent), `measurement_kind` (`REPORTED` si usage API dispo, sinon `ESTIMATED`), `measurement_source`, `cache_read/write`, `served_model`, `attempts` (depuis routeur), attribution agent via `get_actor()` (`actual_agent/principal/declared`) | `app/forge_agent_proxy.py:438-570` (usage ContextVar `_USAGE_RAPPORTE`, `_record_provider_call`, `_rendre_reponse`, `_noter_usage_rapporte`, `_noter_routage`) | `ask_tracked` enregistre via `forge_token_monitor.log_call`. Provider/model **effectivement utilisés** capturés; clé/compte **nom** seulement (jamais valeur) via env/key names. |
| **Routeur** | `provider` (slot), `model` demandé/servi (`_modele_servi` lit `resp.model`), `latency`/TTFT, `attempts`, cascade, circuit-breaker/cooldown, capacité observée, trust-score | `app/forge_llm_router.py:1034-2095` (notamment `call_cascade`, `_modele_servi`, `_noter_ttft`, `_capter_capacite`) | Distingue `requested_model` vs `served_model`. `usage` capturé si dispo. |
| **Monitoring tokens/coûts** | `agent_id`, `provider`, `model`, `prompt_tokens`, `completion_tokens`, `total_tokens`, `cost_usd` (ou `None` si inconnu/prix absent), `latency_ms`, `source`, `session_id`, `meta` (+colonnes enrichies: cache/reasoning/provenance/execution_mode/transport/execution_id/parent/measurement_kind/measurement_source/cost_kind/cost_source/writer_component/served_model/attempts/principal/declared), alerte réseau si seuil franchi | `app/forge_token_monitor.py:1-691` (`log_call`, `migrer`, `DB` via `journal_path`, pricing tables) | **Coûts** : `None` si inconnu (ne force pas 0). Gratuit prouvé uniquement pour providers locaux marqués (`PROVIDERS_GRATUITS`). Clé/compte non loggés. |
| **Traçage HTTP/MCP hub** | Trace HTTP/span, agent/ring depuis headers/ActorContext, statut/durée | `tools/nokido_hub.py` (middleware/gestionnaire `ask`/`tools/call`) + `forge_trace_context` | Trace HTTP peut exister sans être jointe systématiquement à `token_usage` (constaté dans plan). |
| **Quotas/capacité** | Headers ratelimit capturés, `forge_quota_tracker` (état capacité observée) | `app/forge_llm_router.py:1060-1098`, `app/forge_quota_tracker` (référencé) | Local/cloud distingué via `cost_tier`/provider type. |

**Ce qui manque à joindre systématiquement** : `trace_id/span_id` vers l'enregistrement `token_usage` (la ligne d'usage ne reprend pas toujours le trace/span HTTP), distinction `master/delegation` (sujet vs acteur), snapshot physiologique/état régulation au moment de l'appel, verdict `should_throttle/FlowRegulator` et effet appliqué, **identité explicite du compte/clé** (seul le **nom** de la clé/env est connu, jamais la valeur).

## 3) Verdict par endpoint (IDENTIFIÉ / ROUTAGE SEUL / ANONYME / UNKNOWN)

| Famille / Exemples | Verdict | Preuve / Pourquoi |
|---|---|---|
| **Locaux**: `ollama`, `ollama_local`, `llamacpp`, `llamacpp_local`, `lmstudio`, `lmstudio_native`, `docker`, `docker_local`, `llamaedge`, `parallax` | **ROUTAGE SEUL** (majoritairement) | Identifiés via slot/routeur + `ask_tracked` (provider/model), actor/trace parfois présents. Pas d'API key cloud nommée; `cost_tier` local. Mais **compte/clé compte** souvent absent, et corrélation trace↔usage pas systématique. |
| **Gratuits cloud**: `groq`, `gemini`/`gemini_flash_lite`, `openrouter_free`, `nvidia_nim`, `sambanova`, `cerebras`, `together_ai` (si joignable), `hf` | **ROUTAGE SEUL** | Provider/model/route enregistrés; `measurement_kind` peut être `REPORTED`/`ESTIMATED`. **Clé nom** connu (`*_API_KEY`), mais **identité compte/offre** (free vs paid tier effectif) pas toujours explicite dans la ligne d'usage. Confusions possibles entre slots/aliases. |
| **OAuth CLI**: `gemini_cli`, `claude_cli`, `claude_agent_sdk`, `copilot_cli`, `codex_cli` | **ROUTAGE SEUL** | Routed via proxy/CLI; `cost_tier` 0 (subscription) marqué. Actor/trace possibles. **Identité de l'abonnement/compte** pas systématiquement jointe à `token_usage`. |
| **Router/meta**: `router`, `router_local`, `swarm`, `agent`, `nervous`, `wasm` | **ROUTAGE SEUL** | Meta-providers; `RouterCascadeProvider` pose `served_model`/`attempts` dans tiroir usage. L'**endpoint effectif final** peut être perdu si non propagé. |
| **Retirés/refusés**: `gpt4o_github`, `github_*` (marqués `RETIRES`/`perime`), `together_ai`/`grok` dans certains états (`CLEF_REFUSEE`), `zai_glm5_2` sous `SANS_SOLDE` | **UNKNOWN** / **ROUTAGE SEUL** | Alias refusés ou slots périmés; `forge_provider_alias` explique raison, mais pas forcément journalisé comme « endpoint identité » dans trace unifiée. |

**Confusions signalées** :
- **Même hôte/offre différente** : ex. `ollama` local vs `ollama_mimo_v2` (différents slots/modèles, disponibilité différente; `mimo_v2` marqué deprecated). 
- **Aliases ambigus** : `gemini_flash` vs `gemini_flash_lite` (hub slot vs executable) - `NOMS_TROMPEURS` signale que nom promet plus que servi; `forge_provider_alias` refuse résolution infidèle. 
- **Mistral**: `mistral` (large) vs `mistral_free` (nemo) selon abonnement/tier effectif (`SANS_SOLDE` pour certain slot). 
- **GitHub Models** retiré mais encore présent dans configs historiques. 

## 4) Schéma minimal « passeport d'endpoint » (réutiliser existant, sans nouveau module)

Proposition à ajouter à **chaque appel provider** (à poser dans le même tiroir/ligne d'usage, réutilisant `set_actor` + journaux `token_usage`), sans créer de module dédié.

```json
{
  "endpoint_passport": {
    "trace_id": "<string|UNKNOWN>",
    "span_id": "<string|UNKNOWN>",
    "execution_id": "<string|UNKNOWN>",
    "parent_execution_id": "<string|UNKNOWN>",
    "principal": { "id": "<resolved|UNKNOWN>", "ring": "<int|UNKNOWN>", "declared": "<string|UNKNOWN>" },
    "actor": { "agent": "<string>", "channel": "<string>", "transport": "<string>", "machine": "<string>" },
    "route": {
      "method": "direct|router|swarm|cascade|proxy|route_task",
      "chain": ["<slot1>", "..."],
      "attempts": <int|UNKNOWN>,
      "selected_by": "trust_score|dt|force_local|fallback|explicit"
    },
    "endpoint": {
      "provider_id": "<forge_agent_proxy name>",
      "slot_id": "<forge_llm_router slot>",
      "model_requested": "<string>",
      "model_served": "<string|UNKNOWN>",
      "base_url": "<string|UNKNOWN>",
      "host": "<string|UNKNOWN>",
      "api_key_name": "<ENV_NAME|local|UNKNOWN>",
      "account_id": "<string|UNKNOWN>",
      "offer": "free|paid|subscription|local|unknown",
      "locality": "local|cloud|unknown"
    },
    "measurement": {
      "kind": "REPORTED|ESTIMATED|UNKNOWN",
      "source": "<string>",
      "latency_ms": <float|UNKNOWN>,
      "tokens": { "prompt": <int|null>, "completion": <int|null>, "total": <int|null>, "cache_read": <int|null> },
      "cost_usd": <float|null>,
      "cost_kind": "KNOWN|FREE|UNKNOWN_PRICING"
    },
    "regulation": {
      "throttle_verdict": "allow|throttle|refuse|UNKNOWN",
      "hormones_active": ["<name>"],
      "snapshot_age_ms": <int|UNKNOWN>,
      "effect_applied": "none|defer|limit|refuse|reroute|UNKNOWN"
    }
  }
}
```

**Points d'injection (réutiliser existant)**:
- `app/forge_trace_context.py`: `get_trace_id()`, `get_actor()` déjà présents. Étendre pour porter `span_id/execution_id`.
- `app/forge_agent_proxy.py`: `_USAGE_RAPPORTE` (ContextVar) + `_record_provider_call` + `_noter_routage` déjà posent `served_model/attempts/measurement_kind`. Y ajouter `endpoint_passport` (ou champs aplatis).
- `app/forge_token_monitor.py`: `log_call` accepte déjà beaucoup de champs enrichis (`served_model`, `attempts`, `principal`, `declared`, `measurement_kind`, `measurement_source`, `provenance`, `execution_mode`, `transport`). Étendre schéma avec `trace_id/span_id/route_method/endpoint_id/base_url/host/api_key_name/account_id/offer/locality/regulation_*` si manquants (migration idempotente via `migrer`).
- `app/forge_llm_router.py`: déjà capture `requested_model` vs `served_model`, capacité, régulation (cortisol) - exposer effet appliqué.

**Règles**: jamais de valeur de clé/secret; `UNKNOWN` si non exposé; distinguer `principal` vs `actor` (délégation); ne pas inférer fatigue; joindre trace/span à la ligne d'usage.