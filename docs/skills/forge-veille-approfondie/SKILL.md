---
name: forge-veille-approfondie
description: >
  Veille bibliographique approfondie Nokido — pipeline autonome 7 étapes
  via `forge_watch_agent.create_job()` + ChainExecutor : keywords expansion
  Ollama → verify_kw Groq llama-8b → SearXNG multi-queries → refine Groq
  llama-70b → crawl pages → ingest RAG → store biblio_raw. Conçu pour
  **tâches de recherche longues** où l'économie de tokens vient du cache
  RAG persistant et de l'autonomie (pas de prompt user répétitif). Triggers :
  utilisateur fournit un **thème exploratoire** (pas une URL précise) et
  veut "veille auto sur X", "recherche approfondie sur Y", "trouve tout ce
  qui existe sur Z", "veille active", "monte un dossier sur W", "watch
  job sur ce sujet", "lance une recherche large", "que se passe-t-il dans
  l'écosystème de V". Pour cibles inconnues à découvrir. **Distinction
  critique** avec `forge-veille-rapide` : approfondie = thème, 7 étapes,
  ~5-15min, ~5-15k tokens cloud. Rapide = URL connue, 0 tokens cloud, ~5s.
---

# forge-veille-approfondie — Pipeline N8N 7 étapes

## Statut

Skill stable basée sur `app/forge_watch_agent.py` + `app/forge_chain_executor.py`
+ `app/forge_biblio_worker.py`. Boucle autonome ChainExecutor reprend les
chains pending au boot du Hub :8766.

## Quand se déclencher

- L'utilisateur cite **un thème** (pas d'URL) : "Spin Fermyon", "BAML
  structured outputs", "WebAssembly AI inference 2026", etc.
- Demande exploratoire : "qu'est-ce qui existe sur X", "trouve-moi des
  sources sur Y", "monte un dossier sur Z".
- Veille **récurrente** sur un sujet large où SearXNG va découvrir
  blog posts, release notes, GitHub issues, papers, HN threads.
- Volume attendu : 5-30 URLs ingérées par run.
- Patience OK : l'utilisateur accepte 5-15min d'autonomie.

## Quand NE PAS se déclencher

- URL précise connue → `forge-veille-rapide`.
- 1-3 pages spécifiques à indexer → `forge-veille-rapide`.
- Latence critique (réponse synchrone) → `forge-veille-rapide`.
- Token budget zéro → `forge-veille-rapide`.

## Workflow

### 1. Construire un thème de qualité

Le thème est l'**unique input** du pipeline. SearXNG l'utilisera après
expansion. Règles :

- **Multi-keywords** : 5-10 mots discriminants (pas une question, pas une
  phrase complète).
- **Année si pertinent** : "2026" pour cibler du récent.
- **Acronymes + nom complet** : "BAML BoundaryML" plutôt que juste "BAML".
- **Termes techniques précis** : "WASI components" plutôt que "WebAssembly".
- **Pas de stopwords** : éviter "comment", "pourquoi", "what is".

Exemples bons :
- `Spin Fermyon WebAssembly framework SpinKube WASI components SDK 2026`
- `BAML BoundaryML LLM structured outputs DSL prompt function typed Python 2026`
- `Karl Friston Free Energy Principle Active Inference unified brain theory`

Exemples mauvais :
- "qu'est-ce que Spin"  ← question, pas thème
- "Spin"                ← trop court, ambigu (rotation, news, fitness…)
- "j'aimerais en savoir plus sur BAML" ← stopwords

### 2. Créer le job watch

Méthode A — direct Python (recommandé, contourne bug 500 sur /api/watch/jobs) :

```python
import os, sys
sys.path.insert(0, os.path.expanduser(r"~\Script python IA\Nokido\app"))
from forge_watch_agent import create_job

chain_id = create_job(
    theme="Spin Fermyon WebAssembly framework SpinKube WASI components 2026",
    idea_id="veille_active",
    # IDENTITE REELLE DE L'APPELANT — remplacer par la tienne :
    #   CLAUDE_VEILLE_APPROFONDIE | ANTIGRAVITY_VEILLE_APPROFONDIE |
    #   CODEX_VEILLE_APPROFONDIE | GEMINI_VEILLE_APPROFONDIE ...
    agent="<TON_AGENT_ID>_VEILLE_APPROFONDIE",
)
print(f"chain_id={chain_id}")
```

> **Signe de TON identite, jamais celle d'un autre agent.** Mesure 2026-07-25 :
> ce snippet portait `CLAUDE_VEILLE_APPROFONDIE` en dur ; AGY a suivi le skill a la
> lettre et ses deux veilles (cognee, ai-powered-search) se sont retrouvees signees
> CLAUDE dans `watch_jobs`. Consequence : le seul agent capable de dire « ce n'est
> pas moi » etait Claude lui-meme, et l'attribution du travail devenait indecidable
> pour tout le monde. Une identite en dur dans un artefact PARTAGE fabrique de
> l'usurpation involontaire — le `agent=` sert la tracabilite multi-surface, pas la
> decoration.

Méthode B — endpoint REST (si le bug 500 est corrigé) :

```bash
curl -X POST "http://127.0.0.1:8766/api/watch/create" \
  -H "Authorization: Bearer ${LAFORGE_HUB_TOKEN}" \
  -H "Content-Type: application/json" \
  -d '{"theme": "...", "idea_id": "veille_active", "agent": "..."}'
```

### 3. Pipeline 7 étapes (autonome, ChainExecutor)

| # | Step | Agent | LLM | Coût |
|---|---|---|---|---|
| 1 | keywords | KeywordAgent | ollama (laforge-qwen) | 0 cloud |
| 2 | verify_kw | VerifyAgent | groq/llama-8b | ~200 tok |
| 3 | search | SearchAgent | native (SearXNG) | 0 |
| 4 | refine | RefineAgent | groq/llama-70b | ~3-8k tok |
| 5 | crawl | CrawlAgent | native (forge_crawl_tool) | 0 |
| 6 | ingest | IngestAgent | native (NPU embed) | 0 |
| 7 | store | StoreAgent | native (biblio_raw) | 0 |

### 4. Suivre l'avancement

```python
from forge_watch_agent import list_jobs
for j in list_jobs(limit=5):
    print(j["id"], j["status"], j["step"], j["theme"][:50])
```

Ou stream SSE temps réel : `GET /api/watch/stream` (Hub :8766).

### 5. Récupérer les résultats

Une fois `status=completed`, les sources sont dans `biblio_raw` :

```python
from forge_biblio_core import list_entries
recent = list_entries(status_filter="reviewed", limit=20)
# ou status_filter="queued" pour celles que biblio_worker traite encore
```

Et les chunks sont dans `rag_chunks` + `rag_fts` (cherchables BM25/FAISS).

### 6. Anchor mission

```python
from forge_self_correction import anchor_solution
anchor_solution(
    problem=f"Veille approfondie sur <theme>",
    solution=f"Lancé chain {chain_id}, attendre completed via list_jobs()",
    example=f"create_job(theme={theme!r}, idea_id='veille_active')",
    domain="rag",
)
```

## Coût mesuré (par run typique)

- **Groq llama-8b** : ~200 tokens (verify_kw)
- **Groq llama-70b** : ~3000-8000 tokens (refine)
- **Ollama local** : variable, gratuit
- **SearXNG** : 0 (instance locale)
- **Crawl** : 0 (forge_crawl_tool)
- **Embed NPU** : ~50ms × N chunks
- **Latence totale** : 5-15min selon profondeur crawl

L'**économie de tokens vient de l'autonomie** : pas de prompt user
itératif, pas de re-explication du contexte, le pipeline fait tout.
Coût marginal de chaque veille additionnelle ≈ constant.

## Comparaison avec forge-veille-rapide

Voir tableau dans `forge-veille-rapide/SKILL.md`. Règle simple :
**URL connue = rapide. Thème exploratoire = approfondie.**

## Patterns de déclenchement

```
"veille auto sur Spin Fermyon"
"recherche approfondie WebAssembly AI 2026"
"monte un dossier sur BAML BoundaryML"
"watch job: Active Inference Karl Friston"
"trouve tout ce qui existe sur LangGraph"
"que se passe-t-il dans l'écosystème WASM côté serveur"
"lance une recherche large sur grid cells AI"
```

## Anti-patterns

```
"indexe https://spinframework.dev"     → rapide (URL connue)
"garde cette page en mémoire"          → rapide
"j'ai déjà l'URL, fais juste ingest"   → rapide
```

## Hooks Nokido

- **ChainExecutor** doit tourner (vérif via `inspector` ou `/health`)
- **biblio_worker** poll `biblio_raw` queued (cf
  `forge_pluripotent_workers.watch_refresher`)
- **SearXNG** + **crawl4ai** = deux CONTENEURS DOCKER, pas des services natifs.
  `forge_services_launcher` ne les démarre PAS. Chaîne réelle :

      ensure_docker()  ->  pose sandbox/docker.wanted (TTL 900 s)
                       ->  forge_docker_keeper releve Docker Desktop
                       ->  conteneurs searxng-laforge (sert :8080)
                                    + laforge-crawl4ai (docker-compose.crawl4ai.yml)

  Le keeper est en **on-demand strict** : si `docker.wanted` a plus de 900 s, il
  passe en `monitor_only` et ne releve RIEN — Docker reste éteint par design, et
  une veille lancée dans cet état cherche dans le vide. Vérifier l'âge du flag
  AVANT de lancer, pas après. Ne jamais démarrer Docker à la main : on
  court-circuite la purge VHD `_wsl_unmount` du keeper.
- **Groq** API key dispo dans `forge_llm_router`
- **Ollama** UP :11434 (laforge-qwen au minimum)

Si l'un manque, le pipeline cale au step concerné (`status=running step=<step>` figé).
PIRE que caler : SearXNG injoignable rend des résultats VIDES sans erreur, et le
pipeline continue jusqu'au bout en produisant des chunks à sec (cf
`gotcha_veille_fabrication_quarantine`). Un job "terminé" n'est donc PAS une
preuve qu'il a trouvé quoi que ce soit — compter les entrées `biblio_raw`.
Diagnostic via `forge-systematic-debugging` (Phase 1 grille anatomique).


## [fusionné depuis laforge-pipeline]

> Section absorbée depuis l'ancienne skill `laforge-pipeline`. Son frontmatter
> d'origine est conservé ci-dessous EN CITATION : laissé en bloc YAML brut, il
> faisait voir une seconde identité de skill aux chargeurs qui cherchent
> `---` + `name:`, d'où des commandes en double côté CLI (constaté sur AGY,
> 2026-08-11 : `/forge-models` et `/laforge-models`).
>
>     name: laforge-pipeline
>     description: Pipeline de veille active Nokido. Lancer, suivre et analyser
>       les jobs de recherche SearXNG automatiques. Chaînage de micro-agents via
>       agent_chain_nodes.

# Nokido Pipeline — Veille Active

## Lancer une veille

```python
# Via run action=python
from forge_watch_agent import create_job
job_id = create_job("mon thème de recherche", idea_id="ma_categorie")
print(job_id)
```

## Suivre les jobs

```
query "SELECT id, theme, step, status, n_ingested, n_stored FROM watch_jobs ORDER BY created_at DESC LIMIT 10"
```

## Pipeline (6 étapes, reprise automatique si interrompu)

1. `keywords` → LLM local (Ollama/Groq) génère 4 requêtes raffinées
2. `verify_kw` → LLM vérifie la pertinence  
3. `search` → SearXNG (port 8080, 0 token)
4. `refine` → LLM score pertinence 1-10
5. `ingest` → RAG vectorisation (≥4/10)
6. `store` → biblio_raw (≥6/10)

## Voir les résultats

```
query "SELECT title, url, status FROM biblio_raw ORDER BY created_at DESC LIMIT 20"
```

## MessageFrame — communication structurée

Tout message entre agents doit utiliser forge_message_frame.MessageFrame :
- `from_agent`, `to_agent`, `action`, `parameters`, `tool_defs`
- Les tool_defs sont injectées automatiquement par Nokido



## [fusionné depuis forge-veille-rapide]

> **[archivé 2026-08-11]** Frontmatter d'origine, neutralisé. Le dossier
> `forge-veille-rapide` a été supprimé, son contenu vit dans cette section.
>
>     name: forge-veille-rapide
description: >
  Veille bibliographique rapide Nokido — ingestion directe d'URL connue dans le
  RAG sans pipeline LLM. Économie maximale de tokens (zéro appel cloud LLM, juste
  crawl + embedding NPU). Triggers : utilisateur fournit une **URL précise** et
  veut "ajouter au RAG", "ingère cette page", "veille rapide", "quick crawl",
  "garde cette URL en mémoire", "indexe cette doc", "ajoute ce site à la
  bibliographie sans recherche élargie", ou tout cas où la cible est connue et
  où la recherche SearXNG serait du gaspillage. Utilise `mcp_laforge-sovereign-
  hub_crawl` puis `/ingest/url` du Hub :8766. Pour 1-N URLs déjà identifiées.
  **Distinction critique** avec `forge-veille-approfondie` : rapide = URL connue,
  zéro LLM cloud, ~5s/URL. Approfondie = thème exploratoire, pipeline 7 étapes
  SearXNG + Groq, plusieurs minutes.
---

# forge-veille-rapide — Ingestion directe URL → RAG

## Statut

Skill stable basée sur outils MCP existants `crawl` + `read` + endpoint Hub
`/ingest/url`. Aucun nouveau module à créer.

## Quand se déclencher

- L'utilisateur fournit **une ou plusieurs URLs précises** (release notes,
  doc officielle, blog post, CHANGELOG GitHub, README, page Web spécifique).
- L'utilisateur demande "indexe cette page", "ajoute au RAG", "garde en
  mémoire", "veille rapide sur X", "quick fetch", "ingère cette doc".
- L'utilisateur signale qu'il a **déjà identifié la source** et ne veut PAS
  qu'on parte chercher avec SearXNG ("c'est ça que je veux", "pile cette
  URL", "exactement cette page").
- Token budget serré : économie maximum, pas de Groq, pas d'Ollama refine.

## Quand NE PAS se déclencher

- Sujet général, thématique, exploratoire → `forge-veille-approfondie`.
- "Trouve-moi des sources sur X" → `forge-veille-approfondie`.
- Veille récurrente sur un thème large → `forge-veille-approfondie`.
- URL inconnue / à découvrir → `forge-veille-approfondie`.

## Workflow

### 1. Crawl direct via MCP

```python
# Tool MCP : mcp_laforge-sovereign-hub_crawl
# Une URL → contenu brut + métadonnées
result = crawl(url="https://example.com/release-notes/v4.0",
               max_depth=1, max_pages=1)
# result = { "url": ..., "title": ..., "content_md": ..., "links": [...] }
```

Pour multi-URLs, **boucle simple** côté client. Pas de SearXNG, pas
d'expansion de keywords.

### 2. Ingestion RAG via /ingest/url

```bash
curl -X POST "http://127.0.0.1:8766/ingest/url" \
  -H "Authorization: Bearer ${LAFORGE_HUB_TOKEN}" \
  -H "Content-Type: application/json" \
  -d '{"url": "https://example.com/release-notes/v4.0",
       "tags": ["spin", "fermyon", "release"],
       "domain": "ia",
       "agent": "<TON_AGENT_ID>_VEILLE_RAPIDE"}'
```

Le hub gère :
- Déduplication via hash md5 chain (cf `forge_biblio_core.insert_biblio_raw`)
- Chunking markdown (`MarkdownChunker`, headers + overlap)
- Embedding via `forge_npu_embedder` (ONNX NPU Radeon 780M, gratuit)
- Insert dans `rag_chunks` + `rag_fts` (BM25 indexable immédiatement)

### 3. Anchor solution (optionnel mais recommandé)

```python
from forge_self_correction import anchor_solution
anchor_solution(
    problem="Veille rapide sur <sujet>",
    solution="Indexé URL <url> via crawl+ingest direct, tag=<tag>",
    example=f"crawl({url!r}) → /ingest/url",
    domain="rag",
)
```

## Coût mesuré

- **LLM cloud** : 0 token
- **LLM local** : 0 token
- **Embedding NPU** : ~50ms par chunk de 512 tokens (gratuit, hardware)
- **Latence totale** : ~3-8s par URL (crawl + chunk + embed + insert)

## Comparaison avec forge-veille-approfondie

| Critère | rapide | approfondie |
|---|---|---|
| Cible | URL connue | Thème exploratoire |
| SearXNG | non | oui (5-10 queries) |
| Groq llama-8b | non | oui (verify_kw) |
| Groq llama-70b | non | oui (refine) |
| Ollama | non | oui (keywords expansion) |
| Pipeline étapes | 2 (crawl + ingest) | 7 (keywords→verify→search→refine→crawl→ingest→store) |
| Latence | 3-8s | 2-15min |
| Tokens cloud | 0 | ~5000-15000 |
| Use case | "indexe cette page" | "veille auto sur X" |

## Patterns de déclenchement

```
"ingère https://spinframework.dev/changelog"
"garde cette URL en RAG: https://docs.boundaryml.com/v0.222"
"quick crawl https://news.ycombinator.com/item?id=12345"
"ajoute cette page sans recherche SearXNG"
"j'ai déjà l'URL, fais juste ingest"
```

## Anti-patterns

```
"veille sur Spin Fermyon"           → approfondie (thème, pas URL)
"qu'est-ce qu'il y a de neuf sur X" → approfondie (exploratoire)
"trouve-moi des sources sur Y"      → approfondie (recherche)
```

