# Cowork Internalisation — Design (panel multi-LLM 3 tours, 2026-06-09)

Internaliser un **"Cowork" souverain** dans Nokido : collègue IA persistant qui bosse en
arrière-plan sur des projets, workspace partagé, prend l'initiative (bornée), et remonte le
travail pour **revue/approbation async**. On **compose les organes existants** ; le neuf se
réduit à **3 pièces** (2 prévues + 1 imposée par la passe adversariale).

Méthode : panel free-tier souverain (groq-70b, cerebras-120b, mistral-large) — R1 diverge,
R2 critique/raffine, R3 adversarial. Convergence forte + 1 angle mort prod majeur.

## Contraintes (dures)
Souveraineté (data locale ; cloud uniquement via SemanticFirewall). Éco-tokens (LLM free-tier
via hub, exécution **déportée**). **Réutiliser > reconstruire.**

## Organes réutilisés (le câblage)
| Brique | Organe |
|---|---|
| Backlog async + notify | `forge_task_queue` + `forge_mailbox` |
| Mémoire travail partagée | `forge_swarm_blackboard` (zoné, mono-writer asyncio.Lock) |
| Plan + exécution | `orchestrate`/`plan` (GOAP, planning `<think>` gate) + `forge_spawn_swarm` |
| Approbation humaine | `forge_meta_tools._queue_for_approval` (promotion_queue) + integrity rings |
| Checkpoint CODE | `forge_loop.post_loop_safe_check` (ZIP+AST+merge/rollback) — **code-only** |
| Daemon supervisé | `services.toml` / LaForge-Master (heartbeat, reboot-survival, hot-add) |
| Visibilité live | Observatory :7600 / anatomy :7400 / swarm_bus SSE |
| Exposer comme agent | `forge_acp_adapter` (backend ACP → Zed/terminal) |

## Pièces neuves
1. **CoworkProject** — entité persistante (SQLite-WAL).
2. **NokidoCowork** — daemon supervisé (la boucle coworker).
3. **checkpoint_writer** — daemon d'écriture **découplé** (IMPOSÉ par R3, voir §risque).

## Décisions verrouillées (panel)
1. **Rebind `project_id` au niveau wrapper** : `project_id TEXT NULL DEFAULT 'system'` ;
   filtre `WHERE project_id = ? OR project_id IS NULL`. Appels legacy → scope `system`,
   **0 rupture**. Migration = add column + index, pas de redéploiement.
2. **Scheduler = PARK-and-continue** : tâche irréversible → état `awaiting_approval`, le daemon
   **continue les autres** tâches/projets ; reprise sur **événement** `approval_received`
   (ACP/SSE). **Jamais de timeout-reject** (le travail n'est jamais gelé ni abandonné). FIFO
   par projet + round-robin intra-projet.
3. **Checkpoint généralisé, type-dispatché** : `code` → `post_loop_safe_check` (ZIP+AST+diff) ;
   `doc`/`research` → tar/zip des artefacts + `summary.json` + sha256. Rollback via `state_hash`.
   (`post_loop_safe_check` = **mauvais outil** hors code → ne pas l'imposer aux tâches non-code.)
4. **Écritures checkpoint DÉCOUPLÉES du mono-writer** (R3) : artefacts → **fichiers locaux**
   (`sandbox/cowork/<project_id>/`) ; seul un **résumé léger** `{sha256, path, meta}` poussé au
   hub via `event_stream` ; daemon `checkpoint_writer` dédié + `asyncio.Queue(maxsize=N)` +
   backpressure. GOAP intègre un coût d'écriture.
5. **Initiative bornée** (skill `laforge-cowork-propose`) : `scope ⊆ context_refs`,
   `cost ≤ budget`, `risk ≤ threshold`, `max_tasks` ; réversible → auto, irréversible →
   **validé par l'humain AVANT** entrée au backlog. Hard limits (max_tasks/projet, max_runtime/tâche).
6. **Approbation async** : `_queue_for_approval` + `mailbox` notify + ACP ; réversible → auto.

## Schéma `cowork_projects`
```sql
CREATE TABLE cowork_projects (
  id TEXT PRIMARY KEY,
  goal TEXT NOT NULL,
  context_refs TEXT NOT NULL,          -- JSON {"files":[], "notes":[]}
  backlog TEXT NOT NULL,               -- JSON [{"id","description","type","reversible"}]
  review_thread TEXT,                  -- ACP session_id
  status TEXT NOT NULL CHECK (status IN ('idle','running','awaiting_approval','completed','failed')),
  created_at REAL DEFAULT (unixepoch()),
  updated_at REAL
);
CREATE INDEX idx_cowork_status ON cowork_projects(status) WHERE status IN ('running','awaiting_approval');
```

## Boucle coworker (NokidoCowork daemon)
```
loop:
  proj = next_active_project()                      # FIFO idle/running
  task = task_queue.claim(project_id=proj.id)       # wrapper filtré
  if not task: yield; continue
  plan = plan(goal=task, ring_max=2)                # GOAP + <think> gate
  result = spawn_swarm(plan)                         # LLM local
  artifact = write_local(proj.id, result)           # FICHIER local (pas le mono-writer)
  if task.irreversible:
      _queue_for_approval(...) ; mailbox.notify(proj.id, "awaiting") ; proj.status=awaiting_approval
      PARK proj ; continue                           # ne bloque pas
  checkpoint_writer.enqueue({sha256, path, meta})    # résumé léger -> hub (queue bornée)
  digest -> review_inbox (swarm_bus SSE + acp.session_update)
  proj.backlog.append(propose_next(proj))            # initiative bornée (opt-in)
on event approval_received(proj): resume(proj)
```

## #1 risque prod (R3, unanime) + parade
**Contention mono-writer SQLite-WAL → cascade quarantine.** Écritures checkpoint lourdes sur le
verrou partagé (hub + blackboard + autonomous_loops/evolution) → back-pressure → daemons en
restart → quarantine >10/hr → firewall bloque pendant la contention. **Parade = décision #4**
(artefacts fichiers + résumé léger + writer dédié + backpressure). **Baked dans P1.**

## P1 PoC (minimal dé-risqué)
- 1 `CoworkProject` (goal "draft README"), **1 tâche doc RÉVERSIBLE**, auto-approve.
- Chaîne : backlog → `plan` (GOAP) → `spawn_swarm` (1 LLM local) → artefact **fichier local** →
  résumé léger (sha256+path) au hub → digest review inbox (Observatory SSE + ACP `session.update`).
- **100% local.** Prouve : entité projet + boucle + checkpoint généralisé (chemin doc) + writer
  découplé + digest, end-to-end, **sans toucher le hot-path mono-writer**.
- Réutilise le pattern daemon-supervisé + single-instance guard + heartbeat (cf
  `NokidoTraceCollectorRich`, livré 2026-06-09).

## Phasage
- **P1** — `forge_cowork.py` (CoworkProject + boucle + checkpoint dispatcher + write_local) +
  service `NokidoCowork` (services.toml) + rebind `project_id` (default `system`) sur
  task_queue/mailbox + checkpoint_writer. PoC doc-only.
- **P2** — approbation gated (irréversible) + scheduler multi-projet park/resume + digest standup.
- **P3** — initiative bornée (skill propose) + checkpoint code (post_loop_safe_check) + rollback.
- **P4** — exposition ACP (hôtes Zed/terminal co-bossent) + intégration trust rings/firewall complète.

## Souveraineté / éco
Local-first (LLM free-tier via hub, 0 token/min facturé), data dans membrane/RAG, exécution
déportée (la boucle vit dans un daemon supervisé, pas dans le client). ~90% = organes existants.
