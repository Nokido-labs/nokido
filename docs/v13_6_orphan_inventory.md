# Inventaire orphelins v13.6 era — gemmes à ré-évaluer

**Date** : 2026-05-02
**Source** : `app/_attic/shadow_mutation_2026-04/` + `app/legacy/` + `archive/vague3_migration_*/`

User feedback : "vérifie qu on a pas laissé de bonnes idées en v13.6".

---

## 🏆 Top 10 modules orphelins haute valeur

### 1. `forge_knowledge_distiller.py` (232 LOC) ⭐⭐⭐
**Distille connaissance Nokido → projet portable.**
- Extrait : system_rules ring 0-2 + patterns architecturaux + best practices + glossaire
- Produit : `<project>_knowledge.json` + `<project>_rag.db` + `<project>_primer.md`
- CLI : `--project mon-projet --output /chemin/`
- **Use case actuel** : cycle Faire-Savoir étendu. Nokido transmet sa sagesse à
  fork ou autre instance.
- **Décision** : ⭐ **RESSUSCITER** dans `app/forge_knowledge_distiller.py`.

### 2. `forge_knowledge_harvester.py` (170 LOC) ⭐⭐⭐
**On_Success_Test_Pass extract reasoning_path + architecture_decision + pitfall_avoided + template.**
- Trigger : test pass
- Store : Ring5_RAG_Expert_System (rag_chunks + event_log)
- **Use case actuel** : enrichit cycle Singularité. Capture automatique meilleures
  pratiques après succès tool_smith.
- **Décision** : ⭐ ressusciter post-Phase G stabilisation.

### 3. `forge_autonomous_orchestrator.py` (V17) ⭐⭐
**Intent_to_Action_Graph DAG : Parse → DAG → Execute.**
- Multiplexeur OneMCP local + cloud
- **Use case actuel** : remplacer ou enrichir `forge_dispatchers` actuel
  (linéaire) par DAG parallèle.
- **Décision** : étudier Phase H ou plus tard.

### 4. `forge_auto_pilot.py` (Ring 5.5 Système Végétatif Autonome) ⭐⭐⭐
**MMap-driven déclencheurs auto-heal.**
- gui.heartbeat > 10s → restart_service NSSM
- inspector.drift > 0.85 → context_rollback
- inspector.entropy < -0.5 → flush context + reset swarm
- llm.*.vram_mb > 95% → clear_cache
- swarm.state == THINKING > 90s → force_idle
- mesh.last_adr → auto-ingest ADR dans RAG
- ADR-010 → ADR-011 référencé
- **Use case actuel** : étend `forge_autonomous_loops` avec déclencheurs
  threshold-based (pas seulement time-based).
- **Décision** : ⭐ pattern à intégrer (déclencheurs threshold).

### 5. `forge_ghost_router.py` ⭐⭐
**GGUF turbo router (qwen3-0.6b prompts courts).**
- État GHOST_CONTEXT_MAX_V1
- Catalogue : default qwen3-0.6b (ctx 4096, max_tok 512), complex qwen2.5-coder-7b (ctx 16384)
- **Use case actuel** : layer ultra-rapide avant llama.cpp pour décisions binaires.
- **Décision** : utile si latency llama.cpp insuffisante.

### 6. `forge_onnx_genai.py` (337 LOC) ⭐⭐
**Moteur LLM local ONNX Runtime GenAI DirectML/VitisAI NPU.**
- Phi-3.5-mini-instruct-onnx + Qwen2.5-Coder-3B-Instruct-ONNX
- DirectML AMD/Intel/NVIDIA
- **Use case actuel** : alternative brain_worker via ORT GenAI direct.
- **Décision** : SKIP — brain_worker ZMQ ryzen-ai-1.7.0 NPU déjà optimal.

### 7. `legacy/scoring.py` ⭐⭐⭐
**ModelScorer banque scoring + détection arch + best_model_for_role.**
- Scores statiques par rôle/tâche
- Benchmark dynamique (tokens/s, qualité, latence)
- ArchitectureProfile (OS/CPU/containers)
- best_model_for(role, arch) — sélection auto
- **Use case actuel** : améliore `forge_llm_router.call_cascade` choix provider.
- **Décision** : ⭐ pattern à étudier.

### 8. `legacy/danger_guard.py` ⭐⭐⭐
**Intercepte commands SSH dangereuses (rm -rf, etc).**
- Niveaux : INFO / WARNING / CRITICAL / FATAL
- Explication risque langage naturel
- API ask_confirmation
- **Use case actuel** : intègre dans `code_critic.localOpsecScan` Phase G.
- **Décision** : ⭐ patterns à porter dans code_critic.

### 9. `legacy/predictif.py` ⭐⭐
**NLU adaptatif Bayesian + AdaptiveLearner.**
- 80% statique → 95%+ après learning
- Persistance JSON
- **Use case actuel** : enrichit forge_dispatchers routing intelligent.
- **Décision** : étudier.

### 10. `legacy/codesandbox.py` ⭐⭐⭐
**generate_and_test via Ollama + AST + sandbox + score prédictif.**
- ⭐ **Phase G.5 Docker ephemeral pre-existant pattern !**
- AST static analysis
- Exec sandbox timeout strict
- Score prédictif par type tâche
- **Décision** : ⭐ référence directe Phase G.5.

---

## 🥈 Autres modules orphelins (study)

| Module | LOC | Note |
|---|---|---|
| `canvas_nodes.py` | 270 | Nodes UI canvas (vue graph alternative) |
| `forge_distribution.py` | 404 | Arbre Distribution SQLite v16.6 |
| `forge_mutation_cache.py` | 82 | Cache mutations par hash bloc |
| `forge_unified_logger.py` | 198 | Logger structuré unifié |
| `forge_logger.py` | 107 | Variant logger |
| `legacy/loops.py` | gros | Amélioration autonome v3 + ErrorMemory cross-boucles |
| `legacy/arbre.py` | ? | Probablement skilltree v1 |
| `legacy/RAGv2.py` | ? | RAG hybrid pymupdf4llm + LangChain ensemble |
| `legacy/predictif.py` | ? | NLU adaptatif Bayesian |
| `legacy/scapyshark.py` | ? | Capture network scapy |
| `legacy/snif.py` | ? | Sniffer |
| `legacy/onnx_backend.py` | ? | ONNX backend v1 |
| `legacy/routage.py` | ? | Routage ancien |
| `legacy/codetesteur.py` | ? | Code testeur ancien |

---

## 🎯 Action plan ressuscitation

### Phase 1 — Faire-Savoir étendu (immédiat)
- ⭐ `forge_knowledge_distiller` → ressusciter `app/forge_knowledge_distiller.py`
- Use case : Nokido peut produire `nokido_knowledge_pack.json` exporté
  vers nouvelle instance (transfert sagesse)

### Phase 2 — Sécurité Phase G renfort
- ⭐ Patterns `legacy/danger_guard` → intégrer dans
  `code_critic.localOpsecScan()` (rm -rf, sudo, escalade, exfiltration patterns)

### Phase 3 — Auto-loops étendu
- ⭐ Patterns `forge_auto_pilot` thresholds → ajouter déclencheurs
  threshold-based dans `forge_autonomous_loops` (en plus interval)

### Phase 4 — LLM router intelligent
- `legacy/scoring.py` ModelScorer + ArchitectureProfile → enrichir
  `forge_llm_router.call_cascade`

### Phase 5 — Knowledge harvester
- `forge_knowledge_harvester` → trigger `On_Success_Test_Pass` après
  forge_tool succès Phase G

---

## 🚫 NE PAS ressusciter

| Module | Raison |
|---|---|
| `forge_onnx_genai` | brain_worker NPU ryzen-ai déjà optimal |
| `forge_handler_advanced_bak_*.py` | Bak files, code current refactor |
| `forge_banner.py` | 4 LOC stub (déjà supprimé) |
| `forge_core_agents.py` (1741 LOC) | Refactorisé en multiple forge_agents.py current |

---

## 🆕 Découvertes batch 2 (au-delà .py shadow)

### `archive/cockpit_textual_dropped_20260418_122641/` ⭐⭐⭐⭐
**TUI complet abandonné — 7 screens Textual !**
- `dashboard.py` métriques + statut services DI
- `chat.py` LLM multi-backends via NokidoFacade async
- `exegol.py` Docker control + CTF + outils + CH88
- `architecture.py` docs refacto + mermaid + DirectoryTree + MarkdownViewer
- `monitoring.py` logs tail + breakers + métriques temps réel + TabbedContent
- `tools.py` tests NR + lints + skills + snapshots
- `nokido_cockpit.py` launcher unifié bindings d/c/e/a/m/t/q

**Use case actuel** : `tools/nokido_tui.py` v3 actuel = chat-multi-CLI seulement.
Ces screens étendent vers **TUI complète productivité** (architecture/monitoring/
exegol). Pourrait fusionner avec nokido_tui en ajout TabPane par screen.
- **Décision** : ⭐ ressusciter sélectivement screens `monitoring` + `architecture`
  + `tools` post-Phase B.4.

### `app/_attic/forge_thought_interceptor.py` ⭐⭐⭐
**Capture chaîne raisonnement (CoT) `<think>...</think>` DeepSeek-R1.**
- ForgeThoughtInterceptor wrapper MultiLLMBridge
- Sépare `thought` du `content` final
- Métadonnées : model, ms latency
- **Use case actuel** : Phase H Self-Refinement multi-LLM. Si Critic =
  DeepSeek-R1, capturer le raisonnement renforce audit logs + apprentissage.
- **Décision** : ⭐ **RESSUSCITER** maintenant.

### `app/_attic/forge_unified_logger.py` ⭐⭐
**Logger ring-aware centralisé v17.**
- `get_logger("module", ring=2)`
- `log.ring_in("llm_router", "debate", "msg")`
- Compatible RBAC ring 0-5
- **Use case actuel** : remplace logger ad-hoc dispersé.
- **Décision** : étude (déjà partial via std logging).

### `app/_attic/forge_starter.c`
**Cython-compiled forge_starter (perf init).**
- Source : forge_starter.py compilé via Cython 3.2.4
- **Use case actuel** : pas trouvé forge_starter.py current → SKIP.

### `legacy/boitaswitch.py` ⭐⭐
**Agent réseau SSH/Telnet/SNMP Cisco/HP/Aruba/Juniper/MikroTik/Huawei/Fortinet.**
- **Use case actuel** : déjà couvert par `netcfg-agent` Docker container.
- **Décision** : SKIP (duplicate netcfg).

### `legacy/scapyshark.py` ⭐⭐
**Mini IDS scapy + pyshark sniff packets + suspect_ips set.**
- Détection trafic suspect
- **Use case actuel** : sécurité passive réseau.
- **Décision** : étude pour module sécurité futur.

### `legacy/snif.py`
**Network discovery nmap + zeroconf + miniupnpc + SNMP.**
- Couvert par netcfg-agent.
- **Décision** : SKIP.

### `legacy/onnx_backend.py` ⭐⭐⭐
**all-MiniLM-L6-v2 ONNX 2ms vs Ollama 200-500ms (100x speedup embeddings) !**
- Synchrone wrappé run_in_executor
- **Use case actuel** : brain_worker NPU déjà bge-m3, mais l-MiniLM ONNX
  pourrait servir fallback CPU léger.
- **Décision** : étude (vérifier vs brain_worker actual perf).

### `legacy/roles.py` ⭐⭐⭐
**5 rôles IA codecycle : ANALYSTE / DEBUGGER / COMPARATEUR / STRATEGE / JUGE.**
- Fork OctoDevOps v5
- **Use case actuel** : code_critic Phase G utilise 1 critic. Pattern
  multi-rôles permettrait peer review structuré (ANALYSTE détecte risques
  arch, DEBUGGER bugs, JUGE verdict final).
- **Décision** : ⭐ **RESSUSCITER** patterns dans code_critic.

### `legacy/routage.py` ⭐
**Moteur routage multi-agents (remplace modeplanner).**
- Couvert par forge_dispatchers + forge_trajectory.
- **Décision** : SKIP.

### `legacy/web.py` ⭐
**DDGS singleton + RAG (recherche web).**
- Couvert par forge_search ou MCP_DOCKER searxng.
- **Décision** : SKIP.

### `legacy/nokido_testable.py`
**Shim test extraction classes par marqueurs textuels.**
- Pattern test résilient (pas line numbers).
- **Décision** : étude pour test infra.

### `archive/2026-04-audit/` MIGRATION_LOG.md
**Log archivage massif 2026-04-18.**
- 50+ modules archivés en _attic/
- Décisions kill/defer/investigate documentées
- **Décision** : référence historique uniquement.

### `app/backups/auto_boot_*.py` (8 versions 2026-03 → 2026-04)
**Évolution boot Nokido.**
- Audit historique évolution startup
- **Décision** : SKIP (current forge_runtime utilisé).

---

## 📊 Synthèse

- **116 modules** dans `_attic/shadow_mutation_2026-04`
- **18 modules** dans `legacy/`
- **27 modules** dans `archive/vague3_migration_*`
- Total ~161 fichiers v13.6 era
- **10 modules haute valeur identifiés**
- **5 ressusciter** (Phases 1-5 ci-dessus)
- **5 référence/study only**

User pattern ⭐ : "ne pas réinventer". Réutiliser knowledge accumulée
v13.6 quand pertinent. Cycle Faire-Savoir étendu temporellement.
