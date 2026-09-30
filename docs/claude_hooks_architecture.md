# Hooks Claude Code — cartographie & architecture (2026-07-30)

Source de vérité du CÂBLAGE : `~/.claude/settings.json` (global) + `<projet>/.claude/settings.local.json`
(projet « Script python IA »). Ce document est la CARTE (humains + agents) ; le câblage réel est
vérifié à chaque démarrage de session par `tools/hook_integrity_check.py` (SessionStart, fail-loud).

Contexte critique : `skipAutoPermissionPrompt` + `skipDangerousModePermissionPrompt` sont actifs
dans le settings global → **aucun prompt de permission de secours. Les hooks sont l'UNIQUE filet.**
Un script hook supprimé/déplacé/cassé = garde morte EN SILENCE (Claude Code ignore un hook dont la
commande échoue). D'où la garde d'intégrité ci-dessous.

## Câblage actif (mesuré 2026-07-30)

| # | Script (`LaForge/tools/`) | Événement | Matcher | Portée | Timeout | Sortie / décision | Mode panne |
|---|---|---|---|---|---|---|---|
| 1 | `forge_tool_gate.py` | PreToolUse | `Read\|Grep\|Glob\|WebSearch\|WebFetch\|Task\|Agent\|Write\|Edit` | global | 5s | `additionalContext` (déport conseillé hub/RAG) ; deny Write/Edit natifs si `LAFORGE_THIN_CLIENT_ENFORCE` | fail-open |
| 2 | `hook_recon_first.py` | PreToolUse | `mcp__laforge-sovereign-hub__.*` | global | 5s | exit 2 (deny) UNE fois/domaine/jour si mémoire non consultée ; consultation (`rag`/`query`/`read_function_body`) marque le domaine | fail-open |
| 3 | `claude_inbox_tick.py` | UserPromptSubmit | `*` | global | 10s | `additionalContext` : digest inbox multi-canal M2M | fail-open |
| 4 | `claude_precompact.py` | PreCompact | `*` | global | 25s | compression contexte avant compaction | fail-open |
| 5 | `claude_session_start.py` | SessionStart | `*` | global | 5s | contexte : règles actives + leçons + inbox | fail-open |
| 6 | `forge_memory_compactor.py --auto` | SessionStart | `*` | global | 8s | memory ledger (versions chaînées) | fail-open |
| 7 | `claude_session_stop.py` | Stop | `*` | global | 3s | note de fin de session | fail-open |
| 8 | `bash_guard.py` | PreToolUse | `Bash` et `PowerShell` (2 entrées) | projet | défaut (60s) | exit 2 deny shell natif → déport `hub run` | deny = fail-closed sur le natif |
| 9 | `hook_bash_compact.py` | PreToolUse | `Bash` (2e hook de l'entrée #8) | projet | défaut | `updatedInput.command` : pipe la sortie dans `forge_cmd_compactor` | fail-open absolu (exit 0 sur exception) |
| 10 | `hook_search_guard.py` | PreToolUse | `Read\|Grep\|Glob` | projet | défaut | exit 2 deny : Read >14 kB sans `limit`/`offset`, Grep `head_limit:0` → déport `read_function_body` / Agent(Explore) | fail-open sur erreur interne |
| 11 | `forge_tool_gate.py` | PreToolUse | `Write\|Edit` | projet | défaut | **DOUBLON EXACT du #1** (même commande, matcher déjà couvert) | — |
| 12 | `session_anchor.py` | Stop | `""` | projet | défaut | ancrage RAG fin de session (diff + résumé) | fail-open |
| 13 | `hook_posttool_validate.py` | PostToolUse | `Write\|Edit` | projet | défaut | exit 2 + message si AST `.py` cassé ou régression held-out prouvée ; silencieux sinon | fail-open |
| 14 | `hook_integrity_check.py` | SessionStart (1er) | `*` | global | 5s | alerte bruyante si un hook câblé est MORT ou ILLISIBLE (3 états, jamais 2) | fail-loud (sa propre panne s'affiche) |

## Chevauchements — verdicts

1. **#11 = doublon exact de #1** : `forge_tool_gate` tourne 2× sur chaque Write/Edit dans ce
   projet. Reco (décision owner) : retirer l'entrée locale `Write|Edit`, le global couvre.
2. **#1 + #10 sur Read/Grep/Glob : COMPLÉMENTAIRES**, pas redondants — tool_gate conseille le
   déport (contexte), search_guard borne le volume (deny). Garder les deux.
3. **#8 + #9 sur Bash** : séquence dans la même entrée `[bash_guard, hook_bash_compact]` — si le
   guard deny (exit 2), le compact est sans objet. Cohérent.
4. **Stop ×2 (#7 global + #12 projet)** : complémentaires (note courte vs ancrage RAG). Garder.
5. **Timeouts absents côté projet (#8–13)** → défaut 60 s. Reco : poser 5 s (borne un hook wedgé,
   cf. doom-loops mesurés ailleurs).

## Scripts hook NON câblés côté Claude Code (état 2026-07-30)

| Script | Destination déclarée | État / décision |
|---|---|---|
| `hook_pretool_guard.py` | PreToolUse `Edit\|Write` — anti-régression ancrée (mean-pooling bge-m3, override `_AGENT`) via `permissionDecision: ask` | **MORT — jamais câblé** (sa docstring dit `settings.local.json`, il n'y est pas). Motif « garde sans émetteur » (RULES_SHARED 2026-07-30). À câbler OU archiver — décision owner. |
| `hook_gate_orchestrator.py` | wrapper CLI (Phase B, log d'intention muet) | vivant hors settings — pas un hook Claude Code |
| `after_model_hook.py` | Gemini CLI (AfterModel) | autre client |
| `quota_hook.py` | Gemini CLI (quota) | autre client |
| `forge_ci_stop_hook.py` | Stop (variante CI) | non câblé — à statuer |
| `claude_capture.py` | capture | non câblé — à statuer |

## Garde d'intégrité (`hook_integrity_check.py`)

SessionStart, PREMIER hook du settings global. Parse les 3 settings (global, projet, projet.local),
extrait chaque `command` de `hooks.*`, vérifie interpréteur + script : existence puis compile
(`compile()` en mémoire — pas `py_compile`, qui échoue sur `__pycache__` en ACL restreinte).
Trois états par cible : **OK · MORT (prouvé absent/SyntaxError) · ILLISIBLE (pas pu regarder ≠ OK)**.
Silencieux-court si tout est vert ; bloc d'alerte en tête de session sinon. Sa propre exception
s'affiche aussi (un vérificateur cassé muet = pire que pas de vérificateur).

Anti-dup : `forge_embolie_scanner._check_hooks_integrity` ne couvre que l'UTF-8 de 2 hooks Gemini
côté corps ; recouvrement quasi nul, d'où module dédié côté client.
