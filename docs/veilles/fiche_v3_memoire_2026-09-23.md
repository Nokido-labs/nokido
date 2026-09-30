# Fiche de sortie — Veille V3 « Mémoire agentique / compaction / RAG long contexte » (2026-09-23)

Contrat : PATTERNS → NOKIDO_EXISTING → EVIDENCE → GAPS → MINIMAL_EXPERIMENT → NR → DECISION. Pipeline B.
Interroge V1 (agents longs : état hors contexte) et V2 (grader d'issue).

## 1. PATTERNS (`watch:memoire:%`, `watch:rag_long:%`)

| Pattern | Source |
|---|---|
| Trois mémoires : **sémantique** (faits), **épisodique** (expériences), **procédurale** (règles) ; mise à jour « à chaud » (dans la logique) ou « en arrière-plan » | LangGraph memory (CoALA) |
| Honnêteté du déclaré : « trois types définis, UN seul câblé — ne construisez pas contre un type qui n'existe pas » | mem0 memory types |
| Mémoire hiérarchique / pagination de contexte (blocs en contexte ↔ archive) | Letta / MemGPT |
| Outil mémoire persistant inter-sessions (fichiers lus/écrits par l'agent) | Claude memory tool |
| Validité TEMPORELLE des faits (bi-temporel : vrai quand / connu quand) | Zep (arXiv 2501.13956) |
| Réflexion / importance / consolidation | Generative Agents (arXiv 2304.03442) |
| Position dans le contexte long (milieu mal exploité) ; résumés récursifs en arbre | Lost in the Middle ; RAPTOR |

⚠️ **Qualité de veille** : les pages `arxiv.org/abs/…` ont produit des chunks PAUVRES (historique de soumission,
navigation) ; le corps des articles est sous `arxiv.org/html/<id>`. Sources arXiv = ACQUIRED mais **faible substance** →
à remplacer (REPLACED_BY_CURRENT_SOURCE) avant toute conclusion tirée de ces articles.

## 2. NOKIDO_EXISTING

- Sémantique : RAG hybride (dense + lexical FTS, fusion, rerank) ; colonnes `active` / `superseded_by` /
  `retraction_status` — `active` **respecté par le moteur depuis `97d552a90`** (aujourd'hui).
- Épisodique : domaine `episodic_memory` (22 chunks déjà `active=0`) ; `tools/forge_symptom_index.py` (« suis-je
  déjà passé par là ? », index des enquêtes) ; `lessons_learned.md` + `session_summary`.
- Procédurale : règles `CLAUDE.md` / `RULES_SHARED.md` ; mémoire Claude (`MEMORY.md`, fiches `feedback_*`) ;
  hooks qui RÉINJECTENT au bon moment (`hook_recon_first`, `hook_capability_gate`).
- Compaction : `tools/forge_auto_compact.py` (NR « âge inconnu ≠ ancien », PROUVÉ 30/08).
- `parent_summary_id` / `compaction_seq` : **absents de `app/` et `tools/`** (findstr) ; non cherchés ailleurs → INCONNU.

## 3. EVIDENCE

| Élément | Niveau |
|---|---|
| Réinjection procédurale/épisodique au moment de l'action | **VERIFIED** — observée 3 fois AUJOURD'HUI : `hook_recon_first` m'a arrêté sur `write_retry`, `session_summary`, `open_writer` en citant les enquêtes passées |
| Oubli par marquage (`active=0`) | **VERIFIED** (NR `test_rag_respecte_active_nr`, 655 216 chunks raffinés) — effet dense au prochain démarrage du hub |
| Compaction auto | **MEASURED** (NR 30/08) ; déclenchement réel en production non mesuré ici |
| Validité temporelle des faits | **absente** (les fiches mémoire disent « se périment : vérifier la date » — discipline humaine) |

## 4. GAPS

1. **Pas de validité temporelle** sur les faits : un fait daté du 01/09 et un fait du 23/09 pèsent pareil au rappel.
2. Les trois mémoires existent mais **ne sont pas typées** dans le RAG (un chunk ne dit pas s'il est fait, épisode ou règle).
3. Pas de mesure du **rappel utile** : quelle part des réinjections a évité une erreur (vs bruit) ?
4. Campagne de veille : **chunks faibles** (arXiv abs) non détectés à l'ingestion — le filtre substance juge le
   chemin, pas la densité d'information.

## 5. MINIMAL_EXPERIMENT (lecture seule)

(a) Rejouer `forge_symptom_index --ask` sur les 10 incidents de ce jour : combien avaient une enquête antérieure
pertinente ? (mesure du rappel, sans rien modifier). (b) Densité des chunks par source de veille (ratio mots utiles /
boilerplate) pour classer automatiquement « faible substance ».

## 6. NR

`test_rappel_symptome_incident_connu_nr` : un symptôme déjà enquêté (fixture) remonte l'enquête en tête ;
`test_densite_chunk_boilerplate_nr` : une page « abs » arXiv est classée FAIBLE, un corps d'article ne l'est pas.

## 7. DECISION

- **CONSERVER** la réinjection par hooks (VERIFIED, efficace).
- **COMPLÉTER** : typage épisode/fait/règle + validité temporelle — après la mesure (a).
- **CORRIGER la veille** : re-sourcer les articles arXiv en `/html/`.
- UNKNOWN : `parent_summary_id`/`compaction_seq` (périmètre non couvert).
- Contradiction avec V1 : V1 notait « pas d'état de progrès HORS contexte pour une campagne » ; V3 montre que la
  mémoire procédurale/épisodique EXISTE et marche — le manque est spécifique à l'**état de campagne** (quoi est fait,
  quoi reste), pas à la mémoire en général. V1 précisé, pas contredit.
