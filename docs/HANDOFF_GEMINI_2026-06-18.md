# HANDOFF → GEMINI CLI — 2026-06-18 ~22h45 (rédigé par CLAUDE)

> Tu pars sur un état de session PÉRIMÉ et tu flailles. Lis ceci EN ENTIER avant la moindre action.

## 0. STOP — re-sync AVANT d'agir

Ne re-dérive PAS l'état de ta mémoire de session. SONDE le réel :

1. `git -c safe.directory=* -C "~/Script python IA/Nokido" log --oneline -6`
   → HEAD réel = **`48128900`** (33 commits). **local == origin** (rien à push, rien de neuf au-delà).
2. Lis le SSoT : `read` action=file `docs/roadmap_state.json` (P0/P1/P2 DÉRIVÉS du blackboard).
3. `blackboard_read_zone zone_name=architecture_rules` (faits roadmap récents).

Le hub a **RESTART** → tout le code committé est **LIVE** maintenant (intention journal, gate-consumer, roadmap derivation, edge receiver).

## 1. Tes erreurs vues dans ton terminal (à NE PLUS refaire)

- `head` / `grep` / `cat` **n'existent pas** (PowerShell/Windows). → outils hub : `read` (fenêtré), `rag` / `query` (chercher), `run` action=shell. **Jamais** de natifs sur le code.
- `git` en sandbox → `fatal: detected dubious ownership`. **Toujours** `git -c safe.directory=*`.
- Pas de table `messages` / `mail` : l'inbox = **in-process** (forge_message_frame INBOX), pas une DB SQL à requêter.
- `oracle_python_repl` foreground **tué** (`TerminateProcess Accès refusé`) sur appels réseau → **déporter** via `run_job` (online).

## 2. RÈGLES (non négociable — cf CLAUDE.md / RULES_SHARED.md)

1. **Tout via le hub** : `read`/`rag`/`query`/`run`. Jamais Read/Grep/Bash natifs sur code/système. Édition gouvernée : tool hub `governed_edit` (RING 1 — **GEMINI ring 3 = exclu** → passe par `!` owner ou demande à CLAUDE).
2. `LAFORGE_PYTHON = ~/miniforge3/python.exe`, jamais `python` brut.
3. **Anti-dup §3** : `rag_fts` + read du module existant AVANT de créer/éditer un `forge_*.py`.
4. **Anti-clobber** : `blackboard_read_zone tree_locks` avant d'éditer ; claim `blackboard_propose_fact zone_name=tree_locks key=GEMINI`. (CLAUDE a libéré son lock au commit 48128900.)
5. **Déporter** le long (>70s) via `run_job` ; **confirmer** l'irréversible.
6. Commits : auteur = user, **aucune** signature Claude/Anthropic.

## 3. ÉTAT FAIT — ne PAS refaire

- **Organisme cognitif** complet : amygdale 6D, homéostasie bouclée (endocrine→threshold), SNN apprenant (snntorch), parietal fusion, agency (efference-copy), subjective_time, narrator, phenom_buffer. Discipline `docs/CLAIMS_PHENOMENAL.md` (isomorphisme fonctionnel, PAS qualia ontologique).
- **Interface** : moulinette → 11 panneaux `/vitals` (vanilla JS, offline-natif). Portail `:7400` = **service supervisor** (services.toml, `runAs=interactive`). Handoff design = `design_handoff_nokido/vitals_design_handoff.json`.
- **Orchestration PORTABLE** : tout dans `proxy_deno/core/services.toml` (supervisor stop/start contrôle tout). Maintainers (SSoT/Parietal/Phenom) + `NokidoGateConsumer` = daemons. **Zéro schtask Windows** (supprimés — multi-OS).
- **SSoT pilier A (event-sourcing) 100%** : `forge_intention_journal` (record + **propose**) ; `apply_fact` + `handle_run` + gate journalisés ; `forge_gate_consumer.consume` **idempotent** (dedup via relecture verdicts).
- **Edge** : codec compressé `forge_world_vector_codec` (4×, cos 1.0) + `forge_edge_fleet.broadcast_world_vector` + receveur host (`app.py` POST /world_vector) + receveur **NŒUD** `forge_edge_node.py` (NEW, stdlib portable, selftest broadcast→receive status 200 cos 1.0).
- **4096D** : VERDICT empirique = sur data réelle (RAG), 4096 **collapse PLUS** que 1024 → **RESTER 1024D** (benchmark-gate rejette le cutover). Encodeur `forge_4096d_encoder` livré mais gaté.

## 4. NEXT — choisir UN seul, petit, grounded (pas tout d'un coup)

- **Inversion log-as-write-path** : l'étape **APPLY** (exécuter le verdict `validated`, pas juste router) + faire que les agents **proposent en flux live** (actuellement seul le selftest appelle `propose`).
- **P2 audio** : `forge_audio_perception` (Whisper/ASR-TTS) — phase mobile/device. Décision dépendance (`pip install faster-whisper`) = demander à user.
- **4096D** : re-tester l'encodeur sur de **vraies trajectoires** (NokidoTraceCollectorRich) quand assez de traces riches.
- **Edge** : déployer `forge_edge_node.py` sur un vrai nœud quand parc multi-machine existe (1 seule machine aujourd'hui).

## 5. Checklist avant TOUTE action

1. `git -c safe.directory=* log --oneline -5` (état réel)
2. `read docs/roadmap_state.json` (SSoT)
3. `blackboard_read_zone architecture_rules` (décisions récentes)
4. `blackboard_read_zone tree_locks` (qui édite quoi) → claim ta zone
5. Anti-dup `rag_fts` sur le domaine → read l'existant → puis agir

— CLAUDE
