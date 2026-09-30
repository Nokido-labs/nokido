---
name: nokido
description: >
  Nokido Sovereign Hub — orchestrateur multi-agents local-first.
  Hub HTTP:8766, bridge stdio, RAG SQLite, 196+ modules forge_*.py,
  7 rôles locaux (Ollama), 8 cloud roles (groq/github/mistral),
  forge_task_queue, forge_roles, forge_trust_score, forge_mailbox.
  Mis à jour automatiquement après chaque git commit.
---

# Nokido — Knowledge Base pour IAs collaboratrices

## Architecture rapide
- Hub : `tools/nokido_hub.py` — Starlette :8766
- Bridge : `tools/mcp_stdio_bridge.py` — stdio → HTTP
- Rôles : `app/forge_roles.py` — PLANNER/EXECUTOR/REVIEWER/ROUTER/SUMMARIZER/SENTINEL/MONITOR
- Queue : `app/forge_task_queue.py` — SQLite persistant, Semaphore(2)
- RAG : `RAG/embeddings.db` — 100K+ chunks bge-m3 1024d
- Rescue : `tools/forge_rescue.py` — canal de secours admin on-demand

## Changelog automatique (post-commit)








































































## Commit 5a395eb3 — 2026-06-25 13:52
**feat(skill): forge-workflow-autopsy - diagnose stalled autonomous pipelines**

### Documentation mise à jour
- `docs/skills/forge-workflow-autopsy/SKILL.md`


## Commit 3a756ff5 — 2026-06-25 13:48
**feat(skills): reorg script -> forge-* namespace (non-destructive, dry-run)**

### Modules Python modifiés
- `tools/forge_skills_reorg.py`


## Commit a1049136 — 2026-06-25 13:29
**fix(biblio): repair autonomous workflow - worker polls unverified (vocab mismatch)**

### Modules Python modifiés
- `app/forge_biblio_worker.py`
- `app/forge_health_diagnostic.py`


## Commit 2178c862 — 2026-06-25 12:23
**fix(memory): compactor archives dateless non-timeless entries too**

### Modules Python modifiés
- `tools/forge_memory_compactor.py`


## Commit f0769d64 — 2026-06-25 12:20
**fix(memory): force UTF-8 stdout in compactor (cp1252 crash on emoji print)**

### Modules Python modifiés
- `tools/forge_memory_compactor.py`


## Commit 66074a2f — 2026-06-25 12:17
**feat(memory): age-based compaction + ledger sync at SessionStart**

### Modules Python modifiés
- `tools/forge_memory_compactor.py`


## Commit 8ea8ca94 — 2026-06-25 12:10
**feat(memory): wire memory ledger into SessionStart compactor hook**

### Modules Python modifiés
- `tools/forge_memory_compactor.py`


## Commit f6067130 — 2026-06-25 12:08
**feat(memory): blockchain-style memory ledger failsafe (gate de secours)**

### Modules Python modifiés
- `tools/forge_memory_ledger.py`


## Commit e48241db — 2026-06-25 11:39
**fix(security): narrow prompt_guard bypass/ignore to injection-specific terms**

### Modules Python modifiés
- `app/forge_prompt_guard.py`


## Commit 4cc99a9c — 2026-06-25 11:31
**fix(security): kill prompt_guard FR/EN false-positives + close gaps (#2)**

### Modules Python modifiés
- `app/forge_prompt_guard.py`


## Commit b1c1ec19 — 2026-06-25 11:10
**feat(alignment): RSP gate trust-aware, reconcile with forge_exec_tier (#1)**

### Modules Python modifiés
- `tools/forge_rsp_gate.py`


## Commit 9955f6cc — 2026-06-25 11:06
**feat(security): quarantine injection-flagged web content at ingest (risk #1)**

### Modules Python modifiés
- `app/forge_rag_qualify.py`


## Commit 130da15c — 2026-06-25 10:48
**docs(manifesto): add 2.6 "Les quatre gestes de la forge"**

### Documentation mise à jour
- `MANIFESTO.md`


## Commit 6719adb0 — 2026-06-25 09:14
**docs(alignment): B2 declarative rails design (delegated to ANTIGRAVITY)**

### Documentation mise à jour
- `docs/B2_DECLARATIVE_RAILS_DESIGN.md`


## Commit 0bbfec98 — 2026-06-25 09:07
**fix(security): bound firewall redact_text - close residual DoS-hub wedge**

### Modules Python modifiés
- `app/forge_semantic_firewall.py`


## Commit 155ff75e — 2026-06-25 08:27
**feat(alignment): A#2 - is_human_locked gate on autonomous self-heal**

### Modules Python modifiés
- `app/forge_circadian.py`
- `app/forge_docker_monitor.py`
- `tools/forge_coagulation.py`


## Commit 999cfe7f — 2026-06-24 22:20
**feat(routing): P7 - wire route_solver into best() (owner-applied, flag-gated OFF)**

### Modules Python modifiés
- `tools/forge_pool_registry.py`


## Commit 55761987 — 2026-06-24 22:00
**feat(alignment): F3 - pre-push gate blocks on degraded HARD invariant (non-regression)**

### Modules Python modifiés
- `app/forge_git_egress.py`


## Commit a6293ec0 — 2026-06-24 21:39
**feat(alignment): F5 anomaly term (burst+sensor-fail) + F6 emit-fail counter**

### Modules Python modifiés
- `tools/forge_alignment_invariants.py`
- `tools/forge_alignment_trace.py`


## Commit ac2086e7 — 2026-06-24 21:34
**fix(alignment): F1 - status() verifies enforced_by anchors (kill meta-Goodhart)**

### Modules Python modifiés
- `tools/forge_alignment_invariants.py`


## Commit 1570420f — 2026-06-24 21:16
**feat(alignment): #5 lineage-collusion check + P6 pre-commit alignment non-regression**

### Modules Python modifiés
- `app/forge_separation.py`
- `tools/forge_git_gate.py`


## Commit 077f6bd5 — 2026-06-24 20:44
**feat(alignment): wire alignment_events into central retention (_retention_traces)**

### Modules Python modifiés
- `tools/forge_log_retention.py`


## Commit 616b35bd — 2026-06-24 19:43
**feat(alignment): P1 wiring 4/4 - forge_separation emits deny to sensor**

### Modules Python modifiés
- `app/forge_separation.py`


## Commit d8daebe6 — 2026-06-24 19:37
**feat(alignment): P3 comparator - alignment_health (homeostat set-point gap)**

### Modules Python modifiés
- `tools/forge_alignment_invariants.py`


## Commit 3110dd80 — 2026-06-24 19:36
**feat(alignment): P1 wiring - gates emit to observability sensor + bounded table**

### Modules Python modifiés
- `app/forge_skill_curator.py`
- `tools/forge_alignment_trace.py`
- `tools/forge_governed_edit.py`
- `tools/forge_memory_gate.py`


## Commit 2f2af5c7 — 2026-06-24 19:17
**chore(alignment): no_silent_downgrade ENFORCED - dashboard 8/8 (separation fix live post-reboot)**

### Modules Python modifiés
- `tools/forge_alignment_invariants.py`


## Commit 74be60b5 — 2026-06-24 19:12
**fix(separation): remove dashboard from judge_modules (false-positive blocked maintenance)**

### Modules Python modifiés
- `app/forge_separation.py`


## Commit 1a21b337 — 2026-06-24 19:05
**feat(alignment): P1 observability sensor - alignment_trace (service mesh capteur)**

### Modules Python modifiés
- `tools/forge_alignment_trace.py`


## Commit af2f20dc — 2026-06-24 19:00
**feat(alignment): skill_promotion_review (p53 oncoguard) - Wilson significance vs gameable raw rate**

### Modules Python modifiés
- `app/forge_skill_curator.py`
- `tools/forge_alignment_invariants.py`
- `tools/forge_oncoguard.py`


## Commit b791f372 — 2026-06-24 18:55
**feat(alignment): no_self_score_edit - block agents editing judge modules (anti reward-tampering)**

### Modules Python modifiés
- `tools/forge_alignment_invariants.py`
- `tools/forge_governed_edit.py`


## Commit 1225f073 — 2026-06-24 18:49
**chore(alignment): ephemeral_secrets ENFORCED (AGY CapabilityTokens, cross-reviewed)**

### Modules Python modifiés
- `tools/forge_alignment_invariants.py`


## Commit 0fb2af49 — 2026-06-24 18:44
**feat(alignment): wire memory_gate into anchor_solution (P2a ENFORCED, anti-confabulation)**

### Modules Python modifiés
- `app/forge_self_correction.py`
- `tools/forge_alignment_invariants.py`


## Commit d1b15645 — 2026-06-24 18:40
**feat(alignment): P2a memory_gate - reject noise/low-trust before ingest (anti-confabulation)**

### Modules Python modifiés
- `tools/forge_alignment_invariants.py`
- `tools/forge_memory_gate.py`


## Commit 52ccbcd8 — 2026-06-24 18:36
**feat(alignment): P0 Purpose Framework - machine-readable invariants + enforcement dashboard**

### Modules Python modifiés
- `tools/forge_alignment_invariants.py`


## Commit a50c7021 — 2026-06-24 18:22
**security(egress): detect unknown-format secrets in context on prose (root cause of 2nd token leak)**

### Modules Python modifiés
- `app/forge_git_egress.py`


## Commit 38d89b5c — 2026-06-24 18:17
**security(history-redact): cover non-PAT tokens (Models/HF) via contextual value extraction**

### Modules Python modifiés
- `tools/forge_history_redact_v2.py`


## Commit b0ef733c — 2026-06-24 18:05
**security: redact 2nd leaked token (GITHUB_MODELS_TOKEN, non-PAT format)**

### Documentation mise à jour
- `docs/archive/reviews/HANDOFF-2026-04-25-security.md`


## Commit 5a726374 — 2026-06-24 17:34
**docs(alignment): roadmap homeostat axiologique (anti-derive, P0-P7)**

### Documentation mise à jour
- `docs/ALIGNMENT_HOMEOSTAT_ROADMAP.md`


## Commit 101131a7 — 2026-06-24 17:00
**security: redact leaked GitHub PAT in archived handoff**

### Documentation mise à jour
- `docs/archive/reviews/HANDOFF-2026-04-25-security.md`


## Commit 7673ec56 — 2026-06-24 16:49
**feat(rsp): forge_rsp_gate - ASL matrix materialized as exec gate (Gap C)**

### Modules Python modifiés
- `tools/forge_rsp_gate.py`


## Commit 90af32ad — 2026-06-24 16:45
**feat(corrigibility): subordinate watchdog self-heal to human kill-switch (A#2)**

### Modules Python modifiés
- `app/forge_service_watchdog.py`


## Commit c8797518 — 2026-06-24 16:37
**docs(audit): cross-review CLAUDE - quality_floor guard + ortools claim**

### Documentation mise à jour
- `docs/AUDIT_GOODHART_SCORES.md`


## Commit 1e536448 — 2026-06-24 16:13
**feat(corrigibility): wire is_network_kill into firewall pre_flight waist**

### Modules Python modifiés
- `app/forge_semantic_firewall.py`


## Commit 8aca42dd — 2026-06-24 15:47
**feat(safety): AI-safety memo + forge_route_solver (anti-Goodhart routing)**

### Modules Python modifiés
- `tools/forge_route_solver.py`

### Documentation mise à jour
- `docs/AI_SAFETY_APPLIQUEE_NOKIDO.md`


## Commit e04bd5ea — 2026-06-24 15:20
**fix(searxng): make keeper _log encoding-safe (cp1252 arrow crash)**

### Modules Python modifiés
- `tools/forge_searxng_keeper.py`


## Commit ae029896 — 2026-06-16 22:27
**feat(llm): implement dynamic free model cascade and openrouter refresh**

### Modules Python modifiés
- `app/forge_agent_proxy.py`
- `app/forge_llm_router.py`


## Commit 63fb2b34 — 2026-06-16 22:24
**feat(security): residual gemini fixes (integrity TTL, firewall salt, membrane encryption, prompt guard squash)**

### Modules Python modifiés
- `app/forge_integrity.py`
- `app/forge_prompt_guard.py`
- `app/forge_semantic_firewall.py`
- `app/forge_sovereign_membrane.py`

### Documentation mise à jour
- `README.md`


## Commit 374d4e1e — 2026-06-16 21:57
**feat(mcp_lab): forms fideles par tool (form_from_jsonschema runtime)**

### Modules Python modifiés
- `app/web_hub/mcp_lab.py`

### Documentation mise à jour
- `README.md`


## Commit fc3ac658 — 2026-06-16 21:38
**feat(hub): tool MCP governed_edit — edition gouvernee in-process (ecrit app/)**

### Modules Python modifiés
- `app/forge_mcp_registry.py`
- `tools/forge_search_replace.py`


## Commit 1a840ab8 — 2026-06-16 21:28
**feat(moulinette): render_form_html — genere+rend le form d'un coup (endpoint runtime)**

### Modules Python modifiés
- `tools/forge_ui_moulinette.py`


## Commit b01b27ce — 2026-06-16 21:23
**feat(moulinette): forge_ui_repo_cover — couvre tous les tools hub en forms fid500les**

### Modules Python modifiés
- `tools/forge_ui_repo_cover.py`


## Commit 1a07fc55 — 2026-06-16 21:21
**feat(moulinette): form_from_jsonschema — UI fidele depuis contrat JSON Schema (couvrir le depot)**

### Modules Python modifiés
- `tools/forge_ui_moulinette.py`


## Commit 7afe3ab1 — 2026-06-16 21:15
**feat(moulinette): if/for/setup + fix indent enfants (gere composants reels)**

### Modules Python modifiés
- `tools/forge_ui_moulinette.py`


## Commit 6f6d188d — 2026-06-16 21:15
**feat(web_hub): module_card_html — 1er composant design_handoff genere par la moulinette**

### Modules Python modifiés
- `app/web_hub/module_card_html.py`


## Commit 5934b569 — 2026-06-16 21:08
**feat: forge_ui_moulinette — moulinette UI souveraine (economie tokens)**

### Modules Python modifiés
- `tools/forge_ui_moulinette.py`


## Commit 7be0e2f8 — 2026-06-16 21:05
**feat: forge_search_replace — applier SEARCH/REPLACE Aider-style (brique moulinette UI)**

### Modules Python modifiés
- `tools/forge_search_replace.py`


## Commit 9bd6927d — 2026-06-16 20:50
**feat(docset): forge_docset_ingest — extraction bulk docset -> RAG (domain=reference)**

### Modules Python modifiés
- `tools/forge_docset_ingest.py`


## Commit aed64e9a — 2026-06-16 20:35
**refactor(cli): deport Gemini via POLICY ENGINE (decision=deny, tier USER)**

### Modules Python modifiés
- `tools/forge_cli_tool_deport.py`


## Commit 8d7d28b5 — 2026-06-16 20:21
**perf(blackboard): connexion writer PERSISTANTE (supprime churn connect+PRAGMA/write)**

### Modules Python modifiés
- `app/forge_swarm_blackboard.py`


## Commit 3c93fbd7 — 2026-06-16 19:53
**fix(docker): subprocess errors=replace sur docker ps + tasklist (anti-crash binaire)**

### Modules Python modifiés
- `tools/forge_docker_keeper.py`


## Commit ee7f492e — 2026-06-16 19:51
**feat(docker): wsl --shutdown en session OWNER -> auto-recovery stuck-starting durable**

### Modules Python modifiés
- `tools/forge_docker_keeper.py`


## Commit 12b833b9 — 2026-06-16 19:45
**perf(rag): lexical FTS5 -> to_thread + DROP du fetch full-table mort (P0 finish)**

### Modules Python modifiés
- `app/forge_rag_engine.py`


## Commit ef884363 — 2026-06-16 19:17
**fix(cli): deport ecrit tools.exclude (VRAIE cle gemini v0.46, lue dans le schema)**

### Modules Python modifiés
- `tools/forge_cli_tool_deport.py`


## Commit 42510f4d — 2026-06-16 19:12
**fix(cli): deport ecrit tools.excludeTools NESTED (vraie cle gemini v0.46)**

### Modules Python modifiés
- `tools/forge_cli_tool_deport.py`


## Commit 2b74cef9 — 2026-06-16 19:02
**fix(cli): deport fail-safe verifie la vue MERGEE (hub MCP du home compte pour le workspace)**

### Modules Python modifiés
- `tools/forge_cli_tool_deport.py`


## Commit 396c7e7b — 2026-06-16 18:59
**fix(cli): deport cible le settings gemini EFFECTIF (workspace > user)**

### Modules Python modifiés
- `tools/forge_cli_tool_deport.py`


## Commit dfcf0600 — 2026-06-16 18:48
**perf(rag): cache matrice embeddings + normes (P1, stop rebuild 30k x 1024/search)**

### Modules Python modifiés
- `app/forge_rag_engine.py`


## Commit 0ce120f7 — 2026-06-16 18:37
**feat(isolation+wasm): forge_worktree (fix clobber) + forge_wasm_sandbox (tier wasm reel)**

### Modules Python modifiés
- `tools/forge_wasm_sandbox.py`
- `tools/forge_worktree.py`


## Commit f5ab5f26 — 2026-06-16 18:23
**perf(rag): search sim numpy -> asyncio.to_thread (Phase 0 concurrence)**

### Modules Python modifiés
- `app/forge_rag_engine.py`


## Commit 5d65e434 — 2026-06-16 18:14
**docs(concurrency): plan migration hub multithread (multi-process isolation, PAS nogil-flip)**

### Documentation mise à jour
- `docs/HUB_CONCURRENCY_MIGRATION.md`


## Commit 76f2e239 — 2026-06-16 17:04
**refactor(skills): migration taxonomie A hybride appliquee (24->14)**

### Modules Python modifiés
- `app/forge_skill_enricher.py`
- `app/forge_skill_policy.py`
- `tools/forge_skill_sync.py`

### Documentation mise à jour
- `docs/skills/forge-connectors/SKILL.md`
- `docs/skills/forge-core/ARCHITECTURE.md`
- `docs/skills/forge-core/BACKENDS.md`
- `docs/skills/forge-core/CLAWHUB.md`
- `docs/skills/forge-core/CTF.md`
- `docs/skills/forge-core/RECON.md`
- `docs/skills/forge-core/REFERENCE.md`
- `docs/skills/forge-core/SECURITY.md`
- `docs/skills/forge-core/SKILL.md`
- `docs/skills/forge-marketplace/SKILL.md`

