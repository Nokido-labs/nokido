# Fiche de sortie — Veille V1 « Supervision / résilience » + « Agents longue durée » (2026-09-23)

Contrat : PATTERN → DÉJÀ DANS NOKIDO → GAP → EXPÉRIENCE MINIMALE → NR → DÉCISION. Cette fiche PROPOSE.

## 1. Patterns (`watch:supervision:%`, `watch:agents_longs:%`, `watch:homeostasie:%`)

| Pattern | Source primaire |
|---|---|
| Arbre de supervision : stratégies `one_for_one` / `one_for_all` / `rest_for_one` ; **intensité de redémarrage** (MaxR redémarrages en MaxT s) au-delà de laquelle le superviseur ABANDONNE et remonte | Erlang/OTP `sup_princ` ; Akka fault tolerance |
| Circuit breaker : `closed → open → half-open` ; stopper les appels vers un organe en panne au lieu de l'achever | Azure pattern circuit breaker |
| Reprises : budget borné + backoff + jitter ; les reprises AMPLIFIENT la surcharge (boucle de rétroaction) | Azure retry ; AWS backoff/jitter ; AWS délestage (FR) ; SRE surcharge/cascades |
| Santé : liveness ≠ readiness ≠ startup ; boucle de réconciliation état désiré ↔ état réel | Kubernetes probes, controller ; Azure health endpoint |
| Agent longue durée : état HORS contexte (fichier de progrès, liste de fonctionnalités), reprise incrémentale, checkpoints avec *pending writes* (ne pas ré-exécuter ce qui a réussi) | Anthropic harnesses / context engineering ; LangGraph checkpoint README |
| Compensation (saga) quand une étape échoue après que d'autres ont réussi | Azure compensating transaction ; microservices.io saga |

## 2. Ce que Nokido possède DÉJÀ (`introspect` + mémoire datée, à revalider)

- `supervisor.ts` (Deno) : services, respawn, phases circadiennes ; `forge_portable_supervisor.Supervisor.watchdog` ;
  `forge_mcp_registry` : watchdog de boucle armé (03/09).
- `forge_health_diagnostic.run_cycle()` (0 import statique, INVOQUÉ par `run_job` : vivant).
- `forge_chain_executor` : reprise du crawl par URL + deadline globale de chaîne (PROUVÉ 30/08).
- `forge_proposal_applier` (« réflexe médullaire vs décision corticale ») : chaîne proposer→appliquer EXISTANTE mais
  **non câblée + désarmée** (mémoire 22/09) ; `self_improvement_watch` : 742 tirs, un soin persiste 115 cycles
  (*observer ≠ réparer*).
- Régulation RAM : `request_resources` (échelle d'éviction) ; admission `run_job` (refus « embolie RAM ») ; caps RSS.
- Doctrine : `TRANSPORT ≠ APPLICATIF ≠ CAPACITÉ`, `STALE ≠ DEAD`, `BLOQUE_PAR_DEPENDANCE ≠ DEAD` (constitution).
- Mesuré AUJOURD'HUI : 6 jobs tués/arrêtés (RSS, verrou, disque) relancés À LA MAIN ; le WAL affamé par un lecteur
  n'a été libéré que par un redémarrage manuel du hub.

## 3. Gaps

1. **Intensité de redémarrage non vérifiée** : un respawn en boucle (« respawn refusé 11× », 16/07) prouve un garde, mais
   la règle MaxR/MaxT et la remontée au niveau supérieur ne sont pas établies comme un contrat unique.
2. **Pas de circuit breaker nommé** entre le hub et ses organes (embedder, qdrant, providers) — à VÉRIFIER dans
   `forge_agent_proxy` avant d'affirmer l'absence.
3. **Reprise de job non automatique** : un job tué (RSS, verrou, disque) n'est ni relancé ni reprogrammé ; l'état de
   reprise existe (INSERT OR IGNORE, READY sautés) mais personne ne le déclenche.
4. **Famine de checkpoint** : aucun organe ne détecte « un lecteur tient le WAL depuis N minutes » (vu : 4 h).
5. Agents longs : pas d'état de progrès HORS contexte pour une campagne (aujourd'hui : fichiers `C:/tmp`, mémoire
   manuelle) — c'est exactement ce que la mémoire de session a dû compenser.

## 4. Expériences minimales proposées

- (a) Lire le code de respawn de `supervisor.ts` : extraire la règle réelle (MaxR/MaxT ?) — lecture seule.
- (b) Sonde « famine WAL » : âge de la plus vieille transaction de lecture / taille WAL vs `wal_checkpoint` busy répétés
  → signal endocrine, pas d'action (observer avant d'enforcer).
- (c) Reprise de job : un job qui meurt avec `rc ∈ {137, 4, 5}` et une commande idempotente est RE-PROPOSÉ (pas relancé)
  au propriétaire — cf. `forge_proposal_applier`, ne pas en écrire un second.

## 5. NR candidats

`test_supervision_intensite_redemarrage_nr` (règle MaxR/MaxT explicite) · `test_famine_wal_signalee_nr` (lecteur
long simulé ⇒ signal émis) · `test_job_idempotent_repropose_nr`.

## 6. Décision attendue (owner)

- [ ] Autoriser (a) et (b) (lecture/observation seules).
- [ ] (c) : dépend de l'armement de `forge_proposal_applier` (geste owner, 22/09).
