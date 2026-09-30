# Roadmap — idées prises de NousResearch/hermes-agent (veille 2026-06-17)

Corpus en RAG `domain=sdk_gitingest` (+1062 chunks, 44 fichiers). Mémoire :
`veille_hermes_agent_2026-06-17`. **Hermes N'EST PAS adopté** (cherry-pick de motifs
uniquement — directive user). Chaque item = grounded sur le module Nokido PROPRIÉTAIRE
(anti-dup PRÉFILTRANT §3 : étendre l'existant, ne pas recréer).

| # | Idée hermes | Module propriétaire Nokido | Verdict | Statut |
|---|---|---|---|---|
| 1 | `hermes_bootstrap` UTF-8 | `forge_python_bin` + `forge_utf8_bootstrap` (NOUVEAU) | **BUILD** | ✅ **DONE** dcd1eb1c |
| 2 | provenance cross-compaction | `tools/forge_session_provenance.py` (NOUVEAU) + `claude_precompact.py` | **BUILD** | ✅ **DONE** `9568d287` |
| 3 | RPC-from-script delegation | `forge_orchestrate_loop._hub_dispatch` + `orchestrate(task,tools)` + `forge_workflow` | **DÉJÀ COUVERT** | exposer/enseigner (pas de module) |
| 4 | `RedactingFormatter` (secrets jamais sur disque) | `tools/forge_log_redact.py` (NOUVEAU) + `Nokido.py` handlers | **BUILD** (net-new) | ✅ **DONE** `a6128ee4` (s'active au reload Nokido.py) |
| 5 | `events_wait` (attente jobs) | `tools/forge_events_wait.py` (NOUVEAU) sur `forge_job_runner.read_job` | **BUILD** (script-side, PAS verbe hub = anti-wedge) | ✅ **DONE** `c6d1be04` |
| 6 | `background_review` auto-skill/memory post-turn | `tools/forge_background_review.py` (NOUVEAU) + `claude_session_stop.py` ; RÉUTILISE `forge_self_correction`+`forge_skill_forge` ; LLM LOCAL | **BUILD** | ✅ **DONE** `b8b3b4ee` |
| — | hermes comme daemon multi-canal | — | **OPTIONNEL, DÉCLINÉ** (user: « j'en veux pas ») | non construit |

## Détails build

### #1 UTF-8 (DONE)
`forge_utf8_bootstrap.apply()` pose `PYTHONUTF8=1`/`PYTHONIOENCODING=utf-8` process-wide
(hérités par enfants) + reconfigure stdio ; `child_env()` pour subprocess à env explicite.
`run_python`/`popen_python` injectent `child_env`. Racine corrigée : le `reconfigure` éparpillé
fixait le PARENT, pas les ENFANTS → mojibake « Ã©levÃ© ». Prouvé : child stdout UTF-8 exact.
**Reste (optionnel) :** importer `forge_utf8_bootstrap` EN PREMIER dans les hooks/entrypoints
qui impriment (claude_precompact.py, hooks session) pour couvrir les chemins hors `run_python`.

### #2 provenance cross-compaction (USER-VALUE : /compact)
Dériver une chaîne `parent_session_id` → `child` à chaque compaction (comme hermes `provenance.py`
dérive de `parent_session_id`/`end_reason`), handle public stable pendant que le head interne tourne.
Étendre `forge_session_anchor`/`claude_precompact` pour écrire le lien parent→enfant en DB session
→ une session compactée reste retrouvable/continue (réduit la perte de contexte = moins de
ré-injection = moins de 529). Pas de nouveau store.

### #4 RedactingFormatter
`logging.Formatter` qui masque secrets (patterns vault/clé/token) avant écriture disque, branché
sur les handlers existants (`_text_handler` & co dans `Nokido.py`/boot). Défense-en-profondeur
(complète vault DPAPI). HOT file → claim + edit chirurgical + reload coordonné.

### #5 events_wait long-poll
Verbe bloquant (cap borné) qui attend un événement inbox/job au lieu du poll `job_status` répété.
Étendre `_watch_job` (déjà asyncio sur `.rc` + INBOX.push) en exposant un `wait`. Règle le poll
manuel + le bug fan-out connu (un poller draine la notif des autres).

### #6 background fork-review (USER-VALUE : amnésie/529)
Sur Stop-hook : fork un agent LOCAL (qwen, 0 token Claude) qui rejoue le snapshot de tour et décide
« anchor_solution / créer-màj skill ? », écrit dans `forge_self_correction` + skill store.
Prompt-cache jamais touché. RÉUTILISE `forge_self_correction` (=MemGPT, interdit de reconstruire) +
pool local + `forge_skill_sync`. = auto-persistance des compétences sans brûler Claude.

## Méthode (chaque item)
Anti-dup 3 étapes (rag_fts + [[liens]] + read module) → claim `tree_locks` → edit gouverné
(Edit natif, AST auto-validé PostToolUse) → test déporté `run_job` → commit petit (pas `-A`,
pas de signature Claude) → release lock. Reload hub coordonné (`nokido_stop.ps1` puis
`nokido_start.ps1`, owner) groupé en fin, pas par item.
