---
name: laforge-pipeline
description: Pipeline de veille active LaForge. Lancer, suivre et analyser les jobs de recherche SearXNG automatiques. Chaînage de micro-agents via agent_chain_nodes.
---

# LaForge Pipeline — Veille Active

## Lancer une veille

```python
# Via run action=python
from forge_watch_agent import create_job
job_id = create_job("mon thème de recherche", idea_id="ma_categorie")
print(job_id)
```

## Suivre les jobs

```
query "SELECT id, theme, step, status, n_ingested, n_stored FROM watch_jobs ORDER BY created_at DESC LIMIT 10"
```

## Pipeline (6 étapes, reprise automatique si interrompu)

1. `keywords` → LLM local (Ollama/Groq) génère 4 requêtes raffinées
2. `verify_kw` → LLM vérifie la pertinence  
3. `search` → SearXNG (port 8080, 0 token)
4. `refine` → LLM score pertinence 1-10
5. `ingest` → RAG vectorisation (≥4/10)
6. `store` → biblio_raw (≥6/10)

## Voir les résultats

```
query "SELECT title, url, status FROM biblio_raw ORDER BY created_at DESC LIMIT 20"
```

## MessageFrame — communication structurée

Tout message entre agents doit utiliser forge_message_frame.MessageFrame :
- `from_agent`, `to_agent`, `action`, `parameters`, `tool_defs`
- Les tool_defs sont injectées automatiquement par LaForge
