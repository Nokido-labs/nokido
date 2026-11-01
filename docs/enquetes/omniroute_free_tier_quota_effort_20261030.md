# Enquête Comparative OmniRoute vs Nokido : Découverte Free-Tier, Quotas, Effort et Évitement d'Échecs

*Date de l'enquête : 30 octobre 2026*  
*Auteur : Agent ANTIGRAVITY (`agt_antigravity`)*  
*Contexte : Analyse d'architecture suite à l'ingestion de veille OmniRoute (`gitingest/omniroute`, `github:cheaper-inference/OmniRoute/...`)*

---

## 1. Découverte des Free Tiers et des Modèles par Fournisseur

### OmniRoute
* **Fichiers & fonctions :**
  * `src/app/api/providers/[id]/models/route.ts` (`GET /api/providers/[id]/models`)
  * `src/app/api/providers/[id]/models/discovery/helpers.ts` (`mergeLocalCatalogModels`, `mergeSpecialtyCatalogIntoLiveModels`, `enrichOllamaLocalModels`)
  * `src/app/api/providers/[id]/models/discovery/normalizers.ts` (`fetchAntigravityDiscoveryModelsCached`, `normalizeOpenAiLikeModelsResponse`, `normalizeDataRobotCatalogResponse`)
  * `src/app/api/providers/[id]/models/discoveryConfig.ts` (`parseRegistryModelsResponse`)
  * `@omniroute/open-sse/services/alibabaFreeTier.ts` (`shouldUseLiveAlibabaFreeModelDiscovery`)
* **Mécanisme :**
  OmniRoute sépare la configuration statique (registre de 60+ fournisseurs) et la découverte dynamique live. Il interroge les endpoints en amont via `safeOutboundFetch` (protégé contre SSRF par `outboundUrlGuard`), normalise les payloads hétérogènes (OpenAI standard, Ollama `/api/tags`, Claude, Antigravity, SAP, DataRobot) dans une structure de catalogue unifiée, puis fusionne les modèles détectés avec des catalogues spécialisés et des filtres spécifiques (ex: `shouldUseLiveAlibabaFreeModelDiscovery` pour isoler les free tiers Dashscope/Alibaba).
* **Équivalent Nokido :**
  * `tools/forge_free_tier_census.py` : fonctions `catalogue(base, cle)`, `_lire_catalogue`, `est_gratuit(modele, etiquette)`
  * `tools/forge_provider_catalogue.py` : fonctions `interroger(url, cle)`, `modeles_cables()`, `candidates_du_clair(etiquette, env_key)`
* **Écart d'architecture :**
  * *OmniRoute* gère une normalisation multi-formats en temps réel par provider avec cache de découverte, support natif de formats propriétaires variés (OpenAI, Anthropic, Ollama, Google/Antigravity, etc.) et détection heuristique/flags des tiers gratuits par provider node.
  * *Nokido* dispose d'une logique batch/census (`catalogue` interroge `{base}/models` au format OpenAI-compatible strict). La gratuité est évaluée dans `est_gratuit()` uniquement sur le suffixe `:free`, sur `pricing.prompt == 0.0 && pricing.completion == 0.0`, ou sur le tag local (`ollama`, `lmstudio`, `litellm`). Les fournisseurs avec des conventions de découverte tierces (ex: headers de quotas ou endpoints d'inventaire non standard) ne sont pas normalisés dynamiquement.

---

## 2. Connaissance et Suivi des Quotas

### OmniRoute
* **Fichiers & fonctions :**
  * Migration DB : `src/app/api/db/migrations/013_quota_snapshots.sql` (table `quota_snapshots`)
  * `src/app/(dashboard)/dashboard/analytics/ComboHealthTab.tsx` (suivi `target.quota.risk`, `projectedRemainingPct`, `forecast`)
  * `@omniroute/open-sse/services/crof-usage-fetcher.ts` & `copilot-usage.ts`
  * Dashboard & MCP tool : `omniroute_check_quota`
* **Mécanisme :**
  OmniRoute enregistre dans SQLite des snapshots réguliers (`quota_snapshots.sql`) combinant deux sources : l'interrogation active des API de compte (ex: API quota Antigravity, token GitHub Copilot usage, API usage Claude admin) et la capture passive des en-têtes HTTP de réponse (`x-ratelimit-remaining-*`, `x-ratelimit-reset-*`, `Retry-After`). Il calcule un pourcentage d'épuisement, un niveau de risque (`target.quota.risk`) et une projection de coût/consommation dans le temps pour alerter et dérouter le trafic avant rupture.
* **Équivalent Nokido :**
  * `app/forge_quota_tracker.py` : fonctions `record_response_headers(provider, headers)`, `record_429(provider, retry_after)`, `capacite_observee(provider, maintenant)`
  * `app/forge_provider_quota.py` : fonctions `quota_status(provider)`, `should_skip(provider, threshold)`, `estimate_remaining_calls(provider)`
  * `tools/forge_free_tier_census.py` : `consigner_quota_epuise`, `echeance_quota`, `quota_epuise_actif`
* **Écart d'architecture :**
  * *OmniRoute* persiste des snapshots historiques d'utilisation (`quota_snapshots`), supporte des pollers de quotas spécialisés (Copilot, Anthropic, etc.) et calcule un taux de risque projeté intégré directement dans le sélecteur de combos (évitement prédictif avant 100%).
  * *Nokido* dispose d'un suivi très granulaire par fichiers JSON dans `capacite_observee` (`FRAICHE`, `PERIMEE`, `INCONNU` avec gestion des fenêtres de reset temporelles) et en SQLite (`forge_provider_quota` basé sur `usage_this_month` vs `monthly_quota`), mais les modules sont segmentés : `forge_quota_tracker` stocke en mémoire et en fichiers `capacity/`, `forge_provider_quota` calcule en SQL local sur `call_logs`, et `forge_free_tier_census` écrit des dates d'échéance dans `free_tier_census.json`. Le seuil de skip (`should_skip`) est souvent binaire (seuil 1.0 par défaut).

---

## 3. Choix de l'Effort et Reasoning par Modèle

### OmniRoute
* **Fichiers & fonctions :**
  * `src/shared/reasoning/codexEfforts.ts` (`getCodexWireEfforts`, `readCodexReasoningMetadata`)
  * `@omniroute/open-sse/services/learnedReasoningEffortCaps.ts` (`getLearnedReasoningEffortForModel`)
  * `@omniroute/open-sse/utils/syncedEffortVariants.ts` (`isSkippedEffortProvider`)
  * `@omniroute/open-sse/config/providerRegistry.ts` (`getRegistryModelThinkingEfforts`, `getRegistryThinkingEfforts`)
* **Mécanisme :**
  OmniRoute maintient une matrice des efforts de raisonnement supportés par modèle (`low`, `medium`, `high`, `xhigh`). Il lit les métadonnées déclarées par l'amont (ou découvertes via les API de catalogue), apprend les plafonds effectifs (`learnedReasoningEffortCaps`) pour ne pas soumettre un effort non toléré, injecte le bon paramètre filaire selon la cible (`model_reasoning_effort`, `thinking: { budget_tokens }` pour Anthropic/GLM, etc.), et génère si besoin des alias/variantes synthétiques sans polluer l'effort filaire direct.
* **Équivalent Nokido :**
  * `tools/forge_palier_effort.py` : fonction `resoudre(surface, taille, effort, escalade, census)`
  * `tools/forge_free_tier_census.py` : fonction `parametre_effort(fournisseur, surface)`
* **Écart d'architecture :**
  * *OmniRoute* gère dynamiquement et par modèle les paliers de raisonnement avec un mécanisme d'apprentissage (`learnedReasoningEffortCaps`) et d'adaptation selon le dialecte du fournisseur (`reasoning_effort` vs `budget_tokens` vs suffixes spécifiques).
  * *Nokido* repose sur une table rigide par surface CLI (`TABLE[surface][taille]` dans `forge_palier_effort.py`), conditionne l'accès aux efforts élevés (`EFFORTS_HAUTS`) à une justification d'escalade formelle (`ESCALADES`), et filtre de façon statique les fournisseurs dans `FOURNISSEURS_REASONING_EFFORT`. Si le modèle est marqué à 0 req/min dans le census, il lève `ModeleHorsQuota`.

---

## 4. Évitement des Appels Voués à l'Échec

### OmniRoute
* **Fichiers & fonctions :**
  * `src/shared/network/safeOutboundFetch.ts` (retries exponentiels avec gestion de cooldown et SSRF guard)
  * Cooldown-aware retry (v3.6.6+) : capture `x-ratelimit-reset-requests`, `x-ratelimit-reset-tokens`, `Retry-After` avec délai max `MAX_RETRY_INTERVAL_SEC` (défaut 30s)
  * Pipeline proxy / SSE : Circuit breaker (`ProviderHealthMatrixCard.tsx`, états `CLOSED`, `OPEN`, `HALF_OPEN`), rate limiter par compte, anti-thundering herd avec verrou mutex, fallback de combos (stratégies Least-Used, Cost-Optimized, Fallback Policy).
* **Mécanisme :**
  OmniRoute combine trois verrous :
  1. *Circuit Breaker & Health Check* : met en quarantaine (`OPEN`) un provider après N erreurs consécutives ou latence anormale ;
  2. *Cooldown-Aware Retry* : suspend temporairement le routage sur un modèle spécifique si un 429 est reçu avec un header de reset court (<30s) et retente automatiquement ;
  3. *Combo Fallback Routing* : bascule instantanément vers le modèle suivant de la chaîne configurée (ex: Tier 1 Subscriptions -> Tier 2 API Keys -> Tier 3 Cheap -> Tier 4 Free) sans propager l'erreur au client.
* **Équivalent Nokido :**
  * `tools/forge_provider_catalogue.py` : fonctions `classer_reponse(code, detail)`, `geler_voie(voie, code, detail, now)`
  * `tools/forge_free_tier_census.py` : fonctions `consigner_quota_epuise`, `echeance_quota`, `quota_epuise_actif`
  * `app/forge_provider_quota.py` : fonctions `should_skip(provider, threshold)`, `filter_chain(chain, threshold)`
* **Écart d'architecture :**
  * *OmniRoute* implémente un Circuit Breaker actif en mémoire avec état dynamique (`OPEN` / `HALF_OPEN`), retry transparent basé sur `Retry-After` au niveau réseau, et cascade ordonnée multi-tiers automatique.
  * *Nokido* dispose de la classification sémantique fine des erreurs (`SANS_SOLDE`, `HORS_PALIER`, `QUOTA_EPUISE`, `DEBIT`, `CLEF_REFUSEE`, `MODELE_ABSENT` dans `classer_reponse`), gèle la voie (`geler_voie`) et consigne l'échéance dans le census (`consigner_quota_epuise`). Cependant, au moment de l'exécution (`should_skip` / `filter_chain`), la décision dépend d'un ratio de quota mensuel ou d'un check statique, sans boucle de retry à cooldown immédiat ni circuit breaker formel unifié à 3 états dans le hub.

---

## 5. Plan de Tâches S (Par Gain Décroissant)

L'objectif prioritaire est de **supprimer immédiatement les interrogations vouées à l'échec** (429 connus, clé absente, quota journalier/mensuel épuisé, modèle absent ou hors palier).

### Tâche S1 : Court-circuit immédiat sur Voie Gelée / Quota Actif dans le Routeur Cognitive / Hub
* **Fichiers :** `app/forge_cognitive_router.py` (ou `app/forge_cascade.py`) & `app/forge_provider_quota.py` (`should_skip`)
* **Fonction à modifier / ajouter :** `est_voie_bloquee(provider, model) -> tuple[bool, str]`
* **Mécanisme :**
  Consulter avant tout appel réseau la combinaison :
  1. Clé d'API absente ou vide dans l'environnement / coffre ;
  2. Statut dans `free_tier_census.json` (`quota_epuise_jusqu_a > now` via `quota_epuise_actif`) ;
  3. Voie marquée `CLEF_REFUSEE`, `SANS_SOLDE` ou `MODELE_ABSENT` dans la matrice du catalogue (`forge_provider_catalogue.py`).
  Si bloqué, court-circuiter immédiatement sans émettre de requête réseau.
* **Test NR associé :** `tests/nr/test_court_circuit_voie_bloquee_nr.py`
  * Vérifier qu'un provider avec quota expiré dans 300s est rejeté en 0ms avec motif explicite.
  * Vérifier qu'un provider sans clé API ne tente aucune connexion HTTP.

### Tâche S2 : Intercepteur Cooldown-Aware sur 429 et En-têtes Rate-Limit
* **Fichiers :** `app/forge_quota_tracker.py` & `tools/forge_provider_catalogue.py`
* **Fonction à modifier / ajouter :** `forge_quota_tracker.enregistrer_cooldown(provider, retry_after, reset_time)` et intégration dans `record_response_headers`.
* **Mécanisme :**
  À la réception d'un code 429 ou d'en-têtes `Retry-After` / `x-ratelimit-reset-*`, extraire précisément la durée de cooldown en secondes. Si `retry_after <= 30s`, positionner un verrou de cooldown court en mémoire ; si `retry_after > 30s` (ex: quota journalier), basculer en `QUOTA_EPUISE` avec `echeance_quota`.
* **Test NR associé :** `tests/nr/test_cooldown_aware_rate_limit_nr.py`
  * Valider l'extraction de `Retry-After` (format entier ou date HTTP) et la mise en pause temporaire de la cible.
  * Vérifier la reprise automatique une fois le cooldown écoulé sans redémarrage.

### Tâche S3 : Circuit Breaker Léger à Trois États (`CLOSED`, `OPEN`, `HALF_OPEN`)
* **Fichiers :** `app/forge_circuit_breaker.py` (ou extension dans `app/forge_quota_tracker.py`)
* **Fonction à créer :** `class ProviderCircuitBreaker: verifier(provider), signaler_succes(provider), signaler_echec(provider, err)`
* **Mécanisme :**
  Après 3 échecs consécutifs (5xx, timeouts réseau, 401/403 répétés), le circuit passe en `OPEN` pour 60 secondes (évite le matraquage inutile). À l'expiration, passage en `HALF_OPEN` permettant une seule requête sonde. En cas de succès, retour à `CLOSED` ; en cas d'échec, retour à `OPEN`.
* **Test NR associé :** `tests/nr/test_circuit_breaker_provider_nr.py`
  * Simuler 3 erreurs consécutives et vérifier que le 4e appel est bloqué immédiatement avec `CircuitBreakerOpenException`.
  * Simuler l'expiration de la fenêtre et la transition `HALF_OPEN -> CLOSED` sur succès.

### Tâche S4 : Normalisation Dynamique du Plafond d'Effort (`ReasoningCaps`)
* **Fichiers :** `tools/forge_palier_effort.py` & `tools/forge_free_tier_census.py`
* **Fonction à modifier :** `resoudre()` et `parametre_effort()`
* **Mécanisme :**
  Intégrer les métadonnées de modèles découvertes (catalogue) pour borner automatiquement l'effort au maximum supporté par le modèle (ex: replier silencieusement un `high` non supporté sur `medium` au lieu d'échouer avec une erreur 400 Bad Request d'OpenAI/Anthropic).
* **Test NR associé :** `tests/nr/test_palier_effort_clamping_nr.py`
  * Tester qu'un modèle ne supportant que `low`/`medium` appelé avec `high` est ajusté à `medium` avec avertissement sans casser l'appel amont.
