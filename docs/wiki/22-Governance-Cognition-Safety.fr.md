---
type: guide
title: 22 — Gouvernance, cognition & auto-sûreté
status: draft
resource: repo://docs/wiki/22-Governance-Cognition-Safety.fr.md
generated: {by: forge_wiki_modules@INCONNU, at: 2026-09-22T13:02:47+00:00}
empreinte: INCONNUE
---

# 22 — Gouvernance, cognition & auto-sûreté

<!-- revu-le: 2026-09-29 -->
> Mise à jour : 2026-09-29

> 🌐 [English](22-Governance-Cognition-Safety.md) · **Français**

Ces organes permettent à Nokido de **se gouverner, savoir ce qu'il ne sait pas, et
empêcher son propre code auto-généré de régresser**. Tous sont déterministes ou
calibrés — **jamais un LLM dans le verdict**.

---

## Intégrité de livraison — le déclaré face au réel

**Module :** `app/forge_delivery_integrity.py` · **tranche avec :** git + SQLite (0 token) ·
**tourne :** greffé au tick homéostatique.

`status=done` signifie *« l'agent a répondu »*, jamais *« le code existe »*. Cet organe
prouve la différence. Sept scanners déterministes :

| Scanner | Ce qu'il capte |
|---|---|
| `attestation_commit_anterieur` | une tâche « done » citant un commit **antérieur à elle-même** |
| `attestation_contredite` | une enveloppe `SUCCESS` / `OK_DONE` enveloppant un contenu `ERROR` / timeout |
| `unpushed` | des commits locaux jamais poussés |
| `uncommitted` | du travail resté non commité |
| `submodule_drift` | un pointeur de submodule en dérive (via `ls-tree`, pas `git status`) |
| `stale_queue` | des tâches claim et jamais drainées |
| `ci_failures` | un workflow dont le dernier run est **rouge** (l'angle mort *après* le push) |

Findings **acquittables** (`ack(kind, target, motif)`) et bornés dans le temps — une
cause corrigée cesse de sonner au lieu d'alerter indéfiniment.

---

## Curiosité, calibrée — la soif de connaissance

**Modules :** `app/forge_epistemic_veille.py` + `tools/forge_epistemic_daemon.py`.

Nokido éprouve ses **lacunes**. `coverage_dense(requête)` mesure la couverture
(dense Qdrant + BM25 → rerank cross-encoder). Le point dur : distinguer un vrai gap
*on-domain* du bruit hors-sujet — un score bas seul confond « flash attention 3 » (à
apprendre) et « élevage d'alpagas » (hors-sujet). Le remède, **mesuré** : croiser

- **couverture basse** (rerank), et
- **erreur hors-variété / nouveauté basse** — reconstruction façon autoencoder contre la
  variété d'embeddings de Nokido (concept `forge_novelty_organ` / `forge_goap_intuition` :
  le vrai signal est *net*, le bruit est *plat / hors-variété*).

Détecteur à **double seuil avec abstention** — *dans le doute, s'abstenir*. Il ne veille
jamais sur du non-sens (zéro faux positif mesuré). Un gap confirmé déclenche une veille
profonde (`forge_research_agent` → RAG), intégrée ensuite par `forge_veille_digest`. La
veille lourde est **désarmée par défaut** (`LAFORGE_EPISTEMIC_AUTO_VEILLE=1` pour armer).

> **Leçon de conception (mesurée) :** la pertinence vient de l'**intention** (roadmap /
> organes), pas de la distance brute. Guidée par l'intention, la soif a trouvé un gap réel
> et actionnable — *HNSW recall approx vs exact* — précisément le savoir manquant pour
> basculer sa propre recherche Qdrant en sécurité.

---

## Auto-sûreté du code auto-écrit (Φ_T)

**Module :** `tools/forge_heldout_gate.py` · inspiré du score held-out Φ_T de Metal-Sci.

L'évolution autonome propose du code. Avant qu'il ne parte, un module généré / édité doit
préserver des **invariants sur un échantillon gelé de données de production jamais vues**
du générateur. Profil embedder : vecteurs **1024D** exacts, composantes finies, norme non
nulle, auto-cosinus unitaire. Il attrape les régressions silencieuses de **dimension /
NaN / crash**.

**Honnête, pas décoratif :** il distingue `held_out_OK` de `held_out_absent` (jamais un
vert silencieux sur du non-vérifié). Câblé au hook `PostToolUse` (écritures natives), il
sépare une régression de **code** (bloque) d'un **service absent** (advisory — ne bloque
jamais une édition légitime sur un aléa `:8099` passager).

---

## RAG pondéré par l'autorité + mémoire dense continue

**Module :** `app/forge_mcp_registry.py::_rag_dense_search` + `app/forge_rag_qualify.py`.

La recherche n'est **pas** que de la distance. Le pipeline mêle dense (Qdrant HNSW) +
BM25, rerank cross-encoder, **puis pondère par l'autorité de la source** — doctrine
souveraine au-dessus des leçons, au-dessus du code, au-dessus des docsets tiers — et écarte
l'écho brut des tool-calls. Les règles de Nokido priment sur une doc de librairie sur
*« comment Nokido pense »*. (Les poids chiffrés de la première version ne sont pas repris
ici : les lire dans le code.)

Qdrant était tenu à jour par un **outbox continu** (`tools/forge_qdrant_sync_daemon.py`) :
un trigger SQLite pousse chaque nouvel embedding vers le vector store, **tier froid exclu
par design** (dumps de librairies externes = BM25-only). **Au 2026-09-29, son service
`NokidoQdrantSync` est coupé** (`services.toml`) et le store Qdrant est gelé par décision de
l'owner : le store dense n'est pas rafraîchi tant qu'il reste coupé.

---

## Auto-régulation homéostatique

Seuils **adaptatifs** pilotés par l'erreur de prédiction (`forge_active_inference`,
fenêtre par comptage — une moyenne all-time ment). Gate RAM au spawn **intent-aware**
(évincer l'idle avant de refuser un spawn). Éviction par **capacité**
(`forge_service_capabilities`), jamais par liste de noms figée — la régression de juillet
qui a endormi les trois piliers RAG est désarmée. Délai de boot Docker dérivé de la charge.

> **Discipline des capteurs :** un capteur fraîchement écrit est **suspect, pas témoin**.
> Une affirmation temporelle (« par intermittence ») se réfute par un **log**, jamais par
> une sonde à l'instant t. Le coût des deux erreurs n'est jamais symétrique — dans le doute,
> **s'abstenir**.

---

*Branche `alpha`. Ces organes évoluent ; voir les en-têtes de module et
`docs/Nokido_FEATURES.md` §14 pour l'état courant faisant foi.*
