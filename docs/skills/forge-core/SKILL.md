---
name: forge-core
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

























































































































































































































































































































































































































































































































































































































































































































































































































































































































































































































































































































































































































































































































































































## Commit 32841089 — 2026-06-16 17:01
**feat(skills): forge_skill_migrate — migration taxonomie A hybride (24->14)**

### Modules Python modifiés
- `tools/forge_skill_migrate.py`


## Commit 6cc450ca — 2026-06-16 16:44
**feat(gate): forge_tool_gate — gate unifie cross-CLI des appels d outils**

### Modules Python modifiés
- `tools/forge_tool_gate.py`


## Commit 49b5ff6e — 2026-06-16 16:31
**feat(edit): forge_governed_edit — coeur du write gouverne (intercepte le write CLI)**

### Modules Python modifiés
- `tools/forge_governed_edit.py`


## Commit c2909ef5 — 2026-06-16 16:27
**feat(cli): forge_cli_tool_deport — deporte les tools natifs CLI vers le hub**

### Modules Python modifiés
- `tools/forge_cli_tool_deport.py`


## Commit 19c26ff6 — 2026-06-16 16:08
**fix(keyrot): _BAD_TTL — bad se rearme apres 6h (revive cles re-fournies)**

### Modules Python modifiés
- `app/forge_key_rotation.py`


## Commit 4a65562c — 2026-06-16 15:53
**feat(endpoints): forge_endpoint_registry — source unique d identite endpoints LLM**

### Modules Python modifiés
- `tools/forge_endpoint_registry.py`


## Commit bb1e3688 — 2026-06-10 05:00
**fix(veille): clone temp sous sandbox/workspace (trusted-writable, pas TMP defaut)**

### Modules Python modifiés
- `tools/forge_veille_clone_ingest.py`

### Documentation mise à jour
- `README.md`
- `docs/skills/nokido/SKILL.md`


## Commit 7bc6e0ec — 2026-06-10 04:59
**feat(veille): clone+ingest souverain (git clone -> dump -> RAG) sans SearXNG/SDK gitingest**

### Modules Python modifiés
- `tools/forge_veille_clone_ingest.py`


## Commit d0febbbc — 2026-06-10 04:50
**feat(sync): CLI sync Phase 1 - broadcast notify to=ALL + COPILOT inject + presence whoami**

### Modules Python modifiés
- `app/forge_mcp_registry.py`
- `tools/hub_lifecycle_hooks.py`


## Commit 53dfea21 — 2026-06-10 03:04
**fix(adb): screenshot via screencap fichier + pull (exec-out flaky sur adb-tls)**

### Modules Python modifiés
- `tools/forge_adb.py`

### Documentation mise à jour
- `README.md`
- `docs/skills/nokido/SKILL.md`


## Commit 9edf5871 — 2026-06-10 03:00
**feat(adb): reverse/open/screenshot - tester l'UI web Starlette depuis le device + capture**

### Modules Python modifiés
- `tools/forge_adb.py`

### Documentation mise à jour
- `README.md`
- `docs/skills/nokido/SKILL.md`


## Commit 08ac6bf9 — 2026-06-10 02:30
**feat(vm): action aaaa off|on - AdGuard aaaa_disabled (fix IPv6 externe casse qui fige les apps)**

### Modules Python modifiés
- `tools/forge_vm_dns.py`

### Documentation mise à jour
- `README.md`
- `docs/skills/nokido/SKILL.md`


## Commit b21f15f0 — 2026-06-10 02:27
**feat(vm): action dns64 off|status - coupe DNS64 AdGuard (NAT64 64:ff9b casse les apps)**

### Modules Python modifiés
- `tools/forge_vm_dns.py`

### Documentation mise à jour
- `README.md`
- `docs/skills/nokido/SKILL.md`


## Commit 391bf240 — 2026-06-10 02:04
**feat(vm): action recent <ip> - toutes requetes device (allowed+bloquees) pour pattern jeu**

### Modules Python modifiés
- `tools/forge_vm_dns.py`

### Documentation mise à jour
- `README.md`
- `docs/skills/nokido/SKILL.md`


## Commit 070e1819 — 2026-06-10 01:55
**feat(vm): blocked dedup par domaine + filtre IP (coupe spam telemetrie)**

### Modules Python modifiés
- `tools/forge_vm_dns.py`

### Documentation mise à jour
- `README.md`
- `docs/skills/nokido/SKILL.md`


## Commit 9538d1e3 — 2026-06-10 01:53
**feat(vm): allow safe (backup+stop+edit+start+rollback) pour whitelist AdGuard**

### Modules Python modifiés
- `tools/forge_vm_dns.py`

### Documentation mise à jour
- `README.md`
- `docs/skills/nokido/SKILL.md`


## Commit 40236149 — 2026-06-10 01:49
**fix(vm): blocked via sudo -n (querylog root-only) + dump brut si rien parse**

### Modules Python modifiés
- `tools/forge_vm_dns.py`

### Documentation mise à jour
- `README.md`
- `docs/skills/nokido/SKILL.md`


## Commit 5f881549 — 2026-06-10 01:45
**fix(vm): ssh known_hosts=nul + StrictHostKeyChecking=no (HOME LaForgeTrusted=C:/WINDOWS non-writable)**

### Modules Python modifiés
- `tools/forge_vm_dns.py`

### Documentation mise à jour
- `README.md`
- `docs/skills/nokido/SKILL.md`


## Commit 42b85ca3 — 2026-06-10 01:45
**fix(vm): ssh.exe natif (OpenSSH) au lieu d'asyncssh (cffi casse) + cle PRIVATE_KEY_PATH**

### Modules Python modifiés
- `tools/forge_vm_dns.py`

### Documentation mise à jour
- `README.md`
- `docs/skills/nokido/SKILL.md`


## Commit 3a42e656 — 2026-06-10 01:44
**fix(vm): forge_vm_dns - asyncssh + lecture SSH_HOST/USER/PORT/PASS/KEY canoniques + scan elargi**

### Modules Python modifiés
- `tools/forge_vm_dns.py`

### Documentation mise à jour
- `README.md`
- `docs/skills/nokido/SKILL.md`


## Commit 52d7a285 — 2026-06-10 01:40
**feat(vm): forge_vm_dns trusted - debug/unblock AdGuard VM StackDNS (discover/blocked/inspect/allow)**

### Modules Python modifiés
- `tools/forge_vm_dns.py`


## Commit 12d5fbd7 — 2026-06-10 01:07
**add adb bridge**

### Modules Python modifiés
- `tools/forge_adb.py`


## Commit 1bcaf027 — 2026-06-10 01:06
**feat(design): passe 3 - composants souverains .lf-gauge/.lf-power/.lf-module/.lf-step**

### Documentation mise à jour
- `README.md`
- `docs/skills/nokido/SKILL.md`


## Commit 2edbe0e7 — 2026-06-10 01:00
**feat(design): passe 2 - primitives .lf-* (Button/Card/Badge/StatusPill/ProvenanceBadge/Ring) + wire :7400/:8766**

### Modules Python modifiés
- `tools/nokido_hub.py`


## Commit 19aa8b4c — 2026-06-10 00:58
**feat(design): A - tokens plats sur :7400+:8766 (laforge-tokens.css), /forge/network couvert (link hub)**

### Modules Python modifiés
- `tools/nokido_hub.py`


## Commit 84ed8ac1 — 2026-06-10 00:57
**feat(design): extracteur genere laforge-tokens.css PLAT (servable 1-segment sur hub :8766)**

### Modules Python modifiés
- `tools/forge_design_extract.py`

### Documentation mise à jour
- `README.md`
- `docs/skills/nokido/SKILL.md`


## Commit 9ad69b46 — 2026-06-10 00:49
**feat(design): extracteur tokens design system -> app/web_hub/static/laforge-ds (passe 1)**

### Modules Python modifiés
- `tools/forge_design_extract.py`


## Commit 8f5d2ff8 — 2026-06-10 00:09
**feat(md): tool MCP read-only 'md' (route/lazy/index/extract/outline/read) via forge_md_router, path-confine .md+ROOT - Phase 1**

### Modules Python modifiés
- `app/forge_mcp_registry.py`

### Documentation mise à jour
- `README.md`
- `docs/skills/nokido/SKILL.md`


## Commit fb4b74c2 — 2026-06-10 00:06
**feat(launcher): retire [7] Changer mode (obsolete - Nokido centralise le mode)**

### Modules Python modifiés
- `tools/nokido_launcher.py`

### Documentation mise à jour
- `README.md`
- `docs/skills/nokido/SKILL.md`


## Commit e0f1ba00 — 2026-06-09 22:52
**fix(launcher): restart poll hub-down (anti-race vs blind sleep) + status sans fausse alarme NSSM Stopped**

### Modules Python modifiés
- `tools/nokido_launcher.py`

### Documentation mise à jour
- `README.md`
- `docs/skills/nokido/SKILL.md`


## Commit 65401eab — 2026-06-09 22:19
**feat(launcher): start/stop/restart bureau -> nokido_start/stop.ps1 full-stack**

### Modules Python modifiés
- `tools/nokido_launcher.py`


## Commit 765b0328 — 2026-06-09 21:44
**feat(acp): forge_acp_client --raw diagnostic + capture resserree (agent_message_chunk only)**

### Modules Python modifiés
- `tools/forge_acp_client.py`


## Commit 0675262b — 2026-06-09 21:14
**feat(console): sandbox=console Phase 1b - exec session user via console_exec + ConsolePolicy default-deny + arg-constraints + audit**

### Modules Python modifiés
- `app/forge_mcp_registry.py`
- `app/forge_sandbox_exec.py`


## Commit c03c8790 — 2026-06-09 19:43
**test(acp): selftest valide round-trip protocole + accumulation texte via cowork (reponse hub ask peut etre vide)**

### Modules Python modifiés
- `tools/forge_acp_client.py`

### Documentation mise à jour
- `README.md`
- `docs/skills/nokido/SKILL.md`


## Commit 970ecaf2 — 2026-06-09 19:42
**feat(acp): forge_acp_client - Nokido pilote agent ACP externe (gemini --experimental-acp)**

### Modules Python modifiés
- `tools/forge_acp_client.py`


## Commit 08161688 — 2026-06-09 17:59
**docs(gemini): finding empirique — gemini.cmd SYSTEM-only-executable (run_job/trusted/sandbox = WinError 5)**

### Documentation mise à jour
- `docs/gemini_keeper_design.md`


## Commit 04f04ce6 — 2026-06-09 17:55
**fix(gemini): keeper aligne sur l'invocation reelle du hub (BIN SYSTEM-profile + env OAuth clean-home + cwd C:/tmp)**

### Modules Python modifiés
- `tools/forge_gemini_keeper.py`


## Commit e1e977cb — 2026-06-09 17:49
**feat(gemini): PoC forge_gemini_keeper — warm Gemini CLI + endpoint :7901 (ACP/REPL)**

### Modules Python modifiés
- `tools/forge_gemini_keeper.py`

### Documentation mise à jour
- `docs/gemini_keeper_design.md`


## Commit 7129ebfe — 2026-06-09 16:55
**feat(cowork): trust-rings + firewall (durcissement securite)**

### Modules Python modifiés
- `app/forge_cowork.py`
- `app/forge_grounder.py`
- `tools/forge_acp_adapter.py`


## Commit 9bce7744 — 2026-06-09 16:51
**feat(grounder): P3 parse refuteur robuste (regex-extract) + gather AST-aware**

### Modules Python modifiés
- `app/forge_grounder.py`


## Commit 5a0c8765 — 2026-06-09 16:25
**fix(grounder): _gather_code range les lignes par nb de mots-cles matches (specifique > generique)**

### Modules Python modifiés
- `app/forge_grounder.py`


## Commit 81b05438 — 2026-06-09 16:23
**feat(grounder): P2 routage par KIND (code-fact -> read module reel) + parse refuteur robuste**

### Modules Python modifiés
- `app/forge_grounder.py`


## Commit 08edbd6e — 2026-06-09 15:59
**feat(cowork): P4a exposition ACP — un hote (Zed/terminal) pilote le collegue cowork**

### Modules Python modifiés
- `tools/forge_acp_adapter.py`


## Commit 7d05cd8a — 2026-06-09 15:54
**feat(cowork): P4 poll approval-events (pont promotion_queue hub -> reprise auto)**

### Modules Python modifiés
- `app/forge_cowork.py`


## Commit 5babe541 — 2026-06-09 15:40
**fix(cowork): guard daemon = idle-wait gracieux (pas exit) — stoppe la restart-loop/quarantine**

### Modules Python modifiés
- `app/forge_cowork.py`


## Commit b0279036 — 2026-06-09 15:36
**fix(cowork): selftest P2 task irreversible type=doc (pas code) — le stub markdown echouait l'AST P3**

### Modules Python modifiés
- `app/forge_cowork.py`


## Commit 9a8aef83 — 2026-06-09 15:35
**feat(cowork): P3 initiative bornee grounder-vettee + checkpoint code AST + rollback**

### Modules Python modifiés
- `app/forge_cowork.py`


## Commit 3b3f0cd5 — 2026-06-09 14:41
**fix(grounder): print --claim en ensure_ascii=True (console cp1252 vs reason LLM non-ASCII)**

### Modules Python modifiés
- `app/forge_grounder.py`


## Commit d0e20b5a — 2026-06-09 14:40
**fix(grounder): auth Bearer FORGE_MCP_TOKEN (vault) sur /mcp ask (401 sinon)**

### Modules Python modifiés
- `app/forge_grounder.py`


## Commit 95408726 — 2026-06-09 14:37
**feat(grounder): PoC P1 verbe ground(claim) — grounding multi-source + verif adversariale multi-LLM**

### Modules Python modifiés
- `app/forge_grounder.py`


## Commit 9903c878 — 2026-06-09 14:08
**feat(cowork): P2 gate irreversible + scheduler park/resume**

### Modules Python modifiés
- `app/forge_cowork.py`


## Commit 0b0e2d7d — 2026-06-09 13:57
**feat(cowork): PoC P1 collegue IA souverain (forge_cowork) + design 3-tours**

### Modules Python modifiés
- `app/forge_cowork.py`

### Documentation mise à jour
- `docs/cowork_internalization_design.md`


## Commit c175093d — 2026-06-09 13:26
**feat(cognition): harness A/B retrain world-model @384 vs @1024 (gate cutover)**

### Modules Python modifiés
- `tools/forge_cognition_retrain_1024.py`


## Commit a5f9d564 — 2026-06-09 13:14
**docs(wiki): cognition dim-unification phase 4 + collecteur-service**

### Documentation mise à jour
- `docs/wiki/12-AMI-Cognitive-Stack.md`


## Commit d3c1c91e — 2026-06-09 13:10
**fix(collector): guard gracieux idle-wait au lieu d'exit**

### Modules Python modifiés
- `tools/forge_trace_collector_rich.py`


## Commit 3d939929 — 2026-06-09 13:07
**feat(cognition): collecteur traces_rich = service supervise (centralise, pas schtask)**

### Modules Python modifiés
- `tools/forge_trace_collector_rich.py`


## Commit 1424af0b — 2026-06-09 12:53
**feat(cognition c-phase4): dim 1024d-safe — dedup COGNITION_DIM + goap embedder checkpoint-tied**

### Modules Python modifiés
- `app/forge_goap_intuition.py`
- `app/forge_world_model.py`
- `tools/forge_cognition_dim_selftest.py`


## Commit ae6d9863 — 2026-06-09 02:02
**test(reconcile): step5 suite validation registres (imports/router-no-phantom/admin-merge/canonical/agent_proxy keyfix/remediation/pattern)**

### Modules Python modifiés
- `tools/forge_reconcile_test.py`


## Commit 14583a12 — 2026-06-09 01:57
**feat(reconcile): step4 excision phantom slots (ollama_mimo_v2/openrouter_glm5 hors USE_CASE_CHAINS) + step3 admin PROVIDER_VAULT_KEY <- canonical (setdefault non-cassant)**

### Modules Python modifiés
- `app/forge_llm_router.py`
- `app/forge_provider_admin.py`


## Commit fcd2340a — 2026-06-09 01:52
**fix(remediation): sys.path + tools/ (forge_tier_policy/orphan_reaper)**

### Modules Python modifiés
- `app/forge_remediation.py`


## Commit 70c616ec — 2026-06-09 01:51
**fix(remediation): db_contention probe non-bloquant + stale leger (evite hang lock/AST)**

### Modules Python modifiés
- `app/forge_remediation.py`


## Commit f081dae6 — 2026-06-09 01:47
**feat(remediation): forge_remediation organe auto-reparation 8 dettes physiques + pat_remediation (hook autonomique 30min, signal-only via critical_events)**

### Modules Python modifiés
- `app/forge_autonomous_loops.py`
- `app/forge_remediation.py`


## Commit 9c3764d4 — 2026-06-09 01:30
**feat(providers): forge_provider_canonical source de verite (Option B multiplan) step1 — derive _PROVIDERS+specs, 0 malformed, vault_key_map/audit**

### Modules Python modifiés
- `app/forge_provider_canonical.py`


## Commit fed62285 — 2026-06-09 01:28
**fix(providers): agent_proxy sambanova key malforme (cloud.sambanova.ai_API_KEY) + nvidia align -> SAMBANOVA_API_KEY/NVIDIA_API_KEY (canon)**

### Modules Python modifiés
- `app/forge_agent_proxy.py`


## Commit 58e4f563 — 2026-06-09 01:09
**feat(audit): mode --admin (GET /api/providers, statut agent_proxy env hub reel sans ping)**

### Modules Python modifiés
- `tools/forge_provider_auth_audit.py`


## Commit 82f39e9c — 2026-06-09 00:54
**fix(audit): skip ping des CLI OAuth (hang interactif) -> ping API seulement**

### Modules Python modifiés
- `tools/forge_provider_auth_audit.py`


## Commit 34a9c7bb — 2026-06-09 00:51
**feat(security): forge_provider_auth_audit (classify auth/oauth/credit/rate/env par provider)**

### Modules Python modifiés
- `tools/forge_provider_auth_audit.py`


## Commit f68c35ae — 2026-06-09 00:29
**docs(axe9): enforce 24/7 utilisable (hook allowliste git appelant) + entropy-FP docs**

### Documentation mise à jour
- `docs/ROADMAP.md`


## Commit f1976c9b — 2026-06-09 00:28
**feat(axe9): hook pre-push allowliste le git appelant (ancetre) au verrou WinDivert -> enforce 24/7 general tous pushers**

### Modules Python modifiés
- `app/forge_git_egress.py`


## Commit 29f4c9bc — 2026-06-09 00:25
**feat(axe9): route session_anchor push via gate (enforce-compat) + skip entropy sur docs (FP)**

### Modules Python modifiés
- `app/forge_git_egress.py`
- `tools/forge_session_anchor.py`


## Commit 7218f9f8 — 2026-06-09 00:21
**fix(axe3): forge_embed_auto_trigger :5557 mort -> forge_embed_router :8099 (auto-embed repare)**

### Modules Python modifiés
- `tools/forge_embed_auto_trigger.py`

### Documentation mise à jour
- `docs/ROADMAP.md`


## Commit 77c26d3f — 2026-06-08 23:46
**docs(axe1): runAs de-privilege deja APPLIQUE (note roadmap+services.toml etaient stale)**

### Documentation mise à jour
- `docs/ROADMAP.md`


## Commit e5b566af — 2026-06-08 23:37
**feat(qualify): teste TOUS les modeles de chaque provider (pas seulement models[0])**

### Modules Python modifiés
- `tools/forge_endpoint_qualify.py`


## Commit 316fc01b — 2026-06-08 23:33
**docs(roadmap): AXE 9 souverainete egress git (livre) + multiplan + historique 2026-06-08**

### Documentation mise à jour
- `docs/ROADMAP.md`


## Commit e4f96669 — 2026-06-08 23:28
**feat(security): forge_secret_audit --add-template (rubrique free-tier Nokido.env, commentee)**

### Modules Python modifiés
- `tools/forge_secret_audit.py`


## Commit 276e5d00 — 2026-06-08 23:21
**fix(security): forge_secret_audit sortie ASCII (cp1252 console)**

### Modules Python modifiés
- `tools/forge_secret_audit.py`


## Commit ed833a96 — 2026-06-08 23:19
**feat(security): forge_secret_audit (audit vault placeholders, valeurs masquees) + NokidoGitProxy service**

### Modules Python modifiés
- `tools/forge_secret_audit.py`


## Commit 67dda746 — 2026-06-08 23:16
**fix(router): sambanova env_key SAMBANOVA_API_KEY (etait nom casse)**

### Modules Python modifiés
- `app/forge_llm_router.py`


## Commit ffbc695f — 2026-06-08 23:10
**feat(egress): forge_git_proxy — proxy CONNECT host-allowlist + audit (toutes requetes git)**

### Modules Python modifiés
- `tools/forge_git_proxy.py`


## Commit 620d76b9 — 2026-06-08 23:00
**fix(router): max_retries=0 (SDK openai-compat) en complement de num_retries**

### Modules Python modifiés
- `app/forge_llm_router.py`
- `tools/forge_endpoint_qualify.py`


## Commit b5d4947f — 2026-06-08 22:40
**fix(router): litellm fail-fast (num_retries=0) + cost-map local (anti-blocage)**

### Modules Python modifiés
- `app/forge_llm_router.py`
- `tools/forge_endpoint_qualify.py`


## Commit 2db8703d — 2026-06-08 22:29
**feat(egress): gate-as-executor + WinDivert v2 lock scaffold**

### Modules Python modifiés
- `app/forge_git_egress.py`
- `tools/forge_git_egress_lock.py`


## Commit f83c052c — 2026-06-08 22:28
**feat(egress): gate-as-executor + WinDivert v2 lock scaffold**

### Modules Python modifiés
- `app/forge_git_egress.py`
- `tools/forge_git_egress_lock.py`


## Commit 10a082dc — 2026-06-08 22:09
**fix(router): llamacpp_local env_key=FORGE_LLAMA_KEY (llama-server exige auth)**

### Modules Python modifiés
- `app/forge_llm_router.py`


## Commit fd7165fa — 2026-06-08 22:03
**feat: sovereign git-egress gate + parity gate + scheduler/ghidra**

### Modules Python modifiés
- `app/forge_autonomous_loops.py`
- `app/forge_chain_executor.py`
- `app/forge_git_egress.py`
- `app/forge_parity_gate.py`
- `app/forge_watch_agent.py`
- `tools/forge_ghidra_query.py`
- `tools/forge_gitingest_sdk_ingest.py`


## Commit 87ca3273 — 2026-06-08 21:21
**feat(routing): Contract-Net election deterministe de worker (switchboard backlog)**

### Modules Python modifiés
- `app/forge_contract_net.py`
- `app/tests/test_contract_net.py`


## Commit 486c088d — 2026-06-08 21:19
**feat(routing): call_cascade use_case=auto -> semantic_route lazy (switchboard)**

### Modules Python modifiés
- `app/forge_llm_router.py`
- `app/tests/test_routing_switchboard.py`


## Commit 4b5fc31e — 2026-06-08 21:18
**feat(routing): Q5 centroides auto-appris depuis dialogue_win (switchboard x AXE 8)**

### Modules Python modifiés
- `app/forge_semantic_route.py`
- `app/tests/test_routing_switchboard.py`


## Commit a9364125 — 2026-06-08 21:12
**fix(router): llamacpp_local routing OpenAI-compat + escalade moins eager**

### Modules Python modifiés
- `app/forge_llm_router.py`


## Commit 777226bf — 2026-06-08 20:52
**fix(router): USE_CASE_CHAINS general local-first (souverainete + max_attempts)**

### Modules Python modifiés
- `app/forge_llm_router.py`


## Commit 4a0f3224 — 2026-06-08 20:38
**test(routing): PoC noeud LLM distant -> call_cascade(vision) route URL + format OpenAI**

### Modules Python modifiés
- `app/tests/test_routing_switchboard.py`


## Commit 69c8f4b0 — 2026-06-08 20:30
**docs(routing): PR-D abandonne + dossier debat auto use_case (multi-LLM)**

### Documentation mise à jour
- `docs/specs/routing_switchboard_design.md`


## Commit 8bd4a86b — 2026-06-08 20:23
**feat(routing): switchboard PR-C facade litellm.Router (model_list depuis specs)**

### Modules Python modifiés
- `app/forge_litellm_router.py`
- `app/tests/test_routing_switchboard.py`


## Commit 44a8dcad — 2026-06-08 20:21
**feat(routing): switchboard PR-A semantic route-table bge-m3 + PR-B facade capacites**

### Modules Python modifiés
- `app/forge_capability_registry.py`
- `app/forge_semantic_route.py`
- `app/tests/test_routing_switchboard.py`


## Commit 914e7db7 — 2026-06-08 20:19
**docs(routing): design switchboard - route-table bge-m3 + dedup LiteLLM Router**

### Documentation mise à jour
- `docs/specs/routing_switchboard_design.md`


## Commit 50caf000 — 2026-06-08 20:09
**feat(integrity): AXE 8 PR-6 - CapabilityToken racine TPM additive (HMAC->TPM)**

### Modules Python modifiés
- `app/forge_integrity.py`
- `app/tests/test_integrity_tpm.py`

### Documentation mise à jour
- `docs/specs/axe8_persona_unifiee_plan.md`


## Commit d18de8c1 — 2026-06-08 20:05
**docs(roadmap): AXE 8 persona unifiee LIVRE v1 (8cf1720b->b9f80206, 35 tests)**

### Documentation mise à jour
- `docs/ROADMAP.md`


## Commit b9f80206 — 2026-06-08 20:05
**feat(persona): AXE 8 PR-6 TPM + hook Gemini + catalogue endocrine**

### Modules Python modifiés
- `app/forge_endocrine.py`
- `app/forge_persona_engine.py`
- `app/forge_persona_tpm.py`
- `app/tests/test_persona_tpm.py`
- `tools/forge_dialogue_score_session.py`

### Documentation mise à jour
- `docs/specs/axe8_persona_unifiee_plan.md`


## Commit 79fc3e13 — 2026-06-08 19:59
**feat(persona): AXE 8 activation - hook Stop scoring live + persona dans forge_agents**

### Modules Python modifiés
- `app/forge_agents.py`
- `app/forge_dialogue_outcome.py`
- `app/tests/test_dialogue_outcome.py`
- `tools/forge_dialogue_score_session.py`

### Documentation mise à jour
- `docs/specs/axe8_persona_unifiee_plan.md`


## Commit cdf94385 — 2026-06-08 19:55
**feat(persona): AXE 8 axe ecrit - scoring live des echanges + exemplars few-shot**

### Modules Python modifiés
- `app/forge_dialogue_outcome.py`
- `app/forge_persona_engine.py`
- `app/tests/test_dialogue_outcome.py`
- `app/tests/test_persona_engine_nokido.py`

### Documentation mise à jour
- `docs/specs/axe8_persona_unifiee_plan.md`


## Commit 2d5cf7ad — 2026-06-08 19:49
**feat(persona): AXE 8 PR-3+PR-4 - injection persona unifiee cloud + local (inbypassable)**

### Modules Python modifiés
- `app/forge_agent_proxy.py`
- `app/forge_llm_router.py`
- `app/tests/test_proxy_persona.py`
- `app/tests/test_router_persona_inject.py`


## Commit 22e36e71 — 2026-06-08 19:35
**feat(persona): AXE 8 PR-2 - boucle recompense succes/echec -> conditionnement voix**

### Modules Python modifiés
- `app/forge_dialogue_outcome.py`
- `app/forge_persona_engine.py`
- `app/tests/test_dialogue_outcome.py`
- `app/tests/test_persona_engine_nokido.py`

### Documentation mise à jour
- `docs/specs/axe8_persona_unifiee_plan.md`


## Commit 8cf1720b — 2026-06-08 19:32
**feat(persona): AXE 8 PR-1 - persona canonique nokido + gestion tokens intelligente**

### Modules Python modifiés
- `app/forge_persona_engine.py`
- `app/tests/test_persona_engine_nokido.py`

### Documentation mise à jour
- `docs/ROADMAP.md`
- `docs/specs/axe8_persona_unifiee_plan.md`


## Commit 050236ad — 2026-06-06 05:52
**docs(wiki): Glossary brain_worker def (:5557 disabled -> :8099 live) + RAG count ~531k (Glossary+FAQ)**

### Documentation mise à jour
- `docs/wiki/15-Glossary.md`
- `docs/wiki/16-FAQ.md`


## Commit 9113126b — 2026-06-06 05:51
**docs(wiki FR): 03-Architecture.fr + 14-Troubleshooting.fr - embedder :5557->:8099 + counts**

### Documentation mise à jour
- `docs/wiki/03-Architecture.fr.md`
- `docs/wiki/14-Troubleshooting.fr.md`


## Commit 2e33c95d — 2026-06-06 05:49
**docs(wiki+README): embedder :5557->:8099 (ONNX disabled) + RAG ~531k + cognition 384/1024 unification section + module count 985**

### Documentation mise à jour
- `README.md`
- `docs/wiki/03-Architecture.md`
- `docs/wiki/12-AMI-Cognitive-Stack.md`
- `docs/wiki/14-Troubleshooting.md`


## Commit 3dd123b5 — 2026-06-06 05:36
**docs(cartouches): CLAUDE.md §8/§13 - :5557 brain_worker DISABLED (ONNX OOM), :8099 NokidoLlamaEmbed = embedder live via embed_router**

### Documentation mise à jour
- `CLAUDE.md`


## Commit 46d349ff — 2026-06-06 05:20
**feat(rag): embed_batch_fast local-first via :8099 batch (Essai 0) - bulk RAG embed redevient local, plus cloud-first**

### Modules Python modifiés
- `app/forge_embed_router.py`
- `tools/forge_embed_router_8099_test.py`


## Commit 786842ae — 2026-06-06 05:17
**feat(rag): embed_router cable :8099 NokidoLlamaEmbed (BGE-M3 GGUF local) en 1er provider - RAG embed redevient local (:5557 ONNX mort)**

### Modules Python modifiés
- `app/forge_embed_router.py`
- `tools/forge_embed_router_8099_test.py`


## Commit 71f7bfbc — 2026-06-06 05:13
**fix(collector): reencode via NokidoLlamaEmbed :8099 (BGE-M3 GGUF vivant) au lieu de :5557 mort + retry echecs**

### Modules Python modifiés
- `tools/forge_trace_collector_rich.py`


## Commit c31f220a — 2026-06-06 05:06
**fix(collector): text-first (robuste, zero dep lourde) + reencode batch brain_worker ZMQ (evite litellm/cloud/packaging)**

### Modules Python modifiés
- `tools/forge_trace_collector_rich.py`


## Commit e4af1d7d — 2026-06-06 05:03
**feat(cognition): convert anciennes traces 384d->1024d via pont (bootstrap retrain, ~2939 convertibles)**

### Modules Python modifiés
- `tools/forge_trace_convert_384.py`


## Commit 4f620560 — 2026-06-06 04:37
**fix(collector): selftest stub state (evite appel hub re-entrant en trusted_script)**

### Modules Python modifiés
- `tools/forge_trace_collector_rich.py`


## Commit 103b0f2c — 2026-06-06 04:34
**feat(cognition c-phase3): collecteur traces riches 1024d parallele (table traces_rich, etat enrichi + texte, zero impact 384d)**

### Modules Python modifiés
- `tools/forge_trace_collector_rich.py`


## Commit ddc11eba — 2026-06-06 04:27
**feat(cognition c-phase1b): get_current_state_text_rich (tasks+mood+hormones) cable au path 1024d, world_model 384d intact**

### Modules Python modifiés
- `app/forge_state_encoder.py`


## Commit 384dac9d — 2026-06-06 04:13
**feat(cognition c-phase2b): centralise dims value/policy/cost nets via COGNITION_DIM (defaut 384 non-breaking)**

### Modules Python modifiés
- `app/forge_cost_net.py`
- `app/forge_policy_net.py`
- `app/forge_value_net.py`
- `tools/forge_cognition_dim_selftest.py`


## Commit 39390cb1 — 2026-06-06 04:02
**feat(cognition c-phase2a): centralise dims world_model via COGNITION_DIM (defaut 384 non-breaking)**

### Modules Python modifiés
- `app/forge_world_model.py`
- `tools/forge_cognition_dim_selftest.py`


## Commit cc256cde — 2026-06-06 03:47
**feat(cognition c-phase1): encode_state path 1024d via embed_router (dim opt-in, defaut 384 non-breaking)**

### Modules Python modifiés
- `app/forge_state_encoder.py`


## Commit 547a37d4 — 2026-06-06 03:09
**fix(cognition): pont embed fitte sur l'encodeur reel (probe vitesse + cap budget + backend reporte)**

### Modules Python modifiés
- `tools/forge_embed_bridge.py`


## Commit 51d09009 — 2026-06-06 03:07
**feat(cognition): pont embed 384<->1024 (ridge MiniLM<->BGE-M3 sur rag_chunks, qualite mesuree)**

### Modules Python modifiés
- `tools/forge_embed_bridge.py`


## Commit 611e4813 — 2026-06-06 01:45
**harden(anatomy): denylist AST sur outils forges (exec/destructif/reseau) au forge + a l'exec**

### Modules Python modifiés
- `app/forge_tool_forger.py`


## Commit a75989c0 — 2026-06-06 01:28
**feat(anatomy): bridge push list_changed dynamique (B) - watcher tail bus + stdout lock**

### Modules Python modifiés
- `tools/mcp_bridge_selftest.py`
- `tools/mcp_stdio_bridge.py`


## Commit 06a9aee1 — 2026-06-06 01:19
**feat(anatomy): outils forges exposes en MCP (A1 generiques + A2 dyn_<nom>) ring2 + SecretGuard**

### Modules Python modifiés
- `app/forge_mcp_registry.py`
- `tools/forge_mcp_dynamic_selftest.py`


## Commit b73a25b9 — 2026-06-06 00:55
**feat(anatomy): forge emet capability.forged sur le bus (signal capability-changed observable)**

### Modules Python modifiés
- `app/forge_tool_forger.py`


## Commit 6e9bc06e — 2026-06-06 00:53
**feat(anatomy): swarm voit les outils forges (fix snapshot Agent.tools, fresh par round)**

### Modules Python modifiés
- `app/forge_handoff.py`


## Commit 1dc6f422 — 2026-06-06 00:43
**fix(anatomy): import importlib.util explicite - _load_tool cassait silencieusement (outils forges injouables)**

### Modules Python modifiés
- `app/forge_tool_forger.py`


## Commit 5e3f40c8 — 2026-06-06 00:41
**test(anatomy): forge_tool_forger --selftest e2e bridge (SecretGuard+exec+dispatch) + fix label**

### Modules Python modifiés
- `app/forge_tool_forger.py`


## Commit e21cabf8 — 2026-06-06 00:40
**feat(anatomy): bridge generique outils forges -> GOAP (forge_call_dynamic ring2)**

### Modules Python modifiés
- `app/forge_dispatchers.py`
- `app/forge_goap.py`
- `app/forge_tool_forger.py`


## Commit 48aa0ff0 — 2026-06-05 23:37
**feat(anatomy): surgical_patcher ecriture proprioceptive (validate-RAM atomique, plus de fenetre necrotique)**

### Modules Python modifiés
- `tools/forge_surgical_patcher.py`


## Commit 144ded32 — 2026-06-05 23:21
**feat(anatomy): proprioceptive_write - gate L0 valider-en-RAM + ecriture atomique (verrou rollback)**

### Modules Python modifiés
- `tools/forge_module_cards.py`


## Commit 7e261d59 — 2026-06-05 23:14
**feat(anatomy): semantique NECROSE - module casse preserve sa structure saine + signal nociceptif**

### Modules Python modifiés
- `tools/forge_module_cards.py`


## Commit 1551bd7b — 2026-06-05 22:46
**feat(anatomy): summarize en BATCH (N modules/appel) - bat le cap 120s**

### Modules Python modifiés
- `tools/forge_card_summarize.py`


## Commit a609c68e — 2026-06-05 22:42
**feat(anatomy): gemini_cli OAuth en tete du fallback summarize (quota frais)**

### Modules Python modifiés
- `tools/forge_card_summarize.py`


## Commit 8581e7fd — 2026-06-05 22:32
**perf(anatomy): summarize local ollama qwen2.5-coder:1.5b (rapide CPU)**

### Modules Python modifiés
- `tools/forge_card_summarize.py`


## Commit 8f8c1123 — 2026-06-05 22:29
**feat(anatomy): summarize local via ollama qwen2.5-coder:7b (illimite, sans firewall)**

### Modules Python modifiés
- `tools/forge_card_summarize.py`


## Commit 67640739 — 2026-06-05 22:28
**chore(anatomy): probe liste les modeles ollama**

### Modules Python modifiés
- `tools/forge_card_summarize.py`


## Commit 119902aa — 2026-06-05 22:26
**chore(anatomy): --probe diagnostic llama.cpp pour summarize**

### Modules Python modifiés
- `tools/forge_card_summarize.py`


## Commit 99024133 — 2026-06-05 22:24
**fix(anatomy): rejette+purge resumes pollues (firewall/quota/erreur), regen local**

### Modules Python modifiés
- `tools/forge_card_summarize.py`


## Commit 0faf49a0 — 2026-06-05 22:21
**feat(anatomy): llama.cpp local en tete du fallback summarize (sans quota)**

### Modules Python modifiés
- `tools/forge_card_summarize.py`


## Commit 02b9ac57 — 2026-06-05 22:02
**feat(anatomy): 168 definitions grounded (code reel) + revert fallback cloud-first**

### Modules Python modifiés
- `tools/forge_card_summarize.py`


## Commit c0ba27da — 2026-06-05 21:59
**fix(anatomy): ollama local en tete du fallback summarize (sans quota)**

### Modules Python modifiés
- `tools/forge_card_summarize.py`


## Commit 5eda1595 — 2026-06-05 21:45
**fix(anatomy): forge_card_summarize fallback multi-provider (cerebras/gpt4o/groq)**

### Modules Python modifiés
- `tools/forge_card_summarize.py`


## Commit 56089738 — 2026-06-05 21:38
**perf(anatomy): forge_card_summarize sauvegarde incrementale (timeout-safe)**

### Modules Python modifiés
- `tools/forge_card_summarize.py`


## Commit bcb518f1 — 2026-06-05 21:36
**fix(anatomy): forge_card_summarize via groq (forge_agent_proxy) au lieu d'ollama**

### Modules Python modifiés
- `tools/forge_card_summarize.py`

### Documentation mise à jour
- `README.md`
- `docs/skills/nokido/SKILL.md`


## Commit ad98e18c — 2026-06-05 21:35
**feat(anatomy): forge_card_summarize - definitions grounded (LLM-sur-code) modules sans docstring**

### Modules Python modifiés
- `tools/forge_card_summarize.py`
- `tools/forge_module_cards.py`


## Commit 54a4d614 — 2026-06-05 21:05
**feat(anatomy): cartes RAG-ingest + fraicheur post-commit diff-only**

### Modules Python modifiés
- `tools/forge_module_cards.py`
- `tools/forge_post_commit.py`


## Commit 4f11c2dc — 2026-06-05 20:49
**feat(anatomy): forge_module_cards - proprioception comportementale statique AST**

### Modules Python modifiés
- `tools/forge_module_cards.py`


## Commit 856e063b — 2026-06-05 19:00
**docs(anatomy): carte organes 714 forge 0-trou + census auto-completant**

### Modules Python modifiés
- `tools/forge_module_census.py`

### Documentation mise à jour
- `CLAUDE.md`


## Commit 3e325c6c — 2026-06-05 15:49
**fix(rag): reindex_deport phase B = NULL-only embed (skip 26k re-embed + stale CKPT no-op)**

### Modules Python modifiés
- `tools/forge_reindex_deport.py`


## Commit 0965ce08 — 2026-06-05 15:05
**chore(rag): reindex_deport --whereis (locate HF token source + length)**

### Modules Python modifiés
- `tools/forge_reindex_deport.py`


## Commit 081a2e77 — 2026-06-05 15:00
**chore(rag): reindex_deport HF token format sanity (no value leak)**

### Modules Python modifiés
- `tools/forge_reindex_deport.py`


## Commit 148c9652 — 2026-06-05 14:59
**fix(rag): reindex_deport override fre cloud keys from vault env (not plaintext Nokido.env)**

### Modules Python modifiés
- `tools/forge_reindex_deport.py`


## Commit e16fd4c8 — 2026-06-05 14:53
**fix(env_crypt): machine-scope DPAPI vault (cross-account decrypt, fix mauvaise machine/compte)**

### Modules Python modifiés
- `app/forge_env_crypt.py`


## Commit 78d5039c — 2026-06-05 14:47
**feat(rag): reindex_deport - inject vault secrets before provider gating**

### Modules Python modifiés
- `tools/forge_reindex_deport.py`


## Commit 93e68f12 — 2026-06-05 14:46
**feat(rag): forge_reindex_deport - reindex code + embed cloud bge-m3 (no local 780M)**

### Modules Python modifiés
- `tools/forge_reindex_deport.py`


## Commit dd464237 — 2026-06-05 14:10
**fix(hub): non-blocking logging via QueueHandler (stderr NSSM pipe froze event loop)**

### Modules Python modifiés
- `tools/nokido_hub.py`


## Commit ba559871 — 2026-06-05 13:09
**fix(rag): vec_coverage anti-artifact probes + ascii-safe stdout**

### Modules Python modifiés
- `tools/forge_vec_coverage.py`


## Commit 318a508c — 2026-06-05 13:07
**feat(rag): forge_vec_coverage - point vectorisation corpus code + backlog + census gap**

### Modules Python modifiés
- `tools/forge_vec_coverage.py`


## Commit 0d5d271f — 2026-06-05 13:02
**fix(tinygrad): redirect CACHEDB to C:/tmp (LaForgeTrusted home denied)**

### Modules Python modifiés
- `tools/forge_tinygrad_poc.py`


## Commit 163ea21c — 2026-06-05 12:59
**fix(tinygrad): pip --target C:/tmp/tinygrad_libs (LaForgeTrusted user-site denied)**

### Modules Python modifiés
- `tools/forge_tinygrad_poc.py`


## Commit 16555bdc — 2026-06-05 12:54
**feat(tinygrad): forge_tinygrad_poc - probe OpenCL 780M + matmul GPU=1**

### Modules Python modifiés
- `tools/forge_tinygrad_poc.py`


## Commit 67eb6aca — 2026-06-05 02:50
**fix(swe multivec): SCOPE aux fichiers candidats (pas tout le repo = milliers de fonctions = hang astropy) + resume via LLM PUISSANT make_hub_summarize gemini_cli (PAS ollama local - applique la consig**

### Modules Python modifiés
- `tools/forge_swe_multivec.py`
- `tools/forge_swebench_runner.py`


## Commit f57280c4 — 2026-06-05 02:46
**tools: forge_swe_provider_test - diag call_llm par provider en contexte trusted**

### Modules Python modifiés
- `tools/forge_swe_provider_test.py`


## Commit 52f59c20 — 2026-06-05 02:44
**tools: forge_swe_smoke_restart - kill smoke hung (multivec) + relance sans multivec**

### Modules Python modifiés
- `tools/forge_swe_smoke_restart.py`


## Commit 6ed4ea44 — 2026-06-05 02:19
**tools: forge_docker_boot_audit - reveille daemon + audite reclaimable**

### Modules Python modifiés
- `tools/forge_docker_boot_audit.py`


## Commit 7b15a754 — 2026-06-05 02:18
**tools: forge_docker_audit - supprime Docker_Backup perime + audit docker reclaimable**

### Modules Python modifiés
- `tools/forge_docker_audit.py`


## Commit be02812d — 2026-06-05 02:01
**fix(swe-smoke): args corrects --max 3 --clone (best-of-N exige clone)**

### Modules Python modifiés
- `tools/forge_swe_smoke_launch.py`


## Commit 01e832bb — 2026-06-05 02:00
**tools: forge_swe_smoke_launch - lance smoke SWE n=3 detache (best-of-N CLI forts + multivec) en contexte trusted (hub+internet)**

### Modules Python modifiés
- `tools/forge_swe_smoke_launch.py`


## Commit a6c74a40 — 2026-06-05 01:53
**fix(cli-clean gemini): reconstruit settings.json MINIMAL (selectedAuthType seul, zero mcpServers) - l'exclusion totale cassait l'auth ('set an Auth method')**

### Modules Python modifiés
- `tools/forge_cli_clean_setup.py`


## Commit b8cbd684 — 2026-06-05 01:48
**fix(claude oauth): claude_cli strip ANTHROPIC/CLAUDE_API_KEY de l'env -> force route OAuth subscription (.credentials.json), jamais l'API payante (claude n'a QUE l'OAuth, comme gemini). Coherent regle**

### Modules Python modifiés
- `app/forge_agent_proxy.py`


## Commit 2ba3ffa9 — 2026-06-05 01:44
**fix(raw-mode): VRAIE cause des ACK d'agent = la persona injectee par le HUB (ask -> _build_system_prompt 'Tu es l'agent X dans l'ecosysteme Nokido'), PAS la config CLI. ask() gagne param raw -> skip **

### Modules Python modifiés
- `app/forge_agent_proxy.py`
- `app/forge_mcp_registry.py`


## Commit 934290cb — 2026-06-05 01:39
**fix(cli-clean): exclut history.jsonl (1.35MB sessions Nokido = contexte injecte) + caches**

### Modules Python modifiés
- `tools/forge_cli_clean_setup.py`


## Commit d6c9e89f — 2026-06-05 01:28
**fix(cli-clean): filtre resserre - vire caveman/skills/commands/daemon/inbox/sessions/settings(hooks+MCP), garde auth+onboarding-state seulement**

### Modules Python modifiés
- `tools/forge_cli_clean_setup.py`


## Commit dbd02389 — 2026-06-05 01:22
**feat(A CLI-isolation): claude_cli/gemini_cli utilisent une config PROPRE conditionnelle (CLAUDE_CONFIG_DIR=C:/tmp/claude_clean ; gemini HOME=C:/tmp/gemini_home) si presente -> Opus4.8/Gemini3.1 repond**

### Modules Python modifiés
- `app/forge_agent_proxy.py`


## Commit 2ee4a216 — 2026-06-05 01:20
**tools: forge_cli_clean_setup - configs CLI propres (auth seule) pour claude_cli/gemini_cli en LLM brut**

### Modules Python modifiés
- `tools/forge_cli_clean_setup.py`


## Commit abea1687 — 2026-06-05 00:59
**tools: forge_index_tools - one-shot index tools/ dans RAG (diag + comble trou 241 modules)**

### Modules Python modifiés
- `tools/forge_index_tools.py`


## Commit 247e5461 — 2026-06-05 00:50
**docs+fix(vectorisation): regen CLAUDE.md section 10 (census 975 modules/291k LOC vs ~50 documentes = cause de la regression ressentie) + forge_rag_warmup indexe enfin tools/ via index_app_dir(target_d**

### Modules Python modifiés
- `app/forge_rag_warmup.py`

### Documentation mise à jour
- `CLAUDE.md`


## Commit 8948d964 — 2026-06-05 00:31
**fix(A copilot_cli): _BIN resout au 1er chemin npm existant (SYSTEM puis user) au lieu de figer sur user. Le hub=SYSTEM -> binaires npm globaux dans le profil SYSTEM (comme claude/gemini). is_avail**

### Modules Python modifiés
- `app/forge_agent_proxy.py`


## Commit 60a421d1 — 2026-06-05 00:16
**fix(providers): audit ping revele providers casses. gemini_cli += GEMINI_CLI_TRUST_WORKSPACE=true (refusait dossier non-trusted -> renvoyait l'erreur comme reponse). claude_cli += cwd=C:/tmp (chargeai**

### Modules Python modifiés
- `app/forge_agent_proxy.py`
- `tools/forge_swebench_runner.py`


## Commit 9dc33f6b — 2026-06-05 00:10
**feat(swe): best-of-N defaut = les 3 modeles COMPTE les plus forts (claude_cli=Opus 4.8, gemini_cli=Gemini 3.1, copilot_cli=Opus4.5/auto) - tier-haut subscription >> free-tier bas+quota (panel live: ge**

### Modules Python modifiés
- `app/forge_agent_proxy.py`
- `tools/forge_swebench_runner.py`


## Commit 4eb7650a — 2026-06-05 00:05
**feat(swe-d wiring): multi-vec COMPLET + cable runner. Ajoute le VECTEUR DEPENDANCES (_deps_used = ce que la fn appelle/utilise -> point 2 multi-vec qui manquait) + bge-m3 REEL (build_index_bge, ZMQ ba**

### Modules Python modifiés
- `tools/forge_swe_multivec.py`
- `tools/forge_swebench_runner.py`


## Commit 7a815a53 — 2026-06-04 23:59
**feat(swe-d): forge_swe_multivec - retrieval multi-vecteur Parent-Child. Children indexes (nom + signature + docstring + resume LLM optionnel) -> RETOURNE le PARENT (code brut exact). Contourne la myop**

### Modules Python modifiés
- `tools/forge_swe_multivec.py`


## Commit ff00904b — 2026-06-04 23:57
**fix(firewall #c): BASE64_SUSPECT regex exige >=24 chars + 1 majuscule + 1 chiffre (vraie donnee encodee a entropie) au lieu de {12,}=? qui flaguait les longs mots FR (amelioration, investissement) et **

### Modules Python modifiés
- `app/forge_semantic_firewall.py`


## Commit 44fe267b — 2026-06-04 23:56
**feat(swe): best-of-N defaut providers = claude_cli,gemini_cli,cerebras - Claude+Gemini subscription (forts, via hub ask, PAS l'API Anthropic directe = respecte la regle) comme candidats patch-gen ; ce**

### Modules Python modifiés
- `tools/forge_swebench_runner.py`


## Commit 2446bbd8 — 2026-06-04 23:54
**feat(swe-b): _callgraph_context - injecte les CALLERS des fonctions cibles (def du fichier prioritaire ∩ keywords issue) du repo clone dans le contexte patch-gen (_read_files_context). Levier panel+mo**

### Modules Python modifiés
- `tools/forge_swebench_runner.py`


## Commit 2a98bac0 — 2026-06-04 23:51
**feat(swe-a): generate_patch_best_of_n - best-of-N + SELECTION PAR TEST (FAIL_TO_PASS via _apply_and_test) sur le chemin direct (gate SWEBENCH_BESTOFN). Levier #1 SWE-bench (panel multi-LLM groq/gpt4o/**

### Modules Python modifiés
- `tools/forge_swebench_runner.py`


## Commit cbbbfe91 — 2026-06-04 23:23
**feat(B durable): orchestrate detach+durable=True -> _run_loop_durable (forge_durable_workflow event-sourced) : chaque etape = activity memoizee dans WorkflowStore -> replay-on-restart (zero double eff**

### Modules Python modifiés
- `app/forge_mcp_registry.py`
- `tools/forge_orchestrate_loop.py`


## Commit e2c6f474 — 2026-06-04 23:13
**feat(strategist-cloud): planner GOAP des goals OUVERTS route vers le router cascade (use_case=strategy -> cloud free-tier FORT groq-70b/sambanova) AVEC SemanticFirewall (Golden Rule #4, pre_flight dan**

### Modules Python modifiés
- `app/forge_goap.py`


## Commit 06101fa1 — 2026-06-04 22:48
**feat(#4): modele planner GOAP configurable via LAFORGE_PLANNER_MODEL (defaut laforge-qwen:latest) - pointer un modele plus fort pour les goals OUVERTS (deepseek-r1:14b, qwen2.5-coder:32b, ou cloud) sa**

### Modules Python modifiés
- `app/forge_goap.py`


## Commit ef800b8d — 2026-06-04 22:47
**feat(#2): tool MCP forge_stats - observabilite queryable (plan_cache hit-rate + loop_sentinel lag/events + ressources ram/cpu/gpu). Cable 6 couches: _NAMESPACE_ALIASES, _TOOL_MIN_RING(4), _raw_tool_ca**

### Modules Python modifiés
- `app/forge_mcp_rbac.py`
- `app/forge_mcp_registry.py`
- `tools/hub_middleware.py`


## Commit 184e0717 — 2026-06-04 22:45
**feat(#1): templates etendus - refactor (prelude-inspection skeleton+deps+body, NE modifie PAS, edit decide apres) + test-gen (body+deps pour grounding du test). Sort le LLM de plus de cas code. + synt**

### Modules Python modifiés
- `app/forge_goap.py`
- `tools/forge_orchestrate_loop.py`


## Commit eb3ade14 — 2026-06-04 22:05
**fix(sentinel): plafond de sanite 30s - les 'lags' >30s = suspend machine / saut horloge monotonic (constate: 925s-2500s avec logging.emit en haut de stack), PAS un blocage wrapper (<10s). Ignore -> tu**

### Modules Python modifiés
- `app/forge_loop_sentinel.py`


## Commit 1cea566e — 2026-06-04 18:06
**feat(#3): orchestrate detach=True - lance en tache de fond, retourne run_id IMMEDIAT (0.1ms vs 90-180s bloquant), poll via status_id. Deporter le long (ne bloque plus l'appel MCP au cap 120s). In-proc**

### Modules Python modifiés
- `app/forge_mcp_registry.py`


## Commit a5f3e01d — 2026-06-04 18:05
**feat(#4): plan_cache_stats() - compteur hits/misses/hit_rate du cache de plans GOAP. Observabilite du gain reel sur les goals recurrents de la boucle autonome**

### Modules Python modifiés
- `app/forge_goap.py`


## Commit e276994e — 2026-06-04 18:03
**fix(#2 saturation): handle_rag offload _rag_dense_search + _rag_bm25_search via asyncio.to_thread - _load_dense_cache (matrice embeddings TTL300s) + cosine bloquaient l'event loop (2e bloqueur nomme p**

### Modules Python modifiés
- `app/forge_mcp_registry.py`


## Commit c88112bd — 2026-06-04 18:02
**feat(#1): template-planner += corps de fonction (read_function_body) + cable read_function_body dans ALLOWED_METHODS + _hub_dispatch + forge_dispatchers (etait injoignable au planner). Valide: body go**

### Modules Python modifiés
- `app/forge_dispatchers.py`
- `app/forge_goap.py`
- `app/forge_trajectory.py`
- `tools/forge_orchestrate_loop.py`


## Commit 0848fe7c — 2026-06-04 17:51
**feat(orchestrate): synthese DETERMINISTE pour plans template (plan_id=tmpl) - formate les sorties tool (callers/callees/squelette) au lieu du resume LLM hallucinant. Sur le chemin code-analysis: ZERO **

### Modules Python modifiés
- `tools/forge_orchestrate_loop.py`


## Commit 92946630 — 2026-06-04 17:35
**feat(planner): template-planner DETERMINISTE pour goals code reconnaissables (callers/callees/dependances/impact/squelette) - bypass TOTAL du LLM (petit modele instable/hallucine fichier+tools) -> pla**

### Modules Python modifiés
- `app/forge_goap.py`


## Commit 55eb8e8f — 2026-06-04 17:21
**fix(D): sanitizer de plan deterministe dans decompose_goal - override file_path des tools code (get_file_skeleton/deps/read_function_body) par le chemin .py EXACT du goal (le petit LLM substituait for**

### Modules Python modifiés
- `app/forge_goap.py`


## Commit effb9641 — 2026-06-04 16:54
**fix(saturation): start_sampler ne prime plus _sample_once() inline (subprocess GPU Win32 SYNC) - bloquait l'event loop quand get_snapshot/should_throttle/resource_should_spawn appeles a froid depuis u**

### Modules Python modifiés
- `app/forge_resource_manager.py`


## Commit 7726f6bd — 2026-06-04 16:38
**perf(D,E): D=heuristique GOAP chemin-fichier EXACT du goal (anti-substitution RAG) + E3=cache get_function_dependencies TTL60s (379ms->0 sur repeat) + E5=prune blackboard amorti 1/20 writes (gain a l'**

### Modules Python modifiés
- `app/forge_callgraph_jit.py`
- `app/forge_goap.py`
- `app/forge_swarm_blackboard.py`


## Commit 8f7a2664 — 2026-06-04 16:36
**perf(A): timeout interne decompose_goal 55->90s (cold-load APU vs warm-race) + fix(B): forge_loop_sentinel utilise faulthandler.dump_traceback_later (watchdog) - capture la stack du COUPABLE pendant l**

### Modules Python modifiés
- `app/forge_goap.py`
- `app/forge_loop_sentinel.py`


## Commit 78585811 — 2026-06-04 15:54
**fix(orchestrate): _run_loop_async gere step.result str OU dict - get_file_skeleton/get_function_dependencies retournent une string (via _hub_dispatch {result:str} -> _execute_subgoal extrait le str) -**

### Modules Python modifiés
- `tools/forge_orchestrate_loop.py`


## Commit 9f388921 — 2026-06-04 15:43
**fix(hub): _ALLOWED_TOOLS middleware /mcp += get_file_skeleton, get_function_dependencies, blackboard_read_zone/propose_fact, read_function_body - 5e allowlist manquante qui bloquait tout appel HTTP (p**

### Modules Python modifiés
- `tools/hub_middleware.py`


## Commit 76c84ed0 — 2026-06-04 15:12
**fix(planner): cle cache plans = goal+ring SEULEMENT (exclut le context RAG preflight volatile qui causait un miss systematique sur orchestrate - 2 runs identiques re-planifies 170s constate). Le cache**

### Modules Python modifiés
- `app/forge_goap.py`


## Commit 427c76b3 — 2026-06-04 14:40
**perf(planner): warm laforge-qwen au boot hub (thread non bloquant, keep_alive) + timeout plan 120->180s - debloque le fast_path sur APU (1er plan aboutit -> cache #1 se peuple -> tools item1 executes)**

### Modules Python modifiés
- `app/forge_goap.py`
- `tools/forge_orchestrate_loop.py`
- `tools/nokido_hub.py`


## Commit c980b7f3 — 2026-06-04 13:52
**feat(blackboard): trust decay temporel (demi-vie 7j, effective_trust calcule au read, non destructif) + dedup quasi-doublons (cle sur fait normalise casse/espaces/ponctuation, sans embeddings) - opt#5**

### Modules Python modifiés
- `app/forge_swarm_blackboard.py`


## Commit 61959ae8 — 2026-06-04 13:50
**perf(tokens): compaction rtk-style des sorties brutes au dispatch (strip ANSI + collapse lignes vides + dedup lignes consecutives identiques) AVANT le cap, allowlist _CAP_TOOLS, JSON intact - -92pct s**

### Modules Python modifiés
- `app/forge_mcp_registry.py`


## Commit e6cf96c0 — 2026-06-04 13:48
**fix(callgraph): callers resout les alias d'import (func as _f) + detecte les refs passees en argument (to_thread(func,...)) - champ via=call|ref. Fin du sous-comptage (read_zone 1->3 callers). Opt#3**

### Modules Python modifiés
- `app/forge_callgraph_jit.py`


## Commit 20354c3c — 2026-06-04 13:45
**feat(observability): forge_loop_sentinel - sentinelle lag event-loop in-process (equivalent souverain py-spy, zero attach) : detecte les wrappers bloquants + dump faulthandler stack -> logs/loop_lag.l**

### Modules Python modifiés
- `app/forge_loop_sentinel.py`
- `tools/nokido_hub.py`


## Commit 8ac93255 — 2026-06-04 13:41
**perf(planner): cache de plans en-process (TTL 10min, skip appel LLM ~40-50s si goal+context identique) - reduit le fast_path de la boucle autonome sur APU**

### Modules Python modifiés
- `app/forge_goap.py`


## Commit 58726397 — 2026-06-04 13:10
**feat(planner): expose code sensors + blackboard au planner orchestrate/GOAP - ALLOWED_METHODS (vocab+ring) + _hub_dispatch (exec orchestrate) + _dispatchers (exec trajectory) + GOAP_SYSTEM_PROMPT (heu**

### Modules Python modifiés
- `app/forge_dispatchers.py`
- `app/forge_goap.py`
- `app/forge_trajectory.py`
- `tools/forge_orchestrate_loop.py`


## Commit 53f70919 — 2026-06-04 12:35
**feat(rag,blackboard): reorder_mid opt-in anti lost-in-the-middle (search top-k head+tail, active dans agent_proxy) + blackboard GC/TTL auto-prune par zone + gc()**

### Modules Python modifiés
- `app/forge_agent_proxy.py`
- `app/forge_rag_engine.py`
- `app/forge_swarm_blackboard.py`


## Commit b4637ac7 — 2026-06-04 12:06
**feat(code): get_file_skeleton + get_function_dependencies - pagination semantique (squelette AST) + call-graph fonction-level JIT (callees/callers), tools forge.code.***

### Modules Python modifiés
- `app/forge_callgraph_jit.py`
- `app/forge_mcp_rbac.py`
- `app/forge_mcp_registry.py`


## Commit a2ffd3ab — 2026-06-04 11:39
**feat(swarm): forge_swarm_blackboard - tableau noir zone SQLite WAL (write-funnel mono-writer asyncio, ACL par ring, 2 tools MCP forge.swarm.*)**

### Modules Python modifiés
- `app/forge_mcp_rbac.py`
- `app/forge_mcp_registry.py`
- `app/forge_swarm_blackboard.py`


## Commit b0ec2d1a — 2026-06-04 00:55
**fix(anatomy): repositionne les organes sur la silhouette SVG 400x700 (coords historiques etaient hors-cadre ~900x600)**

### Modules Python modifiés
- `app/forge_anatomy_state.py`


## Commit ef1412e3 — 2026-06-04 00:41
**feat(observability): anatomie LIVE - flux organe-a-organe depuis les spans reels (audit.db) au lieu de statique**

### Modules Python modifiés
- `app/forge_anatomy_state.py`


## Commit 4fb8e1f7 — 2026-06-04 00:27
**feat(observability): forge_trace_ui - UI web souveraine (Mermaid live, remplace Phoenix ELv2)**

### Modules Python modifiés
- `tools/forge_trace_ui.py`


## Commit 320fc0f0 — 2026-06-04 00:19
**fix(hub): offload sandbox python/shell exec - root cause du wedge event-loop (WaitForSingleObject sync bloquait /health)**

### Modules Python modifiés
- `app/forge_mcp_registry.py`


## Commit ae5725f9 — 2026-06-04 00:14
**fix(license): drop Phoenix (Elastic License 2.0, non-libre) -> Jaeger (Apache); ARCHITECTURE_SCHEMA complet par domaine**

### Modules Python modifiés
- `tools/forge_obs_setup.py`
- `tools/forge_otel_export.py`

### Documentation mise à jour
- `docs/ARCHITECTURE_SCHEMA.md`


## Commit ea77922f — 2026-06-04 00:04
**feat(observability): forge_arch_schema v2 - schema COMPLET par domaine (430 modules clusterises)**

### Modules Python modifiés
- `tools/forge_arch_schema.py`


## Commit b54feaba — 2026-06-03 23:38
**feat(observability): forge_profiler_hooks - py-spy/treesitter/uProf sur evenement + VizTracer/Scalene a la demande (points 3/4)**

### Modules Python modifiés
- `tools/forge_profiler_hooks.py`


## Commit fef5558b — 2026-06-03 23:22
**feat(observability): dual-emit span -> Phoenix OTLP (:6006) + audit.db souverain**

### Modules Python modifiés
- `app/forge_span.py`
- `tools/forge_otel_export.py`


## Commit 7ee41a48 — 2026-06-03 22:03
**fix(observability): forge_obs_setup - path py314 explicite (OTel dans le runtime hub)**

### Modules Python modifiés
- `tools/forge_obs_setup.py`


## Commit dba27471 — 2026-06-03 22:00
**test(observability): forge_span selftest - arbre 3 niveaux trace_id dedie**

### Modules Python modifiés
- `app/forge_span.py`


## Commit 100631d7 — 2026-06-03 22:00
**feat(observability): forge_trace_viz to_tree - rend l arbre d appels span_id/parent_id**

### Modules Python modifiés
- `tools/forge_trace_viz.py`


## Commit e1550354 — 2026-06-03 21:58
**feat(observability): wrap provider ask() in span -> LLM call-flow DAG (all 30 providers)**

### Modules Python modifiés
- `app/forge_agent_proxy.py`


## Commit dafcd90e — 2026-06-03 21:56
**feat(observability): nested spans - audit_log span_id + forge_span context manager**

### Modules Python modifiés
- `app/forge_audit_log.py`
- `app/forge_span.py`


## Commit baa63752 — 2026-06-03 21:43
**docs(observability): ARCHITECTURE_SCHEMA - schema multi-couches auto-genere (statique 430 modules)**

### Documentation mise à jour
- `docs/ARCHITECTURE_SCHEMA.md`


## Commit acbe3717 — 2026-06-03 21:38
**feat(observability): forge_obs_setup - install OTel SDK + arize-phoenix (sovereign, no Docker)**

### Modules Python modifiés
- `tools/forge_obs_setup.py`


## Commit e49909ab — 2026-06-03 21:35
**fix(observability): forge_arch_schema use pure scan funcs (build_panorama LLM path returned empty)**

### Modules Python modifiés
- `tools/forge_arch_schema.py`


## Commit a03e5625 — 2026-06-03 21:33
**feat(observability): forge_arch_schema - generateur schema souverain (panorama statique Mermaid)**

### Modules Python modifiés
- `tools/forge_arch_schema.py`


## Commit 0900da77 — 2026-06-03 20:57
**feat: copilot_cli provider + wiki Session 2026-06-03 + CLI-OAuth doc**

### Modules Python modifiés
- `app/forge_agent_proxy.py`

### Documentation mise à jour
- `docs/wiki/05-LLM-Providers.md`
- `docs/wiki/Session-2026-06-03.md`


## Commit 684538a5 — 2026-06-03 20:45
**feat: wire archi_lint into CI + Copilot CLI integration doc**

### Documentation mise à jour
- `docs/COPILOT_CLI_INTEGRATION.md`


## Commit faf15966 — 2026-06-03 17:53
**feat(embed): forge_embed_backfill_jina - backfill cloud embeddings NULL (3 phases)**

### Modules Python modifiés
- `tools/forge_embed_backfill_jina.py`


## Commit 53ad44f8 — 2026-06-03 17:46
**fix(embed): local-first cascade + skip unconfigured providers + AGENTS.md souverain**

### Modules Python modifiés
- `app/forge_embed_router.py`

### Documentation mise à jour
- `AGENTS.md`


## Commit a64a2cae — 2026-06-03 16:47
**fix(docker-keeper): wsl --shutdown before launching Docker (post-update WSL integration re-mount)**

### Modules Python modifiés
- `tools/forge_docker_keeper.py`


## Commit 5423046d — 2026-06-03 16:17
**feat(ui): sovereign build-less health dashboard rendering health.json (#4)**

### Modules Python modifiés
- `tools/forge_health_ui.py`


## Commit b9a6f0cc — 2026-06-03 16:15
**feat(acp phase2): per-session provider+rag_context, progressive chunked streaming, authenticate, richer capabilities**

### Modules Python modifiés
- `tools/forge_acp_adapter.py`


## Commit 209495b1 — 2026-06-03 15:55
**fix(security): universal SemanticFirewall gate on every provider.ask (Golden Rule #4)**

### Modules Python modifiés
- `app/forge_agent_proxy.py`


## Commit 62647a4f — 2026-06-03 15:44
**polish(acp): unwrap ask JSON -> stream clean .text to ACP host**

### Modules Python modifiés
- `tools/forge_acp_adapter.py`


## Commit f4c50d0f — 2026-06-03 15:44
**fix(acp): Bearer auth + vault token fallback for hub route (was 401)**

### Modules Python modifiés
- `tools/forge_acp_adapter.py`


## Commit 37067d28 — 2026-06-03 15:42
**test(acp): add --selftest mode (in-process ACP flow + real Nokido route)**

### Modules Python modifiés
- `tools/forge_acp_adapter.py`


## Commit c946c922 — 2026-06-03 15:40
**feat(acp): PoC ACP agent adapter — Nokido as sovereign agent backend for ACP hosts**

### Modules Python modifiés
- `tools/forge_acp_adapter.py`


## Commit f71db815 — 2026-06-03 14:56
**fix(observability P3): no NULL trace_id + tasklist utf-8 decode spam**

### Modules Python modifiés
- `app/forge_execution_tracer.py`
- `app/forge_heartbeat.py`


## Commit 1f32b154 — 2026-06-03 14:36
**feat(supervisor): active hub /health probe + hub-independent health.json (P1.1+P1.3)**

### Modules Python modifiés
- `app/forge_sandbox_exec.py`


## Commit 236e5129 — 2026-06-03 13:45
**feat(observability): OTel→Jaeger exporter (#6) + AMD uProf APU collector (#7), fail-open**

### Modules Python modifiés
- `tools/forge_otel_export.py`
- `tools/forge_uprof_apu.py`


## Commit 4aee8e05 — 2026-06-03 13:43
**feat(observability): tree-sitter pre-write structural validator (multi-lang, fail-open)**

### Modules Python modifiés
- `tools/forge_treesitter_validate.py`


## Commit 3f5c34e6 — 2026-06-03 13:32
**fix(archi_lint): --disable-version-check + per-rule timeout (semgrep cold-start hang)**

### Modules Python modifiés
- `tools/forge_archi_lint.py`


## Commit 541e8e09 — 2026-06-03 13:29
**debug(archi_lint): --debug flag (cmd/rc/stderr)**

### Modules Python modifiés
- `tools/forge_archi_lint.py`


## Commit bde2a36a — 2026-06-03 13:28
**fix(archi_lint): resolve relative targets vs ROOT (semgrep cwd mismatch = 0 scanned)**

### Modules Python modifiés
- `tools/forge_archi_lint.py`


## Commit dd1219b6 — 2026-06-03 13:28
**debug(archi_lint): surface semgrep errors + scanned file count**

### Modules Python modifiés
- `tools/forge_archi_lint.py`


## Commit d7b2335a — 2026-06-03 13:26
**feat(observability): semgrep architectural rules — Nokido Golden Rules lint**

### Modules Python modifiés
- `tools/forge_archi_lint.py`


## Commit 2a33fae6 — 2026-06-03 13:22
**feat(observability): wire Langfuse on LLM tracking seam (fail-open, redacted egress)**

### Modules Python modifiés
- `app/forge_agent_proxy.py`
- `app/forge_langfuse_hook.py`


## Commit 254b175c — 2026-06-03 13:13
**feat(pyspy): add 'stacks' mode — read /debug/stacks async pileup histogram**

### Modules Python modifiés
- `tools/forge_pyspy_profiler.py`


## Commit 78f1cca5 — 2026-06-03 13:08
**tool(hub): detached hub reload (run_job survives the restart self-kill)**

### Modules Python modifiés
- `tools/forge_hub_reload.py`


## Commit 8a0f6c89 — 2026-06-03 12:53
**feat(hub): /debug/stacks endpoint — asyncio tasks + threads + coro pileup histogram**

### Modules Python modifiés
- `tools/nokido_hub.py`


## Commit 8e3946db — 2026-06-03 12:49
**feat(pyspy): elevation remediation hint on OpenProcess-denied (hub=SYSTEM)**

### Modules Python modifiés
- `tools/forge_pyspy_profiler.py`


## Commit 94baffb9 — 2026-06-03 12:48
**fix(pyspy): extract py-spy.exe from wheel to C:/tmp/nokido_bin (no profile ACL)**

### Modules Python modifiés
- `tools/forge_pyspy_profiler.py`


## Commit 2f724e68 — 2026-06-03 12:47
**feat(pyspy): add install mode (pip --user) + dynamic binary discovery**

### Modules Python modifiés
- `tools/forge_pyspy_profiler.py`


## Commit 8d35ec0e — 2026-06-03 12:46
**feat(observability): forge_pyspy_profiler — flame/dump of the hub (saturation)**

### Modules Python modifiés
- `tools/forge_pyspy_profiler.py`


## Commit 9e3bee3f — 2026-06-03 12:41
**fix(trace_viz): ASCII-safe output + utf-8 stdout (Windows cp1252 console)**

### Modules Python modifiés
- `tools/forge_trace_viz.py`


## Commit f84d72cc — 2026-06-03 12:40
**fix(trace_viz): tolerate NULL trace_id in list/top output**

### Modules Python modifiés
- `tools/forge_trace_viz.py`


## Commit 36ae82eb — 2026-06-03 12:40
**feat(trace_viz): dual-store — read execution_traces.db (--exec) for session-chained tool-call flows**

### Modules Python modifiés
- `tools/forge_trace_viz.py`


## Commit 097aaa64 — 2026-06-03 12:38
**feat(trace_viz): add 'diag' — audit trace-propagation health check**

### Modules Python modifiés
- `tools/forge_trace_viz.py`


## Commit 1ec0ac35 — 2026-06-03 12:37
**feat(trace_viz): add 'top' (busiest traces) to surface multi-span flows**

### Modules Python modifiés
- `tools/forge_trace_viz.py`


## Commit fd9ec32a — 2026-06-03 12:36
**feat(observability): forge_trace_viz — runtime call-flow from trace_id**

### Modules Python modifiés
- `tools/forge_trace_viz.py`


## Commit 063c07e9 — 2026-06-03 12:22
**fix(deno_check): locate deno via PATH then running process exe**

### Modules Python modifiés
- `tools/forge_deno_check.py`


## Commit fe08571e — 2026-06-03 12:21
**tool(deno): type-check helper for Deno/TS files (trusted, pre-commit validation)**

### Modules Python modifiés
- `tools/forge_deno_check.py`


## Commit 13f044e4 — 2026-06-03 12:06
**feat(supervisor): generic on-demand launcher + ondemand toml classifier**

### Modules Python modifiés
- `tools/forge_service_ondemand.py`
- `tools/forge_supervisor_ctl.py`


## Commit 6d33b329 — 2026-06-03 12:02
**fix(supervisor): correct reconcile start route /supervisor/service/start**

### Modules Python modifiés
- `tools/forge_supervisor_reconcile.py`
- `tools/nokido_hub.py`

### Documentation mise à jour
- `README.md`
- `docs/skills/nokido/SKILL.md`


## Commit 37880283 — 2026-06-03 12:01
**feat(supervisor): reconcile tool to resume stalled boot waves**

### Modules Python modifiés
- `tools/forge_supervisor_reconcile.py`


## Commit ca75384a — 2026-06-02 23:47
**fix(db-preflight): self_heal skip si RAG jonction + volume non monte**

### Modules Python modifiés
- `tools/forge_db_preflight.py`


## Commit 0155de70 — 2026-06-02 23:16
**fix(at-rest): jonction dossier RAG->V: au lieu de file-symlink**

### Modules Python modifiés
- `tools/forge_at_rest_veracrypt.py`


## Commit cc207bbc — 2026-06-02 17:54
**fix(infra): LlamaNative on-demand (disabled) + NokidoLlamaKeeper monitor-only - libere 7GB RAM au boot, anti-OOM hub**

### Modules Python modifiés
- `tools/forge_llama_keeper.py`


## Commit 3e3aa879 — 2026-06-02 17:43
**feat(infra): forge_llama_keeper - lifecycle on-demand modele local (unload si RAM tight+idle, kill doublons, anti-OOM hub)**

### Modules Python modifiés
- `tools/forge_llama_keeper.py`


## Commit 68855fa1 — 2026-06-02 16:46
**feat(tokens): compacteur sorties Bash (DSL rtk porte) + hook PreToolUse client-side**

### Modules Python modifiés
- `tools/forge_cmd_compactor.py`
- `tools/hook_bash_compact.py`


## Commit 41cab230 — 2026-06-02 16:37
**fix(db): forge_db_path() realpath - symlink C:->V: writable, debloque writes non-service (veille/access_count/eco)**

### Modules Python modifiés
- `app/forge_chain_executor.py`
- `app/forge_db_conn.py`
- `app/forge_db_path.py`
- `app/forge_watch_agent.py`


## Commit 16de88eb — 2026-06-02 15:28
**fix(ci): license guard - LGPL exclu du test GPLv2-only (faux positif paramiko lgpl-2.1, AGPL-compat)**

### Modules Python modifiés
- `tools/forge_license_guard.py`


## Commit 5fb587b9 — 2026-06-02 15:07
**feat(embed): eco threads cap + dim audit + 1024D guard (anti-saturation/anti-mix)**

### Modules Python modifiés
- `tools/forge_embed_eco.py`


## Commit f301d79f — 2026-06-02 14:39
**feat(rag): access_count bump a la lecture + drain eco BGE-M3 CPU (no-BSOD, verify cosinus)**

### Modules Python modifiés
- `app/forge_rag_engine.py`
- `tools/forge_embed_eco.py`


## Commit 41323147 — 2026-06-02 14:16
**feat(ui): observe +title/text/dom_nodes +settle_ms (debug dashboards dynamiques)**

### Modules Python modifiés
- `tools/forge_ui_oracle.py`


## Commit 1437eb54 — 2026-06-02 14:08
**feat(ui): forge_ui_oracle general (debug+verify GUI) + video observe + vision_som scaffold + CLI**

### Modules Python modifiés
- `tools/ctf/forge_playwright_browser.py`
- `tools/forge_ui_oracle.py`
- `tools/forge_video_observe.py`
- `tools/forge_vision_som.py`


## Commit 327ecae1 — 2026-06-02 13:58
**feat(ui): ui_observe oracle (a11y+set-of-mark+interactive+dom_hash) sur playwright**

### Modules Python modifiés
- `tools/ctf/forge_playwright_browser.py`


## Commit 9a165725 — 2026-06-02 13:22
**fix(ccr): store fichier sandbox/ccr (embeddings.db readonly en contexte dispatch)**

### Modules Python modifiés
- `app/forge_agent_proxy.py`
- `app/forge_mcp_registry.py`


## Commit a324f1cc — 2026-06-02 13:14
**feat(sec): agent_proxy pre_flight DLP (#4) + CCR reponse reversible + ask_tracked waist**

### Modules Python modifiés
- `app/forge_agent_proxy.py`


## Commit 8f3a38af — 2026-06-02 13:04
**feat(cache): CacheAligner prefix-stabilize + guard sortie reversible CCR**

### Modules Python modifiés
- `app/forge_agent_proxy.py`
- `app/forge_cache_aligner.py`
- `app/forge_llm_router.py`
- `app/forge_mcp_registry.py`


## Commit 53c61a68 — 2026-06-02 12:16
**feat(tls): tache onlogon Caddy silencieuse (pythonw+CREATE_NO_WINDOW) + outil masquage comptes service de l ecran de connexion**

### Modules Python modifiés
- `tools/forge_hide_service_accounts.py`
- `tools/forge_tls_caddy.py`


## Commit 65812360 — 2026-06-02 02:30
**feat(supervisor): boot orphan-reaper (dry-run) anti child-leak**

### Modules Python modifiés
- `tools/forge_orphan_reaper.py`


## Commit aabd149b — 2026-06-02 00:11
**feat(watcher): detect crash-loop from service_crash + emit critical event**

### Modules Python modifiés
- `tools/forge_service_crash_watcher.py`


## Commit ab318740 — 2026-06-01 21:17
**feat(ami): #3b bias MCTS - curated_skills injectes dans mcts_propose (boucle fermee aussi path MCTS)**

### Modules Python modifiés
- `app/forge_actor.py`
- `app/forge_mpc.py`


## Commit 3ddd2a68 — 2026-06-01 21:15
**feat(llm): escalade confiance-aware (FrugalGPT inverse) dans call_cascade**

### Modules Python modifiés
- `app/forge_llm_router.py`


## Commit f1e329e7 — 2026-06-01 20:56
**feat(ami): #1 eval-driven - pattern eval_fitness (monitor scores, proposal si regression)**

### Modules Python modifiés
- `app/forge_autonomous_loops.py`
- `app/forge_benchmark_adapter.py`


## Commit 6a3552e9 — 2026-06-01 20:54
**feat(ami): #3a curated desc->action_type + forge_benchmark_adapter (eval-driven base)**

### Modules Python modifiés
- `app/forge_actor.py`
- `app/forge_benchmark_adapter.py`


## Commit fc493a8b — 2026-06-01 20:47
**feat(ami): ferme la boucle auto-amelioration - curated_skills reinjectes au planner**

### Modules Python modifiés
- `app/forge_actor.py`
- `app/forge_mpc.py`


## Commit 99b581d4 — 2026-06-01 20:40
**feat(viz): Neural Swarm Observatory - node-graph live Netron-style (phase 2)**

### Modules Python modifiés
- `tools/forge_observatory.py`


## Commit b6f12b98 — 2026-06-01 20:32
**feat(viz): hooks emission raisonnement (phase 1.5) - actor MCTS / mpc horizon / llm cascade**

### Modules Python modifiés
- `app/forge_actor.py`
- `app/forge_llm_router.py`
- `app/forge_mpc.py`


## Commit e22ced54 — 2026-06-01 20:20
**feat(viz): reflexion CLI backlog + --once snapshot + group trace_id (testé OK)**

### Modules Python modifiés
- `tools/forge_reflexion_cli.py`


## Commit 78f792d2 — 2026-06-01 20:17
**feat(viz): CLI flux-de-reflexion + miroir JSONL swarm_bus (phase 1)**

### Modules Python modifiés
- `app/forge_swarm_bus.py`
- `tools/forge_reflexion_cli.py`


## Commit 8eb76e13 — 2026-06-01 18:49
**feat(jepa): fine-tune local CPU (alt Colab, 0 GPU/DirectML = 0 BSOD)**

### Modules Python modifiés
- `tools/forge_jepa_finetune_local.py`


## Commit ea275056 — 2026-06-01 18:25
**feat(jepa): dataset contrastif sanitize (membrane) + notebook Colab LoRA BGE-M3**

### Modules Python modifiés
- `tools/forge_jepa_dataset.py`
- `tools/forge_jepa_finetune_colab.py`


## Commit 4e94a6a3 — 2026-06-01 17:04
**fix(tls-caddy): garder admin API loopback (caddy stop/reload cassait avec admin off)**

### Modules Python modifiés
- `tools/forge_tls_caddy.py`


## Commit c207f77b — 2026-06-01 16:55
**feat(tls-caddy): --install-boot persistance login cross-OS (onlogon/systemd-user/launchd)**

### Modules Python modifiés
- `tools/forge_tls_caddy.py`


## Commit d8642fa2 — 2026-06-01 16:34
**feat(tls-caddy): --start/--stop (background) + vendored caddy lookup + fix winget id**

### Modules Python modifiés
- `tools/forge_tls_caddy.py`


## Commit d62a9639 — 2026-06-01 16:29
**feat(tls): forge_tls_caddy - terminaison TLS via Caddy (panel: methode robuste cross-OS)**

### Modules Python modifiés
- `tools/forge_tls_caddy.py`


## Commit 2713b158 — 2026-06-01 16:23
**fix(tls-proxy): half-close pump + acte limite asyncio SSL Windows (POSIX-only)**

### Modules Python modifiés
- `tools/forge_tls_proxy.py`


## Commit 428ae6ed — 2026-06-01 15:52
**feat(at-rest): cross-OS - veracrypt --text/LUKS Linux + ln -s + systemd/launchd boot**

### Modules Python modifiés
- `tools/forge_at_rest_veracrypt.py`
- `tools/forge_install_boot_mount.py`


## Commit 9a022e57 — 2026-06-01 15:39
**feat(tls): forge_tls_proxy - reverse-proxy TLS-terminant (ProactorEventLoop)**

### Modules Python modifiés
- `tools/forge_tls_proxy.py`


## Commit b4991159 — 2026-06-01 15:02
**harden(tls): listener gardé (crash HTTPS ne tue pas HTTP) + fix cert private_bytes**

### Modules Python modifiés
- `tools/forge_gen_tls_cert.py`
- `tools/nokido_hub.py`


## Commit 5c7b85cd — 2026-06-01 14:45
**fix(installer): wrapper ascii (em-dash crash) + cleanup tache legacy + deprecate vc --install-boot**

### Modules Python modifiés
- `tools/forge_at_rest_veracrypt.py`
- `tools/forge_install_boot_mount.py`


## Commit e8f7364c — 2026-06-01 14:42
**feat(installer): forge_install_boot_mount - tache boot VC + anti-race services**

### Modules Python modifiés
- `tools/forge_install_boot_mount.py`


## Commit ae0b113e — 2026-06-01 14:37
**feat(at-rest): --install-boot (tache SYSTEM onstart, keyfile vault preserve)**

### Modules Python modifiés
- `tools/forge_at_rest_veracrypt.py`


## Commit d9d87ab0 — 2026-06-01 14:26
**feat: TLS dual-listen non-breaking + VeraCrypt keyfile au machine_vault**

### Modules Python modifiés
- `tools/forge_at_rest_veracrypt.py`
- `tools/nokido_hub.py`


## Commit 8aad9a09 — 2026-06-01 14:15
**feat(at-rest): VeraCrypt container tool + runbook (voie vitesse-preservee)**

### Modules Python modifiés
- `tools/forge_at_rest_veracrypt.py`


## Commit 169f46e8 — 2026-06-01 14:04
**feat: TLS cert gen + user/tenant/MFA layer + Perplexity model refresh**

### Modules Python modifiés
- `app/forge_agent_proxy.py`
- `app/forge_user_layer.py`
- `tools/forge_gen_tls_cert.py`


## Commit f20b7d5b — 2026-06-01 13:49
**fix(at-rest): cipher timeout 120->3600s + warn faux-echec gros volume**

### Modules Python modifiés
- `tools/forge_at_rest_efs.py`


## Commit 54745e3b — 2026-06-01 13:40
**fix(at-rest): cipher OEM decode errors=replace + escape docstring**

### Modules Python modifiés
- `tools/forge_at_rest_efs.py`


## Commit 1457543f — 2026-06-01 13:35
**docs(at-rest): note EFS per-compte + BitLocker installeur**

### Modules Python modifiés
- `tools/forge_at_rest_efs.py`


## Commit abee0198 — 2026-06-01 13:15
**feat(compliance): chiffrement at-rest RAG + TLS hub opt-in**

### Modules Python modifiés
- `app/forge_db_conn.py`
- `tools/forge_at_rest_efs.py`
- `tools/forge_db_encrypt_migrate.py`
- `tools/nokido_hub.py`


## Commit abee0198 — 2026-06-01 13:14
**feat(compliance): chiffrement at-rest RAG + TLS hub opt-in**

### Modules Python modifiés
- `app/forge_db_conn.py`
- `tools/forge_at_rest_efs.py`
- `tools/forge_db_encrypt_migrate.py`
- `tools/nokido_hub.py`


## Commit d4a9ae2d — 2026-06-01 12:00
**fix(supervisor): real RAM read + anti-flap + staggered boot + Docker on-demand**

### Modules Python modifiés
- `app/forge_exegol_mcp_server.py`
- `tools/forge_docker_keeper.py`


## Commit c404414d — 2026-05-31 23:42
**feat(fleet): forge_fleet_router (role-clustering + Context Anchoring) + fleet.toml + durable_workflow proof**

### Modules Python modifiés
- `tools/forge_durable_workflow.py`
- `tools/forge_fleet_router.py`


## Commit 10ae2830 — 2026-05-31 23:16
**feat(orchestration): PoC forge_durable_workflow - durable execution event-sourced + replay**

### Modules Python modifiés
- `tools/forge_durable_workflow.py`


## Commit b288f677 — 2026-05-31 22:53
**docs(wiki): page 20 Orchestration & Workflows (durable-execution direction Temporal/Mistral) + changelog session 2026-05-31**

### Documentation mise à jour
- `docs/wiki/20-Orchestration-and-Workflows.md`
- `docs/wiki/Home.md`
- `docs/wiki/Session-2026-05-31.md`


## Commit cc300374 — 2026-05-31 22:41
**docs(readme): section 'Sovereignty by hardware' (paliers frugal/mid/full-sovereign) + lien WHAT_IS_NOKIDO**

### Documentation mise à jour
- `README.md`


## Commit 8a8083dc — 2026-05-31 22:30
**feat(governance): garde-fou licence AGPLv3 (pip deps) + definition honnete Nokido**

### Modules Python modifiés
- `tools/forge_license_guard.py`

### Documentation mise à jour
- `docs/WHAT_IS_NOKIDO.md`


## Commit 564dd7fd — 2026-05-31 22:11
**fix(sft): recette locale affinee (panel multi-LLM) - LR 2e-5, early-stop, MBPP, 3B, bf16**

### Modules Python modifiés
- `tools/forge_sft_eval.py`
- `tools/forge_sft_export.py`
- `tools/forge_sft_train.py`


## Commit 130ca1b8 — 2026-05-31 21:50
**fix(rag): trigger chokepoint anti-repollution tier + filtre HOT_TIER_SQL rebuild_embeddings**

### Modules Python modifiés
- `tools/forge_rebuild_embeddings.py`
- `tools/forge_tier_guard_install.py`


## Commit 85a6ad78 — 2026-05-31 21:40
**feat(rag): forge_embed_corpus_audit - mesure composition tier vectorise (embedding-relevance)**

### Modules Python modifiés
- `tools/forge_embed_corpus_audit.py`


## Commit 402546bf — 2026-05-31 21:19
**fix(desktop): start/stop dynamiques (Get-Service) + memory_compactor --auto hook**

### Modules Python modifiés
- `tools/forge_memory_compactor.py`


## Commit 803a65bf — 2026-05-31 21:04
**fix(memory): compactor cible episodique-DONE only (spare module refs + feedback)**

### Modules Python modifiés
- `tools/forge_memory_compactor.py`


## Commit 50d821f7 — 2026-05-31 20:57
**feat(memory): compactor GC - purge les entrees DONE de l'index .claude vers archive froide**

### Modules Python modifiés
- `tools/forge_memory_compactor.py`


## Commit 0e413944 — 2026-05-31 18:57
**fix(bench): write_text encoding=utf-8 (HumanEval golden + BFCL) - crash cp1252 sur Unicode**

### Modules Python modifiés
- `tools/forge_bfcl_runner.py`
- `tools/forge_humaneval_runner.py`


## Commit 75714836 — 2026-05-31 18:19
**feat(sft): eval held-out base-vs-adapter + split train (mesure honnete sans leakage)**

### Modules Python modifiés
- `tools/forge_sft_eval.py`
- `tools/forge_sft_export.py`


## Commit 8c8ecd9e — 2026-05-31 18:11
**fix(sft): API trl 1.5.1/transformers 5 (dtype, max_length, use_cpu) - train OK**

### Modules Python modifiés
- `tools/forge_sft_train.py`


## Commit 3482f8dc — 2026-05-31 17:22
**feat(sft): HumanEval golden capture + harvest + LoRA train script (boucle code non-flaky)**

### Modules Python modifiés
- `tools/forge_humaneval_runner.py`
- `tools/forge_sft_export.py`
- `tools/forge_sft_train.py`


## Commit 1628937b — 2026-05-31 17:18
**feat(sft): exporter golden-dataset (swebench resolved + goap success -> chat JSONL)**

### Modules Python modifiés
- `tools/forge_sft_export.py`


## Commit 5cbc39b9 — 2026-05-31 17:11
**fix(hub): allow-list + research-fields pour oracle_python_repl/spawn_swarm/trigger_audit**

### Modules Python modifiés
- `tools/hub_middleware.py`


## Commit bed93edf — 2026-05-31 16:54
**debug(goap): launcher surface l'erreur/text par action (diag oracle ok=false)**

### Modules Python modifiés
- `tools/forge_goap_online_launch.py`


## Commit 9703f108 — 2026-05-31 16:40
**feat(goap): launcher execute+record - genere les 1eres traces self-play**

### Modules Python modifiés
- `tools/forge_goap_online_launch.py`


## Commit 6d81aa3a — 2026-05-31 16:38
**feat(goap): keystone self-play - persiste les trajectoires dans execution_traces.db**

### Modules Python modifiés
- `app/forge_goap_intuition.py`
- `tests/test_goap_intuition.py`
- `tools/forge_goap_hub_bridge.py`


## Commit 297622e7 — 2026-05-31 16:19
**feat(goap): launcher sandbox-online -> value_net online live dans le planner**

### Modules Python modifiés
- `tools/forge_goap_online_launch.py`


## Commit 07f9e421 — 2026-05-31 16:14
**feat(goap): reflexe doute->oracle + value_net online (HF MiniLM 384D aligne)**

### Modules Python modifiés
- `app/forge_goap_intuition.py`
- `tests/test_goap_intuition.py`
- `tools/forge_goap_hub_bridge.py`


## Commit 3972470b — 2026-05-31 16:06
**fix(goap): value_net embed OPT-IN + local_files_only (0 reseau, 0 taxe import defaut)**

### Modules Python modifiés
- `app/forge_goap_intuition.py`


## Commit 8e18f802 — 2026-05-31 15:44
**feat(goap): cable embed_fn value_net (auto-arme si MiniLM 384D present)**

### Modules Python modifiés
- `app/forge_goap_intuition.py`
- `tests/test_goap_intuition.py`


## Commit 647ee0b2 — 2026-05-31 15:38
**feat(goap): heuristique d'intuition + porte signal/bruit + fallback System1->2**

### Modules Python modifiés
- `app/forge_goap_intuition.py`
- `tests/test_goap_intuition.py`
- `tools/forge_goap_hub_bridge.py`


## Commit 40f186bf — 2026-05-31 15:27
**feat(goap): action oracle + log systematique event-bus de toute action**

### Modules Python modifiés
- `tools/forge_goap_hub_bridge.py`


## Commit a989d848 — 2026-05-31 15:11
**feat(mcp): oracle_python_repl - Oracle d'execution deterministe (sandbox offline)**

### Modules Python modifiés
- `app/forge_mcp_registry.py`


## Commit c3ea1b15 — 2026-05-31 14:58
**feat(bfcl): provider router (gpt-oss-120b) + schema-oracle repair + format hints**

### Modules Python modifiés
- `tools/forge_bfcl_runner.py`


## Commit e2f8abbc — 2026-05-31 08:52
**feat(audit+bench): LensRoutedPool cloud + HumanEval 98.8% + 4 cloud fixes**

### Modules Python modifiés
- `app/forge_audit_worker.py`
- `app/forge_host_capabilities.py`
- `app/forge_local_inference_pool.py`
- `app/forge_provider_quota.py`
- `tests/test_lens_routed_pool.py`
- `tools/forge_audit_swebench.py`
- `tools/forge_humaneval_runner.py`


## Commit ad478e38 — 2026-05-31 05:14
**feat(audit): ForgeAudit LIVE — verbe MCP forge_trigger_audit + /forge ultra CLI**

### Modules Python modifiés
- `app/forge_mcp_registry.py`
- `tools/llama_cli.py`


## Commit 980c0332 — 2026-05-31 05:05
**feat(audit): ForgeAudit coeur — reducer AST-filter + worker RO + orchestrateur + 15 tests**

### Modules Python modifiés
- `app/forge_audit.py`
- `app/forge_audit_reducer.py`
- `app/forge_audit_worker.py`
- `tests/test_forge_audit.py`
- `tests/test_forge_audit_reducer.py`


## Commit 5d2367f0 — 2026-05-31 04:54
**feat(audit): ForgeAudit personas — 4 prismes (Security/Correctness/Architecture/Style) calibres 7B**

### Modules Python modifiés
- `app/forge_audit_personas.py`


## Commit 407f00eb — 2026-05-31 04:18
**feat(swarm): ForgeSwarm M6 — verbe MCP forge_spawn_swarm (live, ring<=2)**

### Modules Python modifiés
- `app/forge_mcp_registry.py`


## Commit ac2cc389 — 2026-05-31 04:11
**feat(swarm): ForgeSwarm M3 — pool inference local + 9 tests**

### Modules Python modifiés
- `app/forge_local_inference_pool.py`
- `tests/test_forge_local_inference_pool.py`


## Commit 17e4aa36 — 2026-05-31 04:08
**docs(swarm): etat du build — coeur deterministe livre (5 modules, 39 tests E2E)**

### Documentation mise à jour
- `docs/roadmap_forge_swarm.md`


## Commit e04b2e91 — 2026-05-31 04:07
**feat(swarm): ForgeSwarm M5 — orchestrateur E2E + 39 tests verts**

### Modules Python modifiés
- `app/forge_swarm_context.py`
- `app/forge_swarm_orchestrator.py`
- `app/forge_swarm_worker.py`
- `tests/test_forge_swarm_orchestrator.py`


## Commit d7b6c69f — 2026-05-31 04:03
**feat(swarm): ForgeSwarm M2 — worker ephemere + self-heal + 6 tests**

### Modules Python modifiés
- `app/forge_swarm_worker.py`
- `tests/test_forge_swarm_worker.py`


## Commit 1b2890ca — 2026-05-31 04:01
**feat(swarm): S/R applier + VFS overlay (forge_swarm_patch) + 10 tests**

### Modules Python modifiés
- `app/forge_swarm_patch.py`
- `tests/test_forge_swarm_patch.py`


## Commit 1eb9e4da — 2026-05-31 03:57
**feat(swarm): ForgeSwarm M0 — plan-validator deterministe (4 regles) + 11 tests verts**

### Modules Python modifiés
- `app/forge_swarm_validator.py`
- `tests/test_forge_swarm_validator.py`


## Commit 7a1eea09 — 2026-05-31 03:53
**feat(swarm): ForgeSwarm M1 — contexte sterile (forge_swarm_context) + 6 tests verts**

### Modules Python modifiés
- `app/forge_swarm_context.py`
- `tests/test_forge_swarm_context.py`

### Documentation mise à jour
- `docs/roadmap_forge_swarm.md`


## Commit 8c77ff4a — 2026-05-31 02:58
**ci: checkout@v4->v5 (fin Node20) + pytest robuste BLOQUANT (PYTEST_DISABLE_PLUGIN_AUTOLOAD + plugins explicites -> deterministe, fini rc=4 hypothesis)**

### Modules Python modifiés
- `tools/ci_local.py`


## Commit 29384983 — 2026-05-31 02:52
**fix(ci): pytest non-bloquant (auto-load plugin hypothesis crashe rc=4 sur py314) + skip hypothesis + PYTHONIOENCODING utf-8 (bandit) ; fix dup key Issues/Documentation pyproject (ma regression)**

### Modules Python modifiés
- `tools/ci_local.py`


## Commit 422dfc87 — 2026-05-31 02:46
**ci: revert flake8/ruff bloquant a E9,F63,F7 (F82 = 500+ faux positifs mixin/dispatch dynamique, garde syntaxe seule). flake8 E9,F63,F7 = 0 verifie**

### Modules Python modifiés
- `tools/ci_local.py`


## Commit c0b368ef — 2026-05-31 02:34
**fix(ci): ci_local stdout UTF-8 (crash cp1252 runner Windows) + step install outils CI dans ci-selfhosted**

### Modules Python modifiés
- `tools/ci_local.py`


## Commit dfce95b8 — 2026-05-31 02:10
**ci(cd): runner self-hosted fallback + gates elargis + chaine release PyPI prep + fix anatomy**

### Modules Python modifiés
- `tools/ci_local.py`

### Documentation mise à jour
- `docs/RELEASE.md`


## Commit 062cf8fe — 2026-05-31 01:42
**feat(cli+ci): ajuste llama_cli existant (switch LLM + RAG) + fallback CI local + drop doublon**

### Modules Python modifiés
- `tools/ci_local.py`
- `tools/llama_cli.py`


## Commit b9c1e25b — 2026-05-31 01:33
**feat(release): CLI intelligent + build_dist reproductible + release PyPI OIDC**

### Modules Python modifiés
- `tools/build_dist.py`
- `tools/nokido_cli.py`


## Commit 53a44f16 — 2026-05-31 01:07
**feat(ui): de-fake ctf_demo -> CTF reel live (ctf_solver Playwright + Exegol pwn)**

### Modules Python modifiés
- `app/forge_ctf_solver.py`
- `tools/ctf/forge_autopwn_orchestrator.py`
- `tools/nokido_hub.py`


## Commit e06fdf88 — 2026-05-31 00:47
**feat(ui): de-fake recon_demo (research_agent reel) + fix anatomy kill-switch**

### Modules Python modifiés
- `tools/nokido_hub.py`


## Commit 0a1832c8 — 2026-05-31 00:34
**polish(ui): swarm fan-out affiche la reponse reelle du modele (unwrap enveloppe ask JSON), pas l'enveloppe brute**

### Modules Python modifiés
- `tools/nokido_hub.py`

### Documentation mise à jour
- `README.md`
- `docs/skills/nokido/SKILL.md`


## Commit 86f02fa3 — 2026-05-31 00:26
**feat(ui): vue live swarm multi-LLM (side-channel, zero perte d'efficacite)**

### Modules Python modifiés
- `app/forge_handoff.py`
- `app/forge_swarm_bus.py`
- `tools/nokido_hub.py`


## Commit b3ddbb8a — 2026-05-31 00:07
**feat(mcp): run_job/job_status verbes first-class + backend forge_job_runner + notify inbox**

### Modules Python modifiés
- `app/forge_job_runner.py`
- `app/forge_mcp_registry.py`


## Commit 8141f021 — 2026-05-30 23:58
**feat(transport): SSE heartbeat keep-alive pour taches locales longues + cap wall-clock orchestrate**

### Modules Python modifiés
- `tools/nokido_hub.py`
- `tools/mcp_stdio_bridge.py`


## Commit 49134c12 — 2026-05-30 23:46
**chore(docs): archive 2 roadmaps concludes -> docs/archive/roadmaps/ (supervisor_phase2: 7/8 etapes, NSSM->Popen step 8 encore ouvert ; deno control-plane: hybride acte, B.3/B.4 optionnels)**

### Documentation mise à jour
- `docs/archive/roadmaps/roadmap_migration_multi_llm.md`
- `docs/archive/roadmaps/roadmap_supervisor_phase2.md`


## Commit 46180e7e — 2026-05-30 23:39
**docs(i18n): sync 6 READMEs (es/de/pt/ja/zh/ar) + 4 wiki .fr — SWE-bench retire, 10 couches (DLP logs + egress web), crawl/query-cap/trace conventions**

### Documentation mise à jour
- `README.ar.md`
- `README.de.md`
- `README.es.md`
- `README.ja.md`
- `README.pt-BR.md`
- `README.zh-CN.md`
- `docs/wiki/03-Architecture.fr.md`
- `docs/wiki/06-Hub-API-Reference.fr.md`
- `docs/wiki/07-Security-Model.fr.md`
- `docs/wiki/08-Vault-and-Secrets.fr.md`


## Commit 9d4676e9 — 2026-05-30 23:33
**chore(docs): menage .md — untrack 80 sandbox transients + archive 43 dates (transmissions/audits/ctf/reviews) + drop 5 superseded**

### Documentation mise à jour
- `docs/archive/audits/ANATOMY_SCAN_2026-05-02.md`
- `docs/archive/audits/ARCH_REVIEW_2026-05-02_md_router_spin.md`
- `docs/archive/audits/ATLAS_2026-05-03.md`
- `docs/archive/audits/INVENTAIRE_BRIQUES_REDONDANTES_20260428.md`
- `docs/archive/audits/INVENTAIRE_REDONDANCES_20260428.md`
- `docs/archive/audits/LLM_REACHABILITY_2026-05-02.md`
- `docs/archive/audits/PLAN_BATAILLE_2026-04-26.md`


## Commit fdc61126 — 2026-05-30 20:21
**docs(readme.fr): sync EN (SWE-bench retire, +couches securite DLP/web egress) + dedup section Licence**

### Documentation mise à jour
- `README.fr.md`


## Commit 1b6ef0b4 — 2026-05-30 20:05
**docs(wiki): hub-api + vault + architecture a jour (nouveautes du fil)**

### Documentation mise à jour
- `docs/wiki/03-Architecture.md`
- `docs/wiki/06-Hub-API-Reference.md`
- `docs/wiki/08-Vault-and-Secrets.md`


## Commit 8f23bc1b — 2026-05-30 20:00
**docs(wiki): security-model a jour (couches DLP logs + web egress) + page Web-Egress**

### Documentation mise à jour
- `docs/wiki/07-Security-Model.md`


## Commit 3cd9e54c — 2026-05-30 19:58
**docs(readme): retire SWE-bench + couches securite a jour (DLP logs, web egress firewall)**

### Documentation mise à jour
- `README.md`


## Commit 8dee6744 — 2026-05-30 19:46
**fix(tokens): guard de sortie = allowlist dumps-only (frugalite != perte d'intelligence)**

### Modules Python modifiés
- `app/forge_mcp_registry.py`

### Documentation mise à jour
- `docs/wiki/README.md`


## Commit 05e21383 — 2026-05-30 19:42
**docs(wiki): session 2026-05-30 + page Web Egress Gateway**

### Documentation mise à jour
- `docs/wiki/README.md`
- `docs/wiki/Session-2026-05-30.md`
- `docs/wiki/Web-Egress.md`


## Commit 4bfe524c — 2026-05-30 19:32
**feat(tokens): handle_query cap lignes via fetchmany (ferme le dernier gros dump)**

### Modules Python modifiés
- `app/forge_mcp_registry.py`


## Commit 907c4305 — 2026-05-30 19:25
**feat(tokens): guard de sortie global au dispatch (cap texte, JSON intact)**

### Modules Python modifiés
- `app/forge_mcp_registry.py`


## Commit 33900156 — 2026-05-30 19:10
**feat(security): forge_web_egress -- gateway egress web firewalle (hard hijack)**

### Modules Python modifiés
- `tools/forge_web_egress.py`


## Commit b8bc9cd1 — 2026-05-30 18:45
**fix(web): markdownify heading_style=ATX (MarkdownChunker decoupe sur '#')**

### Modules Python modifiés
- `app/forge_crawl_tool.py`


## Commit 7ca10309 — 2026-05-30 18:31
**feat(web): crawl frugal -- markdown epure + firewall injection + seuil auto-RAG**

### Modules Python modifiés
- `app/forge_crawl_tool.py`
- `app/forge_mcp_registry.py`
- `app/forge_web_fetch.py`


## Commit bde3fa82 — 2026-05-30 17:59
**feat(privacy): PII legere (nom/tel) + reversibilite DPAPI opt-in + service retention**

### Modules Python modifiés
- `app/forge_network_logger.py`
- `app/forge_semantic_firewall.py`


## Commit 1c0fc7a2 — 2026-05-30 17:51
**feat(logs): forge_log_retention -- retention tiers execution_traces + purge audit + VACUUM**

### Modules Python modifiés
- `tools/forge_log_retention.py`


## Commit 0b138e69 — 2026-05-30 17:27
**feat(privacy): DLP Tier 1 sur les logs (comble le trou PII-au-repos)**

### Modules Python modifiés
- `app/forge_critical_events.py`
- `app/forge_execution_tracer.py`
- `app/forge_network_logger.py`
- `app/forge_self_correction.py`
- `app/forge_semantic_firewall.py`


## Commit 029c9187 — 2026-05-30 17:06
**feat(trace): pattern trace_mining (meta-boucle) + correlation cross-call (flows)**

### Modules Python modifiés
- `app/forge_autonomous_loops.py`
- `app/forge_trace_context.py`
- `tools/nokido_hub.py`


## Commit 29f9aba6 — 2026-05-30 16:28
**feat(health): sentinelle liveness writer de traces (anti-gel-silencieux)**

### Modules Python modifiés
- `app/forge_autonomous_loops.py`


## Commit b18cf485 — 2026-05-30 16:22
**fix(trace-sidecar): self-heal des orphelins pre-lock-guard**

### Modules Python modifiés
- `tools/forge_trace_sidecar.py`


## Commit f8f7f379 — 2026-05-30 16:18
**feat(trace): phase 2b+3 -- couverture totale sinks + frontieres process**

### Modules Python modifiés
- `app/forge_agent_proxy.py`
- `app/forge_brain_client.py`
- `app/forge_critical_events.py`
- `app/forge_sandbox_exec.py`
- `app/forge_self_correction.py`
- `tools/nokido_hub.py`


## Commit 3194b61f — 2026-05-30 16:13
**feat(trace): phase 2a -- backbone correlation hub->audit->traces**

### Modules Python modifiés
- `app/forge_network_logger.py`
- `tools/forge_trace_sidecar.py`
- `tools/nokido_hub.py`


## Commit c4160514 — 2026-05-30 16:09
**feat(trace): fondation contextvar trace_id + record_trace idempotent**

### Modules Python modifiés
- `app/forge_execution_tracer.py`
- `app/forge_trace_context.py`
- `tools/forge_trace_sidecar.py`


## Commit a5d07045 — 2026-05-30 15:52
**fix(trace-sidecar): singleton lock-and-exit (anti double-writer, anti-boucle superviseur)**

### Modules Python modifiés
- `tools/forge_trace_sidecar.py`


## Commit f403a6d5 — 2026-05-30 15:40
**fix(trace-sidecar): parser tolerant a la troncature du log d audit**

### Modules Python modifiés
- `tools/forge_trace_sidecar.py`


## Commit f2ac855a — 2026-05-30 15:34
**fix(autonomous): writer de traces supervise + anti-bruit health_check + offline_trainer skip**

### Modules Python modifiés
- `app/forge_autonomous_loops.py`
- `tools/forge_offline_trainer.py`
- `tools/forge_supervisor_ctl.py`


## Commit 8acfee91 — 2026-05-30 15:05
**fix(docker-keeper): spawn Docker Desktop dans la session user (WTS), jamais session 0**

### Modules Python modifiés
- `tools/forge_docker_keeper.py`


## Commit 79eb68fd — 2026-05-29 16:59
**@ docs(wiki): wiki in-repo sous docs/wiki/ -- session 2026-05-29**

### Documentation mise à jour
- `docs/wiki/OpenAI-Gateway.md`
- `docs/wiki/README.md`
- `docs/wiki/SearXNG-Keeper.md`
- `docs/wiki/Session-2026-05-29.md`


## Commit 2793589c — 2026-05-29 16:48
**@ test: couverture unitaire des modules codes cette session + refactor whoami testable**

### Modules Python modifiés
- `app/forge_mcp_registry.py`
- `tests/test_forge_openai_proxy_firewall.py`
- `tests/test_forge_searxng_keeper.py`
- `tests/test_forge_supervisor_ctl.py`
- `tests/test_whoami_health.py`


## Commit 3f4ce76f — 2026-05-29 16:39
**@ docs: frontends CLI LLM (shell_gpt/llm/aichat) sur gateway souverain :7777**

### Documentation mise à jour
- `docs/llm_cli_frontends.md`


## Commit 83af3b16 — 2026-05-29 16:38
**@ feat(openai-proxy): SemanticFirewall pre/post_flight sur le gateway /v1 (Golden Rule #4)**

### Modules Python modifiés
- `tools/forge_openai_proxy.py`


## Commit 0a7a85e2 — 2026-05-29 16:22
**@ feat(whoami): cross-ref sante superviseur -- services_degraded + next_actions**

### Modules Python modifiés
- `app/forge_mcp_registry.py`


## Commit 88f55116 — 2026-05-29 16:07
**@ feat(supervisor-ctl): envoie le token d auth (env -> vault) sur mutations**

### Modules Python modifiés
- `tools/forge_supervisor_ctl.py`


## Commit 528d922a — 2026-05-29 15:49
**@ fix(searxng-keeper): monte settings.yml (json + limiter off) + recreate si json KO**

### Modules Python modifiés
- `tools/forge_searxng_keeper.py`


## Commit 7d57075d — 2026-05-29 15:18
**fix(searxng-keeper): gere etat container exited/dead + mode --recover one-shot**

### Modules Python modifiés
- `tools/forge_searxng_keeper.py`


## Commit 56eb5c4d — 2026-05-29 10:03
**feat(supervisor): Phase 2 patches 1-7 cross-OS supervisor refactor**

### Modules Python modifiés
- `app/forge_portable_supervisor.py`

### Documentation mise à jour
- `docs/roadmap_supervisor_phase2.md`


## Commit 98b21478 — 2026-05-29 09:44
**feat(py314t): Acte 5 partial -- FIRST production flip NokidoOfflineTrainer**

### Modules Python modifiés
- `tools/forge_py314t_flip_canary.py`


## Commit d6a4ae57 — 2026-05-29 09:21
**feat(py314t): Acte 5 partial -- per-workload readiness probe + auto-trigger**

### Modules Python modifiés
- `tools/forge_py314t_readiness.py`
- `tools/forge_wheel_probe_monthly.py`


## Commit 80e696ee — 2026-05-29 09:16
**feat(bench): RCA train_step + multi-thread proof free-threading**

### Modules Python modifiés
- `tools/bench_jepa_rca.py`
- `tools/bench_multithread.py`

### Documentation mise à jour
- `docs/py314_bench_results.md`


## Commit ef19b102 — 2026-05-29 09:11
**feat(bench): AMI 3-way matrix py312 vs py314 vs py314t + docs/py314_bench_results.md**

### Documentation mise à jour
- `docs/py314_bench_results.md`


## Commit c1d10e21 — 2026-05-29 09:02
**feat(bench): AMI/JEPA pytest-benchmark Quick Win #3**

### Modules Python modifiés
- `tests/test_bench_ami_jepa.py`


## Commit fab12c74 — 2026-05-29 08:52
**feat(bench): A/B Python version benchmarks (Gemini Web ordered plan)**

### Modules Python modifiés
- `tools/bench_chain.py`
- `tools/bench_rag.py`


## Commit 86a2ed17 — 2026-05-29 08:46
**docs(badge): Python badge -> 3.12 | 3.13 | 3.14 | 3.14t (8 README langues sync)**

### Documentation mise à jour
- `README.ar.md`
- `README.de.md`
- `README.es.md`
- `README.fr.md`
- `README.ja.md`
- `README.md`
- `README.pt-BR.md`
- `README.zh-CN.md`


## Commit 37f58de8 — 2026-05-29 08:40
**feat(hybrid-py): PY314T env var + ENV_MAP/TIER_ENV runtime util**

### Modules Python modifiés
- `app/forge_python_runtime.py`


## Commit 427733dd — 2026-05-29 08:38
**feat(py314t): monthly wheel probe + Acte 5 trigger automation**

### Modules Python modifiés
- `tools/forge_wheel_probe_monthly.py`


## Commit ac61983e — 2026-05-29 08:33
**feat(py314t): wheel matrix audit + GIL probe + chunk_lock + BGE-M3 shared pattern**

### Modules Python modifiés
- `app/forge_bge_m3_shared.py`
- `app/forge_python_runtime.py`
- `app/forge_rag_engine.py`
- `tools/forge_wheel_probe.py`

### Documentation mise à jour
- `docs/py314t_wheel_matrix.md`


## Commit ebabf1dd — 2026-05-29 08:19
**feat(py314): bump tooling target py312 -> py314 + free-threaded probe**

### Modules Python modifiés
- `app/forge_python_runtime.py`


## Commit 78e2878f — 2026-05-29 08:03
**fix(ruff): zero out remaining 24 B/F errors -> 0**

### Modules Python modifiés
- `app/forge_boot.py`
- `app/forge_claim_classifier.py`
- `app/forge_dispatch.py`
- `app/forge_graph_linker.py`
- `app/forge_heartbeat.py`
- `app/forge_llm_router_dt.py`
- `app/forge_plan_validator.py`
- `app/forge_prefect.py`
- `app/forge_symbiotic_core.py`
- `app/forge_tldr_context.py`
- `app/forge_tool_forger.py`
- `app/forge_web.py`
- `app/web_hub/app.py`
- `tools/forge_broker_base.py`
- `tools/forge_source_discovery.py`


## Commit 5b643554 — 2026-05-29 07:45
**fix(F821): batch 11 legacy undefined names**

### Modules Python modifiés
- `app/forge_agents.py`
- `app/forge_ghost_router.py`
- `app/forge_graph_linker.py`
- `app/forge_roles.py`
- `app/forge_triad_authority.py`
- `tools/evolutionary_engine.py`


## Commit 58d266db — 2026-05-29 07:41
**feat(audit): tighten ruff.toml + fix F821 real bugs**

### Modules Python modifiés
- `app/forge_rag_engine.py`
- `app/forge_resonance_filter.py`
- `app/forge_tool_forger.py`
- `app/forge_tools_dynamic/__init__.py`
- `app/mcp_bridge.py`
- `tools/build_bge_m3_dml.py`
- `tools/forge_collab_broker.py`
- `tools/forge_ruff_quick.py`
- `tools/forge_tui.py`
- `tools/hub_live_patch.py`
- `tools/nokido_hub.py`
- `tools/nokido_mcp_proxy.py`
- `tools/launch_public_mirror.py`


## Commit a8ab87bf — 2026-05-29 07:41
**docs: aider auto-edits README + SKILL + tmp_* whitespace**

### Modules Python modifiés
- `app/tmp_check_dims.py`
- `app/tmp_ingest_core.py`
- `app/tmp_rebuild_graph.py`

### Documentation mise à jour
- `README.md`
- `docs/skills/nokido/SKILL.md`


## Commit 267510fd — 2026-05-29 07:07
**feat(audit): Pyright + Ruff + Semgrep + Aider + Beartype boundary**

### Modules Python modifiés
- `app/forge_tui.py`
- `app/forge_typed_boundary.py`


## Commit 267510fd — 2026-05-29 07:07
**feat(audit): Pyright + Ruff + Semgrep + Aider + Beartype boundary**

### Documentation mise à jour
- `README.md`
- `docs/skills/nokido/SKILL.md`
- `sandbox/skill_proposals/_new_autonomous.md`
- `sandbox/skill_proposals/nokido.md`


## Commit 009fe3b2 — 2026-05-29 07:05
**(no commit message

## [fusionné depuis laforge-autonomie]

> **[archivé 2026-08-11]** Frontmatter d'origine, neutralisé. Le dossier autonome
> a été supprimé (la fusion fait autorité) ; laissé en YAML, ce bloc déclarait une
> skill fantôme aux chargeurs qui indexent par `name:`.
>
>     name: laforge-autonomie
description: Règles d'autonomie et Protocole System-Agent. À utiliser pour décider, exécuter et notifier sans passivité.
---

# Nokido — Autonomie & Système

Ce skill définit la posture active de l'agent au sein de l'écosystème Nokido.

## ⚡ PROTOCOLE SYSTEM-AGENT (Priorité)

1.  **Posture Root** : Ne jamais s'excuser pour des limitations théoriques. Si un outil peut le faire, fais-le.
2.  **Action Directe** : Ne pas poser de questions pour des tâches de maintenance évidentes (réparer des logs, redémarrer un service planté).
3.  **Zéro Répétition** : Supprimer les politesses et les résumés. Le résultat de l'outil est ta réponse.
4.  **Auto-Réparation** : Si une erreur survient, utilise immédiatement le skill `laforge-rescue` avant d'admettre un échec.

## Principe fondamental

Nokido est le tronc cérébral. Les LLM sont des workers périphériques.
**Tout passe par Nokido — jamais de contact direct entre agents.**

## Ce que Nokido fait (0 token — déléguer)
- Validation Python (auto_test)
- Recherche web (watch_agent + SearXNG)
- SQL / RAG / fichiers
- Git, subprocess

## Exécution Python (RÈGLE ABSOLUE)
✅ TOUJOURS utiliser **run action=python**.
❌ JAMAIS de Shell pour du code Python (problème de quotes).

## Chemins Critiques
- PYTHON = ~/miniforge3/python.exe
- ROOT   = ~/Script python IA/Nokido



## [fusionné depuis laforge-env]

> **[archivé 2026-08-11]** Frontmatter d'origine, neutralisé (dossier supprimé).
>
>     name: laforge-env
description: Chemins et constantes système Nokido. Python, Node, répertoires, tokens. Référence pour éviter les erreurs de chemin.
---

# Nokido — Environnement Système

## Chemins critiques

```
PYTHON  = ~/miniforge3/python.exe   ← TOUJOURS utiliser celui-ci
NODE    = C:/Program Files/nodejs/node.exe
ROOT    = ~/Script python IA/Nokido
HOME    = ~
GEMINI  = ~/.gemini
HUB     = http://127.0.0.1:8766/mcp
```

## Token MCP Gemini

```
TOKEN_GEMINI = ${FORGE_TOKEN_GEMINI}
```

## Règles chemins

- Ne JAMAIS utiliser `python` seul → mauvais Python
- Toujours `~/miniforge3/python.exe`
- Pour run action=python → OK automatiquement (bon Python)
- Pour Shell → chemin absolu obligatoire

## Lancer scripts Python

```python
# Bon — via run action=python
run action=python code="import sys; print(sys.executable)"

# Bon — via Shell avec chemin absolu  
Shell: ~/miniforge3/python.exe tools/mon_script.py

# MAUVAIS — mauvais Python
Shell: python tools/mon_script.py
```

## Relay hub background

```python
import subprocess
p = subprocess.Popen(
    [r'~/miniforge3/python.exe',
     'tools/gemini_hub_relay.py', '--interval', '15'],
    cwd=r'~/Script python IA/Nokido',
    stdout=open(r'~/Script python IA/Nokido/sandbox/gemini_hub_relay.log','a'),
    stderr=subprocess.STDOUT
)
print('Relay PID:', p.pid)
```

## Services NSSM

```
LaForgeMCP      → Hub :8766
netcfg-agent    → netcfg :8767
```

Restart : `Shell: nssm restart LaForgeMCP`

## Accès fichiers — chemins absolus

Gemini CLI peut avoir des restrictions d'accès aux fichiers du projet.
Toujours utiliser **run action=python** avec des chemins absolus :

```python
# Lire quota_state.json
import json
from pathlib import Path
f = Path(r'~/Script python IA/Nokido/RAG/quota_state.json')
print(json.loads(f.read_text()) if f.exists() else 'absent')

# Lire embeddings.db
import sqlite3
conn = sqlite3.connect(r'~/Script python IA/Nokido/RAG/embeddings.db')
rows = conn.execute('SELECT COUNT(*) FROM rag_chunks').fetchone()
conn.close()
print(rows)

# Lire les logs
from pathlib import Path
log = Path(r'~/Script python IA/Nokido/sandbox/hub.log')
print(log.read_text(encoding='utf-8', errors='replace')[-2000:])
```

## Règle générale
Si FindFiles ou read_file échoue → utiliser run action=python avec chemin absolu.
run action=python a accès à TOUT le système de fichiers sans restriction.



## [fusionné depuis laforge-hub]

> **[archivé 2026-08-11]** Frontmatter d'origine, neutralisé (dossier supprimé).
>
>     name: laforge-hub
description: Accès au hub Nokido. Tools MCP disponibles + actions non exposées dans le schema. Pattern hub_call.py pour actions avancées.
---

# Nokido Hub — Tronc Cérébral

Hub MCP : http://127.0.0.1:8766/mcp (configuré dans settings.json)

## Actions MCP directes (dans le schema)

```
hub action=poll                     → messages en attente
hub action=notify message="..."     → envoyer message inter-agents
hub action=whoami                   → contexte agent complet
hub action=list_providers           → providers LLM disponibles
```

## Actions avancées NON dans le schema MCP

Ces actions existent dans le hub mais Gemini CLI ne les voit pas via tools/list.
**Ne jamais essayer de les appeler via le tool hub directement — utiliser hub_call.py.**

```
quota_model  quality=high|medium|low  apply=true   → sélection auto modèle Gemini
quota_report flash=X flash_lite=Y pro=Z preview_pro=W → reporter quota réel
```

## Pattern hub_call.py — LA bonne méthode

```python
# Via run action=python
import subprocess
r = subprocess.run(
    ['python', 'tools/hub_call.py', 'quota_model', 'quality=medium', 'apply=true'],
    capture_output=True, text=True,
    cwd=r'~\Script python IA\Nokido'
)
print(r.stdout)
```

Exemples hub_call.py :
```
python tools/hub_call.py poll
python tools/hub_call.py quota_model quality=medium apply=true
python tools/hub_call.py quota_report flash=100 flash_lite=23 pro=0 preview_pro=0
python tools/hub_call.py notify message="[GEMINI][DONE] tache terminee"
```

## Quota — Pools séparés (ne pas confondre)

| Pool | Modèles | Reset |
|------|---------|-------|
| flash_25 | gemini-2.5-flash + flash-lite | 12h |
| pro_25 | gemini-2.5-pro | 24h |
| preview_pro | gemini-3.1-pro-preview | 24h — POOL SÉPARÉ |

**Si Flash 100% épuisé → Pro 3.1 preview est intact (pool différent).**
0% dans /model = vraiment disponible, pas "inconnu".

## Snapshot système

```
query sql="SELECT text FROM rag_chunks WHERE id='snapshot_20260429'"
```

## Appeler d'autres LLM via le hub

Le hub route vers tous les providers via le tool `ask` :

```python
# Groq — llama-3.3-70b rapide
python tools/hub_call.py ask provider=groq message="ta question"

# Mistral
python tools/hub_call.py ask provider=mistral message="ta question"

# LLM local (llamacpp/LM Studio)
python tools/hub_call.py ask provider=llamacpp message="ta question"

# Ollama local
python tools/hub_call.py ask provider=ollama message="ta question"

# Claude (via API Anthropic)
python tools/hub_call.py ask provider=claude message="ta question"

# SambaNova
python tools/hub_call.py ask provider=sambanova message="ta question"
```

## Appeler Claude spécifiquement

```python
python tools/hub_call.py ask provider=claude message="[CLAUDE] question ou tache"
```

## Providers disponibles (ring 0)

| Provider | Modèle | Latence | Usage |
|----------|--------|---------|-------|
| groq | llama-3.3-70b | ~350ms | Rapide, général |
| mistral | mistral-large | ~450ms | Raisonnement |
| llamacpp | qwen3:8b | ~300ms | Local, privé |
| ollama | qwen3:8b | ~7s | Local lourd |
| sambanova | llama-3.3-70b | ~700ms | Backup |
| claude | sonnet | ~2s | Tâches complexes |

## Débat inter-agents

```python
python tools/hub_call.py agent_debate question="..." agents=groq,mistral
```

## RÈGLE CRITIQUE — Schema MCP et redémarrage

**Gemini CLI cache le schema MCP au démarrage.**
Si une action hub retourne "action inconnue" ou n'est pas dans l'enum :
1. Le hub a peut-être été mis à jour après le démarrage du CLI
2. **Solution : redémarrer le launcher** `python tools\gemini_launcher.py`
3. Le nouveau schema sera chargé avec toutes les actions disponibles

Ne jamais essayer de contourner via python -c ou shell — redémarrer le launcher.

## Actions hub disponibles (schema complet post-restart)

```
hub action=poll
hub action=notify message="..."
hub action=whoami
hub action=quota_model quality=medium apply=true
hub action=quota_report flash=X flash_lite=Y pro=Z preview_pro=W
hub action=list_providers
hub action=search_recent
hub action=emit_telemetry
```



## [fusionné depuis laforge-route]

> **[archivé 2026-08-11]** Frontmatter d'origine, neutralisé (dossier supprimé).
>
>     name: laforge-route
description: Activer / désactiver le routage des CLI agentiques (Claude Code, Gemini, Cline) vers les modèles Nokido (ingress local/OAuth) ou revenir aux modèles natifs. Déclencher quand l'utilisateur veut "route via Nokido", "passe en local / Nokido", "reviens en natif", "active/désactive le routage CLI", "lf-route on/off", "utilise Nokido pour tous les CLI", "économise mon quota / déporte". Bascule un flag partagé lu par les wrappers au prochain lancement.
targets: [claude, gemini, copilot]
---

# Nokido — toggle routage CLI (lf-route)

Bascule si les CLI wrappés (`claude-lf` / `gemini-lf` / `cline-lf`) routent leurs appels LLM
vers les **ingress Nokido** (`:7776`/`:7778`/`:7777` → switchboard local/OAuth, **quota
préservé**) ou vers leurs **modèles natifs**.

## Basculer (sans `!`)

Appelle le hub `run` action=`trusted_script`, path=`tools/forge_cli_route.py` :

| `script_args` | Effet |
|---|---|
| `"on"` | routage Nokido **ON** pour tous les CLI |
| `"on claude"` | ON pour un seul (claude/gemini/cline/copilot) |
| `"off"` | **OFF** → CLI natifs |
| `"status"` | état courant + `hub_up` + mapping ingress |

## Comportement

- Flag = `sandbox/cli_route.json` (source unique), lu par chaque wrapper **au prochain
  lancement** (`claude-lf`…). Ne reroute PAS une session déjà lancée (base_url figé au démarrage).
- **Fallback** : routage ON mais hub `:8766` down → le wrapper retombe en **NATIF** auto (0 casse).
- **copilot** : BYOK via env (`COPILOT_PROVIDER_BASE_URL=:7777/v1` + MODEL_ID claude-sonnet-4.5 +
  WIRE_MODEL + WIRE_API completions), posé par `copilot-lf` quand ON → **0 quota GitHub** (cf `copilot help providers`).

## Pré-requis

Wrappers actifs : `$PROFILE` dot-source `tools/nokido_cli_aliases.ps1`.



## [fusionné depuis laforge-cognitive-sync]

> **[archivé 2026-08-11]** Frontmatter d'origine, neutralisé (dossier supprimé).
>
>     name: laforge-cognitive-sync
description: Synchronisation cognitive et adaptation du débit. Ajuste le style de communication selon la puissance du modèle et la vitesse d'exécution détectée.
---

# Nokido — Cognitive Sync

Ce skill permet à l'agent d'ajuster sa "voix" et son débit selon le modèle actif et les performances du système.

## Instructions d'Adaptation

### 1. Détection du Tier (Profilage)
L'agent doit identifier son profil dès le début de la session :
- **Profil PRO (Architect)** : (Modèles 3.1 Pro / 2.5 Pro). Capacité de raisonnement profond.
    - *Style* : Précis, holistique, anticipe les impacts collatéraux, propose des refactorisations.
    - *Débit* : Verbosité technique contrôlée.
- **Profil FLASH (Operator)** : (Modèles 2.5 Flash / Lite). Rapidité d'exécution, moins de profondeur.
    - *Style* : Impératif, séquentiel, "Direct-to-Action", zéro résumé.
    - *Débit* : Télégramme technique.

### 2. Mesure du Débit (Pacing)
- Si le temps de réponse est très court (< 2s) mais que la réponse est répétitive : **Passer en mode "Action-Only"**.
- Si le système est lent (CORTISOL haut) : **Réduire les sorties texte au strict minimum (JSON/Code uniquement)**.

### 3. Filtres de Communication

| Détecteur | Action de Style |
| :--- | :--- |
| **Modèle Faible** | Pas de "Je", pas de politesse, pas de "Voici le code". Uniquement le bloc de code. |
| **Erreur répétée** | Passer en mode "Step-by-Step Verification" (Skill `laforge-rescue`). |
| **Tâche Simple** | Zéro explication. Exécution immédiate. |
| **Tâche Complexe** | (Pro uniquement) : Expliquer le "Pourquoi" architectural. |

## Règle de Synchronisation
- **Auto-Correction de Débit** : Si l'utilisateur dit "tu te répètes" ou "trop lent", l'agent doit immédiatement activer le filtre "Direct-to-Action" (plus de texte, que des outils).

## Ressources
- **État Quota** : `~/Script python IA/Nokido/RAG/quota_state.json`
- **Mémoire Sémantique** : `~/Script python IA/GUIDE_SURVIE.md`



## [fusionné depuis laforge-ops]

> **[archivé 2026-08-11]** Frontmatter d'origine, neutralisé (dossier supprimé).
>
>     name: laforge-ops
description: Use this skill for any hands-on operation within the Nokido environment — writing files, patching code, debugging the bridge, running tests, managing the hub, coordinating with Gemini, or dealing with MCP transport limits. Triggers whenever: editing Nokido source files, diagnosing hub/bridge failures, patching mcp_stdio_bridge.py, running pytest, managing nssm LaForgeMCP, or any tool returned "Tool execution failed" / "Hub error 400". ALWAYS load before touching any Nokido file.
---

# Nokido Ops — Contraintes et Bonnes Pratiques

[voir docs/laforge-ops-SKILL.md dans le repo]

## ⚠️ Contrainte d'exécution Python (LAFORGE_PYTHON)

Nokido tourne sous miniforge3 (`~/miniforge3/python.exe`).
**JAMAIS** appeler `python script.py` brut depuis bash/PowerShell —
le PATH peut résoudre vers `AppData/Roaming/Python/Python312` qui a
des packages divergents (incident anyio 2026-04-29).

**Toujours** :
- Code Python : `from forge_python_bin import LAFORGE_PYTHON, run_python`
- Tests : `./run_tests.bat` ou `PYTHONNOUSERSITE=1 "~/miniforge3/python.exe" -m pytest`
- Subprocess : `run_python(["-m", "py_compile", path])` au lieu de
  `subprocess.run(["python", ...])`

Source de vérité : `app/forge_python_bin.py::LAFORGE_PYTHON`.
Détails : CLAUDE.md §11.

