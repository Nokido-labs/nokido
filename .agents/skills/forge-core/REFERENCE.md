# Nokido — Reference : module inventory

Complete inventory of the 196 `forge_*.py` modules in `app/`. Load when the user asks where something lives or what a specific `forge_*` module does.

> Convention: sizes in KB. `[HOT]` = modified in last 48h. Files without notable docstring just list their primary classes.

## Core orchestration (8 modules, ~170 KB)

| Module | Size | Role |
|---|---|---|
| `forge_silo_engine` | — | Silo definitions (7 domains), `MODEL_MAP`, `MODEL_MAP_FAST`, `DOMAIN_TO_USE_CASE`, `KnowledgeGuardian` |
| `forge_autonomous_orchestrator` | 15.7 | `DAGBuilder` constructs DAG from `ParsedIntent` via `DynamicPipelineConstructor` or LLM fallback |
| `forge_orchestrator` | 27.7 | Engrid v3 Layer 2. Full multi-silo chain |
| `forge_dispatch` | 7.0 | Basic dispatcher |
| `forge_dispatch_ai` | 32.2 | AI-routed dispatch |
| `forge_dispatch_network` | 23.5 | Network-level routing |
| `forge_at_dispatch` | 58.1 | TUI @-command dispatcher (~10 registered commands incl. @scan, @skill, @evolve, @rag, @agents, @ids, @ollama, @ssh, @web, @services, @graph, @ragas, @agentic) |
| `forge_silo_fragmenter` | 24.4 | Siloed Fragmentation Engine + Noise Guardian v1.0 — sovereign pipeline for chunking |

## LLM routing & backends (15 modules, ~244 KB)

| Module | Size | Role |
|---|---|---|
| `forge_llm_router` | 32.8 | **Main router.** 24 providers, 12 cascades, env keys, rate limits. See BACKENDS.md |
| `forge_core_models` | 60.8 | Model registry + metadata |
| `forge_ollama_bridge` | 33.9 | Ollama wrapper with retry + streaming |
| `forge_openrouter` | 24.5 | OpenRouter-specific bridge |
| `forge_gemini_bridge` | 15.9 | Gemini API wrapper |
| `forge_llm` | 17.9 | Generic LLM abstraction |
| `forge_litellm_bridge` | 13.2 | LiteLLM proxy integration |
| `forge_ollama` | 11.8 | Low-level Ollama client |
| `forge_ollama_memory` | 10.5 | Ollama context/KV cache management |
| `forge_llamacpp` | 10.6 | llama.cpp local server client |
| `forge_cognitive_router` | 14.7 | Task-type → cascade mapping |
| `forge_ghost_router` | 16.2 | Hot-plug router. 1 exclusive persistent model, lock |
| `forge_hybrid_bridge` | 11.9 | Local+cloud blend |
| `forge_litellm_connector` | 9.0 | LiteLLM connector init |
| `forge_hot_load_manager` | 15.3 | **Ollama keep-alive + cloud quota tracking per provider** |

## RAG & memory (20 modules, ~400 KB)

| Module | Size | Role |
|---|---|---|
| `forge_rag_engine` | 84.2 | **Main RAG engine.** Embedding, indexing, retrieval |
| `forge_rag_truth` | 40.1 | `TruthState` promotion: DRAFT→VERIFIED→GOLD (monotonic, revocation via ring 0/1) |
| `forge_rag_qualify` | 15.0 | RAG chunk qualification |
| `forge_rag_store` | 19.9 | Storage layer for RAG |
| `forge_rag_warmup` | 24.2 | Pre-loads hot chunks at boot |
| `forge_rag_cache` | 15.6 | In-memory cache |
| `forge_rag_index_app` | 11.4 | Application-level indexing |
| `forge_handler_rag` | 23.6 | TUI @rag command handler |
| `forge_graph_rag` | 12.0 | **Graph-RAG layer** — transforms flat vector RAG into navigable knowledge graph |
| `forge_graph_search` | — | Graph search algorithms |
| `forge_mesh_memory` | 13.5 | **Ring 6 nomadic memory.** USB-portable, P2P-syncable, LanceDB-backed |
| `forge_knowledge_harvester` | 15.6 | Web harvest → RAG ingestion |
| `forge_noise_guardian` | 15.7 | **Anonymizes IP/MAC/CVE/paths before cloud.** See SECURITY.md |
| `forge_npu_embedder` | 19.1 | MiniLM-L6-v2 via NPU (VitisAI) |
| `forge_skill_rag_bridge` | 25.0 | **Connects SkillLearner ↔ RAG ↔ @disco** |
| `forge_noise_inject` | 7.4 | Semantic noise injector for cloud-bound snippets |
| `forge_mem_watchdog` | 11.1 | `MemWatchdog` — tracemalloc conditional on RAM threshold |
| `forge_memory` | 13.8 | In-process memory layer |
| `forge_hot_ingest` | 17.1 | **Surveys `data/rag_files/`**, ingests new files with ring=TRUSTED |
| `forge_mmap_context` | 11.1 | Memory-mapped large-context sharing |

## Agents & bridges (15 modules, ~470 KB)

| Module | Size | Role |
|---|---|---|
| `forge_agents` | 127.9 | **Main agent registry.** All 6 agents, roles, capabilities |
| `forge_core_agents` | 68.7 | Core agent abstractions |
| `forge_agent_roles` | 35.9 | Role definitions per agent |
| `forge_handler_agents` | 15.6 | TUI @agents handler |
| `forge_agent_authority` | 13.4 | Governance — who can do what |
| `forge_agentic` | 10.6 | Agentic behavior primitives |
| `forge_agent_hardware` | 7.0 | Per-agent HW allocation |
| `forge_clawhub_bridge` | 28.5 | **ClawHub skill marketplace bridge.** See CLAWHUB.md |
| `forge_clawhub_autoinstall` | 14.9 | Auto-suggests + installs relevant skills for an intention (TF-IDF over 627 catalog) |
| `skilltree.py` | 27.2 | `SkillLearner`, `SkillTree` (Textual Vertical), `SkillNode`, `SkillState` |
| `forge_hub_client` | 6.0 | MCP hub client |
| `forge_hub_handlers` | 36.3 | Hub-level request handlers |
| `forge_hub_worker` | 7.6 | Worker spawned by hub |
| `forge_heartbeat` | 8.8 | Inter-agent heartbeat |
| `forge_idle_watchdog` | 6.3 | Stops NSSM service if idle |

## Handlers (TUI @-commands, 9 dedicated files)

| Module | Size | @-command |
|---|---|---|
| `forge_handlers` | 62.2 | Monolithic dispatcher (legacy) |
| `forge_handler_ci` | 35.0 | @ci — CI/CD loop |
| `forge_handler_rag` | 23.6 | @rag — RAG ops |
| `forge_handler_agents` | 15.6 | @agents |
| `forge_handler_patch` | 15.2 | @patch — AST patches |
| `forge_handler_advanced` | 13.6 | @advanced — power tools |
| `forge_handler_skill` | 11.8 | @skill — ClawHub |
| `forge_handler_build` | 10.1 | @build — OneMCP workflow |
| `forge_handler_evolve` | 8.2 | @evolve — mutation |
| `forge_handler_fragment` | 6.8 | @fragment — RAG chunks |
| `forge_handler_nr` | 6.9 | @nr — natural request |

## Security & integrity (6 modules, ~165 KB)

See SECURITY.md for full detail.

| Module | Size | Role |
|---|---|---|
| `forge_integrity` | 33.0 | **Ring system** (MASTER/SYSTEM/DEV/TRUSTED/COLLAB/UNTRUSTED). `capability_required`, `is_at_least`, HMAC-SHA256 tokens |
| `forge_sentinel` | — | Pattern detection for dangerous outputs |
| `forge_mcp_security` | 11.7 | MCP-level path sandbox + audit |
| `forge_conv_sanitizer` | 22.7 | Conversation sanitization |
| `forge_prompt_guard` | 19.1 | `InjectionResult`, `ConflictReport` — prompt injection defense |
| `forge_env_crypt` | 20.1 | Encrypted secrets handling |
| `forge_sanitizer_analyst` | — | Sanitizer-Driven Exploit Engine — Blue Water style ASAN/MSAN/UBSAN analyzer |
| `forge_trauma_vault` | — | **Memory of failures** with STDP plasticity + topological protection |
| `forge_semantic_firewall` | — | 4-layer semantic firewall |
| `tools/forge_trust_broker.py` | 13.6 | `SecretAnonymizer` + `OrchestratorTrustBroker` — PI protection before cloud |

## CTF & pentest (in `app/`, 8 modules + `tools/ctf/`, 10 modules)

See CTF.md for the full pipeline.

**In `app/`:**

| Module | Size | Role |
|---|---|---|
| `forge_ctf_agent` | 24.4 | **Main CTF solver** — Exegol Docker (175 tools) pipeline CLASSIFY→PLAN→EXECUTE→EXTRACT→REFLECT→RETRY |
| `forge_ctf_brain` | 13.0 | LLM-in-the-loop reasoning cortex |
| `forge_ctf_adaptive` | 7.6 | Adaptive solve loop via Ollama |
| `forge_ctf_benchmark` | 11.1 | Local CTF score benchmark |
| `forge_adaptive_pwn` | 12.9 | Adaptive ret2libc / format string with LibcResolver |
| `forge_libc_resolver` | 13.5 | Libc fingerprinting via libc-database |
| `ctf_planner` | 7.7 | 4-level complexity classifier + strategy router |
| `ctf_ghidra` | 8.0 | Ghidra headless static analysis |
| `ctf_validator` | 5.2 | CTF flag address validator |
| `forge_cyber_pivot` | 7.1 | Cyber-pivoting agentic module |
| `forge_cyber_pivot_engine` | 12.2 | Scanner + Agent + Honeynets + Benchmark |

**In `tools/ctf/`:**

| Module | Size | Role |
|---|---|---|
| `forge_ctf_runner` | 31.5 | Autonomous CTF runner v2 high-performance |
| `forge_payload_forge` | 18.8 | **Nokido Payload Forge (LPF)** — payload generator |
| `forge_ctf_autonomy` | 15.2 | CTF autonomy module |
| `forge_ctf_exploit_writer` | 14.5 | Auto-writes exploits |
| `forge_gdb_live` | 10.8 | GDB Hot-Reload via Machine Interface |
| `forge_docker_orchestrator` | 7.8 | Local Docker orchestrator for CTF |
| `forge_batch_resolver` | 6.9 | Batch CTF challenge resolution |
| `forge_handler_exegol` | 6.2 | @exegol TUI handler |
| `forge_exec` | 4.5 | Docker execution without freeze |
| `forge_pwn_leak_parser` | 3.9 | Memory leak extraction |

## Graph stack (5 modules + `tools/research/`)

| Module | Size | Role |
|---|---|---|
| `forge_graph_explorer` | 61.4 | GUI graph explorer (Cytoscape) |
| `forge_graph_studio` | 36.6 | **Universal Graph Studio v1** — domain-independent graph analysis |
| `forge_graph_universal` | 16.2 | **Universal Graph Engine v2** — cyber, docs, science, finance, medical |
| `forge_graph_rag` | 12.0 | Graph-RAG layer |
| `forge_nlgraph_runner` | 7.6 | NLGraph Benchmark Runner |
| `forge_nlgraph_scorer` | 8.7 | LLM Scorer + Benchmark |
| `tools/research/forge_graph_engine` | 12.8 | Graph Engine v1 |
| `tools/research/forge_gnn` | 16.3 | GNN v3 — Bistable / Neuro-Spin architecture |

## Engrid v3 orchestration layers (5 modules + research)

See ARCHITECTURE.md.

| Module | Size | Layer |
|---|---|---|
| `forge_metacognition_gate` | 25.2 | **Layer 1** — filter between incoming prompt and LLM backend |
| `forge_orchestrator` | 27.7 | **Layer 2** — multi-silo chain |
| `forge_engrid_engine` | 32.2 | **Facade principale** — Engrid v3 |
| `forge_engrid_bridge` | 13.5 | Bridge between autonomous cycle and Engrid |
| `forge_sovereign_membrane` | — | **Bidirectional membrane** between internal world (Ryzen real data) and external (LLM/cloud) |
| `forge_sovereign_mapper` | — | Symmetric sovereignty mapping |
| `tools/research/forge_inhibition_bus` | 12.6 | **Engrid v3 Sprint 2** — inhibition bus |
| `forge_arbitrator` | 19.0 | `ConfidenceReport`, `DispatchResult` |
| `forge_cascade_oracle` | 11.3 | Oracle CE for S1/S2 decision |

## NPU / hardware (5 modules)

| Module | Size | Role |
|---|---|---|
| `forge_npu` | 27.3 | NPU abstraction |
| `forge_npu_embedder` | 19.1 | MiniLM via NPU |
| `forge_npu_env` | 5.2 | NPU environment setup |
| `forge_phi3_npu` | 6.3 | Phi-3 on NPU |
| `hardware_monitor` | 5.8 | HW monitoring |
| `forge_hw_allocator` | 12.4 | Allocates LLM to best HW |
| `forge_agent_hardware` | 7.0 | Per-agent HW mapping |

## Evolution & mutation (many modules)

| Module | Size | Role |
|---|---|---|
| `tools/evolutionary_engine` | **102.1** | **Moteur Évolutif Nokido + Cerberus.** Generations N+1, checkpoints, crossover, population fork, ASTSurgeon, CerberusGuard (AST + pytest + ruff), adaptive temperature |
| `forge_mutation_classifier` | 13.7 | ML classifier for mutation success |
| `forge_mutation_predictor` | 10.7 | ML mutation predictor |
| `forge_recursive_debugger` | 16.2 | `AUTONOMOUS_DEBUG_LOOP_V1` — Write→Test→Analyze→Refactor |
| `forge_self_correction` | — | Auto-correction code |
| `forge_auto_pilot` | 17.1 | Autonomous task pilot |
| `shadow_mutation/vault/` | — | 61 modules, 202 versioned snapshots with genetic tagging (astpatcher/cerberusok/astdoc/ollamaqwen etc.) |
| `forge_distiller` | 12.2 | Knowledge distillation |
| `forge_knowledge_harvester` | 15.6 | Web harvest to RAG |
| `tools/forge_semantic_fuzzer` | 36.1 | Semantic fuzzer for code mutations |
| `tools/forge_surgical_patcher` | 14.6 | AST surgical patch (Pass@1) |
| `tools/forge_library_shifter` | 10.6 | Library permutation via AST |
| `tools/forge_evolutionary_stack` | 14.2 | Stacking évolutif |
| `tools/forge_stream_mutation` | 7.7 | Streaming mutation |

## Swarm & collab (multi-agent)

| Module | Size | Role |
|---|---|---|
| `forge_swarm` | — | State machine: IDLE → THINKING(agent) → STREAMING(agent) → SYNCING_RAG → IDLE |
| `forge_swarm_team` | — | `Team` — serializable participants list for swarm session |
| `forge_triad_authority` | — | 3-way authority decision (represents step with agent, outcome, timing) |
| `forge_collab_modes` | 69.6 | `CollabSession` — orchestrated collaboration sessions |

## Bridges (external systems, 8+ modules)

| Module | Size | Bridges to |
|---|---|---|
| `forge_exegol_bridge` | 25.2 | Exegol Docker container (MSF RPC) |
| `forge_kaggle_bridge` | 11.6 | Kaggle API (REST direct, SDK fallback) |
| `forge_codeberg_sync` | 6.4 | Codeberg Git sync |
| `forge_cai_bridge` | 8.2 | CAI (CyberAI Tactical Engine) |
| `forge_gemini_bridge` | 15.9 | Gemini API |
| `tools/forge_gemini_mcp_connector` | 20.6 | Gemini ↔ MCP Nokido dynamic connector |
| `tools/forge_gemini_mcp_proxy` | 13.5 | Gemini ↔ MCP proxy |
| `forge_github_mcp_connector` | 15.0 | GitHub MCP integration |
| `forge_docker_bridge` | 6.6 | Native Docker bridge |
| `netcfg_silo_bridge.py` | 14.6 | netcfg-agent ↔ Nokido silos |

## Web UI & dashboard

| Module | Size | Role |
|---|---|---|
| `Nokido.py` | 194.5 | Main TUI `_silent` classes + bootstrap |
| `forge_web_service` | 47.5 | Streamlit web façade — security-by-design (creds boot-once, no sensitive path leak) |
| `forge_dashboard` (tools/) | 18.0 | Dashboard v17 |
| `forge_graph_explorer` | 61.4 | GUI Cytoscape |
| `forge_gui_debug` | 11.2 | GUI debug tools |
| `forge_mixin_ui` | 34.0 | UI mixin |

## Specialist modules (notable)

| Module | Size | Role |
|---|---|---|
| `forge_code` | 97.7 | Code manipulation core |
| `forge_mixin_patch` | 59.3 | Patch mixin |
| `brain_worker` | 56.2 | **ZMQ sidecar** on :5557, ONNX cascade NPU→DML→CPU, PriorityQueue(0=user, 5=warmup, 10=bg) |
| `forge_rag_truth` | 40.1 | TruthState promotion engine |
| `forge_integrity` | 33.0 | Ring integrity |
| `forge_health` | 35.1 | Health checks |
| `forge_ingest_self` | 21.4 | Self-ingestion (Nokido indexes itself) |
| `forge_prefect` | 17.8 | Prefect workflow orchestration |
| `forge_promotion_queue` | 22.4 | `PromotionOrchestrator` — adaptive DRAFT→VERIFIED/GOLD queue |
| `forge_pipeline_node` | 13.0 | `Ring2ADRValidator` — ADR conformance check |
| `tools/forge_source_discovery` | 37.4 | Enrichissement RAG by targeted web discovery |
| `tools/forge_lora_trainer` | 16.8 | LoRA fine-tuning of qwen2.5-coder:7b on Nokido corpus |
| `tools/forge_thought_interceptor` | 13.4 | CoT interceptor with GPU Lock + cognitive density |
| `tools/forge_token_optimizer` | 7.4 | Prompt compression |
| `tools/forge_turbo_runner` | 7.6 | Parallelized test runner for Ryzen 8700G |
| `tools/nokido_pipeline` | 22.5 | **Pentest Pipeline — central orchestrator** |
| `tools/nokido_netmap` | 11.3 | Network map terminal interactive |
| `tools/nr_reporter` | 16.3 | NR reports + RAG ingestion |
| `tools/mcp_nr` | 24.1 | NR automation from Claude via MCP sandbox |

## Top-level entry scripts

| File | Purpose |
|---|---|
| `laforge-start.cmd` | Start hub + services |
| `laforge-stop.cmd` | Stop everything |
| `laforge-status.cmd` | Show runtime status |
| `laforge-open.cmd` | Open TUI |
| `La Forge.lnk` | Windows shortcut |
| `Nokido.env` | Secrets + config (13.5 KB, gitignored) |
| `Nokido.env.example` | Template |
| `pyproject.toml` | Python project config |

## Where to look first (cheat sheet)

| You want to... | Start here |
|---|---|
| Know what a TUI @-command does | `forge_handler_<name>.py` |
| Route an LLM call | `forge_llm_router.py` |
| Query RAG | `forge_rag_engine.py` + SQL on `embeddings.db` |
| Install a skill | `forge_clawhub_bridge.py` + CLAWHUB.md |
| Run a CTF | `forge_ctf_agent.py` + CTF.md |
| Scan a network | `recon_silo/recon_master.py` + RECON.md |
| Understand rings | `forge_integrity.py` + ARCHITECTURE.md |
| Anonymize before cloud | `forge_noise_guardian.py` + SECURITY.md |
| Diagnose runtime | `run(action="hub_status")` then `run(action="audit_log")` |
