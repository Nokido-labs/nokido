# UI Kit — Nokido Hub

Recréation haute-fidélité du **hub Nokido** : le point d'entrée unique de la superapp souveraine. Compose les primitives du design system (`window.NokidoDesignSystem_bdc2ac`).

## Écrans / vues (interactifs)

- **Accueil** — Cap en cours + maturité du persona en tête, puis la **grille de modules** homogène (Transport, Santé, Finance, Loisir, Achat, Création, Dev, Domotique, Jeux « bientôt »). Chaque carte porte son accent de domaine, sa provenance et une bascule activer/désactiver.
- **Intention longue (Cap)** — horizon (le cap en une phrase) → jalons → 112 étapes, avec connecteurs, états, provenance et anneau d'intégrité par étape. Actions : valider, bifurquer, réordonner.
- **Maison** — domotique local-first : bandeau de garantie « ne dépend jamais du cloud », scènes (déclencheurs), appareils (capteurs/actionneurs) avec statut.
- **Mémoire du persona** — liste de souvenirs, chacun avec provenance + anneau, bouton « Masquer » (retire l'entrée de l'affichage seulement ; aucune révocation côté persona — décision owner du 25/09).
- **Souveraineté** — curseur de puissance allouée (confidentialité ↔ puissance ↔ coût ↔ latence en direct) + journal de provenance.

Le curseur de souveraineté (sidebar + vue Souveraineté) pilote en direct le marqueur de provenance de la topbar et la jauge.

## Fichiers

- `index.html` — entrée interactive (navigation, bascules, curseur live). Largeur de conception 1280px.
- `hub-shell.ref.jsx` — sidebar souveraine (nav + jauge + identité) et topbar.
- `hub-views.ref.jsx` — les cinq vues.

## Composants réutilisés

`Card`, `Button`, `Badge`, `StatusPill`, `ProvenanceBadge`, `SovereigntyGauge`, `PowerSlider`, `ModuleCard`, `CapStep`, `TextInput` — tous issus du design system, aucun re-implémenté.

## À faire / pistes

- Variante **mobile** (geste, glance) : la même grille recomposée en colonne, scènes domotique en accès rapide.
- Parcours **Onboarding souverain** et **Exposer son hub d'IA** (non encore maquettés).
