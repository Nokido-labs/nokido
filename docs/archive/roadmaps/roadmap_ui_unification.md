# Roadmap — Unification des interfaces web Nokido sur le **style netcfg**

**Date** : 2026-04-30
**Auteur** : CLAUDE (Nokido)
**Cible exécutants** : Gemini CLI déporté, qwen2.5-coder local (UI), Codex CLI (frontend dev).

---

## 0. Objectif unique

Unifier visuellement et architecturalement les **6+ interfaces web Nokido** actuellement disparates en s'alignant sur le style de **netcfg-agent** (`:7500`), tout en préservant la fonctionnalité de chacune. Une seule charte, un seul boot, une seule sidebar de navigation. Zéro doublon CSS/JS.

**Non-objectif** : ne PAS refaire les UIs from scratch. On extrait du commun, on factorise, on garde les vues métier.

---

## 1. Inventaire des UIs existantes (audit 2026-04-30)

| UI | Port | Source | Rôle | État stylistique |
|---|---|---|---|---|
| netcfg-agent UI | `:7500` | `netcfg/views.py` (uvicorn) | Topologie réseau, audit, terminal SSH | **référence** |
| forge_graph_explorer | `:7474` | `app/forge_graph_explorer.py` (FastAPI + Cytoscape.js) | Exploration graphes, GNN, layouts | autonome |
| nokido_hub | `:8766` | `tools/nokido_hub.py` (Starlette MCP) | endpoints hub MCP — **pas une UI**, ne pas toucher |
| netcfg-agent-mcp | `:8767` | netcfg.exe v0.1.3 | endpoints MCP — pas une UI |
| web_hub dashboard | (statique) | `app/web_hub/dashboard.html` + `rag_dashboard.html` + `sidebar.html` | dashboard généraliste + RAG monitor | **untracked**, ébauche récente |
| web_hub app | configurable | `app/web_hub/app.py` (FastAPI) | sert dashboard + RAG views | autonome |
| CTF runner | configurable | `app/ctf_web/app.py` (FastAPI) | CTF challenges runner | autonome |
| router_gateway | `GATEWAY_PORT` | `app/forge_router_gateway.py` | gateway LLM router visualizer | autonome |
| recon_silo | (statique) | `recon_silo/_ui.html` | UI silo recon | très basique |
| docs html | — | `docs/nokido_demo.html`, `nokido_presentation.html`, `nokido_ui.html` | présentation projet | **archive**, ne pas toucher |

**Constat** : ~6 UIs vivantes, 4 ports différents, styles probablement divergents (à confirmer Phase 0).

---

## 2. Contraintes (immuables)

| # | Règle | Vérification |
|---|---|---|
| C1 | **netcfg/views.py + ses templates = source de vérité du style.** Ne pas inventer une nouvelle palette | comparer screenshots avant/après |
| C2 | **Pas de framework CSS lourd ajouté** (pas de Bootstrap/Tailwind si netcfg utilise du custom). On suit ce qui existe | `git diff package.json` doit rester vide |
| C3 | **Pas de breaking change fonctionnel** : chaque UI doit continuer à servir ses endpoints actuels | tests E2E par UI (smoke) |
| C4 | **Charte centralisée** : CSS commun dans `app/web_hub/static/nokido.css`, JS commun dans `nokido.js`. Chaque UI importe ces 2 fichiers | grep `<link rel="stylesheet"` doit pointer vers `/static/nokido.css` partout |
| C5 | **Sidebar unifiée** : composant HTML unique réutilisé via `<iframe>` ou inclusion server-side | 1 seul source pour la sidebar |
| C6 | **Conservation des ports** existants — pas de migration `:7474 → :7500` | grep ports inchangés |

---

## 3. Phases

### Phase 0 — Audit du style netcfg (1h)

**À faire** :
1. `head -100 netcfg/views.py` puis lister les templates Jinja2/static référencés.
2. Extraire la palette : `grep -rE 'color:|background:|--' netcfg/static/*.css` → liste des couleurs canoniques.
3. Identifier le framework CSS (custom, Bulma, Pico.css, etc.) et la grille (CSS Grid / Flexbox).
4. Identifier la typographie (font-family, tailles).
5. Faire un screenshot de la page d'accueil netcfg `:7500`.
6. Documenter dans `docs/style_netcfg.md` : palette + fonts + grille + composants (boutons, cards, terminal embed, tables).

**Livrable** : `docs/style_netcfg.md` (~50 lignes) + 1 screenshot référence.

**Acceptance** : un développeur peut écrire un `<button>` "style netcfg" en lisant uniquement `style_netcfg.md`.

---

### Phase 1 — Charte commune (2h)

**À faire** :
1. Créer `app/web_hub/static/nokido.css` qui contient :
   - Custom properties (`:root { --laforge-bg: ...; --laforge-fg: ...; }`)
   - Reset minimal + base typographique
   - Composants de base : `.laforge-card`, `.laforge-btn`, `.laforge-table`, `.laforge-pane`, `.laforge-status-{up,down,warn}`
2. Créer `app/web_hub/static/nokido.js` qui expose :
   - `Nokido.fetchHub(action, args)` → appel hub MCP avec gestion auth
   - `Nokido.toast(msg, level)` → notif minimaliste
   - `Nokido.theme.toggle()` → bascule dark/light (réutilisé par toutes les UIs)
3. Sidebar dans `app/web_hub/static/nokido_sidebar.html` (snippet HTML inclusible).

**Livrable** : 3 fichiers statiques (~200 lignes CSS, ~100 lignes JS, 30 lignes HTML).

**Acceptance** : une page HTML minimaliste qui fait `<link rel="stylesheet" href="/static/nokido.css">` + `<script src="/static/nokido.js">` rend déjà avec la palette netcfg.

---

### Phase 2 — Refactor des UIs (3h)

Pour chaque UI dans la liste §1 (sauf hub MCP et docs html), répéter :

1. Servir les statiques de la charte via une route additionnelle :
   ```python
   from fastapi.staticfiles import StaticFiles
   app.mount("/static", StaticFiles(
       directory=Path(__file__).parent.parent / "web_hub" / "static"),
       name="static")
   ```
   Ou pour Starlette/uvicorn équivalent.
2. Remplacer `<style>` inline par `<link href="/static/nokido.css">`.
3. Inclure la sidebar : `{% include "nokido_sidebar.html" %}` (Jinja2) ou copier le snippet.
4. Vérifier que les composants existants utilisent les classes `.nokido-*` (renommer au besoin).
5. Smoke test : ouvrir l'UI dans browser, vérifier rendu cohérent avec netcfg.

**UIs à refactor par ordre de priorité** :
1. `app/web_hub/app.py` + `dashboard.html`/`rag_dashboard.html` (déjà en chantier, easy win)
2. `app/forge_graph_explorer.py` (Cytoscape.js — juste reskin du chrome)
3. `app/forge_router_gateway.py`
4. `app/ctf_web/app.py`
5. `recon_silo/_ui.html` (refonte légère)

**Acceptance par UI** : screenshot avant/après visuellement cohérent avec netcfg.

---

### Phase 3 — Hub d'entrée unifié (1h)

**Cible** : `app/web_hub/app.py` devient la **page d'accueil** de toutes les UIs Nokido (port `:8000` ou autre dédié).

**À faire** :
1. Route `GET /` : page avec la sidebar + cards cliquables vers chaque UI :
   - 🌐 Network (netcfg `:7500`)
   - 📊 Graph Explorer (`:7474`)
   - 📚 Biblio Graph (futur, `/biblio/graph`)
   - 🧠 RAG Dashboard (`/rag`)
   - 🔄 Router Gateway (`:GATEWAY_PORT`)
   - 🎯 CTF Runner (port configurable)
2. Status block : appel `GET :8766/health`, `:11434/api/tags`, etc. → affiche état services.
3. Theme toggle persistant (localStorage).

**Livrable** : page d'accueil `:8000/` qui sert de portail.

**Acceptance** : ouvrir un seul URL donne accès à toutes les UIs et l'état du système.

---

### Phase 4 — Dark/light + responsive (1h, optionnel)

1. Custom properties pour `[data-theme="dark"]` et `[data-theme="light"]` dans `nokido.css`.
2. Toggle `Nokido.theme.toggle()` qui bascule + persiste.
3. Breakpoints mobile : `@media (max-width: 768px)` → sidebar collapse en burger.

**Acceptance** : le portail `:8000/` reste utilisable sur smartphone.

---

### Phase 5 — Anchor + maj CLAUDE.md §8 (15 min)

```python
from forge_self_correction import anchor_solution
anchor_solution(
    problem="6+ UIs Nokido avec styles disparates, pas de portail unifié.",
    solution="Charte commune (nokido.css + nokido.js + sidebar.html dans app/web_hub/static/) basée sur netcfg :7500. Refactor 5 UIs. Portail :8000.",
    example="Each UI mounts /static and includes nokido.css; portail at :8000/ links to all UIs.",
    domain="ui",
)
```

Mettre à jour `CLAUDE.md §8` avec mention du portail et de la charte commune.

---

## 4. Anatomie Nokido (CLAUDE.md §10)

| Question | Réponse |
|---|---|
| Quel organe ? | **Sens — Vision (récepteurs visuels)**. Les UIs web sont les yeux par lesquels user perçoit l'état du système. Une charte unifiée = vision binoculaire cohérente, pas un kaléidoscope. |
| Vascularisation | Entrée : appels HTTP vers les apps FastAPI/Starlette. Charte : statiques mountés depuis `app/web_hub/static`. Pas de modification du hub MCP `:8766`. Ring 0 (humain user accède directement). |
| Hémorragie | Si la charte commune casse, **toutes** les UIs cassent simultanément. Mitigation : versionner le CSS (`nokido.css?v=1.0`) + tests visuels par UI avant merge ; ne pas pousser de modification du fichier sans smoke test sur chaque UI. |

---

## 5. Anti-pièges spécifiques Nokido

1. **NE PAS** ajouter de framework JS (React/Vue) — toutes les UIs sont server-rendered ou minimalistes JS. Garder cette philosophie.
2. **NE PAS** dupliquer la sidebar dans chaque UI — un seul fichier source `nokido_sidebar.html`.
3. **NE PAS** toucher `tools/nokido_hub.py` (c'est l'API MCP, pas une UI).
4. **NE PAS** unifier les endpoints — chaque UI garde son port. L'unification est cosmétique + portail, pas architecturale.
5. **TOUJOURS** tester sur Firefox + Chromium (pas que Chrome — user peut basculer).
6. **TOUJOURS** appeler `anchor_solution()` après merge.

---

## 6. Tests d'acceptance globaux

- [ ] `docs/style_netcfg.md` rédigé avec palette + fonts (Phase 0)
- [ ] `app/web_hub/static/nokido.{css,js}` + `nokido_sidebar.html` créés (Phase 1)
- [ ] 5 UIs refactor avec screenshot avant/après cohérent (Phase 2)
- [ ] Portail `:8000/` ouvre sur sidebar + cards + status temps réel (Phase 3)
- [ ] Toutes les UIs partagent la même palette (visuel)
- [ ] Aucun framework CSS/JS ajouté (`git diff package.json` vide)
- [ ] Aucun port modifié (`grep -rE 'port=|listen' app/` montre les mêmes ports qu'avant)
- [ ] `anchor_solution` exécuté

---

## 7. Découpage exécution multi-LLM

| LLM | Phase | Justification |
|---|---|---|
| **Codex CLI** (frontend dev) | Phase 0 + 1 | Meilleur pour audit CSS et création de charte |
| **Gemini déporté** (1M ctx) | Phase 2 | Voit les 5 UIs en parallèle, refactor cohérent |
| **qwen2.5-coder local** | Phase 3 | Page portail simple, pas de quota cloud |
| **llama.cpp master** (post-Phase 0 master roadmap) | Phase 4 + 5 | Polish + anchor offline |

---

## 8. Hors-scope (volontaire)

- Mobile native app (pas de besoin actuel)
- Authentification multi-utilisateur (Nokido = mono-owner)
- Internationalisation (FR/EN seulement, fait au cas par cas)
- WebSocket temps réel sur le portail (le poll HTTP suffit pour le status)
- Refonte de `tools/nokido_hub.py` côté UI (n'est pas une UI)

---

**FIN ROADMAP UI** — version 1.0, 2026-04-30. Liée à `roadmap_master_llamacpp.md` (la Phase 4 peut tourner sur llama.cpp master quand prêt).
