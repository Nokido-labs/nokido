# Sprint Alpha Bibliography Worker - V4 (FINAL avant kickoff)

Date : 2026-04-27
Status : DEFINITIF - integre quotas Gemini reels + multi-canaux d invocation

## Changements V3 -> V4

### Decouvertes nouvelles (data Gemini reelle)
- Gemini 2.5 Flash free tier = **20 reqs/jour seulement**
- Tu as deja depasse cette semaine : 25 reqs / 20 RPD
- Gemini 2.5 Pro = **0/0 quota** (tier payant uniquement)
- Gemini 3 Pro = **0/0 quota** (preview, tier 1+ requis)
=> Mistral Large reste le bon choix pour extraction (deja decide V3)

### Multi-canaux d invocation (nouveau besoin)
La recherche biblio doit etre appelable EN DEHORS de la TUI.

3 canaux complementaires :
- Canal 1 (obligatoire) : Tool MCP `Nokido:biblio`
  Permet appel depuis Claude Desktop, Cline, autres clients MCP
- Canal 2 (deja prevu α2) : EventBus topics `biblio.*`
  Trigger asynchrone par n importe quel agent Nokido
- Canal 3 (optionnel) : CLI `tools/biblio_cli.py`
  Pour scripts cron / shell externe

## Architecture finale

```
                  CANAUX D INVOCATION
                  +----------------------------------------+
                  | 1. Tool MCP Nokido:biblio             |
                  |    actions=search|list|promote|reject  |
                  |                                        |
                  | 2. EventBus topics                     |
                  |    biblio.text_pasted                  |
                  |    biblio.search.requested             |
                  |    biblio.entry.promoted               |
                  |                                        |
                  | 3. CLI tools/biblio_cli.py             |
                  |    Commandes shell directes            |
                  +----------------+-----------------------+
                                   | Tous appellent
                                   v
                  +----------------------------------------+
                  | CORE forge_biblio_core.py              |
                  | Fonctions :                            |
                  |  - extract_from_text(text, idea_id)    |
                  |  - search_for_entry(entry_id)          |
                  |  - promote_entry(entry_id, reviewer)   |
                  |  - reject_entry(entry_id, reason)      |
                  |  - list_entries(status_filter)         |
                  |  - pin_entry(entry_id, pinned)         |
                  +----------------+-----------------------+
                                   | utilise
                                   v
                  +----------------------------------------+
                  | WORKER LOOP (script Python en α)       |
                  | forge_biblio_worker.py                 |
                  | Poll biblio_raw status=queued          |
                  |  -> SearXNG -> UPDATE entry            |
                  +----------------------------------------+
```

## Sous-taches V4

### Pre-α0 (2h) - VALIDATION DEPENDANCES + RESILIENCE

Livrables : `tests/biblio/test_alpha0_deps.py` avec 7 tests :
1. SearXNG /healthz + /search engines arxiv,crossref -> >0 results
2. SearXNG resilience : Docker SearXNG down -> erreur propre, pas crash
3. Mistral provider : prompt JSON strict -> parse OK
4. Mistral resilience : timeout, retry, fallback Groq
5. EventBus.publish + history fonctionnent (mode PULL)
6. SQLite WAL mode actif sur embeddings.db
7. Test concurrence : 2 process ecrivent simultanement biblio_raw -> pas corruption

Critere fini : 7/7 tests PASS, rapport timestamps + latences

### α1 (2h) - Schema DB minimal

Livrables : `migrations/004_biblio_alpha.sql` + `tools/apply_migration.py`

Tables : ideas, biblio_raw, bibliography (3 tables)
Index minimaux : status, idea_id, doi, promoted_from, parent_idea (5 index)
Hash : MD5 hex 32 chars (pas SHA-256+RFC8785, reporte beta)
State machine simplifiee : 8 transitions au lieu de 11

Critere fini :
- 3 tables creees, 5 index actifs
- AST OK
- Test : INSERT ideas + INSERT biblio_raw + INSERT bibliography sans erreur

### α2 (5h) - CORE module + Hook EventBus extracteur

Livrables :
- `app/forge_biblio_core.py` (logique partagee tous canaux)
- Fonction `extract_from_text(text, idea_id) -> list[dict]`
- Hook EventBus PULL : poll topic `biblio.text_pasted` toutes les 5s
- Contrat JSON validate (pydantic schema entry)
- INSERT biblio_raw avec MD5 hash + sanitization status

Critere fini :
- Test : passer texte avec 3 citations -> 3 lignes biblio_raw inserees
- Schema pydantic valide chaque entry (rejet si invalide)
- Hash MD5 recalculable

### α3 (2h) - Worker loop script Python

Livrables : `app/forge_biblio_worker.py`
PAS de NSSM en α (script lance manuellement pour iteration)

Boucle :
```
while not stop_signal:
    entry = SELECT * FROM biblio_raw WHERE status=queued LIMIT 1
    if not entry: sleep 5; continue
    UPDATE status=searching
    query = refine_query(entry)
    results = searxng_search(query, engines=arxiv,crossref,openalex)
    if results: UPDATE status=reviewed, search_results_json=...
    else: UPDATE status=rejected, rejection_reason=no_results
    sleep 3  # politesse SearXNG
```

Critere fini :
- Lance manuellement : `python -m app.forge_biblio_worker`
- 5 entries queued -> reviewed/rejected en 30s
- Logs format strict, ZERO error/critical

### α4 (2h) - Affineur requete templating

Livrables : fonction `refine_query(entry) -> str` dans `forge_biblio_core.py`

Pas de LLM. Templating pur :
- 6 premiers mots significatifs du title (skip stopwords EN+FR)
- + first author lastname
- + year
- Cap 100 chars

Critere fini : 10 entries -> 10 queries valides, longueur OK

### α5 (2h) - Sanitization basique

Livrables : `app/forge_biblio_sanitizer.py`
- validate_doi/arxiv_id/isbn(s) -> bool
- is_url_whitelisted(url) -> bool
- sanitize_content(text) -> tuple[bool, reason]
- sanitize_entry(entry) -> tuple[bool, reason]

10 cas tests dans `tests/biblio/test_sanitizer.py`

Critere fini : 10/10 cas bien classifies

### α6 (1.5h) - 2 canaux d invocation

Livrable α6a (1h) : Tool MCP `Nokido:biblio`
Ajout dans `app/forge_mcp_registry.py` :

```python
async def handle_biblio(self, args, agent, ring):
    action = args.get("action", "list")
    if action == "search":  return await self.handle_biblio_search(...)
    if action == "list":    return await self.handle_biblio_list(...)
    if action == "promote": return await self.handle_biblio_promote(...)
    if action == "reject":  return await self.handle_biblio_reject(...)
    if action == "pin":     return await self.handle_biblio_pin(...)
    return f"biblio: action inconnue {action}"
```

Toutes les actions delegueent a `forge_biblio_core.py`.

Livrable α6b (0.5h) : CLI `tools/biblio_cli.py`

```bash
python tools/biblio_cli.py search "ReAct paper Yao 2022"
python tools/biblio_cli.py list --status=reviewed
python tools/biblio_cli.py promote <entry_id>
python tools/biblio_cli.py reject <entry_id> --reason=duplicate
```

CLI minimal : argparse + appel direct des fonctions `forge_biblio_core.py`.

Critere fini α6 :
- Tool MCP `Nokido:biblio action=list` retourne JSON formate
- CLI affiche output rich/tabulate
- Les 5 actions (search, list, promote, reject, pin) marchent par les 2 canaux

## Effort total V4

| Sous-tache | V3   | V4   | Delta                                       |
|------------|------|------|---------------------------------------------|
| pre-α0     | 2h   | 2h   | inchange                                    |
| α1         | 2h   | 2h   | inchange                                    |
| α2         | 5h   | 5h   | inchange (extraction core)                  |
| α3         | 2h   | 2h   | inchange (script Python)                    |
| α4         | 2h   | 2h   | inchange                                    |
| α5         | 2h   | 2h   | inchange                                    |
| α6         | 1.5h | 1.5h | INCHANGE en duree, mais TUI -> MCP+CLI     |
| **TOTAL**  | **16.5h** | **16.5h** | 0h                                |

Pas de gonflement : la modif α6 (TUI -> MCP+CLI) tient dans la meme enveloppe
horaire car la logique est dans `forge_biblio_core.py` partage.

## Backlog beta (reporte)

- TUI command @biblio (Textual interactive)
- NSSM packaging du worker
- Hash chain SHA-256 + RFC 8785
- Politique retention biblio_raw
- Heartbeat NSSM <-> LaForgeMCP
- EventBus PUSH refactor
- 11 transitions complete state machine
- HTTP API direct sur hub /biblio/search
- Auto-detection [BIBLIO?] markers dans messages

## Quotas providers - decision matrix

| Provider              | Quota free                  | Cas d usage worker biblio              |
|-----------------------|-----------------------------|----------------------------------------|
| Mistral Large         | Payant illimite (~$2/1M tok)| **Extraction sources** (PRIMAIRE α)    |
| Groq Llama 3.3 70B    | 14400/jour quasi illimite   | Affinage requetes, tri resultats       |
| GPT-4o GitHub Models  | Gratuit illimite (Copilot)  | Synthese longue, fallback Mistral      |
| Gemini 2.5 Flash      | **20 reqs/jour seulement**  | EVITER pour worker auto                |
| Gemini 2.5 Flash Lite | 20 RPD seulement            | EVITER pour worker auto                |
| Ollama Qwen local     | Zero-token                  | Taches binaires simples (futur)        |

## Decisions actees V4

1. 3 canaux d invocation au lieu de TUI seule :
   - Tool MCP `Nokido:biblio` (PRIMAIRE)
   - EventBus topics (deja existe)
   - CLI shell `tools/biblio_cli.py` (BONUS)
2. Pattern DRY : `forge_biblio_core.py` = logique partagee
3. Mistral Large pour extraction (Gemini Flash free = 20 RPD insuffisant)
4. TUI Textual reportee en beta
5. NSSM reporte en beta (script Python en α)
6. Hash MD5 en α, SHA-256 en β
7. Effort 16.5h total

## Validation finale avant kickoff

Tu valides :
1. **3 canaux d invocation** (Tool MCP + EventBus + CLI) au lieu de TUI seule en α ?
2. **Effort 16.5h** maintenu (pas de gonflement) ?
3. **Pattern forge_biblio_core.py** comme module partage entre canaux ?
4. **Demarrage par pre-α0** (2h validation deps + resilience) ?
