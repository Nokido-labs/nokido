# Enquête & Audit : Non-livraison des Exécuteurs OpenCode et Écrasement des Worktrees

- **Date** : 19 octobre 2026
- **Auteur** : Agent ANTIGRAVITY (Investigation sur worktree dédié `nokido_worktrees/antigravity`)
- **Objet** : Analyse causale de la perte de travail non committé sur 4 tâches exécuteurs OpenCode (`OPENCODE_NEMOTRON`, `OPENCODE_GLM`, `OPENCODE_GPTOSS`) et identification du mécanisme de réinitialisation destructrice du worktree.

---

## 1. Synthèse des Faits Mesurés sur les 4 Tâches Cibles

Le 19/10/2026, quatre tâches déléguées aux exécuteurs autonomes OpenCode se sont achevées avec du code ou des documents produits sur disque dans leurs worktrees respectifs, mais **aucun commit n'a été produit** sur leur branche de travail (`commits produits : 0`). Ces tâches ont été marquées soit `SUCCESS` soit `FAILURE`, et les modifications ont disparu lors de la tâche suivante.

| Identifiant Tâche / Job | Agent Exécuteur | Fichiers Produits sur Disque | Verdict Exécuteur & Statut M2M | Branche de Sauvegarde Forcée (`_assainir`) |
| :--- | :--- | :--- | :--- | :--- |
| `job_d106a922_1792409719_` | `OPENCODE_NEMOTRON` | **7 fichiers** modifiés | `OK [effet observe] commits produits : 0 (ce3195004..ce3195004) ; fichiers non commites : 7` &rarr; `SUCCESS` (`OK_DONE`) | `preserve/opencode_nemotron-20261019-140108` |
| `job_c0eab523_1792410914_` | `OPENCODE_GLM` | **2 fichiers** modifiés | `KO [effet observe] commits produits : 0 (0e1deed85..0e1deed85) ; fichiers non commites : 2 ; [NON LIVRE]` &rarr; `FAILURE` (`ERR_INTERNAL`) | Écrasé au rebase tâche `job_7d268d0a` |
| `job_36d852ae_1792408170_` | `OPENCODE_NEMOTRON` | **1 fichier** (`docs/audit/sondes_hors_endpoint_commun.md`) | `OK [effet observe] commits produits : 0 (7a80c8ae7..7a80c8ae7) ; fichiers non commites : 1` &rarr; `SUCCESS` (`OK_DONE`) | Resté non suivi (untracked) &rarr; pollution tâche suivante `job_5a99c9ab` |
| `job_b4369f90_1792409728_` | `OPENCODE_GPTOSS` | **5 fichiers** (dont `tests/nr/test_hamilton_detached_classe_nr.py`) | `OK [effet observe] commits produits : 0 (cc3a292ea..cc3a292ea) ; fichiers non commites : 5` &rarr; `SUCCESS` (`OK_DONE`) | `preserve/opencode_gptoss-20261019-145718` |

### Chronologie extraite des journaux superviseurs (`logs/supervisor/NokidoTaskExecutorOpencode*.log`) :
1. **`job_d106a922`** : Démarré à 13:35:43. Quota Nemotron épuisé &rarr; repli sur le modèle par défaut d'OpenCode. Tours 1 à 3 jusqu'à 14:00:05. L'agent écrit 7 fichiers. Le superviseur constate 0 commit produit et 7 fichiers non committés, mais clôt la tâche en `SUCCESS` (`frm_9bbc44f5e8cb`). À 14:01:08, la tâche suivante (`job_36d852ae`) arrive : le rebase sur `alpha` échoue sur modifications non indexées &rarr; `_assainir()` crée `preserve/opencode_nemotron-20261019-140108` et remet `wip/opencode_nemotron` sur `alpha`.
2. **`job_c0eab523`** : Arrive chez GLM à 14:40:37 après réaffectation. Session interrompue à 14:53:22 par une erreur de protocole ACP (`RuntimeError: session/prompt -> {'code': -32603, 'message': 'Internal error'}`). 2 fichiers avaient été écrits sur disque. Le superviseur constate 0 commit et 2 fichiers non committés, conclut `[NON LIVRE]` et clôt en `FAILURE` (`ERR_INTERNAL`). Le travail reste en plan dans le worktree.
3. **`job_36d852ae`** : Démarré à 14:40:55 chez Nemotron. Le modèle rédige `docs/audit/sondes_hors_endpoint_commun.md` et fournit la ligne finale `{"intent":"OK_DONE","pointer_ref":"docs/audit/sondes_hors_endpoint_commun.md"}`. À 14:53:13, l'exécuteur valide la tâche en `SUCCESS` car `pointer_ref` est présent, tout en constatant `0 commit produit ; fichiers non commites : 1` et en logguant `[LIVRAISON INCOMPLETE] docs/audit/sondes_hors_endpoint_commun.md (non suivi)`.
4. **`job_b4369f90`** : Démarré à 14:39:35 chez GPTOSS. L'agent exécute 4 tours jusqu'à 14:57:15, écrit 5 fichiers et confirme le test RED au tour 4. L'exécuteur clôt la tâche en `SUCCESS` avec 0 commit et 5 fichiers non committés. À 14:57:17, la tâche suivante `job_260996e3` est assignée : à 14:57:34, le rebase échoue et `_assainir()` déporte les 5 fichiers sur `preserve/opencode_gptoss-20261019-145718` puis force le checkout sur `alpha`.

---

## 2. Causes Prouvées de l'Échec de l'Étape de Commit

### A. L'agent LLM ne committe pas lui-même (Conception voulue)
- **Preuve 1 — Sandbox** : Dans `tools/forge_task_executor.py` (~l.2450, `_config_opencode_instance`), OpenCode est configuré avec `"permission": {"bash": "deny"}`. Le sous-processus OpenCode n'a aucun accès aux commandes shell ni au binaire `git`.
- **Preuve 2 — Consigne système injectée** : Dans `tools/forge_task_executor.py` (`_CONSIGNE_GIT_OPENCODE`, l.1880), l'instruction stipule expressément :
  > `[Executeur Nokido] Ton bac a sable refuse toute commande hors bac (RunCommand) : ne lance AUCUNE commande (ni git, ni pytest, ni script). Ecris seulement les fichiers demandes dans ce worktree ; l'executeur committe ce que tu as produit...`
- **Conclusion** : L'acte de commit relève **exclusivement du processus superviseur** (`tools/forge_task_executor.py`).

### B. Pourquoi le commit du superviseur (`_committer_pour_agent`) n'aboutit pas
Dans `tools/forge_task_executor.py`, la fonction `_preserver_livraison` (l.1918) appelle `_committer_pour_agent` (l.1936). L'échec du commit s'explique par quatre mécanismes précis :

1. **Court-circuit sur intention d'erreur (`_intent_rendu`)** :
   - Ligne 1943-1944 de `tools/forge_task_executor.py` :
     ```python
     if _intent_rendu(str(detail)):
         return None
     ```
   - Si la sortie de la tâche contient une intention d'erreur (`ERR_*`, `NEED_HUMAN_APPROVAL`, `BUDGET_EXCEEDED`), `_committer_pour_agent` **abandonne immédiatement** et retourne `None`.
   - Même si `_preserver_livraison` tente un commit de sauvegarde en cas d'`ok == False` (l.1927), tout crash d'infrastructure ACP (`RuntimeError`, comme pour GLM `job_c0eab523`) produit un `detail` d'erreur qui neutralise le commit. Les fichiers écrits avant le crash ne sont donc pas committés.

2. **Refus préventif par le Scorecard de Livraison (`scorecard_de_livraison`)** :
   - Introduit le 19/10 dans `tools/forge_task_executor.py` (l.1954–1968) :
     ```python
     sc = scorecard_de_livraison(wt, chemins)
     if sc is not None and sc.grade == QualityGrade.REJECTED:
         return "commit executeur REFUSE par le scorecard : %s" % sc.critique[:300]
     ```
   - Le superviseur exécute un audit qualité statique sur le diff avant tout `git add/commit`.
   - **Effet pervers majeur** : Lors d'un travail TDD où l'agent écrit d'abord la phase RED (comme GPTOSS `job_b4369f90` au tour 4), le diff présente un test qui échoue ou une implémentation partielle. Si le scorecard note le diff `REJECTED`, le superviseur **refuse d'exécuter le commit**. Le travail reste non committé dans le worktree.

3. **Échec ou blocage des hooks pre-commit (`git commit`)** :
   - Lignes 1975–1982 de `tools/forge_task_executor.py` :
     ```python
     a = _sp.run(g + ["add", "--"] + chemins, ...)
     c = _sp.run(g + ["commit", "-m", msg, "-m", corps], ...)
     if c.returncode != 0:
         return "commit executeur REFUSE rc=%s : %s" % (c.returncode, ...)
     ```
   - Le superviseur invoque `git commit` sans `--no-verify`. Tous les hooks pre-commit du dépôt (`git-gate.py`, vérification AST, scans de secrets) sont exécutés. Si une porte échoue ou expire (~6 secondes par fichier vérifié sous Windows), `git commit` renvoie `rc != 0`. L'exécuteur n'insiste pas et laisse les fichiers non committés.

4. **Neutralisation du statut d'échec par `pointer_ref`** :
   - Dans `tools/forge_task_executor.py` (l.1231–1234, `_non_livre`) :
     ```python
     if not m or m.group(1) != "0" or int(m.group(2)) == 0 or '"pointer_ref"' in (reponse or ""):
         return None
     ```
   - Si l'agent mentionne un `pointer_ref` dans son JSON final (cas de Nemotron `job_36d852ae`), la détection de non-livraison (`_non_livre`) est désactivée.
   - Si le fichier existe physiquement dans le worktree, `_artefact_declare_absent` renvoie `None`.
   - La tâche est validée en `SUCCESS` par `_juger_livraison`, alors même que le fichier est resté **non suivi (untracked)** et n'a jamais été committé par le superviseur.

---

## 3. Moment et Mécanisme Exact de la Perte de Données

Le travail n'est pas détruit à la fin de la tâche fautive. Il est écrasé et soustrait à la vue **au début de la tâche suivante** affectée au même exécuteur.

### Déroulement pas-à-pas :
```
[Tâche N termine]
  │  Modifications non committées présentes sur le worktree (nokido_worktrees/opencode_<agent>)
  │  Tâche N close en base (tasks.db) et message M2M émis vers l'émetteur.
  ▼
[Arrivée de la Tâche N+1 pour le même agent]
  │  tools/forge_task_executor.py::run_loop() appelle _preparer_worktree(agent) (l.2812)
  ▼
[_preparer_worktree() appelle forge_worktree.sync(nom)]
  │  tools/forge_worktree.py::sync() tente : git rebase alpha (l.386)
  ▼
[Échec immédiat du Rebase Git]
  │  Git répond : "error: cannot rebase: You have unstaged changes. Please commit or stash them." (rc != 0)
  ▼
[Déclenchement du repli forge_worktree._assainir()] (l.398)
  │  1. Crée une branche d'archive : git checkout -b preserve/<agent>-<timestamp> (l.361)
  │  2. Indexe et committe tout le worktree : git add -A && git commit -m "chore(preservation)..." (l.366)
  │  3. ÉCRASEMENT : git checkout -q -B wip/<agent> alpha (l.371)
  ▼
[Résultat]
  Le worktree est remis à zéro sur HEAD d'alpha.
  Les fichiers de la Tâche N sont désormais confinés dans une branche locale preserve/* orpheline.
```

### Pourquoi ce travail est "perdu" :
1. **Branche orpheline et muette** : La branche `preserve/<agent>-<timestamp>` n'est ni poussée sur le dépôt distant, ni référencée dans la table `tasks` pour la tâche N (celle-ci est déjà close depuis plusieurs minutes).
2. **Angle mort pour les relecteurs** : Les agents superviseurs (Claude, Antigravity) et les pipelines de CI ne surveillent que la branche canonique `alpha` et les branches actives `wip/<agent>`. Personne n'inspecte le namespace `preserve/*`.
3. **Cas des fichiers non suivis (untracked)** : Si le fichier était untracked sans conflit de nom avec `alpha` (cas de `job_36d852ae`), il n'a pas bloqué le rebase et est resté sur disque... pour venir polluer silencieusement la tâche suivante (`job_5a99c9ab`), qui s'est vue refuser sa livraison pour « travail non committé préexistant ».

---

## 4. Ce qui Reste Inmesurable

1. **La cause unitaire exacte du rejet de `_committer_pour_agent` sur `job_d106a922`** :
   - Le journal superviseur n'enregistre que la ligne de synthèse `commits produits : 0 ; fichiers non commites : 7`.
   - Le message d'erreur précis (rejet du `scorecard_de_livraison` vs échec d'un hook `git-gate` pre-commit vs timeout 180s de `git commit`) a été tronqué lors de l'enregistrement M2M (`detail[:220]` dans `_clore_delegation`) et n'apparaît pas dans le log standard.
2. **Le détail des opérations disque au cours des tours intermédiaires ACP** :
   - Le protocole ACP ne consigne pas le journal des écritures de fichiers tour par tour dans les logs du superviseur Nokido. On constate le résultat final au retour de `client.prompt()`, mais pas l'état exact des fichiers au moment précis où l'agent pensait avoir fini.
3. **Le volume exact de travail piégé dans l'ensemble des branches `preserve/*`** :
   - Sans commande d'inspection directe (`git branch --list 'preserve/*'`), il est impossible de quantifier le nombre de tâches historiques dont le travail a été relégué dans ces branches orphelines depuis l'activation de `_assainir` le 19/10.

---

## 5. Correctif Architectural Proposé (Sans Coder)

Pour garantir qu'**aucun travail produit par un exécuteur ne soit jamais perdu ni masqué**, l'architecture doit intégrer 4 garanties strictes :

### G1. Commit de Sauvegarde Systématique (WIP) avant toute clôture de délégation
- **Principe** : Dès que la session du modèle prend fin (que le résultat soit `SUCCESS`, `FAILURE`, `TIMEOUT` ou crash ACP), le superviseur doit immédiatement committer **tous** les fichiers modifiés et non suivis sur une branche de travail dédiée à la tâche : `wip/<agent>/<job_id>`.
- **Immunité aux portes** : Ce commit de préservation physique doit être exécuté avec `git commit --no-verify` afin qu'aucun hook pre-commit, aucun linter et aucun scorecard ne puisse empêcher l'écriture sur l'historique Git.
- **Règle d'or** : La conformité du code (portes qualité, tests verts) détermine le *grade* ou l'*acceptation* de la tâche, mais **ne doit jamais conditionner la sauvegarde de l'état disque**.

### G2. Dissociation stricte entre Scorecard et Action Git
- Le `scorecard_de_livraison` ne doit plus jamais bloquer l'appel à `git commit` dans `_committer_pour_agent`.
- Son rôle doit être strictement consultatif et analytique : il qualifie la livraison (`REJECTED`, `PARTIELLE`, `INTEGREE`) dans les métadonnées de la tâche et guide la décision de fusionner ou non vers `alpha`. Refuser d'enregistrer un diff sur Git au motif qu'il est incomplet (notamment en phase RED d'un cycle TDD) constitue une contradiction méthodologique.

### G3. Raccordement obligatoire de `_assainir` à `tasks.db` et M2M
- Si `forge_worktree.sync()` est contraint d'appeler `_assainir()` suite à un rebase impossible, la fonction doit obligatoirement :
  1. Identifier la dernière tâche exécutée sur ce worktree dans `tasks.db`.
  2. Mettre à jour son enregistrement avec la référence exacte : `pointer_ref = "git:<preserve_branch>@<sha>"`.
  3. Émettre un événement d'alerte M2M (`topic="preservation_worktree"`) vers l'agent orchestrateur (`agt_claude`) pour qu'une revue humaine ou automatisée puisse reprendre ou intégrer cette branche.

### G4. Correction de la porte `pointer_ref` dans `_juger_livraison`
- Dans `_juger_livraison` et `_non_livre`, la présence d'un `pointer_ref` ne doit plus blanchir une absence de commit.
- Si un artefact est pointé sur le disque mais que `commits produits == 0`, le statut ne doit jamais être validé en `SUCCESS` sans déclencher au préalable le commit de sauvegarde immédiat de cet artefact.
