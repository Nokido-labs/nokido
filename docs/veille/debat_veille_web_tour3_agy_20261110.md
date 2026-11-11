# Débat Veille Web — Tour 3 (Antigravity) : Moteurs Résidentiels, Écosystème Open Source, Sécurité GitHub et Arbitrage

Date : 2026-11-10  
Auteur : Antigravity (AGY)  
Destinataire : Owner Nokido / Claude  
Contexte : Avis d'expertise demandé par l'owner sur le Lot 1 « souverain gratuit » (moteurs sans blocage, projets open source de veille, innocuité GitHub API et sanctuarisation de Gitingest).

---

## 1. Moteurs qui passent depuis une IP résidentielle sans clé payante

Face aux blocages constatés sur les généralistes (Google silencieux, Brave/DDG/Startpage en CAPTCHA/429), plusieurs moteurs indépendants ou spécialisés restent exploitables via SearXNG sous IP résidentielle sans coût.

| Moteur SearXNG | Nom `settings.yml` | Clé requise | Limite connue | Niveau de confiance | Preuve / Réf. officielle |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **Wiby** | `wiby` (`json_engine`) | Non | Web rétro/indie, zéro JS, pas d'actu chaude | **SÛR** | [wiby.me/json](https://wiby.me/json/) & [searxng/json_engine](https://docs.searxng.org/dev/engines/online/json_engine.html) |
| **Marginalia** | `marginalia` | Oui (gratuite) | Web textuel/académique/blogs, 1 req/s | **SÛR** | [about.marginalia-search.com/api](https://about.marginalia-search.com/article/api/) & [engines/marginalia.py](https://github.com/searxng/searxng/blob/master/searx/engines/marginalia.py) |
| **Moteurs `it`** | `github`, `pypi`, `stackoverflow`, `mdn` | Non | Périmètre technique pur, rate-limit IP public (ex: GitHub 10 req/min) | **SÛR** | [searxng/engines](https://github.com/searxng/searxng/tree/master/searx/engines) |
| **Mwmbl** | `mwmbl` | Non | Index non-commercial restreint, latence variable | **PROBABLE** | [searxng/engines/mwmbl.py](https://github.com/searxng/searxng/blob/master/searx/engines/mwmbl.py) |
| **Mojeek** | `mojeek` | Non | Crawler propre (UK). Déclenche un PoW (Proof of Work) anti-bot sous charge | **PROBABLE** | [searxng/engines/mojeek.py](https://github.com/searxng/searxng/blob/master/searx/engines/mojeek.py) |
| **Qwant** | `qwant` (`qwant_categ: web`) | Non | Index Bing + propre. Sensible aux rafales (soft-ban temporaire) | **PROBABLE** | [searxng/qwant.html](https://docs.searxng.org/dev/engines/online/qwant.html) |
| **Yep** | `yep` | Non | Moteur Ahrefs. Interstitiels Cloudflare ponctuels sur user-agent bot | **À MESURER** | [searxng/engines/yep.py](https://github.com/searxng/searxng/blob/master/searx/engines/yep.py) |
| **Presearch** | `presearch` | Non | Requête multi-étapes, 403 récurrents via Cloudflare | **À MESURER** | [searxng/issues/2873](https://github.com/searxng/searxng/issues/2873) |
| **SearXNG Publics**| `searx` | Non | Dépend de la santé des instances distantes (latence, bans) | **À MESURER** | [searx.space](https://searx.space/) & [searxng/engines/searx.py](https://github.com/searxng/searxng/blob/master/searx/engines/searx.py) |

### Analyse opérationnelle pour Nokido :
1. **Catégorie `it` (SÛR)** : C'est le joyau pour la veille logicielle. Tous ces moteurs ciblent des API JSON publiques dédiées (PyPI, MDN, StackOverflow) et non des pages HTML protégées par Cloudflare. Aucun blocage observé en IP résidentielle.
2. **Wiby + Marginalia (SÛR)** : L'association parfaite pour trouver des articles de fond, documentations auto-hébergées et blogs techniques indépendants sans aucune publicité ni anti-bot. Marginalia fournit une clé d'API gratuite sur simple demande pour les projets open source/personnels.
3. **Mojeek + Qwant (PROBABLE)** : Utiles en complément généraliste, mais exigent une cadence modérée (1 requête toutes les 2-3 secondes) pour ne pas déclencher le challenge Proof-of-Work de Mojeek ou le rate-limit de Qwant.

---

## 2. Projets Open Source de veille et recherche autonome : Analyse et réutilisation

Les projets récents répondent tous au même problème : concilier recherche d'informations, lecture approfondie de sources et synthèse par LLM.

| Projet | Mécanisme de recherche & contournement anti-bot | Docker / Stack | Licence | Maturité | Verdict pour Nokido |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **Vane (ex-Perplexica)** | S'appuie entièrement sur **SearXNG** en backend. Pas de contournement interne, requêtes JSON directes. | Docker (Next.js + Node) | MIT | Forte (~18k★) | **Ne pas dupliquer**. Nokido dispose déjà de son propre agent (`forge_watch_agent.py`) et de son SearXNG. |
| **GPT-Researcher** | Moteurs modulaires (Tavily, DuckDuckGo, SearXNG). Extraction BeautifulSoup / Playwright. | Python pip (Docker optionnel) | Apache-2.0 | Très forte (~19k★) | **Inspirant mais redondant**. Leur prompt de filtrage des sources est bon, mais la stack Nokido est plus souveraine. |
| **Stanford STORM** | Retriever pluggable (Bing, You, SearXNG). Multi-perspective questioning. | Python pur | MIT | Académique (~15k★) | **Garder l'algorithme** de décomposition en perspectives de veille, mais pas la dépendance de code. |
| **Scrapling** (D4Vinci) | Framework de scraping furtif (anti-detect, adaptive parsing, bypass Cloudflare Turnstile). | Python pur (`pip`) | BSD-3 | Émergente / active (~4k★) | **À RÉUTILISER (pépite)**. Ultra-léger, sans Docker lourd, parfait comme fallback pour Crawl4AI si une page résiste. |
| **Jina Reader** (`r.jina.ai`) | Proxy web-to-markdown optimisé LLM. Gère JS, images, cookie banners. | SaaS gratuit / Docker | Apache-2.0 | Très forte | **À RÉUTILISER en repli** : préfixer une URL par `https://r.jina.ai/` extrait un markdown propre sans calcul local. |
| **Firecrawl** | Moteur complet d'extraction web vers LLM (Playwright + Redis + BullMQ). | Stack Docker lourde | AGPL-3.0 | Très forte (~24k★) | **À ÉVITER**. Trop lourd (mémoire, workers) par rapport aux besoins stricts de Nokido. |

### Règle d'or Nokido (Pas de système parallèle) :
- **À intégrer / étendre** :
  1. Conserver **SearXNG** comme pivot de métarecherche local (moteurs `it` + indépendants).
  2. Adopter **Crawl4AI** pour le crawl structuré (`llms.txt`, sitemaps, lecture propre).
  3. Intégrer la bibliothèque Python légère **`scrapling`** comme brique de secours interne sous `app/` ou `tools/` uniquement si Crawl4AI rencontre un blocage Cloudflare strict (sans empiler un nouveau conteneur).

---

## 3. Exploitation de l'API GitHub sans risque pour le compte

L'inquiétude de l'owner est légitime : un bannissement de compte GitHub pour abus d'API est destructeur. Cependant, le respect strict de la doctrine GitHub élimine 100 % du risque.

### 3.1 Limites officielles GitHub (REST API)
*Source officielle : [GitHub REST API Rate Limits](https://docs.github.com/en/rest/using-the-rest-api/rate-limits-for-the-rest-api) & [Best Practices](https://docs.github.com/en/rest/using-the-rest-api/best-practices-for-using-the-rest-api)*

1. **Quota primaire (REST)** :
   - **Non-authentifié** : 60 requêtes / heure par IP (**SÛR**).
   - **Authentifié (PAT / OAuth)** : 5 000 requêtes / heure (**SÛR**).
2. **Search API (`/search/*`) — Régime d'exception strict** :
   - **Non-authentifié** : **10 requêtes / minute** par IP (**SÛR**).
   - **Authentifié** : **30 requêtes / minute** (**SÛR**).
3. **Secondary Rate Limits (Règles anti-abus et concurrence)** :
   - Déclenchées par des requêtes concurrentes en rafale ou plus de 100 requêtes/minute même avec du quota restant (**SÛR**).
   - Sanction : HTTP `403` ou `429` avec message `"You have triggered an abuse detection mechanism"` ou `"secondary rate limit"`.

### 3.2 Bonnes pratiques obligatoires pour la veille Nokido
1. **Requêtes conditionnelles (`ETag` / `If-None-Match`) — L'arme absolue** :
   - Lorsque Nokido interroge un dépôt (ex: `/repos/{owner}/{repo}/releases`), GitHub renvoie un en-tête `ETag`.
   - À l'interrogation suivante, Nokido envoie l'en-tête `If-None-Match: <etag>`.
   - Si rien n'a changé, GitHub renvoie **`304 Not Modified`** avec un corps vide.
   - **Règle officielle : Les réponses HTTP 304 NE SONT PAS DÉCOMPTÉES du rate limit horaire !** (**SÛR**).
2. **Pilotage par les en-têtes de réponse** :
   - Lire systématiquement `x-ratelimit-remaining` et `x-ratelimit-reset`.
   - Si un code `403`/`429` survient, respecter à la lettre l'en-tête `Retry-After` (en secondes) avant toute nouvelle requête.
3. **Exécution strictly séquentielle** :
   - Zéro thread concurrent sur l'API GitHub ; pause minimale de 1 seconde entre deux appels de recherche.

### 3.3 Diagnostic du moteur SearXNG `github`
- Dans le code source (`searx/engines/github.py`), le moteur appelle :  
  `https://api.github.com/search/repositories?sort=stars&order=desc&{query}`
- Il fonctionne **sans clé d'API par défaut (`require_api_key = False`)**.
- **Conséquence directe** : Il tape sur le quota non-authentifié de l'IP (10 req/min). Si SearXNG lance 5 requêtes de veille générale contenant le mot "python" et que le moteur github est actif dans `general`, l'IP est temporairement throttled (403).

### 3.4 Recommandations d'isolation du risque
1. **Désactiver `github` de la catégorie `general` dans SearXNG** : Ne l'activer QUE dans la catégorie `it` ou pour des requêtes logicielles explicites.
2. **Jeton d'isolation dédié (Recommandé)** :
   - Créer un **Fine-grained Personal Access Token (PAT)** dédié sur GitHub, sans aucun droit d'écriture, restreint à la lecture des dépôts publics (`Public Repositories (read-only)`).
   - Ce jeton n'a accès à aucune organisation privée, aucune clé SSH, aucun droit de compte. Même en cas de bug de boucle infinie, seul ce token de veille est bridé, le compte principal de l'owner reste 100 % indemne.
3. **Sanctuarisation absolue de Gitingest (:9200)** :
   - Le sidecar local Gitingest clone/analyse les dépôts localement via `git` ou télécharge le zip source. Il n'utilise pas la Search API de GitHub et ne risque aucun blocage de compte.
   - **Directive** : Ne modifier aucun paramètre, port ni route de Gitingest (:9200) dans cette refonte.

---

## 4. Verdict d'AGY : Ce que je valide et ce que j'amende au Lot 1

Le Lot 1 « souverain gratuit » retenu par l'owner est **la bonne décision architecturale**. Il préserve l'autonomie locale sans abonnement récurrent. 

### Ajustements concrets recommandés par AGY :

1. **SearXNG : Spécialisation stricte des catégories** :
   - *Problème constaté* : En catégorie `general`, les moteurs commerciaux (Brave, Startpage, DDG) se font bloquer et polluent le diagnostic.
   - *Action* : Pour toute veille logicielle/système de Nokido, requêter explicitement `categories: it`. Ne solliciter les moteurs généralistes que si `it` est vide.
   - *Ajout de moteurs légers* : Ajouter `wiby` (via `json_engine`) et `marginalia` (avec clé gratuite) dans `settings.yml` pour couvrir le web tech indépendant sans blocage.

2. **Désamorcer le piège GitHub dans SearXNG** :
   - Retirer le moteur `github` de la catégorie `general` de SearXNG pour éviter qu'il n'épuise silencieusement le quota IP de 10 req/min.
   - Réserver GitHub Search aux requêtes de la catégorie `it` ou passer par un token read-only isolé.

3. **Crawl & Atterrissage : Crawl4AI avec repli Scrapling** :
   - Crawl4AI est parfait pour les documentations (`llms.txt`, sitemaps, parsing markdown rapide).
   - Si Crawl4AI échoue face à une protection anti-bot stricte (ex: Cloudflare Turnstile sur un blog technique), invoquer la bibliothèque Python `scrapling` en repli local direct, sans déployer une stack lourde comme Firecrawl.

4. **Sanctuarisation de Gitingest** :
   - Gitingest (:9200) reste le canal exclusif d'ingestion des dépôts complets pour le RAG. Il ne doit subir aucune modification lors de ce chantier.

5. **Statut honnête validé** :
   - Maintien strict du statut `bloque_par_dependance` (spécifié au Tour 2) en cas de SearXNG éteint ou d'IP temporairement bridée, bannissant tout repli silencieux vers l'académique pour les thèmes logiciels.
