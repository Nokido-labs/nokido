# Audit : Enquête sur les Sauvegardes d'Exécuteurs (d31564f96) — Cas Vus et Cas Ratés du 19/10/2026

- **Date** : 19 octobre 2026 (post-23:00)
- **Auteur** : Agent ANTIGRAVITY (Investigation sur worktree dédié `nokido_worktrees/antigravity`)
- **Périmètre** : Audit causal du mécanisme de sauvegarde `d31564f96` (`tools/forge_task_executor.py`) : analyse comparative des 2 cas fonctionnels (`job_c67eb508`, `job_d4e2061c`) et des 2 cas ratés (`job_a34c8407`, `job_171ef456`).

---

## 1. Déclencheur du Mécanisme de Sauvegarde dans `tools/forge_task_executor.py`

Le mécanisme introduit par `d31564f96` vise à copier dans `sandbox/sauvegardes_executeurs/<agent>/<tache>/` (avec `manifeste.json`) tout travail laissé sur disque lorsqu'aucun commit ne le préserve.

### A. Définition et implantation
- **Constante du dossier cible** : `tools/forge_task_executor.py:1926`
  ```python
  _SAUVEGARDES = SANDBOX / "sauvegardes_executeurs"
  ```
- **Fonction de copie physique** : `tools/forge_task_executor.py:1929-1961` (`_sauvegarder_travail`)
  - Condition interne de sélection des fichiers (l.1937–1940) :
    ```python
    tous = _chemins_status(wt)
    if not tous:
        return None
    chemins = sorted(p for p in tous - frozenset(exclus or ()) if Path(p).name != ".nokido.agent")
    ```
  - Écriture du manifeste (l.1954–1956) :
    ```python
    (dest / "manifeste.json").write_text(_j.dumps(
        {"tache": str(task_id), "agent": agent, "worktree": str(wt), "motif": str(motif)[:300],
         "fichiers": copies, "ts": time.time()}, ensure_ascii=False, indent=1), encoding="utf-8")
    ```

### B. Points d'appel et conditions logiques dans `_preserver_livraison` (l.1963–1988)
Le déclenchement dépend de la branche de statut `ok` issue de l'exécution de la délégation :

1. **Branche `ok == True` (l.1970–1978)** :
   ```python
   if ok:
       note = _committer_pour_agent(wt, task_id, detail, agent, exclus=exclus)
       if note is None or not note.startswith("commit executeur de"):
           sauve = _sauvegarder_travail(wt, task_id, agent, exclus, motif=note or "intention d'erreur rendue")
           if sauve:
               return "%s ; %s" % (note or "aucun commit (intention d'erreur rendue)", sauve)
       return note
   ```
   - **Condition exacte** : `ok is True` ET (`note is None` OU `not note.startswith("commit executeur de")`).
   - S'active si le commit est refusé (par le scorecard l.2016 ou pre-commit hook l.2035) ou si une intention d'erreur a été rendue (l.1997).

2. **Branche `ok == False` (l.1979–1988)** :
   ```python
   marque = '"commit_message": "chore(%s): INACHEVE a relire, tache %s (session en echec)"' % (agent, str(task_id)[:30])
   note = _committer_pour_agent(wt, task_id, marque, agent, exclus=exclus)
   if not note:
       return None
   if note.startswith("commit executeur de"):
       return "travail INACHEVE preserve : %s" % note
   sauve = _sauvegarder_travail(wt, task_id, agent, exclus, motif=note)
   return "travail INACHEVE NON committe, reste dans le worktree : %s%s" % (note, " ; " + sauve if sauve else "")
   ```
   - **Condition exacte** : `ok is False` ET `bool(note) is True` ET `not note.startswith("commit executeur de")`.
   - **Faille critique (l.1981–1982)** : Si `_committer_pour_agent` retourne `None`, la fonction fait `return None` **sans jamais appeler `_sauvegarder_travail`**.

---

## 2. Analyse Détaillée des 4 Cas (2 Vus + 2 Ratés)

### Cas 1 : `job_c67eb508_1792434808_` (`OPENCODE_GPTOSS`) — SAUVEGARDE VUE
- **Journal** : `logs/supervisor/NokidoTaskExecutorOpencodeGptoss.log` (fenêtre 20:33:39 – 20:44:51)
- **Ligne clé (20:44:51.847)** :
  `INFO DELEGATE job_c67eb508_1792434808_ -> OPENCODE_GPTOSS OK [effet observe] commits produits : 0 (b2a89b5b1..b2a89b5b1) ; fichiers non commites : 5`
- **Branche empruntée** : `ok == True` (l.1970).
  - OpenCode a terminé 5 tours avec réponse textuelle &rarr; `ok = bool(detail.strip())` vaut `True`.
  - Le worktree était propre au boot (rebase réussi à 20:33:39) &rarr; `_sales_avant = frozenset()`.
  - `_committer_pour_agent` tente de committer les 5 fichiers modifiés mais est **refusé par le scorecard de livraison** (faux rouge qualité sur diff RED/TDD).
  - `note` retourne `"commit executeur REFUSE par le scorecard : ..."`.
  - Condition l.1972 vérifiée (`not note.startswith("commit executeur de")`).
  - `_sauvegarder_travail` s'exécute avec `chemins = 5 fichiers` &rarr; Copie dans `sandbox/sauvegardes_executeurs/OPENCODE_GPTOSS/job_c67eb508_1792434808_/` + `manifeste.json`.
  - **Preuve** : Intégration ultérieure réussie au commit `1ad5425fd` (mentionné dans `tests/nr/test_merge_gate_depuis_sauvegarde_nr.py:3`).

### Cas 2 : `job_d4e2061c_1792435291_` (`OPENCODE_NEMOTRON`) — SAUVEGARDE VUE
- **Journal** : `logs/supervisor/NokidoTaskExecutorOpencodeNemotron.log` (fenêtre 20:41:40 – 21:00:48)
- **Lignes clés** :
  - `20:43:08.573 WARNING [opencode] OPENCODE_NEMOTRON : quota epuise -> repli sur le modele de repli pour job_d4e2061c_1792435291_`
  - `21:00:48.602 INFO DELEGATE job_d4e2061c_1792435291_ -> OPENCODE_NEMOTRON KO [effet observe] commits produits : 0 (dc24d98d3..dc24d98d3) ; fichiers non commites : 6 ; [NON LIVRE] aucun commit propre, 6 fichier(s) non committe(s)`
- **Branche empruntée** : `ok == False` (l.1979).
  - La session du modèle de repli a échoué (agent muet 300 s / ACP timeout) &rarr; `ok = False`.
  - Les 6 fichiers ont été écrits sur disque au cours de la tentative sous repli.
  - Dans `_preserver_livraison` (l.1980) : `_committer_pour_agent` est appelé avec `marque`. Le scorecard de livraison refuse le commit du travail inachevé &rarr; `note = "commit executeur REFUSE par le scorecard : ..."`.
  - Ligne 1981 `if not note:` est **fausse** car `note` est une chaîne d'erreur non vide.
  - Ligne 1983 est fausse.
  - Ligne 1985 `sauve = _sauvegarder_travail(...)` est appelée : `chemins = 6 fichiers` &rarr; Copie dans `sandbox/sauvegardes_executeurs/OPENCODE_NEMOTRON/job_d4e2061c_1792435291_/` + `manifeste.json`.
  - **Preuve** : Intégration ultérieure au commit `5a7c3ce91` (`test_merge_gate_depuis_sauvegarde_nr.py:3`).

---

### Cas 3 : `job_a34c8407_1792435960_` (`OPENCODE_GLM`) — SAUVEGARDE RATÉE
- **Journal** : `logs/supervisor/NokidoTaskExecutorOpencodeGlm.log` (fenêtres 21:27 – 21:36 et 22:02 – 22:06)
- **Lignes clés** :
  - `21:27:14.328 INFO 1 tâches à traiter` &rarr; démarré chez GLM.
  - `21:36:43.227 [logboot] journal sans pipe ... TaskExecutor démarré` &rarr; **L'exécuteur GLM a été tué et relancé par le superviseur à 21:36:43**, puis à 21:41, 21:45, 21:50, laissant les 2 fichiers unstaged dans le worktree.
  - `22:02:30.282 WARNING [lease] mission REPRISE job_a34c8407 ... tent 2 — l'agent n'a plus donne signe de progression depuis 1800 s`
  - `22:02:34.972 INFO worktree OPENCODE_GLM : {'agent': 'opencode_glm', 'rebased': True, 'msg': 'Rebasing (1/4)...'}`
  - `22:06:53.075 INFO DELEGATE job_a34c8407_1792435960_ -> OPENCODE_GLM KO [effet observe] commits produits : 0 (8ed44d9ea..8ed44d9ea) ; fichiers non commites : 2 ; [NON LIVRE] aucun commit propre, 2 fichier(s) non committe(s)`
  - `22:06:53.112 WARNING job_a34c8407_1792435960_ : OPENCODE_GLM ne peut pas la prendre ... laissee chez OPENCODE_GLM`
- **Mécanisme exact de l'échec de sauvegarde** :
  1. À 22:02:34, la tâche reprise démarre. À la ligne 2591 de `_delegate_to_opencode` :
     `_sales_avant = _chemins_status(wt) or frozenset()`
     Les 2 fichiers écrits avant le restart superviseur étaient déjà présents non indexés sur disque. Ils ont donc été enregistrés dans **`_sales_avant`**.
  2. Pendant l'exécution 22:02 – 22:06, aucun fichier supplémentaire n'est écrit.
  3. À 22:06:53, `_preserver_livraison` appelle `_committer_pour_agent(..., exclus=_sales_avant)`.
  4. Ligne 2005 : `chemins = tous - frozenset(exclus) = set()`. Ligne 2007 : `if not chemins: return None`.
  5. `_committer_pour_agent` retourne `None`.
  6. Dans `_preserver_livraison` (branche `ok == False`, l.1981) : `if not note: return None` &rarr; **Court-circuit total sans appel à `_sauvegarder_travail`**.
  7. En contraste, `_juger_livraison` (via `_etat_git` l.1172 qui ne soustrait pas `_sales_avant`) compte `fichiers non commites : 2` et déclenche `_non_livre` &rarr; `[NON LIVRE]`.
  8. **Preuve matérielle** : Aucun dossier `sandbox/sauvegardes_executeurs/OPENCODE_GLM/` n'a été créé. Les 2 fichiers sont restés sur disque jusqu'au rebase suivant à 22:33:38, où `forge_worktree._assainir()` les a sauvés en créant la branche `preserve/opencode_glm-20261019-223330` (commit `5b0581521`).

---

### Cas 4 : `job_171ef456_1792437662_` (`OPENCODE_NEMOTRON`) — SAUVEGARDE RATÉE
- **Journal** : `logs/supervisor/NokidoTaskExecutorOpencodeNemotron.log` (fenêtre 22:05:53 – 22:12:12)
- **Lignes clés** :
  - `22:05:53.708 INFO 1 tâches à traiter` (`job_171ef456_1792437662_`)
  - `22:05:53.919 INFO worktree OPENCODE_NEMOTRON : {'agent': 'opencode_nemotron', 'rebased': True...}`
  - `22:07:08.902 WARNING [opencode] OPENCODE_NEMOTRON : quota epuise -> repli sur le modele de repli pour job_171ef456_1792437662_`
  - `22:12:12.193 INFO DELEGATE job_171ef456_1792437662_ -> OPENCODE_NEMOTRON KO [effet observe] commits produits : 0 (b586e09c2..b586e09c2) ; fichiers non commites : 1 ; [NON LIVRE] aucun commit propre, 1 fichier(s) non committe(s)`
  - `22:12:12.200 WARNING job_171ef456_1792437662_ : OPENCODE_NEMOTRON ne peut pas la prendre ... laissee chez OPENCODE_NEMOTRON`
- **Mécanisme exact de l'échec de sauvegarde** :
  1. À 22:05:53, Tentative 1 démarre sur worktree propre (`_sales_avant = frozenset()`). Nemotron produit 1 fichier sur disque.
  2. À 22:07:08, OpenRouter renvoie quota épuisé (`429 / rate limit`). L'exception est capturée (l.2677) et `repli_a_tenter = True` (l.2684).
  3. Ligne 2696 : `return _delegate_to_opencode(task, token, inst)` (appel récursif).
  4. **LE PIÈGE** : Au début de l'appel récursif (l.2591), `_sales_avant` est **ré-échantillonné** :
     `_sales_avant = _chemins_status(wt) or frozenset()`
     Le fichier produit par la Tentative 1 est présent sur disque et devient donc membre de `_sales_avant` !
  5. La Tentative 2 tourne avec le modèle de repli jusqu'à 22:12:12 sans écrire de nouveau fichier, puis échoue (`ok = False`).
  6. À 22:12:12, l'appel récursif atteint `_preserver_livraison(ok=False, ..., exclus=_sales_avant)`.
  7. Dans `_committer_pour_agent` : `chemins = tous - exclus` est vide &rarr; `return None`.
  8. Ligne 1981 : `if not note: return None` &rarr; La sauvegarde `_sauvegarder_travail` n'est pas appelée !
  9. L'appel récursif retourne à la ligne 2696, court-circuitant le bloc de préservation du premier appel.
  10. `_juger_livraison` constate le fichier non committé via `_etat_git` et conclut `[NON LIVRE]`.
  11. **Preuve matérielle** : Aucun dossier de sauvegarde créé pour `job_171ef456`. Le fichier est resté orphelin dans le worktree.

---

## 3. Test des Hypothèses Demandées

1. **Hypothèse « quota épuisé &rarr; repli » (Nemotron 22:07:08) contourne la sauvegarde** :
   - **CONFIRMÉE ET PROUVÉE (VRAIE)**.
   - Cause racine : L'appel récursif `_delegate_to_opencode` ré-évalue `_sales_avant` à l'entrée (l.2591), transformant les fichiers valides produits au tour 1 en fichiers "préexistants" exclus de la préservation et de la sauvegarde au tour 2.

2. **Hypothèse « réaffectation impossible &rarr; laissée chez X » contourne la sauvegarde** :
   - **INFIRMÉE (FAUSSE)**.
   - `_reaffecter` intervient à la ligne 2718, c'est-à-dire **après** `_preserver_livraison` (l.2705). L'échec de la sauvegarde avait déjà eu lieu en amont ; le message "laissée chez X" n'est qu'une conséquence du verdict `[NON LIVRE]` et non la cause de l'absence de sauvegarde.

3. **Hypothèse « l'exécuteur a été relancé entre-temps »** :
   - **CONFIRMÉE ET PROUVÉE (VRAIE pour `job_a34c8407`)**.
   - GLM a subi plusieurs redémarrages de processus (21:36, 21:41, 21:45, 21:50) pendant que `job_a34c8407` était en cours. Lors de la reprise après expiration du lease (22:02:30), `_sales_avant` a englobé les fichiers issus de la première tentative, interdisant leur commit et leur sauvegarde en fin de tâche.

---

## 4. Verdict par Cas & Preuves

| Cas | Agent | Statut Final | Verdict Sauvegarde | Preuve Factuelle |
| :--- | :--- | :--- | :--- | :--- |
| `job_c67eb508` | `OPENCODE_GPTOSS` | `SUCCESS` (0 commit, 5 uncommitted) | **SAUVEGARDE ATTENDUE & EFFECTUÉE** | Dossier créé sous `sandbox/sauvegardes_executeurs/OPENCODE_GPTOSS/job_c67eb508_1792434808_/` ; intégré au commit `1ad5425fd`. |
| `job_d4e2061c` | `OPENCODE_NEMOTRON` | `FAILURE` (0 commit, 6 uncommitted) | **SAUVEGARDE ATTENDUE & EFFECTUÉE** | Dossier créé sous `sandbox/sauvegardes_executeurs/OPENCODE_NEMOTRON/job_d4e2061c_1792435291_/` ; intégré au commit `5a7c3ce91`. |
| `job_a34c8407` | `OPENCODE_GLM` | `FAILURE` (`[NON LIVRE]`, 2 uncommitted) | **SAUVEGARDE ATTENDUE & NON EFFECTUÉE** | Aucun dossier sous `sandbox/sauvegardes_executeurs/OPENCODE_GLM/` ; travail récupéré 27 min plus tard par `preserve/opencode_glm-20261019-223330` (`5b0581521`). |
| `job_171ef456` | `OPENCODE_NEMOTRON` | `FAILURE` (`[NON LIVRE]`, 1 uncommitted) | **SAUVEGARDE ATTENDUE & NON EFFECTUÉE** | Aucun dossier sous `sandbox/sauvegardes_executeurs/OPENCODE_NEMOTRON/job_171ef456_1792437662_/` malgré la présence du fichier loggué à 22:12:12. |

---

## 5. Spécification des Tests RED Proposés (Sans Coder)

Pour fermer définitivement ces deux angles morts, deux tests de non-régression sont proposés :

### RED 1 : Préservation lors d'un repli de quota (`repli_modele`)
- **Nom du test** : `tests/nr/test_sauvegarde_executeur_quota_repli_nr.py::test_repli_modele_ne_masque_pas_fichiers_tour1`
- **Scénario** :
  1. Simuler une tâche `OPENCODE_NEMOTRON` où le client ACP écrit `app/nouveau_module.py` au tour 1.
  2. Déclencher une exception simulant `429 rate limit exceeded` au tour 1 &rarr; passage en repli.
  3. Le second modèle ne produit aucun fichier additionnel et se termine en échec.
- **Assertion clé** :
  ```python
  dossier_sauvegarde = ROOT / "sandbox" / "sauvegardes_executeurs" / "OPENCODE_NEMOTRON" / task_id
  assert dossier_sauvegarde.exists()
  manifeste = json.loads((dossier_sauvegarde / "manifeste.json").read_text(encoding="utf-8"))
  assert "app/nouveau_module.py" in manifeste["fichiers"]
  ```

### RED 2 : Sauvegarde obligatoire en cas de verdict `[NON LIVRE]`
- **Nom du test** : `tests/nr/test_sauvegarde_executeur_non_livre_nr.py::test_non_livre_sauvegarde_meme_si_chemins_dans_sales_avant`
- **Scénario** :
  1. Pré-poser un fichier untracked dans le worktree avant le lancement de la délégation (simulant un crash/restart exécuteur).
  2. Exécuter la tâche sans modification additionnelle &rarr; `_juger_livraison` détecte le fichier et conclut `[NON LIVRE]`.
- **Assertion clé** :
  ```python
  # La condition 'if not note: return None' ne doit plus empêcher la sauvegarde si [NON LIVRE] est avéré
  dossier_sauvegarde = ROOT / "sandbox" / "sauvegardes_executeurs" / agent / task_id
  assert dossier_sauvegarde.exists(), "Un travail qualifié [NON LIVRE] doit obligatoirement être sauvegardé"
  ```
