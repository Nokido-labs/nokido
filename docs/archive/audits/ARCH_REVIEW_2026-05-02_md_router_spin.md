# Architecture Review — MD Router + Spin Sandbox + BAML Lazy Loading

**Date :** 2026-05-02
**Auteur :** Claude Opus 4.7 (session Nokido)
**Statut :** Brouillon pour validation multi-LLM (Gemini CLI, Ollama qwen2.5-coder, deepseek-r1) avant benchmark
**Review attendu :** critique technique, détection d'angles morts, propositions d'alternatives

---

## 1. Contexte

Économie de tokens sur les `/docs/*.md` (ADR, specs, style, roadmaps) en :
1. Extrayant les décisions structurées via BAML (au lieu d'injecter le MD brut).
2. Cacheant les extractions par sha256 (re-extract uniquement si fichier modifié).
3. Exposant la recherche FTS5 via composant Spin/WASM read-only sandboxé pour les agents externes (Gemini CLI, Cline, futurs agents).

Bench cible (post-validation) : Promptfoo + Langfuse + comparaison raw vs structured.

---

## 2. Inventaire existant (anti-duplication)

| Capability | Module Nokido | État |
|---|---|---|
| Vector store | `app/forge_rag_engine.py` (1717 L) — FAISS IndexFlatIP + RRF k=60 + rerank | ✅ |
| BM25 lexical | idem + `rag_chunks_fts` + `rag_fts` SQLite FTS5 (porter+unicode61) | ✅ |
| NPU embedder | `app/forge_npu_embedder.py` — ONNX MiniLM-L12, DirectML+VitisAI Ryzen | ✅ |
| Reranking sémantique | `app/forge_rag_qualify.py` — qualify_chunk + trust_weight | ✅ |
| LRU cache | `app/forge_rag_cache.py` | ✅ |
| Auto-indexation boot | `app/forge_rag_warmup.py` (code+docs+PDFs) | ✅ |
| Chunking MD | `MarkdownChunker` (headers, overlap) | ✅ |
| Storage | `RAG/embeddings.db` 106,991 chunks, 98,277 sources distincts | ✅ |
| Bench framework | `forge_orchestration_benchmark.py` + `forge_capability_benchmark.py` | ✅ |
| Hub MCP HTTP | `tools/nokido_hub.py:8766` — Streamable HTTP + bearer auth + ring | ✅ |

**Conclusion** : pas de RAG à refaire. Pas de LanceDB ni de sentence-transformers à embarquer. Le manquant est **distribution sandboxée + extraction structurée typée**.

---

## 3. Composants livrés (POC fonctionnel)

### 3.1 BAML semantic router — `app/forge_md_router.py` + `sandbox/baml_pilot/baml_src/md_router.baml`

**Schémas typés (5)** : `MdDocSummary`, `AdrExtract`, `SpecExtract`, `StyleExtract`, `RouterDecision`.

**Fonctions BAML (5)** : `IndexMarkdownDocs`, `RouteQueryToDocs`, `ExtractAdrDecision`, `ExtractSpec`, `ExtractStyle`.

**Client** : `MdRouterFallback = fallback [NokidoLocalLlamaCpp, NokidoLocalOllama]` (anomalie notée : `:8080` héberge SearXNG, pas llamacpp ; fallback réel = Ollama).

**Cache** : SQLite `RAG/md_router_cache.db`, table `md_extract_cache(sha256, rel_path, kind, payload_json, extracted_at, baml_version)`. Hit = 0 token LLM.

**Mesures** :
- ADR-002 (1.4 KB) : 342 tok raw → 217 tok struct = -36 %
- EVENT_SPEC.md (17.8 KB) : 4457 tok raw → ~430 tok struct = -90 %
- Premier appel : ~5500 tok prompt (schéma + contenu), suivants : 0 tok (cache hit)

### 3.2 Spin component Rust — `LaForge/spin_md_query/laforge-md-query/`

**Stack** : Rust 1.95 + spin-sdk 5.2 + wasm32-wasip1.

**Routes** :
- `GET /md_query/health` → `db_chunks`, `db_distinct_sources`, `fts_indexed`
- `GET /md_query/search?q=&topk=&prefix=` → BM25-ranked top-k via FTS5

**Sandbox** :
- `allowed_outbound_hosts = []` → zero egress réseau
- `sqlite_databases = ["embeddings"]` + runtime config absolu → mount read-only via host
- Pas de KV store, pas de filesystem mount

**Mesures** :
- Artifact : 376 KB `.wasm`
- Latence p50 : 6.4 ms (FTS5 + WASI overhead)
- Cold start : 83 ms

**Distribution** : OCI push vers Codeberg / GHCR / registry local `:2`. Documenté dans `spin_md_query/laforge-md-query/README.md`.

### 3.3 Git hooks `.githooks/` versionnés

- `pre-push` : bloque force-push + delete sur main/alpha/dist/hackathon
- `pre-commit` : bloque main + scan secrets (AWS/sk-/ghp_/private keys) + bloque .env|.pem|.key
- `commit-msg` : cap 80 chars + bloque WIP/tmp placeholders
- Activation : `git config core.hooksPath .githooks`

---

## 4. Décisions techniques + rationale

### 4.1 Spin + Rust (et pas Python)

**Pourquoi pas Python ?**
- `spin py2wasm` deprecated mi-2024
- Pas de template `http-py` dans Spin 4.0 (vérifié 2026-05-02)
- `componentize-py` séparé non-trivial pour ce use case

**Pourquoi pas TinyGo / Zig ?** Rust = SDK Spin officiel le plus mature (`spin-sdk 5.2`), SQLite host integration mature, écosystème serde mature.

**Trade-off accepté** : Rust = courbe d'apprentissage si futur contributeur Python-only. Mitigation : tout le code WASM tient en 200 lignes, lib.rs lisible.

### 4.2 SQLite FTS5 au lieu de LanceDB / Qdrant

**Pourquoi pas une vraie vector DB dans WASM ?**
- LanceDB / Qdrant = binaires natifs Rust non-WASM-compilés
- sentence-transformers / BGE = PyTorch, ne tourne pas en WASI
- NPU AMD Ryzen 780M (DirectML / VitisAI) **inaccessible depuis sandbox WASM**

**Pourquoi FTS5 suffit pour ce composant ?**
- Le composant Spin sert le step **lexical/keyword** uniquement
- Le step **vectoriel** reste côté Hub Python (où le NPU est accessible)
- Pattern hybride : Hub fait embedding+rerank, Spin fait FTS5 pré-filtre OU lookup post-rerank

**Trade-off accepté** : pas de découverte sémantique dans le composant Spin seul. Si query "auth" doit matcher un ADR sur "JWT tokens", Hub doit faire le pont.

### 4.3 BAML extraction au lieu d'injection MD brut

**Pourquoi typé, pas plain text ?**
- LLM aval reçoit `AdrExtract { decision, constraints[], invalidates_if }` → traite comme **instructions**, pas comme docs informatives
- Validation au runtime : statut `superseded` ou `deprecated` peut être filtré avant injection
- Cache stable : sha256 → JSON, invalidation auto sur modif

**Trade-off accepté** : premier appel coûte ~5500 tok (schéma + contenu). Amorti dès le 2e appel sur le même fichier. Pour fichiers rarement consultés, gain nul.

### 4.4 rag_fts existant vs proposition utilisateur (recréation FTS5)

**Schéma actuel `rag_fts`** : `chunk_id, text, source, domain` (porter+unicode61 tokenizer).
**Schéma `rag_chunks_fts`** : `text, source, domain` avec `content='rag_chunks'`+`content_rowid='rowid'`.

**Proposition user** : DROP + recreate avec `role_hint` et `quality_score` indexés.

**Rejet** : pas nécessaire. Approche adoptée :
- FTS5 reste sur les colonnes lexicalement utiles (`text, source, domain`)
- Le composant Rust JOIN `rag_chunks` sur `rowid` pour récupérer `role_hint, quality_score, meta` au moment du SELECT
- **Pas de migration**, **pas de re-indexation**, **pas de risque de désync**

Coverage mesurée :
- `role_hint` : 74/74 chunks docs+ADR (100 %)
- `quality_score` : 6/74 (8 %, sparse — fallback à 1.0 dans le code Rust)

### 4.5 Sandbox vs intégration directe au Hub

**Pourquoi un microservice Spin séparé du Hub :8766 ?**
- Le Hub a accès à tout (ring 0 master tokens, capability tokens HMAC, write paths)
- Le composant Spin = read-only, deny-by-default réseau, isolation WASM
- Distribuable en OCI (déploiement sur autres machines / sandbox de tests / agents externes)

**Trade-off accepté** : duplication d'une portion de surface (FTS5 /search). Hub continue d'exposer son `mcp_laforge-sovereign-hub_query` riche, Spin sert un subset cheap.

---

## 5. Choix architecturaux à valider

### Q1 — JOIN runtime vs FTS5 schema enrichi
Adopté : SQL `SELECT … FROM rag_fts JOIN rag_chunks USING(rowid) WHERE rag_fts MATCH ?` au moment du query.
Alternative : `DROP TABLE rag_fts; CREATE VIRTUAL TABLE rag_fts USING fts5(text, source, domain, role_hint, quality_score, content='rag_chunks');`

**Question pour reviewer** : la JOIN runtime est-elle réellement aussi performante que l'index multi-colonne ? Sur 106,991 chunks avec FTS5 BM25 retournant ~50 candidats, la JOIN ajoute combien de ms ?

### Q2 — Embedding query côté Hub vs externe
Adopté : Spin component fait FTS5 only. Si query nécessite vector similarity, l'agent appelant doit appeler le Hub d'abord (NPU embed).

**Question pour reviewer** : ajouter un endpoint Hub `/api/embed?q=` qui retourne juste le vecteur (sans search), pour que Spin puisse faire un cosine fusion local ? Ou l'inverse ne sert à rien sans le matrix complet en mémoire ?

### Q3 — Bearer auth dans Spin ?
Non implémenté. `allowed_outbound_hosts=[]` est l'isolation, pas l'auth.

**Question pour reviewer** : sur réseau home/local, port 3030 ouvert sans auth est-il acceptable ? Ou bind localhost + Hub agit comme reverse proxy authentifié vers Spin ?

### Q4 — Désynchronisation rag_chunks / rag_fts
Triggers AFTER INSERT/DELETE/UPDATE non audités. Re-index possible via `forge_post_commit.py` mais coverage incertain.

**Question pour reviewer** : forge_post_commit re-indexe-t-il les FTS5 explicitement, ou compte sur les triggers SQLite ?

### Q5 — BAML on local Ollama only
`MdRouterFallback = [NokidoLocalLlamaCpp, NokidoLocalOllama]`. Le premier ne marche pas (port 8080 = SearXNG). Le second marche (Ollama redémarré 2026-05-02).

**Question pour reviewer** : faut-il :
(a) Corriger CLAUDE.md §8 (mention erronée llamacpp:8080)
(b) Lancer un vrai llama.cpp sur :8080 + bouger SearXNG
(c) Drop NokidoLocalLlamaCpp du fallback BAML
?

---

## 6. Risques + mitigations

| Risque | Probabilité | Impact | Mitigation |
|---|---|---|---|
| Spin component out-of-sync avec embeddings.db après ingestion | M | M | Health check `db_chunks` count drift > X % alerte |
| BAML cache stale après refacto Nokido module renames | M | L | sha256 par contenu, pas par chemin → robust à rename |
| Cold start 80 ms sur Spin = impact UX sur premier query | L | L | Keep-alive Spin process dans `forge_services_launcher.py` |
| Codeberg push fuite token registry | L | H | `.spin login` + token scope minimum + rotation |
| Rust toolchain divergence cross-machine | L | L | Pinner `rust-toolchain.toml` (à ajouter) |
| Composant WASM exécute requête FTS5 user-injectable | M | M | Token filter ≥3 chars + LIMIT 20 + read-only DB |

---

## 7. Métriques cibles post-bench

À mesurer via Promptfoo + Langfuse (à installer après validation) :

| KPI | Baseline (raw MD inject) | Cible (BAML+Spin) |
|---|---|---|
| Tokens prompt moyen / query | ~3000 | ~300 |
| Latence p50 retrieval | ~50 ms (Hub query MCP) | ~10 ms (Spin direct) |
| Hallucination rate sur ADR-status | TBD | <5 % |
| Cache hit rate sur 100 queries | 0 % | >80 % |
| Coût LLM cloud / jour (1000 queries) | TBD | -85 % |

---

## 8. Demande aux reviewers

Critiquer en priorité :
1. **Q1-Q5** ci-dessus (décisions ouvertes)
2. Tout angle mort architectural (sécurité, désync, deadlock SQLite, race condition NPU)
3. Alternatives plus simples qu'on aurait ratées (existe-t-il un composant Spin officiel `sqlite-fts5` qu'on aurait pu fork au lieu de coder from scratch ?)
4. Stratégie de bench (Promptfoo vs alternative ?)

Format de réponse souhaité :
```
## Critique <reviewer name>
- Q1: [agree/disagree + pourquoi]
- Q2: ...
- Q5: ...
- Angles morts détectés: [...]
- Alternatives simples: [...]
- Verdict: GO | GO with caveat | NO-GO
```
