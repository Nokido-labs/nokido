# Decision TTL biblio_raw - Patterns existants Nokido identifies

Date : 2026-04-27
Status : DOC ONLY - decisions actees

## Decision finale : pas de TTL absolu, purge par raffinement d'idee

L'utilisateur a tranche : pas de TTL fixe (3j/7j/30j), MAIS purge declenchee
quand l'idee originelle qui a fait charger la source est raffinee/transformee.

## Rationale

Le TTL fixe est une heuristique grossiere : il purge des sources peut-etre
encore pertinentes juste parce qu'elles ont vieilli. La purge par raffinement
d'idee est plus precise : elle reflete le fait que les sources liees a une
ancienne formulation deviennent obsoletes quand on reformule la question.

Exemple concret :
- Idee initiale : "comment fonctionne ReAct dans les LLM ?"
  -> sources biblio_raw : papier ReAct + papier CoT + tutos generaux
- Idee raffinee : "comment ReAct se compare a Toolformer pour le tool calling ?"
  -> les tutos generaux deviennent obsoletes, papier Toolformer apparait
  -> purge auto des tutos generaux non promus VERIFIED entre temps

## Mecanisme requis dans le schema

Table `biblio_raw` doit avoir :
- `triggered_by_idea_id` (FK vers une table `ideas` ou similaire) : trace l'idee origine
- `pinned: bool` (defaut false) : protege l'entree de la purge auto si toi tu decides de la garder
- `superseded_by_idea_id` : si l'idee a evolue, pointer vers la nouvelle

Workflow purge :
1. Une idee est raffinee -> nouvelle entree `ideas` avec `parent_idea_id`
2. Hook EventBus `idea.refined` -> declenche purge_orphan_sources(old_idea_id)
3. Purge supprime biblio_raw WHERE triggered_by_idea_id=old AND status=unverified AND pinned=false
4. Audit log de chaque purge avec corr_id + raison "idea_refined"

## Patterns existants Nokido a reutiliser (decouverts)

### 1. forge_rag_janitor.py - clean_orphans + purge_old_logs

```python
class RAGJanitor:
    def clean_orphans(self) -> int:
        """Supprime chunks dont la source disque n'existe plus."""
    
    def purge_old_logs(self, days: int = 7) -> int:
        """Purge sessions plus vieilles que N jours."""
```

Pattern reutilisable : ETENDRE avec methode `purge_orphan_biblio_sources(old_idea_id)`.

### 2. TUI command @rag purge - dans forge_handler_rag.py

Commandes existantes :
- `@rag purge session` : vide chunks conversation
- `@rag purge all` : vide tout (DOUBLE CONFIRMATION + cold_backup AVANT)
- `@rag del <source>` : supprime une source specifique
- `@rag reindex` : retire fichiers supprimes

Pattern reutilisable : etendre la TUI avec :
- `@biblio purge orphans` : purge biblio_raw orphelines (idee raffinee)
- `@biblio pin <id>` : protege une entree de la purge auto
- `@biblio unpin <id>` : retire la protection
- `@biblio promote <id>` : valide manuellement vers bibliography (passage VERIFIED)

### 3. forge_versioning.py - staging zone + checkpoint + rollback

Pattern critique :
- staging_dir / backup_dir separes
- _staging_lock (un seul staging actif)
- Checkpoint AVANT toute modif
- Rollback automatique sur exception
- GFS rotation (10 max + hebdo + mensuel)
- cold_backup pre-purge destructive (pour @rag purge all)

Application biblio :
- AVANT toute purge biblio_raw : cold_backup (snapshot DB)
- Sur erreur de purge : rollback complet
- Garde 10 derniers snapshots biblio + 1 hebdo + 1 mensuel

## Schema final biblio_raw enrichi

```sql
CREATE TABLE ideas (
    id              TEXT PRIMARY KEY,           -- uuid
    text            TEXT NOT NULL,              -- la formulation originale ou raffinee
    parent_idea_id  TEXT,                       -- FK ideas.id si raffinement d'une idee precedente
    superseded_by   TEXT,                       -- FK ideas.id si remplacee par version + recente
    created_at      TEXT DEFAULT (datetime('now')),
    refined_at      TEXT,                       -- date du raffinement (= date du superseded_by)
    status          TEXT DEFAULT 'active',      -- active | superseded | abandoned
    FOREIGN KEY (parent_idea_id) REFERENCES ideas(id),
    FOREIGN KEY (superseded_by) REFERENCES ideas(id)
);

CREATE TABLE biblio_raw (
    id              TEXT PRIMARY KEY,           -- uuid
    type            TEXT,                       -- book | paper | url | concept
    title           TEXT NOT NULL,
    authors         TEXT,                       -- JSON array
    year            INTEGER,
    venue           TEXT,
    url             TEXT,
    pdf_url         TEXT,
    doi             TEXT,
    isbn            TEXT,                       -- JSON array
    tags            TEXT,                       -- JSON array
    description     TEXT,
    
    -- Provenance & lien causal avec l'idee
    triggered_by_idea_id  TEXT,                 -- FK ideas.id : QUI a fait charger cette source ?
    source_kind     TEXT DEFAULT 'agent_extract',  -- human_paste | agent_extract | agent_research
    source_engine   TEXT,                       -- arxiv | crossref | google scholar | ...
    extracted_at    TEXT DEFAULT (datetime('now')),
    
    -- Sanitization Q5
    payload_hash    TEXT,                       -- sha256(payload normalise RFC 8785)
    parent_hash     TEXT,                       -- chainage hash precedent
    sanitization_passed BOOL DEFAULT 0,         -- bilan sanitize regex + URL whitelist + DOI valid
    confidence_score INTEGER,                   -- score composite 0-100 (cf Mistral Q-E)
    
    -- Workflow promotion
    status          TEXT DEFAULT 'unverified',  -- unverified | reviewed | promoted | rejected
    pinned          BOOL DEFAULT 0,             -- toi qui decides de proteger
    reviewer_id     TEXT,                       -- agent ou RING_0
    reviewed_at     TEXT,
    rejection_reason TEXT,                      -- si rejected : retracted | predatory | shadow_lib | low_score | duplicate
    
    FOREIGN KEY (triggered_by_idea_id) REFERENCES ideas(id)
);

CREATE TABLE bibliography (
    -- meme schema que biblio_raw mais SEULEMENT entrees verified
    -- + colonne `promoted_at` + `promoted_from_raw_id` (audit trail)
    -- + colonne `embedding` (vectorisee dans rag_chunks domain='bibliography')
);

CREATE TABLE biblio_rejected (
    -- archive des rejetees pour eviter reingestion + audit
    id              TEXT PRIMARY KEY,
    raw_id          TEXT,                       -- FK biblio_raw.id (avant suppression)
    rejection_reason TEXT,                      -- meme enum que biblio_raw.rejection_reason
    rejected_at     TEXT DEFAULT (datetime('now')),
    rejected_by     TEXT                        -- agent ou raison auto (idea_refined, retracted, etc.)
);

CREATE TABLE bunker_shadow_libs (
    -- BUNKER : zone isolee pour annas archive, library genesis, etc.
    -- JAMAIS dans rag_chunks. JAMAIS auto-promu vers bibliography.
    id              TEXT PRIMARY KEY,
    title           TEXT NOT NULL,
    authors         TEXT,
    pdf_url         TEXT,
    source_engine   TEXT CHECK(source_engine IN ('annas archive','library genesis')),
    triggered_by_idea_id TEXT,
    found_at        TEXT DEFAULT (datetime('now')),
    accessed_count  INTEGER DEFAULT 0,          -- audit acces
    FOREIGN KEY (triggered_by_idea_id) REFERENCES ideas(id)
);

CREATE TABLE searxng_rate_budget (
    engine          TEXT PRIMARY KEY,
    requests_made   INTEGER DEFAULT 0,
    window_start    TEXT,                       -- debut fenetre 1h glissante
    last_429_at     TEXT,                       -- dernier rate-limit hit
    cooldown_until  TEXT                        -- jusqu'a quand ne pas requeter
);
```

## Ordre revisite Sprint 2

| Tache                                                  | Heures |
|--------------------------------------------------------|--------|
| Schema DB (ideas + biblio_raw + bibliography + bunker + rejected + budget) | 3h |
| Hook EventBus `biblio.text_pasted` -> Mistral extracteur | 4h     |
| Daemon NSSM `NokidoBiblioWorker` (queue consumer)     | 6h     |
| Affineur requete LLM (multi-langue, 3 passes revisees) | 4h     |
| Sanitization Q5 + retracted (Crossref API) + Beall + langdetect | 5h |
| Rate limiting (budget global + cooldown dynamique)     | 4h     |
| Promotion workflow (unverified -> verified)            | 3h     |
| **Mecanisme purge orphelines sur idea.refined event**  | **3h** |
| TUI commands `@biblio purge orphans` `@biblio pin/unpin/promote` | 3h |
| Tests rate limiting + fallback + purge orphan          | 3h     |
| **TOTAL revise**                                       | **38h** |

Ajout vs version precedente : 7h pour le mecanisme purge par raffinement
+ etendue TUI commands.

## Decisions actees

1. Pas de TTL fixe pour biblio_raw
2. Purge declenchee par event `idea.refined` sur les sources orphelines unverified
3. Flag `pinned` pour proteger les entrees malgre purge
4. Reutilisation patterns existants : RAGJanitor + TUI @rag purge + forge_versioning staging
5. Cold backup AVANT toute purge destructive (cf forge_versioning)
6. TUI etendue avec @biblio commands
7. Bunker shadow libs en table dediee, JAMAIS dans rag_chunks
8. Multi-LLM par sous-tache (Mistral extract, Groq affine, Qwen tri local)

## Validation finale

Avant Sprint 2 code, je dois te confirmer :
- Le **schema DB final** ci-dessus convient ? Modifs ?
- Effort 38h sprint monolithique OK, ou split en 2a + 2b ?
- L'ordre des taches : est-ce que Schema DB doit vraiment etre fait avant tout ?
