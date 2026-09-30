# Fiche de sortie — Veille Hybride (v2 2026-09-27 ; v1 2026-09-23)

Corpus : `watch:hybride:` — 21 pages, 476 chunks actifs, 0 chunk `active=0` écarté
(dossier `sandbox/workspace/veille_fiches_dossier_2026-09-27.md`, job `job_8a190f5556bb`).
**Limite DITE** : PATTERNS = ce que chaque page annonce (extrait porteur lu, 900 caractères par page au plus) ;
le corps détaillé des pages n'a PAS été relu. NOKIDO_EXISTING : recon locale du 27/09, niveau PRÉSENT sauf mention.

## 1. PATTERNS
| # | Pattern | Source |
|---|---|---|
| H1 | Fusion par RANG (RRF) : combine des listes aux scores non comparables, sans calibration | `elastic.co/…/rrf.html` ; `qdrant.tech/documentation/concepts/hybrid-queries/` (RRF/DBSF, prefetch) ; `alexgarcia.xyz/blog/2024/sqlite-vec-hybrid-search/` (FTS5 + sqlite-vec + RRF dans SQLite) |
| H2 | Le dense rate l'identifiant exact, le lexical rate le sens : l'hybride couvre les deux | `qdrant.tech/articles/hybrid-search/` : « Dense retrieval can return a document on the right topic but miss an exact identifier copied into the query. » |
| H3 | Poids relatif lexical / dense réglable (alpha) | `weaviate.io/…/search/hybrid` |
| H4 | Retrieve puis re-rank : bi-encodeur large, cross-encodeur sur le top-k | `sbert.net/…/retrieve_rerank/` |
| H5 | Vecteurs sparse appris (SPLADE) | `qdrant.tech/articles/sparse-vectors/` |
| H6 | Late interaction (multi-vecteur) | ColBERT README ; `qdrant.tech/documentation/concepts/vectors/` (dense, sparse, multivecteur) |
| H7 | Contexte ajouté au chunk AVANT indexation, lexical ET dense | `anthropic.com/news/contextual-retrieval` |
| H8 | `bm25()` FTS5 pondérable par colonne | `sqlite.org/fts5.html#the_bm25_function` |
| H9 | Recherche SYNTAXIQUE du code par requêtes sur l'AST | `tree-sitter.github.io` ; `tree-sitter/…/queries/1-syntax.md` |
| H10 | Graphe + communautés pour cadrer le contexte | GraphRAG README |
| H11 | Coût mémoire et latence : quantization, mmap / on_disk, optimizer après chargement massif | `qdrant.tech/…/quantization/`, `…/storage/`, `…/tuning-qdrant-optimizer/` ; `lancedb.com/…/hybrid-search/` |

## 2. NOKIDO_EXISTING
| Pattern | fichier:ligne | Constat |
|---|---|---|
| H1/H4 outil `rag` | `app/forge_mcp_registry.py:7314` `_rag_dense_search` | docstring : « dense (bge-m3 :8099, cosine) + BM25 FTS5 code-tune (k1=1.2 b=0.5), union des candidats, rerank cross-encoder (:8100) ». Fusion = UNION + rerank, **pas RRF**. Ordre rendu quand le reranker est éteint : NON LU. (La v1 citait `:5931` : la fonction a bougé.) |
| H1 autre chemin | `app/forge_dispatchers.py:96` `_rag_search` ; `app/forge_self_correction.py:157` `_ragengine_search` | « FAISS+BM25+RRF » via RAGEngine. **Deux régimes de fusion coexistent** ; quel appelant emprunte lequel : NON ÉTABLI. |
| H4 reranker | :8100 `NokidoLlamaReranker` ; réveil `rerank.wanted` (`app/forge_embed_router.py:330`) | `disabled=true`, à la demande : le rerank n'est PAS garanti sur le chemin de l'outil. |
| H5/H6 | `tools/bench_qdrant_veracrypt.py:62` | sparse et ColBERT générés SYNTHÉTIQUEMENT pour un banc ; absents du chemin de production. |
| H7 | `app/forge_ingest_pipeline.py:201` `add_contextual_prefix` | préfixe STATIQUE `[domaine:source]`, pas le contexte situé rédigé par modèle du patron H7. Partiel. |
| H9 | `app/forge_repo_map_ts.py:71` `parse_tree_sitter` | « Point d'extension déclaré. Rend None tant que la grammaire TS n'est pas installée. » DECLARED. |
| H10 | `app/forge_graph_linker.py:364` `graph_ppr_search` | expansion sémantique + rerank PPR : PRÉSENT ; exécution réelle non mesurée ce jour. |
| filtre `active` | commit `0690e3a84` | chemin LEXICAL filtré `active=1`, OBSERVÉ après restart le 23/09 19:11. Chemin DENSE : non exercé (embedders éteints). |
| mesure | `tools/forge_retrieval_baseline.py:122` `_capturer`, `:150` `main` | banc de capture de `RAGEngine.search` SEUL (rrf_k=60) : ne voit PAS l'union de l'outil `rag` ; jeu `retrieval_queries_v1.json` = 60 requêtes SANS document attendu (clés `cat`, `id`, `q`) ; trois gardes (témoin immuable, RAM ≥ 6 Go, dense vivant). |

## 3. EVIDENCE
- **MEASURED** : filtre `active=1` du chemin lexical (23/09, contrôles positif et négatif ; blackboard
  `discovered_facts/verif_runtime_rag_actif_0690e3a84`).
- **PRÉSENT** (code lu en recon, non exécuté) : le reste de la section 2.
- **Limite** : extraits porteurs des pages, pas lecture intégrale ; aucune affirmation chiffrée des pages n'est reprise ici.

## 4. GAPS
1. Outil `rag` sans reranker = union sans règle de fusion connue (ordre NON LU), alors que RRF (H1) est la fusion
   standard sans calibration et EXISTE déjà dans RAGEngine. À MESURER avant tout geste.
2. Deux régimes de fusion (union + rerank / RRF) sans carte des appelants : une même question peut rendre deux
   classements selon la porte d'entrée.
3. Contexte par chunk statique (H7) : un morceau découpé perd son sujet. Le préfixe `[url] <sujet>` de la veille
   le compense — et c'est lui qui piège les vérifications par un mot du sujet (leçon du 26/09 : témoin hors sujet).
4. Recherche syntaxique (H9) : déclarée, grammaire non installée.
5. Sparse / multi-vecteur (H5/H6) : absents ; coût mémoire non mesuré.
6. v1 (FERMÉ côté lexical) : `active=0` qui ressurgissait en FTS5 — `0690e3a84`.

## 5. MINIMAL_EXPERIMENT (lecture seule ; rien d'armé sans feu vert owner)
Visé : trois bras sur un jeu FIGÉ — union seule (reranker éteint) · RRF des deux listes · union + rerank — métrique
rang du document attendu (MRR@10) et latence p95.
**BLOQUÉE au 27/09 (préconditions mesurées)** : canal dense muet (« aucun backend d'embedding ne répond »), RAM libre
5,5 Go < plancher 6,0 Go, témoins `baseline_rerank_off/on.json` jamais gelés depuis leur mise en attente du 01/09
(session bbf19437). Et même débloqué, le banc existant ne mesure que `RAGEngine` et n'a pas de document attendu :
il faut (1) une fenêtre d'embedding + RAM, (2) des documents attendus dans le jeu, (3) un bras qui appelle
`_rag_dense_search`. Mesurer en régime lexical seul (`--ignorer-dense-muet`) ne départagerait rien : REFUSÉ.
**Point (2) traité le 27/09, en partie** : `tests/baselines/retrieval_verite_terrain_v1.json` — un artefact SÉPARÉ,
comme l'exige le jeu v1 (« la vérité terrain est un autre artefact », jeu jamais édité). A01–A15 étiquetées par
contenance de l'identifiant exact (critère objectif) ; B–E (45 requêtes) NON ÉTIQUETÉES, jugement owner. Biais
DIT : la contenance favorise le bras lexical — sur A, le banc mesurera surtout qu'une fusion ne dégrade pas le lexical.
**Point (1), remesuré le 27/09** : 5,72 Go libres sur 23,7 < 6,0. Réveiller l'embedder ferait passer sous le
plancher : il faut d'abord un geste owner qui libère 2 à 3 Go, puis `nokido_ensure_service{embed,running}` (et rerank).

## 6. NR (rouge d'abord, seulement si ADOPT)
- `test_rag_sans_reranker_fusionne_par_rang` : reranker indisponible ⇒ ordre = RRF des deux listes, et la réponse
  DIT `rerank: INDISPONIBLE` (jamais un ordre muet).
- À garder vert : le NR du filtre `active` (commit `0690e3a84`).

## 7. DECISION
- **ADOPT après mesure** : RRF comme fusion de repli de l'outil `rag` quand le reranker est absent — primitive déjà
  dans RAGEngine, à réutiliser et non à réécrire.
- **ADOPT (lecture seule)** : carte des appelants des deux régimes de fusion (gap 2).
- **DEFER** : contexte situé rédigé par modèle (H7) — un appel modèle par chunk, envisageable seulement pour les
  nouvelles ingestions ; sparse / ColBERT (H5/H6) après mesure mémoire ; tree-sitter (H9), installer une grammaire
  est un geste owner.
- **REJECT** : remplacer SQLite/FTS5 par un moteur externe (Qdrant, Weaviate, LanceDB) — on prend les primitives
  (RRF, prefetch, quantization), pas le moteur.
