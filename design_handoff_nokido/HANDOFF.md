# Nokido Design System — Handoff Claude Code

Package autonome du **Nokido Design System** destiné à un développeur (ou à Claude Code) pour produire des interfaces fidèles à la marque Nokido.

> Nokido : superapp **souveraine, local-first** / hub personnel d'IA. Règle n°1 du design : **toujours montrer où vit le calcul** (provenance local / hybride / distant) et l'**anneau d'intégrité** d'une donnée. UI en **français**, thème sombre par défaut, accent violet `#774AFF`.

## Démarrage

1. Lier la CSS globale : `<link rel="stylesheet" href="styles.css">` — c'est le **seul** point d'entrée CSS (il `@import` tous les tokens + fonts).
2. Charger le runtime des composants : `<script src="_ds_bundle.js"></script>` (après React 18 + Babel standalone).
3. Utiliser un composant : `const { Button, RingMeter } = window.NokidoDesignSystem_bdc2ac;`

Exemple minimal dans `ui_kits/*/index.html` (à recopier).

## Convention de nommage de CE package

Pour éviter toute collision avec le compilateur de design system, les sources ont été renommées :
- `*.ref.jsx` — **référence** d'un composant ou écran (lecture/copie ; l'`export` a été retiré des composants). La version exécutable vient de `_ds_bundle.js`.
- `*.props.d.ts.txt` — le contrat de props (TypeScript) en texte.
- Les commentaires `@dsCard` / `@startingPoint` ont été retirés des HTML.

Pour reprendre en production : restaure les noms PascalCase (`button.ref.jsx` → `Button.jsx`), remets `export function`, et recompile avec ton outillage.

## Arborescence

- `styles.css` + `tokens/` — couleurs (provenance, anneaux 11 rings, domaines), thèmes sombre/clair/auto, typo, espacement, effets.
- `guidelines/` — cartes-spécimens (couleurs, type, espacement, brand/logo).
- `components/` — 12 primitives : Button, Card, TextInput, Select, Badge, StatusPill, ProvenanceBadge, SovereigntyGauge, PowerSlider, ModuleCard, CapStep, **RingMeter**.
- `ui_kits/` — écrans complets : `login` · `hub` (PC + `mobile.html`) · `onboarding` · `composer` · `webhub` (portail :7400 centralisé : Setup souverain, Rings, Chat, Launcher, Anatomie, Network, MCP Lab, RAG, Feed, Status, Reports, Pipeline, Swarm, Debate).
- `assets/` — `laforge-mark.svg` (marteau + enclume + éclair), `laforge-prefs.js` (prefs persistantes), favicon.
- `cover.html` — page de garde / index.
- `readme.md` — guide complet (fondations, contenu, iconographie, manifeste). **Lis-le en premier.**
- `SKILL.md` — mode d'emploi Agent Skill.

## Règles essentielles

- **Provenance partout** : `<ProvenanceBadge origin="local|hybrid|remote" ring="draft|verified|gold" />` sur chaque réponse/donnée/action.
- **11 rings** : Ring 0 (Lois absolues, centre) → Ring 10 (Corrections de Cap). Plus on est au centre, plus c'est souverain.
- **Thèmes** : attribut `data-theme="dark|light|auto"` sur `<html>`.
- Pas de pub, pas de reco biaisée ; santé/finance = local forcé.

Ouvre `cover.html` ou n'importe quel `ui_kits/*/index.html` dans un navigateur pour voir le rendu.
