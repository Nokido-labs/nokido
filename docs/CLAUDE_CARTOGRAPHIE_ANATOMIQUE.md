<!-- DEPORTE depuis CLAUDE.md le 2026-09-19 pour tenir le budget du noyau resident.
     Le contenu n'a pas ete modifie : seul son LIEU a change.
     Mesure : cette section pesait 52% de CLAUDE.md, re-facture a chaque tour. -->

# 10. Cartographie anatomique (biomimetisme structurel)

> Section de regles **deportee** hors du noyau resident. Elle n'est plus
> chargee a chaque tour ; elle se consulte a la demande (`rag`, `introspect`,
> ou lecture directe). Les pieges qu'elle decrit restent **EXECUTES** par
> `tools/hook_capability_gate.py`, dont les regles vivent dans SON code :
> deporter la prose ne desarme rien.

## 10. Cartographie anatomique (biomimetisme structurel)

Nokido est concu comme un organisme. Cette grille existe deja
partiellement en commentaire dans `tools/nokido_hub.py` (lignes
1070-1077 : Cortex Prefrontal, Cervelet, Moelle Epiniere). On la
generalise ici comme grille de lecture systematique pour conception
ET diagnostic.

### Census automatique — 2026-06-05 (985 modules / 292k LOC, override `organ_map_full.json` — 0 forge_* non classé)

Généré par `tools/forge_module_census.py` (scan app/ + tools/, override carte complète
`sandbox/workspace/organ_map_full.json` puis fallback keyword). La grille manuelle
documentait ~50 modules = **5% du réel**. Carte VRAIE par organe (985 mods, 15 organes,
714 forge TOUS classés) :

| Organe | Mods | LOC | Modules représentatifs (top LOC) |
|---|---|---|---|
| Infra/Bootstrap/Config | 98 | 22k | `forge_mixin_patch.py` · `forge_services_launcher.py` · `forge_mixin_ui.py` · `forge_startup.py` · `forge_health_diagnostic.py` · `forge_settings.py` · `forge_env_crypt.py` |
| Memoire (hippocampe/RAG) | 97 | 24k | `forge_rag_engine.py` · `forge_rag_truth.py` · `forge_world_model.py` · `forge_self_correction.py` · `forge_skill_rag_bridge.py` · `forge_embed_router.py` · `forge_rag_warmup.py` |
| SNC (cerveau/moelle/SNP) | 89 | 43k | `forge_mcp_registry.py` · `nokido_hub.py` · `forge_code.py` · `forge_core_models.py` · `mcp_server_tools.py` · `forge_handlers.py` · `forge_hub_handlers.py` |
| Locomoteur/Orchestration | 81 | 34k | `forge_swebench_runner.py` · `forge_handoff.py` · `forge_at_dispatch.py` · `forge_swebench_lats_runner.py` · `forge_runtime.py` · `forge_swarm_team.py` · `forge_silo_engine.py` |
| SN vegetatif (autonome) | 75 | 25k | `evolutionary_engine.py` · `forge_resource_manager.py` · `forge_autonomous_loops.py` · `forge_rescue.py` · `forge_health.py` · `forge_snapshot.py` |
| Cognition/Agentique/Raisonnement | 72 | 24k | `forge_agents.py` · `forge_roles_legacy.py` · `forge_agent_roles.py` · `skilltree.py` · `forge_watch_agent.py` · `forge_metacognition_gate.py` · `forge_ps_agent.py` |
| Metabolisme LLM (routage/backends) | 67 | 22k | `forge_agent_proxy.py` · `forge_llm_router.py` · `forge_ollama_bridge.py` · `forge_npu.py` · `forge_openrouter.py` · `forge_llm_router_dt.py` · `llama_cli.py` |
| Immunitaire (firewall/garde) | 49 | 14k | `forge_integrity.py` · `forge_sandbox_exec.py` · `forge_semantic_firewall.py` · `forge_opsec.py` · `forge_silo_fragmenter.py` · `forge_sovereign_membrane.py` · `forge_conv_sanitizer.py` |
| Digestif/Sens (ingestion/web) | 48 | 11k | `forge_web_service.py` · `forge_source_discovery.py` · `forge_web.py` · `forge_ui_widgets.py` · `forge_pty.py` · `forge_dashboard.py` · `forge_pty_widget.py` |
| Qualite/Build/Spec | 44 | 9k | `forge_versioning.py` · `forge_commit_intel.py` · `forge_meta_tools.py` · `forge_interaction_test.py` · `forge_mutation_classifier.py` · `forge_post_commit.py` · `forge_demo_record_all.py` |
| Graph/Connaissances | 43 | 11k | `forge_graph_explorer.py` · `forge_graph_studio.py` · `forge_git_historian.py` · `forge_graph_universal.py` · `forge_resonance_filter.py` · `forge_graph_linker.py` · `forge_knowledge_harvester.py` |
| Observabilite/Trace | 36 | 7k | `forge_timecode.py` · `forge_events.py` · `generate_body_anatomy.py` · `forge_anatomy_state.py` · `forge_trace_viz.py` · `forge_metrics.py` · `forge_trace_sidecar.py` |
| Reseau/Distribue/Sync | 21 | 6k | `forge_ssh.py` · `gemini_poll_daemon.py` · `forge_network.py` · `forge_dataset_sync.py` · `forge_network_logger.py` · `forge_pipeline_node.py` · `forge_network_dispatch.py` |
| (recherche sécurité) | — | — | *déporté hors du cœur (dépôt privé)* |
| SWE-bench | 5 | 0k | `forge_swe_ast_whole_func.py` · `forge_swe_multifile.py` · `forge_pydantic_tools.py` · `forge_swe_smoke_launch.py` · `forge_swe_smoke_restart.py` |
| Core/legacy + longue traîne (non-forge) | 149 | 29k | `Nokido.py` · `brain_worker.py` · `nokido_core.py` · `nokido_tui.py` · `patch.py` · `autotools.py` · `multi_llm_daemon.py` · `_batch*_send.py` · `_chain_execute*.py` |

> Index COMPLET (module→organe) : `sandbox/workspace/organ_map_full.json` (714 forge, **0 non classé**)
> + `module_inventory.md` (path｜LOC｜purpose). Régén : `LAFORGE_PYTHON tools/forge_module_census.py`
> (override = la carte json ; fallback keyword pour le non-forge). **Consulter AVANT d'affirmer
> qu'un module n'existe pas / d'en recréer un** (anti-dup, cf §3). Labels « représentatifs » =
> heuristique + LLM groq (approx, ex. `forge_proprioception` mal rangé CTF) — vérifier le module
> réel avant affirmation forte. Vectorisation RAG : forge_*.py **~100%** (712/713 ; seul
> `forge_tui.py` = 0 octet). L'ancien « 11% / 241 manquants » était un FAUX négatif de requête (suffixe `#chunk`).

### Quel organe ? (taxonomie)

| Systeme | Organe | Modules Nokido reels |
|---|---|---|
| **SNC** | Cerveau (hub) | `tools/nokido_hub.py` :8766 |
| | Cortex prefrontal | `app/forge_cognitive_router.py` |
| | Cervelet Python (SNN) | `app/forge_spike_router.py` (PyTorch, 38 challenges, 14 strategies) |
| | Cervelet Deno (intent) | `proxy_deno/core/brain.ts` processLLMIntent — route intentions LLM cote Deno |
| | Bus neural Deno | `proxy_deno/core/nervous_system.ts` SystemBus/BloodCell — event bus inter-organes |
| | Thalamus (NLU tri) | `app/forge_nlu.py` FastClassifier (chat/action/rag) + `app/forge_intent_parser.py` |
| | Moelle epiniere | `app/forge_byte_router.py` ByteDataRouter 13 sentinels |
| | SN peripherique | `app/forge_mcp_registry.py` |
| | Metabolisme energetique | `app/forge_llm_router.py` |
| **Memoire** | Hippocampe (consolidation) | `app/forge_self_correction.py` |
| | Cortex sensoriel (long terme) | `RAG/embeddings.db` + `forge_rag_engine.py` |
| | Synapses vectorielles | `brain_worker` :5557 ZMQ BGE-M3 NPU — ⚠ DISABLED 2026-06-03, l'embedder vivant est :8099 |
| | Synapses (indexation continue) | `forge_rag_warmup.py`, `forge_post_commit.py`, `forge_conv_indexer.py` |
| **Immunitaire** | Barriere hemato-encephalique | `forge_semantic_firewall.py` |
| | Anticorps specifiques | `forge_prompt_guard.py` |
| | Membrane cellulaire | `forge_sovereign_membrane.py` |
| | Macrophages | `SkillGuardian` dans `forge_clawhub_bridge.py` |
| | Systeme HLA / RBAC | `forge_integrity.py::IntegrityRing` |
| | Detection corps etrangers | `forge_silo_fragmenter.py::NoiseGuardian` |
| **SN Vegetatif** | Bulbe rachidien (autonome) | `forge_inspector.py` |
| | Sympathique (alerte) | `forge_idle_watchdog.py`, `forge_ping_monitor.py` |
| | Parasympathique (boot) | `forge_provider_watcher.py` |
| **Digestif** | Bouche / oesophage | `/ingest/url`, `/ingest/bulk` |
| | Estomac (broyage) | `forge_ingest_self.py`, MarkdownChunker |
| | Intestin grele (absorption) | `forge_rag_qualify.py` (trust_weight) |
| | Foie (detox) | `forge_secret_guard.py` (DLP) |
| **Locomoteur** | Muscles stries | 6 SiloDomain (`forge_silo_engine.py`) |
| | Squelette | `forge_runtime.py`, `forge_runner.py` |
| | Articulations | `forge_message_frame.py`, `forge_broker_base.py` |
| **Sens** | Vision | `forge_browser_tool.py`, `forge_crawl_tool.py` |
| | Ouie (clients MCP) | bridge stdio + Claude Desktop, Cline |
| | Toucher (effecteur direct) | netcfg-agent PTY SSH, forge-android |

### Pathologies-types (signatures + remedes)

| Pathologie | Signal code | Module a auditer | Remede |
|---|---|---|---|
| Auto-immunite | Bouclier rejette du legitime | SkillGuardian, SemanticFirewall | Affiner tolerance interne (whitelist trust>0.8) |
| Crise epilepsie | Cascade re-tentatives infinie | forge_llm_router circuit breaker | Periode refractaire, max_retries |
| Sclerose en plaques | Bridge stdio lent / deadlock | mcp_stdio_bridge, broker_base | uvloop, vidage buffers, timeouts (cf. commit 0e038b5) |
| Hemorragie | Fuite memoire async | forge_runner mmap, brokers | Inspector watch + heartbeat |
| Septicemie | Composant compromis exfiltre | semantic_firewall.post_flight (SSRF beacon) | Membrane wrap + canary leak detection |
| Coma | Hub UP mais ne repond plus | forge_inspector triple-confirm | Restart auto (cf. commit 228073f) |

### Regle du nouveau module

Avant de creer/patcher un `forge_*.py`, reponds aux 3 questions :

1. **Quel organe ?** (cortex / hippocampe / immunitaire / vegetatif /
   digestif / locomoteur / sens)
2. **Quelle vascularisation ?** Data flow entrant/sortant, modules
   dependants, ring de securite requis.
3. **Scenario d hemorragie ?** Si ce module fuit, crash, ou est
   compromis : qu est-ce qui meurt dans le systeme ?

Si tu ne sais pas repondre : invoque le skill `forge-anatomy` (grille
de lecture detaillee + diagnostic differentiel par symptome) avant
de coder.

---

