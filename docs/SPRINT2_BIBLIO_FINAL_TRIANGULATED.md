# Sprint 2 Bibliography Worker - Synthese 3 voix consolidee

Date : 2026-04-27
Voix consultees :
- Claude (moi) : ordre vertical slice (alpha/beta/gamma)
- GPT-4o GitHub Models : audit DBA SQLite
- Mistral Large : strategie split sprint pour solo dev

## Convergence forte (3/3)

### Ne PAS faire de monolithe 38h
- Mistral : "monolithe c'est du suicide pour solo sous Windows"
- Moi : "besoin livrable rapide pour ajuster"
- GPT-4o (implicitement via ses 13h additionnels) : trop d'enrichissements
=> **VERDICT : split obligatoire**

### Ordre des bloquants critiques
- Mistral : schema DB + EventBus + daemon = colonne vertebrale
- Moi : memes 3 elements en alpha
- GPT-4o : pas oppose, focus sur enrichissements
=> **VERDICT : MVP minimal first (schema + extracteur + daemon + 1 passe + promotion manuelle)**

## Convergence sur ce qui est REPORTABLE

| Element | Mistral | Claude | Verdict |
|---------|---------|--------|---------|
| Affineur LLM 3 passes | report 2b | beta | -> beta |
| Beall list | report 2b | beta | -> beta |
| Retracted detection | report 2b | beta | -> beta |
| Rate limiting budget | report 2b | beta | -> beta |
| Tests integration | report 2b | gamma | -> gamma |

## Plan consolide final (3 phases, livraison incrementale)

### PHASE ALPHA - MVP utilisable seul (~16h)

Objectif : pipeline fonctionnel basique. Tu colles -> extrait -> cherche -> tu valides via TUI.

| # | Tache | h | Detail |
|---|-------|---|--------|
| 1 | Schema DB minimal (ideas + biblio_raw + bibliography) + INDEX cles | 2 | Pas rejected ni bunker en alpha. Index sur status/triggered_by_idea_id (GPT-4o) |
| 2 | Hook EventBus biblio.text_pasted -> Mistral extracteur | 4 | Provider fixe Mistral |
| 3 | Daemon NSSM stub (1 source par cycle, 1 passe DOI simple) | 4 | Pas de rate limiting yet, juste sleep 3s |
| 4 | Affineur requete BASIQUE 1 passe (DOI seulement) | 2 | Pas multi-passe |
| 5 | Sanitization basique (Q5 regex existantes + URL whitelist) | 2 | Sans Beall ni retracted |
| 6 | TUI command @biblio promote / list (validation manuelle simple) | 2 | Le minimum pour valider |

**Livrable Alpha** : tu colles un texte avec citations -> Mistral extrait -> entre dans biblio_raw -> daemon cherche DOI -> tu valides via @biblio promote -> entre dans bibliography + rag_chunks.

### PHASE BETA - Robustesse production (~17h)

Objectif : qualite controlee, anti-pollution, multi-passe.

| # | Tache | h | Detail |
|---|-------|---|--------|
| 7 | Schema complet (rejected + bunker + budget) + migration alpha | 1.5 | Avec hash_chain table dediee (GPT-4o reco) |
| 8 | Sanitization avancee : Beall list + retracted Crossref + lingua-py + score confiance | 5 | Cron quotidien Beall snapshot |
| 9 | Rate limiting budget global par engine (SQLite, OK pour 200/jour) | 4 | Fallback dynamique Scholar->Semantic->OpenAlex |
| 10 | Affineur 3 passes (DOI/PDF/contexte) avec engines reequilibres Mistral | 2.5 | Apres correction Mistral Q-C |
| 11 | Triggers SQL ON DELETE SET NULL + audit log purges (GPT-4o reco #4) | 1 | Anti corruption referentielle |
| 12 | Constraints CHECK + UNIQUE payload_hash (GPT-4o reco #2) | 1 | Anti doublons |
| 13 | Bunker hash_chain integration (GPT-4o reco #6) | 1 | Integrite shadow libs |
| 14 | Rotation biblio_rejected (archive >6mois, purge >2ans) (GPT-4o reco #5) | 1 | Maintenance daemon |

**Livrable Beta** : worker prod-ready, anti-pollution, qualite controlee.

### PHASE GAMMA - Lifecycle complet (~10h)

Objectif : automatisation purge orphan + tests + doc.

| # | Tache | h | Detail |
|---|-------|---|--------|
| 15 | Mecanisme purge orphan sur idea.refined event | 3 | Avec cold_backup pre-purge (forge_versioning pattern) |
| 16 | TUI commands @biblio purge orphans / pin / unpin | 2 | Etend les @rag commands existantes |
| 17 | Tests integration : rate limiting + fallback + purge orphan | 3 | Tests pytest fixtures |
| 18 | Documentation utilisateur + run-book (markdown) | 2 | docs/BIBLIO_USAGE.md |

**Livrable Gamma** : worker complet avec gestion auto du lifecycle.

## Total revise : 16h + 17h + 10h = 43h

(au lieu de 38h initial)
+5h provenant des recos GPT-4o (index, constraints, hash_chain dedie, triggers, rotation, bunker hash)

## Ce que GPT-4o a apporte de critique

1. **INDEX manquants** sur triggered_by_idea_id, status, pinned, payload_hash, raw_id
2. **CHECK constraints** sur status enums et source_engine enums
3. **UNIQUE payload_hash** pour eviter doublons silencieux
4. **Table hash_chain dediee** plutot qu'embed dans biblio_raw (FK universelle)
5. **ON DELETE SET NULL** sur triggered_by_idea_id pour eviter purge cascade
6. **Bunker doit AVOIR hash_chain** (oubli dans schema initial, vrai risque)
7. **Rotation biblio_rejected** : archive 6mois + purge 2ans
8. **SQLite OK pour 200/jour**, migration Redis seulement >1000/jour

## Decisions actees apres triangulation

- Plan 3 phases ALPHA/BETA/GAMMA (livraison incrementale)
- Schema enrichi des recos GPT-4o (index + constraints + hash_chain table dediee + triggers ON DELETE)
- Phase ALPHA livre quelque chose d'UTILE meme sans le reste
- 43h total au lieu de 38h, etale sur 3 livrables independants
- Pas de tests en alpha (fait en gamma)
- Pas de Beall/retracted en alpha (fait en beta)
- Pas de purge orphan en alpha/beta (fait en gamma)

## Question pour l'utilisateur

1. Plan 3 phases ALPHA/BETA/GAMMA OK ?
2. Phase ALPHA 16h en premier sprint, ou tu veux commencer plus petit (8h juste schema + extracteur + daemon stub) ?
3. Validation finale du schema enrichi GPT-4o avant Sprint Alpha ?
