# Handoff « claude design » — réparer les TUILES MORTES du portail :7400 + passe d'analyse « demandé, jamais construit »

> **À coller dans Claude Desktop.** Fichier autoportant : tu n'as besoin de rien d'autre
> que de lui + les fichiers cités. Ne lis PAS tout le dépôt.
> Rédigé le 2026-08-06 après recon LOCALE (census + lecture ciblée du code de rendu).

---

## 0. Périmètre — lis ceci d'abord, c'est la borne

Ce brief a **deux parties de nature différente** :

- **PARTIE A — RENDU GUI (ton travail d'ouvrier design).** Tu répares la **couche de
  rendu** des tuiles dans `app/web_hub/` : registre de tuiles, `render_cards`,
  `render_modules`, états visuels. Tu écris des **schemas / du HTML `lf-*` déterministe**,
  pas de la logique backend offensive.
- **PARTIE B — ANALYSE (spécification, PAS exécution).** Recense ce qui a été *promis dans
  l'UI mais jamais construit*, dont le **choix d'un LLM adapté à la sécu/CTF**. C'est une
  **recommandation d'architecture** à consigner (et à surfacer dans l'UI de la tuile sécu
  sous forme de doc/statut). **Tu n'implémentes ni n'exécutes aucun outillage offensif** :
  activer le module offensif passe par le flux d'opt-in `--with-redteam` + consentement
  `I-UNDERSTAND`, hors de ta main. Contexte : labo **local souverain**, **CTF / recherche
  sécu autorisée** (cibles Root-Me, pas de tiers réel).

Si un point de la partie B te semble hors de ta zone : traite-le comme du **texte de spec
à afficher**, jamais comme une tâche à coder.

---

## 1. Le système en 12 lignes

- **Portail** = FastAPI `app/web_hub/app.py`, port **:7400** (auth par token, middleware).
- **Registre de tuiles** = le dict `SERVICES` dans `app.py` (lignes **41–196**). Chaque
  entrée : `{target, title, desc, icon, color, [external], [coming_soon]}`.
- **Rendu** = `app/web_hub/dashboard_html.py` : deux fonctions rendent les tuiles —
  `render_cards()` (classe `lf-card`) et `render_modules()` (classe `lf-module`).
- **Une tuile passe « morte » (badge BIENTÔT) si** `cfg["coming_soon"]` **OU**
  `_service_down(cfg)` — sonde TCP 0,25 s sur le `127.0.0.1:PORT` de `target`
  (`dashboard_html.py:12–24`).
- Design system : tokens `var(--…)` (`static/laforge-ds/tokens/*.css`) + classes `lf-*`
  (`static/laforge-components.css`). **RÉUTILISER, ne pas inventer** — au plus un modificateur.
- Rendu **déterministe / 0-token** : schema → `forge_ui_moulinette.skeleton_from_schema`.
  Itérer en blocs SEARCH/REPLACE (`forge_search_replace`), jamais réécrire un fichier entier.
- Convention de page+API montée : voir `app/web_hub/redteam_views.py` (déjà en place).

---

## 2. PARTIE A — Diagnostic des tuiles mortes

Audit du registre `SERVICES` (app.py:41–196) croisé avec le rendu. Trois **états** sont
aujourd'hui écrasés en un seul badge « BIENTÔT », c'est le vrai défaut :

| Tuile | `target` | État RÉEL | Ce que l'UI affiche | Verdict |
|---|---|---|---|---|
| **recon** (« Recon Silo ») | `127.0.0.1:{RECON_PORT}` | Jamais construit — `coming_soon = not _RT_INSTALLED`, dépôt privé `laforge-redteam` **absent** (app.py:442–452). Mais la page d'opt-in `/redteam` **EXISTE** (`redteam_views.py`). | « BIENTÔT / non déployé » (lien mort) | **FAUX MORT** → doit devenir une tuile **opt-in** vers `/redteam` |
| **graph** (:7474), **netcfg** (:7500), **llamacpp_chat** (:8091), **llamacpp_api** (:8090), **ollama** (:11434), **deno** (:7401) | service externe | **Construit, juste ÉTEINT** | « BIENTÔT / non déployé » | **MENSONGE** : c'est *éteint*, pas *jamais fait* → 3ᵉ état « démarrer » |
| **ctf** (« CTF Runner ») | `internal` (mount `/ctf`) | **Construit et vivant** (`app/ctf/{agent,solver,browser_mcp}.py`, mount app.py:403) | OK (vivant) | RAS |
| **reports** (« CTF Reports ») | `/reports` | Router monté (app.py:410) | OK | RAS |
| vitals, mcp_lab, rbac, llm_dashboard, launcher, ui_playground, anatomy, feed, status, docs | routes internes | Vivantes | OK | RAS |

### Les 3 correctifs (par ordre d'impact)

**A1 — Distinguer 3 états au lieu de 1.** Aujourd'hui `dashboard_html.py` ne connaît que
`down = coming_soon OR _service_down`. Introduire un helper unique
`tile_state(cfg) -> {"live" | "off" | "optin" | "soon"}` qui pilote **les deux** renderers
(fin des divergences), avec :
- `live` → carte cliquable normale ;
- `off` (service local déployé mais port injoignable, ex. graph/netcfg/llama/ollama/deno)
  → carte active, badge **« ÉTEINT »**, action **« Démarrer »** pointant vers `/launcher`
  (le lanceur existe déjà, tuile `launcher`). PAS « non déployé ».
- `optin` (`coming_soon` **et** une page d'activation existe, ex. recon→`/redteam`)
  → carte active, badge **« À ACTIVER »**, lien vers la page d'opt-in.
- `soon` (vrai jamais-construit, sans page d'activation) → l'actuel « BIENTÔT » grisé,
  **c'est le seul cas qui garde le libellé mort**.

**A2 — La tuile `recon` pointe vers `/redteam`.** C'est le correctif le plus visible pour
« la sécurité reste morte ». Le flux d'opt-in est **déjà codé** (`redteam_views.py` :
`GET /redteam` page + `GET /api/redteam/status` + `POST /api/redteam/enable` avec
consentement → renvoie vers l'installeur GATE). Il suffit que la tuile cesse d'afficher un
lien mort et route vers cette page en état `optin`. Ne recode PAS le consentement : réutilise.

**A3 — Réconcilier les deux renderers.** `render_cards()` écrit « BIENTÔT » (accentué),
`render_modules()` écrit « BIENTOT » (sans accent) — même donnée, deux libellés. Après A1,
les deux consomment `tile_state()` et le **même** dictionnaire de libellés/couleurs par état.
Un seul point de vérité pour le badge.

> Détail à corriger au passage : le libellé de bas de carte `"/{slug}/ (non déployé)"`
> (`render_cards`, ~ligne 57) est faux pour un service externe éteint — il n'est pas sous
> `/{slug}/` et il *est* déployé. Le texte doit suivre l'état.

### Definition of Done — Partie A
1. Un helper `tile_state()` unique ; `render_cards` et `render_modules` n'ont plus de
   littéral « BIENTÔT/BIENTOT » codé en dur.
2. Les 6 tuiles de services externes éteints affichent « ÉTEINT + Démarrer → /launcher »,
   pas « non déployé ».
3. La tuile **recon** est cliquable et mène à `/redteam` (état « À ACTIVER »).
4. Aucune classe/token nouveau hors un éventuel modificateur `lf-card--off` /
   `lf-card--optin` (réutiliser `lf-card-disabled` comme base).
5. Rendu produit par schema → moulinette (0 token), itéré en SEARCH/REPLACE.

---

## 3. PARTIE B — Passe d'analyse : demandé, jamais construit

Ce que l'UI **promet** et que le code **n'honore pas** encore. Trois manques, le 2ᵉ est le
cœur de la demande.

### B1 — Le Recon Silo (`laforge-redteam`)
La tuile décrit « ARP + nmap + LLM targeting, MSF gateway, SSE live ». Le dépôt privé
`laforge-redteam` (sibling du superrepo) **n'a jamais été créé/cloné** → capacité inexistante,
seule la coquille d'opt-in existe. **Statut : à construire** (dépôt privé, opt-in offensif).
Rien à coder ici côté Desktop — c'est un chantier séparé, gaté par consentement.

### B2 — Un LLM adapté SÉCU/CTF, sans le sur-refus des modèles généraux ⭐ (le vrai sujet)

**Constat mesuré** : aucun modèle spécialisé sécu / à refus réduit n'est câblé (recherche
`dolphin|uncensored|abliterated|whiterabbit|pentestgpt|offensive` dans les configs = **0 hit**).
Le **CTF Runner** (`app/ctf/solver.py`, `agent.py` — déjà construits) et le futur Recon Silo,
quand ils appellent un LLM, tapent les modèles généraux locaux (**qwen2.5-coder**,
**deepseek-r1**, **gemma**) qui **refusent** les tâches offensives légitimes d'un CTF
(génération de payload, ret2libc, primitive de heap, chaîne d'exploitation) — même sur cible
Root-Me autorisée. **C'est pour ça que les capacités sécu paraissent « mortes » : la tuile
existe, le backend cognitif la sabote par sur-refus.**

**DÉCISION OWNER (2026-08-06) — backend de la tuile sécu :**
`pentestgpt-legacy → ollama` avec le modèle **abliterated** `huihui_ai/deepseek-r1-abliterated:8b`
(tiré ✓, `.env` = `OLLAMA_BASE_URL=http://localhost:11434/v1`). **Souverain, hôte, ZÉRO cloud,
ZÉRO garde-fou, ZÉRO dépendance Docker** — assistant de raisonnement qui suggère les commandes.
La tuile CTF/recon déclenche `uv run pentestgpt-legacy --reasoning-model
ollama:huihui_ai/deepseek-r1-abliterated:8b --parsing-model ollama:…` et affiche la sortie.
L'**exécution autonome dans Exegol** (kali en Docker) est **gâtée sur la RCA du VM-kill Docker**
(le backend reçoit un SIGTERM externe propre, cause ouverte — capteur livré :
`tools/forge_docker_kill_source_capture.py` + `config/sysmon_docker_backend.xml`), donc **hors
périmètre de cette tuile pour l'instant**. Desktop câble le déclencheur + l'affichage, pas l'offensif.

**Recommandation détaillée — un endpoint LLM LOCAL dédié sécu, souverain, sans cloud ni clé API :**

1. **PentestGPT est INSTALLÉ** (2026-08-06, `%NOKIDO_WORKSPACE%\PentestGPT`,
   GreyDGL, USENIX Security '24). Il expose **DEUX entrypoints de nature différente** —
   correction d'une hypothèse antérieure (l'`aichat --serve` que ce brief citait est
   **inutile**, PentestGPT parle Ollama nativement) :
   - **`pentestgpt-agent`** (nouveau, autonome, `recon → exploit → walkthrough`) : pilote
     **Claude Code / Codex CLI** via `unified-agent`, `--backend claude|codex`. Il **porte
     donc les garde-fous** de Claude/Codex et exige un CLI **authentifié**. `FULL_ACCESS` →
     isolation = VM/conteneur jetable (rejoint le blocker Docker/Exegol). **Ce n'est PAS le
     chemin sans-garde-fous.**
   - **`pentestgpt-legacy`** (interactif, multi-provider) : lit `.env` et supporte
     **Ollama local** (`OLLAMA_BASE_URL=http://localhost:11434/v1`) + `OPENAI_BASE_URL`.
     **C'EST le chemin souverain** : modèle **100 % local**, zéro cloud, zéro garde-fou
     Anthropic — on choisit le modèle.

2. **Câblage souverain (legacy)** : `.env` → `OLLAMA_BASE_URL=http://localhost:11434/v1`,
   puis `pentestgpt-legacy --list-models` + `--smoke-test`. Aucun binaire tiers, aucun
   endpoint intermédiaire.

3. **Le manque qui RESTE** (mesuré 2026-08-06) : Ollama :11434 porte **15 modèles, tous
   généralistes** (qwen2.5-coder, gemma4, deepseek-r1, llava…) — **aucun spécialisé sécu ni
   à refus réduit**. Donc legacy→Ollama marche mais **le sur-refus persiste**. Pour le lever :
   `ollama pull` d'un modèle **à refus réduit / spécialisé sécu** (WhiteRabbitNeo,
   *dolphin*/*abliterated* de qwen/llama), puis le pointer. **Banc de référence** : le
   pipeline Root-Me existant `app/ctf/solver.py` — mesurer taux de résolution + taux de refus,
   trancher sur données.

4. **Gouvernance (non négociable, déjà en place)** : tout appel reste enveloppé
   `SovereignMembrane` + `SemanticFirewall`, ring-scopé, **LOCAL uniquement**, **usage
   autorisé uniquement** (le flux `/redteam` impose déjà consentement + dépôt privé). CTF /
   Root-Me = cibles autorisées. Le but n'est pas de retirer des garde-fous mais d'éviter le
   **sur-refus** d'un modèle généraliste sur une tâche de labo légitime.

**Ce que Desktop en fait** : rien d'offensif à coder. Au plus, **surfacer cette architecture
dans l'UI** — sur la page `/redteam` (état `optin`), afficher une section « Backend cognitif :
PentestGPT + endpoint local `aichat --serve` → cerveaux locaux, aucun cloud » en statut/doc.
C'est de l'affichage de spec, pas de l'exécution.

### B3 — Divers coquilles vides mineures
- **TUI web terminal** (xterm.js) : tuile retirée volontairement, « re-ajouter quand le
  bridge WS sera livré » (app.py:193, 452). Laisser tel quel (documenté).
- **MCP Lab Phase 2** (stdio bridge) : `mcp_lab.py:6` « non implémenté ». Phase 1 vivante.
  Laisser, ou afficher « Phase 2 à venir » honnêtement.

---

## 4. Contraintes (rappel, RÈGLES)

- **Schemas + rendu déterministe 0-token.** Pas de `render_X()` HTML écrit à la main.
- **`lf-*` + tokens `var(--…)`.** Nouveau CSS = un modificateur, jamais une refonte.
- **Réutiliser l'existant** : `/redteam` (opt-in), `/launcher` (start/stop), `lf-card-disabled`.
- **Itération chirurgicale** : blocs SEARCH/REPLACE (`forge_search_replace`), commit PETIT
  par composant (le post-commit indexe en RAG).
- **Aucun appel cloud pour le rendu** (le connecteur `claude_design` cloud est abandonné).
- **Partie B = spec**, pas exécution. Aucun code offensif produit côté Desktop.

## 5. Fichiers à toucher (Partie A) — la liste courte
- `app/web_hub/dashboard_html.py` — helper `tile_state()` + `render_cards` + `render_modules`.
- `app/web_hub/app.py` — au besoin, marquer la tuile `recon` avec un pointeur d'opt-in
  (`"optin_href": "/redteam"`) pour que le rendu route dessus au lieu de `coming_soon` nu.
- (lecture seule, ne pas recoder) `app/web_hub/redteam_views.py`,
  `app/web_hub/forms/redteam_module_form.py` — la page et la carte d'opt-in existent déjà.
- Réfs design : `DESIGN_GUIDE.md`, `static/laforge-components.css`, `static/laforge-ds/tokens/`.
