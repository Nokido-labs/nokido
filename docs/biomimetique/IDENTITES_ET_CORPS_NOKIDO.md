# Cadre d'identité des agents : cerveau, sens, mémoire, âme, règles — proposition AGY (corrigée)

**Date :** 2026-10-23 · **Auteur :** ANTIGRAVITY (session interactive, demande owner) · **Rapatrié et corrigé par :** CLAUDE, sur GO owner.
**Statut : PROPOSITION.** L'original se déclarait « doctrine d'incarnation validée » (fait `cadre_identites_organiques_soul_nokido_20261023`) sans mesure.
**Contrat exécutable correspondant :** `docs/INTEROCEPTION_ENDPOINTS_PLAN.md` (CODEX, 23/10) — contrat par appel, ordre P0→P4. Ce document donne le vocabulaire ; le plan Codex donne ce qui se mesure.
**Original non suivi :** `../docs/IDENTITES_ET_CORPS_NOKIDO.md` du dépôt parent.

---

## 1. Les cinq dimensions d'une identité

1. **Cerveau** — le modèle effectivement servi pour l'appel.
2. **Sens** — ce que l'identité perçoit de l'extérieur et du corps (faim, soif, fatigue, vigilance), via le hub et selon son ring.
3. **Mémoire** — ce qu'elle lit et écrit (SSoT, RAG, tableau noir, mémoire propre à la surface).
4. **Âme** — finalité, style, invariants (`docs/biomimetique/SOUL.md`). **N'accorde aucun droit d'exécution.**
5. **Règles** — ring effectif, `write_paths`, gardes.

**Correction de fond (contre-audit) :** distinguer par appel **principal** (identité authentifiée, ring décidé par le hub), **profil d'agent** (rôle, règles, mémoire, outils), **endpoint effectif** (client, provider, modèle) et **état de l'appel** (trace, usage, latence, signaux). Le modèle n'est pas l'identité ; l'autorité vient du hub, jamais d'un document.

## 2. Cerveau — valeurs observées, pas déclarées

La version AGY attribuait « Claude 3.7 Sonnet », « GPT-4o », « Gemini 2.5 Pro », « Llama 3.3 70B » sans mesure. Retiré. Règle : le modèle effectif se lit par appel (journal `forge_token_monitor.log_call` : provider + modèle servis) ; absent = `UNKNOWN`.

| Identité | Modèle observé le 23/10 | Source |
|---|---|---|
| ANTIGRAVITY | Gemini 3.8 Flash (High) | bandeau de la session interactive |
| CLAUDE (Claude Code) | Opus 5.5 | session courante |
| CLAUDE_HEADLESS | non relevé | journal de l'exécuteur à lire |
| CODEX | non relevé | — |
| OPENCODE_* | selon la variante (GLM, GPT-OSS, Nemotron…) | nom de l'exécuteur ; modèle exact à lire |

## 3. Sens — définis comme mesures sourcées

| Sens | Mesure candidate | Garde-fou |
|---|---|---|
| Faim (énergie) | coût / budget du jour, quota fournisseur | provider muet = `UNKNOWN`, jamais « affamé » |
| Soif (information) | recherche RAG pauvre sur le sujet | appelle une veille, n'affirme pas |
| Fatigue | RAM plancher 60 s, contexte consommé | jamais déduite d'une fenêtre supposée |
| Vigilance | hormones actives **non expirées** (âge, TTL) | un cortisol expiré ne compte pas |

Chaque valeur porte unité, portée (machine / hub / provider / session), âge, producteur et état (`OBSERVED`, `DECLARED`, `STALE`, `UNAVAILABLE`, `UNKNOWN`).

## 4. Mémoire

- **Tableau noir** : état partagé transitoire (confiance, âge, dégradation de confiance effective).
- **RAG / SSoT** : connaissances persistées et sourcées. **Correction :** `anchor_solution` écrit **immédiatement** ; le transfert « pendant le sommeil » n'est pas démontré.
- **Mémoire de surface** (`MEMORY.md`, scratch) : ne remonte au corps qu'ancrée dans une surface distribuée.

## 5. Règles

Le ring effectif est **décidé par le hub** (`_resolve_ring`, `forge_agent_authority`). La table de rings de l'original (Codex en ring 2) est retirée : l'audit du 23/10 à 21 h 31 montre CODEX en ring 1. Le registre `config/agent_identities.json` est déclaratif ; ne jamais le traiter comme l'autorité.

## 6. Pistes scientifiques — statut (contre-audit Codex)

| Piste | Statut |
|---|---|
| Active Inference (Friston) | partiel : `forge_active_inference.py`, `CyberAgent` (pymdp) ; pas de boucle FEP complète |
| Couvertures de Markov = compartiments | analogie à corriger (frontière statistique ≠ frontière de sécurité) |
| Tuples biochimiques (SAPERE) | source pertinente, transposition non réalisée |
| Systèmes endocriniens artificiels | partiel et réellement câblé |
| Ultrastabilité d'Ashby | partiel, pas de seconde boucle |
| Control Barrier Functions | non établi |
| LIDA / espace de travail global | ressemblance partielle |
