# Self-audit — ÉTAPE 0 : triangulation des instruments contre la vérité terrain (2026-09-23)

Direction owner (23/09 soir) : ne PAS écrire un second `introspect` ; étendre census +
`body_regulation_audit` + `reachability_ledger` + `forge_organ_agents` (gaps/WIRING_PROBES) du niveau
MODULE au niveau MÉCANISME/CAPACITÉ, preuve d'exécution graduée. Étape 0 = mesurer d'abord ce que les
instruments EXISTANTS voient des vérités établies à la main le même jour.

Protocole : `C:/tmp/selfaudit_etape0.py` (job `job_86f5e23a01a9`), lecture seule, aucun second écrivain RAG
(`body_regulation_audit --no-ingest`), pendant l'ingestion 6f et sous le piège WAL. Sorties brutes
`C:/tmp/selfaudit0/*.out` ; verdicts détaillés lus dans les artefacts des instruments
(`sandbox/workspace/body_regulation.json`, `sandbox/reachability.json`), pas dans leur stdout (résumés).

## Vérités terrain (mesurées, non déduites)

| id | vérité | preuve |
|---|---|---|
| D | `DurableWorkflow` jamais exécuté | `durable.db` absente, tables `workflow_*` absentes ; seul `recover_chain_nodes` câblé |
| B | `rc=0` ≠ `VERIFIED` | aucun état VERIFIED automatique (fiche V2) ; `rc=0` + 0 chunk déjà observé |
| C | famine WAL | `WAL X -> X (busy=1)` dans les journaux d'ingestion ; 21 Go à 14h32, 9,2 Go à 15h41 |
| RAG | 655 216 chunks `active=0` | raffinage du 23/09 |
| S | soif étranglée | `curiosity_driver` : 16 tirs, dernier il y a 138 h (fenêtre 4-5 h, 7 j) |
| R | boucle d'auto-amélioration non close | `forge_proposal_applier` non câblé + désarmé (22/09) |

## Résultat

| vérité | census | body_regulation | reachability_ledger | organ_agents.gaps |
|---|---|---|---|---|
| D | muet | **CABLE** (« importé par 1 module ») — FAUX CALME | **UNPROVEN** — honnête, ne tranche pas | muet |
| B | muet | muet | muet | muet |
| C | muet | muet | muet | muet |
| RAG | muet | muet | muet | muet |
| S | muet | curiosity **CABLE**, epistemic_daemon **REGULE** — FAUX CALME | muet | muet |
| R | muet | proposal_applier **INVOQUE** — FAUX CALME | — | ✅ « BOUCLE régénération … pas de boucle close » |

**1 vérité sur 6 retrouvée**, par l'étalon `forge_organ_agents` seul.

## Diagnostic des instruments

1. **`body_regulation_audit` range le non-prouvé du côté sain.** `CABLE`/`INVOQUE` = présence statique
   (import, citation). Juste selon sa définition, mais l'agrégat « **0 zone morte** / 1 977 modules » additionne
   trois mécanismes mesurés en panne : c'est le corollaire violé de la constitution (liste NOIRE : tout ce qui
   n'est pas `ZONE_MORTE` tombe dans le sain).
2. **`reachability_ledger` est honnête mais aveugle à l'exécution.** `DurableWorkflow` (jamais exécuté) et
   `recover_chain_nodes` (seul câblé en exécution) reçoivent le MÊME état `UNPROVEN` ; `PROVEN` = « cité par
   des tests », pas « exécuté en production » (`run_cycle` PROVEN par 15 occurrences de test).
3. **Aucun instrument n'a de dimension RUNTIME** (journaux, bases, pouls, artefacts d'exécution) : B, C et RAG
   sont hors de portée PAR CONSTRUCTION, pas par défaut de réglage.
4. `census` décrit la carte (1 749 modules, 3 non classés) : ce n'est pas un instrument de santé.

## Conséquence pour l'étape 1 (à valider par l'owner — rien n'est codé ici)

Ajouter aux instruments EXISTANTS un axe de preuve d'exécution par MÉCANISME, gradué
`ATTENDU → PRÉSENT(code) → INVOQUÉ(journal/pouls) → ARTEFACT(fichier/table produit) → EFFET(état changé)`,
et un classement par liste BLANCHE : n'est sain que ce qui atteint `EFFET`. Candidat porteur : étendre
`reachability_ledger` (il a déjà `UNPROVEN` honnête) plutôt que `body_regulation` ; sortie vers
`pat_self_improvement` (format existant). NR de calibration : relancé SANS ces verdicts, l'instrument doit
retrouver seul D, S, R (au minimum) — aujourd'hui 1/6.

À INSPECTER AVANT tout code (anti-dup) : `introspect` ne connaît pas de brique « preuve d'exécution graduée »,
mais déclare NE PAS avoir consulté `forge_capability_contracts` (réservé aux questions de SERVICE) — porteur
possible de l'axe INVOQUÉ/ARTEFACT/EFFET — ni `forge_swarm_evidence.arbitrer` (arbitrage de preuves).
Procédures voisines à relire : liste BLANCHE de la purge des veilles (`bde5d1bc5`, 23/09) ; « la veille
distingue une recherche vide d'une recherche non mesurée » (`213e30193`, PROUVÉ).

**Inspecté (même soir) : `tools/forge_capability_contracts.py` PORTE DÉJÀ le patron**, pour les SERVICES :
« TROIS NIVEAUX DE PREUVE, jamais confondus : TRANSPORT · APPLICATIF · CAPACITÉ » ; « aucun endpoint de santé
universel — chaque valeur est MESURÉE » ; `cap=None` quand aucune sonde fonctionnelle n'existe (« on le DIT »).
⇒ l'étape 1 n'invente PAS d'échelle : elle transpose CETTE échelle aux mécanismes SANS PORT
(CODE_PRÉSENT → INVOQUÉ → ARTEFACT → EFFET), avec la même règle `sonde=None ⇒ INCONNU dit`.
Recommandation : vocabulaire et règles de `forge_capability_contracts` ; liste des mécanismes attendus
déclarée à côté de `WIRING_PROBES` (`forge_organ_agents`, l'étalon, seul à avoir vu R) ; verdicts publiés par
`reachability_ledger` (déjà honnête : `UNPROVEN`). Décision de porteur = OWNER.

LIMITES de cette mesure : 6 vérités seulement, choisies par moi (biais de sélection : ce sont des pannes
que je connaissais) ; recherche par nom de module/symbole — un mécanisme porté sous un autre nom serait
manqué ; `CuriosityDriver`/`ProposalApplier` absents du ledger comme SYMBOLES (0 fiche) = nom de classe
supposé, NON vérifié.
