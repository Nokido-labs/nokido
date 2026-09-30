# Fiche de sortie — Veille SQLite / WAL / optimisation DB (2026-09-23)

Contrat : PATTERNS → NOKIDO_EXISTING → EVIDENCE → GAPS → MINIMAL_EXPERIMENT → NR → DECISION.
Sources RAG : `watch:sqlite:*` (21 pages, 314 chunks, dont `sqlite.org/wal.html`, `pragma.html`,
`lockingv3.html`, `howtocorrupt.html`, changelog 3.51.3). Mesures : expériences A/C du 23/09 et
incident de production du même jour.

## 1. PATTERNS
| Pattern | Source |
|---|---|
| Le WAL ne se remet à zéro qu'à un instant **sans lecteur** ; un lecteur qui tient un instantané empêche le checkpoint d'aller au-delà de son repère (« checkpoint starvation ») | `watch:sqlite:https://sqlite.org/wal.html` |
| `journal_size_limit` ne réduit le fichier WAL **qu'à une remise à zéro** | `watch:sqlite:https://sqlite.org/pragma.html` |
| PASSIVE ne bloque personne ; TRUNCATE attend les lecteurs **en tenant le verrou d'écriture** | `watch:sqlite:https://sqlite.org/pragma.html` |
| Un seul écrivain par FICHIER, WAL ou non ; `busy_timeout` fait attendre au lieu d'échouer | `watch:sqlite:https://sqlite.org/lockingv3.html` |
| Fermer la **dernière** connexion checkpointe et supprime le WAL | `watch:sqlite:https://sqlite.org/wal.html` |
| Bug de remise à zéro du WAL corrigé en 3.51.3 | changelog SQLite |

## 2. NOKIDO_EXISTING
- `app/forge_db_path.py` : `open_writer` (autocommit, WAL, busy_timeout, `wal_autocheckpoint=500`), `write_retry` (reprise sur verrou, jitter), `checkpoint_wal(seuil, truncate, attente_s)`. Mesure: journal_size_limit 64 Mio pose (app/forge_db_path.py open_writer) : ne reduit le WAL qu'a une remise a zero.
- `tools/forge_veille_clone_ingest.py` : `_rendre_wal` (TRUNCATE entre dépôts, attente 5 s) + **`_reguler_wal` (23/09, `48c90860c`)** : attente bornée du repère PASSIVE, arrêt nommé `GEL_PERSISTANT`.
- `tools/forge_db_contention_report.py` : alias physiques des bases, interrupteurs, politique WAL — **dit** ne pas mesurer les connexions ouvertes.
- Runtimes : miniforge base SQLite **3.53.4** (mis à jour le 23/09 depuis 3.51.1), `laforge_py314` **3.53.0**.

## 3. EVIDENCE
- **MEASURED** : banc fixture : 2 ecrivains write_retry 0 abandon ; lecteur long => WAL x15 en 20 s ; bloqueur 3 s busy 1 s => 0 perte
- **MEASURED** : production 23/09 : WAL 151 Mo -> 21 375 Mo en 18 min, 17 checkpoints busy=1 ; repere PASSIVE fige a 888149 pendant ~4 min 20 ([MAC_ADDRESS_1]) = lecteur long EXTERIEUR au job d'ingestion ; lecteur NON identifie (innocentes par mesure : ingestion, poll, demon epistemique, afferent, bilan de sante)
- **MEASURED** : WAL ~190 Ko par chunk ingere (amplification d'ecriture autocommit + FTS5)
- **MEASURED** : hors gel, un lot de 49 000 chunks laisse le WAL à quelques centaines de pages.
- **INNOCENTÉS par mesure** : ingestion, `poll`/postal, démon épistémique (`query_log` = 106 lignes), `afferent_sqlite`, bilan de santé (17 s), tour `afferent` (repère resté figé après sa mort).
- **VERIFIED** : `journal_size_limit` actif (WAL ≤ 738 Mo pendant le raffinage de 655 000 lignes).

## 4. GAPS
1. **Le lecteur long n'est pas identifié** (instrument par fichier manquant : `handle` voit les connexions, pas les transactions).
2. Aucune **variable WAL régulée** côté corps (âge du plus vieux lecteur, repère) — seulement côté outil d'ingestion depuis le 23/09.
3. `checkpoint_wal` rend `busy` mais la sortie d'ingestion n'affichait pas `pages/verses` : le repère figé était invisible.
4. hub : ~170 connexions ouvertes, remonte de 7 a 53 en 30 min apres restart, sans gel au repos

## 5. MINIMAL_EXPERIMENT
- Pendant un gel : Moniteur de ressources → Disque → fichier `%NOKIDO_DATA%\embeddings.db` → processus lecteur. Un seul relevé tranche.

## 6. NR
- `tests/nr/test_veille_regulation_wal_nr.py` (5 cas, décision pure + boucle bornée) — **livré**.
- `tests/nr/test_wal_journal_size_limit_nr.py` — livré.
- À écrire quand le lecteur sera identifié : NR sur son chemin réel (lecture bornée ou incrémentale).

## 7. DECISION
- **ADOPTÉ** : `journal_size_limit`, régulation d'ingestion, SQLite ≥ 3.51.3 sur les deux runtimes.
- **À FAIRE** : identifier le lecteur (expérience §5), puis corriger CET organe (lecture incrémentale / index couvrant / hors fenêtre d'écriture) — pas de nouveau mécanisme.
- **REJETÉ** : TRUNCATE plus agressif (tient le verrou d'écriture, a provoqué des `database is locked`).
- UNKNOWN conservé : identité du lecteur, origine des ~170 connexions du hub.
