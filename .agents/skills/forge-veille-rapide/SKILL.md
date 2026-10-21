---
name: forge-veille-rapide
description: "À utiliser quand l'owner donne une ou plusieurs URL précises à garder en mémoire : « ingère cette page », « ajoute au RAG », « indexe cette doc ». Récupère le contenu (source .md ou crawl), le découpe et l'insère dans rag_chunks et rag_fts, sans LLM cloud. /ingest/url seul ne crée qu'une fiche biblio. Thème sans URL : forge-veille-approfondie."
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
> 3. **Écriture** : corrigée le 15/10, voir Workflow §3 ci-dessous
>    (`forge_db_path.ecrire_chunk` dans `write_retry`, depuis un job côté hub). Le schéma
>    de `rag_fts` est `fts5(chunk_id UNINDEXED, text, source UNINDEXED, domain UNINDEXED)`,
>    PAS `(id, source, text)`.
> 4. Exécuter en **`run_job` détaché online** (multi-URLs = long ; cap 70 s hub).
>    Modèle : `sandbox/workspace/veille_github_bp3.py` (job du 21/08).
>
> Le FTS/BM25 est cherchable immédiatement ; l'embedding suit quand le daemon
> embed-trigger se réveille. `/ingest/url` reste utile pour la FICHE biblio
> (traçabilité), pas pour le RAG. La section « Workflow » ci-dessous décrit
> l'ANCIEN chemin — la garder comme référence de la fiche biblio seulement.

## Dépôt GitHub : l'outil existe, ne pas le réécrire (2026-10-18)

Un **dépôt GitHub** (code, `docs/`, README) s'ingère EN ENTIER par
`tools/forge_ingest_github_repo.py --url https://github.com/<owner>/<repo>`
(`run action=run_job ... online=true`) : tarball public via la stdlib (tout compte), découpage
de `forge_gitingest_sdk_ingest`, source `github:<owner>/<repo>/<chemin>` (retrait propre),
dédup `skipped_dedup`. Payé le 18/10 : un script maison n'a ingéré que les README (325
fragments) là où l'outil en a rendu 7 731, dont `docs/AB-RESULTS.md` — la mesure qui
justifiait la veille. Vérifier ensuite par un terme témoin en `rag_chunks_fts`.

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

## Workflow (chemin PROUVÉ le 21/08 : le contenu devient cherchable)

1. **Contenu** : GET direct de la source `.md` quand elle existe (`raw.githubusercontent.com/...`) ;
   sinon l'outil `crawl` du hub (Crawl4AI). Les sites Google/GitHub Docs sont des coquilles JS :
   le crawl n'y rend que ~400 octets.
2. **Découpe** : `forge_rag_store.MarkdownChunker.chunk(md, 2000, 200)`.
3. **Écriture** (corrigée le 15/10) : dans `forge_db_path.write_retry(lambda c: ...)`, un appel
   à `forge_db_path.ecrire_chunk(c, source, domain, texte)` par fragment, depuis le job côté hub,
   jamais depuis un processus client ni par un `sqlite3.connect()` nu.
   - `ecrire_chunk` pose l'`id` canonique `chunk_id(source, texte)` = `sha256(source|texte)[:16]`
     (règle d'or 3). L'ancienne recette hachait `source+text` sans séparateur : identifiants
     non canoniques, déduplication ratée. Il ne tronque jamais en silence (`cap` dit ce qu'il écarte).
   - Les triggers du 01/09 (`fba78f3f1`) indexent alors `rag_chunks_fts`, **que lit la recherche du
     moteur** (`RAGEngine._scores_lexicaux`, vérifié par Codex le 15/10).
   - `rag_fts` est une AUTRE table, toujours lue par une quarantaine de modules (`introspect`,
     `hook_recon_first`, le preflight des leçons, le connecteur des pairs) : pour que la veille y
     soit visible aussi, y insérer `(chunk_id, text, source, domain)`, comme le font `anchor_*`.
   - ⚠️ **Jamais `WHERE chunk_id = ?` sur `rag_fts`** (ni DELETE ni SELECT) : la colonne est `UNINDEXED`,
     chaque appel est un PLEIN SCAN de la table, et un DELETE tient le verrou d'écriture pendant tout ce temps
     (payé le 15/10 : veille figée 20 min à 17 Mo/s de lecture, `introspect` du hub expiré, job tué).
     Forme qui marche : existence par la clef primaire `SELECT 1 FROM rag_chunks WHERE id = ?` ; si le fragment
     existe déjà, sa présence dans `rag_fts` se vérifie par `rag_fts MATCH '"<mots du texte>"' AND chunk_id = ?`
     (indexé). Une transaction par source (`BEGIN IMMEDIATE` … `COMMIT`) : un arrêt ne laisse pas de demi-écriture.
     Modèle : `C:/tmp/drafts/rsi/veille_claude_desktop.py`.
4. **Exécution** : un `run_job` détaché (plusieurs URL = long ; plafond 70 s des appels hub).
   Modèle : `sandbox/workspace/veille_github_bp3.py`.
5. **Vérifier** là où le moteur lit : `rag_chunks_fts MATCH '<terme témoin de la page>'` doit
   rendre des fragments (et `rag_fts MATCH`, si on l'a alimentée). Un `inserted:1` ne prouve rien.

Le FTS/BM25 est cherchable aussitôt ; l'embedding suit quand le daemon embed-trigger se réveille.

## Fiche biblio seule (ancien chemin, traçabilité — ne met PAS le contenu dans le RAG)

### Crawl direct via MCP

```python
# Tool MCP : mcp_laforge-sovereign-hub_crawl
# Une URL → contenu brut + métadonnées
result = crawl(url="https://example.com/release-notes/v4.0",
               max_depth=1, max_pages=1)
# result = { "url": ..., "title": ..., "content_md": ..., "links": [...] }
```

### Fiche via /ingest/url

```bash
curl -X POST "http://127.0.0.1:8766/ingest/url" \
  -H "Authorization: Bearer ${LAFORGE_HUB_TOKEN}" \
  -H "Content-Type: application/json" \
  -d '{"url": "https://example.com/release-notes/v4.0",
       "tags": ["spin", "fermyon", "release"],
       "domain": "ia",
       "agent": "<TON_AGENT_ID>_VEILLE_RAPIDE"}'
```

Ce que fait réellement /ingest/url (mesuré le 21/08) : une fiche `biblio_raw` (titre, URL,
description), dédupliquée par `forge_biblio_core.insert_biblio_raw`. Le CONTENU n'atteint pas
`rag_chunks`/`rag_fts` : pour le rendre cherchable, suivre le Workflow ci-dessus.

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
