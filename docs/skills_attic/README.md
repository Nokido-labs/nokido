# Skills archivées — HORS du chemin de chargement

Ce dossier est volontairement **en dehors** de `docs/skills/`, qui est la racine
lue par les CLI (Claude Code, Antigravity, Cline, Codex) via la jonction
`.agents/skills` -> `docs/skills`.

## Pourquoi pas un préfixe `_attic_` sur place

C'était la situation avant le 2026-08-11, et elle ne marchait pas. Le préfixe
portait sur le **nom du dossier** ; le champ `name:` interne du `SKILL.md`, lui,
gardait son identité vivante. Résultat : cinq skills archivées se déclaraient
toujours sous des noms actifs (`laforge-models`, `laforge-rescue`,
`laforge-skills`, `nokido`), dont une **collision exacte** avec la skill vivante
`forge-veille-approfondie`. Un chargeur qui indexe par `name:` pouvait servir la
version morte sans le moindre signal.

Le préfixe échappait en plus à la moitié des filtres du dépôt, qui ne sont pas
équivalents :

    "_attic" in str(chemin)        -> attrape  _attic_laforge-models
    "_attic" not in chemin.parts   -> NE l'attrape PAS (la partie vaut
                                      "_attic_laforge-models", pas "_attic")

Sortir les dossiers de l'arborescence lue ne suppose rien du comportement de
chaque chargeur tiers. C'est la seule garantie qui tienne.

## Règle

Une skill retirée du service **sort d'ici**, elle n'est pas préfixée sur place.
Rien n'est supprimé : git rend le déplacement réversible.

## Le retrait doit aussi se déclarer : `retires.json` (2026-10-14)

Sortir le dossier ne suffisait pas. Le 2026-08-11, neuf skills absorbées par
`forge-core`, `forge-models` et `forge-veille-approfondie` avaient quitté
`docs/skills/`, mais leurs copies étaient restées dans `~/.claude/skills`. Le
2026-09-26, `forge_skill_sync --apply` a pris ces copies pour des skills nées
côté CLI et les a rapatriées dans le canonical. Ce n'était pas une décision,
c'était un effet de bord.

`retires.json` est le registre qui ferme ce chemin. Une skill qui y figure :

- n'est plus rapatriée depuis une copie CLI ;
- voit ses copies CLI mises de côté par `--apply`, dans
  `sandbox/skill_sync_mis_de_cote/`. Elles ne sont pas supprimées et
  `--rollback` les remet ;
- ne peut plus porter de déclencheur dans `config/skill_triggers.json`
  (vérifié par `tools/forge_skill_hint.py --verifier`).

Les dossiers `_attic_*` ne disent rien du retrait : `_attic_nokido` et
`_attic_forge-veille-approfondie` portent le nom d'une skill vivante. Seul le
registre fait foi.

Le 2026-10-14, huit skills y sont entrées (`forge-autonomie`,
`forge-cognitive-sync`, `forge-env`, `forge-hub`, `forge-ops`,
`forge-pipeline`, `forge-quota`, `forge-route`) puis en sont ressorties le même
soir sur décision owner. Le retrait avait été décidé sur leur description et
leur compteur d'usage, sans lire leur contenu, au motif qu'elles étaient
absorbées par `forge-core`. Or `forge-core` n'était déployée chez aucun agent :
elle est réservée à Gemini, et l'anneau de Gemini dans le sync l'en exclut. Le
contenu des huit n'était donc plus lisible par personne.

Règle qui en sort : on n'inscrit une skill ici qu'après avoir lu son contenu,
nommé l'intention qui l'a fait écrire, et vérifié où ce contenu vit ailleurs,
chez quel agent. Un compteur d'usage à zéro dit qu'une skill n'a pas été
appelée, pas qu'elle est inutile.
