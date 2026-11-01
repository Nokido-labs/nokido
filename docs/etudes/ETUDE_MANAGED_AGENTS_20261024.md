# Étude d'opportunité et comparaison architecturale : Claude Managed Agents vs Nokido Sovereign Hub

**Date :** 2026-10-24  
**Auteur :** ANTIGRAVITY (Agent Sovereign Hub, Ring 1)  
**Item Roadmap :** `P2_etude_managed_agents_relancee_20261024`  
**Statut :** Livrable d'étude d'architecture (Taille M)  
**Worktree cible :** `nokido_worktrees/antigravity`  
**Fichier :** `docs/etudes/ETUDE_MANAGED_AGENTS_20261024.md`  
**Sources primaires :** 27 pages documentaires ingérées au RAG (`claude_docs:platform.claude.com/docs/en/managed-agents/<page>.md`)  

---

## Résumé exécutif

Anthropic a introduit **Claude Managed Agents**, une infrastructure managée d'exécution d'agents autonomes opérant au-dessus ou en complément de la Messages API classique. Ce système propose un harnais complet intégrant bacs à sable (cloud ou auto-hébergés), orchestration multi-agents hiérarchisée, coffres-forts d'identifiants (*vaults*) avec injection de secrets, budgets de dépenses en dollars, déploiements récurrents planifiés par cron, et un paradigme de validation orienté résultat (*outcomes*) articulé autour d'un correcteur hermétique (*grader*).

La présente étude analyse en profondeur l'architecture de cette offre, établit une comparaison rigoureuse point par point avec les mécanismes souverains déjà en production dans **Nokido** (`tools/forge_task_executor.py`, `app/forge_job_runner.py`, `app/forge_secrets.py`, `tools/forge_worktree.py`, `app/forge_quota_tracker.py`), identifie les patrons de conception de haute valeur méritant une **transposition souveraine locale**, et formalise les motifs d'exclusion de l'offre commerciale cloud payante conformément à la doctrine de l'Owner (*zéro spend claude.ai cloud, préservation des quotas*).

---

## 1. Ce que fournit Claude Managed Agents

L'offre Claude Managed Agents (accessible sous le header bêta `managed-agents-2026-04-01`) repose sur quatre abstractions fondamentales et un ensemble de sous-systèmes d'exécution et de gouvernance.

```
+-----------------------------------------------------------------------------------+
|                           CLAUDE MANAGED AGENTS PLATFORM                          |
|                                                                                   |
|  +--------------------+     +---------------------+     +----------------------+  |
|  |       Agent        |     |     Environment     |     |        Vault         |  |
|  |  (Model, Prompts,  |     |  (Cloud Sandbox or  |     |  (OAuth, Bearer,     |  |
|  |   Tools, Skills)   |     |  Self-Hosted Queue) |     |   Env Var Egress)    |  |
|  +---------+----------+     +----------+----------+     +----------+-----------+  |
|            |                           |                           |              |
|            +-------------------+       |       +-------------------+              |
|                                |       |       |                                  |
|                                v       v       v                                  |
|                    +------------------------------------+                         |
|                    |              Session               |                         |
|                    |   (State, FS, Threads, Budget)     |                         |
|                    +-----------------+------------------+                         |
|                                      |                                            |
|                                      v                                            |
|                    +------------------------------------+                         |
|                    |            Event Stream            |                         |
|                    |     (SSE: user.*, agent.*, etc.)   |                         |
|                    +-----------------+------------------+                         |
|                                      |                                            |
|           +--------------------------+--------------------------+                 |
|           v                                                     v                 |
|  +-----------------------------+               +-------------------------------+  |
|  |     Multi-Agent Threads     |               |       Outcome Evaluation      |  |
|  |  - Primary Coordinator      |               |  - User Rubric (Markdown)     |  |
|  |  - Isolated Subagent Context|               |  - Isolated Grader Context    |  |
|  |  - Mid-turn Advisor         |               |  - Iterations (satisfied, etc)|  |
|  +-----------------------------+               +-------------------------------+  |
+-----------------------------------------------------------------------------------+
```

### 1.1 Modèle conceptuel à quatre piliers et flux d'événements
*[Source : overview.md, sessions.md, reference.md]*

1. **Agent** : Définition déclarative et versionnée (`v1`, `v2`, etc.) regroupant le modèle d'inférence (ex. `claude-opus-5`, `claude-sonnet-5`), le prompt système initial, la liste des outils autorisés (`agent_toolset_20260401`), les serveurs MCP déclarés et les compétences (*skills*) chargées [source: `overview.md`].
2. **Environment** : Cible d'exécution sous-jacente déterminant où s'exécutent les commandes système et la manipulation de fichiers : soit une machine virtuelle cloud managée par Anthropic, soit une file de travail distribuée vers une infrastructure auto-hébergée (*self-hosted sandbox*) [source: `overview.md`, `self-hosted-sandboxes.md`].
3. **Session** : Instance vivante d'un agent liée à un environnement pour réaliser une tâche donnée. Une session est persistante, conserve son système de fichiers et son historique conversationnel entre plusieurs interactions [source: `overview.md`, `sessions.md`]. Elle s'initialise en deux étapes (création puis émission d'événement de démarrage) ou en un seul appel via le tableau `initial_events` (jusqu'à 50 événements traités séquentiellement) [source: `sessions.md`].
4. **Events** : Bus asynchrone bidirectionnel en Server-Sent Events (SSE) structuré selon une nomenclature stricte `{domaine}.{action}` :
   - `user.*` : `user.message`, `user.interrupt`, `user.define_outcome`, `user.tool_confirmation`, `user.custom_tool_result`, `user.tool_result` (réservé au self-hosted) [source: `reference.md`].
   - `agent.*` : `agent.message`, `agent.thinking`, `agent.tool_use`, `agent.tool_result`, `agent.mcp_tool_use`, `agent.mcp_tool_result`, `agent.thread_context_compacted`, `agent.thread_message_sent`, `agent.thread_message_received` [source: `reference.md`].
   - `session.*` : `session.status_running`, `session.status_idle` (avec `stop_reason`), `session.status_rescheduled`, `session.status_terminated`, `session.usage`, `session.thread_created`, `session.thread_status_*` [source: `reference.md`].
   - `span.*` : marqueurs d'observabilité pour mesurer la latence et l'usage (`span.model_request_*`, `span.outcome_evaluation_*`) [source: `reference.md`].

### 1.2 Sandboxes : Cloud managé vs Auto-hébergé (`self_hosted`)
*[Source : self-hosted-sandboxes.md, self-hosted-sandboxes-security.md]*

Par défaut, l'exécution s'effectue dans des conteneurs Linux cloud gérés par Anthropic. Pour les organisations soumises à des contraintes de résidence de données ou de réseau privé, Anthropic propose l'environnement `self_hosted` :
- **Principe de découplage** : L'orchestration et l'inférence LLM restent dans le plan de contrôle cloud d'Anthropic, mais l'exécution concrète des outils (`bash`, lecture, écriture, exécution de scripts) est déportée sur l'infrastructure du client [source: `self-hosted-sandboxes.md`].
- **Mécanisme de dispatch asynchrone** : L'environnement agit comme une file d'attente (*work queue*). Un démon client (*worker*), disponible via le CLI `ant beta:worker poll` ou le SDK Python (`EnvironmentWorker`), interroge en continu la file via HTTPS sortant authentifié par une clé `ANTHROPIC_ENVIRONMENT_KEY` [source: `self-hosted-sandboxes.md`].
- **Cycle de vie du worker** : Le worker extrait un élément de travail (*work item*), prépare l'arborescence `/workspace`, télécharge les *skills* de l'agent dans `/workspace/skills/<name>/`, synchronise les banques de mémoire montées dans `/mnt/memory/<mount_path>/`, exécute les commandes dans un conteneur dédié ou sur l'hôte, et poste les résultats d'outils (`user.tool_result`) vers le plan de contrôle [source: `self-hosted-sandboxes.md`].
- **Responsabilité partagée et sécurité** : Anthropic garantit l'intégrité de la file et l'isolation multi-tenant de son API. En revanche, le client assume l'entière responsabilité du durcissement du conteneur (non-root, filesystem read-only, suppression de capabilities Linux), du filtrage egress réseau (VPC/firewall), de la rotation des clés d'environnement et du nettoyage des données sensibles sur disque [source: `self-hosted-sandboxes-security.md`]. Les politiques ZDR (Zero Data Retention) et HIPAA ne sont pas applicables à cette architecture [source: `overview.md`, `self-hosted-sandboxes.md`].

### 1.3 Gestion des identifiants et Vaults
*[Source : vaults.md, mcp-connector.md]*

Le système de *Vaults* sépare la définition de l'agent (réutilisable au niveau organisation) de l'identité de l'utilisateur final qui initie la session :
- **Catégories d'identifiants** :
  1. `mcp_oauth` : Gère l'authentification OAuth 2.0 vers des serveurs MCP tiers (ex. Slack, GitHub). Anthropic gère automatiquement le rafraîchissement des jetons expirés via les configurations `refresh.token_endpoint` et `token_endpoint_auth` (`client_secret_post`, `client_secret_basic`, ou `none`) [source: `vaults.md`].
  2. `static_bearer` : Jetons statiques ou clés d'API transmis lors de la connexion MCP [source: `vaults.md`].
  3. `environment_variable` : Injection de secrets sous forme de variables d'environnement dans le bac à sable. Le secret réel n'est **jamais lisible** par l'agent : il est représenté par une valeur opaque factice et substitué à la volée par le proxy réseau sortant (*egress substitution*). La substitution est chirurgicalement restreinte par `networking.allowed_hosts` et par `injection_location: {header: bool, body: bool}` [source: `vaults.md`].
- **Contrainte self-hosted** : L'injection de secrets de type `environment_variable` avec substitution à l'egress n'est pas supportée sur les sandboxes auto-hébergées [source: `vaults.md`].

### 1.4 Budgets de session et régulation financière
*[Source : budgets.md, scheduled-deployments.md]*

Chaque session peut recevoir un plafond de dépense strict (`budget`) :
- **Unité et précision** : Défini en cents entiers USD sous forme de chaîne de caractères sans zéros initiaux (`"125"` pour $1.25, `"500"` pour $5.00) afin d'interdire tout arrondi flottant [source: `budgets.md`].
- **Métrique List Cost** : La plateforme valorise en temps réel la consommation aux prix publics : tokens du modèle servi, requêtes web ($10 pour 1 000 recherches), et temps d'exécution de la session ($0.08 par heure) [source: `budgets.md`].
- **Interception inter-requêtes** : La vérification s'opère avant chaque appel modèle. La requête en vol qui franchit le seuil va jusqu'à son terme, ce qui peut occasionner un léger dépassement borné à une seule requête modèle par thread (ex. arrêt à `"53"` pour un cap à `"50"`) [source: `budgets.md`].
- **Pause réversible** : La session ne meurt pas : elle passe au statut `idle` avec le motif d'arrêt `stop_reason: budget_reached`. Elle n'accepte alors plus aucun nouveau message utilisateur, mais continue de traiter les événements de clôture des outils en vol (`user.tool_result`, `user.tool_confirmation`). Une simple mise à jour de la session élevant le montant (`budget.max_list_cost`) ou le passant à `null` réactive immédiatement l'exécution sans perte d'état [source: `budgets.md`].

### 1.5 Outcomes et boucle de rétroaction avec Correcteur (Grader)
*[Source : define-outcomes.md]*

Le concept d'Outcome formalise la notion de travail fini (*Definition of Done*) à travers une boucle d'auto-évaluation fermée :
- **Rubric déclarative** : L'utilisateur fournit une grille d'évaluation en Markdown (`rubric`), inline ou via un fichier Files API, articulée en critères précis et mesurables (ex. colonnes requises, tests obligatoires, cohérence financière) [source: `define-outcomes.md`].
- **Grader hermétique** : Le plan de contrôle instancie un agent évaluateur dédié (*grader*) qui s'exécute dans un contexte de tokens complètement isolé de l'agent réalisateur, garantissant l'impartialité de la note [source: `define-outcomes.md`].
- **Cycle d'itération** : L'évaluateur émet des spans de contrôle (`span.outcome_evaluation_start`, `span.outcome_evaluation_ongoing`, `span.outcome_evaluation_end`) et conclut par un verdict formel :
  - `satisfied` : Objectif atteint, transition vers l'état `idle` final [source: `define-outcomes.md`].
  - `needs_revision` : Le rapport d'écarts et de critères échoués est automatiquement transmis à l'agent pour une nouvelle passe de travail [source: `define-outcomes.md`].
  - `max_iterations_reached` : Plafond d'itérations atteint (défaut 3, max 20) sans satisfaction complète [source: `define-outcomes.md`].
  - `failed` : Incompatibilité sémantique manifeste entre la consigne et la grille [source: `define-outcomes.md`].
  - `interrupted` : Interruption manuelle en vol [source: `define-outcomes.md`].
- **Dépôt des livrables** : Les fichiers finaux sont écrits par l'agent sous `/mnt/session/outputs/` et récupérés par l'API Files via le filtre `scope_id` [source: `define-outcomes.md`].

### 1.6 Déploiements planifiés (Scheduled Deployments)
*[Source : scheduled-deployments.md]*

L'API Deployments permet d'automatiser le lancement récurrent d'agents :
- **Syntaxe POSIX & Fuseaux** : Expression standard à 5 champs (`minute hour dom month dow`) couplée à un identifiant IANA (ex. `Europe/Paris`) [source: `scheduled-deployments.md`].
- **Lissage de charge (Jitter)** : Application d'un décalage aléatoire pouvant atteindre 15 % de l'intervalle entre exécutions (minimum 5 secondes, maximum 9 minutes) pour éviter les congestions sur les serveurs d'inférence [source: `scheduled-deployments.md`].
- **Plafond financier unitaire** : Le budget paramétré sur le déploiement s'applique isolément à chaque session instanciée, empêchant une dérive cumulative non maîtrisée [source: `scheduled-deployments.md`].
- **Historique des runs** : Enregistrement de chaque déclenchement dans un registre `deployment_runs` associant l'horodatage, le `session_id` généré ou le code d'erreur rencontré [source: `scheduled-deployments.md`].

### 1.7 Orchestration Multi-agents et rôle Conseiller (Advisor)
*[Source : multiagent-orchestration.md]*

Managed Agents supporte la collaboration d'agents dans un espace d'exécution unifié :
- **Threads de session isolés** : Tous les agents d'une session partagent le même système de fichiers sandbox et les mêmes coffres-forts, mais chaque agent opère dans un *session thread* distinct avec son propre historique de contexte et son modèle assigné [source: `multiagent-orchestration.md`].
- **Topologie hiérarchique stricte** :
  - L'agent coordinateur déclare un roster `multiagent.agents` contenant au maximum 20 agents uniques [source: `multiagent-orchestration.md`].
  - La hiérarchie est strictement bornée à **1 seul niveau de délégation** : si un agent du roster tente lui-même de déclarer un sous-roster, l'API rejette la configuration avec une erreur 400 [source: `multiagent-orchestration.md`].
  - Limite de concurrence de **25 threads simultanés** par session (les threads d'archivage peuvent être libérés via `POST /threads/{id}/archive`) [source: `multiagent-orchestration.md`].
- **Le rôle Conseiller (`anthropic.advisor`)** :
  - Déclaré dans le roster via `{"type": "advisor", "model": "<model_id>"}` (un seul advisor par roster) [source: `multiagent-orchestration.md`].
  - Consultation mid-turn éphémère : invoqué automatiquement par le coordinateur pour guider un plan ou débloquer une situation. Le thread d'advisor naît, livre son avis via l'événement `agent.thread_message_received`, et s'auto-termine immédiatement [source: `multiagent-orchestration.md`].
  - L'advisor ne possède aucun outil, n'a pas accès à `bash`, et n'est pas visible par les sous-agents du roster. Les threads d'advisor sont exemptés de la limite des 25 threads concurrents [source: `multiagent-orchestration.md`].
  - Confidentialité des avis : Selon la politique du modèle, le contenu peut être lisible en clair (ex. Opus 4.8) ou caviardé sous la forme `[{"type": "redacted"}]` sur le flux d'événements client (ex. Opus 5), tout en restant pleinement exploité par le modèle côté serveur [source: `multiagent-orchestration.md`].

---

## 2. Tableau comparatif point par point avec l'existant Nokido

Le tableau ci-dessous confronte chaque capacité de Claude Managed Agents à son équivalent opérationnel dans la base de code Nokido.

| Dimension technique | Claude Managed Agents (Anthropic) | Nokido Sovereign Hub (Existant) | Analyse de maturité & Écart architectural |
| :--- | :--- | :--- | :--- |
| **Exécuteur & Dispatch d'agents** | Coordinateur central avec threads de session isolés, dispatch d'agents configurés par ID dans un roster `multiagent.agents` (max 20 agents, max 25 threads). <br>*[source: multiagent-orchestration.md]* | **`tools/forge_task_executor.py`** :<br>- `process_task` (boucle principale de traitement des tâches)<br>- `_delegate_to_agy` (délégation CLI Antigravity)<br>- `_delegate_to_codex` (délégation CLI Codex)<br>- `_delegate_to_vibe` (délégation Mistral Vibe)<br>- `_delegate_to_opencode` (délégation OpenCode/Nemotron/GLM)<br>- `_delegate_to_claude` (délégation Claude Headless) | **Équivalence fonctionnelle atteinte en local**. Nokido dispatche vers des CLI hétérogènes (AGY, Codex, Vibe, OpenCode) sur machines locales, sans dépendance d'API cloud. Nokido gère en plus la réattribution dynamique en cas de panne fournisseur via `_reaffecter` et `_vers_moins_chargee`. |
| **Validation des livrables & Outcomes** | Boucle d'Outcome avec grille Markdown (`rubric`), évaluateur hermétique (*grader*) sur contexte vierge, 5 statuts : `satisfied`, `needs_revision`, `max_iterations_reached`, `failed`, `interrupted`. <br>*[source: define-outcomes.md]* | **`tools/forge_task_executor.py`** :<br>- `_juger_livraison` (contrôle déterministe complet de livraison)<br>- `_rien_produit` (détection `[RIEN PRODUIT]` si ni commit, ni fichier, ni artefact valide)<br>- `_contrat_livrable` (analyse du contrat `[LIVRABLE_CONTRAT]`)<br>- `_verdict_contrat` (vérification stricte des chemins et types committés)<br>- `_artefact_declare_absent` (rejet si l'artefact pointé n'existe pas sur disque)<br>- `_red_non_observe` (vérification du cycle TDD : RED préalable obligatoire)<br>- `_contenu_livre` (détection des commits vides ou tests touchés hors autorisation) | **Supériorité déterministe de Nokido sur le code**. Nokido inspecte l'état Git réel (`_effet_observe`), l'arbre de travail et l'existence physique des fichiers sur disque au lieu d'une simple validation déclarative LLM. **En revanche**, Nokido ne possède pas encore de brique générique de notation textuelle libre multi-critères (*rubric grading*) par un LLM arbitre indépendant. |
| **Conseiller stratégique (Advisor Pattern)** | Thread éphémère `anthropic.advisor` sans outils, invoqué mid-turn pour arbitrage ou déblocage, résultat textuel ou redacted. <br>*[source: multiagent-orchestration.md]* | **`tools/forge_task_executor.py`** & **`app/forge_llm_router.py`** :<br>- `tools/forge_task_executor.py:_appeler_conseiller` (point d'entrée d'arbitrage de l'exécuteur)<br>- `tools/forge_task_executor.py:_conseil_plan` (avis de cadrage avant exécution)<br>- `tools/forge_task_executor.py:_conseil_revue` (avis d'arbitrage après livraison)<br>- `app/forge_llm_router.py:conseiller` (cascade souveraine : Ollama cloud free -> providers free -> repli OAuth Claude) | **Parité d'intention, souveraineté supérieure pour Nokido**. L'advisor Nokido applique la cascade souveraine `conseil` (local/gratuit d'abord, Claude en dernier recours sans coût d'API payante). Les sorties sont bornées par `CONSEIL_AVIS_MAX` (400 tokens) et ne bloquent jamais l'exécution en cas d'erreur. |
| **Tâches détachées & Jobs asynchrones** | Sessions d'arrière-plan managées par l'infrastructure cloud d'Anthropic ou polling de file en self-hosted. <br>*[source: sessions.md, self-hosted-sandboxes.md]* | **`app/forge_job_runner.py`** :<br>- `launch_job` (spawn de processus détaché avec identité de processus, lane et cap RSS)<br>- `read_job` (lecture des flux stdout/stderr et code retour `.rc`)<br>- `kill_job` (terminaison ciblée)<br>- `reconcile_jobs` (nettoyage des processus zombies/orphelins)<br>**`tools/forge_task_executor.py`** :<br>- `requalifier_orphelines` (reprise des tâches abandonnées par crash d'un exécuteur) | **Nokido dispose d'un gestionnaire de jobs complet**. Nokido protège la machine hôte contre les famines de mémoire vive via `rss_cap_mb` (défaut 6 Go, incident 2026-08-02) et borne la taille des journaux sur disque pour éviter la saturation disque. |
| **Coffre-fort de secrets & Identifiants** | *Vaults* au niveau workspace/session ; gestion OAuth avec auto-refresh (`mcp_oauth`), jetons statiques (`static_bearer`), et substitution à l'egress (`environment_variable`). <br>*[source: vaults.md]* | **`app/forge_secrets.py`** :<br>- `get_secret` (résolution en cascade : mémoire, coffre machine, WCM, coffre réservé, dotenv)<br>- `set_secret` (enregistrement sécurisé)<br>- `injecter_env_depuis_coffre` (injection d'environnement éphémère)<br>**`app/forge_machine_vault.py`** :<br>- `vault_get`, `vault_set` (stockage chiffré machine)<br>- `_protect`, `_unprotect` (chiffrement Windows DPAPI `CryptProtectData` / `CryptUnprotectData` sous `LocalMachine` ou repli POSIX 0600) | **Chiffrement matériel/OS natif sous Nokido**. Nokido utilise Windows DPAPI LocalMachine ou POSIX 0600 (`app/forge_machine_vault.py`), lisible par tous les services locaux sans exposer de clé maître en clair. **Écart** : Nokido ne dispose pas de proxy d'egress interceptant les variables d'environnement à la volée pour masquer les clés aux processus fils. |
| **Isolation de l'espace de travail** | Sandboxes cloud Linux isolées ou conteneurs Docker/MicroVM gérés par le client (`self_hosted`). <br>*[source: self-hosted-sandboxes.md]* | **`tools/forge_worktree.py`** :<br>- `create` (création d'un git worktree dédié par agent : `nokido_worktrees/<agent>`)<br>- `route` (résolution du répertoire de travail isolé)<br>- `cible_ecriture` (cloisonnement strict des écritures par agent)<br>- `create_proof` / `remove_proof` (worktree éphémère pour exécuter les suites de tests en isolation absolue) | **Isolation Git souveraine de haute performance**. Nokido isole chaque agent dans son propre working tree Git sans le surcoût de démarrage de machines virtuelles. La création de worktrees de preuve (`create_proof`) permet de rejouer des tests sans polluer l'espace de développement actif. |
| **Budgets de session & Contrôle des quotas** | Plafond dur en dollars list price (`budget.max_list_cost`), arrêt inter-requêtes, statut `idle` avec `stop_reason: budget_reached`, reprise automatique. <br>*[source: budgets.md]* | **`app/forge_quota_tracker.py`** :<br>- `get_quota`, `get_all_quotas` (suivi des quotas fournisseurs)<br>- `record_response_headers` (analyse des en-têtes HTTP de rate-limit)<br>- `record_429` (enregistrement des saturations et temps d'attente)<br>**`tools/forge_task_executor.py`** :<br>- `_consommer_budget_claude` (décompte strict en USD des appels Claude Headless dans `claude_headless_budget.json`)<br>- `_depense_claude_du_jour` (lecture du cumul quotidien)<br>- `_quota_codex` / `_consommer_quota_codex` (suivi du nombre de runs Codex quotidiens) | **Contrôle budgétaire dual sous Nokido**. Nokido applique un suivi financier en USD pour l'API Claude (`_consommer_budget_claude`) avec distinction mesure vs forfait, et un suivi en volume d'appels pour les CLI (Codex). **Écart** : Nokido n'a pas de mécanisme de suspension `idle` réversible standardisé au niveau de chaque tâche unitaire `tasks.db`. |
| **Planification de tâches récurrentes** | API Deployments avec expressions cron POSIX, fuseaux horaires IANA, jitter de 15% et budget par run. <br>*[source: scheduled-deployments.md]* | **`proxy_deno/core/supervisor.ts`** & daemons Nokido :<br>- Superviseur NSSM / Deno pour services continus<br>- `tools/forge_task_executor.py:run_loop` (polling continu cadencé par `TASK_EXEC_POLL_INTERVAL`)<br>- Scheduled watchers (`NokidoCommWatch`, `NokidoRSSWatcher`) | **Nokido privilégie les daemons supervisés**. Nokido s'appuie sur le superviseur de services et les daemons autonomes plutôt qu'un planificateur cron unifié en base de données. |
| **Politique de permissions des outils** | `always_allow` ou `always_ask` au niveau de l'agent ou par outil/serveur MCP. <br>*[source: permission-policies.md]* | **`app/forge_videur.py`** & **`app/forge_mcp_security.py`** :<br>- Modèle de sécurité multi-rings (Ring 0 superviseur à Ring 4 public/cloud)<br>- Résolution par jeton JWT et agent déclaré (`valider_requete`)<br>- Cloisonnement des dossiers accessibles en écriture par ring (`forge_workspace_guard`)<br>- `SemanticFirewall` (pré/post-filtrage DLP) | **Modèle de sécurité Nokido nettement plus granulaire**. Alors que Claude Managed Agents se limite à un binaire `always_allow` / `always_ask`, Nokido applique un modèle de défense en profondeur à 5 anneaux de privilège (*rings*), un pare-feu sémantique et un audit temps réel en base SQLite. |
| **Banques de mémoire persistante** | *Memory stores* montés à `/mnt/memory/` (max 8 stores par session, 2 000 fichiers/store, max 100 kB par fichier). <br>*[source: memory.md]* | **RAG Nokido & Tableau Noir** :<br>- `embeddings.db` / `rag_chunks` (index dense BGE-M3 + index FTS SQLite multi-millions de chunks)<br>- `app/forge_swarm_blackboard.py` (faits partagés, locks, état inter-agents avec trust score et TTL)<br>- `app/forge_mailbox.py` (boîtes aux lettres persistantes par agent) | **Capacité de mémoire Nokido considérablement plus vaste**. Les memory stores d'Anthropic sont limités à de petits fichiers texte (100 kB). Nokido opère un RAG multi-vectoriel souverain de plusieurs millions d'entrées et un tableau noir partagé avec synchronisation transactionnelle. |

---

## 3. Analyse d'opportunité : Transposition souveraine vs Dépendance cloud

L'analyse de Claude Managed Agents met en lumière des innovations d'architecture logicielle de premier plan, tout en confirmant la nécessité d'exclure l'utilisation directe de l'infrastructure cloud payante d'Anthropic.

### 3.1 Ce qui manque à Nokido et mérite une transposition souveraine

Quatre patrons de conception documentés dans Managed Agents présentent une valeur immédiate pour l'architecture Nokido et peuvent être transposés de façon **100 % souveraine**, sans ajouter la moindre dépendance externe :

#### Patron A : Le Grader hermétique avec Rubric d'Outcome (`define-outcomes.md`)
- **Constat Nokido** : L'exécuteur Nokido dispose d'un juge déterministe très robuste (`_juger_livraison`, `_verdict_contrat`, `_rien_produit`) qui valide la présence de commits, la modification de fichiers cibles et le passage des tests unitaires. Cependant, pour des tâches de synthèse, de documentation, d'analyse d'architecture ou de refactoring sans suite de tests préexistante, Nokido ne possède pas de mécanisme d'évaluation qualitative impartiale.
- **Transposition souveraine** :
  - Créer un module `app/forge_outcome_grader.py`.
  - Quand une tâche porte une balise `[RUBRIC] <markdown>` ou un contrat qualitatif, l'exécuteur soumet l'artefact produit à un évaluateur dédié instancié dans un contexte vierge (modèle local Ollama Qwen 2.5-Coder / DeepSeek ou slot rapide Tier-0 Groq).
  - Le grader évalue indépendamment chaque critère de la grille et rend un verdict structuré : `{result: 'satisfied' | 'needs_revision', explanation: '...'}`.
  - En cas de `needs_revision`, l'exécuteur réinjecte automatiquement l'explication dans la boucle de travail de l'agent sans intervention humaine, jusqu'à un plafond `max_iterations`.

#### Patron B : Egress Secret Masking / Proxy de substitution (`vaults.md`)
- **Constat Nokido** : Les secrets résolus par `app/forge_secrets.py` sont actuellement injectés directement dans l'environnement du processus fils (`os.environ`) via `injecter_env_depuis_coffre`. Si un agent exécute une commande de débogage affichant l'environnement (`env`, `printenv`, `Get-ChildItem env:`), les jetons risquent d'apparaître dans les logs de sortie de tâche.
- **Transposition souveraine** :
  - Adopter le patron d'Anthropic : injecter des valeurs factices opaques (ex. `NOKIDO_MASKED_SECRET_<NAME>`) dans l'environnement de travail des worktrees.
  - Configurer un proxy HTTP local (ou intercepter les appels dans la membrane d'egress `app/forge_network_membrane.py` / `proxy_deno`) pour substituer la vraie valeur du coffre DPAPI uniquement au moment de l'émission sur les hôtes autorisés (`allowed_hosts`). L'agent ne manipule jamais la clé réelle.

#### Patron C : Suspension réversible par Budget de Tâche (`budgets.md`)
- **Constat Nokido** : Le suivi budgétaire actuel (`_consommer_budget_claude`) est passif : il consigne les dépenses après coup dans `claude_headless_budget.json`. Si un plafond quotidien est atteint, les tâches futures sont refusées ou réaffectées, mais une tâche en cours qui dérive en boucle n'est pas mise en pause réversible.
- **Transposition souveraine** :
  - Ajouter un champ `budget_tokens` ou `budget_usd` dans `tasks.db`.
  - L'exécuteur vérifie la consommation cumulée entre chaque tour de dialogue de l'agent. Si le cap est dépassé, la tâche bascule au statut `suspended_budget` au lieu d'échouer.
  - L'Owner ou le superviseur peut débloquer la tâche par une commande d'extension de budget, reprenant le travail exactement là où il s'était arrêté.

#### Patron D : Formalisation standardisée du Roster Multi-agent (`multiagent-orchestration.md`)
- **Constat Nokido** : La délégation inter-agents fonctionne via `tools/forge_task_executor.py` et le tableau noir, mais les rôles et permissions de délégation ne sont pas formalisés sous forme de schéma déclaratif unifié.
- **Transposition souveraine** :
  - Définir une structure déclarative pour les agents coordinateurs, limitant explicitement à 1 niveau de sous-délégation pour prévenir les boucles infinies de sous-agents (règle d'or éprouvée par Anthropic).

---

### 3.2 Ce qui constitue une dépendance cloud payante à écarter formellement

L'utilisation directe du service commercial **Claude Managed Agents** sur l'infrastructure d'Anthropic doit être **formellement écartée** pour les motifs suivants :

1. **Décision ferme de l'Owner (Doctrine Zéro Dépense Cloud payante)** :
   - L'Owner a proscrit tout nouvel engagement financier ou consommation de crédit payant sur `claude.ai` / Anthropic Console.
   - Les quotas Claude existants doivent être réservés aux sessions interactives prioritaires via OAuth (Claude CLI / Antigravity), sans être siphonnés par des boucles autonomes d'arrière-plan.
2. **Surcoût prohibitif de la tarification Managed Agents** :
   - Facturation au tarif public plein (*list rates*) sans application des mécanismes d'optimisation locaux :
     - Inférence facturée au jeton sur des modèles très lourds (`claude-opus-5`, `claude-sonnet-5`).
     - Surcoût d'infrastructure fixe : **$0.08 par heure de machine virtuelle** de session [source: `budgets.md`].
     - Surcoût de recherche web : **$10 pour 1 000 requêtes web** [source: `budgets.md`].
   - À titre de comparaison, Nokido utilise des modèles locaux souverains gratuits (Ollama Qwen 2.5-Coder 32B/7B, DeepSeek-R1) et des API tier-0 gratuites (Groq Llama 3.3-70B, SambaNova, Mistral Free Tier), complétés par SearXNG auto-hébergé pour la recherche web (coût marginal = $0.00).
3. **Absence de garanties sur la confidentialité et la rétention des données** :
   - La documentation d'Anthropic indique explicitement que Claude Managed Agents **n'est pas éligible** aux politiques de rétention zéro (*Zero Data Retention - ZDR*) ni aux accords HIPAA BAA en raison de la persistance obligatoire des états de session côté serveur [source: `overview.md`, `self-hosted-sandboxes.md`].
   - Les données du projet, le code source et les sorties d'outils restent hébergés sur les serveurs d'Anthropic. Cette disposition est incompatible avec la doctrine de souveraineté locale de Nokido.
4. **Verrouillage propriétaire (Vendor Lock-in)** :
   - L'API impose des headers bêta volatils (`managed-agents-2026-04-01`, `agent-memory-2026-07-22`) et lie l'ensemble du cycle de vie des tâches à la disponibilité et aux règles de modération du cloud Anthropic.

---

## 4. Recommandations classées avec coût et risque

Le tableau synthétique ci-dessous classe les actions recommandées selon la méthodologie Nokido (Priorité, Dimensionnement, Coût en ressources, Niveau de risque).

| Priorité | Intitulé du chantier souverain | Composants cibles Nokido | Taille | Coût d'exécution | Risque technique & Mitigation |
| :---: | :--- | :--- | :---: | :---: | :--- |
| **P1** | **Transposition du Grader d'Outcome souverain**<br>Implémenter `app/forge_outcome_grader.py` couplé à `tools/forge_task_executor.py:_juger_livraison` pour évaluer les artefacts non-testables par une grille Markdown (*rubric*). | `app/forge_outcome_grader.py`<br>`tools/forge_task_executor.py`<br>`tests/nr/test_outcome_grader_nr.py` | **M** | **0 USD**<br>(Modèle local Ollama ou Tier-0 Groq gratuit) | **Faible** : Si le grader échoue ou timeout, repli immédiat sur le juge déterministe existant (`_rien_produit`, `_contrat_livrable`). Aucune régression sur le code testé. |
| **P2** | **Suspension réversible sur dépassement de budget**<br>Ajouter le statut `suspended_budget` dans `tasks.db` et intercepter les boucles d'agents dans `forge_task_executor.py` avant épuisement complet des quotas. | `tools/forge_task_executor.py`<br>`sandbox/tasks.db`<br>`tests/nr/test_budget_suspension_nr.py` | **S** | **0 USD**<br>(Logique purement locale) | **Très faible** : Évite le gaspillage de tokens sur les tâches qui bouclent sans issue ; intervention facilitée pour l'Owner. |
| **P3** | **Masquage des secrets à l'egress (Secret Masking)**<br>Remplacer les vraies clés par des tokens opaques dans les worktrees et substituer les valeurs réelles dans la couche réseau/hub. | `app/forge_secrets.py`<br>`app/forge_network_membrane.py`<br>`tests/nr/test_secret_masking_nr.py` | **M** | **0 USD**<br>(Logique de proxy local) | **Moyen** : Risque d'altération de requêtes sortantes spécifiques. Nécessite une batterie de tests d'intégration stricts sur les connecteurs autorisés. |
| **ÉCARTÉ** | **Adoption du cloud Claude Managed Agents**<br>Utilisation directe de l'API `/v1/sessions` et des cloud sandboxes d'Anthropic. | *Aucun composant* | — | **Élevé**<br>(Facturation list rates + VM à l'heure) | **Critique** : Violation directe de la décision Owner (zéro spend cloud), fuite de contexte propriétaire, perte d'indépendance technologique. **Rejet formel**. |

---

## Conclusion et plan d'action

Claude Managed Agents valide avec éclat les choix d'architecture distribuée mis en œuvre dans Nokido depuis plusieurs mois :
- L'isolation des agents par **worktrees dédiés** équivaut avantageusement aux sandboxes self-hosted sans lourdeur de conteneurisation.
- Le juge de livraison déterministe de Nokido (`_juger_livraison`, `_rien_produit`) est **plus strict et plus fiable** que de simples auto-évaluations déclaratives pour la production de code informatique.
- Le conseiller souverain (`_appeler_conseiller`, `forge_llm_router.py`) préfigure exactement le rôle `anthropic.advisor` formalisé par Anthropic, avec l'avantage décisif d'un routage local-first à coût nul.

Le levier d'amélioration majeur pour Nokido réside dans le **Patron Grader/Rubric (P1)** : doter Nokido d'un arbitre qualitatif hermétique sur modèle local ou Tier-0 gratuit permettra d'étendre la rigueur du juge de tâches aux productions rédactionnelles, architecturales et documentaires, consolidant ainsi l'autonomie et l'excellence de la ruche souveraine.

---
{"intent":"OK_DONE","pointer_ref":"docs/etudes/ETUDE_MANAGED_AGENTS_20261024.md","commit_message":"docs(etude): etude comparative managed agents et transposition souveraine"}