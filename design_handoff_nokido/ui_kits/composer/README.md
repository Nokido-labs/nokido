# UI Kit — Composer son app

Parcours **« Compose ton app »** : l'utilisateur assemble SA superapp à partir des sections disponibles. Met en œuvre le principe *superapp composable* — le produit est un méta-conteneur de modules, pas une app figée.

## Contenu

- **Catalogue** (gauche) : les sections disponibles, ajoutables d'un clic.
- **Ta vue** (droite) : la grille personnelle. Pour chaque section : **épingler / désépingler**, **réordonner** (haut/bas), **masquer** (retirer). Les sections épinglées remontent en tête.
- **Jauge de souveraineté** en temps réel dans la topbar : recalcule le % local selon les sections ajoutées.

Tout est local et réversible — cohérent avec « donne le contrôle ».

## Fichiers

- `index.html` — entrée interactive (PC).
- `composer-app.ref.jsx` — catalogue + vue + contrôles de composition. `CATALOG` est extensible (une entrée par domaine `--domain-*`).

## Composants réutilisés

`ModuleCard`, `Button`, `Badge`, `ProvenanceBadge`, `SovereigntyGauge`.

## À faire / pistes

- Drag-and-drop natif pour le réordonnancement (ici : flèches haut/bas).
- Plusieurs **vues** nommées (Travail, Maison, Week-end) et bascule rapide.
- Variante mobile (catalogue en bottom-sheet).
