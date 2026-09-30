# Nokido — Rapport de Session pour Gemini Ultra Web
*Généré le 2026-04-28 18:20*

---

## Vision : Nokido comme Tronc Cérébral

Nokido n'est pas un assistant — c'est un **hub multi-agents autopoïétique** inspiré de Maturana/Varela.
Claude et Gemini sont des **cerveaux périphériques** (workers). Nokido est le **routeur sémantique central**.

```
Claude Desktop ──STDIO──► bridge ──HTTP──► Hub Nokido :8766
                                               ↑          ↓
Gemini CLI OAuth ──────HTTP─────────────────────┘   SQLite WAL
                                               ↑          ↓  
daemon_poll ─────────────────────────────────────   RAG / FSM
```

---

## Architecture — Les Organes

| Organe | Module | Rôle biologique |
|--------|--------|-----------------|
| Cortex | forge_cognitive_router | Anticipation tools, inhibition |
| Cervelet | forge_spike_router | Réflexes SNN appris (CTF) |
| Moelle | forge_byte_router | Middleware intercepteur |
| Endocrine | forge_system_mood | energy/curiosity/fatigue/immune |
| Immunité | forge_mcp_security | CRITICAL_FILES, DangerGuard |
| Hippocampe | forge_rag_engine | Vectorisation, FTS, RAG |
| Yeux | SearXNG :8080 | Perception web (0 token) |
| Bouche | forge_biblio_worker | Ingestion → RAG |
| Mémoire | forge_conversation_logger | Épisodique → longterm |
| Veille | forge_watch_agent | Pipeline N8N 6 étapes |

---

## État de la Mémoire

- **RAG chunks** : 101,034 total
  - beir_fiqa: 57,638
  - beir_trec-covid: 10,000
  - beir_arguana: 8,674
  - beir_scifact: 5,183
  - code: 4,797
  - beir_nfcorpus: 3,633
  - nokido_code: 1,960
  - security: 1,874

- **Conversations** : 436 tours (shared_prompt_log transféré)
- **system_rules** : 50 règles (ring=0 prioritaires)
- **agent_messages** : 126 messages inter-agents
- **agent_chain_nodes** : 0 (schéma Gemini, table prête)

---

## Veille Active — Résultats

watch_jobs : {'completed': 10}
biblio_raw  : {'rejected': 4, 'unverified': 8}

**8 thèmes recherchés via SearXNG** :
- bioinformatics cybernetics biomimetic AI code
- autopoiesis software LLM agent memory 2024
- DEAP NEAT-python genetic algorithms evolution
- spiking neural network edge computing 2024
- crawl4ai docker LLM pipeline python
- autonomous agent communication protocol 2025
- DEAP evolutionary algorithm Python (Gemini)
- Lenia artificial life autopoiesis (Gemini)

---

## Architecture Communication Inter-Agents

### Canal Boîte aux Lettres (implémenté 2026-04-28)

```json
// MessageFrame — enveloppe normalisée
{
  "frame_id": "frm_abc123",
  "from_agent": "agt_claude",
  "to_agent": "agt_gemini",
  "action": "task",
  "parameters": {"theme": "autopoiesis LLM"},
  "tool_defs": [/* 8 tools Nokido injectés */],
  "status": "unread",
  "ttl_s": 300
}
```

**CQRS** : archive `agent_messages` (SQLite, persistant) ≠ inbox asyncio.Queue (volatile, réactif)
**SSE** : `GET /inbox/agt_gemini` — long-poll, réactivité ms

### Daemon gemini_poll_daemon.py

- Thread InboxSSE : connecté en permanence à `/inbox/agt_gemini`
- Réception instantanée → `deliver_to_mailbox()` → pas d'appel API externe
- Fallback : poll classique toutes les 30s

---

## Skills Gemini CLI (nouveaux)

Chargés depuis `~/.gemini/skills/` au démarrage :
- **laforge-hub** : accès tools MCP, boîte aux lettres, protocole
- **laforge-pipeline** : veille active, watch_jobs, biblio
- **laforge-autonomie** : règles délégation LLM vs Nokido (0 token)

---

## Principe de Délégation (économie de tokens)

**Nokido fait (0 token)** :
- Validation AST Python (`auto_test`)
- Recherche web SearXNG (`watch_agent`)
- SQL / RAG / fichiers
- Git, subprocess, monitoring

**LLM fait (tokens justifiés)** :
- Génération de code complexe
- Analyse sémantique
- Synthèse, décision architecturale

---

## Stack Technique

- **Backend** : Python asyncio (uvicorn/starlette)
- **Stockage** : SQLite WAL (≈100k chunks RAG)
- **Volatile** : asyncio.Queue (InboxRegistry)
- **Protocole** : MCP 2025 (JSON-RPC 2.0)
- **Auth** : Bearer token dérivé HMAC-SHA256 par agent
- **Bind** : 127.0.0.1 uniquement (pas d'exposition réseau)

---

## Prochaines Étapes

1. `forge_chain_executor.py` — exécuteur micro-agents chainables (agent_chain_nodes)
2. `forge_crawl_tool.py` + Docker Crawl4AI — extraction Markdown depuis URLs
3. `forge_agent_proxy.py` v3 — migration brokers vers factory pattern
4. Intégrer `forge_llm_transport.py` (Gemini) dans `forge_llm_router.py`
5. Reviewer les 8 biblio_raw unverified

---

*Ce rapport peut être partagé avec Gemini Web (gemini.google.com) pour donner le contexte complet du projet.*
