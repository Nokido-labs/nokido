# CONTRAT D INTERFACE - Sprint α Bibliography Worker

Date : 2026-04-27
Status : Contrat fige avant delegation parallele aux 4 agents
Objectif : permettre que α1, α4, α5, α6b soient ecrites EN PARALLELE par 4 agents
distincts sans qu elles se contredisent. Chaque agent code SA partie et signe le contrat.

## 1. SCHEMA biblio_raw (α1 - GPT-4o)

Toute partie du code qui touche biblio_raw DOIT respecter ces colonnes :

```sql
biblio_raw (
    id              TEXT PRIMARY KEY,           -- 'blr_' + uuid hex 12 chars
    type            TEXT,                       -- book | paper | url | concept
    title           TEXT NOT NULL,
    authors         TEXT,                       -- JSON array string
    year            INTEGER,
    doi             TEXT,
    url             TEXT,
    pdf_url         TEXT,
    description     TEXT,
    triggered_by_idea_id TEXT,
    source_kind     TEXT,                       -- human_paste | agent_extract | agent_research
    payload_hash    TEXT NOT NULL UNIQUE,       -- MD5 hex 32 chars (pas SHA256 en α)
    parent_hash     TEXT,                       -- chainage temporel (NULL pour 1er entry)
    status          TEXT DEFAULT unverified,    -- enum 6 valeurs
    rejection_reason TEXT,                      -- NULL si pas rejete
    search_results_json TEXT,                   -- json brut SearXNG, NULL avant search
    created_at      TEXT DEFAULT (datetime now),
    updated_at      TEXT
)
```

Status enum (8 transitions documentees dans la state machine V4) :
- unverified | queued | searching | reviewed | promoted | rejected

## 2. INTERFACE forge_biblio_core.py (signature publique - moi)

Toute fonction publique du module respecte ces signatures :

```python
from typing import Optional

def extract_from_text(text: str, idea_id: str, agent: str = "CLAUDE") -> list[dict]:
    """
    Appelle Mistral pour extraire sources d un texte.
    Retourne list de dicts conformes au schema entry (cf section 3).
    """

def search_for_entry(entry_id: str) -> dict:
    """
    Lance une recherche SearXNG pour 1 entry (utilise refine_query).
    UPDATE biblio_raw avec search_results_json + status.
    Retourne dict {ok: bool, n_results: int, status: str}.
    """

def list_entries(status_filter: Optional[str] = None, limit: int = 20) -> list[dict]:
    """
    Liste les entries triees par created_at desc.
    """

def promote_entry(entry_id: str, reviewer: str = "RING_0") -> dict:
    """
    Passe entry a status=promoted, INSERT bibliography + rag_chunks.
    """

def reject_entry(entry_id: str, reason: str) -> dict:
    """
    Passe entry a status=rejected.
    """

def pin_entry(entry_id: str, pinned: bool = True) -> dict:
    """
    Marque entry pinned=True pour la proteger de la purge auto.
    """
```

## 3. SCHEMA "entry" (dict Python - utilise par α2 + α5)

Une entry biblio en memoire est ce dict :

```python
{
    "id": "blr_abc123def",                          # str genere
    "type": "paper",                                # enum: book|paper|url|concept
    "title": "ReAct: Synergizing Reasoning...",     # str obligatoire, min 5 chars
    "authors": ["Shunyu Yao", "Jeffrey Zhao"],      # list[str] ou None
    "year": 2022,                                   # int ou None
    "doi": "10.48550/arXiv.2210.03629",            # str ou None, regex section 5.1
    "url": "https://arxiv.org/abs/2210.03629",     # str ou None, whitelist section 5.2
    "pdf_url": "https://arxiv.org/pdf/2210.03629", # str ou None
    "description": "Pattern Reason-Act fondateur",  # str ou None
    "triggered_by_idea_id": "idea_abc123",         # str obligatoire (FK ideas.id)
    "source_kind": "agent_extract",                 # enum
}
```

Validation pydantic (ou jsonschema, peu importe la lib) :
- `title` obligatoire
- `triggered_by_idea_id` obligatoire
- `source_kind` enum strict
- `type` enum strict
- `authors` si present = list[str]
- `year` si present = int dans [1800, 2030]
- `doi` si present = match regex DOI
- `url`/`pdf_url` si present = HTTPS + whitelist domains

## 4. INTERFACE refine_query (α4 - Groq)

```python
def refine_query(entry: dict) -> str:
    """
    Genere une requete SearXNG concise depuis une entry.
    
    Specs :
    - Combine title (6 premiers mots significatifs) + first_author lastname + year
    - Skip stopwords EN+FR (lib stopwords ou liste hardcoded)
    - Cap longueur 100 chars
    - Pas de chars problematiques pour SearXNG (& = ?)
    
    Args:
        entry: dict conforme schema section 3
    
    Returns:
        str: query SearXNG, 1-100 chars, valide
    
    Tests obligatoires (10 cas dans tests/biblio/test_refine_query.py) :
    - 5 entries avec all fields -> 5 queries valides 50-100 chars
    - 2 entries avec title seul -> 2 queries 6 mots max
    - 1 entry avec authors seuls -> query = lastname premier auteur
    - 1 entry vide (que title) -> query = title tronque
    - 1 entry avec chars speciaux dans title -> chars cleanes
    """
```

## 5. INTERFACE forge_biblio_sanitizer.py (α5 - Mistral)

```python
def validate_doi(s: str) -> bool:
    """Regex: ^10\.\d{4,9}/[-._;()/:A-Z0-9]+$ (case insensitive)"""

def validate_arxiv_id(s: str) -> bool:
    """Regex: ^\d{4}\.\d{4,5}(v\d+)?$"""

def validate_isbn(s: str) -> bool:
    """ISBN-10 ou ISBN-13 avec checksum"""

def is_url_whitelisted(url: str) -> tuple[bool, str]:
    """
    Whitelist domains acceptes :
    - arxiv.org, doi.org, oadoi.org, openalex.org
    - openlibrary.org, semanticscholar.org, scholar.google.com
    - openreview.net, neurips.cc, aclanthology.org, ijcai.org
    - acm.org, ieee.org, springer.com, sciencedirect.com
    - github.com (avec note pour validation manuelle si non DOI)
    - zenodo.org, figshare.com, osf.io
    - tout *.edu et *.gov
    Bloque actif :
    - medium.com, dev.to, researchgate.net, academia.edu, blogs perso
    - HTTP non chiffre
    Returns:
        (passed: bool, reason: str)
    """

def sanitize_content(text: str) -> tuple[bool, str]:
    """
    Detecte patterns OWASP LLM01 (instruction override).
    Regex : \b(ignore|disregard|override|you are now|act as|from now on)\b.*(previous|instructions|rules)
    Exception : si encadre dans bloc ```example``` ou <!-- example -->
    Returns:
        (passed: bool, reason: str)
    """

def sanitize_entry(entry: dict) -> tuple[bool, str]:
    """
    Combine validation schema + URL whitelist + content sanitize.
    Pas pydantic ici, juste verifications minimales.
    Returns:
        (passed: bool, reason: str)
    Reasons possibles : doi_invalid | arxiv_invalid | isbn_invalid 
        | url_blacklist | http_not_allowed | prompt_injection 
        | missing_required_field
    """

# Tests obligatoires : tests/biblio/test_sanitizer.py avec 10 cas (5 OK / 5 KO)
```

## 6. INTERFACE Tool MCP (α6a - moi)

Dans `app/forge_mcp_registry.py`, ajout method :

```python
async def handle_biblio(self, args: dict, agent: str, ring: int) -> str:
    """
    Tool MCP `Nokido:biblio`.
    args.action = search | list | promote | reject | pin
    Delegue a forge_biblio_core.py.
    Retourne JSON string.
    """
```

## 7. INTERFACE CLI (α6b - moi)

Dans `tools/biblio_cli.py` :

```bash
python tools/biblio_cli.py search "ReAct paper"
python tools/biblio_cli.py list [--status=reviewed]
python tools/biblio_cli.py promote <entry_id>
python tools/biblio_cli.py reject <entry_id> --reason=duplicate
python tools/biblio_cli.py pin <entry_id> [--unpin]
```

argparse + appels directs forge_biblio_core. Output rich/tabulate.

## 8. ATTRIBUTION DES TACHES

| Agent              | Tache              | Livrable                                          | Estim |
|--------------------|--------------------|--------------------------------------------------|-------|
| GPT-4o GitHub      | α1 schema + migration | `migrations/004_biblio_alpha.sql` + apply_migration.py | 2h |
| Mistral Large      | α5 sanitization      | `app/forge_biblio_sanitizer.py` + tests 10 cas    | 2h    |
| Groq Llama 3.3 70B | α4 refine_query      | fonction Python + tests 10 cas                    | 2h    |
| Claude (moi)       | Contrat + α2 + α3 + α6 + integration | core extraction + worker loop + Tool MCP + CLI | 8h |

## 9. COORDINATION

Les 3 agents externes ecrivent dans `sandbox/biblio_alpha_parallel/<agent>/` :
- `gpt4o/004_biblio_alpha.sql` + `apply_migration.py`
- `mistral/forge_biblio_sanitizer.py` + `test_sanitizer.py`
- `groq/refine_query.py` + `test_refine_query.py`

Apres reception de chaque livrable :
1. AST check via py_compile
2. Validation manuelle de moi (Claude) : conformite contrat
3. Test unitaire execute
4. Si OK -> deplace vers `app/` ou `migrations/`
5. Si KO -> brief de correction renvoye au meme agent

## 10. VALIDATION UTILISATEUR

Avant kickoff : tu valides ce contrat ?
