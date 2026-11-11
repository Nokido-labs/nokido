# Routes gouvernées — UTILISER, jamais bricoler (2026-06-20)

Déportée VERBATIM de `RULES_SHARED.md` le 2026-11-04 (owner : « 16 % de contexte au démarrage »).

Trois « gros boutons » MCP absorbent l'intention ; le hub fait l'impératif
(privilèges/daemons/conteneurs/AST). Un client (Claude/Gemini/Codex/agy/Copilot)
ne RÉINVENTE jamais ça en natif :

- **Recon code** → `forge_deep_explore{intent, target?, globs?, breadth?}` : recon
  LOCALE souveraine (0 token cloud, digest file:line). JAMAIS Agent(Explore) ni
  une rafale de Read/grep natifs sur le code Nokido.
- **Infra / service** → `nokido_ensure_service{service, desired_state}` (docker,
  searxng, hub, ollama, netcfg, webhub, graph, embed, lmstudio · running/stopped/
  restarted). JAMAIS un script keeper/diagnostic ni une commande docker maison.
- **Sous-agent / travail déporté** → `run action=run_job script=tools/mon_script.py`
  (détaché, survit au restart, **0 token cloud**), et `forge_job_watch_notify --rc le_job.rc`
  pour être **notifié dans sa boucle** à la fin. **JAMAIS un sous-agent Claude** — règle
  owner du 2026-09-06, **sans exception**. Un sous-agent Claude facture un modèle pour un
  travail que le corps sait faire seul, et son verdict est une réponse à interpréter là où
  un job rend un fichier (`.rc`). Le gate `forge_tool_gate` le REFUSE désormais quel que
  soit le `subagent_type` : l'ancienne version ne captait que les sous-types de recon, et
  cette échappatoire a été empruntée le jour même en renommant l'intention (`general-purpose`
  refusé → relancé en `claude`, même travail, même coût). **Un garde qu'on franchit en
  renommant son intention ne garde rien.** Précision owner 24/10 : un sous-agent CLAUDE ne se
  lance qu'avec l'**accord explicite de l'owner**, à sa demande (essai mesuré P1_essai_mesure_sous_agents) ;
  des sous-agents sur **LLM GRATUITS** (free tiers, conseiller souverain) : **dès que c'est possible**.
- **Édition de fichier Nokido** → `governed_edit{path, blocks|content}` : écriture
  in-process GOUVERNÉE (AST + scan secret + tree_lock ; blocs SEARCH/REPLACE =
  -80% tokens). JAMAIS Write/Edit/apply_patch natif sur le dépôt Nokido quand on
  peut gouverner. Côté Claude Code, le hook `forge_tool_gate` deny ces écritures
  natives (flag `LAFORGE_THIN_CLIENT_ENFORCE`) ; les clients hook-less l'appliquent
  par DISCIPLINE (cette règle) — leur natif n'est pas interceptable.
