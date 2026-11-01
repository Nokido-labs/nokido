# Enquête : reaffectation « aucun autre executeur vivant » (2026-10-27)

## Contexte
Le 26/10 la réaffectation automatique a écrit « aucun autre executeur vivant » alors que plusieurs exécuteurs étaient vivants (OPENCODE_DEFAUT2..5 notamment jamais choisis ; cf config/opencode_instances.json).

## Fonctions concernées (sources file:line)

### Qui choisit le prochain exécuteur lors d'une réaffectation ?
- `tools/forge_task_executor.py:4397` `_reaffecter(task: dict, motif: str, ordre=None)`
  - Construit `de` (agent actuel), récupère `description` si manquante (4403-4415)
  - Refuse si tâche réservée via `_reservee_a()` -> `_refuser_reaffectation_reservee()` (4415-4418)
  - Si échec auth et agent est OpenCode en repos -> bascule `ordre = _ORDRE_HORS_OPENCODE` (4419-4426)
  - Lit trace `reaffectations` dans tasks.db (4428-4440)
  - Construit `essayes = {de} | {de/vers dans trace}` (4439)
  - Construit `vivants` = candidats dans `ordre or _ORDRE_REPLI` filtrés par : non essayé, `_executeur_bat(a)` frais, et non `_executeur_suspendu(a)` (4440-4441)
  - Si plusieurs vivants, peut appliquer heuristique de charge/hedoniste (4443-4461)
  - Si aucun vivant -> logge ligne 4462-4464 et retourne `None` (pas de réaffectation)
  - Sinon met à jour task: `agent=vers`, `status='pending'`, ajoute trace (4465-4474), log `REAFFECTEE ...` (4473)

### Qui écrit le motif « aucun autre exécuteur vivant » ?
- `tools/forge_task_executor.py:4462-4464` dans `_reaffecter()` :  
  `log.warning(f"  {str(task['id'])[:24]} : {de} ne peut pas la prendre ({motif}) et AUCUN autre executeur vivant hors {sorted(x for x in essayes if x)} -- laissee chez {de}")`

Autre occurrence liée au même motif textuel (contexte différent) :
- `tools/forge_task_executor.py:3134` dans `_delegate_to_vibe()` quand `_reaffecter()` échoue après refus modèle hors quota :  
  `_clore_delegation(task_id, token, False, "[MODELE HORS QUOTA] %s -- aucun autre executeur vivant" % _hors_quota)`

## Pourquoi les OPENCODE_DEFAUT2..5 ne sont pas candidats
Ordre de réaffectation déterminé par `tools/forge_task_executor.py:4146-4157` `_ordre_repli_pour(source, ecrit=True)` qui appelle `_palier_par_defaut(taille, ecrit, explicite=_opencode_demande(desc))` (4128-4139).

Règles clés :
- `_palier_par_defaut` lit taille via `_taille_tache(desc)` (défaut "M" si indéterminé). 
- Si explicite OpenCode demandé (`_opencode_demande` cherche `[opencode...]` ou `RESERVE A OPENCODE` en tête, 4141-4144) OU taille dans `_tailles_opencode_par_defaut()` (4111-4118, typiquement S/local) -> ordre = `_palier_executeurs(taille,ecrit)`.
- Sinon (cas majoritaire M/L sans demande explicite) :
  - si M et pas d'écriture -> `("ANTIGRAVITY",) + _ORDRE_HORS_OPENCODE` (4137)
  - sinon -> `_ORDRE_HORS_OPENCODE` (4138)
- `_ORDRE_HORS_OPENCODE = ("CLAUDE_HEADLESS", "MISTRAL")` (4105)
- `_palier_executeurs` pour M avec écriture ou cas général renvoie `_OPENCODE_ECRITURE` = `("OPENCODE_GPTOSS", "OPENCODE_NEMOTRON", "OPENCODE_GLM")` (4101, 4120-4126) - **ne contient pas OPENCODE_DEFAUT2..5**

De plus `config/opencode_instances.json` liste bien `OPENCODE_DEFAUT2-5` comme instances OpenCode séparées (modele vide / défaut OpenCode). Ils sont dans `_instances_opencode()` donc considérés comme famille OpenCode (`_est_opencode()` retourne True s'ils commencent par OPENCODE_ ou sont dans le registre), mais ils **ne figurent ni dans `_OPENCODE_ECRITURE` ni dans `_ORDRE_HORS_OPENCODE`**. L'ordre par défaut pour la plupart des tâches M réaffectées va donc directement vers `CLAUDE_HEADLESS,MISTRAL` sans jamais considérer les DEFAUTn.

## Dans quel cas « aucun vivant » est rendu à tort (UNKNOWN n'est pas NON)
`_reaffecter()` ne conclut "aucun vivant" que si `vivants` est vide après filtrage (4440-4441). Causes possibles à tort :
1. **Ordre exclut les cibles** (le cas ci-dessus) : ce n'est pas "aucun vivant", c'est "aucun candidat dans l'ordre de réaffectation choisi". Le message est techniquement vrai au sens du filtre, mais peut être trompeur s'il est interprété comme "tous éteints".
2. **Heartbeat non frais** (`_executeur_bat`, 4085-4095): lit `sandbox/task_executor_<slug>.heartbeat` (ou `task_executor.heartbeat` si pas d'agent_filter), parse timestamp `ts` et exige `0 <= age <= 3*POLL_INTERVAL`. Si le fichier est absent, illisible, timestamp malformé ou trop vieux -> retourne `False`. Un exécuteur vivant mais avec heartbeat en retard/illisible est exclu.
3. **Suspendu** (`_executeur_suspendu`, ~830-880 dans le fichier): retourne motif si marqué indisponible (TTL expiré/non expiré), si en repos coupe-circuit OpenCode, ou si registre `config/agent_identities.json` marque `suspendu`. Un statut transitoire/erroné exclut l'exécuteur.
4. **Déjà essayé** : `essayes` contient agent courant + tous vus dans trace `reaffectations` -> exclut tout historique (empêche ping-pong, correct en principe).
5. **Coupe-circuit** (4419-4426): si agent courant est OpenCode en repos, l'ordre devient `_ORDRE_HORS_OPENCODE` (force hors famille) - peut éliminer la famille entière.
6. **Problème de chargement registre/instances**: si `_instances_opencode()` ou registre illisibles, classifications peuvent dégrader.

Doctrine: "UNKNOWN n'est pas NON". Donc il faut distinguer :
- **NON (prouvé éteint/suspendu/indisponible)** : heartbeat périmé et prouvé absent/erroné de manière concluante, ou suspension explicite dans registre avec motif.
- **UNKNOWN (incertain)** : fichier heartbeat illisible/absent sans preuve de mort, registre illisible, état ambigü -> ne devrait **pas** exclure automatiquement par un "False" binaire sans journalisation explicite. Actuellement `_executeur_bat` retourne `False` sur toute exception/absence (4088, 4094) ce qui traite UNKNOWN comme NON (exclut). Idem pour d'autres filtres. C'est potentiellement source de "aucun vivant" à tort.

## Journal (occurrences)
Recherche effectuée:
- `findstr /i /n "aucun autre.*vivant|REAFFECTEE" logs/supervisor/*Executor*.log` -> aucune correspondance
- `findstr /i /n "aucun autre executeur vivant|REAFFECTEE" logs/task_executor*.log logs/*executor*.log` -> aucune correspondance  
- `grep "aucun autre executeur vivant" .` -> uniquement `tools/forge_task_executor.py:3134`

Aucune occurrence datable trouvée dans les journaux locaux accessibles dans ce worktree. Le message "aucun autre exécuteur vivant" (forme avec "exécuteur") n'apparaît que dans le log de réaffectation ligne 4462-4464 et dans le message de clôture ligne 3134. Si le 26/10 l'événement s'est produit, les logs peuvent être dans un autre emplacement (superviseur, autre machine, ou déjà rotatés/supprimés).

## Correctif PROPOSÉ (diff dans le texte)

Objectif: ne pas exclure à tort les exécuteurs dont l'état est incertain; inclure les instances DEFAUTn dans les ordres de réaffectation appropriés.

### Proposition 1: Traiter UNKNOWN comme "incertain" plutôt que NON dans les filtres
**Fichier:** `tools/forge_task_executor.py`  
**Fonction:** `_executeur_bat` (4085-4095)
```diff
 def _executeur_bat(agent: str, max_age_s: float | None = None) -> bool:
     """Le pouls de l'executeur dedie a `agent` est-il frais ? ... Absent ou illisible =
-    False : on ne pousse jamais une tache vers une file dont on ne sait pas qu'elle est videe."""
+    INCONNU : on NE pousse PAS par defaut (conservateur) MAIS on DOIT distinguer dans le log.
+    Retourne (frais_bool, etat) ou utiliser une valeur sentinelle. Minimal: logger l'incertitude."""
     max_age_s = max_age_s or 3 * POLL_INTERVAL
     try:
         d = json.loads(_hb_file(agent).read_text(encoding="utf-8"))
         ts = time.mktime(time.strptime(str(d.get("ts")), "%Y-%m-%dT%H:%M:%S"))
-    except (OSError, ValueError, TypeError, AttributeError):
-        return False
-    return 0 <= time.time() - ts <= max_age_s
+    except (OSError, ValueError, TypeError, AttributeError) as e:
+        log.debug(f"[bat] {agent}: heartbeat illisible/incertain ({type(e).__name__}) -> exclus par prudence")
+        return False  # reste conservateur; améliorer en retournant un tri-state
+    age = time.time() - ts
+    if age < 0 or age > max_age_s:
+        return False
+    return True
```
Note: Changement minimal ci-dessus. Idéalement passer à tri-state (VIVANT/INCONNU/MORT) et en cas d'INCONNU, soit tenter avec garde, soit au moins logger clairement "état inconnu" vs "prouvé mort". Le message actuel agrège tout dans "aucun autre exécuteur vivant" ce qui masque UNKNOWN.

### Proposition 2: Inclure OPENCODE_DEFAUT2..5 dans les ordres de réaffectation
**Fichier:** `tools/forge_task_executor.py`  
**Lignes:** 4101-4106, 4120-4139

```diff
-# PALIER (decision owner 18/10) : par taille ET capacite d'ecriture. AGY et WORKER_CODE n'ecrivent pas de fichier sous
-# sandbox (3 non-livraisons « SUCCESS » mesurees le 18/10) ; Codex hors chaine (quota quasi nul, owner). Le palier L
-# remonte au CLI pilote (Claude) : aucun executeur autonome ne le sert.
-_OPENCODE_ECRITURE = ("OPENCODE_GPTOSS", "OPENCODE_NEMOTRON", "OPENCODE_GLM")
+# PALIER (decision owner 18/10) : par taille ET capacite d'ecriture. AGY et WORKER_CODE n'ecrivent pas de fichier sous
+# sandbox (3 non-livraisons « SUCCESS » mesurees le 18/10) ; Codex hors chaine (quota quasi nul, owner). Le palier L
+# remonte au CLI pilote (Claude) : aucun executeur autonome ne le sert.
+# 2026-10-27: inclure instances DEFAUT supplémentaires (opencode_defaut2-5) pour éviter "aucun autre exécuteur vivant" alors qu'elles existent.
+_OPENCODE_ECRITURE = ("OPENCODE_GPTOSS", "OPENCODE_NEMOTRON", "OPENCODE_GLM",
+                      "OPENCODE_DEFAUT2", "OPENCODE_DEFAUT3", "OPENCODE_DEFAUT4", "OPENCODE_DEFAUT5")
 # 24/10 (mesure : 5 echecs OpenCode sur ~8, reaffectations en chaine GPTOSS -> GLM -> GLM) : hors de la famille
 # OpenCode, la reaffectation va d'abord a CLAUDE_HEADLESS, puis a MISTRAL -- jamais a un autre OpenCode adosse au
 # meme fournisseur gratuit surcharge.
 _ORDRE_HORS_OPENCODE = ("CLAUDE_HEADLESS", "MISTRAL")
```

Alternative plus dynamique: construire `_OPENCODE_ECRITURE` depuis `_instances_opencode()` en filtrant les clés OPENCODE* (et exclure celles explicitement suspendues/coupées). Plus robuste que liste statique.

```diff
+def _opencode_ecriture_ordre() -> tuple:
+    try:
+        inst = _instances_opencode()
+        # prioriser ceux historiques, puis ajouter DEFAUTn
+        base = ["OPENCODE_GPTOSS", "OPENCODE_NEMOTRON", "OPENCODE_GLM"]
+        extra = [k for k in inst.keys() if k.upper().startswith("OPENCODE_") and k.upper() not in base]
+        # ordre stable
+        ordre = []
+        for k in base + sorted(extra):
+            ku = k.upper()
+            if ku in inst and ku not in ordre:
+                ordre.append(ku)
+        return tuple(ordre)
+    except Exception:
+        return ("OPENCODE_GPTOSS", "OPENCODE_NEMOTRON", "OPENCODE_GLM",
+                "OPENCODE_DEFAUT2", "OPENCODE_DEFAUT3", "OPENCODE_DEFAUT4", "OPENCODE_DEFAUT5")
+
-_OPENCODE_ECRITURE = ("OPENCODE_GPTOSS", "OPENCODE_NEMOTRON", "OPENCODE_GLM",
-                      "OPENCODE_DEFAUT2", "OPENCODE_DEFAUT3", "OPENCODE_DEFAUT4", "OPENCODE_DEFAUT5")
+_OPENCODE_ECRITURE = _opencode_ecriture_ordre()
```

### Proposition 3: Améliorer le log pour distinguer "pas dans ordre" vs "dans ordre mais aucun vivant"
**Fichier:** `tools/forge_task_executor.py`  
**Lignes:** 4440-4464

```diff
-        essayes = {de} | {t.get("de") for t in trace} | {t.get("vers") for t in trace}
-        vivants = [a for a in (ordre or _ORDRE_REPLI)
-                   if a not in essayes and _executeur_bat(a) and not _executeur_suspendu(a)]
+        ordre_eff = ordre or _ORDRE_REPLI
+        essayes = {de} | {t.get("de") for t in trace} | {t.get("vers") for t in trace}
+        candidats = [a for a in ordre_eff if a not in essayes]
+        vivants = []
+        exclus = []
+        for a in candidats:
+            if _executeur_suspendu(a):
+                exclus.append((a, "suspendu"))
+                continue
+            if not _executeur_bat(a):
+                exclus.append((a, "bat/heartbeat_incertain"))
+                continue
+            vivants.append(a)
         vers = vivants[0] if vivants else None
         ...
         if not vers:
-            log.warning(f"  {str(task['id'])[:24]} : {de} ne peut pas la prendre ({motif}) et AUCUN autre executeur "
-                        f"vivant hors {sorted(x for x in essayes if x)} -- laissee chez {de}")
+            log.warning(f"  {str(task['id'])[:24]} : {de} ne peut pas la prendre ({motif}) | ordre={ordre_eff} | essayes={sorted(essayes)} | "
+                        f"candidats_non_essayes={candidats} | exclus={exclus} | AUCUN VIVANT DANS L'ORDRE -- laissee chez {de}")
             return None
```

Cela permettrait de distinguer "ordres sans DEFAUTn" vs "DEFAUTn exclus pour cause heartbeat/suspension".

## NR proposé (Non-Régression)
Ajouter test NR pour ce scénario :
- `tests/nr/test_reaffectation_defaut_instances_nr.py`
  - Créer tâche M avec écriture, agent = OPENCODE_GPTOSS en échec (motif déclenchant réaffectation)
  - S'assurer que OPENCODE_DEFAUT2/3/4/5 sont candidats dans l'ordre par défaut (ou dans ordre effectif)
  - Simuler heartbeats frais pour DEFAUTn, pas suspendus
  - Vérifier que réaffectation choisit un DEFAUTn si GPTOSS/GLM/NEMOTRON indisponibles/suspendus
  - Vérifier que message log distingue "pas dans ordre" vs "exclus par état"

## Conclusion
Le principal facteur est l'ordre de réaffectation par défaut (`_palier_par_defaut` pour M sans demande explicite -> `_ORDRE_HORS_OPENCODE`) qui exclut toute la famille OpenCode y compris OPENCODE_DEFAUT2-5. Les DEFAUTn ne sont donc **jamais choisis** par construction pour la majorité des tâches réaffectées, même s'ils sont vivants. Quand tous les candidats dans l'ordre sont exclus (essayés, sans heartbeat frais, suspendus), `_reaffecter` loggue "aucun autre exécuteur vivant" ce qui est littéralement vrai pour l'ordre filtré mais peut être interprété à tort comme "aucun exécuteur vivant dans le système". Le correctif le plus direct est d'inclure les instances DEFAUTn dans `_OPENCODE_ECRITURE`/ordre OpenCode par défaut, ou de construire l'ordre dynamiquement depuis `_instances_opencode()`. Parallèlement, améliorer le logging pour lever l'ambiguïté et traiter explicitement UNKNOWN vs NON.
