# Plan de migration modules legacy → sous-packages (Priorité 3 Gemini)

## État de la migration

- **Phase 1 (DONE 2026-04)** : `app/agents/__init__.py` créé (facade non-breaking) 
- **Phase 2 (EN COURS)** : squelettes de sous-packages créés dans `app/core/`, `app/llm/`, `app/ui/`, `app/orchestration/`, `app/security/`, `app/hardware/`, `app/ctf/`
- **Phase 3 (TODO)** : déplacement effectif des modules. Nécessite :
  1. Tests de non-régression AVANT déplacement
  2. Update imports dans tous les fichiers consommateurs
  3. Stubs de rétrocompat dans les anciens emplacements

## Table de correspondance

| Legacy module | Destination |
|---------------|-------------|
| ✅ `Nokido.py` | `ui/tui_app.py (extraction NokidoApp) + bootstrap entrypoint` |
| ✅ `bootstrap.py` | `core/bootstrap.py` |
| ✅ `ctf_ghidra.py` | `ctf/ghidra.py` |
| ✅ `ctf_layout.py` | `ctf/layout.py` |
| ✅ `ctf_planner.py` | `ctf/planner.py` |
| ✅ `ctf_rag.py` | `ctf/rag.py` |
| ✅ `ctf_validator.py` | `ctf/validator.py` |
| ✅ `forge_adaptive_pwn.py` | `ctf/pwn_engine.py` |
| ✅ `forge_agent_authority.py` | `agents/governance.py (Phase 2)` |
| ✅ `forge_agent_benchmarker.py` | `agents/benchmarking.py (ou archive si orphelin)` |
| ✅ `forge_agent_hardware.py` | `agents/hardware_scoring.py (Phase 2)` |
| ✅ `forge_agent_roles.py` | `agents/roles.py (Phase 2)` |
| ✅ `forge_agentic.py` | `agents/handlers.py (Phase 2)` |
| ✅ `forge_agents.py` | `agents/ (via facade __init__.py)` |
| ✅ `forge_app_context.py` | `core/context.py (fusion)` |
| ✅ `forge_at_dispatch.py` | `orchestration/at_dispatcher.py` |
| ✅ `forge_autonomous_orchestrator.py` | `agents/orchestrator.py (Phase 2)` |
| ✅ `forge_boot.py` | `core/bootstrap.py (avec bootstrap.py existant)` |
| ✅ `forge_code.py` | `security/code_guard.py + sandbox/code_sandbox.py (split)` |
| ⬜ `forge_code_guard.py` | `security/code_guard.py (fusion)` |
| ✅ `forge_cognitive_router.py` | `llm/cognitive_router.py` |
| ✅ `forge_collab_modes.py` | `orchestration/collab_modes.py` |
| ✅ `forge_compose.py` | `orchestration/compose.py` |
| ✅ `forge_context.py` | `core/context.py` |
| ✅ `forge_conv_sanitizer.py` | `security/conv_sanitizer.py` |
| ✅ `forge_ctf_adaptive.py` | `ctf/adaptive.py` |
| ✅ `forge_ctf_agent.py` | `ctf/agent.py` |
| ✅ `forge_ctf_benchmark.py` | `ctf/benchmark.py` |
| ✅ `forge_cyber_pivot.py` | `ctf/cyber_pivot.py` |
| ✅ `forge_cyber_pivot_engine.py` | `ctf/cyber_pivot.py (fusion)` |
| ⬜ `forge_danger_guard.py` | `security/danger_guard.py` |
| ✅ `forge_dispatch.py` | `orchestration/dispatch_core.py` |
| ✅ `forge_dispatch_ai.py` | `orchestration/dispatch_ai.py` |
| ✅ `forge_dispatch_network.py` | `orchestration/dispatch_network.py` |
| ✅ `forge_events.py` | `core/events.py` |
| ✅ `forge_gemini_bridge.py` | `llm/backends/gemini.py` |
| ✅ `forge_ghost_router.py` | `llm/ghost_router.py` |
| ✅ `forge_hw_allocator.py` | `hardware/allocator.py` |
| ✅ `forge_idle_watchdog.py` | `hardware/idle_watchdog.py` |
| ✅ `forge_libc_resolver.py` | `ctf/libc_resolver.py` |
| ✅ `forge_litellm_bridge.py` | `llm/backends/litellm.py` |
| ✅ `forge_litellm_connector.py` | `llm/backends/litellm.py (fusion)` |
| ✅ `forge_llamacpp.py` | `llm/backends/llamacpp.py` |
| ✅ `forge_llm_router.py` | `llm/router.py` |
| ✅ `forge_logging.py` | `core/logging.py` |
| ✅ `forge_mem_watchdog.py` | `hardware/mem_watchdog.py` |
| ✅ `forge_mmap_context.py` | `core/context.py (fusion)` |
| ✅ `forge_ollama.py` | `llm/backends/ollama.py` |
| ✅ `forge_ollama_bridge.py` | `llm/backends/ollama.py (fusion)` |
| ✅ `forge_openrouter.py` | `llm/backends/openrouter.py` |
| ✅ `forge_orchestrator.py` | `orchestration/main_orchestrator.py` |
| ✅ `forge_prompt_builder.py` | `llm/prompt_builder.py` |
| ✅ `forge_prompt_guard.py` | `llm/prompt_guard.py` |
| ✅ `forge_pty.py` | `ui/pty_terminal.py` |
| ✅ `forge_retry_strategies.py` | `core/retry.py` |
| ✅ `forge_router_gateway.py` | `llm/gateway.py` |
| ✅ `forge_settings.py` | `core/settings.py` |
| ✅ `forge_spike_router.py` | `llm/spike_router.py` |
| ✅ `forge_state.py` | `core/state.py` |
| ✅ `forge_ui_widgets.py` | `ui/widgets.py` |
| ✅ `forge_version.py` | `core/versioning.py` |
| ✅ `forge_versioning.py` | `core/versioning.py (fusion)` |
| ✅ `hardware_monitor.py` | `hardware/monitor.py` |


## Règle d'or

- **JAMAIS** déplacer un fichier sans avoir mis à jour TOUS ses importeurs
- **JAMAIS** supprimer un fichier legacy sans avoir mis en place un stub de rétrocompat
- **TOUJOURS** tester `py_compile` + tests `nr/` après chaque migration

## Commande safe pour tester

```bash
python -m py_compile app/LaForge.py app/forge_state.py app/brain_worker.py
python -m pytest tests/nr -x --tb=short
```

## Priorités dans Phase 3 (ordre recommandé)

1. **Modules indépendants** (pas d'imports croisés) : ctf/, hardware/
2. **Modules à faible couplage** : security/, rag/
3. **Modules à fort couplage** : core/ (state déjà OK), llm/ (fusion backends)
4. **Monolithes** : Nokido.py (dernier, risque max)
