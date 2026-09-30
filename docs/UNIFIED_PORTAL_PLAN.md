# Plan — Portail unifié :7400 = « Hub Nokido PC »

> Objectif user (2026-06-19) : **un seul point d'entrée (:7400)** surfaçant **toutes** les
> interfaces, réalisant la maquette **Hub Nokido PC** (`design_handoff_nokido/ui_kits/hub/`),
> avec **tuiles repositionnables** et **interface personnalisable par l'utilisateur**.

## Contexte / contraintes
- Web Nokido = **HTMX + Alpine + `/static/nokido.css`** (PAS de build React). La maquette
  `ui_kits/hub/*.ref.jsx` est une **spec** à porter en HTMX/Alpine + composants `.lf-*`.
- Portail actuel `:7400` = `app/web_hub/app.py` + `dashboard.html` (grille simple) + `proxy.py`
  (reverse-proxy modules) + auth JWT cookie + CSP (`csp.py`).
- `:8766` = endpoint MCP (`/mcp`) qui sert AUSSI des pages web (`/forge/rag`, `/forge/network`,
  SPAs) → **doublon UI** à résorber sous :7400.
- Souveraineté : **zéro dépendance CDN** (vendorer Lucide/Tailwind/Alpine/HTMX en `/static/`).
- Écriture repo = outils natifs (user) ; exécution = hub gouverné (sandbox). Vérif visuelle = user sur :7400.

## Interfaces à fédérer (inventaire)
Portail (A) : dashboard, launcher, mcp_lab, rbac, reports, ctf, **/netcfg**, /anatomy, /vitals,
/ui/playground, llm-dashboard(stub), /forge/feed.
Modules (B) : **Graph Explorer Cytoscape :7420 `/graph/`**, TUI :7440 (déprécié).
Externes (C) : netcfg :7500, deno :7401, **mcp-hub :8766** (+ ses pages rag/network), embedder :8099, ollama :11434.
Design-only (D) : **Hub Nokido PC** (Accueil/Cap/Maison/Persona/Souveraineté) — à bâtir.

---

## Phases

### Phase 0 — Fondations (rapide)
- [x] **Vendorer Lucide** → `/static/lucide.min.js`, retirer le `<script unpkg>` (fix icônes, souverain).
- [ ] Vendorer les autres CDN utilisés (Tailwind, Alpine, HTMX) en `/static/` + resserrer `csp.py`
      (retirer les `https://cdn.*` une fois local) → hub 100 % offline.
- [ ] Audit reverse-proxy : chaque interface atteignable depuis :7400 (route ou lien), aucun lien mort.

### Phase 1 — Shell « Hub Nokido PC » sur :7400
- Porter `ui_kits/hub/hub-shell.ref.jsx` → HTML/HTMX/Alpine : **sidebar** (nav Accueil/Cap/Maison/
  Persona/Souveraineté + jauge souveraineté + identité) + **topbar** (marqueur provenance + thème + version).
- Rendu via `dashboard_html.py` (ou nouveau `hub_shell_html.py`) avec `.lf-*` + tokens DS.
- `Accueil` remplace/englobe `dashboard.html` actuel.
- Fichiers : `app/web_hub/hub_shell_html.py` (nouveau), routes dans `app.py`.

### Phase 2 — Grille de modules = TOUTES les interfaces en tuiles
- Chaque interface = `ModuleCard` (`module-card.ref.jsx`) : accent domaine + provenance + **status dot live** + ouverture (route proxy ou nouvel onglet).
- Réutilise le **tile-gating dynamique** existant (commit 61c7a5c5) + `/status` polling.
- Catalogue de tuiles = source unique (JSON/registre) → `forge_*` ou `launcher.py`.

### Phase 3 — Tuiles repositionnables (drag & drop)
- Vendorer **SortableJS** (`/static/`) ; activer drag&drop sur `.lf-grid`.
- Persister l'ordre/masquage : `localStorage` (v1) → puis **serveur par identité** (`forge_state`/DB) (v2).
- Redimension / épingler / masquer une tuile.

### Phase 4 — Personnalisation utilisateur
- Par utilisateur : tuiles visibles, ordre, thème (dark/light/auto = déjà DS), défaut du curseur
  souveraineté, quick-links épinglés. Persistance `localStorage` → identité serveur.
- Écran « Réglages » accessible depuis la topbar.

### Phase 5 — Vues riches (brancher le réel)
- **Cap (intention longue)** : horizon→jalons→étapes + anneaux intégrité → câbler SSoT/roadmap (`forge_ssot`).
- **Maison** : domotique local-first (scènes/appareils) → réel ou stub honnête.
- **Mémoire persona** : souvenirs + provenance + « oublier » → modules persona/mémoire.
- **Souveraineté** : curseur puissance (confidentialité↔puissance↔coût↔latence) → `forge_orchestration_gate` + provenance live.

### Phase 6 — Résorber le doublon :8766 → :7400
- :8766 garde `/mcp` (endpoint MCP). Ses pages web (rag/network/SPAs) **proxiées/surfacées** sous :7400.
- Une seule porte UI = :7400.

## Risques / décisions ouvertes
- **React→HTMX** : porter les `.ref.jsx` (pas de build). Effort principal Phase 1-2.
- **Proxy d'apps hétérogènes** (Cytoscape graph, netcfg) sous une origine : iframe vs reverse-proxy par route — à trancher par interface.
- **Persistance par-utilisateur** : localStorage d'abord (simple), serveur ensuite (identité×ring).
- **Vérif visuelle** : chaque phase validée par user sur :7400 (pas d'application à l'aveugle).

## Séquencement proposé
P0 (maintenant) → P1 (shell) → P2 (grille complète) → P3 (drag&drop) → P4 (perso) → P5 (vues riches) → P6 (dé-doublon).
Chaque phase = livrable validable indépendamment.
