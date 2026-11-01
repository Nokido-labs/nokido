# Étude comparative : UI OmniRoute vs web_hub Nokido

**Date :** 2026-10-31  
**Référence :** docs/etudes/ui_omniroute_vs_web_hub_20261031.md  
**Auteur :** Antigravity (`agt_antigravity`) — tâche job_f74513a2 ; relu et intégré par CLAUDE (3 chunks vérifiés en base : extraits mot pour mot).

> Note d'intégration (31/10) : chemins absolus du worktree de tâche ramenés aux chemins du dépôt. Le défaut de lecture
> relevé ci-dessous (§2 : `read` → PermissionError, squelette vide sur .html) est corrigé par 1d3f935c3.

---

## 1. Tableau comparatif : Fonctions OmniRoute vs Nokido web_hub

Toutes les preuves OmniRoute ci-dessous proviennent de requêtes directes à l'outil `rag` du hub Nokido (`top_k=5`) sur les ingestions `gitingest/omniroute`. Les extraits sont copiés mot pour mot avec leur identifiant `[chunk:id]`.
Pour Nokido `app/web_hub/`, les accès directs via `read` et `get_file_skeleton` ont été tentés par le hub MCP et sont documentés avec leur état factuel (PermissionError / skeleton AST Python sur fichiers HTML). Les pages web_hub identifiées sont issues des index et traces de commits indexés dans le RAG.

| Fonction OmniRoute | Extrait copié mot pour mot + [chunk:id] | Page Nokido équivalente (chemin) | État |
| :--- | :--- | :--- | :--- |
| **Dashboard UI & Structure** | `│ ├── (dashboard)/ # Dashboard UI pages` <br>`│ │ └── dashboard/` <br>`│ │ ├── agents/` <br>[chunk:48fe8507e27b2245] | `app/web_hub/dashboard.html` | PROUVÉ (OmniRoute) / ILLISIBLE (Hub `read` renvoyait `PermissionError: [Errno 13]`) |
| **Combos & Fallback Chains** | `Dashboard → Combos → Create New` <br>`Name: premium-coding` <br>`Models:` <br>` 1. cc/claude-opus-4-7 (Subscription primary)` <br>` 2. glm/glm-4.7 (Cheap backup, $0.6/1M)` <br>[chunk:5f48e4cc25d3bbb8] | AUCUNE *(géré côté backend par forge_lane_admission / forge_quota_manager sans vue combo dédiée dans web_hub)* | PROUVÉ |
| **Gestion des Combos & Fallback (MCP Tools)** | `| omniroute_list_combos | All configured combos with models |` <br>`| omniroute_get_combo_metrics | Performance metrics for a specific combo |` <br>`| omniroute_switch_combo | Switch active combo by ID/name |` <br>[chunk:4c0367a310fc4e1d] | AUCUNE | PROUVÉ |
| **Simulation de Route & Budget Guard** | `| omniroute_simulate_route | Dry-run routing simulation with fallback tree |` <br>`| omniroute_set_budget_guard | Session budget with degrade/block/alert actions |` <br>[chunk:bb6347ac3ddf8494] | AUCUNE | PROUVÉ |
| **Unified Logs Dashboard** | `- Unified Logs Dashboard — 4 tabs: Request Logs, Proxy Logs, Audit Logs, Console` <br>`- Console Log Viewer — Real-time terminal-style viewer with color-coded levels, auto-scroll, search, filter` <br>[chunk:633ad00eb4948ea9] | `app/web_hub/dashboard.html` *(section logs sommaire)* | PROUVÉ (OmniRoute) / ILLISIBLE (Nokido direct read) |
| **Request Telemetry & Artifacts** | `- SQLite Summary Logs — Request and proxy log indexes stay queryable across restarts without loading large payload blobs into SQLite` <br>`- Request Telemetry — p50/p95/p99 latency + X-Request-Id tracing` <br>[chunk:83e68c762f4cf41c] | AUCUNE *(télémétrie brute en SQLite / WAL sans rendu graphique p50/p95/p99 dans l'UI)* | PROUVÉ |

---

## 2. Pages Nokido web_hub recensées

Tentatives de lecture via les outils du hub MCP (`read` et `get_file_skeleton`) :
1. `read` sur `app/web_hub` (dossier) renvoyait `ERR: PermissionError: [Errno 13] Permission denied: '...\\Nokido'` — cause réelle : paramètre `path` non lu (vide = racine), dossier lu comme fichier ; corrigé 1d3f935c3 (un dossier se liste).
2. `get_file_skeleton` attendait des modules Python AST valides ; sur un `.html`, il renvoyait `ERR: skeleton vide` — corrigé 1d3f935c3 (plan HTML : titre, en-têtes, ids, scripts).

Preuves issues des traces certifiées du RAG Nokido (`[chunk:9c3464fef8b015eb]`, `[chunk:47eaabdaf49e53df]`, `[chunk:1492860f34c6e388]`, `[chunk:e78e0b97f039a9fc]`) :
- `app/web_hub/anatomy.html` — `<title>Nokido — Anatomie Live</title>` [chunk:9c3464fef8b015eb]
- `app/web_hub/dashboard.html` — Hub de contrôle principal [chunk:e78e0b97f039a9fc]
- `app/web_hub/forge_debate.html` — Vue débats inter-agents [chunk:e78e0b97f039a9fc]
- `app/web_hub/forge_feed.html` — Flux d'activité [chunk:e78e0b97f039a9fc]
- `app/web_hub/graph_viz.html` — Visualisation de graphes [chunk:e77a03243c1bb330]
- `app/web_hub/llm_debate.html` — Interface de confrontation LLM [chunk:e77a03243c1bb330]
- `app/web_hub/postal.html` — Messagerie boîte aux lettres / frames [chunk:e77a03243c1bb330]
- `app/web_hub/rag_dashboard.html` — Dashboard de consultation RAG [chunk:e77a03243c1bb330]

---

## 3. Trois ajouts proposés inspirés d'OmniRoute

Sans inventer de nouveaux fichiers de données inexistants et en s'appuyant strictement sur les sources et structures existantes :

1. **Visualisation et test interactif de l'arbre de fallback (« Combos / Fallback Tree ») :**
   - **Inspiration OmniRoute :** `omniroute_simulate_route` (*« Dry-run routing simulation with fallback tree »* [chunk:bb6347ac3ddf8494]) et `Dashboard → Combos → Create New` [chunk:5f48e4cc25d3bbb8].
   - **Page Nokido à étendre :** `app/web_hub/dashboard.html`.
   - **Description :** Intégrer un panneau interactif permettant de simuler l'ordre de bascule des modèles configurés dans `forge_lane_admission.py` (ex. abonnement primaire -> backup gratuit -> modèle local Ollama) et d'afficher le chemin de repli en temps réel sans envoyer de prompt réel.

2. **Onglet Télémétrie & Latence p50 / p95 / p99 (« Request Telemetry ») :**
   - **Inspiration OmniRoute :** `- Request Telemetry — p50/p95/p99 latency + X-Request-Id tracing` [chunk:83e68c762f4cf41c].
   - **Page Nokido à étendre :** `app/web_hub/dashboard.html` (ou intégration directe dans la vue `app/web_hub/anatomy.html`).
   - **Description :** Exploiter les métadonnées de durée des appels déjà stockées dans les journaux d'audit du hub pour afficher une courbe de latence percentile (p50, p95, p99) par provider/modèle directement sur le dashboard au lieu d'une simple table textuelle.

3. **Console temps réel et visualiseur multi-onglets des flux (« Unified Logs Viewer ») :**
   - **Inspiration OmniRoute :** `- Unified Logs Dashboard — 4 tabs: Request Logs, Proxy Logs, Audit Logs, Console` [chunk:633ad00eb4948ea9].
   - **Page Nokido à étendre :** `app/web_hub/forge_feed.html`.
   - **Description :** Transformer la page de flux d'activité en une vue à onglets filtrable avec auto-scroll (Logs de requêtes, Logs d'audit sécurité, Journal console des agents), permettant d'inspecter les requêtes en vol sans ouvrir manuellement les fichiers journaux.
