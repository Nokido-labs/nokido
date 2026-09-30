# Plan de consolidation UI — 1 design-system canonique

> Basé sur l'audit déterministe `sandbox/ui_audit/report.md` (12 surfaces, 16 CSS,
> 18 classes `.lf-*` dupliquées, 167 redéfinitions `:root`). But : tuer la duplication
> qui cause le whack-a-mole (icônes/styles qui cassent par endroit).

## Constat (ce qui est chargé en vrai)
- Les 12 SPAs linkent **uniquement** `/static/nokido.css` → `@import laforge-tokens.css` + `laforge-components.css`. OK, entrée unique.
- `laforge-ds/tokens/*.css` = **SOURCE** ; `laforge-tokens.css` = **build plat généré** (`forge_design_extract.py`). Relation source↔artefact = NORMALE (ne pas y toucher).
- **Vraies duplications nuisibles** :
  1. `nokido.css` redéfinit **47 tokens** déjà fournis par `laforge-tokens.css` (3ᵉ copie, override silencieux).
  2. Cartes (`.lf-card`, `.lf-icon`/`.lf-icon-*`, `.lf-grid`, `.lf-card-head/-target`, `.lf-ext-badge`, `.lf-status-dot`, `.lf-card-disabled`) définies **3×** : `laforge-components.css` + `laforge-dashboard.css` + inline `dashboard.html`.
  3. `.lf-mono` (4×), `.lf-panel` (2×).

## Cible
**1 token layer** (`laforge-tokens.css`, généré depuis `laforge-ds/tokens/`) · **1 composant layer** (`laforge-components.css`) · **1 base/élément layer** (dans `nokido.css`) · pages = `nokido.css` + inline page-spécifique minimal · **1 chargement d'icônes** (`/static/lucide.min.js`, pinné v0).

## Étapes (validables une par une)

### C1 — Tokens : 1 seule source chargée
- Retirer de `nokido.css` les **47 redéfinitions `:root`** (garder `@import` tokens+components + styles d'éléments). Le seul layer de tokens chargé = `laforge-tokens.css`.
- Vérifier : aucune page ne casse (laforge-tokens.css fournit déjà tout). `laforge-ds/styles.css` (612 o, 0 sélecteur, chargé par personne) → supprimer si confirmé orphelin.

### C2 — Composants : 1 seule def des cartes
- **Fusionner** les classes carte/icône/grille manquantes DANS `laforge-components.css` (canonique) : `.lf-grid`, `.lf-icon` + `.lf-icon-{purple,blue,cyan,green,emerald,yellow,orange,red,pink}`, `.lf-card-head`, `.lf-card-target`, `.lf-ext-badge`, `.lf-status-dot(.up/.down)`, `.lf-card-disabled`.
- Réconcilier les 2 `.lf-card` (DS vs dashboard) → 1 version canonique.
- **Supprimer** `laforge-dashboard.css` (doublon que j'ai introduit) + le gros `<style>` carte inline de `dashboard.html` (laisser le chrome portail-spécifique : `.lf-header/.lf-quick/.lf-panel`, ou les déplacer aussi).
- `.lf-mono` / `.lf-panel` → 1 seul endroit.

### C3 — Pages : inline minimal
- Les 12 SPAs gardent `nokido.css` + leur `<style>` page-spécifique, mais on **retire** des inline tout ce qui redéfinit tokens/cartes (déjà fourni par le DS). Garder seulement le layout propre à la page.
- Standardiser le `<head>` (1 helper) : `nokido.css` + `/static/lucide.min.js` pour les pages à icônes.

### C4 — Icônes : 1 chargement testé
- 1 seul `<script src="/static/lucide.min.js">` (pinné v0.544) + `lucide.createIcons()` au bon moment. Vérifier RENDU réel (résout le bug icônes en cours, proprement, une fois pour toutes).

### C5 — Shell = porte unique
- Le shell `/hub` (Phase 1) consomme le DS consolidé ; bascule `/` → `/hub`.

## Méthode d'exécution
- Édits chirurgicaux (natifs, AST-validés) + suppression des fichiers/inline dupliqués.
- Après C1+C2 : rechargement portail + **vérif visuelle user** (chaque étape).
- `forge_search_replace` (moulinette) pour les retraits inline répétitifs sur les 12 SPAs (C3).

## Risque
- Retirer les 47 redéfs de nokido.css : si une valeur y DIFFÉRAIT de laforge-tokens.css, le rendu bouge. → diff les valeurs avant suppression (garder celles qui diffèrent intentionnellement, sinon supprimer).
- Vérif visuelle obligatoire (je ne vois pas le rendu).
