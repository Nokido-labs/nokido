# Débat Veille Web — Tour 1 (Antigravity)
Date : 2026-11-10 | Auteur : Antigravity (AGY) | Réf : Exigence Owner 10/11 & Faits F1-F6

## 1. Diagnostic : Pourquoi la veille est-elle inférieure au CLI direct ?

L'écart mesuré entre la recherche interactive d'un CLI et la veille autonome s'explique par une chaîne de défaillances en cascade, de l'infrastructure d'exécution jusqu'à l'indexation RAG.

### Hiérarchie des causes par impact décroissant

1. **Faux vert structurel & pollution par repli pervers (Impact Critique)**
   Dans `forge_watch_agent.py` (`verdict_chaine`) et `forge_chain_executor.py` (`_call_search`, `run_node`), la panne de transport (SearXNG muet) ne stoppe pas le pipeline. Au contraire, `_academic_search` (OpenAlex/arXiv) s'exécute quand même, ramène 1 à 3 abstracts hors-sujet (l'élimination de Gauss pour `pytest-split`), ce qui remplit `all_res`. Le pipeline enchaîne alors `refine` -> `crawl` -> `ingest` -> `store`. Avec `n_stored > 0`, `verdict_chaine` émet `status="completed"`. La veille se déclare un succès alors qu'elle a perdu la vue : c'est la violation directe du principe `UNKNOWN ≠ NO`.

2. **Désynchronisation du cycle de vie Docker On-Demand (Impact Majeur)**
   Docker Desktop est géré en *on-demand strict* par `tools/forge_docker_keeper.py` (TTL 900 s, `AUTO_LAUNCH=False`). Au repos, le démon est éteint (`daemon_up=false`). Or, un boot à froid sous Windows/WSL réclame 227 s à 375 s sous pression mémoire (RAM 24 Go > 75 %). `_ensure_searxng` pose un drapeau passif `docker.wanted` via `ensure_docker()` et espère un démarrage par le keeper (tick 30 s). Les délais d'attente s'épuisent ou basculent en repli avant que le conteneur `searxng-laforge` ne réponde HTTP 200 sur `:8080`. Sitôt la phase de recherche finie, la rétention Docker tombe (`_retient_docker`), et Docker est recoupé après son délai de grâce (F2).

3. **Atrophie des moteurs SearXNG & blocage anti-bot (Impact Majeur)**
   Contrairement aux CLI qui interrogent des API de recherche commerciales hébergées (Google, Bing) sans blocage d'IP, SearXNG (`settings.yml` monté depuis `C:\nokido\searxng\settings.yml`) scrape le web depuis une IP locale. Les moteurs généralistes (`google`, `duckduckgo`, `brave`) déclenchent rapidement des CAPTCHA ou des rate-limits (HTTP 429). Le disjoncteur par moteur (`_engine_open`) isole les moteurs défaillants. Ne restent ouverts que les moteurs scientifiques (`arxiv`, `crossref`), transformant toute requête d'ingénierie logicielle en bibliographie académique (F3).

4. **Absence de recherche ciblée & requêtes diluées (Impact Élevé)**
   `_step_search` concatène naïvement `" official documentation guide"` à la requête. Sur un SearXNG aux moteurs généralistes anémiés, cela pousse des termes génériques vers des moteurs inadaptés, sans utiliser les filtres spécialisés de SearXNG (`!gh`, `!pypi`, `!readthedocs`) ni cibler directement les index de code.

5. **Crawl superficiel 0-Hop vs exploration interactive (Impact Moyen)**
   `app/forge_crawl_tool.py` invoque l'API de base `/crawl` de Crawl4AI en mode point-à-point mono-URL. Si la recherche trouve la racine d'un domaine (ex. `docs.pytest.org`), le crawleur n'explore pas l'arborescence (F4). Le CLI direct clique, lit les sous-pages et ajuste son focus ; la veille s'arrête à la page d'accueil.

6. **Hallucination de synthèse & RAG vide (Impact Rémanent)**
   En fin de chaîne, le RAG n'a reçu que des résidus académiques ou du vide (`completed_empty`). Lorsqu'on sollicite le modèle local (`laforge-qwen`) via `ask provider=ollama rag_context=true`, celui-ci invente des URLs et des faits pour combler le vide épistémique (F5, F6).

---

## 2. Propositions concrètes

### P1. Barrière d'arrêt stricte `BLOQUE_PAR_DEPENDANCE` (Anti-Faux Vert)
- **Mécanisme** :
  - Dans `app/forge_chain_executor.py` (`_call_search`, `run_node`) et `app/forge_watch_agent.py` (`verdict_chaine`) :
  - Distinguer la nature du thème : si le thème relève de l'outillage/code, interdire à `_academic_search` d'agir comme substitut de couverture.
  - Si SearXNG est muet (`searxng_ok is False`) et qu'aucune source technique primaire (GitHub API / Web) n'a répondu, SearchAgent doit lever `DependencyBlockedError("SearXNG / Docker indisponible")`.
  - Dans `verdict_chaine`, tout job dont le transport web obligatoire a échoué reçoit le statut canonique `bloque_par_dependance`, jamais `completed` ni `completed_empty`.
- **Garde** : Invariant strict : `status == "completed"` exige `searxng_ok == True` (ou validation explicite d'une source primaire dédiée au domaine) ET `n_stored > 0`.
- **Coût RAM** : 0 Mo.

### P2. Cycle de vie Docker synchronisé & Verrou d'exécution complet
- **Mécanisme** :
  - Dans `tools/forge_docker_keeper.py` et `app/forge_watch_agent.py` (`_ensure_searxng`) :
  - Remplacer l'écriture passive de `docker.wanted` par un appel synchrone bloquant de réveil avec supervision d'état : `ensure_docker_synchronous(timeout=budget)`.
  - Modifier `_retient_docker(intents)` dans `tools/forge_docker_keeper.py` : la rétention Docker doit couvrir **l'intégralité** du cycle de vie du job de veille (`create_job` jusqu'au verdict de `StoreAgent`), et non s'arrêter dès la fin de `SearchAgent`/`CrawlAgent`.
  - Recyclage proactif : si RAM > 80 % à la fin de la veille, déclencher immédiatement `_release_docker()` et `_vider_cache_wsl()`, sans attendre l'expiration du TTL de 900 s.
- **Garde** : Si le boot Docker dépasse 240 s, annulation immédiate et mise en attente ordonnée (`retry_pending`), évitant le gaspillage CPU/RAM.
- **Coût RAM** : Neutre à positif. Consommation transitoire de Docker (~2,5 Go), purgée dès la fin du job grâce au recyclage immédiat sous forte charge.

### P3. Moteurs SearXNG ciblés & Bangs techniques
- **Mécanisme** :
  - Dans `C:\nokido\searxng\settings.yml` (documentation : [SearXNG Configured Engines](https://docs.searxng.org/admin/settings/settings_engines.html)) :
    Activer et sanctuariser les moteurs techniques non soumis aux CAPTCHAs agressifs : `github`, `gitlab`, `pypi`, `npm`, `archlinux`, `stackoverflow`, `wikidata`.
  - Dans `app/forge_watch_agent.py` (`_moteurs_searxng`, `_searxng`) :
    Pour toute veille tech, forcer l'usage des catégories `it` et des bangs spécialisés (`!gh`, `!pypi`) au lieu de `general`. Isoler strictement la catégorie `science` pour éviter qu'ArXiv ne pollue les requêtes Python/CLI.
- **Garde** : Coupe-circuit par domaine : si la catégorie `it` est muette, émettre une alerte `moteurs_it_indisponibles` plutôt que de déverser la requête dans `science`.
- **Coût RAM** : 0 Mo (conteneur SearXNG existant ~80 Mo).

### P4. Deep-Crawl 1-Hop sélectif via Crawl4AI
- **Mécanisme** :
  - Dans `app/forge_crawl_tool.py`, exploiter les capacités natives de deep crawl de Crawl4AI (documentation : [Crawl4AI Deep Crawling](https://docs.crawl4ai.com/core/deep-crawling/)).
  - Lorsque l'URL retenue est une racine de documentation (ex. `docs.pytest.org`), déployer `BestFirstCrawlingStrategy` avec `max_depth=1`, `max_pages=4`, et un `KeywordRelevanceScorer` ciblant les mots-clés du thème (`pytest-split`).
- **Garde** : Plafond dur : `max_depth=1`, `max_pages=4`, filtre de domaine strict (`include_external=False`). Empêche l'explosion du graphe et la surconsommation mémoire du headless browser Playwright.
- **Coût RAM** : +300 à +500 Mo durant la session de crawl, libérés dès la fermeture du contexte de navigation.

---

## 3. Méthode de mesure de la parité « Veille ≥ CLI Direct »

Pour que la supériorité ou l'égalité de la veille soit un fait prouvé et non une illusion déclarative, la mesure doit être déterministe, automatisée et dépourvue de complaisance LLM.

### Banc d'évaluation fixe (Gold Standard)
Constitution d'un banc permanent de 10 cas représentatifs :
- **5 cas Logiciel / Écosystème** (ex. `pytest-split GitHub Actions`, `jujutsu git-branchless`, `aider architect mode`, `uv lock multi-platform`, `litellm proxy fallbacks`).
- **3 cas Sécurité / CVE** (ex. vulnérabilités récentes, bypass de sandbox, advisory GitHub).
- **2 cas Théorie / Modèles** (ex. architecture de transformer, distillation de raisonnement).

Pour chaque cas, une liste de **3 URLs canoniques de référence** est figée par avance (dépôt officiel, documentation de référence, article/RFC d'origine).

### Métriques objectives et Dénominateur déclaré
1. **Rappel Strict Top-5 (Recall@5)** :
   $$\text{Recall} = \frac{\text{Nombre d'URLs canoniques retrouvées dans le top 5}}{\text{Nombre total d'URLs attendues (30)}}$$
   Dénominateur constant $D = 30$. Tout échec d'infrastructure, timeout ou job non exécuté vaut strictement 0.
2. **Indice de Fraîcheur & Précision d'Extraction** :
   $$\text{Précision Extraction} = \frac{\text{Caractères utiles pertinents extraits (hors chrome)}}{\text{Taille attendue du document principal}}$$
   Pénalise sévèrement les fallbacks `urllib` rendant 88 caractères de chrome JavaScript.
3. **Taux d'Intégrité d'État** :
   $$\text{Taux Intégrité} = \frac{\text{Jobs avec statut cohérent (Succès prouvé ou Bloqué avéré)}}{\text{Total jobs lancés}}$$
   Tout faux vert (`status="completed"` avec transport dégradé) compte comme une régression majeure (-100 points).

### Élimination du biais du Juge LLM
- Aucun LLM ne doit statuer sur la qualité générale ("bon résumé", "pertinent").
- L'évaluation est 100 % algorithmique :
  - Normalisation syntaxique des URLs (suppression des ancres `#`, query params de tracking, normalisation HTTPS/slash).
  - Matching binaire contre la vérité terrain.
  - Vérification de la présence effective des chunks dans SQLite (`%NOKIDO_DATA%\embeddings.db`, tables `rag_chunks` et `rag_fts`).

---

## 4. Désaccords argumentés avec Claude

Claude identifie le défaut n°1 comme étant le *repli silencieux* (F1) et le n°2 comme la *configuration des moteurs SearXNG* (F3). Sans contredire l'existence de ces faits, je conteste leur rang de causalité première.

### Désaccord 1 : Le défaut n°1 n'est pas le silence du repli, c'est l'hypocrisie architecturale du On-Demand
Le repli n'est pas seulement « silencieux », il est actif et falsificateur : il va chercher de faux résultats pour satisfaire artificiellement `n_stored > 0`. Mais pourquoi ce repli s'active-t-il systématiquement ?
Parce que l'infrastructure sous-jacente (Docker Desktop) est assise sur une contradiction : on exige d'elle une réactivité interactive de veille (quelques secondes), tout en la maintenant éteinte pour économiser la RAM, avec un temps de boot à froid réel mesuré entre 240 s et 375 s. 
Le défaut racine n°1 est **l'illusion de disponibilité du substrat Docker**. Prétendre qu'une dépendance lourde peut être réveillée à la volée de manière transparente sans sémaphore d'attente bloquant ni rétention sur l'ensemble de la tâche condamne mathématiquement le pipeline au repli. Le correctif premier est infrastructurel : synchroniser le réveil ou maintenir une disponibilité programmée de la prothèse lors des sessions de veille.

### Désaccord 2 : SearXNG seul ne suffira jamais face au CLI direct
Blâmer uniquement la configuration de SearXNG (moteurs scientifiques au lieu d'IT) occulte la faiblesse intrinsèque du méta-scraping web non authentifié. 
Même avec un `settings.yml` parfaitement ajusté, SearXNG hébergé localement sur une connexion résidentielle/bureau sans pool de proxys rotatifs subit inévitablement les défenses anti-scraping (Cloudflare turnstile, rate-limiting IP, CAPTCHA). Le CLI direct est supérieur parce qu'il tape des API de recherche SaaS industrielles (Google Search, Bing, Brave API) dotées d'index vivants et de zéro friction de blocage.
Vouloir une veille autonome supérieure ou égale au CLI en s'appuyant uniquement sur du scraping SearXNG nu est une impasse. Le salut réside dans **l'hybridation des sources de transport** :
- SearXNG pour le crawl large et les moteurs ouverts (`it`).
- API de découverte directes pour l'écosystème logiciel : API GitHub Search (code/commits/releases sans scraping), PyPI JSON API, et une passerelle API Web souveraine (ex. Brave Search API ou fallback configuré).
