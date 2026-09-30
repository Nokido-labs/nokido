---
name: forge-veille-rapide
description: "Veille bibliographique rapide LaForge — ingestion directe d'URL connue dans le RAG sans pipeline LLM. Économie maximale de tokens (zéro appel cloud LLM, juste crawl + embedding NPU). Triggers : utilisateur fournit une **URL précise** et veut \"ajouter au RAG\", \"ingère cette page\", \"veille rapide\", \"quick crawl\", \"garde cette URL en mémoire\", \"indexe cette doc\", \"ajoute ce site à la bibliographie sans recherche élargie\", ou tout cas où la cible est connue et où la recherche SearXNG serait du gaspillage. Utilise `mcp_laforge-sovereign- hub_crawl` puis `/ingest/url` du Hub :8766. Pour 1-N URLs déjà identifiées. **Distinction critique** avec `forge-veille-approfondie` : rapide = URL connue, zéro LLM cloud, ~5s/URL. Approfondie = thème exploratoire, pipeline 7 étapes SearXNG + Groq, plusieurs minutes."
---

# forge-veille-rapide — Ingestion directe URL → RAG

## Statut

> ⚠️ **CORRIGÉ 2026-08-21 (mesuré).** `/ingest/url` ne fait PAS ce que ce skill
> promettait : il crée une fiche **`biblio_raw`** (métadonnées : title/url/
> description) — le CONTENU n'atteint JAMAIS `rag_chunks`/`rag_fts`, donc rien
> n'est cherchable. Preuve : 4 URLs ingérées → `inserted:1` chacune, puis
> `SELECT ... FROM rag_chunks WHERE source LIKE '%<url>%'` → **0 ligne**.
> Le chemin qui MARCHE (prouvé, 105 chunks cherchables le 21/08) :
>
> 1. **Contenu** : GET direct de la **source `.md`** quand elle existe
>    (`raw.githubusercontent.com/...` — les sites Google/GitHub Docs sont des
>    shells JS, trafilatura y rend ~400 octets) ; sinon `crawl` (Crawl4AI).
> 2. **Chunk** : `forge_rag_store.MarkdownChunker.chunk(md, 2000, 200)`.
> 3. **Insert** : `INSERT OR IGNORE INTO rag_chunks (id, source, text, domain)`
>    avec `id = sha256(source+text)[:16]` (règle d'or 3), puis si `rowcount`
>    (seule preuve que l'INSERT mord) :
>    `INSERT INTO rag_fts (chunk_id, text, source, domain)` — le schéma FTS
>    est `fts5(chunk_id UNINDEXED, text, source UNINDEXED, domain UNINDEXED)`,
>    PAS `(id, source, text)`.
> 4. Exécuter en **`run_job` détaché online** (multi-URLs = long ; cap 70 s hub).
>    Modèle : `sandbox/workspace/veille_github_bp3.py` (job du 21/08).
>
> Le FTS/BM25 est cherchable immédiatement ; l'embedding suit quand le daemon
> embed-trigger se réveille. `/ingest/url` reste utile pour la FICHE biblio
> (traçabilité), pas pour le RAG. La section « Workflow » ci-dessous décrit
> l'ANCIEN chemin — la garder comme référence de la fiche biblio seulement.

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
       "agent": "CLAUDE_VEILLE_RAPIDE"}'
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
