---
name: forge-code-governance
description: "À utiliser avant de lire, créer ou modifier du code ou un fichier du dépôt Nokido, depuis toute surface : trouver l'existant, lire sans tout charger, réclamer le fichier, écrire par la voie gouvernée, prouver l'effet, committer proprement. Donne l'ordre anti-dup, la lecture fenêtrée, governed_edit et ses pièges, verrous et NR."
---

# forge-code-governance — lire, écrire, prouver dans le dépôt Nokido

Créée le 15/10. Codex, qui a audité les skills sur le code vivant, l'a classée en tête :
« les primitives existent ; il manque un parcours opératoire commun ». Gemini web et AGY
l'avaient aussi demandée. Tout ce qui suit a été pratiqué et vérifié le 15/10.

## 1. Avant d'écrire : trouver l'existant

1. `introspect question=…`, puis `tools/forge_retrieval_sweep.py <terme>`, puis
   `tools/forge_symptom_index.py --ask <symptôme>`, puis les fiches du domaine
   (détail : skill `forge-memory-ssot`).
2. Étendre le module qui porte déjà le contrat plutôt qu'en créer un second.
3. Un nouveau `forge_*.py` déclare son organe en début de ligne, dans les 12 000
   premiers caractères : `__FORGE_COLOR__ = 'organe/role'`. Écrivain :
   `tools/forge_organ_declare.py` ; vérification : le census.
4. `hook_recon_first` refuse UNE fois sans consultation fraîche, et cite les enquêtes
   passées sur le même terme : les lire, puis relancer l'appel.

## 2. Lire sans tout charger

| besoin | outil |
|---|---|
| architecture d'un fichier .py | `get_file_skeleton` |
| une fonction ou une classe | `read_function_body` |
| une plage de lignes | Read `offset`/`limit` (150 lignes au plus) |
| plusieurs fichiers d'une zone | `forge_deep_explore` (recon locale, digest fichier:ligne) |
| un symbole dans le dépôt | `git -c safe.directory=* -C <dépôt> grep -n …` par `run shell` |

- Garde de lecture : 7 lectures ou recherches Nokido en 15 min, puis blocage (message
  du garde côté Claude Code, reçu le 15/10 ; seuil des autres surfaces INCONNU). Passer
  au squelette, ou extraire une plage par `findstr /n` via `run shell`.
- Jamais de balayage récursif du dépôt (`rglob`, `dir /s`) : le hub tue le processus.
  Demander le chemin au module propriétaire de la ressource.

## 3. Écrire : `governed_edit`, seule voie dans le dépôt

- Il vérifie l'AST des `.py`, scanne les secrets, réclame le fichier (tree_lock) et
  relit le disque. Côté Claude Code, Write/Edit natifs y sont refusés ; les autres
  surfaces appliquent la règle par discipline. Hors du dépôt : outils natifs.
- Blocs SEARCH/REPLACE par défaut ; le SEARCH doit être exact (plusieurs lignes possibles).
- **Pièges** :
  - il écrit en CRLF ; git normalise en LF au commit ;
  - vers 16 Ko, un bloc trop gros peut être abandonné EN SILENCE avec une réponse
    `ok` (mesuré le 06/10) : REPLACE de 6 Ko au plus, comparer `bytes`, puis
    `git diff --numstat` (ajouts et retraits attendus ; le 15/10, des blocs courts sur
    des fichiers de 25 à 388 Ko sont passés intacts, vérifiés ainsi) ;
  - si le retour liste `capacites_prouvees_touchees`, rejouer les NR qu'il nomme
    avant de committer.

## 4. Verrous et arbre partagé

- Avant d'éditer : `blackboard_read_zone zone_name=tree_locks`. Un fichier réclamé
  par un autre agent ne s'édite pas.
- Publier son claim (`blackboard_propose_fact zone_name=tree_locks
  key=<agent>_<sujet>`), puis le libérer (`LOCK_RELEASED`) à la fin.
- Un fichier modifié hors claim dans l'arbre partagé empêche tous les autres de
  rattacher un verdict de CI à un commit.

## 5. Prouver

- Un correctif = un NR dans `tests/nr`, qui emprunte le chemin réel (point d'entrée,
  drapeau CLI), déclaré dans `PURE_TESTS` de `tools/ci_local.py` : un test non
  déclaré n'est pas joué.
- Rejeu ciblé (secondes) : `PYTHONNOUSERSITE=1`, `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1`,
  l'interpréteur du hub (`miniforge3/envs/laforge_py314`), `-p pytest_timeout`,
  `--basetemp` sous `sandbox/workspace`.
- La validation AST des `.py` est faite par le hook PostToolUse : ne pas la doubler.
- Le `rc` dit qu'un programme s'est terminé, pas qu'il a fait son travail : relire
  l'artefact. Une recherche vide ne prouve pas une absence.
- CI de référence ou complète : jamais sans le GO de l'owner.

## 6. Committer

- Tôt et petit : `git add -- <fichiers nommés>`, jamais `git add -A` ni `commit -am`.
- Message dans un fichier, puis `git commit -F <fichier>` ; jamais de `Co-Authored-By`.
- Le pre-commit scanne les secrets et passe les gates (alignement, récidive « chemin
  d'erreur muet » en avertissement).
- Pousser est un geste distinct, sur GO de l'owner.
