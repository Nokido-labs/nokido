# Architecture biomimétique de Nokido — proposition AGY (corrigée)

**Date :** 2026-10-23 · **Auteur :** ANTIGRAVITY (session interactive) · **Rapatrié et corrigé par :** CLAUDE, sur GO owner.
**Statut : PROPOSITION, non validée.** La version d'origine se déclarait « doctrine opérationnelle validée » (fait `matrice_biomimetique_modules_nokido_20261023`, confiance 1.0) : aucune validation owner ni mesure ne le portait.
**Item de roadmap qui porte ce travail :** `P1_audit_analogie_corps_apres_ci_20261020` (audit organe par organe, demandé par l'owner le 20/10). Ce document en est une contribution, pas un système parallèle.
**Contre-audit fondé sur le code :** `docs/INTEROCEPTION_ENDPOINTS_PLAN.md`, section « Contre-audit exhaustif des pistes AGY » (CODEX, 23/10). En cas de désaccord, le contre-audit prévaut.
**Original non suivi :** `../docs/ARCHITECTURE_BIOMIMETIQUE_NOKIDO.md` du dépôt parent (laissé en place, geler, jamais supprimer).

---

## 1. Thèse

Un système purement événementiel est aveugle à la charge globale ; la physiologie régule sans contrôleur central par double vitesse (réflexe nerveux / bain endocrinien), perfusion différentielle, confinement local des pannes et rythme veille/sommeil.

**Correction :** l'opposition « organique contre événementiel » est écartée (contre-audit). La biologie combine aussi impulsions discrètes et concentrations continues ; Nokido garde le bus comme transport et module l'intensité de la réponse par des mesures d'état. L'analogie porte sur la **boucle** (stimulus → mesure sourcée → décision bornée → effet → observation après effet), pas sur les noms d'organes.

## 2. Carte organe ↔ module (vue narrative)

**La carte qui fait autorité est le census `sandbox/workspace/organ_map_full.json` (skill forge-anatomy).** Cette table est une vue humaine ; existence des modules mesurée le 23/10.

| Organe | Module(s) | Rôle proposé | Mesure 23/10 |
|---|---|---|---|
| Cortex préfrontal | `forge_cognitive_router.py`, ~~`forge_planner.py`~~ | Délibération, arbitrage GOAP | `forge_planner.py` **ABSENT** |
| Cervelet (SNN) | `forge_spike_router.py`, `NokidoSNN/` | Pré-sélection sub-symbolique | présents |
| Thalamus | `forge_nlu.py`, `forge_byte_router.py` | Triage des entrées | présents |
| Moelle / arc réflexe | `tools/bash_guard.py`, gates AST, rings | Coupure déterministe sans LLM | présents ; « < 1 ms » **non mesuré** |
| Barrière hémato-encéphalique | `forge_semantic_firewall.py` | pre/post-flight | présent |
| Membrane cellulaire | `forge_sovereign_membrane.py` | Caviardage d'egress | présent |
| Immunité (macrophages) | `forge_clawhub_bridge.py`, sandbox | Confinement local | présent |
| Cardiovasculaire (perfusion) | `forge_chain_executor.py`, `forge_anatomy_state.py`, `forge_resource_manager.py` | Allocation RAM/VRAM/budget | présents |
| Foie | Ollama :11434, llama-server | Inférence locale | — |
| Endocrinien | `forge_hormones.py`, `forge_endocrine.py` | Signaux à demi-vie | présents |
| Estomac | `forge_ingest_self.py`, ~~`forge_crawler.py`~~ | Digestion brute | `forge_crawler.py` **ABSENT** |
| Intestin grêle | `forge_rag_qualify.py` | Absorption sélective | présent |
| Hippocampe | `forge_self_correction.py` | `anchor_solution` / `anchor_error` | présent — **écrit immédiatement**, pas « pendant le sommeil » |
| Mémoire long terme | `RAGEngine`, `embeddings.db`, `rag_fts` | Engrammes | — |
| Bulbe / végétatif | `forge_inspector.py`, `forge_idle_watchdog.py` | Pouls, verrous | présents |
| Circadien | `SSoTMaintainer`, `forge_glymphatic_gc.py` | Alternance travail / maintenance | présents |

## 3. Quatre lois proposées et leur statut

### Loi 1 — Double vitesse
Réflexes déterministes à la frontière d'une action ; modulation endocrinienne continue.
**Déjà réel (contre-audit) :** le cortisol module les seuils de `should_throttle()` ; `FlowRegulator.get_dynamic_threshold()` combine CPU, endocrinien et surprise. **Non vérifié :** les demi-vies citées (~60 s adrénaline, ~15 min cortisol) — lire `forge_hormones.release/active` avant de les reprendre. **Invariant :** aucune hormone ne relâche une barrière de sécurité.

### Loi 2 — Perfusion différentielle
Sous charge, réduire les organes secondaires (veille, crawl) au profit de l'agent au contact de l'owner. **Réel en partie :** `attribuer_pression()` (SOI / NON_SOI / NOYAU) et les seuils de throttle. **Rejeté :** la variante « fièvre PGE₂ » qui relève la consigne RAM à 95 % — elle confond priorité et limite de survie (seuil de blocage P1 à 85 %) ; une urgence déplace la perfusion, jamais une limite dure.

### Loi 3 — Confinement local des pannes
But utile. **Justification retirée :** arXiv:1802.03286 étudie des distributions de cascades sur des topologies données ; il ne prouve pas qu'une panne locale Nokido effondre tout. Les quarantaines se justifient par les chemins de panne **mesurés**.

### Loi 4 — Rythme veille / maintenance
**Non démontré :** stade « NREM3 », mélatonine pilotant le consolidateur, transfert automatique Blackboard → RAG. arXiv:2608.04126 (Hopf) ne valide pas un cycle Nokido. Garder validation et provenance avant toute mémoire durable.

## 4. Sources : corrections

- arXiv:1510.01087 : **retiré par son auteur** selon le contre-audit (non revérifié par CLAUDE) — ne pas citer comme preuve.
- arXiv:2306.15145 / 2309.06509 : résultats mathématiques/biologiques ; ne dérivent pas une loi RAM `dM/dt`.

## 5. Chantiers — réordonnés sur le plan du contre-audit

1. **P0** corrélation identité / span de bout en bout (le témoin du 23/10 montre CODEX à l'entrée, HUB à la sortie).
2. **P1** vue intéroceptive read-only, états triés (déclaré / observé / vérifié), scopes RBAC.
3. **P2** preuve des consommateurs hormonaux et des effets exécutés (une hormone publiée sans lecteur prouvé = « consommation UNKNOWN »).
4. **P3** pilote d'hystérésis bornée sur l'admission des travaux lourds, puis banc de transitoires.
5. **P4** seulement si la mesure le justifie : cadence du keeper, dynamique de flux dans `forge_anatomy_state` (`flows_live` / `flows_reason` existent déjà).
