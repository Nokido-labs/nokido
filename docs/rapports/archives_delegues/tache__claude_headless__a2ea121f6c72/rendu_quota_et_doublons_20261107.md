# Rendu - quota v3 (illisible/inconnu) et retrait de doublons - 2026-11-07

## 1. Quota v3 : `illisible` et `inconnu` branches dans l'executeur

NR rouge d'abord : 3 tests `test_point6_*` ajoutes dans `tests/nr/test_quota_agy_par_modele_nr.py`. Deux rouges (L en `inconnu` et en `illisible` partait sur `gemini-3.8-flash-medium`), puis vert : 10 passed.

Code (`tools/forge_task_executor.py`) :
- `_etat_quota_modele_agy(modele)` lit `forge_quota_tracker._fetch_agy_models_quota()`. Tracker injoignable ou modele non suivi = `inconnu`, jamais `ok`.
- `_modele_agy` : pour la taille L seulement, si l'etat du modele resolu est `illisible` ou `inconnu`, rend `None` (+ log.warning). `None` = tache laissee en attente, comme un repli epuise. Aucune marque d'indisponibilite n'est ecrite : `surface_est_indisponible` reste `None`, le slot n'est pas declare en panne (verifie par le NR).
- Seul `ok` (entree registre `status: ok`) laisse partir L. `quota_reached` reste traite par la table et ses replis.
- S et M inchanges ; `LAFORGE_AGY_MODEL` garde la priorite.
- A decider : le tracker ne rend `ok` que sur preuve explicite. Tant que rien n'ecrit `status: ok` dans `surfaces_indisponibles.json`, toute tache L AGY reste en attente. C'est UNKNOWN != sain, mais il manque un ecrivain de `ok`.

### Repli de la taille L sur opus-medium (decrit, non change)
`forge_palier_effort.REPLIS["agy"]["L"] = (("claude-opus-5-5-medium", "medium"),)`. `resoudre("agy","L")` essaie dans l'ordre `gemini-3.8-flash-medium` (medium) puis `claude-opus-5-5-medium`. Un candidat est ecarte s'il contient `argon`, si `surface_est_indisponible` donne un motif, ou si `_modele_hors_quota` (census) en donne un. Le premier restant est pris. Si tous sont ecartes : `ModeleHorsQuota`, et `_modele_agy` rend `None` (pending). Le repli ne se declenche donc qu'a l'epuisement prouve de flash-medium. La garde ci-dessus porte sur le modele resolu : si Opus est resolu, son etat tracker `inconnu`/`illisible` donne aussi `None`.

## 2. Retrait de doublons de regles

Constat : le `CLAUDE.md` de mon worktree est un stub allege (9 lignes, `skip-worktree`), pas le `Nokido/CLAUDE.md` complet, qui est dans l'arbre partage. L'y editer sortirait du perimetre et le commit de l'executeur ignore un fichier skip-worktree. Je n'ai donc PAS modifie CLAUDE.md. Etat lu dans l'arbre partage :

| Point | Etat | Ligne de RULES_SHARED.md qui garde la regle |
|---|---|---|
| Section 1 | deja remplacee par un renvoi | « Anti-dup prefiltrant » l. 63-80 ; « Consulter la cognition » l. 180 |
| Section 3 etape 1 | deja un renvoi | l. 63-80 |
| 6.ter point 6 | A RETIRER, renvoi propose « voir RULES_SHARED.md > Anti-dup prefiltrant » ; garder les 4 exemples (absents de RULES_SHARED) | l. 63-80 |
| 7.2 | A RETIRER, renvoi | l. 68-80, memes etapes |
| 7.9 | A GARDER | l. 9 dit seulement « Hub :8766 avant tout fichier Read » ; la consigne de ne pas sonder le hub par `run` n'y est pas |
| 7.10 | A GARDER | l. 156 couvre governed_edit et run_job, pas « code Python hors du depot (C:/tmp) » |

Restent a faire dans le CLAUDE.md partage : 6.ter point 6 et 7.2. Gardes, Constitution et le reste de 6.ter intacts.

RULES_SHARED.md : seule correction faite, l. 5 `GEMINI.md` (Gemini CLI) devient `GEMINI.md` (AGY CLI).

### 7.8 - `nssm restart LaForgeMCP`
Probablement perime, non modifie : les outils du hub parlent de `NokidoMCP`/`NokidoWebHub`, du superviseur :8765 et de l'ordre `restart-hub`, plus de `LaForgeMCP` ni `LaForge-Master`. Services installes non verifies (aucun redemarrage) : a confirmer par l'owner.

{"intent":"OK_DONE","pointer_ref":"rendu_quota_et_doublons_20261107.md"}
