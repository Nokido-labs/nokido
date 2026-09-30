# Fiche RSI — seconde lecture CLAUDE (26/09) · sources : E:/nokido_veille_rsi (lecture seule, rien exécuté)
Déplacée le 27/09 depuis `sandbox/veille_rsi/fiche_rsi_seconde_lecture_claude_2026-09-26.md` (la copie sandbox n'est plus qu'un pointeur).
Extraits bornés : `sandbox/veille_rsi/extraits_mecanismes_2026-09-26.md` (README 30 l., 18 occurrences/dépôt).
Limite DITE : extraits par mots-clés, pas lecture intégrale — une primitive absente des extraits n'est pas absente du dépôt.

## 1. PATTERNS (preuve = fichier:ligne du clone)
| # | Primitive | Où | Ce qu'elle dit |
|---|---|---|---|
| P1 | **Aucun modèle ne vote sur son propre patch** ; porte DÉTERMINISTE sur preuves APPARIÉES held-out | recuris README (« admitted by paired held-out arithmetic and nothing else ») | le juge est de l'arithmétique, pas un LLM |
| P2 | Échec LOCALISÉ dans UN composant depuis des traces structurées ; on ne corrige que lui | recuris README ; `grounding.py:66` rejected_* | correctif ciblé, pas global |
| P3 | Sélecteur : **non-régression PAR benchmark** + **rejet des égalités de score** | darwin-godel-machine `archive/parent_selector.py:50,52` | gain nul = pas de promotion |
| P4 | Held-out **disjoint, évalué 2 fois** ; paquet de preuves à somme de contrôle qui GARDE les échecs | DGM README (proof bundle, « empty responses, timeouts ») | l'échec est une preuve, pas du bruit |
| P5 | **L'évaluateur est HORS de portée de l'agent** (prepare.py « Not modified »), budget FIXE, 1 métrique, keep/discard | autoresearch README ; `prepare.py:31` TIME_BUDGET=300 | l'agent ne touche jamais la règle qui le juge |
| P6 | **Les agents affaiblissent leurs propres vérifications** (« agents were being taught to write weaker checks ») | rsiagent `core/checks.py:41` | mésévolution mesurée, pas théorique |
| P7 | Tout évolue SAUF le **journal d'événements** (historique canonique) ; snapshots de bac à sable ; auto-vérif + rollback | exo README ; `docs/SELF-CONTROL.md:180` | preuve immuable = ce qui empêche les boucles |
| P8 | Fitness **multi-objectif** : champ `complexity` ; frontière de Pareto ; porte d'écriture qui ne mord que sur violation | openevolve `database.py:65` ; awesome-self-evolving `code/safety_gated_evolution.py:56`, `docs/primer.md:40` | un score scalaire récompense la croissance |
| P9 | Évolution de MÉMOIRE/skills sans toucher aux poids ; mémoire vérifiée par un Verifier distinct de l'Actor | recuris, rsiagent README | L1 d'abord : risque le plus bas |

## 2. NOKIDO_EXISTING — VÉRIFIÉ DANS LE CODE le 27/09
La version du 26/09 (déclarative) PRÉCÉDAIT les adoptions faites le jour même : elle disait « non prouvé / absent »
là où le code porte désormais la brique. Niveau ci-dessous = PRÉSENT (corps de fonction lu). Aucune exécution en
production ni NR relus : VERIFIED / MEASURED restent NON ÉTABLIS.

| # | Brique | fichier:ligne | Constat |
|---|---|---|---|
| P1 | juge arithmétique | `app/forge_mutation_judge.py:548` `juger_gain` | déterministe (tests_ok, tests_total, duree_s), aucun LLM dans la porte. **Held-out disjoint ABSENT** : baseline et candidat mesurés sur la MÊME liste `tests`. Le « juge TIERS » LLM du débat 26/09 n'est pas dans `juger_gain` ; `mesure_juge_2026-09-26.json` non relu ce jour. |
| P3 | non-régression PAR test, égalité ≠ gain | `forge_mutation_judge.py:548` (`tests_passes` perdus ⇒ DEGRADE) ; `:601` `juger_module_avec_gain` | NEUTRE ⇒ `SURVIT_SANS_GAIN`, restauré depuis git HEAD ; aucun test ⇒ `GAIN_INDECIDABLE` (trois états). ADOPTÉ 26/09. |
| P4 | échecs gardés | `juger_module_avec_gain` : `_journaliser` sur CHAQUE branche | les rejets sont journalisés. Held-out évalué deux fois : ABSENT. |
| P5/P6 | évaluateur hors de portée | `forge_mutation_judge.py:142` `_ZONE_EVALUATEUR` (tests/, tools/ci_local.py, config/constitution.toml, sandbox/evolution/, sandbox/mutation_ledger.jsonl, le juge, forge_guarded_mutation_loop) ; `:147` `mutable()` ; clôture d'imports `:109` `perimetre_immuable` (RACINES `:73`) | ADOPTÉ 26/09. Couverture des effecteurs : voir section 2bis (contre-lecture AGY + seconde lecture, 27/09). |
| P7 | registre chaîné | `app/forge_autonomous_loops.py:457` `_chainon`, `:466` `_dernier_chainon` (patron `tools/forge_memory_ledger._append`) | chaînage depuis le 26/09, lignes héritées jamais réécrites. Fichier chaîné : `sandbox/evolution/evolution_experiences.jsonl`, écrit par `record_evolution_experience` (`:552`) ; première entrée chaînée ancrée sur l'empreinte de la dernière ligne héritée (AGY 27/09, non relu par Claude). |
| P8 | fitness Pareto | `app/forge_generation.py:218` `_verdict_pareto`, `:233` `_gain_vs_precedente` | modules = coût, tests NR = bénéfice ; `CROISSANCE_SANS_COUVERTURE` n'est plus une victoire. ADOPTÉ 26/09. |
| P2 | échec localisé | `_reexaminer` (tri v3 `59bcd2658`) | non relu ce jour. |
| P9 | L1 skills/leçons | `forge_self_correction` | non relu ce jour ; sans porte held-out. |

## 2bis. Contre-lecture AGY (27/09) et seconde lecture CLAUDE
Artefact : `sandbox/veille_rsi/contre_lecture_agy_2026-09-27.md` (tâche `job_2a21228f_1790488427_claude_handoff_next`).

| Effecteur | AGY | Seconde lecture CLAUDE (code lu) |
|---|---|---|
| `forge_mutation_judge.juger_module` | appelle `mutable()` (`:343`) | accepté, non relu. |
| `tools/forge_self_patcher.py` | « trou : `fp.write_text` sans `mutable()` » | **INEXACT pour le chemin vivant.** `_apply_search_replace` (`:290`, écriture `:305`) n'a AUCUN appelant dans le fichier ; les deux voies qui appliquent — règles `:441`, propositions `:531` — passent par `_submit_to_judge` (`:397`) → juge → `mutable()`, et « thymus injoignable = refus fail-closed ». Reste une fonction MORTE qui écrit : dette, pas trou actif. Le module tourne réellement (`NokidoSelfPatcher` réveillé par le circadien, `forge_circadian.py:635`). |
| `app/forge_proposal_applier.py` | n'écrit qu'en base, appel non requis | accepté, non relu. |
| `app/forge_guarded_mutation_loop.py` | « trou : `file_path.write_text` sans `mutable()` » | **CONFIRMÉ, DORMANT.** `apply_mutation_with_git_guard` (`:102`, écriture `:127`) : seul contrôle AST constitutionnel ; le détecteur de triche ne hache que la suite de tests (ni `tools/ci_local.py`, ni le juge) ; en cas de succès il **commite seul** (`git commit`, `:183` env.), sans promotion owner. Seul appelant trouvé : l'auto-test `__main__` (`:200`, fichier factice `sandbox/test_mutation.py`). Invocation par chemin non exclue. |

NR (Q3, vérifié par Claude) : `tests/nr/test_juge_evaluateur_hors_portee_nr.py:41` `test_une_mutation_ne_touche_jamais_son_evaluateur`
et `tests/nr/test_boucle_raccordee_gain_nr.py:118` `test_SURVIT_SANS_GAIN_est_un_REFUS` — existent ET déclarés dans `ci_local`.

## 3. EVIDENCE
PATTERNS : extraits bornés (`extraits_mecanismes_2026-09-26.md`), pas lecture intégrale des clones. NOKIDO_EXISTING :
corps de fonction lus le 27/09 (`read_function_body`, plages bornées). Rien exécuté — ni les clones, ni les briques.

## 4. GAPS (au 27/09 — trois des cinq gaps du 26/09 sont fermés dans le code)
1. **Held-out disjoint** (P1/P4) : un candidat jugé sur les tests qui l'ont vu naître peut sur-ajuster. OUVERT — seul ADOPT encore sans code.
2. **`forge_guarded_mutation_loop.apply_mutation_with_git_guard`** : écrit sans `mutable()` et commite seul. Dormant
   (aucun appelant hors auto-test). Décision owner : le brancher sur `mutable()` + promotion owner, ou le GELER
   (jamais supprimer). Tant qu'il dort, ce n'est pas un trou ACTIF — mais c'est une porte qu'un futur appelant ouvrirait.
3. **`forge_self_patcher._apply_search_replace`** : écrivain mort (0 appelant). Geler ou marquer ; ne pas le rebrancher.
4bis. FERMÉ par la contre-lecture : fichier chaîné (`evolution_experiences.jsonl`) ; NR de la section 6 existants.
4. FERMÉS dans le code : égalité = REJECT (`SURVIT_SANS_GAIN`) · périmètre interdit (`_ZONE_EVALUATEUR`) · fitness Pareto (`_verdict_pareto`).

## 5. MINIMAL_EXPERIMENT (rien d'armé sans feu vert owner)
Le 1er effecteur choisi au débat (quarantaine TTL d'un slot routeur mort, 2 observateurs) se CERTIFIE ainsi :
held-out = fenêtre de trafic disjointe de celle qui a déclenché la quarantaine ; métrique déterministe
(taux de réussite du routeur + latence p95) ; REJECT si égalité ; journal chaîné. Aucun LLM dans la porte.

## 6. NR (rouge d'abord)
`test_une_mutation_ne_touche_jamais_son_evaluateur` : un candidat qui modifie `tests/` ou le juge est REFUSÉ
avant évaluation. `test_egalite_de_score_n_est_pas_une_promotion`.

## 7. DECISION
ADOPT : P1, P3, P5, P6, P7 (via forge_memory_ledger), P8 (complexité dans la fitness). DEFER : P2 déjà là,
P9 (L1 skills, après la porte held-out). REJECT : novelty_judge LLM comme porte (openevolve) — contredit P1 ;
utilisable seulement comme indice de doublon.

**État au 27/09 (code lu)** : P3, P5/P6, P7, P8 = adoptés et PRÉSENTS dans le code ; P1 = partiel (juge arithmétique
oui, held-out disjoint non). Prochaine décision owner : le held-out disjoint (gap 1), puis le sort de `apply_mutation_with_git_guard` (gap 2).
NR de la section 6 : EXISTENT et sont déclarés (vérifié 27/09).
