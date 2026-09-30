# Nokido MCP Hub — Vision projet pour LLM tiers

Date snapshot : 2026-04-27
Branche : alpha (15+ commits ahead origin/alpha)
Service NSSM Windows : LaForgeMCP RUNNING sous LocalSystem

## QU EST-CE QUE NOKIDO ?

Nokido est un **hub MCP (Model Context Protocol) souverain et multi-agents**
qui tourne en local sur la machine d un utilisateur (Windows 11 + miniforge3).

Il sert de **orchestrateur central** entre :
- L utilisateur (RING_0, autorite supreme)
- Plusieurs agents IA distants (Claude Desktop, Cline, Gemini CLI, Claude CLI)
- 24 providers LLM cloud (Mistral, Groq, GPT-4o GitHub Models, Cohere, Gemini,
  HF, OpenRouter, Perplexity, etc.) + 12 cascades de fallback
- Des modeles locaux (Ollama Qwen, llama.cpp, LM Studio, ONNX sur NPU AMD)
- Des outils metier (RAG vectoriel SQLite + FAISS + BM25, EventBus PULL,
  TUI Textual, CTF Exegol 175 outils, recon_silo Metasploit, ChainEngine)

## ARCHITECTURE EN 4 COUCHES

### Couche 1 : Hub HTTP MCP (port 8766)
- FastAPI + uvicorn, endpoint `/mcp` (JSON-RPC 2.0)
- 14 outils exposes : read, write, query, run, ask, hub, task, event, rag,
  research_agent, route_task, web_search, auto_test, trigger_autonomous_evolution
- Authentification HMAC + IntegrityRing (MASTER/SYSTEM/DEV/TRUSTED/COLLAB/UNTRUSTED)

### Couche 2 : Cerveau souverain
- Mode AUTO (cascade providers) | CLINE (code) | CHEF (orchestration) |
  DEBAT (multi-LLM contradictoire) | PING (heartbeat seul)
- 6 agents officiels : CLAUDE, GEMINI, ROO, USER, CLINE, CHEF
- forge_cognitive_router decide du provider selon la complexite + cout
- Token Bucket rate limit : 100/min agents, 300/min systeme

### Couche 3 : Memoire & connaissance
- DB SQLite WAL mode (RAG/embeddings.db, 4.5 GB, 60 tables)
- RAG vectoriel : rag_chunks (embeddings) + rag_fts (FTS5) + FAISS index
- EventBus mode PULL (publish + history, pas subscribe) sur 100 topics buffer
- ClawHub marketplace : 627 skills disponibles
- Chronique : forge_versioning (staging zone + cold_backup + GFS rotation 10/hebdo/mensuel)
- Janitor : forge_rag_janitor (clean_orphans + purge_old_logs)

### Couche 4 : Securite & evolution
- Engrid v3 layers (sandbox isolation)
- IntegrityRing (Cerberus guard, PolicyEnforcer)
- NoiseGuardian + TrustBroker (anti prompt injection)
- evolutionary_engine + shadow_mutation vault (mutations testees avant adoption)
- forge_swarm state machine pour auto-modifications du code

## CONVENTIONS DE CODE NOKIDO

- Python 3.11 + miniforge3
- Modules en `app/forge_*.py` (snake_case)
- Logger : `logging.getLogger("Nokido.<Domain>.<Module>")`
- DB access : sqlite3 stdlib (pas SQLAlchemy)
- Config : `.env` LOCAL + Windows Credential Manager (WCM) keyring
- Encoding fichiers : UTF-8 sans BOM
- Pas d emojis dans le code (compatibilite Windows console)
- Pas de print() dans production : logger uniquement
- Patterns reutilises systematiquement :
  * forge_versioning.staging zone + lock + checkpoint + rollback
  * forge_rag_janitor.clean_orphans + purge_old_logs
  * forge_state_manager.EventBus.publish + history (mode PULL)

## SPRINTS EN COURS

### Sprint Q5 (memoire long-terme)
- Schema lessons (9 types : politique, securite, axe, bonne_pratique, garde_fou,
  design, habitude, anti_pattern, bug_resolu)
- Hash chain SHA-256 sur RFC 8785 (JSON canonical)
- Workflow draft -> validated par RING_0
- Estimation : 22h (en attente kickoff)

### Sprint Bibliography Worker (EN COURS)
Phase Alpha (16.5h) : MVP utilisable seul
- Extracteur Mistral pour parser citations dans textes colles
- Worker Python (pas NSSM en alpha) qui poll biblio_raw et lance SearXNG
- 3 canaux d invocation : Tool MCP, EventBus PULL, CLI shell
- Sanitization : DOI/arxiv/ISBN regex + URL whitelist + OWASP LLM01 patterns
- Hash chain MD5 hex 32 chars (SHA-256 reporte beta)
- Pattern DRY : forge_biblio_core.py partage entre canaux

Phase Beta (17h) : Robustesse production
- Beall list cron quotidien (predatory journals)
- Retracted papers detection (Crossref API)
- Detection langue lingua-py
- Score confiance composite 0-100 (rejet si < 70)
- Rate limiting budget global par engine SearXNG
- Bunker shadow_libs (annas archive + library genesis isoles, JAMAIS dans rag_chunks)

Phase Gamma (10h) : Lifecycle complet
- Purge orphan sur event idea.refined
- TUI commands @biblio purge/pin/promote
- Tests integration

## CONTRAINTES OPERATIONNELLES IMPORTANTES

1. **Pas de TTL fixe** sur biblio_raw : purge declenchee par raffinement d idee
2. **EventBus en mode PULL** : workers DOIVENT poll, pas subscribe (latence 5s OK)
3. **Buffer MCP < 4kb** : si write tool depasse, bypass via Python direct
4. **Mistral pour extraction** (Gemini Flash free = 20 RPD insuffisant)
5. **Multi-LLM par sous-tache** : Mistral=extract precis, Groq=affine rapide,
   Qwen local=tri binaire, GPT-4o GitHub=DBA/synthese long
6. **NSSM packaging** reporte en beta (alpha = script Python lance manuellement)
7. **Triangulation systematique** : avant kickoff sprint, audit par 3 LLM distincts
   avec roles distincts (challenger / pragmatist / SRE risk-spotter)
8. **Code-vectoriel banni sans validation** : prose va en RAG, code/git/metadata
   reste en SQL/FTS

## QUOTAS PROVIDERS (snapshot 28 jours)

| Provider              | Quota free                  | Cas d usage worker biblio              |
|-----------------------|-----------------------------|----------------------------------------|
| Mistral Large         | Payant (~$2/1M tokens)      | Extraction precise JSON strict mode    |
| Groq Llama 3.3 70B    | 14400/jour quasi illimite   | Affinage rapide, multilingue           |
| GPT-4o GitHub Models  | Gratuit illimite (Copilot)  | Synthese longue, audit DBA             |
| Gemini 2.5 Flash      | 20 reqs/jour seulement      | EVITER pour worker auto                |
| Gemini 3 Pro / 3 Flash| Quota 0/0 (tier payant)     | Pas accessible free tier               |
| Cohere command-a      | Free tier OK                | Reserve                                |
| Ollama Qwen local     | Zero-token unlimited        | Taches binaires simples                |
| Claude Opus (moi)     | API Anthropic               | Orchestrateur, integration finale      |

## DELEGATION PARALLELE - PATTERN UTILISE

Pour Sprint Alpha biblio worker :
- 3 agents externes en parallele (subprocess detache, gain ~50% temps mur)
- Contrat d interface ecrit AVANT delegation (signatures Python + schema SQL)
- AST check + tests unitaires execution apres chaque livrable
- Verification de moi (Claude Opus) sur conformite contrat
- Si tests buggues -> fix manuel (constat : LLM tiers livrent code OK mais
  tests souvent buggues sur les expected)
- Subprocess detached parfois mute (Mistral notamment) -> fallback synchrone

## CHEMINS IMPORTANTS

- Racine : `~\Script python IA\Nokido`
- DB principale : `RAG/embeddings.db` (WAL mode)
- Modules : `app/forge_*.py`
- Migrations : `migrations/00X_*.sql`
- Tests : `tests/<domain>/test_*.py`
- Sandbox audit : `sandbox/_audit_round/`
- Sandbox parallel : `sandbox/biblio_alpha_parallel/<agent>/`
- Logs : `logs/nokido.log` + `logs/system.log`

## ETAT D AVANCEMENT SPRINT BIBLIOGRAPHY ALPHA

### LIVRES ET VALIDES :
- Pre-alpha0 : test deps via runner Mistral OK, tests SearXNG empiriques OK
- alpha1 (GPT-4o) : schema SQL + apply_migration.py, 3 tables + 5 index, idempotent
- alpha2 (Claude+Mistral) : forge_biblio_core.py + forge_biblio_schema.py
  - extract_from_text via Mistral JSON strict mode (3 sources OK 5.1s)
  - _compute_payload_hash MD5 reproductible
  - insert_biblio_raw avec validation pydantic + sanitization + hash chain
  - 7 cas integration end-to-end PASS (3 OK + 4 rejets attendus)
- alpha4 (Groq) : forge_biblio_refine.py + 10/10 tests PASS
- alpha5 (Mistral) : forge_biblio_sanitizer.py + 10/10 tests PASS

### EN COURS :
- alpha3 : worker loop Python (poll biblio_raw queued, search SearXNG, update)
- alpha6a : Tool MCP `Nokido:biblio` (5 actions)
- alpha6b : CLI tools/biblio_cli.py

## QUE FAIRE QUAND TU ES UN LLM TIER CONSULTE

Si on te consulte pour Nokido :
1. **Lis cette vision pour le contexte**
2. **Demande TOUJOURS le contrat d interface** (signatures Python + schema SQL)
3. **Reponds par des blocs de code delimites** (pas de prose entre les blocs)
4. **Tests inclus dans le livrable** (unittest stdlib, pas pytest)
5. **Stdlib only** sauf si lib explicitement autorisee dans le contrat
6. **AST OK obligatoire** (py_compile -> 0 erreur)
7. **Documente edge cases** : None vs absent, vide vs absent, erreurs reseau
8. **Pas de print()** : logger uniquement
9. **Pas d emojis** dans le code
10. **Si tu doutes d une dependance** : demande, ne suppose pas

## CRITIQUES DEJA RECUES SUR L ARCHITECTURE

1. EventBus PULL = anti-pattern (Mistral) - mais c est l existant, refactor PUSH
   reporte sprint distinct
2. Hash chain SHA-256+RFC8785 = sur-ingenierie en alpha (Mistral) - donc MD5 en alpha
3. State machine 11 transitions over-engineered (Mistral) - reduit a 8
4. NSSM en alpha trop complexe (Groq) - reporte en beta, script Python en alpha
5. TUI Textual remplaceable par Tool MCP (3 canaux) (utilisateur) - adopte

## CE QUI N EST PAS DANS SCOPE

- Refactor EventBus PUSH (Redis ou callback) - sprint futur
- TUI Textual interactive - reportee beta
- NSSM packaging - reporte beta
- HTTP API direct sur hub /biblio/search - reporte beta
- Auto-detection [BIBLIO?] markers - reporte gamma
- 11 transitions complete state machine - reportee beta
- Gemini API pour worker (quota 20 RPD insuffisant)
- Modeles preview Gemini 3 Pro / 3.1 Pro (tier 1+ requis)
