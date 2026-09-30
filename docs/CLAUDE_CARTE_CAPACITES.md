<!-- DEPORTE depuis CLAUDE.md le 2026-09-19 pour tenir le budget du noyau resident.
     Le contenu n'a pas ete modifie : seul son LIEU a change.
     Mesure : cette section pesait 52% de CLAUDE.md, re-facture a chaque tour. -->

# 2. Carte des capacites Nokido (a connaitre par coeur)

> Section de regles **deportee** hors du noyau resident. Elle n'est plus
> chargee a chaque tour ; elle se consulte a la demande (`rag`, `introspect`,
> ou lecture directe). Les pieges qu'elle decrit restent **EXECUTES** par
> `tools/hook_capability_gate.py`, dont les regles vivent dans SON code :
> deporter la prose ne desarme rien.

## 2. Carte des capacites Nokido (a connaitre par coeur)

### Memoire et apprentissage

- `app/forge_self_correction.py` - preflight_check (pipeline 3 tiers RAGEngine
  + FTS5 + LIKE), anchor_error, anchor_solution, session_summary,
  read_lessons, rebuild_fts_index
- `app/forge_rag_engine.py` - RAGEngine : FAISS IndexFlatIP (normalise L2)
  + BM25Okapi + RRF fusion k=60 + rerank cross-encoder local (:8100 — ⚠ DISABLED 2026-08-10)
  avec fallback Etage 1.5 Cloud Cohere (/v2/rerank) + Etage 2 Lexical
  + SIGReg anti-collapse (LeCun 2026) + decroissance exponentielle lambda_decay
  + apply_trust_weight via forge_rag_qualify
- `app/forge_rag_warmup.py` - indexation code source + docs + PDFs au demarrage
- `app/forge_rag_store.py` - storage + MarkdownChunker (headers, overlap)
- `app/forge_rag_qualify.py` - qualification et trust_weight
- `app/forge_rag_truth.py` - verification factuelle des reponses
- `app/forge_rag_cache.py` - cache LRU
- `app/forge_rag_mixin.py` - mixin partage
- `app/forge_rag_index_app.py` - indexation applicative
- `app/forge_hybrid_bridge.py` - bridge hybride BM25 vectoriel
- `app/forge_ingest_self.py` - auto-ingestion
- `app/forge_npu_embedder.py` - ONNX NPU (Radeon 780M via DirectML)
- `app/semantic_scanner.py` - scan semantique du code
- `app/forge_memory.py` - RAM monitoring (PAS semantique, attention)
- `logs/lessons_learned.md` - trace humaine chronologique
- `RAG/embeddings.db` - 531k+ chunks, schema rag_chunks.id TEXT PRIMARY KEY,
  embedding stocke en BLOB float32 binaire (1024D BGE-M3) OU JSON TEXT selon origine.
  `_decode_embedding_blob()` dans forge_rag_engine.py gere les deux formats.
- `tools/forge_embed_auto_trigger.py` - daemon auto-embed chunks NULL via brain_worker
  ZMQ :5557 (⚠ DISABLED 2026-06-03 ; batch 200 chunks, 20 par submit, status=completed, data.vecs)
- `tools/forge_auto_compact.py` - compaction RAG : 20 vieux chunks → 1 résumé ollama
  (domain=compacted), filtre access_count < 3 + created_at < 30 jours
- `tools/forge_session_anchor.py` - fin de session : git diff + ollama summary +
  anchor_solution() + append lessons_learned.md + git push optionnel
- `tools/forge_auto_evolution_loop.py` - daemon autonome : scan heartbeats (10min),
  scan lessons (30min), restart services dégradés, proposals sur 3+ erreurs récurrentes

### Securite et isolation cloud

- `app/forge_semantic_firewall.py` - SemanticFirewall 4 couches avec
  pre_flight (DLP redact + injection detection + ring_check + canary)
  et post_flight (SSRF + social_eng + canary_leak + hallucination + langue)
- `app/forge_sovereign_membrane.py` - wrap / unwrap bidirectionnel avec
  alias HMAC persistants par mission dans membrane.db SQLite WAL.
  Patterns etendus : hostnames *.local *.lan, paths Win/Linux,
  Windows users DOMAIN\\user, containers docker, UUIDs, tokens base64,
  domaines duckdns ddns tailscale
- `app/forge_silo_fragmenter.py::NoiseGuardian` - sanitize IPs MACs CVEs
- `app/forge_integrity.py` - IntegrityRing (MASTER SYSTEM DEV TRUSTED
  COLLAB UNTRUSTED) + capability tokens HMAC
- `app/forge_prompt_guard.py` - detect_injection (15 patterns EN/FR),
  generate_canary, check_canary_leak, Identity Anchor, build_safe_system
- `app/forge_mcp_security.py` - detect_ssrf_beacon
- `app/forge_conv_sanitizer.py` - DLP conversation (redact)
- `app/forge_snapshot.py::preflight_check` - disk db machine_key check
  avant action Master

### Routage LLM multi-provider

- `app/forge_llm_router.py` - LLMRouter.call_cascade avec USE_CASE_CHAINS.
  Depuis commit e1309ed : utilise SemanticFirewall.pre_flight() pour
  filtrer le routage cloud vs local selon DLP / injection
- `app/forge_cascade_oracle.py` - oracle de qualification cascade

### Backends LLM locaux

- `app/forge_ollama.py` - client Ollama (:11434), 12 modeles dont
  laforge-qwen, deepseek-r1:14b, qwen2.5-coder:32b
- `app/forge_llamacpp.py` - bridge llama.cpp
- `tools/forge_services_launcher.py::llamacpp_native` - service port 8080
  auto-detect blob Ollama qwen2.5-coder:7b-instruct-q4_K_M
- brain_worker :5557 ZMQ (embeddings + ONNX NPU) — ⚠ DISABLED 2026-06-03, l'embedder vivant est :8099 via `forge_embed_router`
- LM Studio :1234 OpenAI-compat

### Orchestration

- `app/forge_silo_engine.py` - 6 SiloDomain défensifs (code, security, strategy,
  synthesis, recon, doc)
- `app/forge_orchestrator.py` - ForgeOrchestrator parallel=True
- `app/forge_runner.py` - spawn fire-forget, live_bridge.map mmap IPC
- `tools/nokido_hub.py` - Hub MCP HTTP sur :8766, 13 tools.
  ROOT = auto-detect via Path(__file__).parent.parent (plus hardcodé).
  Auth : FORGE_MCP_TOKEN ; si vide → requetes locales acceptees sans token.
- `tools/nokido_mcp_server.py` - serveur MCP STDIO (Claude Desktop)
- `tools/gemini_poll_daemon.py` - daemon polling autonome (Pattern D2)
- `tools/forge_goap_hub_bridge.py` - planificateur GOAP (BFS forward-chaining)
  câblé hub MCP. Actions : run_shell, run_python, ask_llm, ingest_url,
  search_rag, run_tests. Goals : generate_module, fix_failing_test, ingest_doc.
- `tools/forge_dt_router_wire.py` - bridge DT router → Deno /intent.
  Heartbeat sandbox/dt_router_wire.heartbeat.

### Graph et connaissances

- `app/forge_graph_universal.py` - moteur graph universel (cyber/doc/science)
  exploite vecteurs RAG 1024D comme source native
- `app/forge_graph_ppr.py` - Personalized PageRank power-iteration
- `app/forge_graph_edge_scorer.py` - scoring unifié sémantique+temporel+trust
- `app/forge_graph_lru.py` - cache LRU graph (invalidation sur write)
- `tools/forge_edge_scoring.py` - semantic (TF-IDF cosine) + temporal (7j half-life)
  + trust (domain map) + cooccurrence (SQLite LIKE)
- `tools/forge_graph_lru_expand.py` - GraphLRUCache 512 slots + PPR SQLite
- `tools/forge_cve_propagation_graph.py` - BFS propagation CVE via OSV.dev API
  + networkx DiGraph + DOT export (sans graphviz dep)
- `app/forge_project_state_graph.py` - DAG modules projet (STUB/IMPL/TESTED/BLOCKED)
  + critical_path() DFS + to_dot() export + scan_project() via AST

### Qualite et creation logicielle autonome

- `app/forge_quality_gate.py` - AST parse + pylint >= 7.0 + coverage >= 60%
  + TODO CRITICAL scan. block_if_failing() leve QualityGateError.
- `app/forge_dep_manager.py` - extract_imports() AST + check_missing() importlib
  + install_missing() pip + manage() pipeline dry_run
- `app/forge_spec_clarifier.py` - detect_ambiguities() + generate_questions()
  + formalize_spec() via ollama. ClarificationDialog.run_interactive().

### Sécurité — défensif uniquement

- `tools/forge_cve_osv_fallback.py` - lookup CVE **défensif** (NVD primary + OSV
  fallback), retry backoff, cache sandbox/cve_cache.json

Nokido est un cerveau agentique **défensif**. Le cœur ne porte aucune capacité
offensive et n'en décrit aucune. Les composants de recherche sécurité vivent dans
un dépôt privé séparé.

### Skills marketplace

- `app/forge_clawhub_bridge.py` - ClawHub API + SkillGuardian (review)
- `app/forge_clawhub_autoinstall.py` - auto-install skills approuves

### Context et singletons

- `app/forge_context.py` - registre singletons (rag_engine, gemini_bridge,
  settings, version_manager) - PAS gestion memoire semantique
- `app/forge_context_steadiness.py` - mesure stabilite du contexte
- `app/forge_mmap_context.py::AgentContext` - context manager mmap
- `app/forge_app_context.py` - app_ctx() helper

---

