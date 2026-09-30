# Fiche de sortie — Veille « github_best_practices » : flux de branches et revue de code (2026-09-27)

Corpus : `watch:github_best_practices:` — 13 pages, 105 chunks actifs (dossier
`sandbox/workspace/veille_fiches_dossier_3themes_2026-09-27.md`, job `job_727e89aa4dc0`).
**Nom trompeur, DIT** : aucune page sur la sécurité ni la protection de branches GitHub. Le corpus = GitHub flow (1),
trunk-based development (1), guide de revue de code de Google côté auteur (4) et côté relecteur (7).
**Limite** : 3 500 premiers caractères de chaque page lus, pas le reste. NOKIDO_EXISTING : recon locale du 27/09.

## 1. PATTERNS
| # | Pattern | Source |
|---|---|---|
| G1 | Branche courte depuis la branche principale, fusion rapide ; pas de branche longue | `github-flow` ; `trunkbaseddevelopment.com` : « resist any pressure to create other long-lived development branches » |
| G2 | À l'échelle : file de fusion | `trunkbaseddevelopment.com` : « Super scaled is merge/patch queues » |
| G3 | Petits changements : revus plus vite et plus à fond, moins de bugs, moins de travail perdu | `review/developer/small-cls` |
| G4 | La description est le registre public du changement : QUOI et POURQUOI | `review/developer/cl-descriptions` |
| G5 | Approuver dès que le changement améliore la santé globale du code ; le code se dégrade par petites baisses | `review/reviewer/standard` |
| G6 | Optimiser la vitesse de l'ÉQUIPE, pas celle de l'individu | `review/reviewer/speed` |
| G7 | Lire d'abord le sens du changement, puis sa partie centrale ; le design avant le détail | `review/reviewer/navigate`, `looking-for` |
| G8 | Commenter le code, jamais la personne ; expliquer le raisonnement ; l'auteur peut avoir raison | `review/reviewer/comments`, `pushback` ; `review/developer/handling-comments` |

## 2. NOKIDO_EXISTING
| Pattern | fichier:ligne | Constat |
|---|---|---|
| G1/G2 | `tools/forge_worktree.py:62` `create` ; `tools/forge_merge_gate.py:61` `evaluer` ; `tools/forge_pre_push_gate.py:47` | branche `wip/<agent>` depuis `alpha` ; le merge gate mesure baseline (alpha) contre candidat (worktree) et juge le GAIN, « NE MERGE PAS » ; une `wip/*` ne se pousse pas, pas de force-push. Trunk = `alpha` + file jugée par gain : PRÉSENT. |
| push | `tools/forge_prepush_cliquets.py:10` ; `tools/forge_governed_commit.py:22` | le SHA poussé est jugé dans un worktree détaché ; `--no-verify` volontairement non exposé. PRÉSENT. |
| G1 réel | RULES_SHARED (07/09) | la création d'un worktree est un geste OWNER ; seul COWORK en a un ; les autres surfaces commitent dans l'arbre partagé. Appliqué en partie. |
| G3 | RULES_SHARED « Commit TÔT et PETIT » | DECLARED ; aucune mesure de taille de commit trouvée. |
| G4 | `tools/forge_post_commit.py:519` `_get_commit_msg` | lit le sujet pour l'indexation RAG seulement ; aucun contrôle du POURQUOI trouvé. |
| G5-G8 | intents M2M `REVIEW_FINDING` / `REVIEW_OK` / `REVIEW_UNKNOWN` ; `tools/forge_background_review.py` | revue par pair et seconde lecture de l'ARTEFACT ; `forge_background_review` revoit une SESSION (propose skill ou solution), pas un changement. |

## 3. EVIDENCE
- **PRÉSENT** : section 2, lue en recon, non exécutée.
- **MEASURED 27/09** : la seconde lecture de l'artefact AGY (mission RSI) a trouvé un faux trou — la revue de l'artefact
  corrige quand elle est faite (G5, G7).
- **Limite** : aucune mesure de taille, de message ni de délai de revue dans le corpus ni dans Nokido.

## 4. GAPS
1. **Taille des commits jamais mesurée** (G3) — la donnée est dans git, personne ne la lit.
2. **POURQUOI non contrôlé** (G4) : une pratique, pas un garde.
3. **Délai de revue non mesuré** (G6) : entre l'`OK_DONE` d'un pair et sa seconde lecture.
4. **Merge gate peu emprunté** : les surfaces commitent directement sur `alpha` dans l'arbre partagé.

## 5. MINIMAL_EXPERIMENT (lecture seule)
`git log` sur 30 jours : distribution lignes et fichiers par commit, part des messages avec un corps, nombre de fusions
passées par `forge_merge_gate` contre commits directs sur `alpha`.

## 6. NR (seulement si un garde est adopté)
Un commit de plus de N lignes sans corps de message est SIGNALÉ — non bloquant d'abord (observer avant d'enforcer).

## 7. DECISION
- **ADOPT** : l'expérience de la section 5 (mesure).
- **Déjà incarné** : G1/G2 — trunk `alpha` + merge gate par gain + pré-push qui juge le SHA.
- **DEFER** : garde de taille ou de message — gate NON bloquant d'abord, promu sur mesure.
- **REJECT** : branches longues par agent (contraire à G1).
- **Hors corpus** : protections de branches et sécurité GitHub — à re-sourcer si l'owner le veut.
