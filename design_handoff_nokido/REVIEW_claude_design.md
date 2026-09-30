# Review claude design — corriger la divergence avec l'app réelle

> claude design a **inventé sa propre UI** et **divergé de l'app fonctionnelle**. À corriger
> AVANT toute nouvelle passe. **Source de vérité = `app/web_hub/app.py::SERVICES` + `dashboard_html.py`** (le vrai portail :7400), PAS le mockup.

## Faut-il repasser la moulinette d'abord ? → NON

La moulinette (`forge_ui_moulinette`) génère du **code de rendu** depuis des **schemas**. Le
problème ici n'est PAS le rendu — c'est la **DATA des tuiles** (la liste `SERVICES`) que
claude design a réinventée. Corriger = lui donner la **vraie liste**, pas régénérer.
(La moulinette ne sert que pour créer de NOUVEAUX composants design, pas pour la liste de tuiles.)

## Bugs constatés (à fixer dans la source claude design)

1. **netcfg DROPPÉ.** Les 2 `const SERVICES` du bundle omettent `netcfg`. Le vrai portail l'a.
2. **DÉMO inventé.** Badge "DÉMO" dans le header — n'existe PAS dans le vrai (`dashboard.html` =
   `⚡ Nokido Hub · v{version} · Web Hub :7400`). À retirer (ou "BÊTA" si tu veux marquer le stade).
3. **Doublons.** **2× `const SERVICES`** (2 rendus = rangée icônes du haut + cartouches du bas).
   → **UNE** liste, **UN** rendu = la rangée icônes. Supprimer le 2e.
4. **recon** : ne pas hardcoder `coming:true`. Le serveur gère déjà (`coming_soon` dynamique,
   gaté sur l'install redteam). Lire l'état réel.
5. **Liens morts** : une tuile dont le service est down (port injoignable) doit passer
   `coming_soon`/grisée **dynamiquement** (liveness), jamais un lien mort cliquable.

## Source de vérité — `app/web_hub/app.py::SERVICES` (12 tuiles)

`vitals, mcp_lab, rbac, llm_dashboard, reports, recon, ctf, graph, **netcfg**,
llamacpp_chat, llamacpp_api, ollama`

→ claude design doit **rendre EXACTEMENT ces clés** (titres/targets/icônes/external dans `SERVICES`),
pas une liste maison. Ex `netcfg` = `{title:"Network Config / Audit", target:"http://127.0.0.1:7500",
icon:"network", color:"cyan", external:true}`.

## Règle d'or (rappel `CLAUDE_DESIGN_TODO.md`)

Le **design system** s'APPLIQUE à l'app réelle (tokens `lf-*` sur le vrai render + vrai SERVICES).
On ne maintient PAS un mockup parallèle qui invente/drop des tuiles. **Beau ET fonctionnel = le
design system rendu sur les vraies données**, pas une démo.

## CHANTIER COHÉSION — pages réelles à aligner sur le DS (demande user 2026-06-19)

> Constat user : *« pas de cohérence de style entre le gros dev claude design et les autres pages »*.
> Le dashboard `:7400` (`dashboard.html`) utilise DÉJÀ le DS (`lf-card`, `lf-icon`, `lf-status-dot`).
> Les pages réelles ci-dessous **ne l'utilisent PAS** → incohérence. Les aligner (appliquer
> `lf-*` + tokens), **PAS** repeindre à la main page par page sans le DS.

### Convergence tokens → `laforge-tokens.css` — ✅ FAITE (2026-06-19)

**Diagnostic affiné** : `laforge-tokens.css` est l'export PLAT de `nokido.css` (mêmes NOMS +
VALEURS : `--bg-0..4`, `--purple #774AFF`, `--text-primary`, etc.). Donc 2 des « 3 vocabulaires »
n'en étaient **pas** :

| Surface | État réel | Action |
|---|---|---|
| ✅ Dashboard **:7400** | `nokido.css` = **déjà** la palette DS (mêmes tokens) | aucune — déjà convergé |
| ✅ netcfg **:7500** | `static/style.css` `:root` = **déjà** valeurs DS (`--bg-0 #0C0A13`, `--purple #774AFF`…) | aucune — déjà convergé |
| ✅ Hub **:8766/ root** | `nokido_hub.py::hub_index` ~L2591 | restylé DS `lf-*` (`6e228013`) |
| ✅ **:8766 /forge/network** | `NETWORK_HTML` avait son propre `:root` (`--primary #6366f1`, `--bg` gradient) | `:root` inline → remap tokens DS, dup-named retirés, `--primary→--purple` (`82a41bb8`) |
| ✅ **Anatomy** :7400 | `anatomy.html` hex hardcodés (`#0a0e27/#e0e0e0/#333`, opsec hex) | link DS + hex → tokens DS (`82a41bb8`) |

**Méthode appliquée** : pour les vars **dup-nommées** que le DS fournit déjà (`--bg/--surface/--border/
--text/--ok/--warn/--err/--orange`) → **retirer** la redéfinition inline (le DS, lié au-dessus, gagne).
Pour les noms **locaux** restants → `var(--<token DS>)`. Layout inchangé, couleur pilotée par le DS.

**✅ 4 SPA résiduelles convergées** (`llm_debate`/`graph_viz`/`recon_demo`/`ctf_demo`) : DS lié +
chrome (bg→`var(--bg-0)`, header/title/bordures/inputs → tokens DS). Les couleurs **JS**
(vis-network, statuts providers) laissées telles quelles (un `var()` CSS ne résout pas en JS).
Servies en FileResponse → **live**, pas de reload. Résidu = quelques accents profonds (boutons/
panels) — cosmétique mineur.

⚠️ `:8766` (NETWORK_HTML) nécessite un **reload hub** pour prendre effet ; anatomy/:7400 = live (FileResponse).
