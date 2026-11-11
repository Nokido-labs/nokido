# Sondes HTTP hors `forge_endpoint_commun`

Appels HTTP **directs** (invocation : `urllib.request.urlopen`, `requests.get|post`, `httpx.get|post`)
visant un fournisseur LLM cloud **ou** un endpoint de modele local
(ollama `:11434`, lmstudio `:1234`, llama-server `:8091`, embed-sidecar `:8099`, litellm `:4000`).

Exclus : hub `:8766`, supervisor `:8765`, netcfg `:8767`, SearXNG, GitHub, arXiv/OpenAlex, RSS, MCP.
`dyn:` = URL construite dynamiquement (constante/liste module) ; cibles listees au niveau fichier.

**Total : 232 sites** dans **125 fichiers**.

| Fichier:ligne | Fonction | Cible | Transport | Socle commun |
|---|---|---|---|---|
| `app/forge_actor.py:155` | `_ollama` | dyn: ollama:11434 | urllib | non |
| `app/forge_agent_proxy.py:1879` | `is_available` | ollama:11434 | urllib | non |
| `app/forge_agent_proxy.py:2202` | `ask` | dyn: api.cerebras.ai,api.deepseek.com,api.groq.com,api.mistral.ai,api.perplexity.ai,api.sambanova.ai,api.together.xyz,api.x.ai,api.z.ai,integrate.api.nvidia.com,openrouter.ai,router.huggingface.co + litellm:4000,lmstudio:1234,ollama:11434 | urllib | non |
| `app/forge_autonomous_loops.py:261` | `_llama_vivant` | dyn: litellm:4000,llama-server:8091,ollama:11434 | urllib | non |
| `app/forge_autonomous_loops.py:286` | `_llamacpp_chat` | dyn: litellm:4000,llama-server:8091,ollama:11434 | urllib | non |
| `app/forge_autonomous_loops.py:317` | `_ollama_call` | dyn: litellm:4000,llama-server:8091,ollama:11434 | urllib | non |
| `app/forge_autonomous_orchestrator.py:363` | `_detect_agents` | ollama:11434 | urllib | non |
| `app/forge_baml_adapter.py:69` | `_llm_json_call` | dyn: api.cerebras.ai,api.groq.com | urllib | non |
| `app/forge_biblio_core.py:146` | `extract_from_text` | dyn: api.mistral.ai | urllib | non |
| `app/forge_biblio_worker.py:199` | `_extract_topics` | dyn: ollama:11434 | urllib | non |
| `app/forge_clawhub_bridge.py:106` | `_get` | dyn: ollama:11434 | urllib | non |
| `app/forge_clawhub_bridge.py:338` | `_llm_review` | dyn: ollama:11434 | urllib | non |
| `app/forge_clawhub_bridge.py:442` | `_ingest_sast_findings` | dyn: ollama:11434 | urllib | non |
| `app/forge_cowork.py:183` | `_draft_local` | dyn: litellm:4000,ollama:11434 | urllib | non |
| `app/forge_curiosity_driver.py:365` | `_cerebras_call` | dyn: api.cerebras.ai | urllib | non |
| `app/forge_dsl.py:242` | `_h_ingest` | dyn: litellm:4000 | urllib | non |
| `app/forge_dsl.py:362` | `_h_chat` | dyn: litellm:4000 | urllib | non |
| `app/forge_dt_router.py:24` | `_ollama_fallback` | ollama:11434 | requests | non |
| `app/forge_edge_fleet.py:248` | `sonder_noeuds_http` | dyn: ollama:11434 | urllib | non |
| `app/forge_edge_fleet.py:338` | `heartbeat_self` | dyn: ollama:11434 | urllib | non |
| `app/forge_edge_fleet.py:692` | `dispatch_request` | dyn: ollama:11434 | urllib | non |
| `app/forge_edge_fleet.py:744` | `broadcast_world_vector` | dyn: ollama:11434 | urllib | non |
| `app/forge_embed_router.py:125` | `_embed_hf` | dyn: api.jina.ai,api.voyageai.com,hf-inference,openrouter.ai,router.huggingface.co + embed-sidecar:8099 | urllib | non |
| `app/forge_embed_router.py:181` | `_jina_call` | dyn: api.jina.ai,api.voyageai.com,hf-inference,openrouter.ai,router.huggingface.co + embed-sidecar:8099 | urllib | non |
| `app/forge_embed_router.py:242` | `_voyage_call` | dyn: api.jina.ai,api.voyageai.com,hf-inference,openrouter.ai,router.huggingface.co + embed-sidecar:8099 | urllib | non |
| `app/forge_embed_router.py:307` | `_modal_call` | dyn: api.jina.ai,api.voyageai.com,hf-inference,openrouter.ai,router.huggingface.co + embed-sidecar:8099 | urllib | non |
| `app/forge_embed_router.py:616` | `_appel_8099` | dyn: api.jina.ai,api.voyageai.com,hf-inference,openrouter.ai,router.huggingface.co + embed-sidecar:8099 | urllib | non |
| `app/forge_embed_router.py:933` | `_openrouter_call` | dyn: api.jina.ai,api.voyageai.com,hf-inference,openrouter.ai,router.huggingface.co + embed-sidecar:8099 | urllib | non |
| `app/forge_frugal_cascade.py:135` | `_echec` | dyn: api.cerebras.ai,api.groq.com,api.mistral.ai | urllib | non |
| `app/forge_handoff.py:253` | `_call_ollama_chat` | dyn: llama-server:8091,ollama:11434 | urllib | non |
| `app/forge_handoff.py:792` | `_probe_one` | dyn: llama-server:8091,ollama:11434 | urllib | non |
| `app/forge_handoff.py:1014` | `_call_endpoint_chat` | dyn: llama-server:8091,ollama:11434 | urllib | non |
| `app/forge_handoff_compress.py:91` | `_llm_call` | dyn: api.cerebras.ai,api.groq.com | urllib | non |
| `app/forge_health_diagnostic.py:782` | `_sonder` | dyn: embed-sidecar:8099,llama-server:8091,ollama:11434 | urllib | non |
| `app/forge_hybrid_bridge.py:74` | `_post_json` | dyn: api.deepseek.com,api.groq.com,generativelanguage.googleapis.com,openrouter.ai + ollama:11434 | urllib | non |
| `app/forge_hybrid_bridge.py:96` | `_call_ollama` | dyn: api.deepseek.com,api.groq.com,generativelanguage.googleapis.com,openrouter.ai + ollama:11434 | urllib | non |
| `app/forge_key_validator.py:104` | `check_live` | dyn: api.deepseek.com,api.groq.com,api.x.ai,generativelanguage.googleapis.com,openrouter.ai | urllib | non |
| `app/forge_llamacpp.py:117` | `_server_available` | dyn: llama-server:8091 | urllib | non |
| `app/forge_llamacpp.py:166` | `_server_call` | dyn: llama-server:8091 | urllib | non |
| `app/forge_llm_router.py:117` | `_post` | dyn: api.sambanova.ai,api.x.ai,integrate.api.nvidia.com,openrouter.ai,router.huggingface.co + embed-sidecar:8099,llama-server:8091,lmstudio:1234,ollama:11434 | urllib | non |
| `app/forge_llm_transport.py:123` | `call_mistral` | dyn: api.groq.com,api.mistral.ai,generativelanguage.googleapis.com + ollama:11434 | urllib | non |
| `app/forge_llm_transport.py:157` | `call_gemini` | dyn: api.groq.com,api.mistral.ai,generativelanguage.googleapis.com + ollama:11434 | urllib | non |
| `app/forge_llm_transport.py:186` | `call_ollama` | dyn: api.groq.com,api.mistral.ai,generativelanguage.googleapis.com + ollama:11434 | urllib | non |
| `app/forge_llm_transport.py:207` | `call_llamacpp` | dyn: api.groq.com,api.mistral.ai,generativelanguage.googleapis.com + ollama:11434 | urllib | non |
| `app/forge_llm_transport.py:234` | `call_groq` | dyn: api.groq.com,api.mistral.ai,generativelanguage.googleapis.com + ollama:11434 | urllib | non |
| `app/forge_local_inference_pool.py:78` | `_call` | dyn: openrouter.ai + ollama:11434 | urllib | non |
| `app/forge_local_inference_pool.py:125` | `_call` | dyn: openrouter.ai + ollama:11434 | urllib | non |
| `app/forge_local_inference_pool.py:166` | `_call` | dyn: openrouter.ai + ollama:11434 | urllib | non |
| `app/forge_mcp_registry.py:2904` | `_appel_synchrone` | dyn: embed-sidecar:8099,litellm:4000,llama-server:8091,ollama:11434 | urllib | non |
| `app/forge_nlgraph_scorer.py:55` | `_call` | dyn: ollama:11434 | urllib | non |
| `app/forge_ollama_bridge.py:821` | `get_available_models` | dyn: ollama:11434 | urllib | non |
| `app/forge_ollama_bridge.py:860` | `is_inference_alive` | dyn: ollama:11434 | urllib | non |
| `app/forge_openrouter.py:355` | `_fallback_to_local` | dyn: api.anthropic.com,api.deepseek.com,api.groq.com,api.mistral.ai,generativelanguage.googleapis.com,openrouter.ai + litellm:4000,ollama:11434 | urllib | non |
| `app/forge_openrouter.py:715` | `check_key_limits` | dyn: api.anthropic.com,api.deepseek.com,api.groq.com,api.mistral.ai,generativelanguage.googleapis.com,openrouter.ai + litellm:4000,ollama:11434 | urllib | non |
| `app/forge_openrouter.py:767` | `_zero` | dyn: api.anthropic.com,api.deepseek.com,api.groq.com,api.mistral.ai,generativelanguage.googleapis.com,openrouter.ai + litellm:4000,ollama:11434 | urllib | non |
| `app/forge_organ_afferent.py:178` | `_interroger` | dyn: ollama:11434 | urllib | non |
| `app/forge_perception_vlm.py:53` | `_detect_vlm_model` | ollama:11434 | urllib | non |
| `app/forge_perception_vlm.py:187` | `analyze_image` | dyn: ollama:11434 | urllib | non |
| `app/forge_quota_tracker.py:141` | `_fetch_openrouter` | dyn: openrouter.ai | urllib | non |
| `app/forge_research_agent.py:42` | `_ollama` | dyn: api.groq.com + litellm:4000,ollama:11434 | urllib | non |
| `app/forge_research_agent.py:88` | `_groq` | dyn: api.groq.com + litellm:4000,ollama:11434 | urllib | non |
| `app/forge_research_agent.py:178` | `_search` | dyn: api.groq.com + litellm:4000,ollama:11434 | urllib | non |
| `app/forge_research_agent.py:231` | `_fetch_brut` | dyn: api.groq.com + litellm:4000,ollama:11434 | urllib | non |
| `app/forge_resource_manager.py:3087` | `_sonde_http_coder` | dyn: api.groq.com + embed-sidecar:8099,llama-server:8091,lmstudio:1234,ollama:11434 | urllib | non |
| `app/forge_roles.py:318` | `call_role` | dyn: litellm:4000,ollama:11434 | urllib | non |
| `app/forge_scorecard.py:671` | `create_refine_task` | dyn: ollama:11434 | urllib | non |
| `app/forge_self_awareness.py:53` | `self_snapshot` | dyn: integrate.api.nvidia.com | urllib | non |
| `app/forge_silo_engine.py:474` | `_run` | dyn: ollama:11434 | urllib | non |
| `app/forge_silo_engine.py:484` | `_run` | dyn: ollama:11434 | urllib | non |
| `app/forge_silo_fragmenter.py:456` | `_run` | dyn: ollama:11434 | urllib | non |
| `app/forge_state_encoder.py:159` | `get_current_state_text` | dyn: embed-sidecar:8099,ollama:11434 | urllib | non |
| `app/forge_state_encoder.py:239` | `_encode_384` | dyn: embed-sidecar:8099,ollama:11434 | urllib | non |
| `app/forge_swarm_team.py:859` | `_ollama_remote_call` | dyn: api.deepseek.com,api.groq.com,api.mistral.ai,api.x.ai + ollama:11434 | urllib | non |
| `app/forge_symbiosis_bridge.py:40` | `local_preflight` | dyn: ollama:11434 | requests | non |
| `app/forge_symbiotic_bridge.py:40` | `_ollama_call_sync` | dyn: ollama:11434 | requests | non |
| `app/forge_task_router.py:186` | `_ping` | dyn: ollama:11434 | urllib | non |
| `app/forge_veille_digest.py:422` | `_get` | dyn: ollama:11434 | urllib | non |
| `app/forge_veille_digest.py:691` | `_llm_json` | dyn: ollama:11434 | urllib | non |
| `app/forge_watch_agent.py:325` | `_llm_call_openai_compat` | dyn: api.cerebras.ai,api.groq.com,api.mistral.ai + embed-sidecar:8099,litellm:4000,ollama:11434 | urllib | non |
| `app/forge_watch_agent.py:388` | `_llm_local` | dyn: api.cerebras.ai,api.groq.com,api.mistral.ai + embed-sidecar:8099,litellm:4000,ollama:11434 | urllib | non |
| `app/forge_watch_agent.py:758` | `_up` | dyn: api.cerebras.ai,api.groq.com,api.mistral.ai + embed-sidecar:8099,litellm:4000,ollama:11434 | urllib | non |
| `app/forge_web_fetch.py:154` | `fetch_and_ingest` | dyn: litellm:4000 | urllib | non |
| `app/reembed_souverain.py:23` | `get_embedding` | dyn: lmstudio:1234,ollama:11434 | urllib | non |
| `app/reembed_souverain.py:37` | `get_embedding` | dyn: lmstudio:1234,ollama:11434 | urllib | non |
| `app/tui_adapters/commands_adapter.py:191` | `cmd_model` | ollama:11434 | urllib | non |
| `app/tui_adapters/commands_adapter.py:206` | `cmd_ollama` | ollama:11434 | urllib | non |
| `app/tui_adapters/commands_adapter.py:214` | `cmd_ollama` | ollama:11434 | urllib | non |
| `app/tui_adapters/commands_adapter.py:225` | `cmd_ollama` | dyn: ollama:11434 | urllib | non |
| `tools/assign_gemini_tasks.py:43` | `assign` | dyn: ollama:11434 | urllib | non |
| `tools/autotools.py:505` | `run_litellm_status` | dyn: ollama:11434 | urllib | non |
| `tools/bench/forge_longmemeval_bge.py:53` | `embed` | dyn: ollama:11434 | urllib | non |
| `tools/build_bge_m3_embeddings.py:65` | `load_model` | dyn: ollama:11434 | urllib | non |
| `tools/claude_precompact.py:309` | `_call_openai_compat` | dyn: api.groq.com + lmstudio:1234,ollama:11434 | urllib | non |
| `tools/claude_precompact.py:672` | `main` | dyn: api.groq.com + lmstudio:1234,ollama:11434 | urllib | non |
| `tools/evolutionary_engine.py:944` | `_ollama_fallback` | dyn: api.anthropic.com,generativelanguage.googleapis.com + ollama:11434 | urllib | non |
| `tools/forge_backend_power.py:96` | `_ollama_loaded` | dyn: ollama:11434 | urllib | non |
| `tools/forge_backend_power.py:122` | `warm` | dyn: ollama:11434 | urllib | non |
| `tools/forge_backend_power.py:163` | `start` | dyn: ollama:11434 | urllib | non |
| `tools/forge_backend_power.py:238` | `stop` | dyn: ollama:11434 | urllib | non |
| `tools/forge_bench_all.py:58` | `post_json` | dyn: api.groq.com,api.mistral.ai,openrouter.ai + llama-server:8091,ollama:11434 | urllib | non |
| `tools/forge_bench_beir.py:37` | `_server_up` | dyn: embed-sidecar:8099 | urllib | non |
| `tools/forge_bench_beir.py:47` | `_start_server` | dyn: embed-sidecar:8099 | urllib | non |
| `tools/forge_bench_beir.py:96` | `_embed` | dyn: embed-sidecar:8099 | urllib | non |
| `tools/forge_bench_diagnose.py:37` | `_embed` | dyn: embed-sidecar:8099 | urllib | non |
| `tools/forge_bench_diagnose.py:64` | `main` | dyn: embed-sidecar:8099 | urllib | non |
| `tools/forge_bench_questions.py:36` | `_wait_server` | llama-server:8091 | urllib | non |
| `tools/forge_bench_questions.py:56` | `_ask` | dyn: llama-server:8091 | urllib | non |
| `tools/forge_bench_ragtool.py:45` | `_post` | dyn: embed-sidecar:8099 | urllib | non |
| `tools/forge_bench_rerank.py:36` | `_post` | dyn: embed-sidecar:8099 | urllib | non |
| `tools/forge_bench_rerank.py:83` | `_health` | dyn: embed-sidecar:8099 | urllib | non |
| `tools/forge_bfcl_runner.py:63` | `_fetch` | dyn: api.cerebras.ai,api.groq.com,api.mistral.ai,integrate.api.nvidia.com + litellm:4000,ollama:11434 | urllib | non |
| `tools/forge_broker_deepseek.py:56` | `_call_ds` | dyn: api.deepseek.com,openrouter.ai | urllib | non |
| `tools/forge_broker_deepseek.py:84` | `_call_or_deepseek` | dyn: api.deepseek.com,openrouter.ai | urllib | non |
| `tools/forge_broker_fast.py:90` | `_call_endpoint` | dyn: api.groq.com,api.sambanova.ai | urllib | non |
| `tools/forge_broker_gemini.py:74` | `_call_gemini` | dyn: api.groq.com,api.mistral.ai,generativelanguage.googleapis.com,openrouter.ai | urllib | non |
| `tools/forge_broker_gemini.py:111` | `_call_groq` | dyn: api.groq.com,api.mistral.ai,generativelanguage.googleapis.com,openrouter.ai | urllib | non |
| `tools/forge_broker_gemini.py:136` | `_call_mistral` | dyn: api.groq.com,api.mistral.ai,generativelanguage.googleapis.com,openrouter.ai | urllib | non |
| `tools/forge_broker_gemini.py:167` | `_call_or` | dyn: api.groq.com,api.mistral.ai,generativelanguage.googleapis.com,openrouter.ai | urllib | non |
| `tools/forge_broker_gemini.py:239` | `call_llm_stream` | dyn: api.groq.com,api.mistral.ai,generativelanguage.googleapis.com,openrouter.ai | urllib | non |
| `tools/forge_broker_local.py:47` | `_check_backends` | dyn: ollama:11434 | urllib | non |
| `tools/forge_broker_local.py:67` | `_call_ollama` | dyn: ollama:11434 | urllib | non |
| `tools/forge_broker_local.py:90` | `_call_llamacpp` | dyn: ollama:11434 | urllib | non |
| `tools/forge_broker_mistral.py:56` | `_call` | dyn: api.mistral.ai | urllib | non |
| `tools/forge_card_summarize.py:151` | `main` | ollama:11434 | urllib | non |
| `tools/forge_cognition_retrain_1024.py:37` | `_enc_nomic384` | ollama:11434 | urllib | non |
| `tools/forge_cognition_retrain_1024.py:47` | `_enc_bge1024` | ollama:11434 | urllib | non |
| `tools/forge_collab_broker.py:246` | `_call_gemini_api` | dyn: api.groq.com,api.mistral.ai,api.x.ai,generativelanguage.googleapis.com,openrouter.ai + litellm:4000 | urllib | non |
| `tools/forge_collab_broker.py:283` | `_call_groq` | dyn: api.groq.com,api.mistral.ai,api.x.ai,generativelanguage.googleapis.com,openrouter.ai + litellm:4000 | urllib | non |
| `tools/forge_collab_broker.py:313` | `_call_mistral` | dyn: api.groq.com,api.mistral.ai,api.x.ai,generativelanguage.googleapis.com,openrouter.ai + litellm:4000 | urllib | non |
| `tools/forge_collab_broker.py:352` | `_call_openrouter` | dyn: api.groq.com,api.mistral.ai,api.x.ai,generativelanguage.googleapis.com,openrouter.ai + litellm:4000 | urllib | non |
| `tools/forge_collab_broker.py:383` | `_call_cohere` | dyn: api.groq.com,api.mistral.ai,api.x.ai,generativelanguage.googleapis.com,open