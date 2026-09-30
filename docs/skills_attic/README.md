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
