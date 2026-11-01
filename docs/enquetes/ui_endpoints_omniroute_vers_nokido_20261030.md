# Enquête : Inspiration OmniRoute vers Nokido pour l'interface Endpoints & Fournisseurs

**Date** : 30 octobre 2026  
**Auteur** : Antigravity (`agt_antigravity`)  
**Cadre** : Convergence d'observabilité et pilotage des endpoints/fournisseurs LLM dans Nokido, inspirée de l'architecture OmniRoute, en stricte conformité avec le design system existant de Nokido (thème sombre, `nokido.css`, cartes `lf-grid` / `lf-panel`, typographie JetBrains Mono/Inter, statuts mesurés par liste blanche).

---

## 1. Contexte et Objectifs

OmniRoute propose une interface moderne de répartition de charge, d'observation des tiers (Subscription, Cheap, Free) et d'attribution dynamique de quotas d'inférence LLM multi-fournisseurs.  
Nokido dispose déjà en sous-jacent d'une infrastructure robuste (Hub `:8766`, routeur cognitif, paliers d'effort `forge_palier_effort`, recensements automatiques `free_tier_census.json`, suivi d'épuisement de quotas `quota_epuise`, base relationnelle `tasks.db` et anneaux de sécurité). Cependant, l'interface web actuelle (`app/web_hub`) expose principalement des tuiles de services d'infrastructure et des pages dédiées (RAG, Swarm, Postal, Maison, Debate, Edge), sans console unifiée d'observation et de pilotage fin des fournisseurs/modèles.

L'objectif est d'adapter les concepts clés d'OmniRoute au sein de l'interface Nokido existante, **sans altérer le style visuel** et en s'appuyant rigoureusement sur les données et doctrines souveraines de Nokido.

---

## 2. Analyse des Composants OmniRoute Retenus

Parmi la suite OmniRoute, six composants majeurs apportent une valeur immédiate :

### 1) `TierCoverageWidget`
* **Ce qu'il montre dans OmniRoute** :
  * Répartition des modèles et requêtes par catégories de coûts :
    * `tier1` : *Subscription* (abonnements / clés dédiées payantes).
    * `tier2` : *Cheap* (fournisseurs pay-per-token à faible coût : Groq, Cerebras, DeepSeek direct).
    * `tier3` : *Free* (tiers gratuits / open-source locaux / quotas quotidiens offerts).
  * Indicateur visuel de couverture (« Tier Coverage ») permettant d'identifier si les flux dérivent vers du payant ou restent couverts par du gratuit/local.
* **Données Nokido équivalentes** :
  * `sandbox/free_tier_census.json` : recensement des providers gratuits et de leur état opérationnel (Groq, SambaNova, OpenRouter free tiers, Kimi free, etc.).
  * `forge_palier_effort` : paliers d'escalade d'effort cognitif (tier 0 local/gratuit, tier 1 cloud rapide, tier 2 raisonnement lourd).
  * Base `tasks.db` / `metrics_accounting` : comptabilisation des tokens consommés par tier/provider.
* **Écran Nokido proposé** :
  * Un panneau `.lf-panel` intégré au Hub Web : **« Couverture des Paliers d'Inférence »**.
  * Affichage en trois jauges discrètes ou barre segmentée ASCII/CSS (`--bg-2`, bordures `--border`, accents Nokido vert `--green`, ambre `--amber`, violet `--purple`) :
    * **Palier 0 (Souverain / Gratuit)** : Local (Ollama) + Free-tiers valides (Groq, SambaNova).
    * **Palier 1 (Abonnements Déportés)** : OAuth CLI (Gemini Pro, Claude CLI).
    * **Palier 2 (Cloud Pay-As-You-Go)** : Clés payantes (Mistral, OpenAI, DeepSeek).
  * Badge indiquant le taux de souveraineté immédiat (% des requêtes absorbées sans surcoût).
* **Priorité** : **P1 (Haute)** — Aligné directement sur la doctrine Nokido de préservation des quotas et d'économie de tokens.

---

### 2) `ConnectionQuotaPanel` (providers/[id]/components)
* **Ce qu'il montre dans OmniRoute** :
  * Vue détaillée par fournisseur / connexion :
    * État de connexion, latence mesurée.
    * Fenêtre de quota glissante (requêtes par minute RPM, tokens par minute TPM, requêtes par jour RPD).
    * Pourcentage d'épuisement, heure estimée de reset, et seuil de saturation (circuit breaker).
* **Données Nokido équivalentes** :
  * `quota_epuise` (table / cache dynamique des blocages HTTP 429 et flags d'épuisement).
  * `forge_quota_tracker` & `hub action=quota_status` / `hub action=whoami` (pools Flash, Flash-Lite, Pro, Preview).
  * `sandbox/free_tier_census.json` (quotas journaliers connus : ex. Groq 1000 req/j, SambaNova, Cerebras).
* **Écran Nokido proposé** :
  * Vue modale ou page dédiée accessible depuis une tuile `.lf-card` : **« Détail Connexion & Quotas Fournisseur »**.
  * Tableau sobre respectant `.lf-grid` et `.lf-panel` avec police `JetBrains Mono` :
    * Colonnes : *Fournisseur*, *Modèle cible*, *Statut* (LIVE / DÉGRADÉ / ÉPUISÉ 429 / HORS LIGNE selon la doctrine 5 états de `probe_service`), *Conso estimée*, *Reset attendu (UTC)*, *Circuit Breaker*.
    * Bouton d'action sécurisé (Ring 1/2) : *Réinitialiser le verrou temporaire* ou *Bascule forcée vers repli local*.
* **Priorité** : **P1 (Haute)** — Vital pour éviter les surprises 429 lors des sprints multi-agents.

---

### 3) `ComboControlCenterClient` (combos/[id])
* **Ce qu'il montre dans OmniRoute** :
  * Gestionnaire des « Combos » : cascades de modèles ordonnées selon la tâche (ex. combo « Code », combo « Raisonnement », combo « Fast chat »).
  * Ordre de fallback prioritaire (Fallback Chain), règles de repli en cas de timeout, règles de compression contextuelle (CCR).
* **Données Nokido équivalentes** :
  * `forge_cognitive_router` / `call_cascade` : moteur de bascule dynamique d'inférence de Nokido.
  * `forge_palier_effort` : matrice d'attribution effort vs rôle agent.
  * Tables de routage et profils de swarm (`swarm_membres_vivants.json`).
* **Écran Nokido proposé** :
  * Onglet ou page : **« Cascades & Paliers Cognitifs »**.
  * Interface en blocs verticaux minimalistes listant les routes de tâches :
    * *Tâche / Profil* : Analyse de code, Synthèse RAG, Relecture de sécurité, Triage rapide.
    * *Chaîne d'exécution* : Étape 1 (Ollama local / Groq Tier-0) ➔ Étape 2 (Gemini Flash-Lite) ➔ Étape 3 (Claude/Gemini Pro).
    * Visualisation des conditions de rupture (Timeout > 2500ms, Erreur 429, Firewall sémantique rejeté).
* **Priorité** : **P2 (Moyenne)** — Simplifie grandement la configuration visuelle du routeur cognitif sans passer par l'édition de JSON.

---

### 4) `quota-share` (costs/quota-share)
* **Ce qu'il montre dans OmniRoute** :
  * Répartition relative de la consommation des quotas et budgets entre différents consommateurs ou applications clientes (utilisateurs, clés virtuelles, projets).
* **Données Nokido équivalentes** :
  * `tasks.db` : tables des tâches multi-agents avec corrélation `agent_name` (`agt_claude`, `agt_gemini`, `agt_antigravity`, `vibe`, `mammouth`) et `job_id`.
  * `config/agent_identities.json` : attributions d'identités, rings et permissions.
  * Logs d'audit du hub (`logs/mcp_audit.log`).
* **Écran Nokido proposé** :
  * Panneau dans le dashboard : **« Partage des Quotas par Agent »**.
  * Visualisation en tableau récapitulatif avec barres de progression horizontales discrètes :
    * Part absorbée par Claude, Gemini, Antigravity, Mistral Vibe et Mammouth.
    * Détection des anomalies d'hyper-consommation par un agent en boucle autonome.
* **Priorité** : **P2 (Moyenne)** — Renforce la gouvernance du swarm et prévient la vampirisation du pool partagé.

---

### 5) `ProviderUtilizationTab` (analytics/utilization)
* **Ce qu'il montre dans OmniRoute** :
  * Métriques de performance temporelles par fournisseur :
    * Latence moyenne au premier token (TTFT).
    * Débit moyen (tokens/sec).
    * Taux d'erreurs et de saturation sur 1h, 24h, 7j.
* **Données Nokido équivalentes** :
  * `forge_telemetry` / `logs/mcp_audit.log`.
  * `tasks.db` (`duration_ms`, `tokens_in`, `tokens_out`, `status`).
  * Mesures de santé live de `probe_service` (latence `probe_ms`, qualification en 5 états).
* **Écran Nokido proposé** :
  * Section analytique : **« Vélocité & Disponibilité des Endpoints »**.
  * Métriques brutes présentées en cartes `.lf-panel` :
    * Médiane de réponse (ms) par provider.
    * Ratio de succès/échec (%).
    * Horodatage de la dernière sonde HTTP/TCP.
* **Priorité** : **P3 (Basse)** — Utile pour le benchmarking fin des modèles, mais secondaire face au contrôle direct des quotas.

---

### 6) `ActivityFeed` (activity/ActivityFeed)
* **Ce qu'il montre dans OmniRoute** :
  * Flux temps réel (SSE ou polling court) de chaque requête routée, du provider retenu, de la décision de fallback et des économies générées.
* **Données Nokido équivalentes** :
  * Flux SSE de Nokido déjà existant sous `/api/swarm/stream` ou websocket hub.
  * Table `agent_messages` (inbox inter-agents).
  * Table `tasks` de `tasks.db`.
* **Écran Nokido proposé** :
  * Flux d'activité intégré : **« Journal des Décisions de Routage »**.
  * Liste défilante monospace (police JetBrains Mono, taille compacte 11-12px) :
    * `[Horodatage] [Agent] [Modèle choisi] [Palier/Raison] [Durée ms] [Statut]`
    * Filtres par agent et par état (OK, Fallback déclenché, Rejet Firewall).
* **Priorité** : **P2 (Moyenne)** — Offre une transparence opérationnelle instantanée lors des runs complexes.

---

## 3. Existant Côté Nokido (`app/web_hub`)

### Structure de `dashboard_html.py`
Le rendu HTML actuel de Nokido est caractérisé par :
* Un modèle strict basé sur la mesure réelle (`probe_service`, 5 états : `live`, `degraded`, `error`, `offline`, `unknown`), refusant d'afficher `live` sans sonde effective.
* Une qualification stricte en 6 états applicatifs (`tile_state`), évitant les faux "bientôt disponibles".
* Des tuiles de services (`render_cards`) disposées dans une grille `.lf-grid`.
* Un style CSS sobre et épuré (`dashboard.html` / `nokido.css`), fond sombre (`--bg-1`, `--bg-2`), typographie système et `JetBrains Mono` pour les métadonnées.

### État de `wired_routes.py`
Le routeur `wired_routes.py` ponte les routes frontend mortes vers le Hub `:8766` via `_call(tool, arguments)` :
* Routes existantes :
  * RAG : `/api/rag/stats`, `/api/rag/tokenize`, `/api/rag/search`, `/rag` (page).
  * Swarm / Agents : `/api/swarm/run`, `/api/swarm/stream` (SSE), `/api/agents`, `/swarm` (page).
  * Graphe / Proprioception : `/api/graph/proprioception`.
  * Débat : `/debate`, `/api/debate/run`.
  * Edge / Android : `/api/edge/fleet`, `/api/edge/stats`, `/api/edge/heartbeat`, etc.
* **Absence constatée** :
  * **Aucune route dédiée providers / census / quota** n'est encore câblée dans `wired_routes.py`.
  * L'accès actuel aux providers passe uniquement par le hub tool direct `hub action=list_providers` ou `hub action=quota_status`.

---

## 4. Recommandations d'Intégration dans le Style Nokido

Pour respecter l'identité visuelle et technique de Nokido sans rupture :

1. **Tuile d'accès sur le Dashboard (`/`)** :
   * Ajouter une tuile dans le Hub : **`Endpoints & Quotas LLM`** avec icône Lucide `sliders` ou `cpu`.
   * Cible : `/endpoints` (montage in-process sous `app/web_hub/`).
2. **Câblage des endpoints JSON dans `wired_routes.py`** :
   * `GET /api/endpoints/census` : expose le contenu filtré de `sandbox/free_tier_census.json` combiné aux résultats de `hub action=list_providers`.
   * `GET /api/endpoints/quotas` : expose l'état vivant des quotas (`quota_status`, drapeaux 429 de `quota_epuise`, pools Gemini/Claude).
   * `GET /api/endpoints/paliers` : expose la configuration active de `forge_palier_effort`.
3. **Ergonomie de la page `/endpoints`** :
   * Bandeau supérieur récapitulatif reprenant l'esprit du **`TierCoverageWidget`** (Souverain vs Déporté vs Payant).
   * Tableau principal inspiré de **`ConnectionQuotaPanel`**, stylé selon `.lf-panel` avec indicateurs de sondes réelles (vert live, jaune dégradé, rouge erreur/429).
   * Volet dépliable reprenant le **`ComboControlCenterClient`** pour suivre l'ordre de fallback sans complexité superflue.

---

## 5. Synthèse des Priorités de Réalisation

| Composant OmniRoute | Équivalent Nokido | Priorité | Données SSoT Sources |
|---|---|---|---|
| **TierCoverageWidget** | Couverture des Paliers d'Inférence | **P1** | `sandbox/free_tier_census.json`, `forge_palier_effort` |
| **ConnectionQuotaPanel** | Détail Connexion & Quotas | **P1** | `quota_epuise`, `hub quota_status`, `whoami` |
| **ComboControlCenterClient** | Cascades & Paliers Cognitifs | **P2** | `forge_cognitive_router`, `call_cascade` |
| **quota-share** | Partage des Quotas par Agent | **P2** | `tasks.db`, `logs/mcp_audit.log`, `agent_identities.json` |
| **ActivityFeed** | Journal des Décisions de Routage | **P2** | `agent_messages`, SSE `/api/swarm/stream` |
| **ProviderUtilizationTab** | Vélocité & Disponibilité Endpoints | **P3** | `probe_service`, métriques de runs |

Cette architecture permet à Nokido d'adopter le meilleur de l'expérience d'arbitrage d'OmniRoute tout en restant 100 % fidèle à sa rigueur souveraine, son esthétique épurée et sa doctrine de vérité terrain mesurée.
