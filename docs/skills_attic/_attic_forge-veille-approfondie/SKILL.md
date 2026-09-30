---
name: forge-veille-approfondie
description: "Veille bibliographique approfondie Nokido — pipeline autonome 7 étapes via `forge_watch_agent.create_job()` + ChainExecutor : keywords expansion Ollama → verify_kw Groq llama-8b → SearXNG multi-queries → refine Groq llama-70b → crawl pages → ingest RAG → store biblio_raw. Conçu pour **tâches de recherche longues** où l'économie de tokens vient du cache RAG persistant et de l'autonomie (pas de prompt user répétitif). Triggers : utilisateur fournit un **thème exploratoire** (pas une URL précise) et veut \"veille auto sur X\", \"recherche approfondie sur Y\", \"trouve tout ce qui existe sur Z\", \"veille active\", \"monte un dossier sur W\", \"watch job sur ce sujet\", \"lance une recherche large\", \"que se passe-t-il dans l'écosystème de V\". Pour cibles inconnues à découvrir. **Distinction critique** avec `forge-veille-rapide` : approfondie = thème, 7 étapes, ~5-15min, ~5-15k tokens cloud. Rapide = URL connue, 0 tokens cloud, ~5s."
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
import sys
sys.path.insert(0, r"~\Script python IA\Nokido\app")
from forge_watch_agent import create_job

chain_id = create_job(
    theme="Spin Fermyon WebAssembly framework SpinKube WASI components 2026",
    idea_id="veille_active",
    agent="CLAUDE_VEILLE_APPROFONDIE",
)
print(f"chain_id={chain_id}")
```

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
- **SearXNG** local UP (forge_services_launcher devrait le démarrer)
- **Groq** API key dispo dans `forge_llm_router`
- **Ollama** UP :11434 (laforge-qwen au minimum)

Si l'un manque, le pipeline cale au step concerné (`status=running step=<step>` figé).
Diagnostic via `forge-systematic-debugging` (Phase 1 grille anatomique).
