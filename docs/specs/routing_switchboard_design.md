# Routing « Switchboard » — chaînon manquant + dedup LiteLLM Router

<!-- ports-arretes -->
> ⚠️ **Ports arrêtés cités dans cette page** (note ajoutée le 2026-08-30 ; le corps ci-dessous n'a pas été réécrit) :
>
> - `NokidoLlamaReranker :8100` est **arrete depuis le 2026-08-10** (boot-trim RAM) — le rerank passe alors par son repli (Cohere `/v2/rerank`, puis lexical).


> Design 2026-06-08. Réponse à : routage intelligent d'agents spécialisés à travers
> les LLM joignables (style Hermes / semantic-router / RouteLLM / Contract-Net).
> Principe : DÉDUPLICATION de l'existant, pas de réinvention.

## 0. Anti-dup — ce qui EXISTE déjà (ne pas recréer)

**Registre de capacités = DÉJÀ là, en 3 vues :**
- `app/forge_provider_specs.py` : `PROVIDER_SPECS` (~40 providers × tier/cost/context/
  **capabilities**), `USE_CASE_SPECIALIZATIONS` (use_case→required/preferred caps),
  `matches_use_case()`, `list_providers_for_use_case(uc, free_only)`, `monthly_quota()`.
- `app/forge_edge_fleet.py` : nœuds distribués `register_edge(name,url,capabilities,
  metrics)` + `list_edges()` (ram_free_mb, cpu_pct, models_loaded). = registre Contract-Net.
- `app/forge_handoff.py` : `Agent.capabilities: list[str]` + pool filtré ("fast"/"code"/
  "reasoning") = dispatch capacité local.

**Routage = DÉJÀ ~7 couches :** `forge_llm_router.call_cascade`+`USE_CASE_CHAINS`,
`forge_dt_router.dt_route`+`route_with_dt` (APPRIS), `forge_spike_router` (SNN),
`forge_cognitive_router`, `forge_nlu` (NaiveBayes thalamus), `forge_metacognition_gate`
(spin-flip tier 0→3 = RouteLLM-like), `forge_host_capabilities.can_run_locally` (VRAM).

**Embeddings = DÉJÀ là :** bge-m3 :8099 + rerank :8100 (`_rag_dense_search`).

**Transport :** PAS de NATS (grep 0). Bus réels = `forge_swarm_bus`, ZMQ, Deno :7401, hub HTTP.

## 1. Le vrai chaînon manquant (2 pièces)

### A. Route-table sémantique (bge-m3) — text → use_case
Aujourd'hui le `use_case` est deviné (keyword/NLU/explicite). Manque : router par
**centroïdes d'embeddings** (le cœur de semantic-router, mais SANS la dép Aurelio).

NOUVEAU `app/forge_semantic_route.py` (~40 lignes) :
- centroïdes = moyenne bge-m3 de phrases-types par use_case (clés de
  `USE_CASE_SPECIALIZATIONS`), calculés 1× et cachés (sandbox/route_centroids.npz).
- `semantic_route(text) -> (use_case, score)` : embed via bge-m3 :8099 (réutilise le
  client de `_rag_dense_search`), cosine vs centroïdes, argmax. Seuil → fallback "general".
- branché dans `call_cascade` : si `use_case` non fourni explicitement, `use_case =
  semantic_route(prompt)[0]`. Latence ~ms (1 embed local), zéro LLM de routage.

### B. Adoption `litellm.Router` (dedup du for-loop manuel)
`call_cascade` réimplémente à la main : itération slots, cooldown, rate-limit 429,
record_failure, fallback. `litellm.Router` fait TOUT nativement.

NOUVEAU `app/forge_litellm_router.py` (façade) :
- `build_router(use_case)` génère le `model_list` litellm DEPUIS `PROVIDER_SPECS`
  (capabilities) + `forge_llm_router.PROVIDERS` (model id litellm + base_url + key) :
  ```
  model_list = [{
    "model_name": use_case,                      # groupe = use_case
    "litellm_params": {"model": <litellm_id>, "api_base":..., "api_key":...,
                       "rpm": daily_calls/1440, "tpm":...},
    "model_info": {"caps": spec["capabilities"], "tier": spec["tier"]},
  } for provider in filtered_chain]
  ```
- `Router(model_list, routing_strategy="latency-based-routing",
          fallbacks=[{use_case: chain[1:]}], cooldown_time=60, allowed_fails=1,
          num_retries=0)`.
- singleton par use_case, cache.

## 2. Dedup map — call_cascade manuel → LiteLLM Router natif

| Logique manuelle call_cascade | Remplacée par Router natif |
|---|---|
| `for slot_name in chain[:max_attempts]` | `model_list` + `fallbacks` |
| `slot.record_failure()` / `_cooldown` | `cooldown_time` + `allowed_fails` |
| `if 429: slot.record_rate_limit(60)` | RPM/cooldown auto + `num_retries` |
| sélection slot "is_available" | `routing_strategy` (latency/usage-based) |
| `record_call()` RPM manuel | `rpm`/`tpm` dans litellm_params |

| Logique Nokido À GARDER (wrap autour du Router) | Pourquoi |
|---|---|
| firewall `pre_flight` (DLP/injection→local) | sécu souveraine |
| persona inject (`nokido_system`, AXE 8) | identité unifiée |
| `is_dead_end` (motivation) | apprentissage échec |
| `forge_provider_quota.filter_chain` | quota subscription |
| `can_run_locally` (VRAM/host) | éviter OOM local |
| endocrine `CORTISOL_QUOTA_CLOUD`→local-only | coût |
| `route_with_dt` (préférence APPRISE) re-ordonne chain | mieux que latency statique |
| `forge_secret_guard.scan_outbound` | DLP sortant |
| low-confidence escalade (refus→tier fort) | qualité |

→ Architecture cible : **les pré-filtres Nokido produisent une `chain` ; cette chain
alimente un `litellm.Router` qui gère l'exécution (cooldown/latency/fallback natifs).**
On supprime ~100 lignes de retry/cooldown manuels, on garde toute la souveraineté.

## 3. Façade registre unifié (dedup des 3 vues)

NOUVEAU `app/forge_capability_registry.py` (mince, agrège — ne stocke pas) :
- `capabilities_of(provider) -> list[str]` → `forge_provider_specs.get_spec`
- `providers_for(use_case, free_only, reachable_only) -> list[str]` →
  `list_providers_for_use_case` ∩ providers réellement joignables (slots is_available)
  ∪ `forge_edge_fleet.list_edges()` (nœuds distants avec models_loaded matchant)
- `local_agents_for(capability) -> list[Agent]` → `forge_handoff` pool filtré
- 1 seule porte d'entrée pour router central ET (futur) Contract-Net.

## 4. Plan d'implémentation (TDD, PRs atomiques)

1. **PR-A semantic route** : `forge_semantic_route.py` + centroïdes cache + test
   (route "fix ce bug python"→code, "lis cette image"→vision). Branché opt-in dans
   call_cascade (param `auto_use_case=True`). Dép : aucune.
2. **PR-B capability registry façade** : `forge_capability_registry.py` + test
   (providers_for("vision") ⊃ gemini_flash, exclut groq). Dép : aucune.
3. **PR-C litellm.Router façade** : `forge_litellm_router.py` build_router from specs +
   test (model_list généré, fallbacks). Dép : PR-B.
4. **PR-D dedup call_cascade** : remplacer le for-loop d'exécution par le Router
   (garder TOUS les pré-filtres §2). Le plus sensible → TDD lourd + flag
   `FORGE_USE_LITELLM_ROUTER` (rollback instantané). Dép : PR-C.

## 5. Risques & rollback
- call_cascade = chemin critique (appelé partout). PR-D derrière flag env, rollback 1 var.
- litellm.Router cooldown ≠ sémantique Nokido slot — mapper précisément (allowed_fails=1).
- route_with_dt (appris) doit primer sur routing_strategy statique → l'appliquer en
  ré-ordonnant la chain AVANT de la passer au Router.
- semantic_route seuil trop bas → mauvais use_case ; garder fallback "general" + le
  metacognition tier rattrape.

## 5.bis Décisions 2026-06-08
- **PR-D (dedup litellm.Router dans call_cascade) : ABANDONNÉ.** for-loop manuel conservé
  (fonctionne, chemin critique appelé partout). Façades A/B/C dispo pour usage ponctuel.
- **Auto use_case (semantic_route dans call_cascade) : EN DÉBAT** (cf. §5.ter).

## 5.ter Implications « auto use_case » — dossier de débat (multi-LLM)

Question : faut-il que `call_cascade` déduise le use_case via `semantic_route` (bge-m3)
au lieu du keyword/NLU/explicite actuel ?

**Pour :** intent réel → bon use_case → bonne chain capacités ; local, ~ms, pas de LLM
de routage ; supprime le guessing keyword.

**Contre / risques :**
1. Latence chemin chaud : +1 appel embed :8099 à CHAQUE décision de routage. Si :8099
   down → nouvelle surface d'échec (mitigé : fallback "general", mais dégradé silencieux).
2. Qualité centroïdes : phrases-seed écrites à la main → misroute si non représentatives.
3. Routeurs concurrents : on a DÉJÀ route_with_dt (appris, provider), spike_router, nlu.
   semantic_route = 4e décideur (use_case). Précédence à définir explicitement.
4. Seuil 0.35 arbitraire : trop haut = tout "general" (zéro spécialisation) ; trop bas =
   misroute confiant.
5. Déterminisme : cosine déterministe OK, mais drift si phrases-seed changent.

**Questions à trancher (débat) :**
- Q1 Détection use_case : sémantique (bge-m3) vs keyword/NLU vs HYBRIDE (semantic si
  confiance haute, sinon keyword) ?
- Q2 Précédence des routeurs : semantic_route (use_case) → route_with_dt (provider) →
  metacognition (tier). Cet ordre est-il correct ? Qui peut overrider qui ?
- Q3 Budget latence : 1 embed/décision acceptable, ou seulement si use_case ambigu
  (ex : appeler semantic_route uniquement quand keyword ne tranche pas) ?
- Q4 Failure :8099 down → fallback keyword (robuste) ou "general" (simple) ?
- Q5 **Gouvernance centroïdes — piste forte** : au lieu de phrases-seed manuelles,
  APPRENDRE les centroïdes depuis les `dialogue_win` taggés par use_case (lien AXE 8
  reward loop). La route-table devient auto-apprenante depuis les succès réels.
  → fusionne switchboard + persona reward. À évaluer.

## 6. Contract-Net (backlog, si multi-machines)
`forge_edge_fleet` = déjà la base (nœuds+capabilities+metrics). Bid market sur
`forge_swarm_bus`/Deno :7401 (PAS NATS). À faire SEULEMENT si fédération mini-PC réelle.
