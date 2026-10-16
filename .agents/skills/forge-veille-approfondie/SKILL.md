---
name: forge-veille-approfondie
description: "À utiliser quand l'owner veut explorer un thème sans URL connue : « veille sur X », « recherche approfondie », « monte un dossier », « trouve tout ce qui existe sur Y ». Pipeline autonome en 7 étapes (`forge_watch_agent.create_job()` : mots-clés, recherche, tri, crawl, ingestion RAG), 5 à 15 min. URL déjà connue : forge-veille-rapide."
---

# forge-veille-approfondie — Pipeline N8N 7 étapes

## Statut

Skill stable basée sur `app/forge_watch_agent.py` + `app/forge_chain_executor.py`
+ `app/forge_biblio_worker.py`. Boucle autonome ChainExecutor reprend les
chains pending au boot du Hub :8766.

La veille est UNE chaîne parmi d'autres : la capacité générale de chaînage
d'actions (task, run_job, plan/GOAP, orchestrate, swarm, ChainExecutor) est
décrite par la skill `forge-pipeline`. Ici, seulement la chaîne de veille.

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

`create_job()` écrit une ligne `watch_jobs` et 7 nœuds `agent_chain_nodes` dans UNE
transaction (reprise sur verrou par `write_retry`) ; le ChainExecutor les exécute.
`run_watch_job()` est obsolète (il ne fait que déléguer).

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

**Le statut d'un job n'est pas son verdict.** `verdict_chaine(nodes, n_stored, dedup)`
(même module) le déduit des étapes ET de ce qui a été retenu :

| verdict | sens |
|---|---|
| `completed` | rétention non nulle, toutes les étapes terminées |
| `completed_partial` | une étape cassée, mais du résultat a survécu |
| `completed_dedup` | rien de neuf : la base possédait déjà (pas un échec) |
| `completed_empty` | rien retenu, aucune étape cassée (vide assumé) |
| `failed` | une étape obligatoire cassée ET rien retenu |
| `en_cours` | une étape sans statut terminal : pas encore de verdict |
| `indetermine` | étapes illisibles : ni succès ni échec, ne rien conclure |

> **Une purge efface les lignes de `watch_jobs` et `agent_chain_nodes`** (constaté le
> 22/09). Un job absent de ces tables n'est pas un job qui n'a jamais tourné :
> chercher aussi dans `biblio_raw` et le RAG avant de conclure.

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

Règle simple : **URL connue = rapide. Thème exploratoire = approfondie.**
La rapide ingère une source donnée (crawl → MarkdownChunker → rag_chunks + rag_fts) ;
l'approfondie découvre les sources elle-même (mots-clés → recherche → tri → crawl).

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
preuve qu'il a trouvé quoi que ce soit — lire le verdict (§4) et compter les
entrées `biblio_raw`.
Diagnostic via `forge-systematic-debugging` (Phase 1 grille anatomique).

> Historique : ce fichier portait en annexe deux copies fusionnées le 11/08 (l'ancienne
> `laforge-pipeline`, qui décrivait 6 étapes sans le crawl, et une copie de
> `forge-veille-rapide`). Retirées le 14/10 : chacune vit dans sa propre skill, et la
> copie à 6 étapes contredisait le code. Texte intégral dans l'historique git.
