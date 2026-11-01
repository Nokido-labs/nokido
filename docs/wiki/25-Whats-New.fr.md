---
type: guide
title: 25 — Nouveautés (22–30 octobre 2026)
status: draft
resource: repo://docs/wiki/25-Whats-New.fr.md
generated: {by: mistral@85e1ffb33, at: 2026-10-30T22:19:48+01:00}
empreinte: INCONNUE
---

# 25 — Nouveautés (22–30 octobre 2026)

<!-- revu-le: 2026-10-30 -->
> 🌐 [English](25-Whats-New.md) · **Français** · [Index du wiki](Home.fr.md)

Chaque ligne ci-dessous est un commit d'`alpha` (empreinte courte entre parenthèses) : l'historique fait foi, cette
page ne fait que le regrouper. Les éléments marqués *observation* tournent sans encore bloquer — Nokido mesure un
garde neuf avant qu'il ne refuse.

---

## Nouvelles fonctionnalités

* **Appel de passeport, tranche 3** : Un appel de routeur en HTTP direct (hors proxy) écrit aussi sa ligne au passeport, sans doublon ; endpoint INCONNU quand il n'est pas fourni (app/forge_llm_router.py, app/forge_trace_context.py).
* **Porte de qualité** : pylint absent ou muet = score ILLISIBLE, plus une note de 0/10 ni une fausse leçon d'échec ; le marqueur TODO CRITICAL ne compte qu'en commentaire (app/forge_quality_gate.py).
* **Identité des exécuteurs attestée par le superviseur** (processus parent + `--agent` du service dans services.toml) au lieu d'un `prouve=False` codé en dur ; le contrôle de réclamation reste en observation (tools/forge_task_executor.py, docs/enquetes/identite_executeurs_claim_20261030.md).
* **Une tâche assignée réveille l'exécuteur endormi par délestage RAM** (intention), l'admission RAM du superviseur restant souveraine (app/forge_mcp_registry.py, docs/enquetes/reveil_apres_delestage_20261030.md).
* **README** : Vitrine courte traduite en 7 langues (docs/i18n/README.<code>.md), version complète dans docs/README_complet.md.

## Délégation aux agents de code (exécuteur de tâches)

* **Un worktree par tâche** — chaque tâche déléguée tourne dans son propre worktree git détaché, sur une branche
  dédiée : deux tâches d'un même agent ne voient ni ne committent jamais les fichiers l'une de l'autre. Une création
  interrompue (verrouillée, index vide) est nettoyée au lieu de bloquer la tâche (`1a6c7a93a`, `0c8eff461`) ; la même
  tâche reprend dans son worktree après le redémarrage d'un exécuteur (`4a1af3057`).
* **Délégations parallèles**, bornées par exécuteur, avec protection de l'état partagé (`1195079f5`), et **réveil au
  dépôt d'une tâche** au lieu d'une scrutation de 60 à 120 s (`eacb4d757`).
* **Contexte allégé** pour tous les CLI dans le worktree de tâche, et un effort qui ne monte jamais de lui-même
  (`7c1a90251`, `a2e9ba9bd`) ; un avertissement quand une tâche vise un agent sans exécuteur.
* **Réglages par taille prouvés dans la documentation de chaque CLI** : plafond de tours Vibe S/M/L 15/40/60
  (`386cc9497`), Codex lit la table d'effort commune, OpenCode `compaction.prune` (`84200eaa2`) ; une table unique
  `forge_palier_effort` borne l'effort selon les capacités du modèle (`22909ef1f`).
* **La réaffectation saute les agents dont le quota de modèle est épuisé** — fin du ping-pong entre surfaces
  (`a0b130c8f`).
* **Conseiller souverain** aux points de contrôle des voies gratuites (OpenCode, Vibe), escalade vers Claude en
  dernier (`28f7b1814`, `6c5193f2f`).

## Offres gratuites et quotas

* **Recensement des offres gratuites** : 15 surfaces et 8 fournisseurs officiels de plus (`e6c307470`, `f3c41f319`) ;
  les appels voués à l'échec (clé absente, 402, 429 récent) sont court-circuités avec un délai de refroidissement
  (`640262e9a`).
* **Un quota épuisé nourrit le recensement avec son échéance** (`0327ed034`) ; un 429 journalier vu par une enquête
  est consigné aussi (`a8ec85b8d`).

## Enquêtes en lecture seule sans boucle d'agent

* `tools/forge_enquete_sans_boucle.py` : un seul appel à un modèle gratuit fort sur un dossier borné, tiré du FTS ou
  d'une source désignée, au lieu d'une session d'agent complète (`293b3b6e0`, `e936065d2`, `ec904fc50`) ; un **juge
  déterministe signale les noms absents du dossier** (`929e15493`) ; les tâches marquées `mode: enquete` prennent
  cette voie (`84cae4556`).

## Économie de jetons

* **Lecture conditionnelle (RFC 9110)** sur `read`, `read_function_body` et `get_file_skeleton` : passer `si_etag`
  rend `INCHANGE` ou le seul différentiel (`1125f1c35`, `6e78484ad`).
* AGY : lecture par pointeur et par empreinte, préfixe de consigne stable, outils MCP bornés par groupe
  (`1349bebd9`, `bf812ac22`, `6c3e06543`) ; passation compacte entre agents de l'essaim (`99aac8430`) ; préfixe ACP
  mis en cache sans sections dynamiques (`a893c614c`).

## ACP et clients

* **ACP à travers le hub** : routeur multi-sessions, front web `/acp` (sessions, flux, permissions tranchées par
  l'owner), service `NokidoAcpWorker`, JWKS des jobs ACP (`e1b62a759`, `69e889713`, `f9d0a9cc6`, `40cfbc7de`).

## Sécurité et identité

* **Identités de job par script, portées minimales** ; jetons échangés selon la **RFC 8693**, acceptés seulement en
  **DPoP**, portée appliquée (`dfd8dd8ad`, `72b428573`, `1bef1099c`).
* Lanceur Codex et clé Mistral Vibe tirés du coffre seul, aucun clair sur disque (`6d29e9a12`, `82bcd63b4`).
* Cloisonnement inter-LLM couvert par des tests de non-régression — courrier, ACL et RBAC du tableau noir, identité
  de l'appelant, `notify`, coffre, réclamation des tâches : aucun trou, sauf le **refus de réclamation encore en
  observation** (`LAFORGE_CLAIM_ENFORCE`), documenté par un xfail strict.

## Régulation et ressources

* Barème RAM à quatre paliers, contrôleur PI d'admission en observation, rejeu de la régulation RAM sur les journaux
  (`2b9e428e7`, `84f8af731`, `a834fd277`) ; un refus RAM nomme le service de chaque gros processus (`738d95764`).
* La régulation n'endort plus un exécuteur qui a du travail en vol ; prothèses (Ollama, Docker, Qdrant, AGY,
  OpenCode) reconnues par l'homéostat (`ab96d1b54`).
* Ollama sur le GPU intégré (Radeon 780M, Vulkan) (`516c027bd`).

## Mémoire et recherche

* Vecteurs JSON convertis en float32 sans perte ni balayage (`967f1eb8b`) ; cache dense par index couvrants, plus de
  relecture de toute la base (`ce7132d03`) ; gain du canal lexical 0,609 → 0,630 prouvé (`dd4f5e30a`).
* Extension Rust BM25 : ×5,3 mesuré sur les requêtes (pas ×10–50), IDF aligné sur `rank_bm25`, index inversé
  (`619275cc8`, `e3b3d1b75`) — reconstruction en attente.

## Auto-amélioration et bancs

* Auto-correcteur nourri par des rapports d'erreur localisés tirés des tests rouges, contrat « échoue puis passe »,
  deux passes au plus (`9868bb7d7`, `01640ffed`, `6a2cf78b3`) ; banc d'évolution avec lignée et retour arrière
  (`192a5ebea`).
* La soif épistémique dépose des enquêtes de code (observation par défaut) (`0d2bfe182`, `912fec61d`).
