# UI Kit — Web Hub modernisé

Recréation **modernisée** du vrai portail web de Nokido (`:7400`), tel qu'il existe dans le code (`app/web_hub/dashboard.html`, `sidebar.html`, `forge_feed.html`), réhabillé avec le design system : nouveau logo, provenance partout, thèmes, composants.

## Vues (nav en topbar + puces & tuiles cliquables)

Les **puces** de liens rapides et les **tuiles de service** du Portail **naviguent** désormais vers la vue correspondante (plus aucun `href="#"` inerte).

- **Portail** — grille de services réels (provenance + statut pulsé), barre de puces, panneau MCP.
- **Chat** — `sidebar.html` modernisé : fournisseur, bulles, badge de provenance par réponse.
- **Launcher** — `launcher_html.py` : modules start/stop/logs/live.
- **Anatomie** — `anatomy.html` : OPSEC, KILL SWITCH, organes par système.
- **Network** — recréation de **`forge/network` (:8766)** : graphe nœuds/liens interactif (cerveau, routeur, RAG, MCP, Ollama, cloud…), couleur par provenance, flux animé sur les liens actifs, inspecteur de nœud cliquable.
- **MCP Lab** — marketplace de **skills** (web.fetch, fs.read, rag.search, shell.run, vision.ocr, cloud.ask) avec catégorie, provenance + anneau, et **console Invoke** (sortie JSON).
- **RAG** — `rag_dashboard.html` : stats, recherche locale, ingestion, documents.
- **CTF Reports** — liste de rapports/traces avec état + anneau (puce « CTF Reports »).
- **Status JSON** — `GET /status.json` colorisé (souveraineté, services, RAG).
- **Pipeline souverain** — CI **local-first** : flux commit → pre-commit → pre-push → self-hosted → merge → cloud (manuel). **Gate primaire LOCAL** (pre-commit secret-scan, `tools/ci_local.py`, pytest, runner self-hosted — gratuit, bloquant) vs **fallback cloud MANUEL** (`ci.yml`, `eco-shield.yml`, `gitleaks.yml`, `docker-publish.yml`, `release.yml`, `cla.yml` — `workflow_dispatch` seulement). Reflète la philosophie réelle du dépôt (`.github/workflows`).
- **Event Feed** — `forge_feed.html` : audit coloré par topic.
- **Swarm** — essaim d'agents spécialisés (archiviste, cryptographe, cartographe, libraire, sociologue…) avec santé pulsée, barre de charge et provenance.
- **LLM Debate** — débat multi-modèles arbitré : motion + arguments Pour/Contre/Nuance (modèle + provenance + anneau), synthèse de l'arbitre.

Bouton **thème** (sombre/clair/auto) persistant, **panneau Tweaks** (accent, densité, animations, simplifier le portail).

## Fichiers

- `index.html` — entrée interactive (PC) + panneau Tweaks.
- `web-hub.ref.jsx` — topbar, Portail (puces + tuiles navigantes), Chat, Feed.
- `web-hub-screens.ref.jsx` — Launcher, Anatomie, RAG.
- `web-hub-extra.ref.jsx` — Network Graph, MCP Lab, CTF Reports, Status JSON, Pipeline souverain, Swarm, LLM Debate.
- `tweaks-panel.jsx` — panneau de réglages.

## Ce qui change vs l'original

Même information et même structure que le hub réel, mais : strates de fond et bordures du DS, halo violet au survol, provenance/anneaux explicites, logo forgeron, thèmes clair/sombre/auto, composants `Card`/`Badge`/`StatusPill`/`Button`/`ProvenanceBadge`/`TextInput`/`Select`. Aucune nouvelle invention de service — uniquement ceux présents dans le code.
