# Protocole de mesure — Benchmark Hub Nokido vs CLAUDE.md / AGENTS.md statique

**Statut :** protocole (étape 1). Aucune mesure n'a été exécutée pour produire ce document.  
**Date :** 2026-10-27  
**Décision liée :** tableau noir `architecture_rules/P2_benchmark_nokido_vs_claude_md_statique_20261026`  
**Portée :** comparer (A) Nokido Hub + SSoT face à (B) un simple `CLAUDE.md` / `AGENTS.md` statique, sur les mêmes tâches croisées CLI. **Ce document ne crée pas de mesure, ne modifie aucun fichier existant, ne lance aucune mesure.**

Ce protocole vise à quantifier l'effet du contexte dynamique fourni par le hub Nokido par rapport à un fichier de règles statique. L'objectif est de décider objectivement si la voie hub apporte un gain mesurable au regard de son coût.

---

## 0. Ce que le protocole doit répondre

1. **Efficacité** : tokens consommés (entrée + sortie) pour chaque tâche croisée entre (A) et (B).
2. **Fiabilité** : nombre d'erreurs de parsing ou d'invalidité de règle par tâche.
3. **Connaissance** : rappels effectifs de règles/contraintes pertinents (comptés par tâche).
4. **Performance** : temps d'exécution (ms) par tâche, de la soumission à la réponse complète.

Trois principes pour éviter les biais :

- **Critère de décision pré-enregistré.** Les seuils sont fixés avant toute mesure (cf. §0.1).
- **Tâches croisées identiques.** Même énoncé, même contexte minimal, même grille de validation pour (A) et (B).
- **Mesure aveugle.** L'évaluateur valide contre une grille sans connaître la condition (A)/(B) lors du jugement, autant que possible.

### 0.1 Critère de décision pré-enregistré (à ratifier par l'owner AVANT la campagne)

| condition | lecture |
|---|---|
| gain tokens médian ≥ 15 % **ET** erreurs de règle ≤ 50 % de (B) **ET** rappels pertinents ≥ 120 % de (B) | hub justifié ; conserver la voie (A) |
| gain tokens 5–15 % avec moins d'erreurs ou plus de rappels | l'owner arbitre au regard de la latence/coûts |
| gain < 5 % **OU** erreurs >= (B) **OU** rappels < (B) sans gain tokens compensatoire | ne pas généraliser ; privilégier (B) ou améliorer le ciblage du hub |

Le seuil est posé avant de voir les chiffres, pour que la conclusion ne soit pas choisie après coup.

---

## 1. Périmètre

### 1.1 Conditions comparées

| condition | description | périmètre |
|---|---|---|
| **(A) Hub Nokido** | Accès au hub MCP `:8766` (SSoT/mémoire/tableau noir/outils) selon les règles de surface. Contexte fourni par le hub selon la tâche. | voie gouvernée (règles partagées + contexte dynamique) |
| **(B) CLAUDE.md / AGENTS.md statique** | Uniquement le fichier statique `CLAUDE.md` ou `AGENTS.md` présent dans le worktree au moment du run (tel qu'il existe). Aucun appel hub/tool contextuel au-delà de ce qui est explicitement requis. | contexte figé |

### 1.2 Tâches croisées (jeu figé)

Le jeu de tâches est figé dans `manifest.json` avant campagne. Catégories minimales :

| id | catégorie | but |
|---|---|---|
| T01 | `convention` | Appliquer une convention locale (nommage/imports/format) |
| T02 | `gouvernance` | Respecter une contrainte irréversible/gouvernée |
| T03 | `recherche` | Situer un symbole/module sans halluciner |
| T04 | `edition` | Proposition d'édition chirurgicale conforme |
| T05 | `securite` | Repérer un risque/opsec sans fuite |

Chaque tâche est rédigée de manière identique pour (A) et (B). Aucune tâche ne requiert un accès réseau sortant non autorisé. Le jeu total est défini et gelé avant exécution.

### 1.3 Hors périmètre

- Génération de gros artefacts non contraints (hors gouvernance)
- Tâches nécessitant un service tiers indisponible
- Comparaisons multi-modèles (même modèle CLI si possible)
- Mesure de latence réseau inter-hub (hors surface utilisée)

---

## 2. Pré-enregistrement (OBLIGATOIRE)

Avant toute mesure, remplir et figer dans `manifest.json` :

| variable | source | requis |
|---|---|---|
| `env_snapshot` | variables d'environnement pertinentes (sans valeurs secrètes) | oui |
| `nokido_hub_version` | `/version` ou commit du hub si accessible | oui |
| `claude_md_hash` | `sha256` du fichier `CLAUDE.md` utilisé (le cas échéant) | oui |
| `agents_md_hash` | `sha256` du fichier `AGENTS.md` utilisé | oui |
| `rule_files_hashes` | `sha256` des fichiers de règles chargés (si identifiables) | oui |
| `max_token_budget` | budget maximal autorisé pour la campagne | oui |
| `cli_name` | nom du CLI utilisé (ex. claude/codex/gemini/copilot) | oui |
| `model_id` | identifiant modèle utilisé pour les runs | oui |
| `worktree` | chemin relatif du worktree | oui |
| `git_commit` | `git rev-parse HEAD` | oui |
| `task_set_hash` | `sha256` du jeu de tâches gelé | oui |
| `timestamp_pre` | horodatage ISO8601 avant premier run | oui |

**Règle :** aucun run ne démarre tant que le pré-enregistrement n'est pas complet et figé. Si une variable requise est inconnue, elle est consignée comme `UNKNOWN` (jamais déduite).

---

## 3. Banc de mesure

### 3.1 Environnement figé
- Même machine/VM, même compte, même horloge (|offset| > 1s → invalide, cf. §4).
- Même worktree état (commit figé) pour toutes les conditions.
- Réseau : selon politique surface (pas d'egress non requis). État réseau enregistré.
- Antivirus/updates : état consigné en tant que variante si changeant.

### 3.2 Observateurs
- **O_tokens** : compteur tokens entrée+sortie exposé par le CLI (source unique si disponible). Sinon extraction traçable depuis la session. Toujours enregistrer la méthode.
- **O_time** : chronomètre monotone (ms) entre soumission de tâche et fin de réponse.
- **O_rules** : évaluation manuelle/structurée contre grille (cf. §3.3). Erreurs de parsing/règle comptabilisées.
- **O_recall** : nombre de rappels de règles/contraintes pertinents correctement invoqués (grille par tâche).

---

## 4. Métriques obligatoires

Pour chaque tâche croisée `(task_id, condition)` :

| métrique | unité | définition | source |
|---|---|---|---|
| `tokens_in` | tokens | tokens d'entrée comptabilisés | O_tokens |
| `tokens_out` | tokens | tokens de sortie comptabilisés | O_tokens |
| `tokens_total` | tokens | `tokens_in + tokens_out` | calculé |
| `latency_ms` | ms | temps monotone soumission→réponse | O_time |
| `parse_errors` | entier | erreurs de parsing/structure de réponse invalidant l'exécution | O_rules |
| `rule_invalidity` | entier | violations explicites de règle gouvernée détectées | O_rules |
| `rule_recall` | entier | rappels pertinents de règles/contraintes (corrects) | O_recall |
| `rule_miss` | entier | règles pertinentes non rappelées alors attendues | O_recall |
| `hallucination_flag` | bool/int | affirmation non sourçable sur le code (file:line requis) | O_rules |

**Agrégats requis :** médiane, p50/p95 (si n>=3), min/max, et nombre de runs valides par `(task_id, condition)`. Toute valeur manquante est `UNKNOWN`, jamais `0`.

---

## 5. Critères d'invalidité

| # | test | conséquence |
|---|---|---|
| I1 | Pré-enregistrement incomplet ou hashes de règles/tâches manquants | campagne annulée |
| I2 | Même tâche non identique entre (A) et (B) (diff constaté) | run invalidé |
| I3 | Changement de modèle/CLI entre runs d'une même paire sans justification | paire invalidée |
| I4 | Horloge |offset| > 1s ou sommeil/hibernation | run invalidé |
| I5 | Tokens non traçables (méthode non enregistrée) | métrique `tokens_*` = UNKNOWN ; si tous UNKNOWN → run invalidé |
| I6 | Évaluation sans grille (O_rules/O_recall non remplis) | run invalidé |
| I7 | Tentative de balayage interdit (ex. `%NOKIDO_DATA%\embeddings.db`) | campagne annulée, incident consigné |
| I8 | Utilisation de valeur caviardée comme valeur réelle (`[IP_INTERNAL_n]`, `[PATH_WIN_n]`, `[SECRET_n]`) | run invalidé |
| I9 | >= 1 `hallucination_flag` sans source `file:line` traçable | run invalidé (ou non comptabilisé comme valide) |
| I10 | Budget tokens dépassé sans autorisation | run marqué `OVERRUN`, à justifier ou exclure |

---

## 6. Livrables

Structure obligatoire :

```text
docs/enquetes/benchmark_hub_vs_claude_md_20261027/
  manifest.json        # pré-enregistrement + hashes + config
  task_set.json        # jeu de tâches gelé + grille par tâche
  runs/
    run_001/
      A/               # condition hub
        T01.json
        ...
      B/               # condition statique
        T01.json
        ...
  results.csv          # agrégats par (task_id,condition)
  evaluation.md        # synthèse vs seuil pré-enregistré
```

`manifest.json` doit contenir au minimum : `pre_register` (section 2), `conditions`, `task_set_hash`, `git_commit`, `worktree`, `timestamp_pre`, `evaluator`.  
Chaque fichier de run doit référencer la source des compteurs tokens et l'heure monotone utilisée.

---

## 7. Ordre d'exécution

1. **Pré-enregistrer** : remplir section 2, calculer hashes, figer `task_set.json`, horodater `timestamp_pre`.
2. **Geler l'environnement** : snapshot/état, consigner CLI/modèle/offset.
3. **Calibrer** : dry-run sur 1 tâche pour valider compteur tokens et chronomètre.
4. **Exécuter croisées** : pour chaque tâche, exécuter (A) puis (B) (ou ordre randomisé figé), enregistrer immédiatement.
5. **Évaluer** : remplir grille O_rules/O_recall sans connaissance de l'ordre si possible, sourcer toute affirmation.
6. **Vérifier invalidités** : appliquer §5, exclure runs invalides, journaliser raisons.
7. **Synthétiser** : produire `results.csv` et `evaluation.md` en comparant **uniquement** aux seuils §0.1.
8. **Clôturer** : ne pas modifier les fichiers de mesure ; conclure objectivement.

**Règle finale :** Aucune mesure n'est lancée dans cette étape. Seul le protocole est créé. Chaque affirmation sur le code doit être sourcée `file:line`. Tout jeton `[IP_INTERNAL_n]/[PATH_WIN_n]/[SECRET_n]` est un jeton de caviardage, jamais une valeur.

{"intent":"OK_DONE","pointer_ref":"bb:architecture_rules/P2_benchmark_nokido_vs_claude_md_statique_20261026","commit_message":"docs(enquetes): add benchmark hub vs claude.md protocol"}

